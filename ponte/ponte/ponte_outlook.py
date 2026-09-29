"""A ponte entre a NÓRIA e o e-mail da empresa.

Roda fora do servidor da NÓRIA, porque é aqui que existe a conexão com o
Outlook. Ela não pensa: só carrega. De dentro para fora, leva o que a NÓRIA
já decidiu que era notícia (a fila de avisos). De fora para dentro, traz o
que chegou pedindo resposta (a caixa de demandas). Quem julga é o cérebro,
lá dentro, com a fila e a caixa gravadas no banco dele.

Por isso a conta usada aqui é a `ponte`: ela não alcança número do ERP, nem
missão, nem aprovação. Se este script vazar inteiro, o que se perde é a fila
de avisos — e nada mais.

Uso:
    python3 ponte_outlook.py entrada    # Outlook -> NÓRIA
    python3 ponte_outlook.py saida      # NÓRIA -> Outlook
    python3 ponte_outlook.py            # os dois, entrada primeiro
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request

NORIA = os.environ.get("NORIA_URL", "http://174.138.92.164")
PONTE_EMAIL = os.environ.get("NORIA_PONTE_EMAIL", "ponte@pianetto.com.br")
PONTE_SENHA = os.environ.get("NORIA_PONTE_SENHA", "ponte-noria")
DESTINO = os.environ.get("NORIA_DESTINO", "humberto@pianettotransportes.com.br")
CASA = "pianettotransportes.com.br"
ROBOS = ("comunicados@", "no-reply", "noreply", "nao-responda",
         "microsoftexchange")


# ------------------------------------------------------------------- Outlook
def outlook(ferramenta: str, entrada: dict) -> dict:
    p = subprocess.run(["pplx", "connector", "call", "outlook", ferramenta,
                        "--input", json.dumps(entrada)],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[:500])
    r = json.loads(p.stdout)
    if r.get("requires_auth"):
        # O correio devolve isso com codigo de saida 0. Sem este teste, uma
        # conexao vencida vira "enviado com sucesso" e ninguem recebe nada.
        raise RuntimeError("OUTLOOK DESCONECTADO: o conector pediu nova "
                           "autorizacao. Nenhum e-mail saiu.")
    if r.get("is_error"):
        raise RuntimeError(str(r.get("error"))[:500])
    return r.get("result") or {}


def ler_caixa(paginas: int = 3) -> list[dict]:
    """Traz as mensagens mais recentes, sem pedir nada específico."""
    fora, cursor = [], None
    for _ in range(paginas):
        pedido: dict = {"queries": [""]}
        if cursor:
            pedido["cursor"] = cursor
        r = outlook("search_email", pedido).get("email_results") or {}
        fora += r.get("emails") or []
        cursor = r.get("next_cursor")
        if not cursor:
            break
    return fora


# ------------------------------------------------------------------- NÓRIA
def _http(caminho: str, dados=None, token: str = "") -> dict:
    req = urllib.request.Request(
        NORIA + caminho,
        data=json.dumps(dados).encode() if dados is not None else None,
        headers={"content-type": "application/json",
                 **({"authorization": "Bearer " + token} if token else {})},
        method="POST" if dados is not None else "GET")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def entrar() -> str:
    return _http("/api/entrar", {"email": PONTE_EMAIL,
                                 "senha": PONTE_SENHA})["token"]


# -------------------------------------------------------------- classificação
# Régua rasa, de propósito. A ponte separa o que é gente do que é máquina e
# marca do que trata pelo assunto; o julgamento fino é do cérebro, com o
# banco na mão. Aqui errar para menos é melhor do que inventar.
ASSUNTOS = [
    (r"fatura|faturamento|sem fatura|cobran|t[íi]tulo|receber|inadimpl",
     "faturamento e cobrança", "Contas a Receber"),
    (r"ct-?e|conhecimento|cte|mdf-?e|sefaz|fiscal|nota fiscal",
     "documento fiscal", "Fiscal"),
    (r"coleta|carga|entrega|descarga|pesagem|romaneio|viagem|frete|embarque",
     "operação de transporte", "Operações"),
    (r"manuten|pneu|oficina|diesel|abastec|ve[íi]culo|placa|frota",
     "frota", "Frota"),
    (r"dre|ebitda|resultado|margem|custo", "resultado", "Controladoria"),
    (r"contrato|tabela|reajuste|proposta|cota[çc][ãa]o",
     "comercial", "Comercial"),
]


def classificar(e: dict) -> dict:
    de = (e.get("from_") or "").lower()
    assunto = (e.get("subject") or "")
    trecho = (e.get("snippet") or e.get("summary") or "")[:600]
    baixo = (assunto + " " + trecho).lower()

    if assunto.strip().upper().startswith(("NÓRIA", "NORIA")):
        # Eco da propria NORIA: o que ela mandou volta pela caixa conectada.
        # Sem este filtro, cada aviso enviado renascia como demanda de cliente.
        classe, tema, area = "sistema", "eco de aviso da própria NÓRIA", \
            "Tecnologia"
    elif "não é possível entregar" in baixo or "undeliverable" in baixo:
        classe, tema, area = "sistema", "e-mail que não chegou ao destino", \
            "Tecnologia"
    elif any(r in de for r in ROBOS):
        classe = "sistema"
        tema, area = "aviso automático", "Tecnologia"
    elif de.endswith("@" + CASA):
        classe, tema, area = "equipe", "", ""
    elif "@" in de:
        classe, tema, area = "cliente", "", ""
    else:
        classe, tema, area = "ruido", "", ""

    if not tema:
        for padrao, t, a in ASSUNTOS:
            if re.search(padrao, baixo):
                tema, area = t, a
                break

    return {
        "canal": "outlook", "externo_id": e.get("email_id"),
        "conversa_id": e.get("thread_id"), "de": e.get("from_"),
        "para": ", ".join(e.get("to") or [])[:300], "assunto": assunto,
        "trecho": trecho, "recebida_em": e.get("date"),
        "classe": classe, "assunto_operacional": tema or None,
        "quem_responde": area or None, "link": e.get("web_link"),
    }


def entrada(paginas: int = 3) -> dict:
    tok = entrar()
    msgs = [classificar(e) for e in ler_caixa(paginas) if e.get("email_id")]
    r = _http("/api/demandas", {"mensagens": msgs}, tok)
    return {"lidas": len(msgs), **r}


# -------------------------------------------------------------------- saída
CORES = {"alta": "#c2410c", "media": "#334155"}


NO_CORPO = 30   # linhas por achado no corpo; a planilha leva todas

ROTULOS = {"ctrc": "CTRC", "carta_frete": "Carta frete", "emissao": "Emissão",
           "transportador": "Transportador", "enquadramento": "Enquadr.",
           "margem_nao_descontada": "Valor", "vl_seguro": "Seguro",
           "seguro_descontado": "Seguro", "valor": "Valor"}


def _br(v) -> str:
    if isinstance(v, float):
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "" if v is None else str(v)


def _tabela(linhas: list[dict], n: int) -> str:
    if not linhas:
        return ""
    # CTRC e carta frete primeiro: é por eles que a equipe acha a carga no ATUA.
    ordem = ["ctrc", "carta_frete", "emissao", "transportador", "enquadramento"]
    cols = [c for c in ordem if c in linhas[0]]
    valor = next((c for c in ("margem_nao_descontada", "seguro_descontado",
                              "vl_seguro", "valor") if c in linhas[0]), None)
    if not cols:
        cols = list(linhas[0].keys())[:5]
    if valor and valor not in cols:
        cols.append(valor)
    th = "".join(f'<th style="text-align:left;padding:4px 6px;font:600 11px Arial;'
                 f'color:#64748b;border-bottom:1px solid #cbd5e1">'
                 f'{ROTULOS.get(c, c)}</th>' for c in cols)
    tr = "".join("<tr>" + "".join(
        f'<td style="padding:3px 6px;font:400 12px Arial;color:#0f172a;'
        f'border-bottom:1px solid #f1f5f9">{_br(ln.get(c))}</td>' for c in cols)
        + "</tr>" for ln in linhas[:n])
    resto = len(linhas) - n
    rodape = (f'<div style="font:400 12px Arial;color:#64748b;margin-top:4px">'
              f'Mostrando {n} de {len(linhas)}. A lista inteira está na planilha '
              f'em anexo.</div>' if resto > 0 else
              '<div style="font:400 12px Arial;color:#64748b;margin-top:4px">'
              'Lista completa também na planilha em anexo.</div>')
    return (f'<table style="border-collapse:collapse;margin-top:8px;width:100%">'
            f'<tr>{th}</tr>{tr}</table>{rodape}')


def _bloco(a: dict, n: int = NO_CORPO) -> str:
    cor = CORES.get(a["gravidade"], "#334155")
    return (
        f'<tr><td style="padding:14px 0;border-bottom:1px solid #e2e8f0">'
        f'<div style="font:600 12px/1.4 Arial;color:{cor};letter-spacing:.08em;'
        f'text-transform:uppercase">{a["especie"].replace("_", " ")} · '
        f'{a["agente_nome"] or ""}</div>'
        f'<div style="font:600 16px/1.4 Arial;color:#0f172a;margin-top:4px">'
        f'{a["titulo"]}</div>'
        f'<div style="font:400 14px/1.5 Arial;color:#475569;margin-top:4px">'
        f'{(a["texto"] or "")[:400]}</div>'
        f'{_tabela(a.get("linhas") or [], n)}</td></tr>')


def planilhas(avs: list[dict]) -> list[str]:
    import csv
    pasta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "anexos")
    os.makedirs(pasta, exist_ok=True)
    fora = []
    for a in avs:
        lns = a.get("linhas") or []
        if not lns:
            continue
        caminho = os.path.join(pasta, f"achado-{a['id']}.csv")
        cols = list(lns[0].keys())
        with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols, delimiter=";")
            w.writeheader()
            for ln in lns:
                w.writerow({c: (_br(ln.get(c)).replace(".", "")
                                if isinstance(ln.get(c), float) else ln.get(c))
                            for c in cols})
        fora.append(caminho)
    return fora


def montar(avs: list[dict], n: int = NO_CORPO) -> tuple[str, str]:
    alta = [a for a in avs if a["gravidade"] == "alta"]
    assunto = (f"NÓRIA · {len(avs)} achado(s)"
               + (f" · {len(alta)} para hoje" if alta else ""))
    linhas = "".join(_bloco(a, n) for a in avs)
    html = (
        '<div style="max-width:640px;margin:0 auto;padding:24px;'
        'font-family:Arial,Helvetica,sans-serif">'
        '<div style="font:700 13px/1 Arial;letter-spacing:.22em;color:#0f172a">'
        'N Ó R I A</div>'
        '<div style="font:400 13px/1.5 Arial;color:#64748b;margin-top:6px">'
        'Achados dos agentes desde o último aviso. Cada número saiu do ATUA e '
        'está gravado na missão que o gerou.</div>'
        f'<table style="width:100%;border-collapse:collapse;margin-top:16px">'
        f'{linhas}</table>'
        f'<div style="font:400 12px/1.5 Arial;color:#94a3b8;margin-top:18px">'
        f'Sala do CEO: {NORIA}</div></div>')
    return assunto, html


def saida(limite: int = 12) -> dict:
    tok = entrar()
    avs = (_http(f"/api/avisos?estado=pendente&limite={limite}",
                 token=tok)).get("avisos") or []
    if not avs:
        return {"enviados": 0}
    # O pedido vira argumento de linha de comando: encolhe o corpo até caber.
    n = NO_CORPO
    while True:
        assunto, html = montar(avs, n)
        if len(html) <= 90000 or n <= 3:
            break
        n = max(3, n // 2)
    pedido = {"action": "send", "to": [DESTINO], "cc": [], "bcc": [],
              "subject": assunto, "html_body": html,
              "body": "\n".join(a["titulo"] for a in avs)}
    anexos = planilhas(avs)
    try:
        outlook("send_email", dict(pedido, attachment_files=anexos)
                if anexos else pedido)
    except RuntimeError as e:
        if "DESCONECTADO" in str(e) or not anexos:
            raise
        outlook("send_email", pedido)   # sem anexo, mas o CTRC vai no corpo
    for a in avs:
        _http(f"/api/avisos/{a['id']}/entregue",
              {"canal": "outlook", "referencia": DESTINO}, tok)
    return {"enviados": len(avs), "assunto": assunto}


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else "tudo"
    if modo in ("entrada", "tudo"):
        print("entrada:", entrada())
    if modo in ("saida", "tudo"):
        print("saida:", saida())
