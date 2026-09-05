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
 LIMIT %(limite)s
