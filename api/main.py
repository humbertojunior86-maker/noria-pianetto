"""API da NÓRIA. É o único caminho entre a interface e o núcleo.

A interface não calcula nada: ela mostra o que a API devolve, com o estado real
de cada coisa. Integração desconectada chega aqui como desconectada.
"""
from __future__ import annotations

import hashlib
import secrets
import sys
from datetime import timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from fastapi import Body, Depends, FastAPI, HTTPException, Header, Query  # noqa: E402
from fastapi.responses import FileResponse                                # noqa: E402
from fastapi.staticfiles import StaticFiles                               # noqa: E402

from agentes import registro as ar                                        # noqa: E402
from ferramentas import atua, base as fb                                  # noqa: E402,F401
from nucleo import bd, orquestrador as orq                                # noqa: E402

app = FastAPI(title="NÓRIA", version="1.0", docs_url="/api/docs")


def _senha(p: str) -> str:
    return hashlib.sha256(("noria$" + p).encode()).hexdigest()


# --------------------------------------------------------------------- sessão
def sessao(authorization: str = Header(default="")) -> dict:
    token = authorization.replace("Bearer ", "").strip()
    if not token:
        raise HTTPException(401, "sem credencial")
    s = bd.linha("SELECT * FROM sessao WHERE token=?", (token,))
    if not s or s["expira_em"] < bd.agora():
        raise HTTPException(401, "sessão expirada")
    u = bd.linha("SELECT * FROM usuario WHERE id=?", (s["usuario_id"],))
    return {"usuario": u, "empresa_id": s["empresa_id"]}


@app.post("/api/entrar")
def entrar(dados: dict = Body(...)):
    u = bd.linha("SELECT * FROM usuario WHERE email=? AND ativo=1",
                 (dados.get("email", "").strip().lower(),))
    if not u or u["senha_hash"] != _senha(dados.get("senha", "")):
        raise HTTPException(401, "e-mail ou senha não conferem")
    from datetime import datetime
    token = secrets.token_urlsafe(32)
    bd.inserir("sessao", {
        "token": token, "usuario_id": u["id"], "empresa_id": u["empresa_id"],
        "criada_em": bd.agora(),
        "expira_em": (datetime.now(bd.FUSO) + timedelta(days=7)).isoformat(
            timespec="seconds")})
    return {"token": token, "usuario": {"nome": u["nome"], "papel": u["papel"],
                                        "email": u["email"]}}


@app.get("/api/eu")
def eu(s: dict = Depends(sessao)):
    e = bd.linha("SELECT * FROM empresa WHERE id=?", (s["empresa_id"],))
    return {"usuario": {k: s["usuario"][k] for k in ("nome", "email", "papel")},
            "empresa": {"id": e["id"], "nome": e["nome"], "cnpj": e["cnpj"]}}


# ------------------------------------------------------------------ panorama
@app.get("/api/panorama")
def panorama(s: dict = Depends(sessao)):
    emp = s["empresa_id"]

    def n(sql, a=()):
        return int(bd.linha(sql, a)["n"] or 0)

    estados_missao = {
        r["estado"]: r["n"] for r in bd.linhas(
            "SELECT estado, COUNT(*) n FROM missao WHERE empresa_id=? "
            "GROUP BY estado", (emp,))}

    integr = bd.linhas("SELECT * FROM integracao WHERE empresa_id=?", (emp,))
    agentes = ar.todos()
    hab = [d for d in agentes if d.situacao()[0] == "habilitado"]

    ult = bd.linhas(
        "SELECT id, objetivo, estado, natureza, criada_em, encerrada_em "
        "FROM missao WHERE empresa_id=? ORDER BY id DESC LIMIT 8", (emp,))

    achados = bd.linhas(
        "SELECT v.camada, v.resultado, v.justificativa, v.missao_id, v.criada_em "
        "FROM validacao v WHERE v.empresa_id=? AND v.resultado='reprovado' "
        "ORDER BY v.id DESC LIMIT 8", (emp,))

    return {
        "missoes": {"por_estado": estados_missao,
                    "total": sum(estados_missao.values()),
                    "em_curso": sum(estados_missao.get(e, 0) for e in
                                    ("planejada", "executando", "validando",
                                     "replanejando"))},
        "agentes": {"cadastrados": len(agentes), "habilitados": len(hab),
                    "sem_integracao": len(agentes) - len(hab)},
        "integracoes": [{"id": i["id"], "nome": i["nome"], "estado": i["estado"],
                         "escreve": bool(i["escreve"]),
                         "limitacao": i["ultimo_erro"]} for i in integr],
        "aprovacoes_pendentes": n(
            "SELECT COUNT(*) n FROM acao_externa WHERE empresa_id=? AND "
            "estado IN ('proposta','aguardando')", (emp,)),
        "evidencias": n("SELECT COUNT(*) n FROM evidencia WHERE empresa_id=?", (emp,)),
        "artefatos": n("SELECT COUNT(*) n FROM artefato WHERE empresa_id=?", (emp,)),
        "ultimas_missoes": ult,
        "achados_abertos": achados,
        "gerado_em": bd.agora(),
    }


