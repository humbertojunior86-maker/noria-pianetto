"""O núcleo. Interpreta, planeja, despacha, valida, replaneja e conclui.

O ciclo roda sem modelo de linguagem: o planejador é uma tabela de padrões que
liga objetivo a agente, e a validação é código. O adaptador de modelo, quando
existir, entra apenas para redigir texto — nunca para decidir se algo passou.
"""
from __future__ import annotations

import json
import re

from agentes import registro as ar
from ferramentas import base as fb

from . import bd, estados, limites, validacao


# ===========================================================================
# 1. Interpretação — objetivo em texto vira intenção verificável
# ===========================================================================

# Missões abertas pelo agendador e pela sentinela já sabem qual agente querem.
# Confiar no regex nesse caso seria trocar uma certeza por uma adivinhação:
# "duplicidade de pagamento" bate em `pagar`, que ia parar no agente errado.
POR_AGENTE = {
    "contas.pagar": [
        ("contagem_confere", {"chave": "grupos"}),
        ("toda_afirmacao_tem_evidencia", {})],
    "comercial.faturamento": [
        ("contagem_confere", {"chave": "quantidade"}),
        ("toda_afirmacao_tem_evidencia", {})],
    "comercial.inteligencia": [
        ("contagem_confere", {"chave": "quantidade"}),
        ("toda_afirmacao_tem_evidencia", {})],
    "controladoria.margem": [
        ("toda_afirmacao_tem_evidencia", {})],
    "controladoria.lucratividade": [
        ("toda_afirmacao_tem_evidencia", {})],
    "frota.resultado": [
        ("contagem_confere", {"chave": "tratores",
                              "onde": {"id_tracao": True}}),
        ("toda_afirmacao_tem_evidencia", {})],
    "fiscal.documento": [
        ("contagem_confere", {"chave": "pendentes_abertos",
                              "onde": {"linha": "pendente"}}),
        ("toda_afirmacao_tem_evidencia", {})],
    "cobranca.carteira": [
        ("soma_confere", {"campo": "vl_saldo", "chave": "total"}),
        ("contagem_confere", {"chave": "quantidade"}),
        ("toda_afirmacao_tem_evidencia", {}), ("artefato_existe", {})],
}

# Fallback para objetivo digitado por gente. Vem ANTES dos padrões genéricos
# porque "duplicidade de pagamento" contém "pagar".
PADROES_NOVOS = [
    (r"lucratividad|por setor|resultado do setor|setor da frota|"
     r"ag[eê]ncia|agenciamento|frota contra terceiro", "controladoria.lucratividade"),
    (r"duplicidad|pago em dobro|pagamento duplicad", "contas.pagar"),
    (r"sem t[ií]tulo|n[aã]o faturad|frete n[aã]o cobrad|cte sem", "comercial.faturamento"),
    (r"cliente que sumiu|cliente parou|perda de cliente|queda de cliente", "comercial.inteligencia"),
    (r"margem|rentabilidad|resultado por cte", "controladoria.margem"),
    (r"ve[ií]culo|placa|frota|cavalo|carreta", "frota.resultado"),
    (r"cte pendent|sefaz|denegad|rejeitad|n[aã]o transmitid", "fiscal.documento"),
]

