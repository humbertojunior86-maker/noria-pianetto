# CONSULTAS-NOVAS — 6 consultas validadas no ATUA

**Data:** 2026-09-05 · **`current_date` do servidor:** 2026-09-05
**Banco:** PostgreSQL 15.14, schema `public`, usuário somente leitura `jhn_ro` via pgbouncer
**Formato:** cada bloco está pronto para colar no dicionário `CONSULTAS` de `ferramentas/atua.py`
`{nome: (sql, params_obrigatorios, pesada?, descricao)}`
**Arquivos soltos:** `ferramentas/extracao/sql/<nome>.sql` · execução crua em `sql/_resultado_execucao.json`

Todas as seis rodaram de verdade. Nenhuma passou de **2 segundos**. Nenhuma é `pesada`.

## Descobertas de modelagem novas (feitas aqui, valem para o resto do projeto)

| Questão | Verificação | Conclusão |
| --- | --- | --- |
| Como CT-e vira título a receber? | 3.950 CT-es em 30d: 3.148 com `cd_movimento` preenchido, e **100% desses** têm `titulo` com `cd_movimento` igual e `id_tipo=1`. Zero casos de `cd_movimento` preenchido sem título. | Vínculo é `ctrc.cd_movimento = titulo.cd_movimento`. **`ctrc.cd_movimento IS NULL` ⇒ não existe título** |
| Onde está a situação SEFAZ do CT-e? | `ctrc_cte.cd_status` (código SEFAZ) → `status_cte.ds_status` (73 códigos catalogados). `ctrc_status_cte` é o histórico de eventos. | `100`=autorizado, `101`=cancelado homologado, `102`=inutilizado, `110/301/303`=denegado, resto = rejeição |
| Todo documento em `ctrc` é CT-e? | 67 documentos de 30d com `id_modelo='55'` (NF-e) não têm linha em `ctrc_cte`. | **Filtrar `id_modelo='55'` antes de acusar “sem transmissão”** |
| Como separar frota própria de terceiro? | `ctrc.id_proprietario_veiculo`: 90d → `3`=terceiro (11.561), `1`=frota própria (384), `2`=agregado (71). Nos 384 de `id=1` a `cd_pessoa_transportadora` é **sempre 2 (a própria Pianetto)**. | `id_proprietario_veiculo = 1` é o flag confiável de frota própria |
| `carta_frete` serve de custo para frota própria? | Nos CT-es `id_proprietario_veiculo=1` (90d) há R$ 3.557.061,94 de carta frete — emitida contra a própria Pianetto. | **Não.** É transferência interna. Custo de frota própria = `caixa_veiculo` → `caixa` |
| Custo real por placa | `caixa_veiculo` (20.173 linhas) → `caixa.vl_lancamento`, classificado por `historico_caixa.ds_historico` (COMBUSTIVEL, MANUTENCAO, PECAS, PNEU, PEDAGIO, SALARIO). 90d = R$ 3.444.516,90 em 107 veículos. | Fonte de custo de frota |
| Maior falso positivo de duplicidade a pagar | Financiamento de frota: BANCO PACCAR, 6 títulos de R$ 22.137,49 no mesmo dia = 6 caminhões, `movimento.qt_parcela = 58`. | Filtrar por `movimento.qt_parcela <= 3` mata a classe inteira |
| `titulo.cd_lote_titulo` / `nr_titulo` servem para agrupar? | 26.256 títulos a pagar em 365d: apenas **23** com `cd_lote_titulo` e **104** com `nr_titulo`. | Campos abandonados. Não usar |
| `titulo_debito.nr_codigo_barras` como prova dura de duplicidade? | Preenchido em 1.553 de 26.256 (5,9%). Em 730d gera só 6 grupos duplicados / R$ 4.012,82. | Sinal certeiro mas de cobertura baixa demais para ser a regra principal |

---

## 1. `pagar.duplicidade_suspeita`

**O que faz.** Junta títulos **a pagar** (`id_tipo = 2`) do mesmo fornecedor, com **o mesmo valor**, cujos vencimentos caem dentro de uma janela de `:dias`. Exclui parcelamentos longos (`movimento.qt_parcela <= :max_parcelas`), que é a classe que produzia quase toda a sujeira.

### SQL — pronto para colar em `CONSULTAS`

