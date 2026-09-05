"""Formatação em pt-BR. Número de dinheiro nunca sai em formato americano."""
from __future__ import annotations


def brl(v) -> str:
    try:
        n = float(v or 0)
    except (TypeError, ValueError):
        return "R$ 0,00"
    s = f"{abs(n):,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{'-' if n < 0 else ''}R$ {s}"


def pct(v, casas: int = 1) -> str:
    try:
        return f"{float(v or 0) * 100:.{casas}f}".replace(".", ",") + "%"
    except (TypeError, ValueError):
        return "0,0%"