# ---------------------------------------------------------------- contraprova
# Quem contesta quem, e por qual caminho. A regra é uma só: o auditor NÃO pode
# repetir a consulta do apurador. Ele tem que chegar ao mesmo fato por outra
# porta do banco — outra tabela, outra chave — para poder discordar de verdade.
# Repetir a mesma consulta e obter o mesmo número não confirma nada.
CONTRAPROVA: dict[str, list[dict]] = {
    "comercial.faturamento": [{
        "agente": "fiscal.documento",
        "pergunta": "os CT-es sem título estão mesmo autorizados na SEFAZ? "
                    "documento cancelado ou nunca transmitido não tem título "
                    "por estar certo, e não pode entrar como receita perdida"}],
    "fiscal.documento": [{
        "agente": "comercial.faturamento",
        "pergunta": "algum documento sem autorização da SEFAZ já foi faturado? "
                    "cobrar por documento que não existe legalmente é pior, e é "
                    "outro problema"}],
    "contas.pagar": [{
        "agente": "auditoria.interna",
        "pergunta": "os títulos de cada grupo vêm do mesmo documento fiscal ou "
                    "de compras diferentes? duas notas distintas de mesmo valor "
                    "são duas compras reais, não pagamento em dobro"}],
    "controladoria.lucratividade": [{
        "agente": "controladoria.margem",
        "pergunta": "o custo da frota fecha por outro caminho do banco? se o "
                    "centro de custo mostrar despesa que o caixa do veículo "
                    "não mostra, a margem da frota está apoiada em custo "
                    "incompleto e sai alta por construção"}],
    # Caio tem duas frentes e cada uma pede um contestador diferente. O campo
    # "foco" liga a contraprova ao recorte que está sendo apurado: perguntar
    # sobre carta frete numa apuração por placa seria contestar outra coisa.
    "controladoria.margem": [{
        "agente": "frota.resultado", "foco": "",
        "pergunta": "quantos CT-es de margem negativa são de frota própria? "
                    "nesses a carta frete é transferência interna, não custo, "
                    "e a margem negativa pode ser artefato de cálculo"},
        {
        "agente": "controladoria.lucratividade", "foco": "veiculo",
        "pergunta": "as placas apontadas como negativas continuam negativas "
                    "com o dobro da janela? veículo que ficou dois meses em "
                    "oficina, ou que recebeu a nota do motor de uma vez, "
                    "aparece igual a veículo estruturalmente ruim em 90 dias — "
                    "e a decisão que cada um pede é oposta"}],
}


def _foco(entradas: dict) -> str:
    """Recorte declarado na tarefa. Vazio quando não há recorte."""
    v = str(entradas.get("foco") or "").lower()
    return "veiculo" if v in ("veiculo", "veiculos", "placa") else ""


PADROES = [
    # (regex, agente, montador de entradas, critérios objetivos)
    (r"concilia|extrato|ofx|banco|caixa", "tesouraria.conciliador",
     "_entradas_conciliacao",
     [("conciliacao_fecha", {}), ("periodo_coberto", {}),
      ("sem_duplicidade", {"campos": ["cd_conciliado"]}),
      ("toda_afirmacao_tem_evidencia", {}), ("artefato_existe", {})]),
    (r"vencid|inadimpl|cobran|receber|carteira", "cobranca.carteira",
     "_entradas_carteira",
     [("soma_confere", {"campo": "vl_saldo", "chave": "total"}),
      ("contagem_confere", {"chave": "quantidade"}),
      ("toda_afirmacao_tem_evidencia", {}), ("artefato_existe", {})]),
    (r"pagar|fornecedor|despesa", "cobranca.carteira", "_entradas_pagar",
     [("soma_confere", {"campo": "vl_saldo", "chave": "total"}),
      ("contagem_confere", {"chave": "quantidade"}),
      ("toda_afirmacao_tem_evidencia", {}), ("artefato_existe", {})]),
]


def _entradas_conciliacao(objetivo: str, contexto: dict) -> dict:
    e = {"cd_conta": contexto.get("cd_conta"), "data": contexto.get("data")}
    if not e["data"]:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", objetivo)
        if m:
            e["data"] = m.group(1)
        else:
            # O objetivo é escrito para gente ler: 04/09/2026.
            m = re.search(r"(\d{2})/(\d{2})/(\d{4})", objetivo)
            if m:
                e["data"] = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.search(r"conta\s+(\d+)", objetivo, re.I)
    if m and not e["cd_conta"]:
        e["cd_conta"] = int(m.group(1))
    return e


def _lado(objetivo: str, contexto: dict, padrao: int) -> int:
    """O contexto manda. Só quando ele não diz é que se lê o texto.

    Inverter isto já custou uma missão de contas a pagar que virou
    contas a receber sem ninguém perceber.
    """
    if contexto.get("id_tipo") in (1, 2, "1", "2"):
        return int(contexto["id_tipo"])
    if re.search(r"\ba\s+pagar\b|fornecedor", objetivo, re.I):
        return 2
    if re.search(r"\ba\s+receber\b|cliente|cobran", objetivo, re.I):
        return 1
    return padrao


def _entradas_carteira(objetivo: str, contexto: dict) -> dict:
    m = re.search(r"(\d+)\s*dias", objetivo, re.I)
    return {"id_tipo": _lado(objetivo, contexto, 1),
            "dias": int(m.group(1)) if m else int(contexto.get("dias", 90))}


