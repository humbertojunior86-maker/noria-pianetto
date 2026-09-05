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
), cx AS (
  SELECT cv.cd_veiculo,
         sum(k.vl_lancamento) AS vl_caixa_total,
         sum(k.vl_lancamento) FILTER (WHERE upper(coalesce(h.ds_historico,'')) LIKE '%%COMBUST%%') AS vl_combustivel,
         sum(k.vl_lancamento) FILTER (WHERE upper(coalesce(h.ds_historico,'')) ~ 'MANUT|PECA|PE.A|PNEU|ESTOFARIA') AS vl_manutencao,
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
       COALESCE(cx.qt_lancamentos, 0) AS qt_lancamentos_caixa
  FROM frota f
  LEFT JOIN rec r ON r.cd_veiculo = f.cd_veiculo
  LEFT JOIN cx    ON cx.cd_veiculo = f.cd_veiculo
 WHERE COALESCE(r.qt_ctes, 0) > 0 OR COALESCE(cx.qt_lancamentos, 0) > 0
 ORDER BY (COALESCE(r.vl_receita, 0) - COALESCE(cx.vl_caixa_total, 0)) ASC
 LIMIT %(limite)s""",
        ["dias", "cd_pessoa_filial", "limite"], False,
        "receita e custo identificavel por placa da frota propria no periodo"),

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
    "fiscal.cte_pendente": {"dias": 90, "cd_pessoa_filial": None, "limite": 200},
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
