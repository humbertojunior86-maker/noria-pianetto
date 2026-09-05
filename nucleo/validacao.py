"""Seis camadas de validação.

Nenhuma tarefa vira 'aprovada' porque o executor disse que terminou. A entrega
é uma declaração. A aprovação vem daqui, e sempre com justificativa gravada.

Regra que sustenta o resto: dois agentes concordando não provam nada. Só conta
como confirmação quem recomputou por conta própria a partir da evidência bruta.
"""
from __future__ import annotations

from ferramentas import verificadores as vf
from . import bd

CAMADAS = ["estrutural", "objetiva", "documental", "especializada",
           "global", "operacional"]


def _reg(missao_id, entrega_id, criterio_id, camada, revisor, resultado,
         justificativa, empresa_id, independente=0, evidencia_id=None) -> int:
    return bd.inserir("validacao", {
        "empresa_id": empresa_id, "missao_id": missao_id,
        "entrega_id": entrega_id, "criterio_id": criterio_id, "camada": camada,
        "revisor": revisor, "resultado": resultado,
        "justificativa": justificativa, "evidencia_id": evidencia_id,
        "independente": independente, "criada_em": bd.agora()})


# ------------------------------------------------------------------ camada 1
def estrutural(entrega: dict, tarefa: dict, empresa_id: int) -> list[tuple]:
    """Formato, campos obrigatórios, limites. Barato e roda sempre primeiro."""
    saidas = bd.dj(tarefa.get("saidas_esperadas"), {}) or {}
    res = bd.dj(entrega["resultado"], {}) or {}
    achados = []

    if entrega["status_declarado"] not in ("concluida", "parcial", "bloqueada"):
        achados.append(("reprovado", "status declarado fora do vocabulário"))
    if not (entrega["resumo"] or "").strip():
        achados.append(("reprovado", "entrega sem resumo legível"))

    # entrega bloqueada não deve trazer os campos do resultado — o que ela deve
    # trazer é o motivo do bloqueio, e isso é cobrado abaixo.
    if entrega["status_declarado"] == "bloqueada":
        pend = bd.dj(entrega.get("pendencias"), [])
        if not pend:
            achados.append(("reprovado",
                            "entrega bloqueada sem dizer o que a bloqueou"))
        else:
            achados.append(("nao_verificavel",
                            f"entrega bloqueada: {pend[0]}"))
        return achados

    faltando = [k for k in saidas if k not in res]
    if faltando:
        achados.append(("reprovado",
                        f"campos obrigatórios ausentes: {', '.join(faltando)}"))
    if not achados:
        achados.append(("aprovado",
                        "estrutura da entrega íntegra e dentro do contrato"))
    return achados


# ------------------------------------------------------------------ camada 2
def objetiva(entrega: dict, criterios: list[dict], bruto: dict,
             empresa_id: int) -> list[tuple]:
    """Verificadores de código recomputam do zero. É a camada que dá o veredito."""
    res = bd.dj(entrega["resultado"], {}) or {}
    achados = []
    for c in criterios:
        nome = c.get("verificador")
        if not nome:
            continue
        f = vf.obter(nome)
        if f is None:
            achados.append((c["id"], "nao_verificavel",
                            f"verificador '{nome}' não existe"))
            continue
        params = dict(bd.dj(c.get("parametros"), {}) or {})
        params.setdefault("entrega_id", entrega["id"])
        params.setdefault("missao_id", entrega["missao_id"])
        try:
            r, just = f(res, bruto, params)
        except Exception as e:  # noqa: BLE001
            r, just = "nao_verificavel", f"verificador falhou: {e}"
        achados.append((c["id"], r, just))
    return achados