def _entradas_pagar(objetivo: str, contexto: dict) -> dict:
    d = _entradas_carteira(objetivo, contexto)
    d["id_tipo"] = _lado(objetivo, contexto, 2)
    return d


_MONTADORES = {"_entradas_conciliacao": _entradas_conciliacao,
               "_entradas_carteira": _entradas_carteira,
               "_entradas_pagar": _entradas_pagar}


def interpretar(objetivo: str, contexto: dict) -> dict | None:
    """Devolve a intenção reconhecida, ou None quando não sabe fazer.

    Não sabe fazer é uma resposta legítima. É melhor que inventar um plano.
    """
    alvo = objetivo.lower()

    # Quem abriu a missão pode dizer de quem ela é. Isso vale mais que texto.
    pedido = (contexto or {}).get("agente_id")
    if pedido and pedido in POR_AGENTE:
        return {"agente_id": pedido,
                "entradas": {k: v for k, v in (contexto or {}).items()
                             if k not in ("agente_id", "chave")},
                "criterios": POR_AGENTE[pedido]}

    for rx, agente_id in PADROES_NOVOS:
        if re.search(rx, alvo):
            return {"agente_id": agente_id,
                    "entradas": {k: v for k, v in (contexto or {}).items()
                                 if k not in ("agente_id", "chave")},
                    "criterios": POR_AGENTE[agente_id]}

    for rx, agente_id, montador, criterios in PADROES:
        if re.search(rx, alvo):
            return {"agente_id": agente_id,
                    "entradas": _MONTADORES[montador](objetivo, contexto),
                    "criterios": criterios}
    return None


# ===========================================================================
# 2. Planejamento
# ===========================================================================
def abrir_missao(empresa_id: int, objetivo: str, *, contexto: dict | None = None,
                 origem: str = "humano", solicitante: int | None = None,
                 area: str | None = None, prioridade: str = "normal",
                 prazo: str | None = None) -> int:
    ctx = contexto or {}
    mid = bd.inserir("missao", {
        "empresa_id": empresa_id, "objetivo": objetivo,
        "contexto": bd.j(ctx), "area": area, "prioridade": prioridade,
        "prazo": prazo, "restricoes": bd.j({}), "origem": origem,
        "solicitante": solicitante, "estado": "rascunho",
        "criada_em": bd.agora(), "atualizada_em": bd.agora()})
    bd.evento(empresa_id, "missao.aberta", objetivo, missao_id=mid,
              ator=f"usuario:{solicitante}" if solicitante else origem)
    return mid


