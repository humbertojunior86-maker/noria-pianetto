"""Guarda — nenhum SQL escrito por modelo chega ao ATUA sem passar por aqui.

O que passa: um único SELECT, sobre tabela da lista branca, com LIMIT, fora da
janela de faturamento. Qualquer outra coisa é recusada com o motivo escrito.
"""
from __future__ import annotations

import re
from datetime import datetime

from nucleo import bd

JANELA_PROIBIDA = (8, 11)
LIMITE_MAX = 5000

TABELAS_OK = {
    "titulo", "titulo_pagamento", "movimento", "ctrc", "ctrc_cte",
    "carta_frete",
    "ctrc_produto", "produto_transportado", "pessoa", "cliente",
    "veiculo", "veiculo_proprio", "motorista", "viagem", "manifesto",
    "documento_eletronico", "cidade", "estado", "conta", "portador",
    "centro_custo", "plano_conta", "filial", "empresa",
}

_PROIBIDO = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|"
    r"vacuum|merge|call|do|execute|refresh|lock|listen|notify|set|reset|"
    r"pg_sleep|pg_read_file|pg_ls_dir|lo_import|lo_export|dblink|"
    r"pg_terminate_backend|pg_cancel_backend|into\s+outfile)\b", re.I)
_TABELA = re.compile(r"\b(?:from|join)\s+(?:public\.)?\"?([a-z_][a-z0-9_]*)\"?", re.I)
_SENSIVEL = re.compile(r"\b(usuario|senha|password|token|sessao|auth|acesso_)\w*",
                       re.I)


class Recusa(ValueError):
    """SQL barrado. A mensagem é o motivo, escrito para humano ler."""


def _sem_comentario(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return re.sub(r"\s+", " ", sql).strip()


def conferir(sql: str, respeitar_janela: bool = True) -> str:
    """Devolve o SQL limpo e aprovado, ou levanta `Recusa`."""
    if not sql or not sql.strip():
        raise Recusa("consulta vazia")
    limpo = _sem_comentario(sql).rstrip(";").strip()

    if limpo.count(";"):
        raise Recusa("mais de um comando na mesma consulta")
    cab = limpo.lstrip("( ").lower()
    if not (cab.startswith("select") or cab.startswith("with")):
        raise Recusa("só SELECT é aceito; a consulta começa com outra coisa")
    if _PROIBIDO.search(limpo):
        raise Recusa("a consulta usa comando de escrita ou função perigosa")
    if _SENSIVEL.search(limpo):
        raise Recusa("a consulta toca tabela ou coluna de usuário, senha ou sessão")

    ctes = {m.lower() for m in re.findall(
        r"(?:with|,)\s+([a-z_][a-z0-9_]*)\s+as\s*\(", limpo, re.I)}
    tabelas = {t.lower() for t in _TABELA.findall(limpo)} - ctes
    fora = sorted(t for t in tabelas if t not in TABELAS_OK)
    if not tabelas:
        raise Recusa("não deu para identificar a tabela consultada")
    if fora:
        raise Recusa("tabela fora da lista branca: " + ", ".join(fora))

    m = re.search(r"\blimit\s+(\d+)\b", limpo, re.I)
    if not m:
        limpo += f" LIMIT {LIMITE_MAX}"
    elif int(m.group(1)) > LIMITE_MAX:
        raise Recusa(f"LIMIT acima do teto de {LIMITE_MAX} linhas")

    if respeitar_janela:
        hora = datetime.now(bd.FUSO).hour
        if JANELA_PROIBIDA[0] <= hora < JANELA_PROIBIDA[1]:
            raise Recusa("janela de faturamento (8h–11h): consulta adiada")

    return limpo
