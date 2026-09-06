-- Córtex de raciocínio — tabelas laterais (DD-002).
-- Nenhuma tabela existente da NÓRIA depende destas. Se o córtex sumir do
-- disco, o sistema sobe igual.

CREATE TABLE IF NOT EXISTS hipotese (
  id                INTEGER PRIMARY KEY,
  empresa_id        INTEGER NOT NULL,
  pergunta          TEXT NOT NULL,
  motivo            TEXT NOT NULL,
  origem            TEXT NOT NULL,
  aposta            TEXT,
  estado            TEXT NOT NULL DEFAULT 'levantada',
  -- levantada | em_prova | confirmada | derrubada | inconclusiva | rejeitada
  leitura           TEXT,
  chave             TEXT NOT NULL,
  criada_em         TEXT NOT NULL,
  decidida_em       TEXT
);
CREATE INDEX IF NOT EXISTS ix_hip_estado ON hipotese(empresa_id, estado, id DESC);

CREATE TABLE IF NOT EXISTS consulta_proposta (
  id             INTEGER PRIMARY KEY,
  hipotese_id    INTEGER NOT NULL REFERENCES hipotese(id),
  porta          TEXT NOT NULL,
  sql            TEXT NOT NULL,
  grao           TEXT NOT NULL,
  papel          TEXT NOT NULL DEFAULT 'principal',   -- principal | contraprova
  recusa         TEXT,
  resultado_json TEXT,
  linhas         INTEGER,
  erro           TEXT,
  rodou_em       TEXT,
  criada_em      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_cons_hip ON consulta_proposta(hipotese_id);

CREATE TABLE IF NOT EXISTS raciocinio (
  id           INTEGER PRIMARY KEY,
  hipotese_id  INTEGER REFERENCES hipotese(id),
  passo        INTEGER NOT NULL,
  texto        TEXT NOT NULL,
  criado_em    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS uso_ia (
  id              INTEGER PRIMARY KEY,
  tarefa          TEXT NOT NULL,
  modelo          TEXT NOT NULL,
  entrada_hash    TEXT NOT NULL,
  tokens_entrada  INTEGER,
  tokens_saida    INTEGER,
  custo_estimado  REAL,
  duracao_ms      INTEGER,
  sucesso         INTEGER NOT NULL,
  erro            TEXT,
  criado_em       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_uso_dia ON uso_ia(criado_em);
