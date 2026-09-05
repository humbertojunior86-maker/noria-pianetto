/* Peças de interface reaproveitadas por todas as telas. */

import * as f from './fmt.js';

/** Cria elemento: el('div.painel', {onclick}, [filhos|texto]) */
export function el(seletor, atributos = null, filhos = null) {
  const [tag, ...classes] = String(seletor).split('.');
  const n = document.createElement(tag || 'div');
  if (classes.length) n.className = classes.join(' ');
  if (atributos) {
    for (const [k, v] of Object.entries(atributos)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'texto') n.textContent = v;
      else if (k === 'html') n.innerHTML = v;
      else if (k === 'classe') n.className = `${n.className} ${v}`.trim();
      else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? '' : String(v));
    }
  }
  juntar(n, filhos);
  return n;
}

export function juntar(pai, filhos) {
  if (filhos === null || filhos === undefined || filhos === false) return pai;
  if (Array.isArray(filhos)) { filhos.forEach((c) => juntar(pai, c)); return pai; }
  pai.appendChild(filhos instanceof Node ? filhos : document.createTextNode(String(filhos)));
  return pai;
}

export function limpar(n) { while (n.firstChild) n.removeChild(n.firstChild); return n; }

/* ------------------------------------------------------------- ícones ----- */
const CAMINHOS = {
  visao: 'M3 3h6v6H3zM11 3h6v4h-6zM11 9h6v8h-6zM3 11h6v6H3z',
  cerebro: 'M10 3v14M10 3a3 3 0 0 0-3 3 2.5 2.5 0 0 0-1 4.8A3 3 0 0 0 10 17M10 3a3 3 0 0 1 3 3 2.5 2.5 0 0 1 1 4.8A3 3 0 0 1 10 17',
  missoes: 'M4 3h9l3 3v11H4zM7 9h6M7 12h6',
  entregas: 'M3 7l7-4 7 4v6l-7 4-7-4zM3 7l7 4 7-4M10 11v6',
  agentes: 'M7 9a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM2.5 17c0-2.5 2-4.2 4.5-4.2s4.5 1.7 4.5 4.2M14 5.2a2 2 0 1 1 0 4M13.5 12.8c2 .3 3.5 1.9 3.5 4.2',
  conhecimento: 'M4 4h5.5v13H4zM10.5 4H16v13h-5.5zM4 4c0-.6.4-1 1-1h4.5M16 4c0-.6-.4-1-1-1h-4.5',
  aprovacoes: 'M4 10.5l3.5 3.5L16 5.5M3 16.5h14',
  integracoes: 'M7 4v4M13 4v4M5 8h10v3a5 5 0 0 1-10 0zM10 16v2',
  seta: 'M4 10h12M11 5l5 5-5 5',
  vazio: 'M4 5h12v10H4zM4 8h12',
  baixar: 'M10 3v9M6 9l4 4 4-4M4 16h12',
  luz: 'M10 2v2M10 16v2M2 10h2M16 10h2M4.5 4.5l1.4 1.4M14.1 14.1l1.4 1.4M15.5 4.5l-1.4 1.4M5.9 14.1l-1.4 1.4M10 6.5a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7z',
  lua: 'M13.5 3.2A7 7 0 1 0 16.8 12 5.6 5.6 0 0 1 13.5 3.2z',
  menu: 'M3 5h14M3 10h14M3 15h14',
  sair: 'M8 4H4v12h4M12 7l3 3-3 3M15 10H7',
  relogio: 'M10 5v5l3 2M10 2.5a7.5 7.5 0 1 1 0 15 7.5 7.5 0 0 1 0-15z',
  alerta: 'M10 3l7 13H3zM10 8v4M10 14h.01',
};

export function icone(nome, tamanho = 16) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('width', tamanho);
  svg.setAttribute('height', tamanho);
  svg.setAttribute('viewBox', '0 0 20 20');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.4');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  p.setAttribute('d', CAMINHOS[nome] || CAMINHOS.vazio);
  svg.appendChild(p);
  return svg;
}

