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
 LIMIT %(limite)s
