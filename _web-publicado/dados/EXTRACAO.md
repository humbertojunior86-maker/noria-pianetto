# EXTRACAO - Retrato quantitativo Pianetto Transportes

**Data da extracao:** 2026-09-05  
**Data de referencia no banco (`current_date`):** 2026-09-05  
**Fonte:** ERP ATUA - PostgreSQL, schema `public`, acesso somente leitura (`jhn_ro`) via pgbouncer.  
**Script reprodutivel:** `cortex/dados/extrair_retrato.py` (regenera `retrato.json` do zero).  
**Saida:** `cortex/dados/retrato.json`

Todas as janelas temporais sao relativas a `current_date` do servidor. "Ultimos 12 meses" = `dt_emissao >= current_date - interval '12 months'`. Toda consulta a CT-es aplica `dt_cancelamento is null` (exceto o alerta que mede justamente os cancelados).

## Decisoes de modelagem verificadas no banco

| Questao | Verificacao | Conclusao |
| --- | --- | --- |
| Qual `titulo.id_tipo` e a receber? | `select t.id_tipo, count(*) from titulo_credito_vencimento d join titulo t using (cd_titulo) group by 1` -> 42.874 linhas, todas `id_tipo=1`; `titulo_debito` -> 35.566 linhas, todas `id_tipo=2`. Alem disso 41.504 de 41.733 titulos `id_tipo=1` pertencem a pessoas que sao pagadoras de CT-e. | **id_tipo=1 = A RECEBER**, **id_tipo=2 = A PAGAR** |
| Qual `id_situacao` significa ativo em `veiculo`/`motorista`? | Cruzamento com CT-es dos ultimos 90 dias: 4.457 de 4.725 veiculos utilizados estao em `id_situacao=2` (266 em 1, 2 em 0); mesmo padrao para motoristas (4.495 em 2). | **`id_situacao = 2` = ativo/liberado** |
| Existem `pessoa_juridica` / `pessoa_fisica`? | Nao aparecem em `information_schema.tables`. `pessoa.nr_cnpj_cpf` existe e esta preenchido. | Documentos lidos de `pessoa.nr_cnpj_cpf` |
| `dt_lancamento` do OFX e a data do movimento? | Conta 8189: 304 movimentos com `dt_lancamento` todos em 2026-08-19 (mesmo segundo) mas `dt_documento` distribuido de 2026-04-08 a 2026-08-18. | `dt_lancamento` = instante da importacao. **Usar `dt_documento`** |
| `id_conciliacao` e FK ou flag? | `select id_conciliacao, count(*) ... group by 1` -> apenas dois valores: 1 (43.142) e 0 (1.234); nunca nulo. | Flag booleano. Conciliado = `id_conciliacao = 1` |
| `ctrc.vl_custo` serve para margem? | 37.320 de 37.325 CT-es dos ultimos 12 meses tem `vl_custo` zerado (soma total R$ 4.838,86). `carta_frete.vl_frete` dos mesmos CT-es soma R$ 182.812.979,67. | Campo abandonado. **Custo = `carta_frete.vl_frete`**; `vl_resultado` (populado) mantido como resultado oficial |
| Nome de cidade/UF | `cidade` (cd_cidade, nm_cidade, cd_uf) join `uf` (cd_uf, ds_sigla). | Rotas formatadas como `CIDADE/UF` |

## 0. Metadados / data de referencia

Query 1:

```sql
select current_date d
```

## 1. empresa - matriz, filiais ativas, periodo coberto

Query 1:

```sql
select p.nm_pessoa, p.nm_fantasia, p.nr_cnpj_cpf
from filial f join pessoa p on p.cd_pessoa = f.cd_pessoa_filial
where f.cd_pessoa_filial = f.cd_pessoa_matriz and f.cd_pessoa_matriz = 2
```

Query 2:

```sql
select count(*) filter (where id_ativo = 2) ativas_2,
       count(*) filter (where id_ativo = 1) ativas_1,
       count(*) total,
       count(*) filter (where cd_pessoa_matriz = 2) grupo_pianetto,
       count(distinct cd_pessoa_matriz) matrizes
from filial
```