/** Marca da NÓRIA: núcleo e seis nós, como no logo. */
export function logo(tamanho = 26) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('width', tamanho);
  svg.setAttribute('height', tamanho);
  svg.setAttribute('viewBox', '0 0 32 32');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'NÓRIA');
  const g = document.createElementNS(ns, 'g');
  g.setAttribute('stroke', 'currentColor');
  g.setAttribute('stroke-width', '1.2');
  const anel = document.createElementNS(ns, 'circle');
  anel.setAttribute('cx', '16'); anel.setAttribute('cy', '16'); anel.setAttribute('r', '11');
  anel.setAttribute('opacity', '.35');
  g.appendChild(anel);
  for (let i = 0; i < 6; i++) {
    const a = (Math.PI / 3) * i - Math.PI / 2;
    const x = 16 + Math.cos(a) * 11, y = 16 + Math.sin(a) * 11;
    const linha = document.createElementNS(ns, 'line');
    linha.setAttribute('x1', 16); linha.setAttribute('y1', 16);
    linha.setAttribute('x2', x.toFixed(2)); linha.setAttribute('y2', y.toFixed(2));
    linha.setAttribute('opacity', '.45');
    g.appendChild(linha);
    const no = document.createElementNS(ns, 'circle');
    no.setAttribute('cx', x.toFixed(2)); no.setAttribute('cy', y.toFixed(2));
    no.setAttribute('r', '2'); no.setAttribute('fill', 'currentColor');
    no.setAttribute('stroke', 'none');
    g.appendChild(no);
  }
  const nucleo = document.createElementNS(ns, 'circle');
  nucleo.setAttribute('cx', '16'); nucleo.setAttribute('cy', '16'); nucleo.setAttribute('r', '4');
  nucleo.setAttribute('fill', 'currentColor'); nucleo.setAttribute('stroke', 'none');
  g.appendChild(nucleo);
  svg.appendChild(g);
  return svg;
}

/* ---------------------------------------------------------- componentes --- */
export function etiqueta(texto, tom = 'neutra', comPonto = false) {
  return el(`span.etq.${tom}`, null, [comPonto ? el('i.ponto') : null, texto]);
}

export const etiquetaEstado = (e) => {
  const r = f.estadoMissao(e);
  return etiqueta(r.texto, r.tom, true);
};

export function painel({ titulo, nota, acoes, corpo, semFolga }) {
  const cab = (titulo || nota || acoes)
    ? el('div.painel-cab', null, [
      titulo ? el('h3', { texto: titulo }) : null,
      nota ? el('p.nota', { texto: nota }) : null,
      acoes || null,
    ])
    : null;
  return el('section.painel', null, [
    cab,
    el(`div.painel-corpo${semFolga ? '.sem-folga' : ''}`, null, corpo),
  ]);
}

export function metrica(rotulo, valor, obs, { destaque = false, menor = false } = {}) {
  return el(`div.metrica${destaque ? '.destaque' : ''}`, null, [
    el('span.rot', { texto: rotulo }),
    el(`span.val${menor ? '.menor' : ''}`, { texto: valor }),
    obs ? el('span.obs', { texto: obs }) : null,
  ]);
}

export function vazio(mensagem, detalhe, acao) {
  return el('div.vazio', null, [
    icone('vazio', 24),
    el('p', { texto: mensagem }),
    detalhe ? el('p', { texto: detalhe }) : null,
    acao ? el('div.acao', null, acao) : null,
  ]);
}

export function carregando(linhas = 3) {
  return el('div', null, Array.from({ length: linhas }, (_, i) =>
    el('div.esqueleto', { style: `width:${100 - i * 14}%` })));
}

export function erro(mensagem) {
  return el('div.aviso-erro', null, [`Não deu para carregar: ${mensagem}`]);
}

export function par(rotulo, valor) {
  return el('div.par', null, [el('span', { texto: rotulo }), el('b', { texto: valor })]);
}

export function tabela(colunas, linhas) {
  const cabeca = el('tr', null, colunas.map((c) =>
    el(`th${c.num ? '.num' : ''}`, { texto: c.titulo })));
  const corpo = linhas.map((l) => el('tr', null, l.map((c, i) => {
    const num = colunas[i] && colunas[i].num;
    const td = el(`td${num ? '.num' : ''}`);
    juntar(td, c);
    return td;
  })));
  return el('div.tabela-caixa', null,
    el('table.tabela', null, [el('thead', null, cabeca), el('tbody', null, corpo)]));
}

export function tituloLinha(texto, extra) {
  return el('div.titulo-linha', null, [el('h3', { texto }), el('span.traco'), extra || null]);
}

export function secao(titulo, descricao, corpo) {
  return el('section.secao', null, [
    titulo ? el('h2', { texto: titulo }) : null,
    descricao ? el('p.descricao', { texto: descricao }) : null,
    corpo || null,
  ]);
}

export function migalhas(itens) {
  const n = el('nav.migalhas', { 'aria-label': 'Você está em' });
  itens.forEach((it, i) => {
    if (i) juntar(n, el('span', { texto: '/' }));
    juntar(n, it.destino ? el('a', { href: it.destino, texto: it.texto }) : el('span', { texto: it.texto }));
  });
  return n;
}

/** Uma linha de evento do núcleo. */
export function linhaEvento(ev) {
  const alvo = ev.missao_id ? `missão ${ev.missao_id}` : 'sistema';
  const transicao = ev.de_estado && ev.para_estado ? ` ${ev.de_estado} → ${ev.para_estado}` : '';
  return el('div.log-linha', null, [
    el('span.h', { texto: f.hora(ev.criado_em) }),
    el('span.t', null, [
      el('b', { texto: f.tipoEvento(ev.tipo) }),
      ` · ${alvo}${transicao} — ${f.textoBr(ev.texto || '')}`,
    ]),
  ]);
}
