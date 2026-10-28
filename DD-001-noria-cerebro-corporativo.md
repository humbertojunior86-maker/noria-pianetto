# DD-001: NÓRIA — Cérebro Corporativo Autônomo da Pianetto

Versão 2.0 · Setembro/2026 · Autor: Arquitetura · Sponsor: José Humberto Jr. (CEO)

---

## 1. Contexto

Hoje a Pianetto tem dados demais e conclusão de menos. ATUA (Mais Frete), Power BI com 12 relatórios, Supabase `pianettoai`, n8n, Weeke, ATS Via RH, WorkMonitor, Gobrax, X7 Bank, T4S, RD Conversas/UZAPI, Outlook e GitHub produzem informação continuamente — mas quem cruza, desconfia e cobra ainda é gente. Dashboard não pensa: ele espera alguém olhar.

A NÓRIA inverte isso. Não é um painel, é um **órgão de decisão**: um orquestrador que formula hipóteses sobre onde a empresa está perdendo dinheiro, aciona agentes especialistas para investigar, confronta uma fonte contra a outra, exige evidência, calcula impacto em R$ e só então fala com um humano — já com o caso montado e a ação sugerida.

Princípio-mestre: **nenhum achado existe sem evidência rastreável e sem impacto financeiro estimado.**

---

## 2. Objetivos

Ao final da implantação a NÓRIA deve, sem intervenção humana:

1. Varrer continuamente todas as áreas (comercial, financeiro, crédito/cobrança, tesouraria, controladoria, fiscal, contábil, compras, frota, operação, RH, compliance/SGI, jurídico, TI) em busca de **prejuízo, fraude, processo errado, processo lento e processo duplicado**.
2. **Confrontar relatório contra relatório** e sistema contra sistema — ATUA × Power BI × extrato bancário × SEFAZ × telemetria × cartão diesel × ponto — e tratar divergência como hipótese, não como ruído.
3. **Validar rotinas e entregáveis**: saber se cada função executou o que devia, no horário, com evidência, e escalar quando não executou.
4. **Abrir e conduzir casos** com dono, prazo, alçada e trilha imutável, integrando-se ao Weeke, e-mail e WhatsApp.
5. **Aprender**: cada caso confirmado ou descartado recalibra o detector que o originou.

Meta de negócio do ano 1: recuperar/evitar perda equivalente a **1,5% a 3% do faturamento** (faixa típica de leakage em transportadoras com múltiplas filiais) e reduzir o tempo de detecção de anomalia de "semanas" para "menos de 24h".

---

## 3. Arquitetura em camadas

```
┌──────────────────────────────────────────────────────────────────────┐
│  L6  INTERFACE       Sala do CEO · Briefing diário · WhatsApp · Email │
├──────────────────────────────────────────────────────────────────────┤
│  L5  AÇÃO            Casos, chamados Weeke, bloqueios, cobranças,     │
│                      notificações, tarefas com prazo e alçada        │
├──────────────────────────────────────────────────────────────────────┤
│  L4  CÓRTEX          Orquestrador · Planner · Fila de hipóteses ·     │
│      (raciocínio)    Roteador de agentes · Árbitro de conflitos       │
├──────────────────────────────────────────────────────────────────────┤
│  L3  AGENTES         14 agentes de área + 6 agentes transversais      │
│                      (cada um com skills e ferramentas próprias)      │
├──────────────────────────────────────────────────────────────────────┤
│  L2  DETECTORES      ~120 regras + modelos estatísticos + LLM judge   │
│                      (produzem SINAIS, não conclusões)                │
├──────────────────────────────────────────────────────────────────────┤
│  L1  MEMÓRIA         Data lake operacional + camada semântica +       │
│                      memória vetorial (pgvector) + ledger append-only │
├──────────────────────────────────────────────────────────────────────┤
│  L0  INGESTÃO        Conectores: ATUA API/réplica, Supabase, Power BI,│
│                      SEFAZ, bancos, Gobrax, X7, T4S, Weeke, RH, Zap   │
└──────────────────────────────────────────────────────────────────────┘
```

