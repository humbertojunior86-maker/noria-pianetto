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
 LIMIT %(limite)s
