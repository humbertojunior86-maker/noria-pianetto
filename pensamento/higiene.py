"""Higiene — nada sai do droplet sem passar por aqui.

Remove documento de pessoa, conta bancária, chave PIX, telefone, e-mail e
token de qualquer texto antes de virar prompt. O de-para volta a ser aplicado
na entrada, então a NÓRIA continua enxergando o dado certo internamente.
"""
from __future__ import annotations

import re

_PADROES = [
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "[cpf]"),
    (re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"), "[cnpj]"),
    (re.compile(r"\b(?:\+55\s?)?\(?\d{2}\)?\s?9?\d{4}-?\d{4}\b"), "[telefone]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[email]"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}\b"), "[token]"),
    (re.compile(r"\b[A-Za-z0-9]{8}-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}-"
                r"[A-Za-z0-9]{4}-[A-Za-z0-9]{12}\b"), "[chave]"),
    (re.compile(r"\bag[êe]ncia\s*\d{3,5}[\s/-]*c/?c?\s*\d{3,}\b", re.I), "[conta]"),
    (re.compile(r"\b\d{4}[\s.-]?\d{4}[\s.-]?\d{4}[\s.-]?\d{4}\b"), "[cartao]"),
]


def limpar(texto: str) -> str:
    """Devolve o texto sem dado sensível. Nunca levanta exceção."""
    if not texto:
        return ""
    saida = str(texto)
    for padrao, marca in _PADROES:
        saida = padrao.sub(marca, saida)
    return saida


def limpar_estrutura(obj):
    """Aplica `limpar` recursivamente em dict, lista e texto."""
    if isinstance(obj, str):
        return limpar(obj)
    if isinstance(obj, dict):
        return {k: limpar_estrutura(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [limpar_estrutura(v) for v in obj]
    return obj
