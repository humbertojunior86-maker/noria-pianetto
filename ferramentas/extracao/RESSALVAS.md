### Ressalvas — o que esta consulta NÃO prova

- **Não prova duplicidade. Prova coincidência.** Dois caminhões iguais comprados no mesmo dia do mesmo revendedor produzem exatamente esta assinatura — e os casos SUÉCIA/VARELLA/LIBRELATO têm essa cara. O que a consulta entrega é uma fila de conferência ordenada por dinheiro, não uma acusação.
- **Seguro por veículo é falso positivo estrutural.** A AXA emite uma apólice por placa; frota homogênea gera prêmios idênticos. É a maior fonte de linhas na cauda.
- **`vl_min = 100` corta duplicidades pequenas de alto volume** (tarifa bancária, pedágio avulso). Baixar o parâmetro aumenta muito o número de linhas.
- **Agrupa por valor exato arredondado a 2 casas.** Duplicidade com centavos de diferença (juro, desconto) escapa.
- **`max_parcelas = 3` pode esconder duplicidade real** em compra parcelada em 4× ou mais. É um trade-off consciente: sem ele, 33 dos 432 grupos eram financiamento de frota puro.
- **Não olha o extrato bancário.** Dois títulos quitados não são prova de duas saídas de caixa; a confirmação é cruzar com `caixa_financeiro_lancamento` / `ar_cd_conciliado`.

---

## 2. `faturamento.cte_sem_titulo`
### Ressalvas — o que esta consulta NÃO prova

- **Nem todo CT-e sem título é frete não cobrado.** Alguns CT-es de subcontratação, redespacho ou complemento podem ser faturados por fora ou nem gerar cobrança própria. `id_frete` e `id_tipo_ctrc` vão na saída exatamente para o analista separar — não filtrei por eles porque **as três modalidades aparecem tanto no grupo faturado quanto no não faturado**, então não existe regra limpa de exclusão.
- **A carência de 7 dias é arbitrária.** Com carência 0 a lista sobe para 802 CT-es porque inclui o faturamento em curso. Se a Pianetto fatura quinzenal, o parâmetro deveria subir para 15.
- **Não prova que o cliente não pagou.** Prova que o ERP não tem título. Cobrança por fora do sistema não aparece aqui.
- Só cobre CT-e com `cd_status = 100`. CT-e não transmitido é problema da consulta 6, de propósito.

---

## 3. `comercial.cliente_que_sumiu`
### Ressalvas — o que esta consulta NÃO prova

- **“Sumiu” é errado para os `caiu`.** MOTZ emitiu CT-e hoje. A consulta detecta *queda*, não abandono; use a coluna `situacao` para separar as duas leituras antes de mandar alguém ligar.
- **Sazonalidade agrícola vira falso positivo em massa.** A carteira da Pianetto é agro (AMAGGI, SLC, CHS, COFCO, fertilizantes). Comparar a entressafra contra a safra acusa o setor inteiro. Uma versão honesta compararia com o mesmo período do ano anterior — o banco tem histórico desde 26/08/2024, ou seja, **cabe exatamente um ano de comparação, sem folga**.
- **Agrupa por `cd_pessoa_pagador`, não por grupo econômico.** Cliente que trocou o CNPJ pagador de filial aparece como perdido e ganho ao mesmo tempo. Para consolidar, aplicar a raiz de 8 dígitos do CNPJ como em `ceo.concentracao`.
- **`dt_ultimo_cte` é limitada pela janela** de `dias_base + dias_recente` (240 dias). Cliente parado há mais tempo que isso nem entra na lista, porque não tem base de comparação.
- **Não olha título nem inadimplência.** Cliente pode ter sido bloqueado por débito de propósito — isso é decisão, não perda.

---

## 4. `controladoria.margem_por_cte`
### Ressalvas — o que esta consulta NÃO prova

