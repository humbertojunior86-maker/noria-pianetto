/* NÓRIA — único caminho da interface até o núcleo.
   Nenhuma tela inventa número: tudo aqui vem de /api. */

const BASE = '/api';
const CHAVE = 'noria.token';

let token = null;
try { token = localStorage.getItem(CHAVE); } catch { token = null; }

export function temSessao() { return !!token; }

export function guardar(t) {
  token = t;
  try { localStorage.setItem(CHAVE, t); } catch { /* armazenamento bloqueado */ }
}

export function esquecer() {
  token = null;
  try { localStorage.removeItem(CHAVE); } catch { /* idem */ }
}

export class ErroApi extends Error {
  constructor(mensagem, status) {
    super(mensagem);
    this.status = status;
  }
}

async function pedir(rota, opcoes = {}) {
  const cab = { 'Accept': 'application/json' };
  if (token) cab['Authorization'] = `Bearer ${token}`;
  if (opcoes.corpo !== undefined) cab['Content-Type'] = 'application/json';

  let r;
  try {
    r = await fetch(BASE + rota, {
      method: opcoes.metodo || 'GET',
      headers: cab,
      body: opcoes.corpo !== undefined ? JSON.stringify(opcoes.corpo) : undefined,
    });
  } catch {
    throw new ErroApi('não foi possível falar com o servidor da NÓRIA', 0);
  }

  if (r.status === 401) {
    esquecer();
    window.dispatchEvent(new CustomEvent('noria:sem-sessao'));
    throw new ErroApi('sessão expirada — entre novamente', 401);
  }

  let dados = null;
  const tipo = r.headers.get('content-type') || '';
  if (tipo.includes('application/json')) dados = await r.json().catch(() => null);

  if (!r.ok) {
    let msg = (dados && (dados.detail || (dados.erro && dados.erro.mensagem)))
      || `falha na chamada ${rota} (HTTP ${r.status})`;
    // FastAPI devolve lista de erros de validação; vira frase legível.
    if (Array.isArray(msg)) {
      msg = msg.map((e) => {
        const campo = Array.isArray(e.loc) ? e.loc[e.loc.length - 1] : 'dado';
        return `${campo}: ${e.msg || 'valor inválido'}`;
      }).join('; ');
    } else if (typeof msg !== 'string') {
      msg = `falha na chamada ${rota} (HTTP ${r.status})`;
    }
    throw new ErroApi(msg, r.status);
  }
  return dados;
}

/* --------------------------------------------------------------- sessão --- */
export async function entrar(email, senha) {
  const d = await pedir('/entrar', { metodo: 'POST', corpo: { email, senha } });
  guardar(d.token);
  return d.usuario;
}

export const eu = () => pedir('/eu');

/* ------------------------------------------------------------- consultas -- */
export const panorama = () => pedir('/panorama');
export const missoes = (estado) => pedir('/missoes' + (estado ? `?estado=${encodeURIComponent(estado)}` : ''));
export const missao = (id) => pedir(`/missoes/${id}`);
export const entregas = (id) => pedir(`/missoes/${id}/entregas`);
export const agentes = () => pedir('/agentes');
export const agente = (id) => pedir(`/agentes/${encodeURIComponent(id)}`);
export const eventos = (desde = 0) => pedir(`/eventos?desde=${desde}`);
export const execucoes = () => pedir('/execucoes');
export const artefatos = () => pedir('/artefatos');
export const aprovacoes = () => pedir('/aprovacoes');
export const integracoes = () => pedir('/integracoes');
export const ceo = (forcar) => pedir('/ceo' + (forcar ? '?forcar=true' : ''));
/* A agenda é lida à parte dos grandes números porque tem outro ritmo: os
   números do ERP mudam de minuto a minuto, o dia da NÓRIA muda de hora em hora
   — e a faixa do ritmo se recarrega sozinha sem redesenhar a tela inteira. */
export const agenda = () => pedir('/agenda');
export const saguao = () => pedir('/saguao');
export const evidencia = (id) => pedir(`/evidencias/${id}`);
/* O pensamento tem chamada própria: se ele estiver desligado ou sem crédito, a
   Sala do CEO continua desenhando os números normalmente. */
export const pensamento = () => pedir('/pensamento');

/* o diário do que a NÓRIA fez sem ninguém pedir */
export const autonomia = () => pedir('/autonomia');
/* os agentes que a própria NÓRIA criou, e as informações que ela publicou sem
   ninguém pedir. Quem dá voz a um vigia é o CEO: por isso aprovar e desligar
   são POST daqui, nunca ato dela. */
export const vigias = () => pedir('/vigias');
export const aprovarVigia = (id) => pedir(`/vigias/${id}/aprovar`, { metodo: 'POST', corpo: {} });
export const desligarVigia = (id, motivo) =>
  pedir(`/vigias/${id}/desligar`, { metodo: 'POST', corpo: { motivo: motivo || '' } });
export const entregaveis = () => pedir('/entregaveis');

export const decidirHipotese = (id, decisao) =>
  pedir(`/pensamento/hipoteses/${id}/decidir`, { metodo: 'POST', corpo: { decisao } });

/* ------------------------------------------------------------- comandos --- */
export const criarMissao = (objetivo, contexto) =>
  pedir('/missoes', { metodo: 'POST', corpo: { objetivo, contexto: contexto || {} } });
export const avancarMissao = (id) => pedir(`/missoes/${id}/avancar`, { metodo: 'POST', corpo: {} });
export const cancelarMissao = (id, motivo) =>
  pedir(`/missoes/${id}/cancelar`, { metodo: 'POST', corpo: { motivo } });
export const decidir = (id, decisao, observacao) =>
  pedir(`/aprovacoes/${id}`, { metodo: 'POST', corpo: { decisao, observacao } });
export const testarIntegracao = (id) => pedir(`/integracoes/${id}/testar`, { metodo: 'POST', corpo: {} });
export const bradescoConfig = () => pedir('/integracoes/bradesco/config');
export const bradescoPfx = (dados) => pedir('/integracoes/bradesco/pfx', { metodo: 'POST', corpo: dados });
export const bradescoGravar = (dados) => pedir('/integracoes/bradesco/config', { metodo: 'POST', corpo: dados });
export const tesourariaBradesco = () => pedir('/tesouraria/bradesco');
export const bradescoColher = () => pedir('/tesouraria/bradesco/colher', { metodo: 'POST', corpo: {} });

export function urlArtefato(id) {
  return `${BASE}/artefatos/${id}/baixar`;
}

/** Baixa um artefato mandando o token (a rota é autenticada). */
export async function baixarArtefato(id, nome) {
  const r = await fetch(urlArtefato(id), { headers: { Authorization: `Bearer ${token}` } });
  if (!r.ok) throw new ErroApi(`não foi possível baixar (HTTP ${r.status})`, r.status);
  const b = await r.blob();
  const u = URL.createObjectURL(b);
  const a = document.createElement('a');
  a.href = u;
  a.download = nome || `artefato-${id}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(u), 4000);
}