Query 3:

```sql
select min(dt_emissao) ini, max(dt_emissao) fim, count(*) ctes_validos, sum(vl_total) receita_total
from ctrc where dt_cancelamento is null
```

## 2. filiais - CT-es, receita, ticket medio e participacao (12 meses)

Query 1:

```sql
with base as (
  select c.cd_pessoa_filial, count(*) qt, sum(c.vl_total) receita,
         coalesce(sum((select sum(cf.vl_frete) from carta_frete cf where cf.cd_ctrc = c.cd_ctrc)), 0) custo,
         sum(c.vl_resultado) resultado
  from ctrc c
  where c.dt_cancelamento is null and c.dt_emissao >= current_date - interval '12 months'
  group by 1
)
select f.cd_pessoa_filial, coalesce(nullif(p.nm_fantasia,''), p.nm_pessoa) nome,
       p.nm_pessoa, p.nr_cnpj_cpf, f.id_ativo, f.cd_pessoa_matriz,
       coalesce(b.qt,0) qt, coalesce(b.receita,0) receita,
       coalesce(b.custo,0) custo, coalesce(b.resultado,0) resultado
from filial f
left join base b on b.cd_pessoa_filial = f.cd_pessoa_filial
left join pessoa p on p.cd_pessoa = f.cd_pessoa_filial
order by coalesce(b.receita,0) desc
```

## 3. faturamento_mensal - serie de 24 meses

Query 1:

```sql
select to_char(date_trunc('month', c.dt_emissao), 'YYYY-MM') mes,
       count(*) qt, sum(c.vl_total) receita, sum(c.vl_custo) custo_campo,
       sum(c.vl_resultado) resultado, sum(c.vl_peso) peso, sum(c.vl_frete) frete,
       coalesce(sum((select sum(cf.vl_frete) from carta_frete cf where cf.cd_ctrc = c.cd_ctrc)), 0) custo_carta_frete
from ctrc c
where c.dt_cancelamento is null
  and c.dt_emissao >= date_trunc('month', current_date) - interval '23 months'
group by 1 order by 1
```

## 4. clientes_top + concentracao_clientes

Query 1:

```sql
select c.cd_pessoa_pagador, coalesce(nullif(p.nm_fantasia,''), p.nm_pessoa) nome,
       p.nm_pessoa, p.nr_cnpj_cpf,
       count(*) qt, sum(c.vl_total) receita, sum(c.vl_resultado) resultado
from ctrc c left join pessoa p on p.cd_pessoa = c.cd_pessoa_pagador
where c.dt_cancelamento is null and c.dt_emissao >= current_date - interval '12 months'
group by 1,2,3,4 order by receita desc nulls last limit 15
```

Query 2:

```sql
with t as (
  select cd_pessoa_pagador, sum(vl_total) r
  from ctrc where dt_cancelamento is null and dt_emissao >= current_date - interval '12 months'
  group by 1
), tot as (select sum(r) total, count(*) clientes from t)
select (select sum(r) from (select r from t order by r desc limit 5) x) top5,
       (select sum(r) from (select r from t order by r desc limit 10) y) top10,
       (select sum(r) from (select r from t order by r desc limit 20) z) top20,
       total, clientes from tot
```

## 5. carteira - a receber e a pagar por faixa de atraso

Query 1:

```sql
select case when dt_vencimento >= current_date then 'a_vencer'
            when current_date - dt_vencimento between 1 and 30  then 'atraso_1_30'
            when current_date - dt_vencimento between 31 and 60 then 'atraso_31_60'
            when current_date - dt_vencimento between 61 and 90 then 'atraso_61_90'
            else 'atraso_mais_90' end faixa,
       count(*) qt, sum(vl_titulo - coalesce(vl_pago,0)) saldo, sum(vl_titulo) bruto
from titulo
where dt_quitacao is null and id_tipo = %s and vl_titulo - coalesce(vl_pago,0) > 0
group by 1
```

