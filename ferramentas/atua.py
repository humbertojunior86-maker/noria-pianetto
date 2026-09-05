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

    # ---------------------------------------------------------------- CEO
    # O que o dono da empresa olha primeiro. Consultas propositalmente
    # baratas (~1s cada) porque a sala do CEO relê a cada minuto.

    "ceo.pulso": (
        """SELECT
             (SELECT count(*) FROM ctrc WHERE dt_cancelamento IS NULL
                AND dt_emissao::date = CURRENT_DATE) AS ctes_hoje,
             (SELECT coalesce(sum(vl_total),0) FROM ctrc WHERE dt_cancelamento IS NULL
                AND dt_emissao::date = CURRENT_DATE) AS receita_hoje,
             (SELECT count(*) FROM ctrc WHERE dt_cancelamento IS NULL
                AND dt_emissao >= date_trunc('month', CURRENT_DATE)) AS ctes_mes,
             (SELECT coalesce(sum(vl_total),0) FROM ctrc WHERE dt_cancelamento IS NULL
                AND dt_emissao >= date_trunc('month', CURRENT_DATE)) AS receita_mes,
             (SELECT count(*) FROM ctrc WHERE dt_cancelamento IS NULL
                AND dt_emissao >= CURRENT_DATE - interval '12 months') AS ctes_12m,
             (SELECT coalesce(sum(vl_total),0) FROM ctrc WHERE dt_cancelamento IS NULL
                AND dt_emissao >= CURRENT_DATE - interval '12 months') AS receita_12m""",
        [], False, "CT-es e receita de hoje, do mês e dos 12 meses"),

    "ceo.carteira": (
        """SELECT t.id_tipo,
                  count(*) AS qt,
                  sum(t.vl_total - coalesce(t.vl_pago,0)) AS aberto,
                  count(*) FILTER (WHERE t.dt_vencimento::date < CURRENT_DATE) AS qt_vencido,
                  sum(CASE WHEN t.dt_vencimento::date < CURRENT_DATE
                           THEN t.vl_total - coalesce(t.vl_pago,0) ELSE 0 END) AS vencido
             FROM titulo t
            WHERE t.dt_quitacao IS NULL
              AND (t.vl_total - coalesce(t.vl_pago,0)) > 0.009
            GROUP BY t.id_tipo ORDER BY t.id_tipo""",
        [], False, "a receber e a pagar em aberto, e quanto já venceu"),

    # Concentração é por GRUPO econômico, não por CNPJ: filiais do mesmo dono
    # quebram na mesma crise. Agrupa pela raiz de 8 dígitos do CNPJ.
    "ceo.concentracao": (
        """WITH base AS (
             SELECT left(regexp_replace(coalesce(p.nr_cnpj_cpf,''),'[^0-9]','','g'),8) AS raiz,
                    coalesce(nullif(p.nm_fantasia,''), p.nm_pessoa) AS nome,
                    c.vl_total
               FROM ctrc c LEFT JOIN pessoa p ON p.cd_pessoa = c.cd_pessoa_pagador
              WHERE c.dt_cancelamento IS NULL
                AND c.dt_emissao >= CURRENT_DATE - interval '12 months'),
           tot AS (SELECT sum(vl_total) t FROM base)
           SELECT b.raiz, min(b.nome) AS nome, sum(b.vl_total) AS receita,
                  round(100.0*sum(b.vl_total)/(SELECT t FROM tot), 2) AS pct
             FROM base b WHERE b.raiz <> ''
            GROUP BY b.raiz ORDER BY receita DESC LIMIT 8""",
        [], False, "maiores grupos econômicos por receita em 12 meses"),

    "ceo.serie_mensal": (
        """SELECT to_char(date_trunc('month', c.dt_emissao),'YYYY-MM') AS mes,
                  count(*) AS qt, sum(c.vl_total) AS receita
             FROM ctrc c
            WHERE c.dt_cancelamento IS NULL
              AND c.dt_emissao >= date_trunc('month', CURRENT_DATE) - interval '12 months'
            GROUP BY 1 ORDER BY 1""",
        [], False, "receita e CT-es mês a mês nos últimos 13 meses"),

    # --- consultas de vigilância: cada uma existe para dar trabalho de
    # verdade a um agente que estava parado por falta de pergunta.
    "pagar.duplicidade_suspeita": (
        """\
-- pagar.duplicidade_suspeita
-- Titulos A PAGAR (id_tipo=2) do mesmo fornecedor, mesmo valor e vencimento
-- dentro de uma janela de :dias. Exclui parcelamentos longos (financiamento de
-- frota) via movimento.qt_parcela, que e a maior fonte de falso positivo.
WITH base AS (
  SELECT t.cd_titulo, t.cd_pessoa, round(t.vl_total, 2) AS vl,
         t.dt_vencimento, t.dt_quitacao, t.nr_titulo, t.nr_parcela,
         m.qt_parcela, m.cd_pessoa_filial, m.dt_movimento
    FROM titulo t
    JOIN movimento m ON m.cd_movimento = t.cd_movimento
   WHERE t.id_tipo = 2
     AND t.vl_total >= %(vl_min)s
     AND t.dt_vencimento >= CURRENT_DATE - %(dias_retro)s
     AND COALESCE(m.qt_parcela, 1) <= %(max_parcelas)s
     AND (%(cd_pessoa_filial)s IS NULL OR m.cd_pessoa_filial = %(cd_pessoa_filial)s)
), grp AS (
  SELECT b.cd_pessoa, b.vl,
         count(*) AS qt_titulos,
         min(b.dt_vencimento) AS venc_ini,
         max(b.dt_vencimento) AS venc_fim,
         count(*) FILTER (WHERE b.dt_quitacao IS NOT NULL) AS qt_pagos,
         sum(CASE WHEN b.dt_quitacao IS NOT NULL THEN b.vl ELSE 0 END) AS vl_ja_pago,
         array_agg(b.cd_titulo    ORDER BY b.dt_vencimento) AS ar_cd_titulo,
         array_agg(b.nr_titulo    ORDER BY b.dt_vencimento) AS ar_nr_titulo,
         array_agg(b.dt_vencimento ORDER BY b.dt_vencimento) AS ar_vencimento,
         array_agg(b.dt_quitacao  ORDER BY b.dt_vencimento) AS ar_quitacao,
         array_agg(DISTINCT b.cd_pessoa_filial) AS ar_filial
    FROM base b
   GROUP BY 1, 2
  HAVING count(*) > 1
     AND max(b.dt_vencimento) - min(b.dt_vencimento) <= %(dias)s
)
SELECT g.cd_pessoa,
       coalesce(nullif(p.nm_fantasia,''), p.nm_pessoa) AS fornecedor,
       p.nr_cnpj_cpf,
       g.vl AS vl_titulo,
       g.qt_titulos,
       round(g.vl * (g.qt_titulos - 1), 2) AS vl_exposicao,
       g.qt_pagos, g.vl_ja_pago,
       g.venc_ini, g.venc_fim,
       (g.venc_fim - g.venc_ini) AS dias_entre,
       CASE WHEN g.venc_ini = g.venc_fim AND g.qt_pagos = g.qt_titulos THEN 'alta'
            WHEN g.venc_ini = g.venc_fim                                THEN 'media'
            ELSE 'baixa' END AS confianca,
       g.ar_cd_titulo, g.ar_nr_titulo, g.ar_vencimento, g.ar_quitacao, g.ar_filial
  FROM grp g
  LEFT JOIN pessoa p ON p.cd_pessoa = g.cd_pessoa
 ORDER BY (g.vl * (g.qt_titulos - 1)) DESC
 LIMIT %(limite)s""",
        ["dias", "dias_retro", "vl_min", "max_parcelas", "cd_pessoa_filial", "limite"], False,
        "titulos a pagar do mesmo fornecedor, mesmo valor e vencimento a menos de N dias - possivel pagamento em duplicidade"),

    "faturamento.cte_sem_titulo": (
        """\
-- faturamento.cte_sem_titulo
-- CT-e autorizado na SEFAZ (ctrc_cte.cd_status = 100), nao cancelado, que nao
-- gerou titulo a receber. O vinculo real e ctrc.cd_movimento -> titulo.cd_movimento
-- com titulo.id_tipo = 1: se cd_movimento e NULL nao existe titulo nenhum.
SELECT c.cd_ctrc,
       c.nr_ctrc,
       btrim(c.ds_serie) AS ds_serie,
       c.dt_emissao,
       c.vl_total,
       c.cd_pessoa_pagador,
       coalesce(nullif(p.nm_fantasia,''), p.nm_pessoa) AS cliente,
       p.nr_cnpj_cpf,
       c.cd_pessoa_filial,
       coalesce(nullif(pf.nm_fantasia,''), pf.nm_pessoa) AS filial,
       (CURRENT_DATE - c.dt_emissao) AS dias_sem_faturar,
       c.id_frete,
       c.id_tipo AS id_tipo_ctrc,
       c.id_proprietario_veiculo,
       cc.nr_chave,
       count(*)      OVER () AS qt_total,
       sum(c.vl_total) OVER () AS vl_total_geral
  FROM ctrc c
  JOIN ctrc_cte cc ON cc.cd_ctrc = c.cd_ctrc AND cc.cd_status = 100
  LEFT JOIN pessoa p  ON p.cd_pessoa = c.cd_pessoa_pagador
  LEFT JOIN pessoa pf ON pf.cd_pessoa = c.cd_pessoa_filial
 WHERE c.dt_cancelamento IS NULL
   AND c.dt_emissao BETWEEN CURRENT_DATE - %(dias)s AND CURRENT_DATE - %(carencia_dias)s
   AND c.cd_movimento IS NULL
   AND (%(cd_pessoa_filial)s IS NULL OR c.cd_pessoa_filial = %(cd_pessoa_filial)s)
 ORDER BY c.vl_total DESC
 LIMIT %(limite)s""",
        ["dias", "carencia_dias", "cd_pessoa_filial", "limite"], False,
        "CT-es autorizados na SEFAZ nos ultimos N dias que nao geraram titulo a receber"),

    "comercial.cliente_que_sumiu": (
        """\
-- comercial.cliente_que_sumiu
-- Cliente (pagador do CT-e) que faturava com regularidade na janela base
-- (:dias_base dias anteriores) e parou ou caiu na janela recente (:dias_recente).
WITH base AS (
  SELECT c.cd_pessoa_pagador, c.dt_emissao, c.vl_total, c.cd_pessoa_filial
    FROM ctrc c
   WHERE c.dt_cancelamento IS NULL
     AND c.dt_emissao >= CURRENT_DATE - (%(dias_base)s + %(dias_recente)s)
     AND c.cd_pessoa_pagador IS NOT NULL
     AND (%(cd_pessoa_filial)s IS NULL OR c.cd_pessoa_filial = %(cd_pessoa_filial)s)
), calc AS (
  SELECT b.cd_pessoa_pagador,
         sum(b.vl_total) FILTER (WHERE b.dt_emissao <  CURRENT_DATE - %(dias_recente)s) AS vl_base,
         count(*)        FILTER (WHERE b.dt_emissao <  CURRENT_DATE - %(dias_recente)s) AS qt_base,
         count(DISTINCT date_trunc('month', b.dt_emissao))
                         FILTER (WHERE b.dt_emissao <  CURRENT_DATE - %(dias_recente)s) AS meses_ativos,
         COALESCE(sum(b.vl_total) FILTER (WHERE b.dt_emissao >= CURRENT_DATE - %(dias_recente)s), 0) AS vl_recente,
         COALESCE(count(*)        FILTER (WHERE b.dt_emissao >= CURRENT_DATE - %(dias_recente)s), 0) AS qt_recente,
         max(b.dt_emissao)        AS dt_ultimo_cte,
         max(b.cd_pessoa_filial)  AS cd_pessoa_filial
    FROM base b
   GROUP BY 1
)
SELECT c.cd_pessoa_pagador,
       coalesce(nullif(p.nm_fantasia,''), p.nm_pessoa) AS cliente,
       p.nr_cnpj_cpf,
       c.meses_ativos,
       c.qt_base,
       c.vl_base,
       round(c.vl_base / (%(dias_base)s / 30.0), 2)      AS vl_media_mensal_anterior,
       c.qt_recente,
       c.vl_recente,
       round(c.vl_recente / (%(dias_recente)s / 30.0), 2) AS vl_media_mensal_recente,
       round(100.0 * (1 - (c.vl_recente / (%(dias_recente)s / 30.0))
                        / NULLIF(c.vl_base / (%(dias_base)s / 30.0), 0)), 2) AS pr_queda,
       round((c.vl_base / (%(dias_base)s / 30.0))
             - (c.vl_recente / (%(dias_recente)s / 30.0)), 2) AS vl_perda_mensal,
       c.dt_ultimo_cte,
       (CURRENT_DATE - c.dt_ultimo_cte) AS dias_sem_cte,
       CASE WHEN c.qt_recente = 0 THEN 'parou' ELSE 'caiu' END AS situacao,
       c.cd_pessoa_filial
  FROM calc c
  LEFT JOIN pessoa p ON p.cd_pessoa = c.cd_pessoa_pagador
 WHERE c.meses_ativos >= %(meses_min)s
   AND c.vl_base / (%(dias_base)s / 30.0) >= %(vl_mensal_min)s
   AND (c.vl_recente / (%(dias_recente)s / 30.0))
       < (1 - %(pr_queda_min)s / 100.0) * (c.vl_base / (%(dias_base)s / 30.0))
 ORDER BY vl_perda_mensal DESC
 LIMIT %(limite)s""",
        ["dias_base", "dias_recente", "meses_min", "vl_mensal_min", "pr_queda_min", "cd_pessoa_filial", "limite"], False,
        "clientes regulares na janela base que pararam ou cairam mais de N% na janela recente"),

    "controladoria.margem_por_cte": (
        """\
-- controladoria.margem_por_cte
-- Receita do CT-e contra custo real de frete (carta_frete.vl_frete).
-- Linha 'total' = agregado; linhas 'pior_caso' = CT-es com margem negativa ou
-- abaixo de :pr_margem_min. CT-e sem carta frete NAO entra na margem: e contado
-- em qt_sem_carta_frete. Custo zero (carta existe, vl_frete = 0) e contado a parte.
WITH ct AS (
  SELECT c.cd_ctrc, c.nr_ctrc, btrim(c.ds_serie) AS ds_serie, c.dt_emissao,
         c.vl_total, c.cd_pessoa_filial, c.cd_pessoa_pagador,
         (SELECT sum(cf.vl_frete) FROM carta_frete cf WHERE cf.cd_ctrc = c.cd_ctrc) AS vl_custo
    FROM ctrc c
   WHERE c.dt_cancelamento IS NULL
     AND c.dt_emissao >= CURRENT_DATE - %(dias)s
     AND (%(cd_pessoa_filial)s IS NULL OR c.cd_pessoa_filial = %(cd_pessoa_filial)s)
), cls AS (
  SELECT ct.*,
         CASE WHEN ct.vl_custo IS NULL THEN 'sem_carta_frete' ELSE 'com_custo' END AS classe,
         (ct.vl_total - COALESCE(ct.vl_custo, 0)) AS vl_margem
    FROM ct
), agg AS (
  SELECT count(*)      FILTER (WHERE classe = 'com_custo') AS qt_ctes,
         sum(vl_total) FILTER (WHERE classe = 'com_custo') AS vl_receita,
         sum(vl_custo) FILTER (WHERE classe = 'com_custo') AS vl_custo,
         sum(vl_margem) FILTER (WHERE classe = 'com_custo') AS vl_margem,
         count(*)      FILTER (WHERE classe = 'sem_carta_frete') AS qt_sem_carta_frete,
         sum(vl_total) FILTER (WHERE classe = 'sem_carta_frete') AS vl_sem_carta_frete,
         count(*)      FILTER (WHERE classe = 'com_custo' AND vl_custo = 0) AS qt_custo_zero,
         count(*)      FILTER (WHERE classe = 'com_custo' AND vl_margem < 0) AS qt_margem_negativa,
         sum(vl_margem) FILTER (WHERE classe = 'com_custo' AND vl_margem < 0) AS vl_margem_negativa
    FROM cls
)
SELECT 'total' AS linha,
       NULL::int AS cd_ctrc, NULL::bigint AS nr_ctrc, NULL::text AS ds_serie,
       NULL::date AS dt_emissao, NULL::text AS cliente, NULL::int AS cd_pessoa_filial,
       a.qt_ctes, a.vl_receita, a.vl_custo, a.vl_margem,
       round(100.0 * a.vl_margem / NULLIF(a.vl_receita, 0), 2) AS pr_margem,
       a.qt_sem_carta_frete, a.vl_sem_carta_frete, a.qt_custo_zero,
       a.qt_margem_negativa, a.vl_margem_negativa
  FROM agg a
UNION ALL
SELECT 'pior_caso', x.cd_ctrc, x.nr_ctrc, x.ds_serie, x.dt_emissao,
       coalesce(nullif(p.nm_fantasia,''), p.nm_pessoa), x.cd_pessoa_filial,
       1, x.vl_total, x.vl_custo, x.vl_margem,
       round(100.0 * x.vl_margem / NULLIF(x.vl_total, 0), 2),
       NULL, NULL, NULL, NULL, NULL
  FROM cls x
  LEFT JOIN pessoa p ON p.cd_pessoa = x.cd_pessoa_pagador
 WHERE x.classe = 'com_custo'
   AND (x.vl_margem < 0 OR 100.0 * x.vl_margem / NULLIF(x.vl_total, 0) < %(pr_margem_min)s)
 ORDER BY 1 DESC, 11
 LIMIT %(limite)s""",
        ["dias", "pr_margem_min", "cd_pessoa_filial", "limite"], False,
        "receita do CT-e contra custo real de carta frete no periodo, agregado e piores casos"),

    "frota.resultado_veiculo": (
        """\
-- frota.resultado_veiculo
-- Resultado por placa da FROTA PROPRIA (veiculo_proprio, dt_baixa IS NULL).
-- Receita: CT-es com ctrc.id_proprietario_veiculo = 1 (frota propria) via ctrc.cd_veiculo.
-- Custo:  lancamentos de caixa amarrados ao veiculo (caixa_veiculo -> caixa),
--         classificados por historico_caixa.ds_historico.
-- A carta_frete emitida nesses CT-es e transferencia interna (transportadora = a
-- propria Pianetto); vem como coluna informativa e NAO entra no resultado.
WITH frota AS (
  SELECT v.cd_veiculo, btrim(v.ds_placa) AS ds_placa, v.ds_modelo,
         vp.nr_frota, tv.nm_tipo_veiculo,
         (tv.nm_tipo_veiculo ILIKE 'CAVALO%%' OR tv.nm_tipo_veiculo ILIKE '%%TRATOR%%') AS id_tracao
    FROM veiculo_proprio vp
    JOIN veiculo v ON v.cd_veiculo = vp.cd_veiculo
    LEFT JOIN tipo_veiculo tv ON tv.cd_tipo_veiculo = v.cd_tipo_veiculo
   WHERE vp.dt_baixa IS NULL
), rec AS (
  SELECT c.cd_veiculo,
         count(*) AS qt_ctes,
         sum(c.vl_total) AS vl_receita,
         sum(COALESCE(c.vl_peso, 0)) AS vl_peso,
         sum(COALESCE(c.vl_km_rodado, 0)) AS vl_km,
         max(c.dt_emissao) AS dt_ultimo_cte,
         max(c.cd_pessoa_filial) AS cd_pessoa_filial,
         sum((SELECT COALESCE(sum(cf.vl_frete), 0) FROM carta_frete cf
               WHERE cf.cd_ctrc = c.cd_ctrc)) AS vl_carta_frete_interna
    FROM ctrc c
   WHERE c.dt_cancelamento IS NULL
     AND c.dt_emissao >= CURRENT_DATE - %(dias)s
     AND c.id_proprietario_veiculo = 1
     AND c.cd_veiculo IS NOT NULL
     AND (%(cd_pessoa_filial)s IS NULL OR c.cd_pessoa_filial = %(cd_pessoa_filial)s)
   GROUP BY 1
), agr AS (
  -- A MESMA placa emitindo conhecimento fora da frota propria (agregado = 2,
  -- terceiro = 3). Enquanto isso existe, o veiculo tem custo na frota e
  -- receita fora dela: o resultado da frota fica errado nos dois lados.
  SELECT c.cd_veiculo,
         count(*) AS qt_ctes_agregado,
         sum(c.vl_total) AS vl_receita_agregado,
         sum(COALESCE(c.vl_km_rodado, 0)) AS vl_km_agregado,
         string_agg(DISTINCT c.id_proprietario_veiculo::text, ',') AS ds_proprietarios_outros
    FROM ctrc c
   WHERE c.dt_cancelamento IS NULL
     AND c.dt_emissao >= CURRENT_DATE - %(dias)s
     AND c.id_proprietario_veiculo <> 1
     AND c.cd_veiculo IS NOT NULL
   GROUP BY 1
), cx AS (
  SELECT cv.cd_veiculo,
         sum(k.vl_lancamento) AS vl_caixa_total,
         sum(k.vl_lancamento) FILTER (WHERE upper(coalesce(h.ds_historico,'')) LIKE '%%COMBUST%%') AS vl_combustivel,
         -- 'PE.A' pegava PESADOS em "COMBUSTIVEL VEIC. PESADOS" e contava
         -- combustivel como manutencao. O ponto virou classe fechada.
         sum(k.vl_lancamento) FILTER (WHERE upper(coalesce(h.ds_historico,'')) ~ 'MANUT|PE[CC]A|PE[CÇ]A|PNEU|BORRACH|ESTOFARIA|RETIFIC') AS vl_manutencao,
         sum(k.vl_lancamento) FILTER (WHERE upper(coalesce(h.ds_historico,'')) LIKE '%%PEDAGIO%%') AS vl_pedagio,
         sum(k.vl_lancamento) FILTER (WHERE upper(coalesce(h.ds_historico,'')) ~ 'SALARIO|RECISAO|RESCISAO') AS vl_pessoal,
         count(*) AS qt_lancamentos
    FROM caixa_veiculo cv
    JOIN caixa k ON k.cd_caixa = cv.cd_caixa
    LEFT JOIN historico_caixa h ON h.cd_historico = k.cd_historico
   WHERE k.dt_documento BETWEEN CURRENT_DATE - %(dias)s AND CURRENT_DATE
   GROUP BY 1
)
SELECT f.cd_veiculo, f.ds_placa, f.nr_frota, f.ds_modelo, f.nm_tipo_veiculo, f.id_tracao,
       COALESCE(r.qt_ctes, 0)          AS qt_ctes,
       COALESCE(r.vl_receita, 0)       AS vl_receita,
       COALESCE(cx.vl_combustivel, 0)  AS vl_combustivel,
       COALESCE(cx.vl_manutencao, 0)   AS vl_manutencao,
       COALESCE(cx.vl_pedagio, 0)      AS vl_pedagio,
       COALESCE(cx.vl_pessoal, 0)      AS vl_pessoal,
       COALESCE(cx.vl_caixa_total, 0)  AS vl_custo_identificavel,
       (COALESCE(r.vl_receita, 0) - COALESCE(cx.vl_caixa_total, 0)) AS vl_contribuicao,
       round(100.0 * (COALESCE(r.vl_receita, 0) - COALESCE(cx.vl_caixa_total, 0))
             / NULLIF(r.vl_receita, 0), 2) AS pr_contribuicao,
       COALESCE(r.vl_carta_frete_interna, 0) AS vl_carta_frete_interna,
       COALESCE(r.vl_peso, 0) AS vl_peso,
       COALESCE(r.vl_km, 0)   AS vl_km,
       r.dt_ultimo_cte, r.cd_pessoa_filial,
       COALESCE(cx.qt_lancamentos, 0) AS qt_lancamentos_caixa,
       COALESCE(a.qt_ctes_agregado, 0)    AS qt_ctes_agregado,
       COALESCE(a.vl_receita_agregado, 0) AS vl_receita_agregado,
       COALESCE(a.vl_km_agregado, 0)      AS vl_km_agregado,
       a.ds_proprietarios_outros
  FROM frota f
  LEFT JOIN rec r ON r.cd_veiculo = f.cd_veiculo
  LEFT JOIN cx    ON cx.cd_veiculo = f.cd_veiculo
  LEFT JOIN agr a ON a.cd_veiculo = f.cd_veiculo
 WHERE COALESCE(r.qt_ctes, 0) > 0 OR COALESCE(cx.qt_lancamentos, 0) > 0
 ORDER BY (COALESCE(r.vl_receita, 0) - COALESCE(cx.vl_caixa_total, 0)) ASC
 LIMIT %(limite)s""",
        ["dias", "cd_pessoa_filial", "limite"], False,
        "receita e custo identificavel por placa da frota propria no periodo"),

    "frota.abastecimento_veiculo": (
        """\
-- frota.abastecimento_veiculo
-- O diesel por dentro. O resultado por placa so enxerga o VALOR do combustivel
-- (historico_caixa LIKE '%%COMBUST%%'). Aqui a mesma despesa e aberta em
-- litro, preco do litro e leitura de painel, usando o item da despesa
-- (caixa_produto, cd_produto = 6 DIESEL) amarrado ao veiculo por caixa_veiculo.
-- Com isso da para separar duas coisas que o valor sozinho mistura:
--   . abastecer CARO   -> preco medio do litro acima do resto da frota
--   . abastecer DEMAIS -> litro por quilometro rodado acima do resto da frota
-- Limites honestos: o km vem da diferenca entre a primeira e a ultima leitura
-- do periodo, entao ignora o que o veiculo rodou antes do primeiro
-- abastecimento; troca de painel derruba a conta e aparece como km_l absurdo.
-- qt_abast_acima_tanque conta o abastecimento cuja litragem passou da
-- capacidade cadastrada do tanque: ou o cadastro esta errado, ou o bico
-- encheu mais de um tanque.
WITH frota AS (
  SELECT v.cd_veiculo, btrim(v.ds_placa) AS ds_placa,
         vp.nr_frota, vp.qt_litros_tanque,
         (tv.nm_tipo_veiculo ILIKE 'CAVALO%%' OR tv.nm_tipo_veiculo ILIKE '%%TRATOR%%') AS id_tracao
    FROM veiculo_proprio vp
    JOIN veiculo v ON v.cd_veiculo = vp.cd_veiculo
    LEFT JOIN tipo_veiculo tv ON tv.cd_tipo_veiculo = v.cd_tipo_veiculo
   WHERE vp.dt_baixa IS NULL
), item AS (
  SELECT cv.cd_veiculo, cx.cd_caixa, k.dt_documento,
         cp.qt_produto, cp.vl_total, cv.vl_medidor
    FROM caixa_produto cp
    JOIN caixa cx ON cx.cd_caixa = cp.cd_caixa
    JOIN caixa k  ON k.cd_caixa = cx.cd_caixa
    JOIN caixa_veiculo cv ON cv.cd_caixa = cx.cd_caixa
   WHERE cp.cd_produto = 6
     AND cp.qt_produto > 0
     AND k.dt_documento BETWEEN CURRENT_DATE - %(dias)s AND CURRENT_DATE
), ab AS (
  SELECT i.cd_veiculo,
         count(DISTINCT i.cd_caixa) AS qt_abastecimentos,
         sum(i.qt_produto)          AS qt_litros,
         sum(i.vl_total)            AS vl_diesel,
         min(NULLIF(i.vl_medidor, 0)) AS vl_hodometro_min,
         max(NULLIF(i.vl_medidor, 0)) AS vl_hodometro_max,
         count(*) FILTER (WHERE COALESCE(i.vl_medidor, 0) = 0) AS qt_sem_hodometro,
         max(i.dt_documento) AS dt_ultimo_abastecimento
    FROM item i
   GROUP BY 1
), estouro AS (
  SELECT i.cd_veiculo, count(*) AS qt_abast_acima_tanque
    FROM item i
    JOIN frota f ON f.cd_veiculo = i.cd_veiculo
   WHERE COALESCE(f.qt_litros_tanque, 0) > 0
     AND i.qt_produto > f.qt_litros_tanque
   GROUP BY 1
)
SELECT f.cd_veiculo, f.ds_placa, f.nr_frota, f.id_tracao,
       COALESCE(f.qt_litros_tanque, 0) AS qt_litros_tanque,
       ab.qt_abastecimentos, ab.qt_litros, ab.vl_diesel,
       round(ab.vl_diesel / NULLIF(ab.qt_litros, 0), 3) AS vl_preco_litro,
       ab.vl_hodometro_min, ab.vl_hodometro_max,
       (ab.vl_hodometro_max - ab.vl_hodometro_min) AS vl_km_hodometro,
       round((ab.vl_hodometro_max - ab.vl_hodometro_min)
             / NULLIF(ab.qt_litros, 0), 2) AS vl_km_por_litro,
       ab.qt_sem_hodometro,
       COALESCE(e.qt_abast_acima_tanque, 0) AS qt_abast_acima_tanque,
       ab.dt_ultimo_abastecimento
  FROM frota f
  JOIN ab ON ab.cd_veiculo = f.cd_veiculo
  LEFT JOIN estouro e ON e.cd_veiculo = f.cd_veiculo
 ORDER BY ab.vl_diesel DESC
 LIMIT %(limite)s""",
        ["dias", "limite"], False,
        "litro, preco do litro e km por litro por placa da frota propria"),

    "contraprova.km_por_hodometro": (
        """\
-- contraprova.km_por_hodometro
-- O quilometro por OUTRA porta. O plano por veiculo se apoia em
-- ctrc.vl_km_rodado: distancia declarada no conhecimento. Aqui a distancia vem
-- do hodometro lido no abastecimento (caixa_veiculo.vl_medidor), que e leitura
-- de painel, nao declaracao de documento.
-- Duas coisas aparecem quando os dois numeros divergem:
--   . hodometro >> CT-e  -> o veiculo rodou sem conhecimento emitido nele
--   . hodometro << CT-e  -> quilometragem declarada acima do que o painel andou
-- Troca de painel zera o medidor e produz salto absurdo; a coluna
-- id_salto marca isso em vez de esconder.
WITH leit AS (
  SELECT cv.cd_veiculo, k.dt_documento::date AS d, cv.vl_medidor AS m
    FROM caixa_veiculo cv
    JOIN caixa k ON k.cd_caixa = cv.cd_caixa
   WHERE cv.vl_medidor > 0
     AND k.dt_documento BETWEEN CURRENT_DATE - %(dias)s AND CURRENT_DATE
)
, outro AS (
  -- O MESMO veiculo emitindo conhecimento como agregado ou terceiro. A
  -- apuracao de frota propria filtra id_proprietario_veiculo = 1 e nao ve
  -- isto; e a explicacao mais provavel para painel que anda sem CT-e.
  SELECT c.cd_veiculo,
         count(*) AS qt_ctes_outro,
         sum(c.vl_total) AS vl_receita_outro,
         sum(COALESCE(c.vl_km_rodado, 0)) AS km_outro,
         string_agg(DISTINCT c.id_proprietario_veiculo::text, ',') AS ds_proprietarios
    FROM ctrc c
   WHERE c.dt_cancelamento IS NULL
     AND c.dt_emissao >= CURRENT_DATE - %(dias)s
     AND c.id_proprietario_veiculo <> 1
     AND c.cd_veiculo IS NOT NULL
   GROUP BY 1
)
SELECT v.cd_veiculo, btrim(v.ds_placa) AS ds_placa, v.ds_modelo,
       count(*)        AS qt_leituras,
       min(l.m)        AS km_inicial,
       max(l.m)        AS km_final,
       (max(l.m) - min(l.m)) AS km_hodometro,
       min(l.d)        AS primeira_leitura,
       max(l.d)        AS ultima_leitura,
       ((max(l.m) - min(l.m)) > %(dias)s * 900) AS id_salto,
       COALESCE(o.qt_ctes_outro, 0)    AS qt_ctes_outro,
       COALESCE(o.vl_receita_outro, 0) AS vl_receita_outro,
       COALESCE(o.km_outro, 0)         AS km_outro,
       o.ds_proprietarios
  FROM leit l
  JOIN veiculo v ON v.cd_veiculo = l.cd_veiculo
  LEFT JOIN outro o ON o.cd_veiculo = l.cd_veiculo
 GROUP BY 1, 2, 3, o.qt_ctes_outro, o.vl_receita_outro, o.km_outro,
          o.ds_proprietarios
HAVING count(*) >= 2
 ORDER BY (max(l.m) - min(l.m)) DESC
 LIMIT %(limite)s""",
        ["dias", "limite"], False,
        "quilometragem pelo hodometro do abastecimento e conhecimento "
        "emitido na mesma placa fora da frota propria"),

    "lucratividade.por_setor": (
        """\
-- lucratividade.por_setor
-- Resultado por setor economico, na chave que decide o custo:
-- ctrc.id_proprietario_veiculo (1 = frota propria, 2 = agregado, 3 = terceiro).
-- Agenciamento (2 e 3): o custo e a carta frete paga ao transportador.
-- Frota propria (1): a carta frete e paga a PROPRIA Pianetto (transferencia
-- interna) e por isso NAO entra como custo; entra o caixa amarrado ao veiculo.
-- CT-e sem carta frete fica fora do custo e e contado a parte: tratar como
-- custo zero inventaria margem.
WITH ct AS (
  SELECT c.cd_ctrc, c.vl_total,
         CASE c.id_proprietario_veiculo WHEN 1 THEN 'frota_propria' WHEN 2 THEN 'agregado'
              WHEN 3 THEN 'terceiro' ELSE 'sem_classificacao' END AS setor,
         (SELECT sum(f.vl_frete) FROM carta_frete f WHERE f.cd_ctrc = c.cd_ctrc) AS vl_carta
    FROM ctrc c
   WHERE c.dt_cancelamento IS NULL
     AND c.dt_emissao >= CURRENT_DATE - %(dias)s
     AND (%(cd_pessoa_filial)s IS NULL OR c.cd_pessoa_filial = %(cd_pessoa_filial)s)
), rec AS (
  SELECT setor,
         count(*) AS qt_ctes,
         sum(vl_total) AS vl_receita,
         sum(vl_carta) FILTER (WHERE setor <> 'frota_propria') AS vl_frete_terceiro,
         sum(vl_carta) FILTER (WHERE setor =  'frota_propria') AS vl_carta_interna,
         count(*)      FILTER (WHERE vl_carta IS NULL) AS qt_sem_custo,
         sum(vl_total) FILTER (WHERE vl_carta IS NULL) AS vl_sem_custo
    FROM ct GROUP BY 1
), frota AS (
  SELECT sum(k.vl_lancamento) AS vl_caixa, count(*) AS qt_lanc
    FROM caixa_veiculo cv
    JOIN caixa k ON k.cd_caixa = cv.cd_caixa
    JOIN veiculo_proprio vp ON vp.cd_veiculo = cv.cd_veiculo AND vp.dt_baixa IS NULL
   WHERE k.dt_documento BETWEEN CURRENT_DATE - %(dias)s AND CURRENT_DATE
)
SELECT r.setor,
       r.qt_ctes,
       round(COALESCE(r.vl_receita, 0)::numeric, 2)        AS vl_receita,
       round(COALESCE(r.vl_frete_terceiro, 0)::numeric, 2) AS vl_frete_terceiro,
       round((CASE WHEN r.setor = 'frota_propria'
                   THEN COALESCE((SELECT vl_caixa FROM frota), 0) ELSE 0 END)::numeric, 2) AS vl_custo_frota,
       round((COALESCE(r.vl_receita, 0) - COALESCE(r.vl_frete_terceiro, 0)
              - CASE WHEN r.setor = 'frota_propria'
                     THEN COALESCE((SELECT vl_caixa FROM frota), 0) ELSE 0 END)::numeric, 2) AS vl_margem,
       round((100.0 * (COALESCE(r.vl_receita, 0) - COALESCE(r.vl_frete_terceiro, 0)
              - CASE WHEN r.setor = 'frota_propria'
                     THEN COALESCE((SELECT vl_caixa FROM frota), 0) ELSE 0 END)
              / NULLIF(r.vl_receita, 0))::numeric, 2) AS pr_margem,
       round(COALESCE(r.vl_carta_interna, 0)::numeric, 2) AS vl_carta_interna,
       r.qt_sem_custo,
       round(COALESCE(r.vl_sem_custo, 0)::numeric, 2) AS vl_sem_custo,
       COALESCE((SELECT qt_lanc FROM frota), 0) AS qt_lancamentos_frota
  FROM rec r
 ORDER BY 3 DESC""",
        ["dias", "cd_pessoa_filial"], False,
        "receita e custo por setor economico: frota propria, agregado e terceiro"),

    "lucratividade.por_agencia": (
        """\
-- lucratividade.por_agencia
-- Cada CT-e nasce numa agencia (ctrc.cd_agencia). Receita e custo direto de
-- frete por unidade, mais a despesa lancada no centro de custo ligado a
-- agencia (agencia_centro_custo -> caixa_participacao).
-- Ressalva de leitura: o centro de custo da matriz recebe despesa geral da
-- empresa, entao o resultado dela nao e comparavel com o de uma agencia.
-- O custo do veiculo proprio NAO esta aqui: ele nao e rateado por agencia.
WITH ct AS (
  SELECT c.cd_agencia, c.vl_total, c.id_proprietario_veiculo AS tipo,
         (SELECT sum(f.vl_frete) FROM carta_frete f WHERE f.cd_ctrc = c.cd_ctrc) AS vl_carta
    FROM ctrc c
   WHERE c.dt_cancelamento IS NULL
     AND c.dt_emissao >= CURRENT_DATE - %(dias)s
     AND (%(cd_pessoa_filial)s IS NULL OR c.cd_pessoa_filial = %(cd_pessoa_filial)s)
), rec AS (
  SELECT cd_agencia,
         count(*) AS qt_ctes,
         sum(vl_total) AS vl_receita,
         sum(vl_total) FILTER (WHERE tipo = 1)  AS vl_receita_frota,
         sum(vl_carta) FILTER (WHERE tipo <> 1) AS vl_frete_terceiro,
         count(*)      FILTER (WHERE tipo <> 1 AND vl_carta IS NULL) AS qt_sem_custo,
         sum(vl_total) FILTER (WHERE tipo <> 1 AND vl_carta IS NULL) AS vl_sem_custo
    FROM ct GROUP BY 1
), desp AS (
  SELECT ac.cd_agencia, sum(cp.vl_participacao) AS vl_despesa, count(*) AS qt_lanc
    FROM agencia_centro_custo ac
    JOIN caixa_participacao cp ON cp.cd_centro_custo = ac.cd_centro_custo
    JOIN caixa k ON k.cd_caixa = cp.cd_caixa
   WHERE k.dt_documento BETWEEN CURRENT_DATE - %(dias)s AND CURRENT_DATE
   GROUP BY 1
)
SELECT a.cd_agencia, btrim(a.nm_agencia) AS nm_agencia, r.qt_ctes,
       round(COALESCE(r.vl_receita, 0)::numeric, 2)        AS vl_receita,
       round(COALESCE(r.vl_receita_frota, 0)::numeric, 2)  AS vl_receita_frota,
       round(COALESCE(r.vl_frete_terceiro, 0)::numeric, 2) AS vl_frete_terceiro,
       round((COALESCE(r.vl_receita, 0) - COALESCE(r.vl_frete_terceiro, 0))::numeric, 2) AS vl_margem_bruta,
       round(COALESCE(d.vl_despesa, 0)::numeric, 2)        AS vl_despesa_agencia,
       round((COALESCE(r.vl_receita, 0) - COALESCE(r.vl_frete_terceiro, 0)
              - COALESCE(d.vl_despesa, 0))::numeric, 2)    AS vl_resultado,
       round((100.0 * (COALESCE(r.vl_receita, 0) - COALESCE(r.vl_frete_terceiro, 0)
              - COALESCE(d.vl_despesa, 0)) / NULLIF(r.vl_receita, 0))::numeric, 2) AS pr_resultado,
       COALESCE(r.qt_sem_custo, 0) AS qt_sem_custo,
       round(COALESCE(r.vl_sem_custo, 0)::numeric, 2) AS vl_sem_custo,
       (d.cd_agencia IS NOT NULL) AS id_centro_custo_ligado,
       COALESCE(d.qt_lanc, 0) AS qt_lancamentos_despesa
  FROM rec r
  JOIN agencia a ON a.cd_agencia = r.cd_agencia
  LEFT JOIN desp d ON d.cd_agencia = r.cd_agencia
 ORDER BY 4 DESC
 LIMIT %(limite)s""",
        ["dias", "cd_pessoa_filial", "limite"], False,
        "receita, custo de frete e despesa de centro de custo por agencia"),

    "contraprova.lucratividade_custo_frota": (
        """\
-- contraprova.lucratividade_custo_frota
-- O custo da frota por OUTRA porta do banco. O apurador soma o caixa amarrado
-- ao veiculo (caixa_veiculo). Aqui o caminho e o centro de custo: placa,
-- FROTA e OFICINA em caixa_participacao. Se os dois caminhos divergirem muito,
-- o custo declarado nao esta fechado.
-- A carta frete da frota propria vem junto, com o nome de quem recebeu: e o
-- teste de que ela e transferencia interna, e nao custo.
WITH placas AS (
  SELECT DISTINCT btrim(v.ds_placa) AS ds_placa
    FROM veiculo_proprio vp JOIN veiculo v ON v.cd_veiculo = vp.cd_veiculo
   WHERE vp.dt_baixa IS NULL
), cc_frota AS (
  SELECT cc.cd_centro_custo
    FROM centro_custo cc
   WHERE btrim(cc.nm_centro_custo) IN (SELECT ds_placa FROM placas)
      OR upper(btrim(cc.nm_centro_custo)) LIKE '%%FROTA%%'
      OR upper(btrim(cc.nm_centro_custo)) LIKE 'OFICINA%%'
), por_cc AS (
  SELECT sum(cp.vl_participacao) AS vl, count(*) AS qt
    FROM cc_frota f
    JOIN caixa_participacao cp ON cp.cd_centro_custo = f.cd_centro_custo
    JOIN caixa k ON k.cd_caixa = cp.cd_caixa
   WHERE k.dt_documento BETWEEN CURRENT_DATE - %(dias)s AND CURRENT_DATE
), por_veiculo AS (
  -- placas COM lancamento no periodo, nao placas cadastradas: dizer "257
  -- placas" quando so 105 tiveram despesa infla a base e esconde o veiculo
  -- parado.
  SELECT sum(k.vl_lancamento) AS vl, count(*) AS qt,
         count(DISTINCT cv.cd_veiculo) AS qt_placas
    FROM caixa_veiculo cv
    JOIN caixa k ON k.cd_caixa = cv.cd_caixa
    JOIN veiculo_proprio vp ON vp.cd_veiculo = cv.cd_veiculo AND vp.dt_baixa IS NULL
   WHERE k.dt_documento BETWEEN CURRENT_DATE - %(dias)s AND CURRENT_DATE
), carta AS (
  SELECT coalesce(nullif(p.nm_fantasia, ''), p.nm_pessoa) AS nm_recebedor,
         count(*) AS qt, sum(f.vl_frete) AS vl
    FROM ctrc c
    JOIN carta_frete f ON f.cd_ctrc = c.cd_ctrc
    LEFT JOIN pessoa p ON p.cd_pessoa = c.cd_pessoa_transportadora
   WHERE c.dt_cancelamento IS NULL
     AND c.dt_emissao >= CURRENT_DATE - %(dias)s
     AND c.id_proprietario_veiculo = 1
   GROUP BY 1
)
SELECT 'custo' AS linha, 'centro_custo' AS caminho, NULL::text AS nm_recebedor,
       round(COALESCE((SELECT vl FROM por_cc), 0)::numeric, 2) AS vl,
       COALESCE((SELECT qt FROM por_cc), 0) AS qt,
       (SELECT count(*) FROM cc_frota) AS qt_chaves
UNION ALL
SELECT 'custo', 'caixa_veiculo', NULL,
       round(COALESCE((SELECT vl FROM por_veiculo), 0)::numeric, 2),
       COALESCE((SELECT qt FROM por_veiculo), 0),
       COALESCE((SELECT qt_placas FROM por_veiculo), 0)
UNION ALL
SELECT 'carta_frete_propria', 'ctrc', c.nm_recebedor,
       round(c.vl::numeric, 2), c.qt, NULL
  FROM carta c
 ORDER BY 1, 4 DESC""",
        ["dias"], False,
        "custo da frota por centro de custo contra caixa do veiculo, e quem recebe a carta frete propria"),

    "fiscal.cte_pendente": (
        """\
-- fiscal.cte_pendente
-- Situacao fiscal real vem de ctrc_cte.cd_status (codigo SEFAZ) + status_cte.ds_status.
-- 100 = autorizado, 101 = cancelado homologado, 102 = inutilizado,
-- 110/301/303 = denegado, demais = rejeicao. Sem linha em ctrc_cte = nunca transmitido.
-- ctrc.id_modelo = '55' e NF-e (nao CT-e) e por isso nao tem registro em ctrc_cte:
-- fica em classe propria para nao virar falso positivo.
WITH base AS (
  SELECT c.cd_ctrc, c.nr_ctrc, btrim(c.ds_serie) AS ds_serie, c.id_modelo,
         c.dt_emissao, c.vl_total, c.cd_pessoa_filial, c.cd_pessoa_pagador,
         c.dt_cancelamento, cc.cd_status, cc.nr_protocolo, cc.nr_chave,
         CASE
           WHEN c.id_modelo = '55'               THEN 'nao_e_cte_modelo_55'
           WHEN cc.cd_ctrc IS NULL               THEN 'nunca_transmitido'
           WHEN cc.cd_status IS NULL             THEN 'sem_retorno_sefaz'
           WHEN cc.cd_status = 100               THEN 'autorizado'
           WHEN cc.cd_status = 101               THEN 'cancelado'
           WHEN cc.cd_status = 102               THEN 'inutilizado'
           WHEN cc.cd_status IN (110, 301, 303)  THEN 'denegado'
           ELSE 'rejeitado'
         END AS situacao
    FROM ctrc c
    LEFT JOIN ctrc_cte cc ON cc.cd_ctrc = c.cd_ctrc
   WHERE c.dt_emissao >= CURRENT_DATE - %(dias)s
     AND (%(cd_pessoa_filial)s IS NULL OR c.cd_pessoa_filial = %(cd_pessoa_filial)s)
), resumo AS (
  SELECT situacao, count(*) AS qt, sum(vl_total) AS vl FROM base GROUP BY 1
)
SELECT 'resumo' AS linha, r.situacao, r.qt, r.vl,
       NULL::int AS cd_ctrc, NULL::bigint AS nr_ctrc, NULL::text AS ds_serie,
       NULL::date AS dt_emissao, NULL::numeric AS vl_total, NULL::int AS cd_status,
       NULL::text AS ds_status, NULL::text AS cliente, NULL::int AS cd_pessoa_filial,
       NULL::date AS dt_cancelamento, NULL::int AS dias_parado
  FROM resumo r
UNION ALL
SELECT 'pendente', b.situacao, NULL, NULL,
       b.cd_ctrc, b.nr_ctrc, b.ds_serie, b.dt_emissao, b.vl_total, b.cd_status,
       left(coalesce(s.ds_status, '(sem retorno da SEFAZ)'), 140),
       coalesce(nullif(p.nm_fantasia,''), p.nm_pessoa),
       b.cd_pessoa_filial, b.dt_cancelamento,
       (CURRENT_DATE - b.dt_emissao)
  FROM base b
  LEFT JOIN status_cte s ON s.cd_status = b.cd_status
  LEFT JOIN pessoa p     ON p.cd_pessoa = b.cd_pessoa_pagador
 WHERE b.situacao IN ('nunca_transmitido', 'sem_retorno_sefaz', 'rejeitado', 'denegado', 'inutilizado')
   AND b.dt_cancelamento IS NULL
 ORDER BY 1, 3 DESC NULLS LAST, 9 DESC NULLS LAST
 LIMIT %(limite)s""",
        ["dias", "cd_pessoa_filial", "limite"], False,
        "CT-es dos ultimos N dias com situacao SEFAZ diferente de autorizado"),

    # ------------------------------------------------------- CONTRAPROVAS
    # Cada uma existe para um agente CONTESTAR o numero de outro agente,
    # chegando ao mesmo fato por outro caminho no banco. Nao substituem a
    # consulta original: dizem o que a original nao pode dizer.

    "contraprova.cte_sem_titulo_situacao": (
        """\
-- contraprova.cte_sem_titulo_situacao
-- CONTRAPROVA de faturamento.cte_sem_titulo (agente comercial).
-- A consulta original ja entra filtrando ctrc_cte.cd_status = 100 e
-- dt_cancelamento IS NULL: ela so ve o CT-e autorizado e vigente. Aqui o
-- universo e TODO documento sem titulo (ctrc.cd_movimento IS NULL) na MESMA
-- janela, quebrado pela situacao real na SEFAZ (ctrc_cte.cd_status +
-- status_cte.ds_status). CT-e cancelado, rejeitado ou nunca transmitido NAO
-- deveria ter titulo: ele esta corretamente sem titulo e nao e receita
-- nao faturada. Quem some da conta do comercial aparece aqui.
WITH base AS (
  SELECT c.cd_ctrc, c.vl_total, c.dt_emissao, c.dt_cancelamento, c.id_modelo,
         cc.cd_status,
         CASE
           WHEN c.id_modelo = '55'               THEN 'nao_e_cte_modelo_55'
           WHEN cc.cd_ctrc IS NULL               THEN 'nunca_transmitido'
           WHEN cc.cd_status IS NULL             THEN 'sem_retorno_sefaz'
           WHEN cc.cd_status = 100               THEN 'autorizado'
           WHEN cc.cd_status = 101               THEN 'cancelado'
           WHEN cc.cd_status = 102               THEN 'inutilizado'
           WHEN cc.cd_status IN (110, 301, 303)  THEN 'denegado'
           ELSE 'rejeitado'
         END AS situacao_sefaz
    FROM ctrc c
    LEFT JOIN ctrc_cte cc ON cc.cd_ctrc = c.cd_ctrc
   WHERE c.dt_emissao BETWEEN CURRENT_DATE - %(dias)s AND CURRENT_DATE - %(carencia_dias)s
     AND c.cd_movimento IS NULL
     AND (%(cd_pessoa_filial)s IS NULL OR c.cd_pessoa_filial = %(cd_pessoa_filial)s)
), cls AS (
  -- 'autorizado_vigente' e exatamente o universo da consulta original: o unico
  -- grupo em que a falta de titulo e de fato receita nao faturada.
  SELECT b.*,
         CASE WHEN b.situacao_sefaz = 'autorizado' AND b.dt_cancelamento IS NULL
                THEN 'autorizado_vigente'
              WHEN b.situacao_sefaz = 'autorizado'
                THEN 'autorizado_cancelado_no_erp'
              ELSE b.situacao_sefaz END AS situacao
    FROM base b
), tot AS (
  SELECT count(*) AS qt, sum(vl_total) AS vl FROM cls
)
-- linha 'total': a janela inteira de CT-es sem titulo
SELECT 1 AS nr_ordem, 'total' AS linha, 'TODOS_SEM_TITULO' AS situacao,
       NULL::int AS cd_status, NULL::text AS ds_status,
       t.qt AS qt_ctes, t.vl AS vl_ctes,
       100.00::numeric AS pr_qt,
       NULL::bigint AS qt_cancelado_no_erp,
       NULL::date AS dt_emissao_min, NULL::date AS dt_emissao_max
  FROM tot t
UNION ALL
-- linhas 'subtotal': autorizado e vigente (o numero do comercial) contra o resto
SELECT 2, 'subtotal',
       CASE WHEN c.situacao = 'autorizado_vigente' THEN 'AUTORIZADO_VIGENTE'
            ELSE 'DEMAIS_SITUACOES' END,
       NULL, NULL,
       count(*), sum(c.vl_total),
       round(100.0 * count(*) / NULLIF((SELECT qt FROM tot), 0), 2),
       count(*) FILTER (WHERE c.dt_cancelamento IS NOT NULL),
       min(c.dt_emissao), max(c.dt_emissao)
  FROM cls c
 GROUP BY 3
UNION ALL
-- linhas 'situacao': quebra fina por situacao SEFAZ e codigo, com o texto do catalogo
SELECT 3, 'situacao', c.situacao, c.cd_status,
       left(coalesce(s.ds_status, '(sem registro em ctrc_cte)'), 140),
       count(*), sum(c.vl_total),
       round(100.0 * count(*) / NULLIF((SELECT qt FROM tot), 0), 2),
       count(*) FILTER (WHERE c.dt_cancelamento IS NOT NULL),
       min(c.dt_emissao), max(c.dt_emissao)
  FROM cls c
  LEFT JOIN status_cte s ON s.cd_status = c.cd_status
 GROUP BY c.situacao, c.cd_status, 5
 ORDER BY 1, 6 DESC
 LIMIT %(limite)s""",
        ["dias", "carencia_dias", "cd_pessoa_filial", "limite"], False,
        "CONTRAPROVA de faturamento.cte_sem_titulo: CT-es sem titulo quebrados pela situacao na SEFAZ - autorizado vigente contra cancelado/rejeitado/nao transmitido"),

    "contraprova.cte_pendente_faturado": (
        """\
-- contraprova.cte_pendente_faturado
-- CONTRAPROVA de fiscal.cte_pendente (agente fiscal).
-- O fiscal lista o documento sem autorizacao da SEFAZ como problema fiscal.
-- Aqui vem a pergunta do comercial: quantos desses JA FORAM FATURADOS?
-- Titulo a receber existe quando ctrc.cd_movimento nao e NULL (vinculo
-- ctrc.cd_movimento -> titulo.cd_movimento, id_tipo = 1). Documento nao
-- autorizado e com titulo gerado nao e pendencia de digitacao: e cobranca
-- emitida sem documento fiscal valido, problema mais grave e de outra natureza.
WITH base AS (
  SELECT c.cd_ctrc, c.nr_ctrc, btrim(c.ds_serie) AS ds_serie, c.id_modelo,
         c.dt_emissao, c.vl_total, c.cd_movimento, c.cd_pessoa_filial,
         c.cd_pessoa_pagador, c.dt_cancelamento, cc.cd_status,
         CASE
           WHEN c.id_modelo = '55'               THEN 'nao_e_cte_modelo_55'
           WHEN cc.cd_ctrc IS NULL               THEN 'nunca_transmitido'
           WHEN cc.cd_status IS NULL             THEN 'sem_retorno_sefaz'
           WHEN cc.cd_status = 100               THEN 'autorizado'
           WHEN cc.cd_status = 101               THEN 'cancelado'
           WHEN cc.cd_status = 102               THEN 'inutilizado'
           WHEN cc.cd_status IN (110, 301, 303)  THEN 'denegado'
           ELSE 'rejeitado'
         END AS situacao
    FROM ctrc c
    LEFT JOIN ctrc_cte cc ON cc.cd_ctrc = c.cd_ctrc
   WHERE c.dt_emissao >= CURRENT_DATE - %(dias)s
     AND (%(cd_pessoa_filial)s IS NULL OR c.cd_pessoa_filial = %(cd_pessoa_filial)s)
), pend AS (
  -- mesmo recorte da lista 'pendente' de fiscal.cte_pendente: sem autorizacao
  -- da SEFAZ e ainda nao cancelado no ERP
  SELECT b.*,
         CASE WHEN b.cd_movimento IS NOT NULL THEN 'com_titulo' ELSE 'sem_titulo' END AS classe
    FROM base b
   WHERE b.situacao IN ('nunca_transmitido', 'sem_retorno_sefaz', 'rejeitado',
                        'denegado', 'inutilizado')
     AND b.dt_cancelamento IS NULL
), tit AS (
  -- o titulo a receber de fato existente, somado por CT-e (pode ter parcelas)
  SELECT p.cd_ctrc,
         count(t.cd_titulo) AS qt_titulos,
         sum(t.vl_total) AS vl_titulo,
         sum(t.vl_total - COALESCE(t.vl_pago, 0)) AS vl_saldo_aberto,
         min(t.dt_vencimento) AS dt_vencimento,
         count(t.cd_titulo) FILTER (WHERE t.dt_quitacao IS NOT NULL) AS qt_quitados
    FROM pend p
    LEFT JOIN titulo t ON t.cd_movimento = p.cd_movimento AND t.id_tipo = 1
   WHERE p.classe = 'com_titulo'
   GROUP BY 1
)
-- linha 'resumo': o corte que o fiscal nao fez — com titulo contra sem titulo
SELECT 1 AS nr_ordem, 'resumo' AS linha, p.classe AS classe, NULL::text AS situacao,
       count(*) AS qt_ctes, sum(p.vl_total) AS vl_ctes,
       round(100.0 * count(*) / NULLIF((SELECT count(*) FROM pend), 0), 2) AS pr_qt,
       NULL::int AS cd_ctrc, NULL::bigint AS nr_ctrc, NULL::text AS ds_serie,
       NULL::date AS dt_emissao, NULL::numeric AS vl_total, NULL::int AS cd_status,
       NULL::text AS ds_status, NULL::text AS cliente, NULL::int AS cd_pessoa_filial,
       NULL::int AS cd_movimento, NULL::bigint AS qt_titulos, NULL::numeric AS vl_titulo,
       NULL::numeric AS vl_saldo_aberto, NULL::date AS dt_vencimento,
       NULL::bigint AS qt_titulos_quitados, NULL::int AS dias_parado
  FROM pend p
 GROUP BY p.classe
UNION ALL
-- linha 'resumo_situacao': dentro dos que TEM titulo, qual a situacao SEFAZ
SELECT 2, 'resumo_situacao', 'com_titulo', p.situacao,
       count(*), sum(p.vl_total),
       round(100.0 * count(*) / NULLIF((SELECT count(*) FROM pend), 0), 2),
       NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
       NULL, NULL, NULL, NULL
  FROM pend p
 WHERE p.classe = 'com_titulo'
 GROUP BY p.situacao
UNION ALL
-- linha 'detalhe': cada documento nao autorizado que JA tem titulo a receber
SELECT 3, 'detalhe', 'com_titulo', p.situacao,
       NULL, NULL, NULL,
       p.cd_ctrc, p.nr_ctrc, p.ds_serie, p.dt_emissao, p.vl_total, p.cd_status,
       left(coalesce(s.ds_status, '(sem retorno da SEFAZ)'), 140),
       coalesce(nullif(pe.nm_fantasia, ''), pe.nm_pessoa),
       p.cd_pessoa_filial, p.cd_movimento,
       tit.qt_titulos, tit.vl_titulo, tit.vl_saldo_aberto, tit.dt_vencimento,
       tit.qt_quitados, (CURRENT_DATE - p.dt_emissao)
  FROM pend p
  JOIN tit ON tit.cd_ctrc = p.cd_ctrc
  LEFT JOIN status_cte s ON s.cd_status = p.cd_status
  LEFT JOIN pessoa pe    ON pe.cd_pessoa = p.cd_pessoa_pagador
 WHERE p.classe = 'com_titulo'
 ORDER BY 1, 5 DESC NULLS LAST, 12 DESC NULLS LAST
 LIMIT %(limite)s""",
        ["dias", "cd_pessoa_filial", "limite"], False,
        "CONTRAPROVA de fiscal.cte_pendente: quantos documentos sem autorizacao da SEFAZ ja tem titulo a receber gerado"),

    "contraprova.duplicidade_documento": (
        """\
-- contraprova.duplicidade_documento
-- CONTRAPROVA de pagar.duplicidade_suspeita (agente financeiro).
-- A consulta original agrupa por fornecedor + valor + vencimento proximo, e por
-- isso nao distingue "a mesma nota lancada duas vezes" de "duas compras iguais".
-- Introspeccao feita antes de escrever: titulo e movimento NAO tem nr_documento,
-- nr_nota nem nr_nf (movimento so tem cd_movimento/qt_parcela; nota_fiscal tem
-- nr_nota_fiscal mas cd_movimento nunca casa com titulo a pagar - zero linhas em
-- 18.267 titulos testados). O numero do documento do titulo a pagar esta em
-- caixa.nr_documento, ligado por caixa.cd_movimento = titulo.cd_movimento
-- (cobertura de cerca de 47 por cento dos titulos). O sufixo de parcela
-- ('1944344/1') e cortado
-- para nao inventar documento distinto onde ha so parcela.
-- Prova pratica: SUECIA 2 x R$ 998.000,00 sao documentos 216783 e 216785 -
-- dois caminhoes, nao um pagamento em dobro.
WITH base AS (
  SELECT t.cd_titulo, t.cd_pessoa, round(t.vl_total, 2) AS vl,
         t.dt_vencimento, t.dt_quitacao, t.cd_movimento,
         m.qt_parcela, m.cd_pessoa_filial,
         -- documento fiscal do lancamento, sem o sufixo de parcela
         (SELECT string_agg(DISTINCT split_part(btrim(k.nr_documento), '/', 1), ',')
            FROM caixa k
           WHERE k.cd_movimento = t.cd_movimento
             AND nullif(btrim(k.nr_documento), '') IS NOT NULL) AS nr_documento
    FROM titulo t
    JOIN movimento m ON m.cd_movimento = t.cd_movimento
   WHERE t.id_tipo = 2
     AND t.vl_total >= %(vl_min)s
     AND t.dt_vencimento >= CURRENT_DATE - %(dias_retro)s
     AND COALESCE(m.qt_parcela, 1) <= %(max_parcelas)s
     AND (%(cd_pessoa_filial)s IS NULL OR m.cd_pessoa_filial = %(cd_pessoa_filial)s)
), grp AS (
  -- mesmo agrupamento da consulta original: fornecedor + valor + janela de :dias
  SELECT b.cd_pessoa, b.vl,
         count(*) AS qt_titulos,
         count(DISTINCT b.cd_movimento) AS qt_movimentos,
         count(b.nr_documento) AS qt_titulos_com_documento,
         count(DISTINCT b.nr_documento) AS qt_documentos,
         min(b.dt_vencimento) AS venc_ini,
         max(b.dt_vencimento) AS venc_fim,
         count(*) FILTER (WHERE b.dt_quitacao IS NOT NULL) AS qt_pagos,
         max(COALESCE(b.qt_parcela, 1)) AS qt_parcela_max,
         array_agg(b.cd_titulo ORDER BY b.dt_vencimento) AS ar_cd_titulo,
         array_agg(DISTINCT b.cd_movimento) AS ar_cd_movimento,
         array_agg(DISTINCT b.nr_documento) FILTER (WHERE b.nr_documento IS NOT NULL) AS ar_documento
    FROM base b
   GROUP BY 1, 2
  HAVING count(*) > 1
     AND max(b.dt_vencimento) - min(b.dt_vencimento) <= %(dias)s
), cls AS (
  -- Classificacao: e a MESMA compra lancada duas vezes, ou sao compras
  -- diferentes? Um unico cd_movimento com dois titulos iguais nao e duplicidade:
  -- e o mesmo lancamento parcelado (qt_parcela > 1) com parcelas de igual valor
  -- e vencimentos vizinhos. Duplicidade forte exige lancamentos DIFERENTES
  -- apontando para o MESMO numero de documento.
  SELECT g.*,
         CASE
           WHEN g.qt_movimentos = 1                      THEN 'mesmo_movimento_parcelado'
           WHEN g.qt_titulos_com_documento < g.qt_titulos THEN 'documento_desconhecido'
           WHEN g.qt_documentos = 1                       THEN 'mesmo_documento'
           ELSE 'documentos_distintos'
         END AS classificacao
    FROM grp g
)
-- linha 'total': quantos grupos e quanta exposicao em cada classificacao
SELECT 1 AS nr_ordem, 'total' AS linha, c.classificacao,
       count(*) AS qt_grupos,
       sum(c.qt_titulos) AS qt_titulos,
       sum(round(c.vl * (c.qt_titulos - 1), 2)) AS vl_exposicao,
       round(100.0 * count(*) / NULLIF((SELECT count(*) FROM cls), 0), 2) AS pr_grupos,
       NULL::int AS cd_pessoa, NULL::text AS fornecedor, NULL::text AS nr_cnpj_cpf,
       NULL::numeric AS vl_titulo, NULL::bigint AS qt_movimentos,
       NULL::bigint AS qt_documentos, NULL::bigint AS qt_titulos_com_documento,
       NULL::bigint AS qt_pagos, NULL::int AS qt_parcela_max,
       NULL::date AS venc_ini, NULL::date AS venc_fim,
       NULL::int[] AS ar_cd_titulo, NULL::int[] AS ar_cd_movimento,
       NULL::text[] AS ar_documento
  FROM cls c
 GROUP BY c.classificacao
UNION ALL
-- linha 'grupo': cada grupo suspeito com o veredito documento a documento
SELECT 2, 'grupo', c.classificacao,
       1, c.qt_titulos, round(c.vl * (c.qt_titulos - 1), 2), NULL,
       c.cd_pessoa,
       coalesce(nullif(p.nm_fantasia, ''), p.nm_pessoa),
       p.nr_cnpj_cpf,
       c.vl, c.qt_movimentos, c.qt_documentos, c.qt_titulos_com_documento,
       c.qt_pagos, c.qt_parcela_max, c.venc_ini, c.venc_fim,
       c.ar_cd_titulo, c.ar_cd_movimento, c.ar_documento
  FROM cls c
  LEFT JOIN pessoa p ON p.cd_pessoa = c.cd_pessoa
 ORDER BY 1, 6 DESC
 LIMIT %(limite)s""",
        ["dias", "dias_retro", "vl_min", "max_parcelas", "cd_pessoa_filial", "limite"], False,
        "CONTRAPROVA de pagar.duplicidade_suspeita: os titulos do grupo vem do mesmo documento fiscal ou de documentos distintos"),

    "contraprova.margem_frota_propria": (
        """\
-- contraprova.margem_frota_propria
-- CONTRAPROVA de controladoria.margem_por_cte (agente de controladoria).
-- A controladoria calcula custo = carta_frete.vl_frete. Isso vale para terceiro
-- e agregado, mas NAO para frota propria: nesses CT-es a carta frete e emitida
-- contra a propria Pianetto (id_proprietario_veiculo = 1 => transportadora = 2),
-- ou seja e TRANSFERENCIA INTERNA, nao saida de caixa. Tratar isso como custo
-- ja produziu -R$ 2,58 milhoes de prejuizo inexistente. O custo real de frota
-- propria vive em caixa_veiculo -> caixa.
-- Reproduz exatamente o recorte 'pior_caso' da original (margem negativa ou
-- abaixo de :pr_margem_min) e quebra por tipo de proprietario do veiculo.
WITH ct AS (
  SELECT c.cd_ctrc, c.nr_ctrc, btrim(c.ds_serie) AS ds_serie, c.dt_emissao,
         c.vl_total, c.cd_pessoa_filial, c.cd_pessoa_pagador, c.cd_veiculo,
         c.id_proprietario_veiculo,
         (SELECT sum(cf.vl_frete) FROM carta_frete cf WHERE cf.cd_ctrc = c.cd_ctrc) AS vl_custo
    FROM ctrc c
   WHERE c.dt_cancelamento IS NULL
     AND c.dt_emissao >= CURRENT_DATE - %(dias)s
     AND (%(cd_pessoa_filial)s IS NULL OR c.cd_pessoa_filial = %(cd_pessoa_filial)s)
), cls AS (
  -- mesma classificacao da original: sem carta frete fica fora da margem
  SELECT ct.*,
         CASE WHEN ct.vl_custo IS NULL THEN 'sem_carta_frete' ELSE 'com_custo' END AS classe,
         (ct.vl_total - COALESCE(ct.vl_custo, 0)) AS vl_margem,
         CASE ct.id_proprietario_veiculo
           WHEN 1 THEN 'frota_propria'
           WHEN 2 THEN 'agregado'
           WHEN 3 THEN 'terceiro'
           ELSE 'nao_informado'
         END AS tipo_proprietario
    FROM ct
), ruim AS (
  -- exatamente as linhas 'pior_caso' da consulta original
  SELECT * FROM cls
   WHERE classe = 'com_custo'
     AND (vl_margem < 0 OR 100.0 * vl_margem / NULLIF(vl_total, 0) < %(pr_margem_min)s)
), tot AS (
  SELECT count(*) AS qt, sum(vl_total) AS vl_receita, sum(vl_custo) AS vl_custo,
         sum(vl_margem) AS vl_margem
    FROM ruim
)
-- linha 'total': o bloco inteiro de CT-es abaixo do minimo, como a original ve
SELECT 1 AS nr_ordem, 'total' AS linha, 'TODOS' AS tipo_proprietario,
       NULL::smallint AS id_proprietario_veiculo,
       t.qt AS qt_ctes, t.vl_receita, t.vl_custo, t.vl_margem,
       round(100.0 * t.vl_margem / NULLIF(t.vl_receita, 0), 2) AS pr_margem,
       100.00::numeric AS pr_qt,
       NULL::bigint AS qt_margem_negativa, NULL::numeric AS vl_margem_negativa,
       NULL::bigint AS qt_veiculos, NULL::numeric AS vl_custo_caixa_veiculo
  FROM tot t
UNION ALL
-- linhas 'quebra': por tipo de proprietario. Em 'frota_propria' o vl_custo e
-- carta frete interna e a margem negativa e artefato: o custo comparavel esta
-- em vl_custo_caixa_veiculo (caixa_veiculo -> caixa, mesma janela).
SELECT 2, 'quebra', r.tipo_proprietario, r.id_proprietario_veiculo,
       count(*), sum(r.vl_total), sum(r.vl_custo), sum(r.vl_margem),
       round(100.0 * sum(r.vl_margem) / NULLIF(sum(r.vl_total), 0), 2),
       round(100.0 * count(*) / NULLIF((SELECT qt FROM tot), 0), 2),
       count(*) FILTER (WHERE r.vl_margem < 0),
       sum(r.vl_margem) FILTER (WHERE r.vl_margem < 0),
       count(DISTINCT r.cd_veiculo),
       (SELECT COALESCE(sum(k.vl_lancamento), 0)
          FROM caixa_veiculo cv
          JOIN caixa k ON k.cd_caixa = cv.cd_caixa
         WHERE cv.cd_veiculo IN (SELECT r2.cd_veiculo FROM ruim r2
                                  WHERE r2.id_proprietario_veiculo = r.id_proprietario_veiculo
                                    AND r2.cd_veiculo IS NOT NULL)
           AND k.dt_documento BETWEEN CURRENT_DATE - %(dias)s AND CURRENT_DATE)
  FROM ruim r
 GROUP BY r.tipo_proprietario, r.id_proprietario_veiculo
 ORDER BY 1, 5 DESC
 LIMIT %(limite)s""",
        ["dias", "pr_margem_min", "cd_pessoa_filial", "limite"], False,
        "CONTRAPROVA de controladoria.margem_por_cte: quanto da margem negativa e frota propria, onde a carta frete e transferencia interna"),
}


