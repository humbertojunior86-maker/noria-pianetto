"""API da NÓRIA. É o único caminho entre a interface e o núcleo.

A interface não calcula nada: ela mostra o que a API devolve, com o estado real
de cada coisa. Integração desconectada chega aqui como desconectada.
"""
from __future__ import annotations

import hashlib
import secrets
import sys
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from fastapi import (Body, Depends, FastAPI, HTTPException, Header,       # noqa: E402
                     Query, Request)
from fastapi.responses import FileResponse                                # noqa: E402
from fastapi.staticfiles import StaticFiles                               # noqa: E402

from agentes import registro as ar                                        # noqa: E402
from ferramentas import atua, base as fb                                  # noqa: E402,F401
from nucleo import bd, orquestrador as orq                                # noqa: E402

app = FastAPI(title="NÓRIA", version="1.0", docs_url="/api/docs")


def _senha(p: str) -> str:
    return hashlib.sha256(("noria$" + p).encode()).hexdigest()


# --------------------------------------------------------------------- sessão
# O painel do saguão fica numa parede à vista de cliente e de visitante. A
# conta que o abre não pode chegar em dinheiro, nome de cliente ou decisão
# pendente — e a recusa mora aqui, no único portão por onde toda rota passa.
# Guardar isso só na interface seria fingir controle: bastaria trocar o
# endereço no navegador.
# /api/agentes entra porque a abertura desenha o quadro real de agentes, e ele
# não contém dinheiro nem nome de terceiro — só quem existe e o que cada um
# ainda não consegue fazer.
ROTAS_DO_SAGUAO = {"/api/eu", "/api/saguao", "/api/agentes"}

# A ponte é a conta que o carteiro usa: ela leva aviso para fora e traz
# demanda para dentro. Não é o CEO com outro nome — ela não alcança número
# do ERP, missão, aprovação nem agente. Se o token dela vazar, o estrago
# possível é o tamanho da fila de avisos, e nada mais.
PREFIXOS_DA_PONTE = ("/api/eu", "/api/avisos", "/api/demandas")


def sessao(request: Request, authorization: str = Header(default="")) -> dict:
    token = authorization.replace("Bearer ", "").strip()
    if not token:
        raise HTTPException(401, "sem credencial")
    s = bd.linha("SELECT * FROM sessao WHERE token=?", (token,))
    if not s or s["expira_em"] < bd.agora():
        raise HTTPException(401, "sessão expirada")
    u = bd.linha("SELECT * FROM usuario WHERE id=?", (s["usuario_id"],))
    if u["papel"] == "saguao" and request.url.path not in ROTAS_DO_SAGUAO:
        raise HTTPException(403, "o painel do saguão não tem acesso a esta área")
    if u["papel"] == "ponte" and not request.url.path.startswith(PREFIXOS_DA_PONTE):
        raise HTTPException(403, "a ponte só alcança a fila de avisos e a caixa de demandas")
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


# ------------------------------------------------------------------ sala do CEO
# O dono da empresa não abre o sistema para navegar: ele abre para saber se
# está tudo de pé. Esta rota junta, num fôlego só, o dinheiro real do ERP, o
# risco estrutural e o que a equipe de agentes está fazendo agora.
#
# O ERP é consultado no máximo uma vez por minuto. Sala do CEO fica aberta na
# TV o dia inteiro; não vou martelar o banco de produção por vaidade.
_CACHE_CEO: dict = {"em": None, "dados": None}
_VALIDADE_CEO = timedelta(seconds=60)


