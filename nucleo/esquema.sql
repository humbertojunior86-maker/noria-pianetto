-- NÓRIA — esquema da fonte de verdade
-- SQLite, WAL. Toda tabela de negócio carrega empresa_id.
-- Nada aqui guarda segredo. Nada aqui é apagado: usa-se situação/estado.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- identidade
CREATE TABLE IF NOT EXISTS empresa (
  id            INTEGER PRIMARY KEY,
  nome          TEXT NOT NULL,
  cnpj          TEXT,
  cd_matriz     INTEGER,              -- cd_pessoa_matriz no ATUA
  ativa         INTEGER NOT NULL DEFAULT 1,
  criada_em     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usuario (
  id            INTEGER PRIMARY KEY,
  empresa_id    INTEGER NOT NULL REFERENCES empresa(id),
  nome          TEXT NOT NULL,
  email         TEXT NOT NULL UNIQUE,
  senha_hash    TEXT NOT NULL,
  papel         TEXT NOT NULL,        -- ceo | gestor | operador | leitor
  ativo         INTEGER NOT NULL DEFAULT 1,
  criado_em     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessao (
  token         TEXT PRIMARY KEY,
  usuario_id    INTEGER NOT NULL REFERENCES usuario(id),
  empresa_id    INTEGER NOT NULL REFERENCES empresa(id),
  criada_em     TEXT NOT NULL,
  expira_em     TEXT NOT NULL
);

-- ------------------------------------------------------------------- agentes
-- Um agente é um cadastro versionado. Missão em curso fixa a versão usada.
CREATE TABLE IF NOT EXISTS agente (
  id            TEXT PRIMARY KEY,     -- ex.: tesouraria.conciliador
  nome          TEXT NOT NULL,
  papel         TEXT NOT NULL,
  area          TEXT NOT NULL,
  promessa      TEXT,
  ativo         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS agente_versao (
  id            INTEGER PRIMARY KEY,
  agente_id     TEXT NOT NULL REFERENCES agente(id),
  versao        INTEGER NOT NULL,
  competencias  TEXT NOT NULL,        -- json []
  ferramentas   TEXT NOT NULL,        -- json [] ids de ferramenta
  escopo_dados  TEXT NOT NULL,        -- json {}
  entradas      TEXT NOT NULL,        -- json schema
  saidas        TEXT NOT NULL,        -- json schema
  limites       TEXT NOT NULL,        -- json {}
  criterios     TEXT NOT NULL,        -- json [] qualidade
  situacao      TEXT NOT NULL,        -- habilitado | sem_integracao | desativado
  criada_em     TEXT NOT NULL,
  UNIQUE(agente_id, versao)
);

-- ------------------------------------------------------------------ missões
CREATE TABLE IF NOT EXISTS missao (
  id            INTEGER PRIMARY KEY,
  empresa_id    INTEGER NOT NULL REFERENCES empresa(id),
  objetivo      TEXT NOT NULL,        -- texto original, nunca reescrito
  contexto      TEXT,
  area          TEXT,
  prioridade    TEXT NOT NULL DEFAULT 'normal',
  prazo         TEXT,
  restricoes    TEXT,                 -- json {}
  origem        TEXT NOT NULL,        -- humano | agendador | agente
  solicitante   INTEGER REFERENCES usuario(id),
  estado        TEXT NOT NULL,        -- rascunho|planejada|executando|validando|
                                      -- replanejando|concluida|parcial|bloqueada|cancelada
  plano_vigente INTEGER,              -- plano.id
  resultado     TEXT,                 -- json {} conclusão sustentada
  natureza      TEXT,                 -- analise|proposta|executada|confirmada
  criada_em     TEXT NOT NULL,
  atualizada_em TEXT NOT NULL,
  encerrada_em  TEXT
);
CREATE INDEX IF NOT EXISTS ix_missao_emp ON missao(empresa_id, estado);

-- Critério de conclusão. Verificável por código sempre que possível.
CREATE TABLE IF NOT EXISTS criterio (
  id            INTEGER PRIMARY KEY,
  missao_id     INTEGER NOT NULL REFERENCES missao(id),
  tarefa_chave  TEXT,                 -- a qual tarefa este critério se aplica.
                                      -- NULL = missão inteira (rows antigas).
                                      -- A contraprova tem critério próprio: o
                                      -- verificador da apuração não serve para
                                      -- julgar quem veio contestá-la.
  ordem         INTEGER NOT NULL,
  descricao     TEXT NOT NULL,
  camada        TEXT NOT NULL,        -- estrutural|objetiva|documental|especializada|global|operacional
  verificador   TEXT,                 -- id do verificador de código, se houver
  parametros    TEXT,                 -- json {}
  obrigatorio   INTEGER NOT NULL DEFAULT 1,
  resultado     TEXT,                 -- aprovado|reprovado|nao_verificavel
  justificativa TEXT,
  evidencia_id  INTEGER,
  aferido_em    TEXT
);
CREATE INDEX IF NOT EXISTS ix_criterio_missao ON criterio(missao_id);

-- Plano versionado. Mudança de objetivo gera nova versão, nunca edita a antiga.
CREATE TABLE IF NOT EXISTS plano (
  id            INTEGER PRIMARY KEY,
  missao_id     INTEGER NOT NULL REFERENCES missao(id),
  versao        INTEGER NOT NULL,
  motivo        TEXT NOT NULL,        -- por que este plano existe
  estrategia    TEXT,                 -- direto | agente_unico | multi_agente
  criado_em     TEXT NOT NULL,
  UNIQUE(missao_id, versao)
);

CREATE TABLE IF NOT EXISTS tarefa (
  id             INTEGER PRIMARY KEY,
  empresa_id     INTEGER NOT NULL REFERENCES empresa(id),
  missao_id      INTEGER NOT NULL REFERENCES missao(id),
  plano_id       INTEGER NOT NULL REFERENCES plano(id),
  chave          TEXT NOT NULL,       -- estável entre versões de plano
  titulo         TEXT NOT NULL,
  objetivo       TEXT NOT NULL,
  agente_id      TEXT REFERENCES agente(id),
  agente_versao  INTEGER,             -- congelada no despacho
  entradas       TEXT NOT NULL,       -- json {}
  fontes         TEXT,                -- json []
  acoes_permitidas TEXT NOT NULL,     -- json [] nada fora disso executa
  formato_entrega TEXT NOT NULL,
  saidas_esperadas TEXT,              -- json {} campos que a entrega deve trazer
  prazo          TEXT,
  orcamento_centavos INTEGER NOT NULL DEFAULT 0,
  max_tentativas INTEGER NOT NULL DEFAULT 2,
  tentativas     INTEGER NOT NULL DEFAULT 0,
  estado         TEXT NOT NULL,       -- pendente|despachada|executando|entregue|
                                      -- aprovada|reprovada|nao_verificavel|falha|cancelada|substituida
  criada_em      TEXT NOT NULL,
  atualizada_em  TEXT NOT NULL,
  UNIQUE(plano_id, chave)
);
CREATE INDEX IF NOT EXISTS ix_tarefa_estado ON tarefa(estado, missao_id);

CREATE TABLE IF NOT EXISTS dependencia (
  tarefa_id     INTEGER NOT NULL REFERENCES tarefa(id),
  depende_de    INTEGER NOT NULL REFERENCES tarefa(id),
  tipo          TEXT NOT NULL DEFAULT 'ordem',  -- ordem | dado
  PRIMARY KEY (tarefa_id, depende_de)
);

-- ------------------------------------------------------------------ entregas
CREATE TABLE IF NOT EXISTS entrega (
  id             INTEGER PRIMARY KEY,
  empresa_id     INTEGER NOT NULL REFERENCES empresa(id),
  missao_id      INTEGER NOT NULL REFERENCES missao(id),
  tarefa_id      INTEGER NOT NULL REFERENCES tarefa(id),
  tentativa      INTEGER NOT NULL,
  -- declaração do executor. NÃO é aprovação.
  status_declarado TEXT NOT NULL,     -- concluida | parcial | bloqueada
  resumo         TEXT NOT NULL,
  resultado      TEXT NOT NULL,       -- json {} estruturado
  incertezas     TEXT,                -- json []
  conflitos      TEXT,                -- json []
  pendencias     TEXT,                -- json []
  complemento    TEXT,                -- json {} o que o agente pediu de volta
  criada_em      TEXT NOT NULL,
  UNIQUE(tarefa_id, tentativa)
);

-- Uma afirmação da entrega. É AQUI que mora a rastreabilidade.
CREATE TABLE IF NOT EXISTS afirmacao (
  id            INTEGER PRIMARY KEY,
  entrega_id    INTEGER NOT NULL REFERENCES entrega(id),
  texto         TEXT NOT NULL,
  natureza      TEXT NOT NULL,        -- fato | hipotese | contradicao | ausencia
  evidencia_id  INTEGER,              -- NULL => vira hipótese na validação
  verificada    TEXT                  -- aprovado|reprovado|nao_verificavel
);

CREATE TABLE IF NOT EXISTS evidencia (
  id            INTEGER PRIMARY KEY,
  empresa_id    INTEGER NOT NULL REFERENCES empresa(id),
  missao_id     INTEGER REFERENCES missao(id),
  tipo          TEXT NOT NULL,        -- consulta | documento | arquivo | calculo | externo
  origem        TEXT NOT NULL,        -- ex.: atua:public.titulo | doc:412 | ofx:BB-3066
  referencia    TEXT NOT NULL,        -- sql, id do doc, caminho, expressão
  trecho        TEXT,                 -- o pedaço que sustenta a afirmação
  conteudo_hash TEXT,
  consultada_em TEXT NOT NULL,        -- data da consulta, obrigatória
  raiz          TEXT,                 -- origem-raiz p/ não contar repetição como confirmação
  criada_em     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_evid_missao ON evidencia(missao_id);

CREATE TABLE IF NOT EXISTS artefato (
  id            INTEGER PRIMARY KEY,
  empresa_id    INTEGER NOT NULL REFERENCES empresa(id),
  missao_id     INTEGER NOT NULL REFERENCES missao(id),
  entrega_id    INTEGER REFERENCES entrega(id),
  nome          TEXT NOT NULL,
  formato       TEXT NOT NULL,        -- md | csv | json | pdf
  caminho       TEXT NOT NULL,        -- precisa existir para aparecer
  bytes         INTEGER,
  versao        INTEGER NOT NULL DEFAULT 1,
  criado_em     TEXT NOT NULL
);

-- ----------------------------------------------------------------- validação
CREATE TABLE IF NOT EXISTS validacao (
  id            INTEGER PRIMARY KEY,
  empresa_id    INTEGER NOT NULL REFERENCES empresa(id),
  missao_id     INTEGER NOT NULL REFERENCES missao(id),
  entrega_id    INTEGER REFERENCES entrega(id),
  criterio_id   INTEGER REFERENCES criterio(id),
  camada        TEXT NOT NULL,
  revisor       TEXT NOT NULL,        -- codigo:<verificador> | agente:<id>
  resultado     TEXT NOT NULL,        -- aprovado|reprovado|nao_verificavel
  justificativa TEXT NOT NULL,
  evidencia_id  INTEGER REFERENCES evidencia(id),
  independente  INTEGER NOT NULL DEFAULT 0,  -- recomputou por conta própria?
  criada_em     TEXT NOT NULL
);

-- --------------------------------------------------------------- ferramentas
CREATE TABLE IF NOT EXISTS execucao_ferramenta (
  id            INTEGER PRIMARY KEY,
  empresa_id    INTEGER NOT NULL REFERENCES empresa(id),
  missao_id     INTEGER REFERENCES missao(id),
  tarefa_id     INTEGER REFERENCES tarefa(id),
  ferramenta    TEXT NOT NULL,
  operacao      TEXT NOT NULL,
  escreve       INTEGER NOT NULL DEFAULT 0,
  entrada       TEXT NOT NULL,        -- json {}
  chave_idem    TEXT,
  estado        TEXT NOT NULL,        -- ok | erro | timeout | ambiguo
  saida_resumo  TEXT,
  linhas        INTEGER,
  erro          TEXT,
  ms            INTEGER,
  iniciada_em   TEXT NOT NULL,
  terminada_em  TEXT
);
CREATE INDEX IF NOT EXISTS ix_exec_idem ON execucao_ferramenta(chave_idem);

-- ------------------------------------------------------------ ações externas
CREATE TABLE IF NOT EXISTS acao_externa (
  id            INTEGER PRIMARY KEY,
  empresa_id    INTEGER NOT NULL REFERENCES empresa(id),
  missao_id     INTEGER NOT NULL REFERENCES missao(id),
  tarefa_id     INTEGER REFERENCES tarefa(id),
  tipo          TEXT NOT NULL,        -- email | mensagem | pagamento | escrita_erp | publicacao
  destino       TEXT NOT NULL,
  conteudo      TEXT NOT NULL,
  valor_centavos INTEGER,
  impacto       TEXT,
  hash_conteudo TEXT NOT NULL,        -- muda => aprovação antiga perde validade
  exige_aprovacao INTEGER NOT NULL DEFAULT 1,
  estado        TEXT NOT NULL,        -- proposta|aguardando|aprovada|rejeitada|
                                      -- executada|confirmada|ambigua|cancelada
  chave_idem    TEXT,
  efeito_conferido TEXT,              -- json {} o que se viu no destino
  criada_em     TEXT NOT NULL,
  executada_em  TEXT,
  confirmada_em TEXT
);

CREATE TABLE IF NOT EXISTS aprovacao (
  id            INTEGER PRIMARY KEY,
  empresa_id    INTEGER NOT NULL REFERENCES empresa(id),
  acao_id       INTEGER NOT NULL REFERENCES acao_externa(id),
  hash_aprovado TEXT NOT NULL,        -- congela a versão aprovada
  decisao       TEXT,                 -- aprovar | ajustar | rejeitar
  decidida_por  INTEGER REFERENCES usuario(id),
  observacao    TEXT,
  valida_ate    TEXT,
  criada_em     TEXT NOT NULL,
  decidida_em   TEXT
);

-- Alçada: quem pode aprovar o quê, por valor. Sem isto nada de impacto executa.
CREATE TABLE IF NOT EXISTS alcada (
  id            INTEGER PRIMARY KEY,
  empresa_id    INTEGER NOT NULL REFERENCES empresa(id),
  tipo_acao     TEXT NOT NULL,
  ate_centavos  INTEGER,              -- NULL = sem teto
  papel_minimo  TEXT NOT NULL,
  automatica    INTEGER NOT NULL DEFAULT 0
);

-- ------------------------------------------------------------- conhecimento
CREATE TABLE IF NOT EXISTS documento (
  id            INTEGER PRIMARY KEY,
  empresa_id    INTEGER NOT NULL REFERENCES empresa(id),
  titulo        TEXT NOT NULL,
  assunto       TEXT NOT NULL,        -- taxonomia editável
  origem        TEXT NOT NULL,
  caminho       TEXT,
  mime          TEXT,
  nivel_acesso  TEXT NOT NULL DEFAULT 'interno',
  situacao      TEXT NOT NULL,        -- confirmado|hipotese|contestado|substituido
  validade      TEXT,
  versao        INTEGER NOT NULL DEFAULT 1,
  substitui     INTEGER REFERENCES documento(id),
  data_doc      TEXT,
  ingerido_em   TEXT NOT NULL,
  processado    TEXT NOT NULL DEFAULT 'pendente'  -- pendente|extraindo|indexado|erro
);

CREATE TABLE IF NOT EXISTS trecho (
  id            INTEGER PRIMARY KEY,
  documento_id  INTEGER NOT NULL REFERENCES documento(id),
  ordem         INTEGER NOT NULL,
  texto         TEXT NOT NULL,        -- texto original preservado
  pagina        INTEGER,
  hash          TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS trecho_fts USING fts5(
  texto, content='trecho', content_rowid='id', tokenize="unicode61 remove_diacritics 2"
);

CREATE TABLE IF NOT EXISTS aprendizado (
  id            INTEGER PRIMARY KEY,
  empresa_id    INTEGER NOT NULL REFERENCES empresa(id),
  missao_id     INTEGER REFERENCES missao(id),
  enunciado     TEXT NOT NULL,
  origem        TEXT NOT NULL,
  escopo        TEXT NOT NULL,
  validade      TEXT,
  estado        TEXT NOT NULL DEFAULT 'proposto',  -- proposto|aprovado|rejeitado|revogado
  aprovado_por  INTEGER REFERENCES usuario(id),
  criado_em     TEXT NOT NULL,
  decidido_em   TEXT
);

-- ------------------------------------------------------------- integrações
CREATE TABLE IF NOT EXISTS integracao (
  id            TEXT PRIMARY KEY,
  empresa_id    INTEGER NOT NULL REFERENCES empresa(id),
  nome          TEXT NOT NULL,
  tipo          TEXT NOT NULL,
  permissoes    TEXT NOT NULL,        -- json []
  escreve       INTEGER NOT NULL DEFAULT 0,
  estado        TEXT NOT NULL,        -- conectada|desconectada|erro|nao_configurada
  ultimo_teste  TEXT,
  ultimo_erro   TEXT,
  ambiente      TEXT NOT NULL DEFAULT 'producao'  -- producao | demonstracao
);

-- -------------------------------------------------------- limites e consumo
CREATE TABLE IF NOT EXISTS limite (
  id            INTEGER PRIMARY KEY,
  empresa_id    INTEGER NOT NULL REFERENCES empresa(id),
  escopo        TEXT NOT NULL,        -- missao | tarefa | global_dia
  chave         TEXT NOT NULL,        -- tempo_s|custo_centavos|tokens|max_tarefas|
                                      -- concorrencia|max_tentativas|max_replanejamentos
  valor         INTEGER NOT NULL,
  UNIQUE(empresa_id, escopo, chave)
);

-- Reserva ANTES do despacho, para concorrência não estourar o teto.
CREATE TABLE IF NOT EXISTS consumo (
  id            INTEGER PRIMARY KEY,
  empresa_id    INTEGER NOT NULL REFERENCES empresa(id),
  missao_id     INTEGER REFERENCES missao(id),
  tarefa_id     INTEGER REFERENCES tarefa(id),
  tipo          TEXT NOT NULL,        -- reserva | realizado | estorno
  custo_centavos INTEGER NOT NULL DEFAULT 0,
  tokens        INTEGER NOT NULL DEFAULT 0,
  ms            INTEGER NOT NULL DEFAULT 0,
  criado_em     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_consumo_missao ON consumo(missao_id, tipo);

-- Detecção de ciclo improdutivo: mesma assinatura repetida sem ganho.
CREATE TABLE IF NOT EXISTS assinatura_exec (
  id            INTEGER PRIMARY KEY,
  missao_id     INTEGER NOT NULL REFERENCES missao(id),
  assinatura    TEXT NOT NULL,
  vezes         INTEGER NOT NULL DEFAULT 1,
  ultimo_hash_saida TEXT,
  atualizada_em TEXT NOT NULL,
  UNIQUE(missao_id, assinatura)
);

-- ------------------------------------------------------------------- eventos
-- Append only. É a trilha de auditoria e o fluxo que a interface lê.
CREATE TABLE IF NOT EXISTS evento (
  id            INTEGER PRIMARY KEY,
  empresa_id    INTEGER NOT NULL REFERENCES empresa(id),
  missao_id     INTEGER REFERENCES missao(id),
  tarefa_id     INTEGER REFERENCES tarefa(id),
  tipo          TEXT NOT NULL,
  ator          TEXT NOT NULL,        -- nucleo | agente:<id> | usuario:<id> | agendador
  de_estado     TEXT,
  para_estado   TEXT,
  texto         TEXT NOT NULL,
  dados         TEXT,                 -- json {}
  criado_em     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_evento_emp ON evento(empresa_id, id DESC);

-- ------------------------------------------------------------------ marcador
-- Memória curta da sentinela: guarda a última leitura de um indicador para que
-- a próxima possa dizer o que MUDOU. Sem isso a vigilância repete o mesmo
-- número de hora em hora e vira ruído em vez de sinal.
CREATE TABLE IF NOT EXISTS marcador (
  chave         TEXT PRIMARY KEY,
  valor         TEXT NOT NULL,        -- json
  atualizado_em TEXT NOT NULL
);

-- -------------------------------------------------------------------- aviso
-- Fila de avisos que a NÓRIA quer levar para fora — hoje por e-mail. Ela é
-- do sistema, não do carteiro: o cérebro decide o que merece sair daqui e
-- registra; quem entrega apenas marca o que já saiu. Trocar o Outlook por
-- WhatsApp amanhã não muda uma linha do que está acima desta tabela.
-- A chave existe para o mesmo achado não virar e-mail todo dia: enquanto o
-- número não muda, é o mesmo aviso. Quando muda, é outro, e sai de novo.
CREATE TABLE IF NOT EXISTS aviso (
  id            INTEGER PRIMARY KEY,
  empresa_id    INTEGER NOT NULL REFERENCES empresa(id),
  entrega_id    INTEGER REFERENCES entrega(id),
  missao_id     INTEGER REFERENCES missao(id),
  agente_id     TEXT,
  agente_nome   TEXT,
  especie       TEXT NOT NULL,   -- dinheiro_parado | vermelho | risco | divergencia | travado
  gravidade     TEXT NOT NULL,   -- alta | media
  titulo        TEXT NOT NULL,
  texto         TEXT NOT NULL,
  valor         REAL,
  quantidade    INTEGER,
  chave         TEXT NOT NULL UNIQUE,
  estado        TEXT NOT NULL DEFAULT 'pendente',  -- pendente | entregue | dispensado
  canal         TEXT,
  referencia    TEXT,
  criado_em     TEXT NOT NULL,
  entregue_em   TEXT
);
CREATE INDEX IF NOT EXISTS ix_aviso_fila ON aviso(empresa_id, estado, id DESC);

-- ------------------------------------------------------------------ demanda
-- O que chegou de fora pedindo resposta: e-mail de cliente, cobrança da
-- equipe, aviso de outro sistema. A NÓRIA guarda o pedido, não a caixa de
-- e-mail — corpo inteiro fica no Outlook, aqui mora o suficiente para o
-- cérebro decidir se aquilo vira missão.
-- `externo_id` é o id da mensagem na origem: é ele que impede a mesma
-- mensagem de entrar duas vezes quando a ponte roda de novo.
CREATE TABLE IF NOT EXISTS demanda (
  id            INTEGER PRIMARY KEY,
  empresa_id    INTEGER NOT NULL REFERENCES empresa(id),
  canal         TEXT NOT NULL,      -- outlook | whatsapp | manual
  externo_id    TEXT NOT NULL,
  conversa_id   TEXT,
  de            TEXT,
  para          TEXT,
  assunto       TEXT,
  trecho        TEXT,
  recebida_em   TEXT,
  classe        TEXT NOT NULL,      -- cliente | equipe | sistema | ruido
  assunto_operacional TEXT,         -- do que trata, quando dá para dizer
  quem_responde TEXT,               -- área da casa que deve responder
  prazo         TEXT,
  estado        TEXT NOT NULL DEFAULT 'aberta',  -- aberta | em_missao | respondida | dispensada
  missao_id     INTEGER REFERENCES missao(id),
  link          TEXT,
  criada_em     TEXT NOT NULL,
  UNIQUE(canal, externo_id)
);
CREATE INDEX IF NOT EXISTS ix_demanda_fila ON demanda(empresa_id, estado, recebida_em DESC);

-- -------------------------------------------------------------------- vigia
-- Um vigia é um agente que a NÓRIA cria SOZINHA, e ele é dado — nunca código.
-- O motor que roda vigia está em nucleo/vigia.py e é imutável em produção;
-- aqui fica só a pergunta, a consulta e o limiar. Foi assim que se deu a ela
-- o poder de criar agentes sem lhe dar o poder de escrever no sistema: se um
-- vigia estiver errado, some apagando uma linha, não fazendo um deploy.
--
-- `estado` conta a vida dele: nasce em 'observacao' (roda, apura e registra,
-- mas não toca o sino do alerta crítico), vira 'ativo' quando o CEO aprova,
-- cai para 'suspenso' sozinho depois de três falhas seguidas e vai para
-- 'aposentado' quando passa trinta dias sem achar nada.
CREATE TABLE IF NOT EXISTS vigia (
  id            INTEGER PRIMARY KEY,
  empresa_id    INTEGER NOT NULL REFERENCES empresa(id),
  nome          TEXT NOT NULL,
  area          TEXT NOT NULL,
  foco          TEXT NOT NULL DEFAULT 'margem',
  pergunta      TEXT NOT NULL,
  motivo        TEXT NOT NULL,          -- por que ele precisa existir
  consulta      TEXT NOT NULL,          -- SELECT conferido pela guarda
  campo_valor   TEXT,                   -- coluna que carrega o dinheiro
  campo_rotulo  TEXT,                   -- coluna que nomeia a linha
  limiar        REAL NOT NULL DEFAULT 0,
  especie       TEXT NOT NULL DEFAULT 'margem',
  gravidade     TEXT NOT NULL DEFAULT 'alta',
  cadencia      TEXT NOT NULL DEFAULT 'diaria',
  estado        TEXT NOT NULL DEFAULT 'observacao',
  criado_por    TEXT NOT NULL DEFAULT 'pensamento',
  hipotese_id   INTEGER REFERENCES hipotese(id),
  execucoes     INTEGER NOT NULL DEFAULT 0,
  falhas        INTEGER NOT NULL DEFAULT 0,
  falhas_seguidas INTEGER NOT NULL DEFAULT 0,
  achados       INTEGER NOT NULL DEFAULT 0,
  ultimo_achado TEXT,
  ultima_execucao TEXT,
  aprovado_em   TEXT,
  aprovado_por  TEXT,
  criada_em     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_vigia_fila ON vigia(empresa_id, estado, id DESC);

CREATE TABLE IF NOT EXISTS vigia_execucao (
  id            INTEGER PRIMARY KEY,
  vigia_id      INTEGER NOT NULL REFERENCES vigia(id),
  quando        TEXT NOT NULL,
  ok            INTEGER NOT NULL,
  linhas        INTEGER,
  valor         REAL,
  achou         INTEGER NOT NULL DEFAULT 0,
  aviso_id      INTEGER REFERENCES aviso(id),
  erro          TEXT,
  amostra       TEXT                     -- json das primeiras linhas
);
CREATE INDEX IF NOT EXISTS ix_vigia_exec ON vigia_execucao(vigia_id, id DESC);

-- --------------------------------------------------------------- entregável
-- Informação nova que ninguém pediu. A NÓRIA monta quando descobre algo que
-- merece existir como documento, e publica no painel interno. Sair para fora
-- da casa — cliente, banco, órgão — exige aprovação de gente.
CREATE TABLE IF NOT EXISTS entregavel (
  id            INTEGER PRIMARY KEY,
  empresa_id    INTEGER NOT NULL REFERENCES empresa(id),
  titulo        TEXT NOT NULL,
  motivo        TEXT NOT NULL,
  foco          TEXT NOT NULL DEFAULT 'margem',
  origem        TEXT NOT NULL,          -- vigia:<id> | hipotese:<id> | missao:<id>
  secoes        TEXT NOT NULL,          -- json [{titulo, texto, linhas[]}]
  destino       TEXT NOT NULL DEFAULT 'interno',  -- interno | externo
  estado        TEXT NOT NULL DEFAULT 'publicado', -- publicado | aprovado | arquivado
  criado_em     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_entregavel ON entregavel(empresa_id, id DESC);
