"""A conferência diária do seguro dos terceiros, entregue por e-mail.

Roda fora do servidor da NÓRIA, porque é aqui que existe a conexão com o
Outlook. Não pensa e não calcula: pede a apuração pronta à NÓRIA
(`/api/seguro/diario`, que executa os vigias 21 e 22 no ATUA na hora) e
escreve o e-mail carga por carga.

Duas listas, por naturezas diferentes:

  1. seguro descontado de quem não pode sofrer desconto (TAC e equiparado)
     — passivo de devolução e prova contra a casa;
  2. viagem de quem devia sofrer desconto e saiu sem (ETC e cooperativa)
     — margem que ficou no caminho.

Se as duas listas vierem vazias, nenhum e-mail sai. Silêncio declarado vale
mais que movimento inventado.

Uso:
    python3 seguro_diario.py
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import urllib.request

# Quantas linhas cabem no corpo do e-mail antes de virar parede. O resto vai
# inteiro no anexo: ninguém perde uma carta frete por causa de layout.
NO_CORPO = 60

NORIA = os.environ.get("NORIA_URL", "http://174.138.92.164")
EMAIL = os.environ.get("NORIA_EMAIL", "humbertojunior86@gmail.com")
SENHA = os.environ.get("NORIA_SENHA", "pianetto")
DESTINOS = [d.strip() for d in os.environ.get(
    "NORIA_SEGURO_DESTINOS",
    "humberto@pianettotransportes.com.br,"
    "controladoria@pianettotransportes.com.br,"
    "fiscal@pianettotransportes.com.br").split(",") if d.strip()]

TITULOS = {
    "descontado_de_quem_nao_pode": (
        "Seguro descontado de quem não pode sofrer desconto",
        "TAC e equiparado a TAC. Cada linha é um valor retido que a empresa "
        "terá de devolver e que serve de prova contra ela em reclamação "
        "trabalhista ou fiscalização da ANTT."),
    "sem_desconto_de_quem_devia": (
        "Viagem sem o desconto de seguro",
        "ETC e cooperativa, de quem o desconto é devido. O valor é a taxa que "
        "o próprio produto arrecadou nos últimos 180 dias aplicada ao valor da "
        "carga daquele CT-e — estimativa, não extrato."),
}


# ----------------------------------------------------------------- utilidades
def _http(caminho: str, corpo: dict | None = None, token: str | None = None):
    req = urllib.request.Request(
        NORIA + caminho,
        data=json.dumps(corpo).encode() if corpo is not None else None,
        headers={"content-type": "application/json",
                 **({"authorization": f"Bearer {token}"} if token else {})},
        method="POST" if corpo is not None else "GET")
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())


def outlook(ferramenta: str, entrada: dict) -> dict:
    p = subprocess.run(["pplx", "connector", "call", "outlook", ferramenta,
                        "--input", json.dumps(entrada)],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[:500])
    r = json.loads(p.stdout)
    if r.get("is_error"):
        raise RuntimeError(str(r.get("error"))[:500])
    return r.get("result") or {}


def reais(v) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    return f"{n:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


def rotulo(c: str) -> str:
    return c.replace("_", " ").capitalize()


# --------------------------------------------------------------------- e-mail
def tabela(bloco: dict, corte: int) -> str:
    """Tabela enxuta de propósito. O pedido ao correio viaja como argumento de
    linha de comando, e argumento tem teto: HTML gordo não chega a ninguém."""
    linhas = bloco["linhas"]
    if not linhas:
        return ""
    cols = list(linhas[0].keys())
    num = {bloco["campo_valor"], "frete", "valor_carga"}
    cab = "".join(
        f'<th align="{"right" if c in num else "left"}">{rotulo(c)}</th>'
        for c in cols)
    corpo = []
    for ln in linhas[:corte]:
        tds = []
        for c in cols:
            v = ln.get(c)
            txt = reais(v) if c in num else ("" if v is None else str(v))
            tds.append(f'<td align="{"right" if c in num else "left"}">{txt}</td>')
        corpo.append("<tr>" + "".join(tds) + "</tr>")
    resto = ""
    if len(linhas) > corte:
        resto = ('<div style="font:400 12px/1.5 Arial;color:#64748b;margin-top:8px">'
                 f'Mais {len(linhas) - corte} carta(s) frete na planilha em '
                 'anexo. Aqui estão as de maior valor.</div>')
    return ('<table cellpadding="5" cellspacing="0" border="0" '
            'style="width:100%;border-collapse:collapse;margin-top:10px;'
            'font:400 11px/1.4 Arial;color:#334155">'
            f'<tr style="font-weight:700;color:#0f172a;'
            f'border-bottom:1px solid #cbd5e1">{cab}</tr>'
            f'{"".join(corpo)}</table>' + resto)


def secao(bloco: dict, corte: int) -> str:
    titulo, explica = TITULOS.get(bloco["chave"], (bloco.get("nome", ""), ""))
    if not bloco.get("ok"):
        return ('<div style="margin-top:26px">'
                f'<div style="font:700 15px/1.3 Arial;color:#0f172a">{titulo}</div>'
                '<div style="font:400 12px/1.5 Arial;color:#b45309;margin-top:6px">'
                'Esta conferência não rodou hoje. Motivo: '
                f'{bloco.get("motivo", "não informado")}.</div></div>')
    cabeca = (
        '<div style="margin-top:26px">'
        f'<div style="font:700 15px/1.3 Arial;color:#0f172a">{titulo}</div>'
        f'<div style="font:400 12px/1.5 Arial;color:#64748b;margin-top:4px">'
        f'{explica}</div>'
        f'<div style="font:700 13px/1.5 Arial;color:#0f172a;margin-top:8px">'
        f'{bloco["qt"]} carta(s) frete · R$ {reais(bloco["total"])}</div>')
    if not bloco["linhas"]:
        return cabeca + ('<div style="font:400 12px/1.5 Arial;color:#15803d;'
                         'margin-top:6px">Nenhuma ocorrência hoje.</div></div>')
    return cabeca + tabela(bloco, corte) + "</div>"


def montar(blocos: list[dict], corte: int = NO_CORPO) -> tuple[str, str, str]:
    a = next((b for b in blocos if b["chave"] == "descontado_de_quem_nao_pode"), {})
    b = next((b for b in blocos if b["chave"] == "sem_desconto_de_quem_devia"), {})
    partes = []
    if a.get("qt"):
        partes.append(f"{a['qt']} desconto(s) indevido(s)")
    if b.get("qt"):
        partes.append(f"{b['qt']} viagem(ns) sem desconto")
    assunto = "NÓRIA · Seguro dos terceiros · " + (" · ".join(partes) or "sem ocorrência")
    html = (
        '<div style="max-width:900px;margin:0 auto;padding:24px;'
        'font-family:Arial,Helvetica,sans-serif">'
        '<div style="font:700 13px/1 Arial;letter-spacing:.22em;color:#0f172a">'
        'N Ó R I A</div>'
        '<div style="font:400 13px/1.5 Arial;color:#64748b;margin-top:6px">'
        'Conferência diária do desconto de seguro dos terceiros, carga por '
        'carga. Todo número saiu do ATUA na hora desta leitura. O enquadramento '
        'vem do próprio CT-e: ETC e cooperativa sofrem desconto, TAC e '
        'equiparado a TAC não.</div>'
        + "".join(secao(x, corte) for x in blocos)
        + '<div style="font:400 12px/1.5 Arial;color:#94a3b8;margin-top:22px">'
        f'Sala do CEO: {NORIA}</div></div>')
    texto = "\n".join(
        f"{TITULOS.get(x['chave'], ('', ''))[0]}: "
        + (f"{x.get('qt', 0)} carta(s) frete, R$ {reais(x.get('total', 0))}"
           if x.get("ok") else f"não rodou — {x.get('motivo', '')}")
        for x in blocos)
    return assunto, html, texto


def planilhas(blocos: list[dict]) -> list[str]:
    """Uma planilha por lista, com TODAS as cartas frete. O corpo do e-mail
    mostra as maiores; o anexo carrega a conferência inteira."""
    pasta = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "anexos")
    os.makedirs(pasta, exist_ok=True)
    fora = []
    for b in blocos:
        if not b.get("ok") or not b.get("linhas"):
            continue
        caminho = os.path.join(pasta, f"{b['chave']}.csv")
        cols = list(b["linhas"][0].keys())
        with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols, delimiter=";")
            w.writeheader()
            for ln in b["linhas"]:
                w.writerow({c: ln.get(c) for c in cols})
        fora.append(caminho)
    return fora


# ----------------------------------------------------------------------- roda
def rodar() -> dict:
    tok = _http("/api/entrar", {"email": EMAIL, "senha": SENHA})["token"]
    blocos = _http("/api/seguro/diario", token=tok).get("blocos") or []
    achou = sum(int(x.get("qt") or 0) for x in blocos if x.get("ok"))
    falhou = [x for x in blocos if not x.get("ok")]
    if not achou and not falhou:
        return {"enviado": False, "motivo": "nenhuma ocorrência hoje"}
    # O pedido ao correio vira um argumento de linha de comando: acima de
    # ~100 mil caracteres o sistema recusa. Encolhe o corpo até caber; a
    # planilha em anexo continua com todas as cartas frete.
    corte = NO_CORPO
    while True:
        assunto, html, texto = montar(blocos, corte)
        if len(html) <= 90000 or corte <= 5:
            break
        corte = max(5, corte // 2)
    anexos = planilhas(blocos)
    pedido = {"action": "send", "to": DESTINOS, "cc": [], "bcc": [],
              "subject": assunto, "html_body": html, "body": texto}
    try:
        outlook("send_email", dict(pedido, attachment_files=anexos))
    except Exception:  # noqa: BLE001
        # Anexo é conforto, não é a notícia. Se o correio recusar o arquivo,
        # o e-mail sai mesmo assim e diz que saiu sem a planilha.
        pedido["html_body"] = html.replace(
            "na planilha em anexo", f"no painel, em {NORIA}")
        outlook("send_email", pedido)
        anexos = []
    return {"enviado": True, "destinos": DESTINOS, "assunto": assunto,
            "anexos": [os.path.basename(a) for a in anexos],
            "totais": {x["chave"]: {"qt": x.get("qt"), "total": x.get("total"),
                                    "ok": x.get("ok"), "motivo": x.get("motivo")}
                       for x in blocos}}


if __name__ == "__main__":
    r = rodar()
    print(json.dumps(r, ensure_ascii=False))
    sys.exit(0)