```python
    "pagar.duplicidade_suspeita": (
        """\
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
 LIMIT %(limite)s""",
        ["dias", "dias_retro", "vl_min", "max_parcelas", "cd_pessoa_filial", "limite"], False,
        "titulos a pagar do mesmo fornecedor, mesmo valor e vencimento a menos de N dias - possivel pagamento em duplicidade"),
```

<details><summary>SQL puro (também em <code>sql/pagar.duplicidade_suspeita.sql</code>)</summary>

```sql
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
```

</details>

### Parâmetros

| Parâmetro | Padrão | O que é |
| --- | --- | --- |
| `dias` | `5` | janela máxima entre o primeiro e o último vencimento do grupo |
| `dias_retro` | `365` | quanto tempo para trás olhar (por `dt_vencimento`) |
| `vl_min` | `100` | valor mínimo do título; abaixo disso é ruído de tarifa |
| `max_parcelas` | `3` | descarta títulos cujo `movimento.qt_parcela` é maior — financiamento de frota |
| `cd_pessoa_filial` | `None` | filial (via `movimento.cd_pessoa_filial`); `NULL` = todas |
| `limite` | `200` | grupos devolvidos |

### Colunas devolvidas

| Coluna | Tipo | Significado |
| --- | --- | --- |
| `cd_pessoa` | int | código do fornecedor |
| `fornecedor` | text | fantasia, ou razão social se não houver |
| `nr_cnpj_cpf` | text | documento do fornecedor |
| `vl_titulo` | numeric | valor unitário repetido |
| `qt_titulos` | int | quantos títulos idênticos no grupo |
| `vl_exposicao` | numeric | `vl_titulo × (qt_titulos − 1)` — o valor potencialmente pago a mais |
| `qt_pagos` | int | quantos do grupo já foram quitados |
| `vl_ja_pago` | numeric | soma do que já saiu do caixa |
| `venc_ini` / `venc_fim` | date | primeiro e último vencimento do grupo |
| `dias_entre` | int | distância em dias entre eles |
| `confianca` | text | `alta` = mesmo dia **e** todos já pagos; `media` = mesmo dia; `baixa` = dias diferentes |
| `ar_cd_titulo` | int[] | os títulos, para o financeiro abrir um a um |
| `ar_nr_titulo` | bigint[] | número do documento (quase sempre nulo neste ERP) |
| `ar_vencimento` / `ar_quitacao` | date[] | datas alinhadas com `ar_cd_titulo` |
| `ar_filial` | int[] | filiais envolvidas |

### Resultado real da execução

Rodada com os padrões, 2026-09-05, **1,52 s**, 200 grupos devolvidos (limite). Agregado completo sem limite:

- **399 grupos**, 895 títulos, **R$ 3.956.072,61 de exposição** nos últimos 365 dias.
- **281 grupos com `confianca = 'alta'`** (mesmo vencimento e todos já quitados): **R$ 3.559.837,50 já saíram do caixa**.
- Os cinco maiores: SUÉCIA VEÍCULOS R$ 998.000,00 ×2 (venc. 23/03/2026, ambos quitados no mesmo dia); VARELLA VEÍCULOS PESADOS R$ 845.000,00 ×2 (26/11/2025); MEGATEC R$ 185.000,00 ×2 (16/12/2025); LIBRELATO R$ 149.507,00 ×2 e R$ 128.860,00 ×2 (ambos 23/03/2026).
- Cauda repetitiva relevante: **AXA SEGUROS**, dezenas de pares idênticos (R$ 31.855,82; R$ 30.542,75; R$ 27.025,87; R$ 23.773,17…), todos com vencimento no mesmo dia e todos quitados.

### Ressalvas — o que esta consulta NÃO prova

- **Não prova duplicidade. Prova coincidência.** Dois caminhões iguais comprados no mesmo dia do mesmo revendedor produzem exatamente esta assinatura — e os casos SUÉCIA/VARELLA/LIBRELATO têm essa cara. O que a consulta entrega é uma fila de conferência ordenada por dinheiro, não uma acusação.
- **Seguro por veículo é falso positivo estrutural.** A AXA emite uma apólice por placa; frota homogênea gera prêmios idênticos. É a maior fonte de linhas na cauda.
- **`vl_min = 100` corta duplicidades pequenas de alto volume** (tarifa bancária, pedágio avulso). Baixar o parâmetro aumenta muito o número de linhas.
- **Agrupa por valor exato arredondado a 2 casas.** Duplicidade com centavos de diferença (juro, desconto) escapa.
- **`max_parcelas = 3` pode esconder duplicidade real** em compra parcelada em 4× ou mais. É um trade-off consciente: sem ele, 33 dos 432 grupos eram financiamento de frota puro.
- **Não olha o extrato bancário.** Dois títulos quitados não são prova de duas saídas de caixa; a confirmação é cruzar com `caixa_financeiro_lancamento` / `ar_cd_conciliado`.