# ------------------------------------------------------------------ camada 3
def documental(entrega: dict, empresa_id: int) -> list[tuple]:
    """Toda afirmação de fato precisa apontar para evidência com data.

    Afirmação sem lastro não é apagada: é rebaixada a hipótese e continua
    visível, marcada. O que não pode é passar como fato.
    """
    fatos = bd.linhas(
        "SELECT * FROM afirmacao WHERE entrega_id=? AND natureza='fato'",
        (entrega["id"],))
    if not fatos:
        return [("nao_verificavel", "a entrega não declarou afirmações")]

    orfas, sem_data = [], []
    for f in fatos:
        if not f["evidencia_id"]:
            orfas.append(f)
            continue
        ev = bd.linha("SELECT * FROM evidencia WHERE id=?", (f["evidencia_id"],))
        if not ev or not ev["consultada_em"]:
            sem_data.append(f)

    for f in orfas:
        bd.atualizar("afirmacao", f["id"],
                     {"natureza": "hipotese", "verificada": "nao_verificavel"})

    if orfas:
        return [("reprovado",
                 f"{len(orfas)} de {len(fatos)} afirmação(ões) sem evidência — "
                 f"rebaixadas a hipótese; ex.: “{orfas[0]['texto'][:90]}”")]
    if sem_data:
        return [("reprovado",
                 f"{len(sem_data)} evidência(s) sem data de consulta")]
    return [("aprovado", f"{len(fatos)} afirmação(ões) com evidência datada")]


# ------------------------------------------------------------------ camada 4
def especializada(entrega: dict, tarefa: dict, empresa_id: int) -> list[tuple]:
    """Estado da revisão por par NO MOMENTO da entrega.

    O veredito de verdade sai no fechamento da missão, em especializada_missao:
    aqui a contraprova ainda nem rodou, porque ela depende desta entrega para
    ter o que contestar. Esta camada só diz em que pé está. Nunca 'aprovado'.
    """
    from agentes import registro as ar
    dono = tarefa.get("agente_id")
    d = ar.obter(dono) if dono else None
    if d is None:
        return [("nao_verificavel", "tarefa sem agente responsável identificado")]

    if (bd.dj(tarefa.get("entradas"), {}) or {}).get("papel") == "contraprova":
        return [("nao_verificavel",
                 "contraprova não é contestada por outra contraprova — "
                 "ela é a contestação")]

    revs = _contraprovas_de(tarefa["id"])
    if revs:
        nomes = ", ".join(
            (ar.obter(r["agente_id"]).nome if ar.obter(r["agente_id"])
             else r["agente_id"]) for r in revs)
        return [("nao_verificavel",
                 f"contraprova com {nomes} ainda não rodou; o veredito sai no "
                 f"fechamento da missão")]
    return [("nao_verificavel",
             f"não há contraprova prevista para {d.papel} — este número saiu "
             f"por um caminho só e ninguém o conferiu por outro")]


def _contraprovas_de(tarefa_id: int) -> list[dict]:
    """Tarefas de contraprova que apontam para esta tarefa."""
    alvo = bd.linha("SELECT missao_id FROM tarefa WHERE id=?", (tarefa_id,))
    if alvo is None:
        return []
    saida = []
    for t in bd.linhas(
            "SELECT * FROM tarefa WHERE missao_id=? AND estado <> 'substituida'",
            (alvo["missao_id"],)):
        e = bd.dj(t["entradas"], {}) or {}
        if e.get("papel") == "contraprova" and e.get("auditar_tarefa") == tarefa_id:
            saida.append(t)
    return saida