- **Os piores casos foram conferidos contra o campo `ctrc.vl_resultado` do próprio ERP e o sinal bate** (DAUS: ERP marca −R$ 17.061,30; CALCARE 2113: −R$ 8.239,66). Não é artefato do meu cálculo — o ATUA também enxerga prejuízo nesses CT-es. A diferença de centavos vem de o ERP embutir pedágio/impostos que eu não incluo.
- **Margem por CT-e é frágil quando uma viagem carrega vários CT-es.** Um caminhão com uma carta frete alta e vários CT-es de valor pequeno joga todo o custo em cima de um deles. Os casos CALCARE têm exatamente esse formato. **A leitura confiável é o agregado; o `pior_caso` é fila de investigação.**
- **`vl_total` é receita bruta.** Não desconta ICMS, PIS/COFINS nem comissão. Os 10,82% são margem de contribuição de frete, não lucro.
- **Custo é só carta frete.** Pedágio pago fora da carta, quebra, avaria, seguro e despesa de filial não entram.
- **Os 371 CT-es sem carta frete não são de graça.** Ou são frota própria (custo em `caixa_veiculo`, ver consulta 5), ou a carta ainda não foi lançada. Tratar como “margem 100%” seria mentira — por isso ficam fora.

---

## 5. `frota.resultado_veiculo`
### Ressalvas — o que esta consulta NÃO prova

- **Só três coisas foram provadas:** o CT-e sabe qual veículo o puxou, o ERP sabe qual CT-e é de frota própria, e o caixa sabe qual veículo consumiu. **O que não existe é rateio de carreta.** A receita nasce no cavalo; a carreta que carregou a carga aparece só como custo. Comparar cavalos entre si é justo; comparar cavalo com carreta não é.
- **`vl_contribuicao` não é lucro.** Falta depreciação (`veiculo_depreciacao` existe, não foi usada), seguro de frota, IPVA, estrutura, e o motorista quando o salário não é lançado com o veículo.
- **Descasamento de período.** Receita é por `dt_emissao` do CT-e; custo é por `dt_documento` do caixa. Nota de manutenção lançada com atraso cai no período errado — é a explicação mais provável do caso SCU2F22 (2 CT-es contra R$ 108 mil de custo: veículo parado em oficina, com nota do serviço lançada nesta janela).
- **Veículo com custo e zero CT-e não é necessariamente ocioso.** Pode ser carreta, carro administrativo (é a maioria), ou cavalo em manutenção. A coluna `id_tracao` é o filtro para separar.
- **Classificação de custo é por texto de `ds_historico`.** Histórico novo com redação diferente cai fora das classes e sobra só em `vl_custo_identificavel` — que é justamente por isso o total, e não a soma das partes.
- **Amostra pequena:** 384 CT-es de frota própria contra 11.561 de terceiro em 90 dias. A Pianetto opera essencialmente com terceiros; esta consulta cobre ~3% do movimento.

---

## 6. `fiscal.cte_pendente`
### Ressalvas — o que esta consulta NÃO prova

- **`nunca_transmitido` mistura duas coisas.** CT-e digitado e esquecido, e CT-e que é rascunho/minuta legítimo. O ERP não marca a diferença; `dias_parado` é o melhor separador prático (um documento parado há 25 dias não é rascunho).
- **`sem_retorno_sefaz` pode ser lixo antigo**: registro em `ctrc_cte` criado antes da transmissão e nunca atualizado. Dos 64 da janela, **57 já foram cancelados** — por isso a lista final mostra só 7.
- **O corte de `id_modelo = '55'` é meu, não do ERP.** Se a Pianetto passar a emitir CT-e com outro modelo, ou usar `55` para algo que deveria ser transmitido, esses 67 documentos somem da vigilância sem aviso.
- **`ds_status` do catálogo é genérico.** Vários textos em `status_cte` carregam protocolo e chave de um caso específico (ex.: o 204 traz o `nProt` de uma duplicidade antiga). É descrição do código, não a mensagem daquele CT-e — a mensagem individual está em `ctrc_status_cte.ds_status`.
- **Não consulta a SEFAZ.** Se o ERP perdeu o retorno, a consulta reproduz o erro do ERP. Ela audita o banco, não a receita estadual.

---