---

## 2. `faturamento.cte_sem_titulo`

**O que faz.** CT-e **autorizado pela SEFAZ** (`ctrc_cte.cd_status = 100`), não cancelado, emitido na janela, que **não gerou título a receber**. O teste é `ctrc.cd_movimento IS NULL` — validado como equivalente a “não existe título” (ver tabela de descobertas). Há uma carência para não acusar o faturamento do próprio dia.

### SQL — pronto para colar em `CONSULTAS`

```python
    "faturamento.cte_sem_titulo": (
        """\
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
 LIMIT %(limite)s""",
        ["dias", "carencia_dias", "cd_pessoa_filial", "limite"], False,
        "CT-es autorizados na SEFAZ nos ultimos N dias que nao geraram titulo a receber"),
```

<details><summary>SQL puro (também em <code>sql/faturamento.cte_sem_titulo.sql</code>)</summary>

```sql
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
```

</details>

### Parâmetros

| Parâmetro | Padrão | O que é |
| --- | --- | --- |
| `dias` | `30` | quanto olhar para trás a partir de hoje |
| `carencia_dias` | `7` | ignora CT-es emitidos nos últimos N dias (lote de faturamento ainda rodando) |
| `cd_pessoa_filial` | `None` | filial emissora; `NULL` = todas |
| `limite` | `500` | linhas devolvidas |

### Colunas devolvidas

| Coluna | Tipo | Significado |
| --- | --- | --- |
| `cd_ctrc` | int | chave interna do CT-e |
| `nr_ctrc` | bigint | número do CT-e |
| `ds_serie` | text | série |
| `dt_emissao` | date | emissão |
| `vl_total` | numeric | valor do frete que ninguém cobrou |
| `cd_pessoa_pagador` / `cliente` / `nr_cnpj_cpf` | int/text/text | quem deveria ter sido faturado |
| `cd_pessoa_filial` / `filial` | int/text | filial emissora |
| `dias_sem_faturar` | int | idade do CT-e |
| `id_frete` | smallint | modalidade de frete (0/1/3 no uso real) |
| `id_tipo_ctrc` | smallint | tipo do CT-e (0 normal, 1, 3) |
| `id_proprietario_veiculo` | smallint | 1 própria, 2 agregado, 3 terceiro |
| `nr_chave` | text | chave de acesso, para conferir na SEFAZ |
| `qt_total` / `vl_total_geral` | bigint/numeric | totais da janela inteira, repetidos em toda linha (`OVER ()`) |

### Resultado real da execução

Rodada com os padrões, **1,30 s**:

- **355 CT-es autorizados, R$ 1.628.337,90** emitidos entre 06/08 e 29/08/2026 sem nenhum título a receber.
- Maiores: AMAGGI R$ 24.500,00 (CT-e 7375, 28/08, filial SP) e R$ 21.100,00 (7351, 26/08); IHARABRAS R$ 18.828,56 ×2 (7352 e 7362); JALLES MACHADO R$ 17.996,80 (36577, 13/08, matriz); RIO BRANCO ALIMENTOS R$ 15.165,80.
- Com `dias=365, carencia_dias=60` (só o que já passou de qualquer prazo razoável de faturamento): **136 CT-es, R$ 687.387,57 parados**. O backlog decai mês a mês (65 CT-es no 3º mês, 20 no 4º, 4 no 7º), o que confirma que o processo eventualmente fatura — e que esses 136 ficaram para trás.

### Ressalvas — o que esta consulta NÃO prova

- **Nem todo CT-e sem título é frete não cobrado.** Alguns CT-es de subcontratação, redespacho ou complemento podem ser faturados por fora ou nem gerar cobrança própria. `id_frete` e `id_tipo_ctrc` vão na saída exatamente para o analista separar — não filtrei por eles porque **as três modalidades aparecem tanto no grupo faturado quanto no não faturado**, então não existe regra limpa de exclusão.
- **A carência de 7 dias é arbitrária.** Com carência 0 a lista sobe para 802 CT-es porque inclui o faturamento em curso. Se a Pianetto fatura quinzenal, o parâmetro deveria subir para 15.
- **Não prova que o cliente não pagou.** Prova que o ERP não tem título. Cobrança por fora do sistema não aparece aqui.
- Só cobre CT-e com `cd_status = 100`. CT-e não transmitido é problema da consulta 6, de propósito.