def especializada_missao(missao_id: int, empresa_id: int) -> list[dict]:
    """Camada 4 de verdade: lê o que o auditor achou e dá o veredito.

    Roda no fechamento, quando a contraprova já correu. Contradição aqui não
    manda o apurador tentar de novo: repetir daria o mesmo número, porque o
    número dele não está errado — está sendo lido de outro jeito por outra
    porta do banco. Isso é divergindo, e quem decide é gente.
    """
    from agentes import registro as ar
    achados: list[dict] = []
    for t in bd.linhas(
            "SELECT * FROM tarefa WHERE missao_id=? AND estado <> 'substituida'",
            (missao_id,)):
        ent_t = bd.dj(t["entradas"], {}) or {}
        if ent_t.get("papel") != "contraprova":
            continue
        alvo_id = ent_t.get("auditar_tarefa")
        ep = bd.linha("SELECT id FROM entrega WHERE tarefa_id=? "
                      "ORDER BY id DESC LIMIT 1", (alvo_id,))
        ec = bd.linha("SELECT * FROM entrega WHERE tarefa_id=? "
                      "ORDER BY id DESC LIMIT 1", (t["id"],))
        rev = ar.obter(t["agente_id"])
        nome = rev.nome if rev else t["agente_id"]

        if ec is None:
            r, just = ("nao_verificavel",
                       f"{nome} não chegou a entregar a contraprova "
                       f"({t['estado']})")
        else:
            dados = bd.dj(ec["resultado"], {}) or {}
            vd = dados.get("veredito")
            if vd == "confirma":
                r = "aprovado"
            elif vd == "contradiz":
                r = "reprovado"
            else:
                r = "nao_verificavel"
            just = f"{nome} conferiu por outro caminho: {ec['resumo']}"

        _reg(missao_id, ep["id"] if ep else None, None, "especializada",
             f"agente:{t['agente_id']}", r, just, empresa_id, independente=1)
        achados.append({"camada": "especializada", "resultado": r,
                        "justificativa": just})
    return achados


# ------------------------------------------------------------------ camada 5
def global_(missao_id: int, empresa_id: int) -> list[tuple]:
    """Coerência entre entregas da missão e contra o que já se sabe.

    Contradição não é apagada. Vira achado explícito.
    """
    entregas = bd.linhas(
        "SELECT e.* FROM entrega e JOIN tarefa t ON t.id = e.tarefa_id "
        "WHERE e.missao_id=? AND t.estado <> 'substituida'", (missao_id,))
    if len(entregas) < 2:
        return [("nao_verificavel",
                 "coerência cruzada exige ao menos duas entregas na missão")]

    raizes = {r["raiz"] for r in bd.linhas(
        "SELECT DISTINCT raiz FROM evidencia WHERE missao_id=? AND raiz IS NOT NULL",
        (missao_id,))}
    if len(raizes) < 2:
        return [("nao_verificavel",
                 f"todas as entregas vêm da mesma origem-raiz ({', '.join(raizes) or 'nenhuma'}) — "
                 f"repetir a mesma fonte não confirma o fato")]

    bloq = [e for e in entregas if e["status_declarado"] == "bloqueada"]
    if bloq:
        return [("reprovado",
                 f"{len(bloq)} entrega(s) bloqueada(s) impedem conclusão coerente")]
    return [("aprovado",
             f"{len(entregas)} entregas coerentes, sustentadas por "
             f"{len(raizes)} origens-raiz distintas")]


# ------------------------------------------------------------------ camada 6
def operacional(missao_id: int, empresa_id: int) -> list[tuple]:
    """O que foi prometido existe? Arquivo abre? Ação de impacto foi confirmada?"""
    achados = []
    f = vf.obter("artefato_existe")
    r, just = f({}, {}, {"missao_id": missao_id})
    achados.append((r, just))

    acoes = bd.linhas(
        "SELECT * FROM acao_externa WHERE missao_id=? AND estado='executada'",
        (missao_id,))
    nao_conf = [a for a in acoes if not a["confirmada_em"]]
    if nao_conf:
        achados.append(("reprovado",
                        f"{len(nao_conf)} ação(ões) executada(s) sem conferência "
                        f"do efeito no destino"))
    ambig = bd.linhas(
        "SELECT id FROM acao_externa WHERE missao_id=? AND estado='ambigua'",
        (missao_id,))
    if ambig:
        achados.append(("reprovado",
                        f"{len(ambig)} ação(ões) em estado ambíguo aguardando "
                        f"verificação humana"))
    return achados