def planejar(missao_id: int, *, motivo: str = "plano inicial") -> dict:
    m = bd.linha("SELECT * FROM missao WHERE id=?", (missao_id,))
    emp = m["empresa_id"]
    ctx = bd.dj(m["contexto"], {}) or {}

    intencao = interpretar(m["objetivo"], ctx)
    if intencao is None:
        estados.mover_missao(missao_id, "bloqueada",
                             motivo="objetivo fora do repertório atual da NÓRIA")
        bd.evento(emp, "missao.sem_repertorio",
                  "Não há agente habilitado para este objetivo. "
                  "A missão fica registrada e aguarda um executor.",
                  missao_id=missao_id)
        return {"ok": False, "motivo": "sem_repertorio"}

    d = ar.obter(intencao["agente_id"])
    sit, lim = d.situacao()
    if sit != "habilitado":
        estados.mover_missao(missao_id, "bloqueada",
                             motivo=f"agente {d.nome} indisponível: {lim}")
        return {"ok": False, "motivo": "agente_indisponivel", "limitacao": lim}

    ver = bd.linha("SELECT MAX(versao) v FROM plano WHERE missao_id=?",
                   (missao_id,))["v"] or 0
    plano_id = bd.inserir("plano", {
        "missao_id": missao_id, "versao": ver + 1, "motivo": motivo,
        "estrategia": "agente_unico", "criado_em": bd.agora()})

    # tarefas do plano anterior que ainda não terminaram são substituídas
    for t in bd.linhas(
            "SELECT id FROM tarefa WHERE missao_id=? AND estado IN "
            "('pendente','reprovada','nao_verificavel','falha')", (missao_id,)):
        estados.mover_tarefa(t["id"], "substituida",
                             motivo=f"substituída pelo plano v{ver + 1}")

    chave_ap = f"{d.id}#1"
    tid = bd.inserir("tarefa", {
        "empresa_id": emp, "missao_id": missao_id, "plano_id": plano_id,
        "chave": chave_ap, "titulo": f"{d.papel}: {m['objetivo'][:80]}",
        "objetivo": m["objetivo"], "agente_id": d.id, "agente_versao": d.versao,
        "entradas": bd.j(intencao["entradas"]), "fontes": bd.j(d.ferramentas),
        "acoes_permitidas": bd.j(d.acoes), "formato_entrega": "json+md",
        "saidas_esperadas": bd.j(
            d.saidas_foco.get(_foco(intencao["entradas"]), d.saidas)),
        "prazo": m["prazo"], "orcamento_centavos":
            int(d.limites.get("custo_centavos", 0)),
        "max_tentativas": 2, "tentativas": 0, "estado": "pendente",
        "criada_em": bd.agora(), "atualizada_em": bd.agora()})

    bd.executar("DELETE FROM criterio WHERE missao_id=? AND aferido_em IS NULL",
                (missao_id,))
    for i, (nome, params) in enumerate(intencao["criterios"], 1):
        p = dict(params)
        if nome == "periodo_coberto":
            data = intencao["entradas"].get("data")
            p.setdefault("de", data)
            p.setdefault("ate", data)
        bd.inserir("criterio", {
            "missao_id": missao_id, "tarefa_chave": chave_ap, "ordem": i,
            "descricao": f"verificador {nome}", "camada": "objetiva",
            "verificador": nome, "parametros": bd.j(p), "obrigatorio": 1})

    aud_ids = _plantar_contraprovas(m, d, plano_id, tid, chave_ap,
                                    intencao["entradas"])

    bd.atualizar("missao", missao_id,
                 {"plano_vigente": plano_id, "atualizada_em": bd.agora()})
    if m["estado"] in ("rascunho",):
        estados.mover_missao(missao_id, "planejada", motivo=motivo)
    quantos = 1 + len(aud_ids)
    bd.evento(emp, "plano.criado",
              f"Plano v{ver + 1}: {d.nome} ({d.papel}) apura" +
              (f", e {len(aud_ids)} contraprova(s) conferem por outro caminho"
               if aud_ids else ", sem par habilitado para contestar") +
              f" — {motivo}",
              missao_id=missao_id, dados={"tarefas": quantos})
    return {"ok": True, "plano_id": plano_id, "tarefa_id": tid,
            "contraprovas": aud_ids}


def _plantar_contraprovas(m: dict, d, plano_id: int, tid: int,
                          chave_ap: str, entradas: dict) -> list[int]:
    """Cria as tarefas que vão contestar a apuração.

    A contraprova recebe as MESMAS entradas do apurador. Se ela olhasse outra
    janela de dias ou outra filial, discordar não significaria nada: seriam
    dois universos diferentes, não duas leituras do mesmo.
    """
    emp, missao_id = m["empresa_id"], m["id"]
    criados: list[int] = []
    for i, cp in enumerate(CONTRAPROVA.get(d.id, []), 1):
        if "foco" in cp and cp["foco"] != _foco(entradas):
            continue
        rev = ar.obter(cp["agente"])
        if rev is None or rev.auditor is None:
            bd.evento(emp, "contraprova.sem_par",
                      f"{d.nome} apurou sem contraprova: {cp['agente']} não tem "
                      f"auditor implementado.", missao_id=missao_id)
            continue
        chave_cp = f"{rev.id}#c{i}"
        cid = bd.inserir("tarefa", {
            "empresa_id": emp, "missao_id": missao_id, "plano_id": plano_id,
            "chave": chave_cp,
            "titulo": f"contraprova de {d.nome}: {cp['pergunta'][:70]}",
            "objetivo": cp["pergunta"], "agente_id": rev.id,
            "agente_versao": rev.versao,
            "entradas": bd.j({**entradas, "papel": "contraprova",
                              "auditar_tarefa": tid,
                              "pergunta": cp["pergunta"]}),
            "fontes": bd.j(rev.ferramentas),
            "acoes_permitidas": bd.j(rev.acoes), "formato_entrega": "json+md",
            "saidas_esperadas": bd.j({"veredito": "confirma|contradiz"}),
            "prazo": m["prazo"],
            "orcamento_centavos": int(rev.limites.get("custo_centavos", 0)),
            # Contraprova não repete: se falhou, falhou. Insistir até concordar
            # é o oposto de auditar.
            "max_tentativas": 1, "tentativas": 0, "estado": "pendente",
            "criada_em": bd.agora(), "atualizada_em": bd.agora()})
        bd.inserir("dependencia",
                   {"tarefa_id": cid, "depende_de": tid, "tipo": "dado"})
        bd.inserir("criterio", {
            "missao_id": missao_id, "tarefa_chave": chave_cp, "ordem": 1,
            "descricao": "verificador toda_afirmacao_tem_evidencia",
            "camada": "objetiva",
            "verificador": "toda_afirmacao_tem_evidencia",
            "parametros": bd.j({}), "obrigatorio": 1})
        criados.append(cid)
    return criados