# -------------------------------------------------------------------- missões
@app.get("/api/missoes")
def listar_missoes(s: dict = Depends(sessao), estado: str | None = None,
                   limite: int = Query(50, le=200)):
    sql = "SELECT * FROM missao WHERE empresa_id=?"
    a: list = [s["empresa_id"]]
    if estado:
        sql += " AND estado=?"
        a.append(estado)
    sql += " ORDER BY id DESC LIMIT ?"
    a.append(limite)
    return {"missoes": bd.linhas(sql, tuple(a))}


@app.post("/api/missoes")
def criar_missao(dados: dict = Body(...), s: dict = Depends(sessao)):
    objetivo = (dados.get("objetivo") or "").strip()
    if len(objetivo) < 8:
        raise HTTPException(400, "descreva o objetivo com mais clareza")
    mid = orq.abrir_missao(
        s["empresa_id"], objetivo, contexto=dados.get("contexto") or {},
        origem="humano", solicitante=s["usuario"]["id"],
        area=dados.get("area"), prioridade=dados.get("prioridade", "normal"),
        prazo=dados.get("prazo"))
    r = orq.planejar(mid)
    return {"missao_id": mid, "planejamento": r}


@app.get("/api/missoes/{mid}")
def ver_missao(mid: int, s: dict = Depends(sessao)):
    m = bd.linha("SELECT * FROM missao WHERE id=? AND empresa_id=?",
                 (mid, s["empresa_id"]))
    if not m:
        raise HTTPException(404, "missão não encontrada")
    m["contexto"] = bd.dj(m["contexto"], {})
    m["resultado"] = bd.dj(m["resultado"], {})
    tarefas = bd.linhas(
        "SELECT * FROM tarefa WHERE missao_id=? ORDER BY id", (mid,))
    for t in tarefas:
        t["entradas"] = bd.dj(t["entradas"], {})
        t["acoes_permitidas"] = bd.dj(t["acoes_permitidas"])
    return {
        "missao": m,
        "planos": bd.linhas("SELECT * FROM plano WHERE missao_id=? ORDER BY versao",
                            (mid,)),
        "tarefas": tarefas,
        "criterios": bd.linhas(
            "SELECT * FROM criterio WHERE missao_id=? ORDER BY ordem", (mid,)),
        "validacoes": bd.linhas(
            "SELECT * FROM validacao WHERE missao_id=? ORDER BY id", (mid,)),
        "artefatos": bd.linhas("SELECT * FROM artefato WHERE missao_id=?", (mid,)),
        "eventos": bd.linhas(
            "SELECT * FROM evento WHERE missao_id=? ORDER BY id", (mid,)),
    }


@app.get("/api/missoes/{mid}/entregas")
def entregas(mid: int, s: dict = Depends(sessao)):
    saida = []
    for e in bd.linhas(
            "SELECT e.*, t.titulo, t.agente_id FROM entrega e "
            "JOIN tarefa t ON t.id=e.tarefa_id WHERE e.missao_id=? AND "
            "e.empresa_id=? ORDER BY e.id", (mid, s["empresa_id"])):
        af = bd.linhas(
            "SELECT a.*, v.origem, v.referencia, v.trecho, v.consultada_em, v.raiz "
            "FROM afirmacao a LEFT JOIN evidencia v ON v.id=a.evidencia_id "
            "WHERE a.entrega_id=? ORDER BY a.id", (e["id"],))
        saida.append({**e,
                      "resultado": bd.dj(e["resultado"], {}),
                      "incertezas": bd.dj(e["incertezas"]),
                      "conflitos": bd.dj(e["conflitos"]),
                      "pendencias": bd.dj(e["pendencias"]),
                      "afirmacoes": af})
    return {"entregas": saida}