### L0 — Ingestão

| Fonte | Tipo | Cadência | O que alimenta |
|---|---|---|---|
| ATUA / Mais Frete | REST API + réplica PostgreSQL read-only | 15 min (delta) | CT-e, contas a pagar/receber, viagens, frota, cadastros |
| Supabase `pianettoai` / `pianetto-boards` | PostgreSQL | tempo real (webhook) | boards, formulários, rotinas |
| Power BI | REST API (dataset refresh + query) | 1 h | KPIs consolidados para confronto |
| SEFAZ / distribuição DFe | Web service | 30 min | CT-e, NF-e, MDF-e, eventos, cancelamentos |
| Extratos bancários | OFX / API / CNAB retorno | diário 08:00 | conciliação de tesouraria |
| X7 / C7 Bank | API (IP autorizado) | diário | abastecimento, preço/litro, cartão × veículo |
| Gobrax | API | diário | score de condução, consumo, telemetria |
| T4S | API | diário | rastreamento, câmeras, jornada |
| Weeke | API / export | 1 h | chamados, SLA, retrabalho |
| ATS Via RH + WorkMonitor | API / export | diário | ponto, presença, atividade de PC |
| RD Conversas / UZAPI | webhook | tempo real | tratativas, evidências de comunicação |
| Outlook / Microsoft 365 | Graph API | 1 h | despachos, malotes, comprovantes, cotas de caixa |
| GitHub | API | evento | deploys, mudanças em automações |

Padrão obrigatório: **toda ingestão é idempotente, versionada e carimbada** (`source`, `source_id`, `fetched_at`, `hash`). Nada é sobrescrito — cada carga vira uma nova versão, para que a NÓRIA consiga responder "o valor mudou depois?".

### L1 — Memória

Três memórias distintas:

- **Operacional (fatos)** — tabelas normalizadas por domínio no schema `noria_raw` + `noria_core`. É a verdade transacional.
- **Semântica (conceitos)** — dicionário de negócio versionado: o que é "margem por viagem", "estadia indevida", "título órfão". Sem isso, agente nenhum concorda com outro.
- **Episódica (experiência)** — pgvector com histórico de casos, decisões do CEO, justificativas aceitas e recusadas. É o que faz o sistema parar de repetir a mesma pergunta boba.

### L2 — Detectores

Detectores **não decidem**. Produzem sinais com `score`, `janela`, `entidades envolvidas` e `evidência bruta`. Três famílias:

1. **Determinísticos (SQL)** — duplicidade exata, título sem centro de custo, CT-e sem MDF-e, pagamento sem fatura.
2. **Estatísticos** — outlier de preço/km por rota, z-score de estadia por filial, quebra de sazonalidade de receita, Benford em valores de despesa (clássico antifraude).
3. **Semânticos (LLM)** — leitura de contrato × prática real, justificativa vaga em baixa manual, descrição de despesa incompatível com o centro de custo, texto de tratativa que revela combinação entre comprador e fornecedor.

### L3 — Agentes

Cada agente tem: escopo, ferramentas permitidas, dados que pode ler, ações que pode propor, e **nunca** ação de escrita direta em sistema financeiro.

**Agentes de área (14)**

