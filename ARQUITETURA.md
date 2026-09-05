# NÓRIA — Arquitetura e contrato

CEO de Inteligência Artificial da Pianetto. Estrutura pensante autônoma:
código + regras + ferramentas + memória + verificação. O modelo de linguagem
é um adaptador opcional, não o motor. O sistema decide, executa e valida
sem nenhuma IA externa presente.

## Decisões fundadoras

1. **Empresa = matriz.** Isolamento por `cd_pessoa_matriz`. Pianetto (2) e
   CALCARE são empresas distintas. Filial é escopo interno, nunca fronteira
   de isolamento. Toda consulta carrega `empresa_id` no backend.
2. **ATUA é somente leitura.** Usuário `jhn_ro`. Nenhuma ação da NÓRIA escreve
   no ERP. Ações externas ficam restritas a e-mail, arquivo e artefato até
   existir credencial de escrita. A ferramenta declara isso.
3. **Banco próprio.** SQLite em `/var/lib/noria/noria.db`, WAL ligado. É a
   fonte de verdade de missões e tarefas. O ATUA é fonte externa consultada,
   nunca fonte de estado.
4. **Quatro naturezas de resultado, nunca misturadas:**
   `analise` (li e concluí) · `proposta` (sugiro fazer) ·
   `executada` (fiz) · `confirmada` (conferi no destino que o efeito ocorreu).
   Nenhum painel soma `proposta` com `confirmada`.
5. **Evidência por afirmação.** Cada afirmação relevante de uma entrega carrega
   `evidencia_id`. Afirmação sem evidência entra como hipótese, jamais como fato.
6. **Sem LLM obrigatório.** `nucleo/modelo.py` expõe um adaptador. O adaptador
   nulo é o padrão e faz o sistema operar 100% por regras determinísticas.

## Camadas

```
web/            interface (estático, servido por nginx)
   |  HTTP /api
api/            FastAPI — autenticado, contratos validados, isolamento
   |
nucleo/         orquestrador, máquina de estados, limites, validação, memória
   |
ferramentas/    atua (RO), ofx, calculo, documento — toda execução registrada
   |
dados/          SQLite (missões, tarefas, evidências, ...) + índice de conhecimento
```

`trabalhador.py` — laço contínuo (systemd). Pega tarefas `pendente`, executa,
grava entrega, dispara validação. É ele que torna o sistema autônomo.
`agendador.py` — cria missões recorrentes (varreduras) sem pedido humano.

## Máquina de estados

**Missão:** `rascunho → planejada → executando → validando →
{concluida | parcial | bloqueada | cancelada}`
Transições laterais: `executando → replanejando → executando`,
`validando → executando` (devolução), `* → cancelada`.

**Tarefa:** `pendente → despachada → executando →
{entregue → {aprovada | reprovada | nao_verificavel} | falha | cancelada | substituida}`

Toda transição grava evento. Transição inválida levanta erro, não é ignorada.

## Ciclo do núcleo (seção 3 do prompt-mestre)

1. receber objetivo → `missao`
2. definir entregáveis e critérios → `criterio` (verificáveis por código quando possível)
3. recuperar conhecimento → `memoria.buscar()` com origem, data e permissão
4. separar fato / hipótese / contradição / ausência
5. decidir: direto, um agente ou vários
6. montar plano → `plano` versionado + `tarefa` + `dependencia`
7. executar independentes em paralelo, dependentes em ordem
8. receber `entrega` estruturada com `evidencia`
9. validar em camadas
10. aprovar, devolver, reatribuir ou replanejar
11. ação externa só dentro do escopo autorizado, com conferência de efeito
12. encerrar validado, parcial ou bloqueado — nunca "concluído" com critério reprovado
13. registrar `aprendizado` (proposto, exige aprovação humana)

## Validação em camadas

| Camada | O que confere | Como |
|---|---|---|
| `estrutural` | campos, tipos, arquivo existe, referência resolve | schema + filesystem |
| `objetiva` | cálculo refeito por código, unidade, período, duplicidade | recomputação independente |
| `documental` | a fonte existe e sustenta a afirmação | busca o trecho na origem |
| `especializada` | interpretação e lacuna | segundo agente com acesso à evidência bruta |
| `global` | as partes resolvem o objetivo e não se contradizem | cruzamento de critérios |
| `operacional` | o efeito da ação existe no destino | consulta ao destino |