---

## 3. `comercial.cliente_que_sumiu`

**O que faz.** Compara a média mensal de receita do cliente na janela base (`:dias_base` dias anteriores) com a média mensal na janela recente (`:dias_recente`). Só considera cliente que tinha **regularidade** — presença em pelo menos `:meses_min` meses distintos e faturamento médio acima de `:vl_mensal_min`.

### SQL — pronto para colar em `CONSULTAS`

```python
    "comercial.cliente_que_sumiu": (
        """\
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
 LIMIT %(limite)s""",
        ["dias_base", "dias_recente", "meses_min", "vl_mensal_min", "pr_queda_min", "cd_pessoa_filial", "limite"], False,
        "clientes regulares na janela base que pararam ou cairam mais de N% na janela recente"),
```

<details><summary>SQL puro (também em <code>sql/comercial.cliente_que_sumiu.sql</code>)</summary>

```sql
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
```

</details>

### Parâmetros

| Parâmetro | Padrão | O que é |
| --- | --- | --- |
| `dias_base` | `180` | janela de referência (6 meses anteriores) |
| `dias_recente` | `60` | janela recente comparada |
| `meses_min` | `4` | meses distintos com CT-e na base; filtro de regularidade |
| `vl_mensal_min` | `2000` | receita média mensal mínima na base |
| `pr_queda_min` | `60` | queda percentual mínima para entrar na lista |
| `cd_pessoa_filial` | `None` | filial; `NULL` = todas |
| `limite` | `200` | linhas |

### Colunas devolvidas

| Coluna | Tipo | Significado |
| --- | --- | --- |
| `cd_pessoa_pagador` / `cliente` / `nr_cnpj_cpf` | int/text/text | o cliente |
| `meses_ativos` | int | meses distintos com CT-e na janela base |
| `qt_base` / `vl_base` | bigint/numeric | CT-es e receita na janela base |
| `vl_media_mensal_anterior` | numeric | receita média mensal antes |
| `qt_recente` / `vl_recente` | bigint/numeric | CT-es e receita na janela recente |
| `vl_media_mensal_recente` | numeric | receita média mensal agora |
| `pr_queda` | numeric | queda em %, `100` = parou de vez |
| `vl_perda_mensal` | numeric | R$/mês que deixaram de entrar — coluna de ordenação |
| `dt_ultimo_cte` | date | último CT-e emitido (dentro da janela de 240 dias) |
| `dias_sem_cte` | int | dias desde o último CT-e |
| `situacao` | text | `parou` (zero CT-e na janela recente) ou `caiu` |
| `cd_pessoa_filial` | int | última filial que atendeu |

### Resultado real da execução

Rodada com os padrões, **1,84 s**, 30 clientes:

- **Perda combinada de R$ 5.804.743,74/mês** — mas **R$ 3.495.302,99 são um cliente só**: MOTZ TRANSPORTES GO, que caiu de R$ 5,37 M/mês para R$ 1,88 M/mês (−65%) e **continua emitindo hoje**. Sem a MOTZ, a lista soma **R$ 2.309.440,75/mês**.
- **17 clientes com `situacao = 'parou'`** (zero CT-e em 60 dias), somando **R$ 1.204.823,05/mês** que evaporaram. Os maiores: FUTURO CEREAIS R$ 165.947,28/mês (último CT-e 12/05, 116 dias); SLC AGRÍCOLA R$ 131.490,65/mês (07/05, 121 dias); VETORIAL SIDERURGIA R$ 129.306,73/mês (10/04, **148 dias**); CHS AGRONEGÓCIO R$ 128.214,85/mês (02/06, 95 dias).
- Quedas severas ainda vivas: COFCO −83,18% (R$ 256 k → R$ 43 k/mês) e NOVAAGRI −78,33% (R$ 221 k → R$ 48 k/mês).

### Ressalvas — o que esta consulta NÃO prova

