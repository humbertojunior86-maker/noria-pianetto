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
 LIMIT %(limite)s
