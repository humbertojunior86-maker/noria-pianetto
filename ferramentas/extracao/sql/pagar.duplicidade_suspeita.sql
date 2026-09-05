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
 LIMIT %(limite)s
