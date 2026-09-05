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
    m = re.search(r"(\d{4}-\d{2}-\d{2})", objetivo)
    if m and not e["data"]:
        e["data"] = m.group(1)
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

    tid = bd.inserir("tarefa", {
        "empresa_id": emp, "missao_id": missao_id, "plano_id": plano_id,
        "chave": f"{d.id}#1", "titulo": f"{d.papel}: {m['objetivo'][:80]}",
        "objetivo": m["objetivo"], "agente_id": d.id, "agente_versao": d.versao,
        "entradas": bd.j(intencao["entradas"]), "fontes": bd.j(d.ferramentas),
        "acoes_permitidas": bd.j(d.acoes), "formato_entrega": "json+md",
        "saidas_esperadas": bd.j(d.saidas),
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
            "missao_id": missao_id, "ordem": i,
            "descricao": f"verificador {nome}", "camada": "objetiva",
            "verificador": nome, "parametros": bd.j(p), "obrigatorio": 1})

    bd.atualizar("missao", missao_id,
                 {"plano_vigente": plano_id, "atualizada_em": bd.agora()})
    if m["estado"] in ("rascunho",):
        estados.mover_missao(missao_id, "planejada", motivo=motivo)
    bd.evento(emp, "plano.criado",
              f"Plano v{ver + 1}: {d.nome} ({d.papel}) — {motivo}",
              missao_id=missao_id, dados={"tarefas": 1})
    return {"ok": True, "plano_id": plano_id, "tarefa_id": tid}


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

    try:
        ent = d.executor(empresa_id=emp, missao_id=mid, tarefa_id=tarefa_id,
                         entradas=entradas, acoes=bd.dj(t["acoes_permitidas"]))
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
        "SELECT resumo, resultado FROM entrega WHERE missao_id=? ORDER BY id",
        (missao_id,))
    pendencias = [a["justificativa"] for a in achados
                  if a["resultado"] != "aprovado"]

    resultado = {
        "natureza": natureza,
        "conclusao": entregas[-1]["resumo"] if entregas else
                     "Nenhuma entrega foi produzida.",
        "dados": bd.dj(entregas[-1]["resultado"], {}) if entregas else {},
        "tarefas_aprovadas": aprovadas, "tarefas_totais": total,
        "o_que_nao_foi_possivel": pendencias,
        "achados_de_validacao": achados,
    }
    bd.atualizar("missao", missao_id, {
        "resultado": bd.j(resultado), "natureza": natureza,
        "atualizada_em": bd.agora()})

    alvo = "concluida" if completo else "parcial"
    estados.mover_missao(missao_id, alvo,
                         motivo=("Conclusão sustentada por evidência."
                                 if completo else
                                 "Conclusão parcial — o que faltou está escrito."))
    bd.evento(empresa_id, "missao.encerrada",
              resultado["conclusao"], missao_id=missao_id,
              dados={"natureza": natureza, "estado": alvo})
    return {"fim": True, "passo": "conclusao", "estado": alvo,
            "natureza": natureza}
