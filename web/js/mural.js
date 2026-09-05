/* NÓRIA — mural do saguão.
 *
 * Esta tela fica numa parede à vista de cliente, motorista e visitante. Ela
 * responde a uma pergunta só: "esta empresa opera com controle?". Mostra o
 * ritmo dos embarques em quantidade, a equipe de agentes que vigia cada área
 * e a agenda de varreduras do dia — e nada além disso.
 *
 * O que esta tela nunca mostra, por decisão e não por esquecimento: valor em
 * reais, nome de cliente, texto de achado, decisão pendente. A API recusa
 * essas rotas para a conta do saguão; aqui a interface apenas não pede.
 *
 * Nenhum número é calculado aqui. Tudo vem de /api/saguao, que por sua vez lê
 * o ERP e o núcleo. Se a leitura falhar, o mural diz que falhou em vez de
 * mostrar zero.
 */

import * as api from './api.js';
import { el, juntar, limpar, logo } from './ui.js';
import * as f from './fmt.js';

const RECARGA_MS = 60000;

const MES_CURTO = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun',
  'jul', 'ago', 'set', 'out', 'nov', 'dez'];

function rotuloMes(iso) {
  const [ano, mes] = String(iso || '').split('-');
  const m = MES_CURTO[Number(mes) - 1];
  return m ? `${m}` : iso;
}

/* ----------------------------------------------------------------- peças --- */
function selo(valor, rotulo, apoio) {
  return el('div.mural-selo', null, [
    el('div.mural-selo-n', { texto: f.numero(valor) }),
    el('div.mural-selo-r', { texto: rotulo }),
    apoio ? el('div.mural-selo-a', { texto: apoio }) : null,
  ]);
}

/** Ritmo mensal em quantidade de documentos. Sem eixo de valor: a altura
 *  compara meses entre si, e o mês corrente aparece marcado porque está
 *  incompleto e comparar com ele seria mentira visual. */
function ritmo(serie) {
  if (!serie || !serie.length) {
    return el('p.mural-vazio', { texto: 'série mensal indisponível nesta leitura' });
  }
  const max = Math.max(...serie.map((p) => Number(p.qt) || 0), 1);
  const ultimo = serie.length - 1;
  const barras = serie.map((p, i) => {
    const v = Number(p.qt) || 0;
    const alt = Math.max(2, Math.round((v / max) * 100));
    return el('div.mural-barra' + (i === ultimo ? '.parcial' : ''), {
      title: `${p.mes}: ${f.numero(v)} CT-es`,
    }, [
      el('span.mural-barra-v', { texto: f.numero(v) }),
      el('span.mural-barra-t', { style: `height:${alt}%` }),
      el('span.mural-barra-m', { texto: rotuloMes(p.mes) }),
    ]);
  });
  return el('div.mural-ritmo', null, barras);
}

function equipePorArea(equipe, areas) {
  return el('div.mural-areas', null, areas.map((a) => {
    const gente = equipe.filter((x) => x.area === a);
    return el('div.mural-area', null, [
      el('h3', { texto: a }),
      el('div.mural-gente', null, gente.map((g) => el(
        'div.mural-pessoa' + (g.situacao === 'habilitado' ? '.viva' : '')
        + (g.trabalhando_agora ? '.agora' : ''),
        { title: `${g.papel} · ${g.situacao}` },
        [el('span.ponto'), el('span.nome', { texto: g.nome })],
      ))),
    ]);
  }));
}

function agendaDoDia(rotinas) {
  if (!rotinas || !rotinas.length) {
    return el('p.mural-vazio', { texto: 'sem varredura marcada para hoje' });
  }
  return el('div.mural-agenda', null, rotinas.map((r) => el(
    `div.mural-rotina.${r.estado}`, null, [
      el('span.h', { texto: `${String(r.hora).padStart(2, '0')}h` }),
      el('span.n', { texto: r.nome }),
      el('span.e', {
        texto: r.estado === 'feito' ? 'concluída'
          : r.estado === 'atrasado' ? 'em fila' : 'prevista',
      }),
    ],
  )));
}