Query 2:

```sql
select case when dt_vencimento >= current_date then 'a_vencer'
            when current_date - dt_vencimento between 1 and 30  then 'atraso_1_30'
            when current_date - dt_vencimento between 31 and 60 then 'atraso_31_60'
            when current_date - dt_vencimento between 61 and 90 then 'atraso_61_90'
            else 'atraso_mais_90' end faixa,
       count(*) qt, sum(vl_titulo - coalesce(vl_pago,0)) saldo, sum(vl_titulo) bruto
from titulo
where dt_quitacao is null and id_tipo = %s and vl_titulo - coalesce(vl_pago,0) > 0
group by 1
```

## 6. contas_bancarias - 9 contas com movimento OFX

Query 1:

```sql
with mov as (
  select cd_conta, count(*) qt, min(dt_documento) ini, max(dt_documento) fim,
         count(*) filter (where id_conciliacao = 1) conciliados,
         sum(case when dt_documento >= current_date - 90 and vl_lancamento > 0 then vl_lancamento else 0 end) entradas90,
         sum(case when dt_documento >= current_date - 90 and vl_lancamento < 0 then vl_lancamento else 0 end) saidas90,
         count(*) filter (where dt_documento >= current_date - 90) qt90
  from caixa_financeiro_lancamento_ofx group by 1
)
select m.*, b.nm_banco, b.nr_banco, ct.nr_agencia, ct.nr_conta, ct.nr_digito_conta,
       ct.nm_titular, coalesce(nullif(p.nm_fantasia,''), p.nm_pessoa) titular_pessoa
from mov m
left join conta ct on ct.cd_conta = m.cd_conta
left join banco b on b.cd_banco = ct.cd_banco
left join pessoa p on p.cd_pessoa = ct.cd_pessoa
order by m.qt desc
```

## 7. frota - veiculos, motoristas, manifestos, cartas-frete

Query 1:

```sql
select (select count(*) from veiculo) veiculos_total,
       (select count(*) from veiculo where id_situacao = 2) veiculos_ativos,
       (select count(distinct cd_veiculo) from ctrc
          where dt_cancelamento is null and dt_emissao >= current_date - interval '12 months'
            and cd_veiculo is not null) veiculos_usados_12m,
       (select count(*) from motorista) motoristas_total,
       (select count(*) from motorista where id_situacao = 2) motoristas_ativos,
       (select count(distinct cd_pessoa_motorista) from ctrc
          where dt_cancelamento is null and dt_emissao >= current_date - interval '12 months'
            and cd_pessoa_motorista is not null) motoristas_usados_12m,
       (select count(*) from funcionario) funcionarios_total,
       (select count(*) from funcionario where dt_demissao is null) funcionarios_ativos,
       (select count(*) from manifesto
          where dt_cancelamento is null and dt_emissao >= current_date - interval '12 months') manifestos_12m,
       (select count(*) from manifesto) manifestos_total,
       (select count(*) from carta_frete
          where dt_emissao >= current_date - interval '12 months') cartas_frete_12m,
       (select count(*) from carta_frete) cartas_frete_total,
       (select coalesce(sum(vl_frete),0) from carta_frete
          where dt_emissao >= current_date - interval '12 months') valor_cartas_frete_12m,
       (select count(*) from viagem) viagens_total
```

Query 2:

```sql
select count(*) c from information_schema.columns
              where table_schema='public' and table_name='tipo_veiculo' and column_name='ds_tipo_veiculo'
```

## 8. rotas_top - 12 pares origem-destino mais frequentes

Query 1:

```sql
select co.nm_cidade || '/' || uo.ds_sigla origem,
       cd.nm_cidade || '/' || ud.ds_sigla destino,
       count(*) qt, sum(c.vl_total) receita, sum(c.vl_resultado) resultado, sum(c.vl_peso) peso
from ctrc c
join cidade co on co.cd_cidade = c.cd_cidade_origem
join cidade cd on cd.cd_cidade = c.cd_cidade_destino
join uf uo on uo.cd_uf = co.cd_uf
join uf ud on ud.cd_uf = cd.cd_uf
where c.dt_cancelamento is null and c.dt_emissao >= current_date - interval '12 months'
group by 1,2 order by qt desc limit 12
```

