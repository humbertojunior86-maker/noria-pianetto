/* NÓRIA — casca da aplicação: entrada, menu, tema, rotas e o pulso de eventos. */

import * as api from './api.js';
import { el, juntar, limpar, icone, logo, carregando, erro } from './ui.js';
import * as f from './fmt.js';
import { abertura, pular, DURACAO } from './abertura.js';
import { mural } from './mural.js';

/* ------------------------------------------------------------------ tema --- */
const CHAVE_TEMA = 'noria.tema';

function lerTema() {
  try { return localStorage.getItem(CHAVE_TEMA) || 'escuro'; } catch { return 'escuro'; }
}

function aplicarTema(t) {
  if (t === 'claro') document.documentElement.setAttribute('data-tema', 'claro');
  else document.documentElement.removeAttribute('data-tema');
  try { localStorage.setItem(CHAVE_TEMA, t); } catch { /* bloqueado */ }
}
aplicarTema(lerTema());

/* ------------------------------------------------------------- pulso ------ */
/** Único poll de /api/eventos; as telas se inscrevem. */
export const pulso = {
  ultimo: 0,
  eventos: [],
  ouvintes: new Set(),
  timer: 0,
  assinar(fn) {
    this.ouvintes.add(fn);
    if (this.eventos.length) fn(this.eventos, []);
    return () => this.ouvintes.delete(fn);
  },
  async ciclo() {
    try {
      const d = await api.eventos(this.ultimo);
      const novos = (d.eventos || []).slice().sort((a, b) => b.id - a.id);
      if (novos.length) {
        this.ultimo = Math.max(this.ultimo, ...novos.map((e) => e.id));
        this.eventos = [...novos, ...this.eventos].slice(0, 120);
        this.ouvintes.forEach((fn) => fn(this.eventos, novos));
      }
    } catch { /* sem barulho: a tela mostra o último estado conhecido */ }
  },
  iniciar() {
    if (this.timer) return;
    this.ciclo();
    this.timer = setInterval(() => this.ciclo(), 4000);
  },
  parar() { clearInterval(this.timer); this.timer = 0; },
  zerar() { this.parar(); this.ultimo = 0; this.eventos = []; this.ouvintes.clear(); },
};

/* ------------------------------------------------------------- contexto --- */
export const ctx = { usuario: null, empresa: null };

/* --------------------------------------------------------------- rotas ---- */
const TELAS = [
  { id: 'ceo', rotulo: 'Sala do CEO', icone: 'sala', grupo: 'Operação', carregar: () => import('./telas/ceo.js') },
  { id: 'visao', rotulo: 'Visão geral', icone: 'visao', grupo: 'Operação', carregar: () => import('./telas/visao.js') },
  { id: 'cerebro', rotulo: 'Cérebro', icone: 'cerebro', grupo: 'Operação', carregar: () => import('./telas/cerebro.js') },
  { id: 'missoes', rotulo: 'Missões', icone: 'missoes', grupo: 'Operação', carregar: () => import('./telas/missoes.js') },
  { id: 'entregas', rotulo: 'Entregas', icone: 'entregas', grupo: 'Operação', carregar: () => import('./telas/entregas.js') },
  { id: 'agentes', rotulo: 'Agentes', icone: 'agentes', grupo: 'Estrutura', carregar: () => import('./telas/agentes.js') },
  { id: 'conhecimento', rotulo: 'Conhecimento', icone: 'conhecimento', grupo: 'Estrutura', carregar: () => import('./telas/conhecimento.js') },
  { id: 'aprovacoes', rotulo: 'Aprovações', icone: 'aprovacoes', grupo: 'Estrutura', carregar: () => import('./telas/aprovacoes.js') },
  { id: 'integracoes', rotulo: 'Integrações', icone: 'integracoes', grupo: 'Estrutura', carregar: () => import('./telas/integracoes.js') },
];

const TITULOS = {
  ceo: ['Sala do CEO', 'A empresa inteira num olhar, com a hora de cada número'],
  visao: ['Visão geral', 'O pulso real da operação, direto do núcleo'],
  cerebro: ['Cérebro', 'O ciclo de decisão em operação, alimentado por eventos reais'],
  missoes: ['Missões', 'Objetivo, plano, tarefas, validação e artefatos'],
  entregas: ['Entregas', 'Cada afirmação com o seu lastro'],
  agentes: ['Agentes', 'Quem existe, quem pode operar e o que falta'],
  conhecimento: ['Conhecimento', 'Importação de extratos e acervo indexado'],
  aprovacoes: ['Aprovações', 'Ações externas aguardando decisão humana'],
  integracoes: ['Integrações', 'Estado real de cada conexão'],
};

