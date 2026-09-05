/* Formatação pt-BR. Nada de número decorativo: se o valor não vier, sai "—". */

const NADA = '—';

export function numero(v, casas = 0) {
  if (v === null || v === undefined || v === '' || Number.isNaN(Number(v))) return NADA;
  return Number(v).toLocaleString('pt-BR', {
    minimumFractionDigits: casas, maximumFractionDigits: casas,
  });
}

export function dinheiro(v) {
  if (v === null || v === undefined || v === '' || Number.isNaN(Number(v))) return NADA;
  return `R$ ${Number(v).toLocaleString('pt-BR', {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  })}`;
}

export function porcento(v, casas = 1) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return NADA;
  return `${Number(v * 100).toLocaleString('pt-BR', {
    minimumFractionDigits: casas, maximumFractionDigits: casas,
  })}%`;
}

function partes(iso) {
  if (!iso) return null;
  const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/);
  if (!m) return null;
  return { a: m[1], me: m[2], d: m[3], h: m[4], mi: m[5] };
}

/** 10/08/2026 */
export function data(iso) {
  const p = partes(iso);
  return p ? `${p.d}/${p.me}/${p.a}` : NADA;
}

/** 10/08/2026 13:11 */
export function dataHora(iso) {
  const p = partes(iso);
  if (!p) return NADA;
  return p.h ? `${p.d}/${p.me}/${p.a} ${p.h}:${p.mi}` : `${p.d}/${p.me}/${p.a}`;
}

/** 13:11 */
export function hora(iso) {
  const p = partes(iso);
  return p && p.h ? `${p.h}:${p.mi}` : NADA;
}

export function duracao(ms) {
  if (ms === null || ms === undefined || Number.isNaN(Number(ms))) return NADA;
  const n = Number(ms);
  if (n < 1000) return `${numero(n)} ms`;
  if (n < 60000) return `${numero(n / 1000, 1)} s`;
  return `${numero(n / 60000, 1)} min`;
}

export function bytes(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return NADA;
  const v = Number(n);
  if (v < 1024) return `${numero(v)} B`;
  if (v < 1024 * 1024) return `${numero(v / 1024, 1)} kB`;
  return `${numero(v / (1024 * 1024), 1)} MB`;
}

/** O núcleo grava algumas frases com dinheiro no padrão en-US
 *  ("R$ 1,964,842.57"). O valor é o mesmo; aqui só o formato é corrigido
 *  para o padrão brasileiro na hora de exibir. */
export function textoBr(t) {
  if (!t) return '';
  return String(t).replace(
    /R\$\s?(\d{1,3}(?:,\d{3})+)\.(\d{2})/g,
    (_, inteiro, cent) => `R$ ${inteiro.replace(/,/g, '.')},${cent}`,
  );
}

/* ------------------------------------------------------------- rótulos ---- */
const ESTADO_MISSAO = {
  rascunho: ['Rascunho', 'neutra'],
  planejada: ['Planejada', 'acento'],
  executando: ['Executando', 'acento'],
  validando: ['Validando', 'atencao'],
  replanejando: ['Replanejando', 'atencao'],
  concluida: ['Concluída', 'ok'],
  parcial: ['Parcial', 'atencao'],
  bloqueada: ['Bloqueada', 'erro'],
  cancelada: ['Cancelada', 'neutra'],
};

const ESTADO_TAREFA = {
  pendente: ['Pendente', 'neutra'],
  despachada: ['Despachada', 'acento'],
  executando: ['Executando', 'acento'],
  entregue: ['Entregue', 'acento'],
  aprovada: ['Aprovada', 'ok'],
  reprovada: ['Reprovada', 'erro'],
  nao_verificavel: ['Não verificável', 'atencao'],
  falha: ['Falha', 'erro'],
  cancelada: ['Cancelada', 'neutra'],
  substituida: ['Substituída', 'neutra'],
};

const RESULTADO = {
  aprovado: ['Aprovado', 'ok'],
  reprovado: ['Reprovado', 'erro'],
  nao_verificavel: ['Não verificável', 'atencao'],
  pendente: ['Não aferido', 'neutra'],
};

const INTEGRACAO = {
  conectada: ['Conectada', 'ok'],
  erro: ['Com erro', 'erro'],
  nao_configurada: ['Não configurada', 'atencao'],
  desconectada: ['Desconectada', 'erro'],
};

const NATUREZA = {
  analise: ['Análise', 'neutra'],
  proposta: ['Proposta', 'atencao'],
  executada: ['Executada', 'acento'],
  confirmada: ['Confirmada', 'ok'],
  fato: ['Fato', 'ok'],
  hipotese: ['Hipótese', 'atencao'],
  contradicao: ['Contradição', 'erro'],
  ausencia: ['Ausência', 'atencao'],
  // Dois caminhos do banco discordaram sobre o mesmo fato. Não é erro do
  // sistema: é o momento em que ele para e chama gente.
  contestada: ['Contestada', 'erro'],
};

const CAMADA = {
  estrutural: 'Estrutural',
  objetiva: 'Objetiva',
  documental: 'Documental',
  especializada: 'Especializada',
  global: 'Global',
  operacional: 'Operacional',
};

const CAMADA_O_QUE = {
  estrutural: 'campos, tipos, arquivo existe, referência resolve',
  objetiva: 'cálculo refeito por código, unidade, período, duplicidade',
  documental: 'a fonte existe e sustenta a afirmação',
  especializada: 'interpretação e lacuna, por um segundo agente',
  global: 'as partes resolvem o objetivo e não se contradizem',
  operacional: 'o efeito da ação existe no destino',
};

function achar(mapa, chave, cru) {
  const v = mapa[chave];
  if (v) return { texto: v[0], tom: v[1] };
  return { texto: cru || chave || NADA, tom: 'neutra' };
}

export const estadoMissao = (e) => achar(ESTADO_MISSAO, e);
export const estadoTarefa = (e) => achar(ESTADO_TAREFA, e);
export const resultado = (r) => achar(RESULTADO, r || 'pendente');
export const estadoIntegracao = (e) => achar(INTEGRACAO, e);
export const natureza = (n) => achar(NATUREZA, n);
export const camada = (c) => CAMADA[c] || c || NADA;
export const camadaConfere = (c) => CAMADA_O_QUE[c] || '';
export const CAMADAS = ['estrutural', 'objetiva', 'documental', 'especializada', 'global', 'operacional'];

export const ESTADOS_MISSAO = Object.keys(ESTADO_MISSAO);

const TIPO_EVENTO = {
  'missao.aberta': 'Missão aberta',
  'missao.estado': 'Estado da missão',
  'missao.encerrada': 'Missão encerrada',
  'missao.ciclo_improdutivo': 'Ciclo improdutivo interrompido',
  'missao.sem_repertorio': 'Sem repertório para o objetivo',
  'plano.criado': 'Plano criado',
  'tarefa.estado': 'Estado da tarefa',
  'acao.decidida': 'Ação decidida',
  'artefato.falha': 'Falha em artefato',
};
export const tipoEvento = (t) => TIPO_EVENTO[t] || t;

export function ator(a) {
  if (!a) return NADA;
  if (a === 'nucleo') return 'núcleo';
  if (a.startsWith('agente:')) return `agente ${a.slice(7)}`;
  if (a.startsWith('usuario:')) return 'usuário';
  return a;
}

export { NADA };