- **“Sumiu” é errado para os `caiu`.** MOTZ emitiu CT-e hoje. A consulta detecta *queda*, não abandono; use a coluna `situacao` para separar as duas leituras antes de mandar alguém ligar.
- **Sazonalidade agrícola vira falso positivo em massa.** A carteira da Pianetto é agro (AMAGGI, SLC, CHS, COFCO, fertilizantes). Comparar a entressafra contra a safra acusa o setor inteiro. Uma versão honesta compararia com o mesmo período do ano anterior — o banco tem histórico desde 26/08/2024, ou seja, **cabe exatamente um ano de comparação, sem folga**.
- **Agrupa por `cd_pessoa_pagador`, não por grupo econômico.** Cliente que trocou o CNPJ pagador de filial aparece como perdido e ganho ao mesmo tempo. Para consolidar, aplicar a raiz de 8 dígitos do CNPJ como em `ceo.concentracao`.
- **`dt_ultimo_cte` é limitada pela janela** de `dias_base + dias_recente` (240 dias). Cliente parado há mais tempo que isso nem entra na lista, porque não tem base de comparação.
- **Não olha título nem inadimplência.** Cliente pode ter sido bloqueado por débito de propósito — isso é decisão, não perda.

---

## 4. `controladoria.margem_por_cte`

**O que faz.** Receita (`ctrc.vl_total`) contra custo real de frete (`carta_frete.vl_frete`, somado por CT-e), num período de `:dias`. Devolve uma linha `total` com o agregado e linhas `pior_caso` com os CT-es de margem negativa ou abaixo de `:pr_margem_min`.

**Regra dura do enunciado, implementada:** CT-e **sem** carta frete (`vl_custo IS NULL`) fica **fora** do cálculo de margem e é contado em `qt_sem_carta_frete`. CT-e **com** carta frete de valor zero é `custo zero` e entra na margem, contado à parte em `qt_custo_zero`. Os dois nunca se misturam.

### SQL — pronto para colar em `CONSULTAS`

```python
    "controladoria.margem_por_cte": (
        """\
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
 LIMIT %(limite)s""",
        ["dias", "pr_margem_min", "cd_pessoa_filial", "limite"], False,
        "receita do CT-e contra custo real de carta frete no periodo, agregado e piores casos"),
```

<details><summary>SQL puro (também em <code>sql/controladoria.margem_por_cte.sql</code>)</summary>

```sql
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
```

</details>

### Parâmetros

| Parâmetro | Padrão | O que é |
| --- | --- | --- |
| `dias` | `30` | janela por `dt_emissao` |
| `pr_margem_min` | `5` | abaixo desta margem % o CT-e vira `pior_caso` |
| `cd_pessoa_filial` | `None` | filial; `NULL` = todas |
| `limite` | `300` | linhas (a linha `total` ocupa uma) |

### Colunas devolvidas

Duas formas de linha, distinguidas por `linha`.

**`linha = 'total'`** (uma linha): `qt_ctes` (int, CT-es com custo conhecido), `vl_receita`, `vl_custo`, `vl_margem` (numeric), `pr_margem` (numeric, %), `qt_sem_carta_frete` (int) e `vl_sem_carta_frete` (numeric) — o bloco excluído do cálculo —, `qt_custo_zero` (int), `qt_margem_negativa` (int), `vl_margem_negativa` (numeric).

**`linha = 'pior_caso'`** (N linhas): `cd_ctrc` (int), `nr_ctrc` (bigint), `ds_serie` (text), `dt_emissao` (date), `cliente` (text), `cd_pessoa_filial` (int), e reuso das colunas numéricas com significado por CT-e — `vl_receita` = `vl_total` do CT-e, `vl_custo` = carta frete daquele CT-e, `vl_margem` = diferença, `pr_margem` = % daquele CT-e. As colunas de agregado vêm `NULL`.

### Resultado real da execução

Rodada com os padrões, **1,36 s**:

| | |
| --- | --- |
| CT-es com custo conhecido | **3.583** |
| Receita | **R$ 20.875.055,22** |
| Custo (carta frete) | **R$ 18.616.201,58** |
| Margem | **R$ 2.258.853,64** — **10,82 %** |
| CT-es sem carta frete (fora do cálculo) | **371**, R$ 1.195.951,73 |
| CT-es com custo zero | **1** |
| CT-es com margem negativa | **158**, somando **−R$ 421.444,74** |

Sem o `limite`, a consulta devolve **648 CT-es** abaixo de 5% de margem. Piores: CT-e 37761 da DAUS ALIMENTOS — receita R$ 607,63 contra custo R$ 18.729,97 (**−R$ 18.122,34**); CT-e 17 da MINERVA — R$ 6.010,43 contra R$ 23.185,60 (−R$ 17.175,17); três CT-es da CALCARE INSUMOS (2113, 2128, 2095) com −R$ 8.675,37, −R$ 8.329,27 e −R$ 8.218,54.