# --------------------------------------------------------------- orquestração
def validar_entrega(entrega_id: int, bruto: dict) -> str:
    """Roda as camadas de 1 a 4 sobre uma entrega. Devolve o veredito da tarefa."""
    e = bd.linha("SELECT * FROM entrega WHERE id=?", (entrega_id,))
    t = bd.linha("SELECT * FROM tarefa WHERE id=?", (e["tarefa_id"],))
    emp = e["empresa_id"]
    # Cada tarefa é julgada pelos critérios DELA. O verificador da apuração
    # não serve para julgar a contraprova: ela devolve outra forma de dado.
    # tarefa_chave NULL é critério antigo, de antes desta separação.
    criterios = bd.linhas(
        "SELECT * FROM criterio WHERE missao_id=? AND camada='objetiva' "
        "AND (tarefa_chave IS NULL OR tarefa_chave=?)",
        (e["missao_id"], t["chave"]))

    resultados: list[str] = []

    for r, just in estrutural(e, t, emp):
        _reg(e["missao_id"], entrega_id, None, "estrutural", "codigo:estrutural",
             r, just, emp, independente=1)
        resultados.append(r)

    for crit_id, r, just in objetiva(e, criterios, bruto, emp):
        _reg(e["missao_id"], entrega_id, crit_id, "objetiva",
             "codigo:verificador", r, just, emp, independente=1)
        bd.atualizar("criterio", crit_id,
                     {"resultado": r, "justificativa": just,
                      "aferido_em": bd.agora()})
        resultados.append(r)

    for r, just in documental(e, emp):
        _reg(e["missao_id"], entrega_id, None, "documental", "codigo:documental",
             r, just, emp, independente=1)
        resultados.append(r)

    for r, just in especializada(e, t, emp):
        _reg(e["missao_id"], entrega_id, None, "especializada", "codigo:par",
             r, just, emp)
        resultados.append(r)

    if "reprovado" in resultados:
        return "reprovada"
    if all(r == "nao_verificavel" for r in resultados):
        return "nao_verificavel"
    return "aprovada"


def validar_missao(missao_id: int, empresa_id: int) -> tuple[str, list[dict]]:
    """Camadas 5 e 6. Devolve (natureza_do_resultado, achados)."""
    achados = []
    achados.extend(especializada_missao(missao_id, empresa_id))
    for r, just in global_(missao_id, empresa_id):
        _reg(missao_id, None, None, "global", "codigo:coerencia", r, just,
             empresa_id, independente=1)
        achados.append({"camada": "global", "resultado": r, "justificativa": just})
    for r, just in operacional(missao_id, empresa_id):
        _reg(missao_id, None, None, "operacional", "codigo:operacional", r, just,
             empresa_id, independente=1)
        achados.append({"camada": "operacional", "resultado": r,
                        "justificativa": just})

    houve_acao = bd.linha(
        "SELECT COUNT(*) n FROM acao_externa WHERE missao_id=? AND "
        "estado IN ('executada','confirmada')", (missao_id,))["n"]
    proposta = bd.linha(
        "SELECT COUNT(*) n FROM acao_externa WHERE missao_id=? AND "
        "estado IN ('proposta','aguardando','aprovada')", (missao_id,))["n"]

    # Contraprova que discordou muda a natureza do resultado. Não é análise
    # entregue: é dois caminhos do banco dizendo coisas diferentes sobre o
    # mesmo fato, e isso precisa de gente para desempatar.
    contestada = any(a["camada"] == "especializada"
                     and a["resultado"] == "reprovado" for a in achados)

    if contestada:
        natureza = "contestada"
    elif houve_acao:
        conf = bd.linha(
            "SELECT COUNT(*) n FROM acao_externa WHERE missao_id=? AND "
            "estado='confirmada'", (missao_id,))["n"]
        natureza = "confirmada" if conf == houve_acao else "executada"
    elif proposta:
        natureza = "proposta"
    else:
        natureza = "analise"
    return natureza, achados
