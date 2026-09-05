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
 LIMIT %(limite)s
