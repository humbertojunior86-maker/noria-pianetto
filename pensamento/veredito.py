"""Veredito — a hipótese encara o banco.

Roda a consulta principal e a contraprova, entrega as LINHAS à NÓRIA e pede
uma leitura em português. O conferente confere número por número: o que não
tiver lastro nas linhas devolvidas bloqueia a leitura inteira. Confirmada,
vira aprendizado em estado proposto, esperando o aval do CEO.
"""
from __future__ import annotations

import json

from nucleo import bd
from . import cliente, conferente, prova

SISTEMA = """Você é a NÓRIA lendo o resultado de uma prova.

Recebeu: a pergunta, o SQL que rodou e as LINHAS que o banco devolveu.

Sua tarefa é dizer se a hipótese foi confirmada, derrubada ou ficou
inconclusiva, e escrever uma leitura curta em português do Brasil.

Regras que não se negociam:
- todo número que você escrever tem de estar nas linhas recebidas; se não
  estiver, sua resposta é bloqueada;
- se a principal e a contraprova discordam, o veredito é "inconclusiva" e a
  leitura tem de apontar QUAL DEFINIÇÃO difere entre as duas, não escolher a
  maior;
- zero linha não é prova de nada: é "inconclusiva";
- decimais com vírgula, sem emoji, sem exagero, sem adjetivo de vendedor;
- contribuição nunca é lucro; saldo em aberto nunca é dinheiro perdido.

Formato, JSON puro:
{"veredito":"confirmada|derrubada|inconclusiva",
 "leitura":"até quatro frases",
 "vale_aprendizado":true|false,
 "enunciado":"a frase que a casa deve guardar, com o número e a porta"}
"""


def _br(v: float) -> str:
    """Número em português: milhar com ponto, decimal com vírgula."""
    return f"{v:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _linhas_da(cp_id):
    cp = bd.linha("SELECT resultado_json FROM consulta_proposta WHERE id=?", (cp_id,))
    return bd.dj(cp["resultado_json"], []) if cp and cp["resultado_json"] else []


def provar(hipotese_id: int, respeitar_janela: bool = True) -> dict:
    h = bd.linha("SELECT * FROM hipotese WHERE id=?", (hipotese_id,))
    if not h:
        return {"ok": False, "erro": "hipótese não existe"}

    bd.executar("UPDATE hipotese SET estado='em_prova' WHERE id=?", (hipotese_id,))
    consultas = bd.linhas(
        "SELECT * FROM consulta_proposta WHERE hipotese_id=? ORDER BY id",
        (hipotese_id,))

    resultados, portas_ok = {}, []
    for cp in consultas:
        r = prova.executar_proposta(cp["id"], respeitar_janela)
        resultados[cp["papel"]] = r
        if r.get("ok"):
            portas_ok.append(cp["papel"])
        bd.inserir("raciocinio", {
            "hipotese_id": hipotese_id, "passo": 2,
            "texto": f"{cp['papel']}: " + (
                f"{len(r.get('linhas', []))} linha(s)" if r.get("ok")
                else "barrada — " + (r.get("recusa") or r.get("erro") or "")),
            "criado_em": bd.agora()})

    if "principal" not in portas_ok:
        motivo = (resultados.get("principal", {}).get("recusa")
                  or resultados.get("principal", {}).get("erro")
                  or "consulta principal não rodou")
        bd.executar("UPDATE hipotese SET estado='inconclusiva', leitura=?, "
                    "decidida_em=? WHERE id=?", (motivo, bd.agora(), hipotese_id))
        return {"ok": False, "estado": "inconclusiva", "motivo": motivo}

    principais = resultados["principal"]["linhas"]
    contra = resultados.get("contraprova", {}).get("linhas") if \
        resultados.get("contraprova", {}).get("ok") else None

    pedido = json.dumps({
        "pergunta": h["pergunta"], "motivo": h["motivo"], "aposta": h["aposta"],
        "sql_principal": resultados["principal"]["sql"],
        "linhas_principal": principais[:60],
        "sql_contraprova": (resultados.get("contraprova") or {}).get("sql"),
        "linhas_contraprova": (contra or [])[:60],
        "consultada_em": resultados["principal"]["consultada_em"],
    }, ensure_ascii=False, default=str)[:60000]

    r = cliente.pensar_json("veredito", SISTEMA, pedido)
    leitura = (r.get("leitura") or "").strip()
    veredito = (r.get("veredito") or "inconclusiva").strip()
    if veredito not in ("confirmada", "derrubada", "inconclusiva"):
        veredito = "inconclusiva"

    lastro = list(principais) + list(contra or [])
    check = conferente.conferir(leitura + " " + (r.get("enunciado") or ""), lastro)
    if not check["ok"]:
        aviso = ("leitura bloqueada pelo conferente: número sem lastro nas "
                 "linhas do banco — " + ", ".join(_br(n) for n in check["orfaos"]))
        bd.executar("UPDATE hipotese SET estado='inconclusiva', leitura=?, "
                    "decidida_em=? WHERE id=?", (aviso, bd.agora(), hipotese_id))
        bd.inserir("raciocinio", {"hipotese_id": hipotese_id, "passo": 3,
                                  "texto": aviso, "criado_em": bd.agora()})
        return {"ok": False, "estado": "inconclusiva", "motivo": aviso}

    bd.executar("UPDATE hipotese SET estado=?, leitura=?, decidida_em=? WHERE id=?",
                (veredito, leitura, bd.agora(), hipotese_id))
    bd.inserir("raciocinio", {"hipotese_id": hipotese_id, "passo": 3,
                              "texto": f"veredito {veredito}: {leitura}",
                              "criado_em": bd.agora()})

    aprendizado_id = None
    if veredito == "confirmada" and r.get("vale_aprendizado") and r.get("enunciado"):
        selo = "conferido" if contra else "apurado"
        aprendizado_id = bd.inserir("aprendizado", {
            "empresa_id": h["empresa_id"],
            "enunciado": r["enunciado"].strip()[:2000],
            "origem": f"NÓRIA · ATUA ({selo} em {bd.agora()[:10]}) · hipótese {hipotese_id}",
            "escopo": "pensamento", "estado": "proposto", "criado_em": bd.agora()})

    return {"ok": True, "estado": veredito, "leitura": leitura,
            "portas": portas_ok, "aprendizado_id": aprendizado_id,
            "linhas_principal": len(principais)}


def provar_pendentes(limite: int = 5, respeitar_janela: bool = True) -> list[dict]:
    alvos = bd.linhas(
        "SELECT id FROM hipotese WHERE estado='levantada' ORDER BY id LIMIT ?",
        (limite,))
    return [{"hipotese": a["id"], **provar(a["id"], respeitar_janela)}
            for a in alvos]
