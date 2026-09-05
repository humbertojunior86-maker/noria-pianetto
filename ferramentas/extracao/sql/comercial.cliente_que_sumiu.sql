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
 LIMIT %(limite)s