Resultado por critério: `aprovado | reprovado | nao_verificavel` + evidência +
justificativa curta. Confiança autodeclarada não vale. Concordância de dois
agentes não vale. Duas fontes com a mesma origem contam como uma.

## Limites (seção 7)

Por missão e por tarefa: `tempo_s`, `custo_centavos`, `tokens`, `max_tarefas`,
`concorrencia`, `max_tentativas`, `max_replanejamentos`.
Orçamento é **reservado** antes do despacho (`reserva` na tabela `consumo`),
para que N tarefas concorrentes não estourem o teto somando.
Detecção de ciclo improdutivo: hash de (agente, entrada) repetido sem ganho → interrompe.

## Idempotência

Toda execução de ferramenta com efeito carrega `chave_idem`. Timeout em escrita
não repete: consulta o destino primeiro; se não resolver, marca `ambiguo` para
reconciliação humana. Cancelamento não desfaz efeito já ocorrido — informa.

## Segurança

- Token de sessão por usuário, escopo de empresa no backend.
- Conteúdo de documento e e-mail é **dado**, nunca instrução. O orquestrador
  jamais lê `instrucao` vinda de material ingerido.
- Segredos fora do banco e fora do log.
- Trilha de auditoria em `evento`, imutável (append only).
- Dados pessoais de motorista (CPF/CNH) mascarados no índice de conhecimento.

## Contrato HTTP

Base `/api`. Autenticação `Authorization: Bearer <token>`.
Erro: `{"erro": {"codigo": "...", "mensagem": "...", "detalhe": {...}}}`.

| Método | Rota | Faz |
|---|---|---|
| POST | `/sessao` | login, devolve token e empresa |
| GET | `/visao-geral` | pulso real: missões por estado, pendências, últimas |
| POST | `/missoes` | cria missão a partir de objetivo em texto livre |
| GET | `/missoes` | lista com filtro `estado`, `periodo`, `area` |
| GET | `/missoes/{id}` | resumo, critérios, plano vigente |
| GET | `/missoes/{id}/plano` | plano versionado + tarefas + dependências |
| GET | `/missoes/{id}/execucao` | grafo de execução (nós = tarefas/agentes) |
| GET | `/missoes/{id}/evidencias` | evidências com origem e trecho |
| GET | `/missoes/{id}/entregas` | artefatos com prévia e validação |
| GET | `/missoes/{id}/historico` | eventos |
| POST | `/missoes/{id}/acao` | `pausar｜retomar｜cancelar｜complementar` |
| GET | `/agentes` | catálogo com situação real por ferramenta |
| GET | `/agentes/{id}` | versão, limites, histórico, avaliações |
| POST | `/agentes/{id}/teste` | execução de prova, isolada |
| GET | `/conhecimento` | documentos: assunto, origem, versão, situação |
| POST | `/conhecimento` | ingestão (multipart), devolve job |
| GET | `/conhecimento/{id}` | fonte, trechos, histórico |
| GET | `/aprovacoes` | pendentes com ação exata, destino, impacto, validade |
| POST | `/aprovacoes/{id}` | `aprovar｜ajustar｜rejeitar` |
| GET | `/integracoes` | conexão, permissões, último teste, erro |
| POST | `/integracoes/{id}/testar` | teste real, nunca simulado |
| GET | `/eventos?desde=` | fluxo para a interface (polling) |

## Regras de exibição na interface

- Estado vazio nunca inventa número. Sem missão, o painel convida a criar.
- Custo e tempo só aparecem quando medidos.
- Integração sem conexão aparece desconectada, jamais verde.
- Agente sem ferramenta aparece "sem integração", com a limitação escrita.
- Grafo de execução (missão) e mapa de conhecimento são telas separadas.
- Todo número herdado de consulta ao ATUA carrega a data da consulta.