## 9. alertas - achados de controller (+ concentracao_grupos)

Query 1:

```sql
select count(*) qt, sum(vl_resultado) prejuizo, sum(vl_total) receita
from ctrc where dt_cancelamento is null and dt_emissao >= current_date - interval '12 months'
  and vl_resultado < 0
```

Query 2:

```sql
select count(*) qt from ctrc where dt_cancelamento is null
              and dt_emissao >= current_date - interval '12 months'
```

Query 3:

```sql
select count(*) qt, sum(vl_titulo - coalesce(vl_pago,0)) saldo
from titulo where id_tipo = 1 and dt_quitacao is null
  and vl_titulo - coalesce(vl_pago,0) > 0 and current_date - dt_vencimento > 90
```

Query 4:

```sql
select count(*) qt, sum(vl_titulo - coalesce(vl_pago,0)) saldo
from titulo where id_tipo = 2 and dt_quitacao is null
  and vl_titulo - coalesce(vl_pago,0) > 0 and current_date - dt_vencimento > 90
```

Query 5:

```sql
select count(*) filter (where coalesce(id_conciliacao,0) <> 1) nao_conc, count(*) total,
       sum(abs(vl_lancamento)) filter (where coalesce(id_conciliacao,0) <> 1) valor
from caixa_financeiro_lancamento_ofx where dt_documento >= current_date - 60
```

Query 6:

```sql
select count(*) qt, sum(vl_total) receita
from ctrc where dt_cancelamento is null and dt_emissao >= current_date - interval '12 months'
  and coalesce(vl_custo,0) = 0
```

Query 7:

```sql
select count(*) qt, sum(c.vl_total) valor from ctrc c
where c.dt_cancelamento is null and c.dt_emissao >= current_date - interval '12 months'
  and not exists (select 1 from carta_frete cf where cf.cd_ctrc = c.cd_ctrc)
```

Query 8:

```sql
select count(*) qt, sum(vl_total) valor from ctrc
where dt_emissao >= current_date - interval '12 months' and dt_cancelamento is not null
```

Query 9:

```sql
select count(*) qt, sum(vl_total) valor from ctrc
where dt_cancelamento is null and dt_emissao >= current_date - interval '12 months'
  and cd_pessoa_motorista is null
```

Query 10:

```sql
select count(*) qt, sum(vl_saldo) valor from carta_frete
where dt_emissao >= current_date - interval '12 months'
  and dt_retorno_comprovante is null and coalesce(vl_saldo,0) > 0
```

Query 11:

```sql
select count(*) qt, sum(vl_titulo - coalesce(vl_pago,0)) saldo from titulo
where id_tipo = 1 and dt_quitacao is null and vl_titulo - coalesce(vl_pago,0) > 0
  and dt_vencimento < current_date
```

Query 12:

```sql
select count(*) qt, sum(abs(o.vl_lancamento)) valor, count(distinct o.cd_conta) contas
from caixa_financeiro_lancamento_ofx o
join conta ct on ct.cd_conta = o.cd_conta
join banco b on b.cd_banco = ct.cd_banco
where b.nr_banco = 450 and coalesce(o.id_conciliacao,0) <> 1
```

Query 13:

```sql
with g as (
  select left(p.nr_cnpj_cpf, 8) raiz, sum(c.vl_total) receita, count(*) qt
  from ctrc c join pessoa p on p.cd_pessoa = c.cd_pessoa_pagador
  where c.dt_cancelamento is null and c.dt_emissao >= current_date - interval '12 months'
    and p.nr_cnpj_cpf is not null and length(trim(p.nr_cnpj_cpf)) = 14
  group by 1
)
select raiz, receita, qt from g order by receita desc limit 1
```