| Agente | Missão central | Confrontos típicos |
|---|---|---|
| Comercial | margem por cliente/rota, desconto sem alçada, cliente que só dá volume | tabela de preço × CT-e emitido × margem realizada |
| Crédito | limite estourado, carga liberada sem aprovação, produtor rural >15 dias | política de crédito × liberação × faturamento |
| Cobrança | aging, promessa quebrada, baixa manual suspeita | título em aberto × extrato × registro de contato |
| Faturamento | CT-e não faturado, faturamento fora de regra do cliente | viagem concluída × CT-e × fatura |
| Tesouraria | amarração diária 09:15, pagamento sem lastro, conta de terceiro | extrato × contas a pagar × contas a receber |
| Contas a pagar | duplicidade, rateio ausente, fora da janela 10/20/30 | NF × pedido × recebimento × pagamento |
| Controladoria | DRE gerencial × contábil, centro de custo, resultado por veículo | ATUA × Power BI × contabilidade |
| Fiscal | ICMS, CT-e/MDF-e irregular, crédito perdido, retrabalho | XML × escrita fiscal × SEFAZ |
| Contabilidade | conciliação de contas, provisão, fechamento | balancete × razão × operacional |
| Compras | preço acima de mercado, fornecedor concentrado, vínculo suspeito | 3 cotações × histórico × CNPJ/sócios |
| Frota | custo/km, diesel fora de rota, manutenção repetida, pneu | X7 × Gobrax × T4S × ordem de serviço |
| Operação | viagem sem manifesto, estadia indevida, ociosidade | T4S × ATUA × registro de estadia |
| RH | ponto × produtividade, hora extra crônica, rotatividade cara | ATS Via RH × WorkMonitor × entregáveis |
| Compliance/SGI | PGR, DDR, SASSMAQ, documento vencido, cobertura de seguro | checklist × embarque × apólice |

**Agentes transversais (6)**

- **Auditor de Rotinas** — verifica execução, horário, evidência e teto de score (rotina 45% / KPI 35% / gestor 20%), escalando tarefa crítica em aberto.
- **Auditor de Entregáveis** — confere se o que foi prometido foi entregue (relatório enviado, malote recebido, conciliação fechada), não se a tarefa foi "marcada como feita".
- **Caçador de Fraude** — trabalha por padrão e não por regra: conluio, fornecedor-fantasma, quebra de segregação, mesma pessoa concedendo e baixando.
- **Analista de Processo** — mede lead time, retrabalho, fila e duplicidade de esforço entre setores. É o agente que descobre processo lento e processo duplicado.
- **Pesquisador Externo** — preço de diesel, tabela ANTT, piso mínimo de frete, situação cadastral de CNPJ, protesto, reclamação trabalhista de concorrente, benchmark setorial.
- **Advogado do Diabo** — obrigatório. Antes de qualquer caso chegar ao CEO, tenta derrubá-lo: busca a explicação inocente, o dado desatualizado, o falso positivo. Caso que sobrevive a ele é caso de verdade.

### L4 — Córtex (o orquestrador)

O núcleo roda um loop contínuo de 7 passos:

```
SENSE      → coleta sinais dos detectores e eventos de webhook
FRAME      → agrupa sinais correlatos em UMA hipótese ("filial X paga estadia acima do padrão")
PLAN       → escolhe quais agentes acionar, em que ordem, com que orçamento de tempo/custo
INVESTIGATE→ agentes buscam evidência em fontes independentes
CONFRONT   → cruza as evidências; discordância entre fontes vira sub-hipótese
JUDGE      → Advogado do Diabo + árbitro: confirma, descarta ou pede mais dado
ACT        → abre caso, notifica dono, define prazo/alçada, registra no ledger
LEARN      → resultado retroalimenta o peso do detector e a memória episódica
```

Regras de governo do loop:
- **Orçamento por hipótese** (tempo, chamadas de LLM, custo). Hipótese cara sem retorno é arquivada.
- **Prioridade = impacto R$ × probabilidade × reversibilidade.** Perda ainda evitável ganha da perda já consumada.
- **Quorum para acusação de fraude**: mínimo de 2 evidências de fontes independentes + parecer do Advogado do Diabo. Nunca acusa pessoa nominalmente sem isso; o caso nasce como "risco de controle", não como "fulano roubou".
- **Fila de escuridão**: áreas que não geram sinal por muito tempo entram em varredura ativa. Silêncio não é sinal de saúde.