function rotaAtual() {
  const h = (location.hash || '').replace(/^#\/?/, '');
  const p = h.split('/').filter(Boolean);
  // Rota vazia cai na Sala do CEO: é a tela que fica aberta na TV da sala.
  const tela = TELAS.some((t) => t.id === p[0]) ? p[0] : 'ceo';
  return { tela, params: p.slice(1) };
}

let limpezaTela = null;
let contadores = {};

async function desenharTela() {
  const { tela, params } = rotaAtual();
  const alvo = document.getElementById('conteudo');
  if (typeof limpezaTela === 'function') { try { limpezaTela(); } catch { /* nada */ } }
  limpezaTela = null;

  document.querySelectorAll('#menu a').forEach((a) => {
    if (a.dataset.tela === tela) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  const [t, s] = TITULOS[tela] || ['NÓRIA', ''];
  document.getElementById('titulo').textContent = t;
  document.getElementById('subtitulo').textContent = s;
  document.title = `${t} · NÓRIA`;

  limpar(alvo);
  const folha = el('div.folha', null, carregando(4));
  juntar(alvo, folha);
  window.scrollTo(0, 0);

  const def = TELAS.find((x) => x.id === tela);
  try {
    const mod = await def.carregar();
    limpar(folha);
    limpezaTela = await mod.montar(folha, params, { ctx, pulso, ir });
  } catch (e) {
    limpar(folha);
    juntar(folha, erro(e && e.message ? e.message : 'erro inesperado'));
    console.error(e);
  }
}

export function ir(destino) {
  location.hash = destino.startsWith('#') ? destino : `#/${destino}`;
}

/* -------------------------------------------------------------- casca ----- */
function menuLateral() {
  const nav = el('nav.menu', { id: 'menu', 'aria-label': 'Navegação principal' });
  let grupo = null;
  TELAS.forEach((t) => {
    if (t.grupo !== grupo) {
      grupo = t.grupo;
      juntar(nav, el('div.menu-grupo', { texto: grupo }));
    }
    juntar(nav, el('a', { href: `#/${t.id}`, 'data-tela': t.id }, [
      icone(t.icone), el('span', { texto: t.rotulo }), el('span.conta', { 'data-conta': t.id }),
    ]));
  });
  return nav;
}

function atualizarContadores(p) {
  contadores = {
    missoes: p.missoes ? p.missoes.total : null,
    agentes: p.agentes ? p.agentes.cadastrados : null,
    aprovacoes: p.aprovacoes_pendentes ?? null,
    entregas: null,
    integracoes: p.integracoes ? p.integracoes.length : null,
  };
  document.querySelectorAll('#menu [data-conta]').forEach((s) => {
    const v = contadores[s.dataset.conta];
    s.textContent = v === null || v === undefined ? '' : f.numero(v);
  });
  const pe = document.getElementById('lateral-pe');
  if (!pe) return;
  limpar(pe);
  const linha = (r, v) => el('div.linha-info', null, [el('span', { texto: r }), el('b', { texto: v })]);
  const semInt = (p.integracoes || []).filter((i) => i.estado !== 'conectada').length;
  juntar(pe, [
    linha('Missões em curso', f.numero(p.missoes ? p.missoes.em_curso : null)),
    linha('Agentes habilitados', `${f.numero(p.agentes.habilitados)} de ${f.numero(p.agentes.cadastrados)}`),
    linha('Integrações pendentes', f.numero(semInt)),
    linha('Evidências no acervo', f.numero(p.evidencias)),
    linha('Leitura de', f.dataHora(p.gerado_em)),
  ]);
}

function casca() {
  const lateral = el('aside.lateral', { id: 'lateral' }, [
    el('div.marca', null, [
      logo(28),
      el('div', null, [
        el('h1.marca-cromo', { texto: 'NÓRIA' }),
        el('span', { texto: 'Pianetto Transportes' }),
      ]),
    ]),
    menuLateral(),
    el('div.lateral-pe', { id: 'lateral-pe' }),
  ]);

  const btnTema = el('button.btn.btn-peq', {
    type: 'button', id: 'btn-tema',
    'aria-label': 'Alternar tema claro e escuro',
    title: 'Alternar tema',
    onclick: () => {
      const novo = lerTema() === 'claro' ? 'escuro' : 'claro';
      aplicarTema(novo);
      trocarIconeTema();
    },
  });
  function trocarIconeTema() {
    limpar(btnTema);
    juntar(btnTema, [icone(lerTema() === 'claro' ? 'lua' : 'luz', 14),
      el('span', { texto: lerTema() === 'claro' ? 'Escuro' : 'Claro' })]);
  }
  trocarIconeTema();

  const topo = el('header.topo', null, [
    el('button.btn.btn-peq.botao-menu', {
      type: 'button', 'aria-label': 'Abrir menu',
      onclick: () => alternarLateral(true),
    }, icone('menu', 16)),
    el('div', null, [
      el('h2', { id: 'titulo', texto: 'Sala do CEO' }),
      el('p.sub', { id: 'subtitulo', texto: '' }),
    ]),
    el('div.vao'),
    el('div.topo-acoes', null, [
      el('span.etq.neutra', { id: 'quem', texto: '' }),
      btnTema,
      el('button.btn.btn-peq', {
        type: 'button', title: 'Encerrar sessão',
        onclick: () => { api.esquecer(); pulso.zerar(); location.reload(); },
      }, [icone('sair', 14), el('span', { texto: 'Sair' })]),
    ]),
  ]);

  return el('div.app', null, [lateral, topo, el('main.conteudo', { id: 'conteudo' })]);
}

function alternarLateral(abrir) {
  const l = document.getElementById('lateral');
  if (!l) return;
  l.classList.toggle('aberta', abrir);
  let fundo = document.getElementById('fundo-menu');
  if (abrir && !fundo) {
    fundo = el('div.fundo-menu', { id: 'fundo-menu', onclick: () => alternarLateral(false) });
    document.body.appendChild(fundo);
  } else if (!abrir && fundo) fundo.remove();
}

/* -------------------------------------------------------------- entrada --- */
function telaEntrada(aoEntrar) {
  const aviso = el('div.aviso-erro.oculto');
  const email = el('input', { type: 'email', id: 'e-mail', autocomplete: 'username', placeholder: 'seu@email.com' });
  const senha = el('input', { type: 'password', id: 'senha', autocomplete: 'current-password', placeholder: '••••••••' });
  const btn = el('button.btn.btn-forte', { type: 'submit', texto: 'Entrar' });

  const form = el('form.entrada-caixa', {
    onsubmit: async (ev) => {
      ev.preventDefault();
      aviso.classList.add('oculto');
      btn.disabled = true;
      btn.textContent = 'Verificando…';
      try {
        await api.entrar(email.value.trim(), senha.value);
        aoEntrar();
      } catch (e) {
        aviso.textContent = e.message;
        aviso.classList.remove('oculto');
        btn.disabled = false;
        btn.textContent = 'Entrar';
      }
    },
  }, [
    el('div.marca', null, [
      logo(30),
      el('div', null, [el('h1.marca-cromo', { texto: 'NÓRIA' }),
        el('span', { texto: 'Pianetto Transportes' })]),
    ]),
    el('p.intro', { texto: 'Entre para acompanhar as missões, a validação e as decisões pendentes.' }),
    aviso,
    el('div.campo', null, [el('label', { for: 'e-mail', texto: 'E-mail' }), email]),
    el('div.campo', null, [el('label', { for: 'senha', texto: 'Senha' }), senha]),
    btn,
  ]);

  return el('div.entrada-tela', null, form);
}

/* ------------------------------------------------------------- abertura --- */
/* Esta tela fica num painel central da empresa. A abertura roda toda vez que
   alguém entra e volta sozinha depois de OCIOSO_MS sem ninguém tocar, para
   que a parede nunca fique numa imagem parada. */
const OCIOSO_MS = 5 * 60 * 1000;

let aberturaNoAr = false;

function rodarAbertura(aoTerminar, sobreposta = false) {
  if (aberturaNoAr) return;
  aberturaNoAr = true;

  const caixa = el('div', { id: 'abertura' }, [
    el('button.btn.btn-peq.pular', {
      type: 'button', texto: 'Pular abertura', onclick: () => { try { pular(); } catch { encerrar(); } },
    }),
  ]);
  if (sobreposta) caixa.classList.add('sobreposta');
  document.body.appendChild(caixa);

  let encerrada = false;
  function encerrar() {
    if (encerrada) return;
    encerrada = true;
    aberturaNoAr = false;
    clearTimeout(cao);
    sair.forEach((ev) => window.removeEventListener(ev, aoTocar, true));
    caixa.classList.add('saindo');
    setTimeout(() => caixa.remove(), 640);
    aoTerminar();
  }

  // Quando a abertura entra por cima do painel, qualquer toque a dispensa na
  // hora: quem chegou para usar o sistema não deve esperar a animação.
  const sair = sobreposta
    ? ['pointerdown', 'keydown', 'wheel', 'touchstart']
    : [];
  const aoTocar = () => { try { pular(); } catch { encerrar(); } };
  sair.forEach((ev) => window.addEventListener(ev, aoTocar, true));

  // Cão de guarda: a abertura é enfeite, o sistema é o que importa. Se ela
  // travar por qualquer motivo, o painel entra no ar do mesmo jeito.
  const cao = setTimeout(encerrar, DURACAO + 4000);

  try {
    abertura(caixa, encerrar);
  } catch (e) {
    console.error('abertura falhou, seguindo direto para o painel', e);
    encerrar();
  }
}

/* ----------------------------------------------------------------- boot --- */
async function aplicacao() {
  // Quem é o usuário decide qual sistema sobe. A conta do saguão abre o mural
  // e nada mais: sem menu, sem rota, sem pulso de eventos. Mesmo que alguém
  // digite #/ceo na barra, não há tela para desenhar — e a API recusaria.
  let quemE = null;
  try {
    quemE = await api.eu();
  } catch (e) {
    if (e.status === 401) return;
    console.error(e);
  }

  if (quemE && quemE.usuario && quemE.usuario.papel === 'saguao') {
    ctx.usuario = quemE.usuario;
    ctx.empresa = quemE.empresa;
    limpar(document.body);
    document.body.classList.add('modo-saguao');
    document.title = 'NÓRIA · Pianetto Transportes';
    document.body.appendChild(mural());
    vigiarOcioso();
    return;
  }

  limpar(document.body);
  document.body.appendChild(casca());
  window.addEventListener('hashchange', desenharTela);

  if (quemE) {
    ctx.usuario = quemE.usuario;
    ctx.empresa = quemE.empresa;
    document.getElementById('quem').textContent = `${quemE.usuario.nome} · ${quemE.empresa.nome.split(' ')[0]}`;
    document.getElementById('quem').title = `${quemE.usuario.papel} · ${quemE.empresa.nome} · CNPJ ${quemE.empresa.cnpj}`;
  }

  desenharTela();
  pulso.iniciar();

  // rodapé e contadores do menu vêm do panorama real, atualizados a cada 20 s
  const atualizar = async () => {
    try { atualizarContadores(await api.panorama()); } catch { /* silencioso */ }
  };
  atualizar();
  setInterval(atualizar, 20000);

  vigiarOcioso();
}

/* ---- volta da abertura depois de OCIOSO_MS parado --------------------- */
let relogioOcioso = null;

function vigiarOcioso() {
  const eventos = ['pointerdown', 'pointermove', 'keydown', 'wheel', 'touchstart'];
  const rearmar = () => {
    clearTimeout(relogioOcioso);
    relogioOcioso = setTimeout(() => {
      // não entra por cima da tela de entrada nem de outra abertura
      if (aberturaNoAr || !api.temSessao()) { rearmar(); return; }
      if (document.hidden) { rearmar(); return; }
      rodarAbertura(() => rearmar(), true);
    }, OCIOSO_MS);
  };
  eventos.forEach((ev) => window.addEventListener(ev, rearmar, { passive: true }));
  document.addEventListener('visibilitychange', rearmar);
  rearmar();
}

function iniciar() {
  // Avisa o salva-vidas que o código chegou vivo até aqui.
  window.dispatchEvent(new Event('noria:vivo'));
  const capa = document.getElementById('primeira-pintura');
  if (capa) capa.remove();

  if (!api.temSessao()) {
    limpar(document.body);
    document.body.appendChild(telaEntrada(() => iniciar()));
    return;
  }
  limpar(document.body);
  rodarAbertura(() => aplicacao());
}

window.addEventListener('noria:sem-sessao', () => {
  pulso.parar();
  limpar(document.body);
  document.body.appendChild(telaEntrada(() => iniciar()));
});

iniciar();