### Ressalvas — o que esta consulta NÃO prova

- **Os piores casos foram conferidos contra o campo `ctrc.vl_resultado` do próprio ERP e o sinal bate** (DAUS: ERP marca −R$ 17.061,30; CALCARE 2113: −R$ 8.239,66). Não é artefato do meu cálculo — o ATUA também enxerga prejuízo nesses CT-es. A diferença de centavos vem de o ERP embutir pedágio/impostos que eu não incluo.
- **Margem por CT-e é frágil quando uma viagem carrega vários CT-es.** Um caminhão com uma carta frete alta e vários CT-es de valor pequeno joga todo o custo em cima de um deles. Os casos CALCARE têm exatamente esse formato. **A leitura confiável é o agregado; o `pior_caso` é fila de investigação.**
- **`vl_total` é receita bruta.** Não desconta ICMS, PIS/COFINS nem comissão. Os 10,82% são margem de contribuição de frete, não lucro.
- **Custo é só carta frete.** Pedágio pago fora da carta, quebra, avaria, seguro e despesa de filial não entram.
- **Os 371 CT-es sem carta frete não são de graça.** Ou são frota própria (custo em `caixa_veiculo`, ver consulta 5), ou a carta ainda não foi lançada. Tratar como “margem 100%” seria mentira — por isso ficam fora.

---

## 5. `frota.resultado_veiculo`

**O que faz.** Por placa da frota própria (`veiculo_proprio`, `dt_baixa IS NULL`), num período de `:dias`: quantidade de CT-es, receita atribuída e custos identificáveis, abertos por natureza.

**Como o veículo se liga ao CT-e — investigado antes de decidir.** O elo é `ctrc.cd_veiculo`, presente em 12.015 de 12.017 CT-es de 90 dias. Para isolar frota própria eu **não** usei o join solto `cd_veiculo IN (SELECT ... FROM veiculo_proprio)`: usei `ctrc.id_proprietario_veiculo = 1`, que é o flag do próprio ERP e nos 384 CT-es assim marcados tem `cd_pessoa_transportadora = 2` (a Pianetto) em 100% dos casos. `viagem` existe mas tem **494 linhas no banco inteiro** e não serve de base.

**Custo — e por que a carta frete ficou de fora.** Nos CT-es de frota própria há R$ 3.557.061,94 de `carta_frete` em 90 dias, emitida contra a própria Pianetto: é transferência interna, não saída de caixa. Somá-la ao combustível dava um resultado de **−R$ 2,58 milhões**, que é dupla contagem, não prejuízo. O custo real vem de `caixa_veiculo → caixa.vl_lancamento`, classificado por `historico_caixa.ds_historico`. A carta frete vai na saída como `vl_carta_frete_interna`, **informativa e fora do resultado**.

### SQL — pronto para colar em `CONSULTAS`

```python
    "frota.resultado_veiculo": (
        """\
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
 LIMIT %(limite)s""",
        ["dias", "cd_pessoa_filial", "limite"], False,
        "receita e custo identificavel por placa da frota propria no periodo"),
```

<details><summary>SQL puro (também em <code>sql/frota.resultado_veiculo.sql</code>)</summary>

```sql
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
```

</details>

### Parâmetros

| Parâmetro | Padrão | O que é |
| --- | --- | --- |
| `dias` | `90` | janela, aplicada a `ctrc.dt_emissao` e a `caixa.dt_documento` |
| `cd_pessoa_filial` | `None` | filial dos CT-es; `NULL` = todas |
| `limite` | `400` | linhas |

### Colunas devolvidas

| Coluna | Tipo | Significado |
| --- | --- | --- |
| `cd_veiculo` / `ds_placa` / `nr_frota` / `ds_modelo` | int/text/text/text | identificação |
| `nm_tipo_veiculo` | text | CAVALO TRUCADO, CARRETA…, CARRO, DOLLY, MOTO |
| `id_tracao` | bool | **true = unidade tratora**, a única que recebe receita |
| `qt_ctes` | int | CT-es de frota própria no período |
| `vl_receita` | numeric | soma de `ctrc.vl_total` |
| `vl_combustivel` | numeric | lançamentos com histórico de combustível |
| `vl_manutencao` | numeric | manutenção, peças, pneus, estofaria |
| `vl_pedagio` | numeric | notas de pedágio |
| `vl_pessoal` | numeric | salários e rescisões alocados ao veículo |
| `vl_custo_identificavel` | numeric | **total** de `caixa_veiculo`, inclusive o que não caiu nas classes acima |
| `vl_contribuicao` | numeric | `vl_receita − vl_custo_identificavel` |
| `pr_contribuicao` | numeric | % sobre a receita; `NULL` quando não houve receita |
| `vl_carta_frete_interna` | numeric | informativo, **não** entra no resultado |
| `vl_peso` / `vl_km` | numeric | peso e km dos CT-es |
| `dt_ultimo_cte` | date | último CT-e da placa |
| `cd_pessoa_filial` | int | filial |
| `qt_lancamentos_caixa` | int | quantos lançamentos de custo sustentam a linha |