def _ceo_erp(emp: int) -> dict:
    """Números do ERP com carimbo de hora. Falha de uma consulta não derruba
    as outras: cada bloco diz se veio ou por que não veio."""
    saida: dict = {}
    for op, chave in (("ceo.pulso", "pulso"),
                      ("ceo.carteira", "carteira"),
                      ("ceo.concentracao", "concentracao"),
                      ("ceo.serie_mensal", "serie")):
        r = fb.rodar("atua", op, {}, empresa_id=emp,
                     acoes_permitidas=[f"atua.{op}"])
        if r.ok:
            saida[chave] = {"linhas": r.dados.get("linhas", []),
                            "consultada_em": r.dados.get("consultada_em")}
        else:
            saida[chave] = {"erro": r.erro or "consulta não respondeu",
                            "linhas": []}

    # Resultado por setor. Estas consultas pedem janela e recorte explícitos:
    # deixar o padrão implícito faria a tela dizer "90 dias" sem que ninguém
    # tivesse escrito 90 em lugar nenhum.
    for op, chave, par in (
            ("lucratividade.por_setor", "setor",
             {"dias": 90, "cd_pessoa_filial": None}),
            ("lucratividade.por_agencia", "agencia",
             {"dias": 90, "cd_pessoa_filial": None, "limite": 60}),
            # A contraprova refaz o custo da frota por outro caminho do banco.
            # Ela vem para a tela junto com o número que ela contesta: separar
            # os dois deixaria o CEO ler a margem sem ler a dúvida sobre ela.
            ("contraprova.lucratividade_custo_frota", "contraprova_frota",
             {"dias": 90}),
            # A frota so vira decisao quando desce a placa. Trinta cavalos
            # puxam receita; o resto do cadastro so gera despesa, e isso
            # precisa aparecer separado, nao diluido no custo do setor.
            ("frota.resultado_veiculo", "veiculo",
             {"dias": 90, "cd_pessoa_filial": None, "limite": 300})):
        r = fb.rodar("atua", op, par, empresa_id=emp,
                     acoes_permitidas=[f"atua.{op}"])
        if r.ok:
            saida[chave] = {"linhas": r.dados.get("linhas", []),
                            "consultada_em": r.dados.get("consultada_em"),
                            "janela_dias": par["dias"]}
        else:
            saida[chave] = {"erro": r.erro or "consulta não respondeu",
                            "linhas": [], "janela_dias": par["dias"]}
    return saida


def _erp_em_cache(emp: int, forcar: bool = False) -> tuple[dict, str]:
    """Uma leitura do ERP serve as duas telas. A Sala do CEO e o saguão pedem
    o mesmo pulso; sem cache comum, a parede dobraria a carga no banco."""
    agora = bd.agora()
    fresco = (_CACHE_CEO["dados"] is not None and not forcar
              and _CACHE_CEO["em"] is not None
              and (datetime.fromisoformat(agora)
                   - datetime.fromisoformat(_CACHE_CEO["em"])) < _VALIDADE_CEO)
    if fresco:
        return _CACHE_CEO["dados"], _CACHE_CEO["em"]
    erp = _ceo_erp(emp)
    _CACHE_CEO["dados"] = erp
    _CACHE_CEO["em"] = agora
    return erp, agora


