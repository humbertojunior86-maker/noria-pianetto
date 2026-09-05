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
 LIMIT %(limite)s