### Resultado real da execução

Rodada com os padrões, **1,21 s**, 105 veículos com movimento.

**As 31 unidades tratoras (`id_tracao = true`), 90 dias:** 384 CT-es, receita **R$ 4.292.000,62**, custo direto **R$ 3.055.682,31**, contribuição **R$ 1.236.318,31 (28,8 %)**.

- **10 dos 31 cavalos têm contribuição negativa.** O pior: **SCU2F22** — 2 CT-es, R$ 15.617,20 de receita contra R$ 108.658,12 de custo (R$ 62.682,08 de combustível, R$ 16.162,98 de manutenção): **−R$ 93.040,92**.
- O melhor: **TVD5B79** — 25 CT-es, R$ 214.800,10 de receita, R$ 77.371,41 de custo, **+R$ 137.428,69 (63,98 %)**.
- **74 veículos sem tração consumiram R$ 343.506,78 sem gerar um único CT-e** — e a maior fatia são **43 automóveis (CARRO), R$ 274.496,19 em 90 dias**. Frota administrativa, não operacional.
- A margem de contribuição da frota própria (28,8%) é bem acima da margem de frete terceirizado da consulta 4 (10,82%) — mas as duas **não são comparáveis**, porque a primeira não carrega depreciação nem estrutura.

### Ressalvas — o que esta consulta NÃO prova

- **Só três coisas foram provadas:** o CT-e sabe qual veículo o puxou, o ERP sabe qual CT-e é de frota própria, e o caixa sabe qual veículo consumiu. **O que não existe é rateio de carreta.** A receita nasce no cavalo; a carreta que carregou a carga aparece só como custo. Comparar cavalos entre si é justo; comparar cavalo com carreta não é.
- **`vl_contribuicao` não é lucro.** Falta depreciação (`veiculo_depreciacao` existe, não foi usada), seguro de frota, IPVA, estrutura, e o motorista quando o salário não é lançado com o veículo.
- **Descasamento de período.** Receita é por `dt_emissao` do CT-e; custo é por `dt_documento` do caixa. Nota de manutenção lançada com atraso cai no período errado — é a explicação mais provável do caso SCU2F22 (2 CT-es contra R$ 108 mil de custo: veículo parado em oficina, com nota do serviço lançada nesta janela).
- **Veículo com custo e zero CT-e não é necessariamente ocioso.** Pode ser carreta, carro administrativo (é a maioria), ou cavalo em manutenção. A coluna `id_tracao` é o filtro para separar.
- **Classificação de custo é por texto de `ds_historico`.** Histórico novo com redação diferente cai fora das classes e sobra só em `vl_custo_identificavel` — que é justamente por isso o total, e não a soma das partes.
- **Amostra pequena:** 384 CT-es de frota própria contra 11.561 de terceiro em 90 dias. A Pianetto opera essencialmente com terceiros; esta consulta cobre ~3% do movimento.

---

## 6. `fiscal.cte_pendente`

**O que faz.** Classifica todo documento de `ctrc` da janela pela **situação real na SEFAZ**, lida de `ctrc_cte.cd_status` com a descrição de `status_cte.ds_status`. Devolve uma linha `resumo` por situação e a lista `pendente` dos casos abertos (não cancelados).

**A coluna de situação foi descoberta, não presumida.** Não existe campo de situação em `ctrc` — só `dt_cancelamento`. O código SEFAZ vive em `ctrc_cte.cd_status`, e `status_cte` cataloga 73 códigos. `ctrc_status_cte` é histórico de eventos, não estado atual.

### SQL — pronto para colar em `CONSULTAS`

```python
    "fiscal.cte_pendente": (
        """\
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
 LIMIT %(limite)s""",
        ["dias", "cd_pessoa_filial", "limite"], False,
        "CT-es dos ultimos N dias com situacao SEFAZ diferente de autorizado"),
```