## Chaves do JSON e como auditar

| Chave | Bloco de queries acima | Observacao |
| --- | --- | --- |
| `empresa` | 1 | `filiais_ativas` = `count(*) filter (where id_ativo=1)` em `filial`; todas as 14 tem `id_ativo=1` e `dt_inativacao` nula. Duas matrizes convivem no banco: Pianetto (cd 2, 11 filiais) e Calcare Insumos (cd 9124, 3 filiais). |
| `filiais` | 2 | Lista as 14 filiais cadastradas (6 sem CT-e nos ultimos 12 meses aparecem com zeros). `nm_fantasia` esta vazio para todas, usou-se `nm_pessoa`. Participacao calculada sobre a receita de 12 meses das filiais (R$ 219,330,260.36). |
| `faturamento_mensal` | 3 | Janela 2024-10 a 2026-09. `custo` = soma de `carta_frete.vl_frete` dos CT-es do mes; `custo_campo_vl_custo` preservado para evidenciar que o campo esta vazio. `margem_pct` = `vl_resultado / vl_total`. |
| `clientes_top`, `concentracao_clientes` | 4 | Agrupado por `cd_pessoa_pagador`. Atencao: MOTZ TRANSPORTES aparece como 1o e 2o colocado por serem CNPJs distintos (filiais GO e SP) do mesmo grupo - ver `concentracao_grupos`. |
| `carteira` | 5 | Saldo = `vl_titulo - coalesce(vl_pago,0)`, somente `dt_quitacao is null` e saldo > 0. Faixas por `current_date - dt_vencimento`. |
| `contas_bancarias` | 6 | Uma linha por `cd_conta` presente no OFX (exatamente 9). Periodo, entradas/saidas 90d e conciliacao usam `dt_documento`. Sinal de `vl_lancamento` preservado (saidas negativas). |
| `frota` | 7 | `*_ativos` usam `id_situacao=2`. O cadastro de veiculos/motoristas inclui terceiros e agregados, por isso os totais (63,2 mil veiculos) sao muito maiores que a frota efetivamente utilizada (`*_usados_12m`). `funcionarios_ativos` = `dt_demissao is null`. |
| `rotas_top` | 8 | Inner join obrigatorio com `cidade`/`uf`; CT-es sem cidade resolvida ficam de fora. Ordenado por quantidade de CT-es. |
| `alertas`, `concentracao_grupos` | 9 | Cada alerta tem uma query propria listada no bloco 9, na mesma ordem em que aparece o codigo. Severidade atribuida por regra explicita no script (ex.: nao conciliados > 30% = critica). |
| `nao_apurado` | - | Limitacoes conhecidas, incluindo a ausencia de saldo bancario consolidado. |

## Nao apurado

- **documentos_pessoa**: Nao existem tabelas pessoa_juridica/pessoa_fisica neste banco; CNPJ/CPF foi lido diretamente de pessoa.nr_cnpj_cpf.
- **nm_fantasia_filiais**: Nenhuma filial possui nm_fantasia preenchido em pessoa; foi usada a razao social (nm_pessoa) como nome.
- **dt_lancamento_ofx**: caixa_financeiro_lancamento_ofx.dt_lancamento reflete o instante da importacao do arquivo, nao a data do movimento; todas as metricas de periodo usam dt_documento, que e a data real do lancamento bancario.
- **serie_24_meses**: A janela de 24 meses vai de 2024-10 a 2026-09. O banco tem CT-es desde 2024-08-26, mas os meses 2024-08 e 2024-09 ficam fora da janela; 2026-09 e parcial (ate o dia 5).
- **conciliacao_ofx**: id_conciliacao e um flag 0/1 (nao nulo em 100% das linhas), nao uma FK. O percentual de conciliacao foi calculado como id_conciliacao = 1.
- **saldo_bancario**: Nao foi apurado saldo contabil das contas: o OFX importado nao traz campo de saldo e nao foi localizada tabela de saldo consolidado por conta confiavel.
