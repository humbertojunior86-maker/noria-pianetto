"""Conferente — a peça que impede alucinação de valor.

Pega o texto que o modelo escreveu e confere que todo número citado existe no
conjunto de números que vieram do banco. Número que não bate: o texto é
bloqueado. É determinístico e barato, e roda depois de toda geração de texto.
"""
from __future__ import annotations

import re

_NUM = re.compile(r"-?\d[\d.\s]*(?:,\d+)?")
# datas, percentuais de uma casa e números de até 3 dígitos (contagem curta,
# ordinal, ano) não precisam de lastro — o que interessa é valor e volume.
_DATA = re.compile(r"\b\d{2}/\d{2}/\d{4}\b|\b\d{4}-\d{2}-\d{2}\b")


def _para_float(t: str):
    t = t.strip().replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def numeros_de(texto: str) -> set[float]:
    texto = _DATA.sub(" ", texto or "")
    saida = set()
    for m in _NUM.finditer(texto):
        v = _para_float(m.group())
        if v is not None:
            saida.add(round(abs(v), 2))
    return saida


def numeros_do_banco(linhas: list[dict]) -> set[float]:
    saida = set()
    for l in linhas or []:
        for v in l.values():
            if isinstance(v, bool) or v is None:
                continue
            if isinstance(v, (int, float)):
                saida.add(round(abs(float(v)), 2))
                saida.add(round(abs(float(v)) / 1_000_000, 1))
                saida.add(round(abs(float(v)) / 1_000, 1))
    return saida


def conferir(texto: str, linhas: list[dict], tolerancia: float = 0.02) -> dict:
    """Devolve {ok, orfaos}. `orfaos` são os números sem lastro no banco."""
    do_banco = numeros_do_banco(linhas)
    orfaos = []
    for n in sorted(numeros_de(texto)):
        if n < 1000:          # contagem curta, ano, percentual: dispensado
            continue
        if any(abs(n - b) <= max(tolerancia, abs(b) * 0.005) for b in do_banco):
            continue
        orfaos.append(n)
    return {"ok": not orfaos, "orfaos": orfaos}