# ===========================================================================
# 3. Despacho e execução
# ===========================================================================
def _pronta(t: dict) -> bool:
    dep = bd.linhas(
        "SELECT d.depende_de, x.estado FROM dependencia d "
        "JOIN tarefa x ON x.id = d.depende_de WHERE d.tarefa_id=?", (t["id"],))
    return all(d["estado"] == "aprovada" for d in dep)


def proxima_tarefa(missao_id: int) -> dict | None:
    for t in bd.linhas(
            "SELECT * FROM tarefa WHERE missao_id=? AND estado='pendente' "
            "ORDER BY id", (missao_id,)):
        if _pronta(t):
            return t
    return None


def executar_tarefa(tarefa_id: int) -> dict:
    t = bd.linha("SELECT * FROM tarefa WHERE id=?", (tarefa_id,))
    emp, mid = t["empresa_id"], t["missao_id"]
    d = ar.obter(t["agente_id"])
    entradas = bd.dj(t["entradas"], {}) or {}

    assin = limites.assinatura(t["agente_id"], entradas)

    if not limites.concorrencia_livre(emp, mid):
        return {"ok": False, "motivo": "concorrencia"}

    try:
        reserva = limites.reservar(emp, mid, tarefa_id,
                                   int(t["orcamento_centavos"] or 0))
    except limites.LimiteEstourado as e:
        estados.mover_tarefa(tarefa_id, "cancelada", motivo=str(e))
        estados.mover_missao(mid, "bloqueada", motivo=f"orçamento: {e}")
        return {"ok": False, "motivo": "limite", "erro": str(e)}

    estados.mover_tarefa(tarefa_id, "despachada",
                         motivo=f"despachada para {d.nome}")
    estados.mover_tarefa(tarefa_id, "executando", ator=f"agente:{d.id}",
                         motivo=f"{d.nome} começou a trabalhar")
    bd.atualizar("tarefa", tarefa_id,
                 {"tentativas": int(t["tentativas"]) + 1,
                  "atualizada_em": bd.agora()})

    contraprova = entradas.get("papel") == "contraprova"
    try:
        if contraprova:
            alvo = _alvo_da_contraprova(entradas.get("auditar_tarefa"))
            if alvo is None:
                estados.mover_tarefa(
                    tarefa_id, "nao_verificavel",
                    motivo="a apuração a ser contestada não produziu entrega")
                limites.realizar(emp, mid, tarefa_id, reserva, 0, 0, 0)
                return {"ok": False, "motivo": "sem_alvo"}
            ent = d.auditor(empresa_id=emp, missao_id=mid, tarefa_id=tarefa_id,
                            entradas=entradas,
                            acoes=bd.dj(t["acoes_permitidas"]), alvo=alvo)
        else:
            ent = d.executor(empresa_id=emp, missao_id=mid, tarefa_id=tarefa_id,
                             entradas=entradas,
                             acoes=bd.dj(t["acoes_permitidas"]))
    except Exception as e:  # noqa: BLE001
        limites.realizar(emp, mid, tarefa_id, reserva, 0, 0, 0)
        estados.mover_tarefa(tarefa_id, "falha", motivo=f"erro do executor: {e}")
        return {"ok": False, "motivo": "erro", "erro": str(e)}

    limites.realizar(emp, mid, tarefa_id, reserva, 0, 0, 0)

    # ciclo improdutivo: mesma entrada, mesma saída, de novo
    vezes = limites.registrar_ciclo(mid, assin, fb.hash_saida(ent.resultado))
    if vezes > limites.IMPRODUTIVO_APOS:
        bd.evento(emp, "missao.ciclo_improdutivo",
                  f"A mesma consulta repetiu {vezes} vezes sem trazer "
                  f"informação nova. A missão para aqui em vez de gastar mais.",
                  missao_id=mid, tarefa_id=tarefa_id)
        estados.mover_tarefa(tarefa_id, "entregue", ator=f"agente:{d.id}",
                             motivo="entrega registrada")
        estados.mover_missao(mid, "bloqueada", motivo="ciclo improdutivo")
        return {"ok": False, "motivo": "improdutivo"}

    entrega_id = registrar_entrega(t, ent)
    estados.mover_tarefa(tarefa_id, "entregue", ator=f"agente:{d.id}",
                         motivo=ent.resumo[:200])

    veredito = validacao.validar_entrega(entrega_id, ent.bruto)
    estados.mover_tarefa(tarefa_id, veredito, motivo=f"validação: {veredito}")
    return {"ok": veredito == "aprovada", "entrega_id": entrega_id,
            "veredito": veredito}