### L5 — Ação

Cada caso confirmado gera uma ação proporcional:

| Nível | Gatilho | Ação automática |
|---|---|---|
| 1 Informativo | desvio pequeno, sem risco | entra no briefing diário |
| 2 Cobrança | rotina não executada, evidência faltando | mensagem ao dono + prazo D+1 |
| 3 Caso | prejuízo estimado ou controle quebrado | chamado no Weeke com dono, prazo, checklist |
| 4 Bloqueio | risco de perda imediata | recomenda bloqueio (liberação de carga, pagamento) para aprovação humana |
| 5 CEO | fraude provável, valor material, risco jurídico | dossiê completo para o CEO em canal reservado |

**Nenhuma ação nível 4 ou 5 é executada sem humano.** A NÓRIA propõe, o humano assina — e a assinatura fica no ledger.

### L6 — Interface

- **Sala do CEO** (web, mobile-first): não é dashboard de números, é **fila de decisões**. Cada card traz: o que aconteceu, quanto custa, quem é o dono, o que o sistema recomenda, e três botões — Aprovar / Rejeitar / Pedir mais evidência.
- **Briefing diário 07:00** por e-mail/WhatsApp: 5 achados de maior impacto, dinheiro em risco no dia, rotinas não cumpridas, o que o sistema fez sozinho nas últimas 24h.
- **Pergunte ao Cérebro**: linguagem natural sobre toda a base ("por que a margem de Jataí caiu em agosto?") — o córtex aciona os agentes necessários e responde com fontes.

---

## 4. Modelo de dados (schema `noria`)

```sql
-- Núcleo
signal(id, detector_id, tipo, severidade, score, janela_ini, janela_fim,
       entidades jsonb, payload jsonb, empresa_id, created_at)

hypothesis(id, titulo, area, status, prioridade, impacto_estimado_brl,
           probabilidade, signals uuid[], empresa_id, created_at, closed_at)

agent_run(id, hypothesis_id, agent, objetivo, ferramentas jsonb, input jsonb,
          output jsonb, custo_tokens, duracao_ms, status, created_at)

evidence(id, hypothesis_id, fonte, fonte_ref, tipo, conteudo jsonb,
         hash_sha256, coletado_em, confiabilidade numeric)

finding(id, hypothesis_id, classe, -- prejuizo | fraude | erro | lento | duplicado
        descricao, impacto_brl, confianca, contra_argumento,
        veredito_devils_advocate, dono_sugerido, created_at)

case_(id, finding_id, nivel, dono, prazo, status, weeke_id,
      decisao_humana, decidido_por, decidido_em)

ledger(id, entidade, entidade_id, evento, ator, payload jsonb,
       hash_anterior, hash, created_at) -- append-only, encadeado

-- Controle de rotinas
routine(id, funcao, titulo, horario_alvo, criticidade, evidencia_obrigatoria bool)
routine_run(id, routine_id, colaborador_id, data, executado_em,
            evidencia_url, justificativa, status, validado_por_agente bool)
deliverable(id, funcao, titulo, periodicidade, criterio_aceite jsonb)
deliverable_check(id, deliverable_id, periodo, entregue bool,
                  prova jsonb, verificado_em)

-- Metadados
detector(id, nome, familia, sql_ou_prompt, peso, precisao_historica,
         falsos_positivos, ativo)
confront_matrix(id, fonte_a, fonte_b, chave_join, tolerancia, regra)
```

Regras não negociáveis:
- **RLS em 100% das tabelas**, com filtro por `empresa_id` (Pianetto, AdaptaLog, Calcari e futuras).
- `ledger` é **append-only com hash encadeado** — trilha probatória serve para auditoria, seguro e, se preciso, processo judicial.
- `service_role` só em Edge Function / worker server-side. Nunca no front.
- Todo dado pessoal de colaborador (ponto, WorkMonitor) tem base legal registrada e retenção definida — LGPD, art. 7º e 37.