@app.get("/api/ceo")
def sala_do_ceo(s: dict = Depends(sessao), forcar: bool = False):
    emp = s["empresa_id"]
    agora = bd.agora()
    erp, lido_em = _erp_em_cache(emp, forcar)

    # ------------------------------------------------------------- a equipe
    # Cada agente com o que ele fez de verdade: quantas missões tocou, quando
    # trabalhou pela última vez e se está executando algo neste instante.
    trabalho = {r["agente_id"]: r for r in bd.linhas(
        "SELECT t.agente_id, COUNT(*) n, MAX(t.atualizada_em) ultima, "
        "SUM(CASE WHEN t.estado IN ('despachada','executando') THEN 1 ELSE 0 END) agora "
        "FROM tarefa t WHERE t.empresa_id=? AND t.agente_id IS NOT NULL "
        "GROUP BY t.agente_id", (emp,))}

    equipe = []
    for d in ar.todos():
        sit, motivo = d.situacao()
        w = trabalho.get(d.id) or {}
        equipe.append({
            "codigo": d.id, "nome": d.nome, "papel": d.papel,
            "area": d.area, "situacao": sit, "limitacao": motivo,
            "tarefas": int(w.get("n") or 0),
            "trabalhando_agora": int(w.get("agora") or 0) > 0,
            "ultima_vez": w.get("ultima"),
        })
    equipe.sort(key=lambda a: (a["situacao"] != "habilitado", -a["tarefas"], a["nome"]))

    # ------------------------------------------------------------- a operação
    em_curso = bd.linhas(
        "SELECT id, objetivo, estado, criada_em FROM missao WHERE empresa_id=? "
        "AND estado IN ('planejada','executando','validando','replanejando') "
        "ORDER BY id DESC", (emp,))

    # --------------------------------------------- a palavra do auditor
    # O número do custo da frota é contestado por um agente, não por uma regra
    # escondida no código. Quem contestou, quando e com que veredito vai para
    # a tela; sem isso a contraprova vira enfeite.
    aud = bd.linha(
        "SELECT e.resumo, e.resultado, e.criada_em, e.status_declarado, "
        "e.missao_id, t.agente_id, t.chave "
        "FROM entrega e JOIN tarefa t ON t.id=e.tarefa_id "
        "WHERE e.empresa_id=? AND t.agente_id='controladoria.margem' "
        "AND t.chave LIKE '%#c%' ORDER BY e.id DESC LIMIT 1", (emp,))
    contraprova = None
    if aud:
        res = bd.dj(aud["resultado"], {}) or {}
        d_aud = ar.obter(aud["agente_id"])
        contraprova = {
            "auditor": d_aud.nome if d_aud else aud["agente_id"],
            "papel": d_aud.papel if d_aud else None,
            "veredito": res.get("veredito"),
            "resumo": aud["resumo"],
            "dados": {k: v for k, v in res.items() if k != "veredito"},
            "dita_em": aud["criada_em"],
            "missao_id": aud["missao_id"],
        }

    # ------------------------------------- o plano placa a placa e a dúvida
    # A apuração por veículo diz quem está no vermelho; o plano diz o que
    # fazer com cada placa. Os dois andam juntos com a contestação da Vera:
    # ela é quem confere, pelo hodômetro, se o quilômetro que sustenta o
    # diagnóstico existe. Plano sem essa dúvida ao lado vira ordem de serviço
    # apoiada em número não conferido.
    ap = bd.linha(
        "SELECT e.resumo, e.resultado, e.criada_em, e.missao_id, t.agente_id "
        "FROM entrega e JOIN tarefa t ON t.id=e.tarefa_id "
        "WHERE e.empresa_id=? AND t.agente_id='controladoria.margem' "
        "AND t.chave NOT LIKE '%#c%' AND e.resultado LIKE '%\"plano\"%' "
        "ORDER BY e.id DESC LIMIT 1", (emp,))
    plano_frota = None
    if ap:
        res = bd.dj(ap["resultado"], {}) or {}
        d_ap = ar.obter(ap["agente_id"])
        duvida = bd.linha(
            "SELECT e.resumo, e.resultado, e.criada_em, t.agente_id "
            "FROM entrega e JOIN tarefa t ON t.id=e.tarefa_id "
            "WHERE e.empresa_id=? AND e.missao_id=? AND t.chave LIKE '%#c%' "
            "ORDER BY e.id DESC LIMIT 1", (emp, ap["missao_id"]))
        contesta = None
        if duvida:
            rd = bd.dj(duvida["resultado"], {}) or {}
            d_rev = ar.obter(duvida["agente_id"])
            contesta = {"auditor": d_rev.nome if d_rev else duvida["agente_id"],
                        "papel": d_rev.papel if d_rev else None,
                        "veredito": rd.get("veredito"),
                        "resumo": duvida["resumo"],
                        "dados": {k: v for k, v in rd.items()
                                  if k != "veredito"},
                        "dita_em": duvida["criada_em"]}
        plano_frota = {
            "analista": d_ap.nome if d_ap else ap["agente_id"],
            "papel": d_ap.papel if d_ap else None,
            "resumo": ap["resumo"], "dados": res,
            "dita_em": ap["criada_em"], "missao_id": ap["missao_id"],
            "contestacao": contesta,
        }

    hoje = agora[:10]
    return {
        "contraprova_frota": contraprova,
        "plano_frota": plano_frota,
        "empresa": bd.linha("SELECT nome, cnpj FROM empresa WHERE id=?", (emp,)),
        "erp": erp,
        "lido_em": lido_em,
        "equipe": equipe,
        "operacao": {
            "em_curso": em_curso,
            "concluidas_hoje": int(bd.linha(
                "SELECT COUNT(*) n FROM missao WHERE empresa_id=? AND "
                "estado='concluida' AND substr(encerrada_em,1,10)=?",
                (emp, hoje))["n"] or 0),
            "evidencias_hoje": int(bd.linha(
                "SELECT COUNT(*) n FROM evidencia WHERE empresa_id=? AND "
                "substr(criada_em,1,10)=?", (emp, hoje))["n"] or 0),
            "consultas_hoje": int(bd.linha(
                "SELECT COUNT(*) n FROM execucao_ferramenta WHERE empresa_id=? "
                "AND substr(iniciada_em,1,10)=?", (emp, hoje))["n"] or 0),
            "reprovacoes_abertas": int(bd.linha(
                "SELECT COUNT(*) n FROM validacao WHERE empresa_id=? AND "
                "resultado='reprovado'", (emp,))["n"] or 0),
            "aprovacoes_pendentes": int(bd.linha(
                "SELECT COUNT(*) n FROM acao_externa WHERE empresa_id=? AND "
                "estado IN ('proposta','aguardando')", (emp,))["n"] or 0),
        },
        "gerado_em": agora,
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
def _quem_ele_audita(aid: str) -> list[str]:
    """Quais agentes este aqui é chamado para contestar."""
    from nucleo.orquestrador import CONTRAPROVA
    return [dono for dono, cps in CONTRAPROVA.items()
            if any(c["agente"] == aid for c in cps)]


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
            # audita = tem contraprova implementada: sabe refazer o número de
            # outro agente por um caminho diferente do banco.
            "audita": d.auditor is not None,
            "audita_quem": _quem_ele_audita(d.id),
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



# --------------------------------------------------------------- ritmo do dia
@app.get("/api/agenda")
def agenda(s: dict = Depends(sessao)):
    """O dia da NÓRIA: o que já rodou, o que está rodando, o que vem depois.

    Existe porque o sistema parecia morto entre uma varredura e outra. Estava
    apenas em silêncio — mas silêncio sem agenda visível é indistinguível de
    defeito. Agora o repouso tem hora marcada e o CEO vê a fila do dia.
    """
    import agendador as ag

    emp = s["empresa_id"]
    agora = datetime.now(bd.FUSO)
    hoje = agora.date()
    dia = hoje.weekday()

    itens = []
    for chave, nome, hora, dias, _fn in ag.ROTINAS:
        if dias is not None and dia not in dias:
            continue
        # O agendador grava a data como JSON simples ("2026-09-05"), não como
        # objeto. Ler com .get() estourava a rota inteira em AttributeError.
        marcador = bd.linha("SELECT valor FROM marcador WHERE chave=?",
                            (f"rotina:{chave}", ))
        rodou = bool(marcador) and \
            bd.dj(marcador["valor"], None) == hoje.isoformat()
        agente = (ag.VIGILANCIA.get(chave) or (None,))[0] \
            or ("tesouraria.conciliador" if chave == "conciliacao"
                else "cobranca.carteira")
        d = ar.obter(agente)
        itens.append({
            "chave": chave, "nome": nome, "hora": hora,
            "agente_id": agente, "agente": d.nome if d else agente,
            "estado": "feito" if rodou else
                      ("atrasado" if agora.hour > hora else "previsto"),
        })

    # Sentinela: não tem hora, tem intervalo. É o que dá pulso ao resto.
    # A chave é a que a sentinela realmente grava. Antes eu inventei um nome
    # parecido, e a vigília aparecia morta mesmo estando viva.
    ultimo = bd.linha("SELECT valor FROM marcador WHERE chave=?",
                      ("pulso.faturamento", ))
    vigilia = (bd.dj(ultimo["valor"], {}) or {}).get("em") if ultimo else None

    return {
        "hoje": hoje.isoformat(),
        "agora": agora.isoformat(),
        "dia_util": dia < 5,
        "itens": sorted(itens, key=lambda x: x["hora"]),
        "feitos": sum(1 for i in itens if i["estado"] == "feito"),
        "vigilia": {
            "intervalo_s": ag.INTERVALO_VIGILIA,
            "ultima_leitura": vigilia,
        },
        "agentes": {
            "total": len(ar.todos()),
            "operando": sum(1 for d in ar.todos()
                            if d.situacao()[0] == "habilitado"),
        },
        "em_curso": bd.linhas(
            "SELECT t.id, t.agente_id, t.estado, t.atualizada_em, m.objetivo "
            "FROM tarefa t JOIN missao m ON m.id = t.missao_id "
            "WHERE t.empresa_id=? AND t.estado IN "
            "('despachada','executando') ORDER BY t.id DESC LIMIT 10", (emp,)),
        "ultimas_entregas": bd.linhas(
            "SELECT e.id, e.resumo, e.status_declarado, e.criada_em, "
            "       t.agente_id, t.estado AS veredito "
            "FROM entrega e JOIN tarefa t ON t.id = e.tarefa_id "
            "WHERE e.empresa_id=? ORDER BY e.id DESC LIMIT 8", (emp,)),
    }


# --------------------------------------------------------------------- saguão
def _so_numero(linha: dict, campos: tuple[str, ...]) -> dict:
    """Deixa passar apenas os campos escolhidos. Nada de valor em reais e nada
    de nome de terceiro sai desta rota: a filtragem é por lista de permissão,
    não por remoção, porque esquecer de remover é fácil demais."""
    return {c: linha.get(c) for c in campos}


@app.get("/api/saguao")
def saguao(s: dict = Depends(sessao)):
    """Painel de parede. Mostra que a empresa opera e que a NÓRIA vigia, sem
    revelar quanto ela fatura, quem deve e o que está sob suspeita.

    O que entra aqui: contagem de documentos, ritmo mensal em quantidade, a
    equipe de agentes e a agenda de varreduras. O que nunca entra: reais,
    nome de cliente, texto de achado e decisão pendente.
    """
    import agendador as ag

    emp = s["empresa_id"]
    agora = datetime.now(bd.FUSO)
    hoje = agora.date().isoformat()
    erp, lido_em = _erp_em_cache(emp)

    pulso = (erp.get("pulso", {}).get("linhas") or [{}])[0]
    serie = [_so_numero(l, ("mes", "qt"))
             for l in (erp.get("serie", {}).get("linhas") or [])]

    equipe = []
    trabalhando = {r["agente_id"] for r in bd.linhas(
        "SELECT DISTINCT agente_id FROM tarefa WHERE empresa_id=? AND "
        "estado IN ('despachada','executando')", (emp,))}
    for d in ar.todos():
        sit, _motivo = d.situacao()
        equipe.append({"nome": d.nome, "area": d.area, "papel": d.papel,
                       "situacao": sit,
                       "trabalhando_agora": d.id in trabalhando})
    equipe.sort(key=lambda a: (a["area"], a["nome"]))

    dia = agora.weekday()
    rotinas = []
    for chave, nome, hora, dias, _fn in ag.ROTINAS:
        if dias is not None and dia not in dias:
            continue
        m = bd.linha("SELECT valor FROM marcador WHERE chave=?",
                     (f"rotina:{chave}",))
        rodou = bool(m) and bd.dj(m["valor"], None) == hoje
        rotinas.append({"nome": nome, "hora": hora,
                        "estado": "feito" if rodou else
                                  ("atrasado" if agora.hour > hora
                                   else "previsto")})
    rotinas.sort(key=lambda r: r["hora"])

    def n(sql, args=()):
        return int((bd.linha(sql, args) or {}).get("n") or 0)

    areas = sorted({d.area for d in ar.todos()})
    return {
        "empresa": (bd.linha("SELECT nome FROM empresa WHERE id=?",
                             (emp,)) or {}).get("nome"),
        "agora": agora.isoformat(timespec="seconds"),
        "lido_em": lido_em,
        "operacao": {
            "ctes_hoje": int(pulso.get("ctes_hoje") or 0),
            "ctes_mes": int(pulso.get("ctes_mes") or 0),
            "ctes_12m": int(pulso.get("ctes_12m") or 0),
            "serie": serie,
            "erro": erp.get("pulso", {}).get("erro"),
        },
        "equipe": equipe,
        "areas": areas,
        "rotinas": rotinas,
        "nucleo": {
            "agentes": len(ar.todos()),
            "habilitados": sum(1 for d in ar.todos()
                               if d.situacao()[0] == "habilitado"),
            "areas": len(areas),
            "camadas": 6,
            # Par é mão dupla: comercial contesta o fiscal e o fiscal contesta
            # o comercial contam como um par só, igual à abertura.
            "pares_contraprova": len({
                frozenset((quem, c["agente"]))
                for quem, lista in orq.CONTRAPROVA.items() for c in lista}),
            "conferencias_hoje": n(
                "SELECT COUNT(*) n FROM validacao WHERE empresa_id=? AND "
                "substr(criada_em,1,10)=?", (emp, hoje)),
            "conferencias_total": n(
                "SELECT COUNT(*) n FROM validacao WHERE empresa_id=?", (emp,)),
            "consultas_hoje": n(
                "SELECT COUNT(*) n FROM execucao_ferramenta WHERE empresa_id=? "
                "AND substr(iniciada_em,1,10)=?", (emp, hoje)),
            "evidencias": n(
                "SELECT COUNT(*) n FROM evidencia WHERE empresa_id=?", (emp,)),
            "missoes_concluidas": n(
                "SELECT COUNT(*) n FROM missao WHERE empresa_id=? AND "
                "estado='concluida'", (emp,)),
            "missoes_em_curso": n(
                "SELECT COUNT(*) n FROM missao WHERE empresa_id=? AND estado "
                "IN ('planejada','executando','validando','replanejando')",
                (emp,)),
        },
    }


# --------------------------------------------------------- avisos e demandas
# A NÓRIA decide o que merece sair daqui; quem entrega é trocável. Estas
# rotas são o balcão: de um lado a fila do que ela quer contar, do outro a
# caixa do que chegou de fora pedindo resposta.
@app.get("/api/avisos")
def listar_avisos(s: dict = Depends(sessao), estado: str = "pendente",
                  limite: int = Query(50, le=200)):
    return {"avisos": bd.linhas(
        "SELECT * FROM aviso WHERE empresa_id=? AND estado=? "
        "ORDER BY CASE gravidade WHEN 'alta' THEN 0 ELSE 1 END, id "
        "LIMIT ?", (s["empresa_id"], estado, limite))}


@app.post("/api/avisos/{aid}/entregue")
def aviso_entregue(aid: int, dados: dict = Body(default={}),
                   s: dict = Depends(sessao)):
    a = bd.linha("SELECT * FROM aviso WHERE id=? AND empresa_id=?",
                 (aid, s["empresa_id"]))
    if not a:
        raise HTTPException(404, "aviso não encontrado")
    bd.executar("UPDATE aviso SET estado=?, canal=?, referencia=?, entregue_em=? "
                "WHERE id=?", (dados.get("estado") or "entregue",
                               dados.get("canal"), dados.get("referencia"),
                               bd.agora(), aid))
    return {"ok": True, "id": aid}


@app.post("/api/demandas")
def receber_demandas(dados: dict = Body(...), s: dict = Depends(sessao)):
    """Entrada de mensagens vindas de fora. Repetida não entra duas vezes:
    o id da origem é único, então a ponte pode rodar quantas vezes quiser."""
    emp = s["empresa_id"]
    novas, repetidas = [], 0
    for m in (dados.get("mensagens") or []):
        ext = str(m.get("externo_id") or "").strip()
        if not ext:
            continue
        if bd.linha("SELECT id FROM demanda WHERE canal=? AND externo_id=?",
                    (m.get("canal") or "outlook", ext)):
            repetidas += 1
            continue
        novas.append(bd.inserir("demanda", {
            "empresa_id": emp, "canal": m.get("canal") or "outlook",
            "externo_id": ext, "conversa_id": m.get("conversa_id"),
            "de": m.get("de"), "para": m.get("para"),
            "assunto": m.get("assunto"), "trecho": m.get("trecho"),
            "recebida_em": m.get("recebida_em"),
            "classe": m.get("classe") or "ruido",
            "assunto_operacional": m.get("assunto_operacional"),
            "quem_responde": m.get("quem_responde"), "prazo": m.get("prazo"),
            "estado": "aberta", "link": m.get("link"),
            "criada_em": bd.agora()}))
    return {"recebidas": len(novas), "repetidas": repetidas, "ids": novas}


@app.get("/api/demandas")
def listar_demandas(s: dict = Depends(sessao), estado: str | None = None,
                    classe: str | None = None, limite: int = Query(60, le=200)):
    sql = "SELECT * FROM demanda WHERE empresa_id=?"
    a: list = [s["empresa_id"]]
    if estado:
        sql += " AND estado=?"
        a.append(estado)
    if classe:
        sql += " AND classe=?"
        a.append(classe)
    sql += " ORDER BY recebida_em DESC, id DESC LIMIT ?"
    a.append(limite)
    return {"demandas": bd.linhas(sql, tuple(a))}


@app.post("/api/demandas/{did}/missao")
def demanda_vira_missao(did: int, dados: dict = Body(default={}),
                        s: dict = Depends(sessao)):
    """Uma pergunta que chegou de fora vira trabalho de agente. A demanda
    guarda o número da missão: assim a resposta tem de onde vir, e ninguém
    responde cliente de memória."""
    d = bd.linha("SELECT * FROM demanda WHERE id=? AND empresa_id=?",
                 (did, s["empresa_id"]))
    if not d:
        raise HTTPException(404, "demanda não encontrada")
    if d["missao_id"]:
        return {"ok": True, "missao_id": d["missao_id"], "ja_existia": True}
    objetivo = (dados.get("objetivo") or "").strip() or (
        f"Levantar no ATUA o que responde: {d['assunto'] or d['trecho'] or ''}")
    ctx = dict(dados.get("contexto") or {})
    ctx.setdefault("demanda_id", did)
    ctx.setdefault("chave", f"demanda:{did}")
    mid = orq.abrir_missao(s["empresa_id"], objetivo, contexto=ctx,
                           origem="demanda", prioridade=dados.get("prioridade")
                           or "alta")
    bd.executar("UPDATE demanda SET estado='em_missao', missao_id=? WHERE id=?",
                (mid, did))
    return {"ok": True, "missao_id": mid}


# --------------------------------------------------------------------- NÓRIA
# O pensamento da NÓRIA é lateral: se a pasta não existir, estes endpoints respondem
# "desligado" e o resto da NÓRIA segue igual.
def _pensamento():
    try:
        from pensamento import cliente as cx
        return cx
    except Exception:
        return None


@app.get("/api/pensamento")
def pensamento_estado(s: dict = Depends(sessao)):
    """o que a NÓRIA pensou, o que ela provou e quanto custou."""
    cx = _pensamento()
    if cx is None:
        return {"ligado": False, "motivo": "o pensamento não está instalado neste servidor"}
    try:
        est = cx.estado()
    except Exception as e:
        return {"ligado": False, "motivo": f"pensamento sem base: {e}"}

    emp = s["empresa_id"]
    try:
        hips = bd.linhas(
            "SELECT id, pergunta, motivo, aposta, estado, leitura, criada_em, "
            "decidida_em FROM hipotese WHERE empresa_id=? "
            "ORDER BY id DESC LIMIT 30", (emp,))
        contagem = {r["estado"]: r["n"] for r in bd.linhas(
            "SELECT estado, COUNT(*) AS n FROM hipotese WHERE empresa_id=? "
            "GROUP BY estado", (emp,))}
    except Exception as e:
        return {"ligado": False, "motivo": f"tabelas do pensamento ausentes: {e}"}

    for h in hips:
        h["consultas"] = bd.linhas(
            "SELECT papel, porta, grao, linhas, recusa, erro, rodou_em, sql "
            "FROM consulta_proposta WHERE hipotese_id=? ORDER BY id", (h["id"],))
    return {"ligado": bool(est.get("chave")), "estado": est,
            "contagem": contagem, "hipoteses": hips}


@app.get("/api/pensamento/hipoteses/{hid}")
def pensamento_hipotese(hid: int, s: dict = Depends(sessao)):
    h = bd.linha("SELECT * FROM hipotese WHERE id=? AND empresa_id=?",
                 (hid, s["empresa_id"]))
    if not h:
        raise HTTPException(404, "hipótese não encontrada")
    h["consultas"] = bd.linhas(
        "SELECT * FROM consulta_proposta WHERE hipotese_id=? ORDER BY id", (hid,))
    h["raciocinio"] = bd.linhas(
        "SELECT passo, texto, criado_em FROM raciocinio WHERE hipotese_id=? "
        "ORDER BY id", (hid,))
    return h


@app.post("/api/pensamento/hipoteses/{hid}/decidir")
def pensamento_decidir(hid: int, dados: dict = Body(...), s: dict = Depends(sessao)):
    """O CEO aceita ou rejeita o que a NÓRIA levantou. Sem isso, nada vira fato."""
    if (s["usuario"]["papel"] or "") not in ("ceo", "gestor"):
        raise HTTPException(403, "só o CEO decide hipótese")
    decisao = (dados.get("decisao") or "").strip()
    if decisao not in ("aceitar", "rejeitar"):
        raise HTTPException(400, "decisão deve ser aceitar ou rejeitar")
    h = bd.linha("SELECT * FROM hipotese WHERE id=? AND empresa_id=?",
                 (hid, s["empresa_id"]))
    if not h:
        raise HTTPException(404, "hipótese não encontrada")
    novo = "confirmada" if decisao == "aceitar" else "rejeitada"
    bd.executar("UPDATE hipotese SET estado=?, decidida_em=? WHERE id=?",
                (novo, bd.agora(), hid))
    return {"ok": True, "estado": novo}


# ------------------------------------------------------------------- estático
WEB = RAIZ / "web"
if WEB.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