<details><summary>SQL puro (também em <code>sql/fiscal.cte_pendente.sql</code>)</summary>

```sql
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
```

</details>

### Parâmetros

| Parâmetro | Padrão | O que é |
| --- | --- | --- |
| `dias` | `30` | janela por `dt_emissao` |
| `cd_pessoa_filial` | `None` | filial; `NULL` = todas |
| `limite` | `500` | linhas |

Classificação: `100`→`autorizado`; `101`→`cancelado`; `102`→`inutilizado`; `110/301/303`→`denegado`; qualquer outro código→`rejeitado`; sem linha em `ctrc_cte`→`nunca_transmitido`; linha existe mas `cd_status IS NULL`→`sem_retorno_sefaz`; `id_modelo = '55'`→`nao_e_cte_modelo_55` (é NF-e, não deve ser cobrada de CT-e).

### Colunas devolvidas

**`linha = 'resumo'`**: `situacao` (text), `qt` (bigint), `vl` (numeric). Uma linha por situação, **cobrindo a janela inteira**.

**`linha = 'pendente'`**: `situacao` (text), `cd_ctrc` (int), `nr_ctrc` (bigint), `ds_serie` (text), `dt_emissao` (date), `vl_total` (numeric), `cd_status` (int, código SEFAZ), `ds_status` (text, motivo da SEFAZ truncado em 140 caracteres), `cliente` (text), `cd_pessoa_filial` (int), `dt_cancelamento` (date), `dias_parado` (int). Só aparecem `nunca_transmitido`, `sem_retorno_sefaz`, `rejeitado`, `denegado` e `inutilizado`, e apenas os que **não** foram cancelados depois.

### Resultado real da execução

Rodada com os padrões, **1,04 s**. Resumo dos 30 dias:

| Situação | CT-es | Valor |
| --- | --- | --- |
| `autorizado` | 3.830 | R$ 21.453.378,54 |
| `cancelado` | 126 | R$ 738.601,24 |
| `nao_e_cte_modelo_55` | 67 | R$ 297.260,67 |
| `sem_retorno_sefaz` | 64 | R$ 439.430,86 |
| `nunca_transmitido` | 59 | R$ 349.541,59 |
| `rejeitado` | 14 | R$ 66.583,37 |

Nenhum denegado nem inutilizado na janela.

**Casos realmente abertos (não cancelados): 67 documentos, R$ 359.286,32** — 57 `nunca_transmitido`, 7 `sem_retorno_sefaz`, 3 `rejeitado`. Concentração óbvia: **ANDERSON PEIXOTO CORDEIRO** aparece com seis CT-es seguidos nunca transmitidos (nºs 464, 465, 466 de 11/08 a R$ 45.000,00 cada; 472, 473, 474 de 20/08 a R$ 31.500,00, R$ 27.000,00 e R$ 24.000,00) — **R$ 217.500,00 num cliente só**, todos na matriz. Em 90 dias o quadro é o mesmo em proporção: 11.772 autorizados, 363 cancelados, 13 com status 203 (emitente irregular), 3 com chave de NF-e inválida.

### Ressalvas — o que esta consulta NÃO prova

- **`nunca_transmitido` mistura duas coisas.** CT-e digitado e esquecido, e CT-e que é rascunho/minuta legítimo. O ERP não marca a diferença; `dias_parado` é o melhor separador prático (um documento parado há 25 dias não é rascunho).
- **`sem_retorno_sefaz` pode ser lixo antigo**: registro em `ctrc_cte` criado antes da transmissão e nunca atualizado. Dos 64 da janela, **57 já foram cancelados** — por isso a lista final mostra só 7.
- **O corte de `id_modelo = '55'` é meu, não do ERP.** Se a Pianetto passar a emitir CT-e com outro modelo, ou usar `55` para algo que deveria ser transmitido, esses 67 documentos somem da vigilância sem aviso.
- **`ds_status` do catálogo é genérico.** Vários textos em `status_cte` carregam protocolo e chave de um caso específico (ex.: o 204 traz o `nProt` de uma duplicidade antiga). É descrição do código, não a mensagem daquele CT-e — a mensagem individual está em `ctrc_status_cte.ds_status`.
- **Não consulta a SEFAZ.** Se o ERP perdeu o retorno, a consulta reproduz o erro do ERP. Ela audita o banco, não a receita estadual.

---