---

## 5. Matriz de confronto (o coração do "confere um relatório com o outro")

| # | Fonte A | Fonte B | Chave | O que expõe |
|---|---|---|---|---|
| C01 | Viagem concluída (ATUA) | CT-e autorizado (SEFAZ) | viagem/placa/data | receita não faturada |
| C02 | CT-e (SEFAZ) | Contas a receber (ATUA) | número CT-e | título não gerado |
| C03 | Contas a receber | Extrato bancário | valor+data+sacado | baixa sem dinheiro / dinheiro sem baixa |
| C04 | Contas a pagar | NF + comprovante de recebimento | fornecedor+NF | pagamento sem lastro, duplicidade |
| C05 | Abastecimento X7 | Rota T4S/Gobrax | placa+timestamp+geo | diesel fora de rota, desvio |
| C06 | Km rodado ATUA | Km telemetria | placa+período | km inflado, acerto indevido |
| C07 | Estadia registrada | Permanência real (rastreador) | viagem | estadia indevida paga |
| C08 | DRE gerencial (Power BI) | Balancete contábil | conta+competência | resultado que não fecha |
| C09 | Ponto (ATS) | Atividade PC (WorkMonitor) | colaborador+dia | hora paga sem trabalho / trabalho sem registro |
| C10 | Rotina declarada | Evidência anexada | rotina+dia | checklist declaratório |
| C11 | Cotação de compra | Preço de mercado (pesquisa) | item+período | sobrepreço |
| C12 | Sócios de fornecedor | Cadastro de colaboradores | CPF/CNPJ | conflito de interesse |
| C13 | Contrato do cliente | Regra de faturamento aplicada | cliente | faturamento fora do contrato |
| C14 | Manifesto (MDF-e) | Veículo em movimento | placa+data | "sem manifesto, não roda" violado |
| C15 | Chamado Weeke | Reabertura do mesmo tema | assunto+cliente | retrabalho e processo errado |

Cada linha vira um detector com tolerância parametrizada e histórico de precisão.

---

## 6. Catálogo de achados por classe

**Prejuízo** — frete abaixo do custo por rota, estadia paga indevidamente, multa evitável, juros por atraso próprio, crédito fiscal não aproveitado, caixa parado sem aplicação, seguro pagando o que o processo devia prevenir.

**Fraude** — fornecedor com vínculo, cartão diesel abastecendo veículo de terceiro, baixa manual sem lastro, pagamento em conta de terceiro (proibido na política), nota de serviço sem serviço, conluio filial-motorista em descarga, quebra de segregação em crédito/cobrança.

**Processo errado** — carga liberada sem análise de crédito, CT-e emitido com tomador errado, rateio de despesa ausente, lançamento sem centro de custo, cliente novo operando sem onboarding concluído.

**Processo lento** — lead time de faturamento, tempo entre chegada do documento e pagamento do motorista (risco reputacional já mapeado nas filiais), SLA de chamado, tempo de fechamento contábil, fila do fiscal.

**Processo duplicado** — dois setores conferindo o mesmo documento, relatório manual que já existe no BI, retrabalho entre Weeke e RD Conversas, dupla digitação MyRP → ATUA.

---

## 7. Stack e implementação

| Camada | Tecnologia | Justificativa |
|---|---|---|
| Ingestão/ETL | n8n + workers Node/TypeScript no Dokploy | já rodam no 187.77.242.106, custo zero adicional |
| Armazenamento | **Supabase novo e dedicado** (`noria`) + pgvector | isolamento do `pianettoai`; um bug do cérebro não derruba a operação |
| Orquestrador | Worker Node/TS com fila (pg-boss ou Redis) | controle fino de orçamento, retry e paralelismo |
| Agentes | Claude/GPT via API, com ferramentas tipadas (function calling) | modelo forte para julgamento, barato para triagem |
| Detectores SQL | Views materializadas + jobs pg_cron | rápido e barato; 80% dos achados saem daqui |
| Front | Nuxt 4 + Vue 3 + Tailwind (padrão IA16) | reaproveita design system e auth existentes |
| Notificação | UZAPI (WhatsApp), Outlook/Graph (e-mail), Weeke (chamado) | canais que a empresa já usa |
| Observabilidade | Logs estruturados + painel de custo por agente | evita o cérebro virar despesa descontrolada |

