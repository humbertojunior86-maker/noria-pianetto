"""ATUA — consulta SOMENTE LEITURA ao ERP da Pianetto.

Nenhum agente escreve SQL. Existe um catálogo de consultas nomeadas, com
parâmetros tipados. Isso fecha a porta para injeção, para consulta cara em
horário de faturamento e para um agente ler dados de outra empresa.

Toda consulta devolve `consultada_em` — o número nasce carimbado com a data.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from nucleo import bd
from .base import Ferramenta, Resultado, registrar

_SEGREDO = Path(os.environ.get(
    "NORIA_ATUA_SEGREDO", "/home/user/workspace/.secrets/jhn.json"))

# Janela em que consultas pesadas ficam proibidas (pico de faturamento).
JANELA_PROIBIDA = (8, 11)
LIMITE_LINHAS = 5000


def _conn():
    import json as _json
    import psycopg2
    cfg = _json.loads(_SEGREDO.read_text())
    return psycopg2.connect(
        host=cfg["host"], port=cfg["port"],
        dbname=cfg.get("dbname") or cfg["database"],
        user=cfg["user"], password=cfg["password"],
        sslmode=cfg.get("sslmode", "disable"), connect_timeout=15,
    )


# --------------------------------------------------------------- catálogo
# {nome: (sql, params_obrigatorios, pesada?, descricao)}
CONSULTAS: dict[str, tuple] = {

    "conta.listar": (
        """SELECT c.cd_conta, b.nm_banco, c.nr_agencia, c.nr_conta,
                  c.nr_digito_conta, c.id_principal
             FROM conta c LEFT JOIN banco b ON b.cd_banco = c.cd_banco
            WHERE EXISTS (SELECT 1 FROM caixa_financeiro_lancamento_ofx o
                           WHERE o.cd_conta = c.cd_conta)
            ORDER BY c.id_principal DESC NULLS LAST, c.cd_conta""",
        [], False, "contas bancárias que possuem extrato OFX importado"),

    "ofx.movimentos_do_dia": (
        """SELECT o.cd_conciliado, o.cd_conta, o.dt_documento::date AS data,
                  o.ds_lancamento, o.vl_lancamento, o.ds_tipo,
                  o.id_conciliacao, o.id_checknum
             FROM caixa_financeiro_lancamento_ofx o
            WHERE o.cd_conta = %(cd_conta)s
              AND o.dt_documento::date = %(data)s
            ORDER BY o.vl_lancamento DESC""",
        ["cd_conta", "data"], False,
        "movimentos do extrato OFX de uma conta em um dia"),

    "ofx.nao_conciliados": (
        """SELECT o.cd_conciliado, o.cd_conta, o.dt_documento::date AS data,
                  o.ds_lancamento, o.vl_lancamento
             FROM caixa_financeiro_lancamento_ofx o
            WHERE o.cd_conta = %(cd_conta)s
              AND o.dt_documento::date BETWEEN %(de)s AND %(ate)s
              AND COALESCE(o.id_conciliacao, 0) = 0
            ORDER BY ABS(o.vl_lancamento) DESC
            LIMIT 2000""",
        ["cd_conta", "de", "ate"], False,
        "movimentos do extrato sem conciliação no período"),

    # Pareamento real do ATUA: o lançamento guarda em ar_cd_conciliado os ids
    # dos movimentos de extrato que ele quita. Não é heurística de valor+data.
    "lancamento.pareado_com_extrato": (
        """SELECT o.cd_conciliado, o.dt_documento::date AS data,
                  o.ds_lancamento AS ds_extrato, o.vl_lancamento AS vl_extrato,
                  l.cd_lancamento, l.vl_lancamento AS vl_erp,
                  l.ds_lancamento AS ds_erp, l.cd_titulo, l.cd_titulo_pagamento,
                  COALESCE(array_length(l.ar_cd_conciliado, 1), 0) AS qt_movimentos
             FROM caixa_financeiro_lancamento_ofx o
             LEFT JOIN caixa_financeiro_lancamento l
                    ON o.cd_conciliado = ANY(l.ar_cd_conciliado)
            WHERE o.cd_conta = %(cd_conta)s
              AND o.dt_documento::date = %(data)s
            ORDER BY ABS(o.vl_lancamento) DESC""",
        ["cd_conta", "data"], False,
        "cada movimento do extrato com o lançamento do ATUA que o quita, se houver"),

    "ofx.resumo_periodo": (
        """SELECT COUNT(*) AS movimentos,
                  SUM(CASE WHEN vl_lancamento > 0 THEN vl_lancamento ELSE 0 END) AS entradas,
                  SUM(CASE WHEN vl_lancamento < 0 THEN vl_lancamento ELSE 0 END) AS saidas,
                  SUM(CASE WHEN COALESCE(id_conciliacao,0) <> 0 THEN 1 ELSE 0 END) AS conciliados
             FROM caixa_financeiro_lancamento_ofx
            WHERE cd_conta = %(cd_conta)s
              AND dt_documento::date BETWEEN %(de)s AND %(ate)s""",
        ["cd_conta", "de", "ate"], False,
        "totais do extrato no período, com quantos estão conciliados"),

    # Não existe coluna de saldo no ATUA: o saldo em aberto é vl_total menos
    # o que já foi pago, e o título só está aberto enquanto não tem quitação.
    "titulo.vencidos": (
        """SELECT COUNT(*) OVER () AS total_geral,
                  SUM(t.vl_total - COALESCE(t.vl_pago,0)) OVER () AS total_saldo,
                  t.cd_titulo, t.nr_titulo, t.dt_vencimento::date AS vencimento,
                  t.vl_total AS vl_titulo,
                  (t.vl_total - COALESCE(t.vl_pago,0)) AS vl_saldo,
                  (CURRENT_DATE - t.dt_vencimento::date) AS dias_vencido,
                  p.nm_pessoa AS pessoa
             FROM titulo t LEFT JOIN pessoa p ON p.cd_pessoa = t.cd_pessoa
            WHERE t.id_tipo = %(id_tipo)s
              AND t.dt_quitacao IS NULL
              AND (t.vl_total - COALESCE(t.vl_pago,0)) > 0.009
              AND t.dt_vencimento::date < CURRENT_DATE - %(dias)s
            ORDER BY (t.vl_total - COALESCE(t.vl_pago,0)) DESC LIMIT 500""",
        ["id_tipo", "dias"], False,
        "títulos em aberto vencidos há mais de N dias (1=receber, 2=pagar)"),
}


def _executar(operacao: str, empresa_id: int, **kw) -> Resultado:
    if operacao not in CONSULTAS:
        return Resultado(False, erro=f"consulta '{operacao}' não está no catálogo")
    sql, obrig, pesada, _desc = CONSULTAS[operacao]

    faltando = [p for p in obrig if kw.get(p) is None]
    if faltando:
        return Resultado(False, erro=f"parâmetros ausentes: {', '.join(faltando)}")

    if pesada and JANELA_PROIBIDA[0] <= datetime.now(bd.FUSO).hour < JANELA_PROIBIDA[1]:
        return Resultado(
            False,
            erro="consulta pesada bloqueada na janela de faturamento (8h–11h)")

    params = {p: kw[p] for p in obrig}
    with _conn() as c, c.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        dados = [dict(zip(cols, r)) for r in cur.fetchmany(LIMITE_LINHAS)]

    return Resultado(
        ok=True,
        dados={"linhas": dados, "consultada_em": bd.agora()},
        resumo=f"{len(dados)} linha(s) de atua:{operacao}",
        linhas=len(dados),
        raiz=f"atua:{operacao}",
        referencia=f"atua:{operacao} {params}",
    )


FERRAMENTA = registrar(Ferramenta(
    id="atua",
    nome="ATUA (ERP)",
    descricao="Consulta somente leitura ao ERP, por catálogo de consultas nomeadas.",
    escreve=False,
    executar=_executar,
    operacoes=sorted(CONSULTAS),
    limitacao=None if _SEGREDO.exists() else "credencial do ATUA não configurada",
))