# Padrões por consulta. Um parâmetro com padrão deixa de ser obrigatório: quem
# chama diz só o que quer mudar. `cd_pessoa_filial=None` significa "todas as
# filiais" — sem esta tabela o None era lido como parâmetro esquecido e a
# consulta era recusada antes de sair do lugar.
PADROES: dict[str, dict] = {
    "pagar.duplicidade_suspeita": {"dias": 5, "dias_retro": 365, "vl_min": 100,
                                   "max_parcelas": 3, "cd_pessoa_filial": None,
                                   "limite": 200},
    "faturamento.cte_sem_titulo": {"dias": 30, "carencia_dias": 0,
                                   "cd_pessoa_filial": None, "limite": 200},
    "comercial.cliente_que_sumiu": {"dias_base": 180, "dias_recente": 60,
                                    "meses_min": 3, "vl_mensal_min": 5000,
                                    "pr_queda_min": 60, "cd_pessoa_filial": None,
                                    "limite": 100},
    "controladoria.margem_por_cte": {"dias": 30, "pr_margem_min": 5,
                                     "cd_pessoa_filial": None, "limite": 100},
    "frota.resultado_veiculo": {"dias": 90, "cd_pessoa_filial": None,
                                "limite": 100},
    "frota.abastecimento_veiculo": {"dias": 90, "limite": 200},
    "fiscal.cte_pendente": {"dias": 90, "cd_pessoa_filial": None, "limite": 200},
    "lucratividade.por_setor": {"dias": 90, "cd_pessoa_filial": None},
    "lucratividade.por_agencia": {"dias": 90, "cd_pessoa_filial": None,
                                  "limite": 60},
    "contraprova.lucratividade_custo_frota": {"dias": 90},
    "contraprova.km_por_hodometro": {"dias": 90, "limite": 300},
    # contraprovas: mesmos padroes das consultas que elas contestam, para que a
    # comparacao seja de fato sobre o mesmo universo.
    "contraprova.cte_sem_titulo_situacao": {"dias": 30, "carencia_dias": 0,
                                            "cd_pessoa_filial": None,
                                            "limite": 200},
    "contraprova.cte_pendente_faturado": {"dias": 90, "cd_pessoa_filial": None,
                                          "limite": 200},
    "contraprova.duplicidade_documento": {"dias": 5, "dias_retro": 365,
                                          "vl_min": 100, "max_parcelas": 3,
                                          "cd_pessoa_filial": None,
                                          "limite": 200},
    "contraprova.margem_frota_propria": {"dias": 30, "pr_margem_min": 5,
                                         "cd_pessoa_filial": None,
                                         "limite": 100},
}


def _executar(operacao: str, empresa_id: int, **kw) -> Resultado:
    if operacao not in CONSULTAS:
        return Resultado(False, erro=f"consulta '{operacao}' não está no catálogo")
    sql, obrig, pesada, _desc = CONSULTAS[operacao]

    kw = {**PADROES.get(operacao, {}), **{k: v for k, v in kw.items()
                                          if v is not None}}
    padrao = PADROES.get(operacao, {})
    faltando = [p for p in obrig if p not in padrao and kw.get(p) is None]
    if faltando:
        return Resultado(False, erro=f"parâmetros ausentes: {', '.join(faltando)}")

    if pesada and JANELA_PROIBIDA[0] <= datetime.now(bd.FUSO).hour < JANELA_PROIBIDA[1]:
        return Resultado(
            False,
            erro="consulta pesada bloqueada na janela de faturamento (8h–11h)")

    params = {p: kw.get(p) for p in obrig}
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