Recomendação de infra: **Supabase dedicado para a NÓRIA**, lendo ATUA por API/réplica read-only. Custo marginal baixo, risco operacional muito menor, e permite política de retenção e RLS próprias sem contaminar os produtos existentes.

Custo estimado de operação (regime): infraestrutura R$ 300–800/mês + LLM R$ 1.500–4.000/mês na fase madura, com triagem barata e julgamento caro apenas nos casos que sobrevivem à triagem.

---

## 8. Plano de implantação

**Fase 0 — Fundação (semanas 1–3)**
Supabase `noria`, schema núcleo, RLS, ledger, ingestão ATUA (delta 15 min) + extrato bancário + Power BI. Entregável: base viva e auditável.

**Fase 1 — Primeiro cérebro: Financeiro/Tesouraria (semanas 4–7)**
Confrontos C02, C03, C04 + detectores de duplicidade, título órfão, rateio e centro de custo (aproveitando as skills de auditoria e SQL financeiro que já existem). Agentes: Tesouraria, Contas a Pagar, Cobrança, Advogado do Diabo. Entregável: **briefing diário 07:00 com dinheiro em risco** e casos no Weeke.

**Fase 2 — Rotinas e entregáveis (semanas 8–10)**
Migração do piloto Apps Script/Sheets para `routine`/`deliverable` no banco central, com evidência obrigatória, score com teto por tarefa crítica e Auditor de Rotinas ativo. Entregável: placar diário por função, com prova e não com declaração.

**Fase 3 — Operação, frota e fiscal (semanas 11–16)**
C01, C05, C06, C07, C14 + agente Fiscal com CT-e/MDF-e/SEFAZ. Entregável: perda operacional visível por filial, veículo e rota.

**Fase 4 — Comercial, compras, RH e compliance (semanas 17–22)**
Margem por cliente/rota, sobrepreço, conflito de interesse, ponto × produtividade, PGR/DDR/documentos. Entra o Caçador de Fraude com quorum de evidências.

**Fase 5 — Autonomia e aprendizado (semanas 23–26)**
Loop de calibração (precisão por detector), varredura ativa das áreas silenciosas, "Pergunte ao Cérebro", multiempresa (Pianetto, AdaptaLog, Calcari).

Marco de valor: no fim da Fase 1 o sistema já deve pagar o próprio custo anual.

---

## 9. Governança e segurança

- **Segregação de funções embutida**: a NÓRIA conhece a matriz RACI e acusa quando a mesma pessoa concede crédito e dá baixa, ou compra e confirma recebimento.
- **Quatro olhos digital**: recomendação de nível 4/5 exige aprovação nomeada e registrada.
- **Imutabilidade**: ledger com hash encadeado; export assinado serve como prova.
- **Anti-perseguição**: achado sobre pessoa nasce anônimo por função; nome só aparece após quorum de evidência e revisão do CEO ou do Controller.
- **LGPD**: dados de ponto e atividade com base legal, minimização e retenção de 24 meses.
- **Contra o próprio cérebro**: auditoria mensal de falsos positivos por detector; detector com precisão < 40% é suspenso automaticamente. Sistema que grita demais é sistema que ninguém escuta.

---

## 10. Riscos e pontos de atenção