/* ----------------------------------------------------------------- tela ---- */
export function mural() {
  const raiz = el('div.mural', null, [
    el('header.mural-topo', null, [
      el('div.mural-marca', null, [
        logo(34),
        el('div', null, [
          el('h1.marca-cromo', { texto: 'NÓRIA' }),
          el('span', { id: 'mural-empresa', texto: 'Pianetto Transportes' }),
        ]),
      ]),
      el('div.vao'),
      el('div.mural-relogio', null, [
        el('div.hora', { id: 'mural-hora', texto: '--:--' }),
        el('div.dia', { id: 'mural-dia', texto: '' }),
      ]),
    ]),
    el('div.mural-corpo', { id: 'mural-corpo' }),
    el('footer.mural-pe', null, [
      el('span', { id: 'mural-estado', texto: 'lendo a operação…' }),
      el('div.vao'),
      el('span.mural-legenda', { texto: 'painel de exibição · sem dados financeiros' }),
    ]),
  ]);

  /* Fator de parede. Cresce com a tela, mas pela MENOR das duas medidas: um
     monitor largo e baixo não pode inflar a tipografia a ponto de empurrar o
     rodapé para fora. O mural não rola — o que não couber some, e sumir é
     pior do que ficar um pouco menor. */
  function ideal() {
    return Math.max(0.7, Math.min(2.1,
      window.innerWidth / 1440, window.innerHeight / 900));
  }

  function medir(m) {
    raiz.style.setProperty('--m', String(Math.round(m * 100) / 100));
  }

  /* Encaixe. Depois de pintar, mede se sobrou conteúdo para fora e vai
     reduzindo o fator até caber. É o oposto de esconder o excesso: numa
     parede, nada é rolado, então o que não coube simplesmente nunca seria
     visto — e o mural passaria a mentir por omissão. */
  function encaixar() {
    const corpo = raiz.querySelector('#mural-corpo');
    if (!corpo) return;
    let m = ideal();
    medir(m);
    for (let i = 0; i < 16; i += 1) {
      if (corpo.scrollHeight <= corpo.clientHeight + 1) break;
      m *= 0.955;
      if (m < 0.55) break;
      medir(m);
    }
  }

  function relogio() {
    const d = new Date();
    const h = raiz.querySelector('#mural-hora');
    const dia = raiz.querySelector('#mural-dia');
    // Fuso fixo da empresa: se o computador da parede estiver com o relógio
    // em outro fuso, quem manda é Brasília, não a máquina.
    const FUSO = { timeZone: 'America/Sao_Paulo' };
    if (h) {
      h.textContent = d.toLocaleTimeString('pt-BR',
        { ...FUSO, hour: '2-digit', minute: '2-digit' });
    }
    if (dia) {
      const t = d.toLocaleDateString('pt-BR',
        { ...FUSO, weekday: 'long', day: '2-digit', month: 'long' });
      dia.textContent = t.charAt(0).toUpperCase() + t.slice(1);
    }
  }

  function pintar(d) {
    const corpo = raiz.querySelector('#mural-corpo');
    limpar(corpo);
    const op = d.operacao || {};
    const nu = d.nucleo || {};

    juntar(corpo, [
      el('section.mural-linha-selos', null, [
        selo(op.ctes_hoje, 'conhecimentos emitidos hoje'),
        selo(op.ctes_mes, 'no mês'),
        selo(op.ctes_12m, 'nos últimos 12 meses'),
      ]),

      el('section.mural-bloco.mural-bloco-ritmo', null, [
        el('h2', { texto: 'Ritmo de embarques' }),
        el('p.mural-sub', { texto: 'quantidade de conhecimentos por mês · mês corrente ainda em curso' }),
        op.erro ? el('p.mural-vazio', { texto: `leitura indisponível: ${op.erro}` })
          : ritmo(op.serie),
      ]),

      el('div.mural-duas', null, [
        el('section.mural-bloco', null, [
          el('h2', { texto: 'Quem vigia cada área' }),
          el('p.mural-sub', {
            texto: `${f.numero(nu.agentes)} agentes em ${f.numero(nu.areas)} áreas · `
              + `${f.numero(nu.habilitados)} operando com dado real`,
          }),
          equipePorArea(d.equipe || [], d.areas || []),
        ]),
        el('section.mural-bloco', null, [
          el('h2', { texto: 'A vigilância de hoje' }),
          el('p.mural-sub', { texto: 'varreduras automáticas com hora marcada' }),
          agendaDoDia(d.rotinas),
          el('div.mural-numeros', null, [
            el('div', null, [el('b', { texto: f.numero(nu.consultas_hoje) }),
              el('span', { texto: 'consultas ao sistema hoje' })]),
            el('div', null, [el('b', { texto: f.numero(nu.conferencias_hoje) }),
              el('span', { texto: 'conferências feitas hoje' })]),
            el('div', null, [el('b', { texto: f.numero(nu.evidencias) }),
              el('span', { texto: 'evidências guardadas' })]),
            el('div', null, [el('b', { texto: f.numero(nu.missoes_concluidas) }),
              el('span', { texto: 'apurações concluídas' })]),
          ]),
        ]),
      ]),

      el('section.mural-regra', null, [
        el('span', { texto: `${f.numero(nu.camadas)} camadas de validação` }),
        el('i'),
        el('span', { texto: `${f.numero(nu.pares_contraprova)} pares de contraprova independente` }),
        el('i'),
        el('span', { texto: 'nenhuma conclusão sem evidência de origem' }),
      ]),
    ]);

    const est = raiz.querySelector('#mural-estado');
    if (est) est.textContent = `operação lida às ${f.hora(d.lido_em)}`;
    const emp = raiz.querySelector('#mural-empresa');
    if (emp && d.empresa) emp.textContent = d.empresa.replace(/ LTDA$/i, '');
    encaixar();
  }

  async function carregar() {
    try {
      pintar(await api.saguao());
    } catch (e) {
      const est = raiz.querySelector('#mural-estado');
      if (est) est.textContent = `não consegui ler agora: ${e.message}`;
    }
  }

  medir(ideal());
  window.addEventListener('resize', encaixar);
  relogio();
  carregar();
  setInterval(relogio, 20000);
  setInterval(carregar, RECARGA_MS);
  return raiz;
}
