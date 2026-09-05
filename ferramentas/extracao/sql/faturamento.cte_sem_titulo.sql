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
 LIMIT %(limite)s