| Risco | Impacto | Mitigação |
|---|---|---|
| Alarme excessivo mata a adoção | alto | limite duro de 5 casos/dia no briefing; suspensão automática de detector impreciso |
| Acusação injusta a colaborador | alto | quorum de 2 fontes + Advogado do Diabo + anonimização inicial |
| Custo de LLM sem controle | médio | triagem SQL barata primeiro; orçamento por hipótese; painel de custo por agente |
| Dado do ATUA atrasado gera achado falso | médio | carimbo de frescor; hipótese só fecha com dados dentro da janela de confiança |
| Dependência de uma pessoa (você) | alto | tudo versionado em Git, migrations, DD e runbook; nada em planilha pessoal |
| Uso político do sistema internamente | médio | acesso ao ledger restrito; relatórios de área sem exposição nominal |
| Vazamento entre empresas do grupo | alto | RLS por `empresa_id` obrigatório e teste automatizado de isolamento em CI |

---

## 11. Decisões que dependem de você

1. **Escopo do piloto** — recomendação: Financeiro/Tesouraria (maior valor por real investido, dados mais limpos, resultado mensurável em 30 dias).
2. **Alçadas** — quais níveis de bloqueio o sistema pode recomendar e quem assina cada um.
3. **Política de nome** — a partir de que confiança um achado pode identificar o colaborador.
4. **Nome do sistema** — NÓRIA é sugestão de trabalho.

---

## Anexo A — O que mudou da versão 1.0 para a 2.0

A versão 1.0 deste documento descrevia o sistema sob o nome CORTEX. O nome mudou para **NÓRIA**, e a mudança não foi só de rótulo: o que existia era uma interface com dados em grande parte simulados, e o que existe hoje é um núcleo que roda sozinho contra o banco real do ATUA.

### Renomeação concluída em 05/09/2026

| Item | Antes | Agora |
|---|---|---|
| Sistema | CORTEX | NÓRIA |
| Repositório | `cortex-pianetto` | [`noria-pianetto`](https://github.com/humbertojunior86-maker/noria-pianetto) |
| Servidor (DigitalOcean) | `cortex-pianetto` | `noria-pianetto` (IP 174.138.92.164, inalterado) |
| Caminho no servidor | `/var/www/cortex` | `/var/www/noria` |
| Configuração nginx | `sites-available/cortex` | `sites-available/noria` |
| Parser de OFX | `window.CortexOFX` | `window.NoriaOFX` |
| Chave de implantação | `.secrets/cortex_deploy` | `.secrets/noria_deploy` |
| Utilitários de extração | `cortex/tools/` | `noria/ferramentas/extracao/` |

O IP foi preservado de propósito: renomear o droplet pela API da DigitalOcean mantém o endereço, enquanto recriar a máquina o perderia.

### Diferenças de arquitetura em relação à 1.0

1. **O contrato vinculante passou a ser `ARQUITETURA.md`**, dentro do repositório. Este DD é o documento de intenção; aquele é o que o código obedece.
2. **Banco próprio e isolado** (SQLite com WAL), separado do ATUA. Todo o estado mora nele — por isso o sistema se recupera de uma queda no meio de uma tarefa em vez de perder o trabalho.
3. **Seis camadas de validação** (estrutural, objetiva, documental, especializada, global e operacional), cada afirmação amarrada a uma evidência com origem, trecho e data de consulta.
4. **Acesso ao ATUA é somente leitura, por catálogo de consultas nomeadas.** Não há SQL livre, e consultas pesadas são bloqueadas na janela de faturamento (8h–11h).
5. **Autonomia real:** `trabalhador.py` e `agendador.py` rodam como serviço. As varreduras abrem missões sem ninguém pedir.
6. **Honestidade obrigatória:** quando o sistema não consegue conferir algo, a validação responde `não verificável` com o motivo escrito. Ele não aprova o que não checou, e integração desconectada nunca aparece como conectada na interface.
7. **15 agentes cadastrados, 2 com executor real** (conciliação de tesouraria e carteira de cobrança). Os outros 13 aparecem declarados com a limitação escrita — não fingem funcionar.