@app.post("/api/missoes/{mid}/avancar")
def avancar(mid: int, s: dict = Depends(sessao)):
    m = bd.linha("SELECT id FROM missao WHERE id=? AND empresa_id=?",
                 (mid, s["empresa_id"]))
    if not m:
        raise HTTPException(404, "missão não encontrada")
    return orq.avancar(mid)


@app.post("/api/missoes/{mid}/cancelar")
def cancelar(mid: int, dados: dict = Body(default={}), s: dict = Depends(sessao)):
    from nucleo import estados
    estados.mover_missao(mid, "cancelada",
                         ator=f"usuario:{s['usuario']['id']}",
                         motivo=dados.get("motivo") or "cancelada pelo usuário")
    return {"ok": True}


# -------------------------------------------------------------------- agentes
@app.get("/api/agentes")
def agentes(s: dict = Depends(sessao)):
    saida = []
    for d in ar.todos():
        sit, lim = d.situacao()
        feito = bd.linha(
            "SELECT COUNT(*) n FROM tarefa WHERE agente_id=? AND estado='aprovada'",
            (d.id,))["n"]
        saida.append({
            "id": d.id, "nome": d.nome, "papel": d.papel, "area": d.area,
            "promessa": d.promessa, "versao": d.versao, "situacao": sit,
            "limitacao": lim, "ferramentas": d.ferramentas,
            "acoes": d.acoes, "competencias": d.competencias,
            "entradas": d.entradas, "saidas": d.saidas,
            "tarefas_aprovadas": feito,
        })
    return {"agentes": saida}


@app.get("/api/agentes/{aid}")
def agente(aid: str, s: dict = Depends(sessao)):
    d = ar.obter(aid)
    if not d:
        raise HTTPException(404, "agente não encontrado")
    sit, lim = d.situacao()
    hist = bd.linhas(
        "SELECT t.id, t.titulo, t.estado, t.atualizada_em, t.missao_id "
        "FROM tarefa t WHERE t.agente_id=? AND t.empresa_id=? "
        "ORDER BY t.id DESC LIMIT 20", (aid, s["empresa_id"]))
    return {"agente": {"id": d.id, "nome": d.nome, "papel": d.papel,
                       "area": d.area, "promessa": d.promessa,
                       "versao": d.versao, "situacao": sit, "limitacao": lim,
                       "ferramentas": d.ferramentas, "acoes": d.acoes,
                       "entradas": d.entradas, "saidas": d.saidas,
                       "criterios": d.criterios},
            "historico": hist}


# -------------------------------------------------------- evidências e trilha
@app.get("/api/evidencias/{eid}")
def evidencia(eid: int, s: dict = Depends(sessao)):
    e = bd.linha("SELECT * FROM evidencia WHERE id=? AND empresa_id=?",
                 (eid, s["empresa_id"]))
    if not e:
        raise HTTPException(404, "evidência não encontrada")
    return {"evidencia": e}


@app.get("/api/eventos")
def eventos(s: dict = Depends(sessao), limite: int = Query(60, le=300),
            desde: int = 0):
    return {"eventos": bd.linhas(
        "SELECT * FROM evento WHERE empresa_id=? AND id > ? "
        "ORDER BY id DESC LIMIT ?", (s["empresa_id"], desde, limite))}


@app.get("/api/execucoes")
def execucoes(s: dict = Depends(sessao), limite: int = Query(50, le=200)):
    return {"execucoes": bd.linhas(
        "SELECT id, ferramenta, operacao, estado, linhas, ms, erro, iniciada_em "
        "FROM execucao_ferramenta WHERE empresa_id=? ORDER BY id DESC LIMIT ?",
        (s["empresa_id"], limite))}


# ------------------------------------------------------------------ artefatos
@app.get("/api/artefatos")
def artefatos(s: dict = Depends(sessao)):
    return {"artefatos": bd.linhas(
        "SELECT * FROM artefato WHERE empresa_id=? ORDER BY id DESC LIMIT 100",
        (s["empresa_id"],))}


@app.get("/api/artefatos/{aid}/baixar")
def baixar(aid: int, s: dict = Depends(sessao)):
    a = bd.linha("SELECT * FROM artefato WHERE id=? AND empresa_id=?",
                 (aid, s["empresa_id"]))
    if not a:
        raise HTTPException(404, "artefato não encontrado")
    p = Path(a["caminho"])
    if not p.is_file():
        raise HTTPException(410, "o arquivo não existe mais em disco")
    return FileResponse(p, filename=p.name)