def _alvo_da_contraprova(tarefa_id) -> dict | None:
    """O que o apurador afirmou, para o auditor ter o que contestar."""
    if not tarefa_id:
        return None
    e = bd.linha("SELECT * FROM entrega WHERE tarefa_id=? "
                 "ORDER BY id DESC LIMIT 1", (tarefa_id,))
    if e is None:
        return None
    t = bd.linha("SELECT agente_id FROM tarefa WHERE id=?", (tarefa_id,))
    return {"entrega_id": e["id"], "tarefa_id": tarefa_id,
            "agente_id": t["agente_id"] if t else None,
            "resumo": e["resumo"],
            "resultado": bd.dj(e["resultado"], {}) or {}}


def registrar_entrega(t: dict, ent) -> int:
    emp, mid = t["empresa_id"], t["missao_id"]
    entrega_id = bd.inserir("entrega", {
        "empresa_id": emp, "missao_id": mid, "tarefa_id": t["id"],
        "tentativa": int(t["tentativas"]) + 1,
        "status_declarado": ent.status, "resumo": ent.resumo,
        "resultado": bd.j(ent.resultado), "incertezas": bd.j(ent.incertezas),
        "conflitos": bd.j(ent.conflitos), "pendencias": bd.j(ent.pendencias),
        "complemento": bd.j(ent.complemento) if ent.complemento else None,
        "criada_em": bd.agora()})

    ids = []
    for e in ent.evidencias:
        ids.append(bd.inserir("evidencia", {
            "empresa_id": emp, "missao_id": mid, "tipo": e["tipo"],
            "origem": e["origem"], "referencia": e["referencia"],
            "trecho": e.get("trecho"), "conteudo_hash": None,
            "consultada_em": e["consultada_em"], "raiz": e.get("raiz"),
            "criada_em": bd.agora()}))

    for a in ent.afirmacoes:
        idx = a.get("evidencia")
        bd.inserir("afirmacao", {
            "entrega_id": entrega_id, "texto": a["texto"],
            "natureza": a.get("natureza", "fato"),
            "evidencia_id": ids[idx] if isinstance(idx, int) and idx < len(ids)
                            else None,
            "verificada": None})
    return entrega_id


# ===========================================================================
# 4. Ciclo
# ===========================================================================
def avancar(missao_id: int) -> dict:
    """Um passo da missão. O trabalhador chama isto em laço."""
    m = bd.linha("SELECT * FROM missao WHERE id=?", (missao_id,))
    if m is None:
        return {"fim": True, "motivo": "missão não existe"}
    emp = m["empresa_id"]

    if m["estado"] in estados.TERMINAIS_MISSAO:
        return {"fim": True, "estado": m["estado"]}

    if m["estado"] == "rascunho":
        r = planejar(missao_id)
        return {"fim": not r["ok"], "passo": "planejamento", **r}

    if m["estado"] == "planejada":
        estados.mover_missao(missao_id, "executando", motivo="início da execução")
        m["estado"] = "executando"

    if m["estado"] in ("executando", "replanejando"):
        if m["estado"] == "replanejando":
            estados.mover_missao(missao_id, "executando", motivo="plano refeito")
        t = proxima_tarefa(missao_id)
        if t:
            r = executar_tarefa(t["id"])
            return {"fim": False, "passo": "execucao", **r}

        # nada pendente: há devolução para reprocessar?
        dev = bd.linhas(
            "SELECT * FROM tarefa WHERE missao_id=? AND estado IN "
            "('reprovada','falha') AND tentativas < max_tentativas", (missao_id,))
        if dev:
            for x in dev:
                estados.mover_tarefa(x["id"], "pendente",
                                     motivo="devolvida para nova tentativa")
            return {"fim": False, "passo": "devolucao", "tarefas": len(dev)}

        estados.mover_missao(missao_id, "validando",
                             motivo="todas as tarefas encerradas")
        m["estado"] = "validando"

    if m["estado"] == "validando":
        return concluir(missao_id, emp)

    return {"fim": False, "passo": "aguardando", "estado": m["estado"]}


