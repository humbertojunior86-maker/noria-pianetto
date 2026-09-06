"""Cliente do modelo — a única porta de saída do córtex para fora do droplet.

Regras que este arquivo faz valer sozinho:
  - chave só de /opt/noria/.secrets/cortex.json, modo 600, fora do git;
  - teto de gasto por dia e por mês, conferido contra `uso_ia` ANTES da chamada;
  - três falhas seguidas no dia derrubam o córtex até o dia seguinte;
  - toda chamada vira linha em `uso_ia`, com hash da entrada.

Se qualquer coisa aqui falhar, quem chamou recebe `CortexIndisponivel` e a
NÓRIA segue o dia normalmente — nenhum agente determinístico depende disto.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from nucleo import bd
from . import higiene

_RAIZ = Path(__file__).resolve().parent
_SEGREDO = Path(os.environ.get(
    "NORIA_CORTEX_SEGREDO", "/opt/noria/.secrets/cortex.json"))
URL = "https://api.anthropic.com/v1/messages"


class CortexIndisponivel(RuntimeError):
    """Córtex fora do ar: sem chave, teto estourado ou modelo mudo."""


def config() -> dict:
    return json.loads((_RAIZ / "config.json").read_text(encoding="utf-8"))


def tem_chave() -> bool:
    try:
        return bool(json.loads(_SEGREDO.read_text()).get("anthropic_api_key"))
    except Exception:
        return False


def _chave() -> str:
    try:
        ch = json.loads(_SEGREDO.read_text()).get("anthropic_api_key", "")
    except Exception as e:
        raise CortexIndisponivel(
            f"chave do córtex não pôde ser lida em {_SEGREDO}: {e}") from e
    if not ch:
        raise CortexIndisponivel(f"chave do córtex ausente em {_SEGREDO}")
    return ch


# ------------------------------------------------------------------ gasto
def gasto(periodo: str = "dia") -> float:
    corte = bd.agora()[:10] if periodo == "dia" else bd.agora()[:7]
    r = bd.linha(
        "SELECT COALESCE(SUM(custo_estimado),0) AS v FROM uso_ia "
        "WHERE substr(criado_em,1,?) = ?", (len(corte), corte))
    return float(r["v"] if r else 0.0)


def _falhas_seguidas_hoje() -> int:
    hoje = bd.agora()[:10]
    linhas = bd.linhas(
        "SELECT sucesso FROM uso_ia WHERE substr(criado_em,1,10)=? "
        "ORDER BY id DESC LIMIT 10", (hoje,))
    n = 0
    for l in linhas:
        if l["sucesso"]:
            break
        n += 1
    return n


def estado() -> dict:
    c = config()
    return {
        "chave": tem_chave(),
        "modelo": c["modelo"],
        "gasto_dia": round(gasto("dia"), 4),
        "teto_dia": c["teto_dia_brl"],
        "gasto_mes": round(gasto("mes"), 4),
        "teto_mes": c["teto_mes_brl"],
        "falhas_seguidas": _falhas_seguidas_hoje(),
        "dormente": (gasto("dia") >= c["teto_dia_brl"]
                     or gasto("mes") >= c["teto_mes_brl"]
                     or _falhas_seguidas_hoje() >= c["falhas_para_dormir"]),
    }


def _guardar(tarefa, modelo, h, te, ts, custo, ms, ok, erro=None):
    bd.inserir("uso_ia", {
        "tarefa": tarefa, "modelo": modelo, "entrada_hash": h,
        "tokens_entrada": te, "tokens_saida": ts, "custo_estimado": custo,
        "duracao_ms": ms, "sucesso": 1 if ok else 0,
        "erro": (erro or "")[:400] or None, "criado_em": bd.agora()})


# ------------------------------------------------------------------ chamada
def pensar(tarefa: str, sistema: str, mensagem: str,
           max_tokens: int | None = None) -> str:
    """Manda pensar e devolve o texto puro. Levanta CortexIndisponivel."""
    c = config()
    est = estado()
    if est["dormente"]:
        motivo = ("teto de gasto atingido"
                  if est["gasto_dia"] >= c["teto_dia_brl"]
                  or est["gasto_mes"] >= c["teto_mes_brl"]
                  else "falhas seguidas no dia")
        raise CortexIndisponivel(f"córtex dormente: {motivo}")

    mensagem = higiene.limpar(mensagem)
    h = hashlib.sha256(mensagem.encode("utf-8")).hexdigest()[:24]
    corpo = json.dumps({
        "model": c["modelo"],
        "max_tokens": max_tokens or c["max_tokens"],
        "system": sistema,
        "messages": [{"role": "user", "content": mensagem}],
    }).encode("utf-8")

    req = urllib.request.Request(URL, data=corpo, headers={
        "x-api-key": _chave(),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=c["timeout_s"]) as resp:
            dados = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detalhe = e.read().decode("utf-8", "ignore")[:300]
        _guardar(tarefa, c["modelo"], h, None, None, 0.0,
                 int((time.time() - t0) * 1000), False, f"HTTP {e.code}: {detalhe}")
        raise CortexIndisponivel(f"modelo devolveu HTTP {e.code}: {detalhe}") from e
    except Exception as e:
        _guardar(tarefa, c["modelo"], h, None, None, 0.0,
                 int((time.time() - t0) * 1000), False, str(e))
        raise CortexIndisponivel(f"modelo não respondeu: {e}") from e

    ms = int((time.time() - t0) * 1000)
    uso = dados.get("usage", {})
    te = uso.get("input_tokens") or 0
    ts = uso.get("output_tokens") or 0
    custo = ((te / 1_000_000) * c["usd_por_milhao_entrada"]
             + (ts / 1_000_000) * c["usd_por_milhao_saida"]) * c["brl_por_usd"]
    texto = "".join(b.get("text", "") for b in dados.get("content", [])
                    if b.get("type") == "text").strip()
    _guardar(tarefa, c["modelo"], h, te, ts, round(custo, 6), ms, bool(texto),
             None if texto else "resposta vazia")
    if not texto:
        raise CortexIndisponivel("modelo devolveu resposta vazia")
    return texto


def pensar_json(tarefa: str, sistema: str, mensagem: str,
                max_tokens: int | None = None) -> dict:
    """Igual a `pensar`, mas exige JSON de volta. Lixo vira exceção."""
    bruto = pensar(tarefa, sistema + "\n\nResponda SOMENTE com JSON válido, "
                                     "sem cerca de código e sem comentário.",
                   mensagem, max_tokens)
    t = bruto.strip()
    if t.startswith("```"):
        t = t.split("```")[1]
        t = t[4:] if t.lower().startswith("json") else t
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < 0:
        raise CortexIndisponivel("resposta do modelo não trouxe JSON")
    try:
        return json.loads(t[i:j + 1])
    except json.JSONDecodeError as e:
        raise CortexIndisponivel(f"JSON inválido do modelo: {e}") from e