# ----------------------------------------------------------------- aprovações
@app.get("/api/aprovacoes")
def aprovacoes(s: dict = Depends(sessao)):
    return {"acoes": bd.linhas(
        "SELECT * FROM acao_externa WHERE empresa_id=? AND estado IN "
        "('proposta','aguardando','ambigua') ORDER BY id DESC",
        (s["empresa_id"],))}


@app.post("/api/aprovacoes/{acao_id}")
def decidir(acao_id: int, dados: dict = Body(...), s: dict = Depends(sessao)):
    a = bd.linha("SELECT * FROM acao_externa WHERE id=? AND empresa_id=?",
                 (acao_id, s["empresa_id"]))
    if not a:
        raise HTTPException(404, "ação não encontrada")
    decisao = dados.get("decisao")
    if decisao not in ("aprovar", "rejeitar", "ajustar"):
        raise HTTPException(400, "decisão inválida")

    alc = bd.linha(
        "SELECT * FROM alcada WHERE empresa_id=? AND tipo_acao=?",
        (s["empresa_id"], a["tipo"]))
    ordem = {"leitor": 0, "operador": 1, "gestor": 2, "ceo": 3}
    if alc and ordem.get(s["usuario"]["papel"], 0) < ordem.get(alc["papel_minimo"], 3):
        raise HTTPException(
            403, f"esta ação exige alçada de {alc['papel_minimo']}")

    bd.inserir("aprovacao", {
        "empresa_id": s["empresa_id"], "acao_id": acao_id,
        "hash_aprovado": a["hash_conteudo"], "decisao": decisao,
        "decidida_por": s["usuario"]["id"], "observacao": dados.get("observacao"),
        "valida_ate": None, "criada_em": bd.agora(), "decidida_em": bd.agora()})
    novo = {"aprovar": "aprovada", "rejeitar": "rejeitada",
            "ajustar": "proposta"}[decisao]
    bd.atualizar("acao_externa", acao_id, {"estado": novo})
    bd.evento(s["empresa_id"], "acao.decidida",
              f"Ação {acao_id} — {decisao} por {s['usuario']['nome']}",
              ator=f"usuario:{s['usuario']['id']}", missao_id=a["missao_id"])
    return {"ok": True, "estado": novo}


# ---------------------------------------------------------------- integrações
@app.get("/api/integracoes")
def integracoes(s: dict = Depends(sessao)):
    itens = bd.linhas("SELECT * FROM integracao WHERE empresa_id=?",
                      (s["empresa_id"],))
    for i in itens:
        i["permissoes"] = bd.dj(i["permissoes"])
        i["escreve"] = bool(i["escreve"])
    return {"integracoes": itens}


@app.post("/api/integracoes/{iid}/testar")
def testar(iid: str, s: dict = Depends(sessao)):
    f = fb.obter(iid)
    if f is None:
        bd.executar(
            "UPDATE integracao SET estado='nao_configurada', ultimo_teste=?, "
            "ultimo_erro=? WHERE id=? AND empresa_id=?",
            (bd.agora(), "não há ferramenta registrada para esta integração",
             iid, s["empresa_id"]))
        return {"estado": "nao_configurada",
                "detalhe": "não há ferramenta registrada para esta integração"}
    if not f.disponivel():
        bd.executar(
            "UPDATE integracao SET estado='nao_configurada', ultimo_teste=?, "
            "ultimo_erro=? WHERE id=? AND empresa_id=?",
            (bd.agora(), f.limitacao, iid, s["empresa_id"]))
        return {"estado": "nao_configurada", "detalhe": f.limitacao}

    r = fb.rodar(iid, "conta.listar", {}, empresa_id=s["empresa_id"],
                 acoes_permitidas=[f"{iid}.conta.listar"])
    estado = "conectada" if r.ok else "erro"
    bd.executar(
        "UPDATE integracao SET estado=?, ultimo_teste=?, ultimo_erro=? "
        "WHERE id=? AND empresa_id=?",
        (estado, bd.agora(), r.erro, iid, s["empresa_id"]))
    return {"estado": estado, "detalhe": r.resumo or r.erro}


# ------------------------------------------------------------------- estático
WEB = RAIZ / "web"
if WEB.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