def concluir(missao_id: int, empresa_id: int) -> dict:
    # o artefato precisa existir ANTES da camada operacional conferir se existe
    from ferramentas import artefato
    try:
        artefato.relatorio(missao_id)
    except Exception as e:  # noqa: BLE001
        bd.evento(empresa_id, "artefato.falha",
                  f"Não foi possível gerar o relatório: {e}", missao_id=missao_id)

    natureza, achados = validacao.validar_missao(missao_id, empresa_id)
    aprovadas = bd.linha(
        "SELECT COUNT(*) n FROM tarefa WHERE missao_id=? AND estado='aprovada'",
        (missao_id,))["n"]
    total = bd.linha(
        "SELECT COUNT(*) n FROM tarefa WHERE missao_id=? AND estado NOT IN "
        "('substituida','cancelada')", (missao_id,))["n"]

    reprovou = any(a["resultado"] == "reprovado" for a in achados)
    completo = total > 0 and aprovadas == total and not reprovou

    entregas = bd.linhas(
        "SELECT e.resumo, e.resultado, t.entradas, t.agente_id "
        "FROM entrega e JOIN tarefa t ON t.id = e.tarefa_id "
        "WHERE e.missao_id=? ORDER BY e.id", (missao_id,))
    # A conclusão da missão é o que a APURAÇÃO achou. A contraprova entra ao
    # lado, como conferência — trocar uma pela outra faria a missão terminar
    # dizendo "conferi" em vez de dizer o que foi encontrado.
    apur, confs = [], []
    for e in entregas:
        ent = bd.dj(e["entradas"], {}) or {}
        (confs if ent.get("papel") == "contraprova" else apur).append(e)
    principal = apur[-1] if apur else (entregas[-1] if entregas else None)
    pendencias = [a["justificativa"] for a in achados
                  if a["resultado"] != "aprovado"]

    resultado = {
        "natureza": natureza,
        "conclusao": principal["resumo"] if principal else
                     "Nenhuma entrega foi produzida.",
        "dados": bd.dj(principal["resultado"], {}) if principal else {},
        "conferencia": [{"agente_id": c["agente_id"],
                         "agente": (ar.obter(c["agente_id"]).nome
                                    if ar.obter(c["agente_id"])
                                    else c["agente_id"]),
                         "resumo": c["resumo"],
                         "veredito": (bd.dj(c["resultado"], {}) or {})
                                     .get("veredito")}
                        for c in confs],
        "tarefas_aprovadas": aprovadas, "tarefas_totais": total,
        "o_que_nao_foi_possivel": pendencias,
        "achados_de_validacao": achados,
    }
    bd.atualizar("missao", missao_id, {
        "resultado": bd.j(resultado), "natureza": natureza,
        "atualizada_em": bd.agora()})

    alvo = "concluida" if completo else "parcial"
    if natureza == "contestada":
        motivo_fim = ("A contraprova discordou da apuração. O número fica "
                      "registrado com a discordância ao lado, e não vale como "
                      "conclusão até alguém desempatar.")
    elif completo:
        motivo_fim = "Conclusão sustentada por evidência e conferida por outro caminho."
    else:
        motivo_fim = "Conclusão parcial — o que faltou está escrito."
    estados.mover_missao(missao_id, alvo, motivo=motivo_fim)
    bd.evento(empresa_id, "missao.encerrada",
              resultado["conclusao"], missao_id=missao_id,
              dados={"natureza": natureza, "estado": alvo})
    return {"fim": True, "passo": "conclusao", "estado": alvo,
            "natureza": natureza}
