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
 LIMIT %(limite)s
