/* Sala do CEO — a empresa inteira num olhar, para ficar aberta numa TV.
   Todo número vem de /api/ceo. Bloco do ERP que falhar mostra o motivo escrito,
   nunca zero: zero inventado esconde a falha, motivo escrito denuncia. */

import * as api from '../api.js';
import * as f from '../fmt.js';
import { el, juntar, limpar, painel, icone, linhaEvento, etiqueta } from '../ui.js';

/* Recarrega sozinha porque a tela vive numa TV, sem ninguém para clicar.
   60 s é o mesmo tempo que o servidor guarda os números do ERP. */
const INTERVALO_MS = 60000;

const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

/** 2026-08 → ago/26 */
function mesCurto(ym) {
  const m = String(ym || '').match(/^(\d{4})-(\d{2})/);
  if (!m) return f.NADA;
  return `${MESES[Number(m[2]) - 1] || '?'}/${m[1].slice(2)}`;
}

/** 2026-08 → agosto de 2026 */
function mesLongo(ym) {
  const NOMES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho',
    'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];
  const m = String(ym || '').match(/^(\d{4})-(\d{2})/);
  if (!m) return f.NADA;
  return `${NOMES[Number(m[2]) - 1] || '?'} de ${m[1]}`;
}

/** A regra da casa é carimbar a hora de leitura; aqui com segundos, porque o
    CEO precisa distinguir duas leituras do mesmo minuto. */
function horaSeg(iso) {
  const m = String(iso || '').match(/[T ](\d{2}:\d{2}:\d{2})/);
  return m ? m[1] : f.hora(iso);
}

/** Tempo relativo curto: numa TV, "há 4 min" se lê mais rápido que um carimbo. */
function haQuanto(iso) {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  const s = Math.floor((Date.now() - t) / 1000);
  if (s < 0) return 'agora';
  if (s < 60) return `há ${s} s`;
  if (s < 3600) return `há ${Math.floor(s / 60)} min`;
  if (s < 86400) return `há ${Math.floor(s / 3600)} h`;
  const d = Math.floor(s / 86400);
  return d === 1 ? 'há 1 dia' : `há ${d} dias`;
}

/** Número redondo para pensar. O exato aparece sempre logo abaixo. */
function abreviar(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return f.NADA;
  const n = Number(v);
  const abs = Math.abs(n);
  if (abs >= 1e9) return `R$ ${f.numero(n / 1e9, 1)} bi`;
  if (abs >= 1e6) return `R$ ${f.numero(n / 1e6, 1)} mi`;
  if (abs >= 1e3) return `R$ ${f.numero(n / 1e3, 0)} mil`;
  return f.dinheiro(n);
}

/** Qualquer bloco do ERP pode voltar com erro; a tela nunca supõe forma. */
function bloco(erp, nome) {
  const b = erp && erp[nome];
  if (!b) return { linhas: [], erro: 'a resposta da API não trouxe este bloco' };
  return { linhas: Array.isArray(b.linhas) ? b.linhas : [], erro: b.erro || null, consultada_em: b.consultada_em };
}

function carimbo(b, oQue) {
  if (b.consultada_em) {
    return el('p.ceo-carimbo', { texto: `${oQue} lidos no ERP às ${horaSeg(b.consultada_em)}` });
  }
  return el('p.ceo-carimbo', { texto: `${oQue}: sem hora de leitura informada pela API` });
}

/* ------------------------------------------------ faixa dos grandes números */

function numerao({ rotulo, valor, exato, apoio, motivo, tom }) {
  if (motivo) {
    return el('div.ceo-numerao.ceo-falho', null, [
      el('span.rot', { texto: rotulo }),
      el('span.motivo', { texto: `Sem número: ${motivo}` }),
      el('span.apoio', { texto: 'nada foi estimado nem arredondado no lugar do dado que faltou' }),
    ]);
  }
  return el(`div.ceo-numerao${tom ? `.${tom}` : ''}`, null, [
    el('span.rot', { texto: rotulo }),
    el('span.val', { texto: valor, title: exato || valor }),
    exato ? el('span.exato', { texto: exato }) : null,
    apoio && apoio.length ? el('div.apoio', null, apoio) : null,
  ]);
}

function faixaNumeros(d) {
  const p = bloco(d.erp, 'pulso');
  const c = bloco(d.erp, 'carteira');
  const s = bloco(d.erp, 'serie');
  const l = p.linhas[0] || null;

  const cartoes = [];

  /* 1. Receita de 12 meses */
  if (!l) {
    cartoes.push(numerao({ rotulo: 'Receita 12 meses', motivo: p.erro || 'o ERP não devolveu linha de pulso' }));
  } else {
    const ticket = l.ctes_12m ? l.receita_12m / l.ctes_12m : null;
    cartoes.push(numerao({
      rotulo: 'Receita 12 meses',
      valor: abreviar(l.receita_12m),
      exato: f.dinheiro(l.receita_12m),
      apoio: [
        el('span', { texto: `${f.numero(l.ctes_12m)} CT-es emitidos` }),
        el('span', { texto: ticket ? `ticket médio ${f.dinheiro(ticket)}` : 'ticket médio indisponível' }),
      ],
    }));
  }

  /* 2. Faturado no mês. A comparação pedida com o mesmo dia do mês anterior não
     é possível: a série do ERP vem mensal, não diária. Então comparamos com o
     fechamento do mês anterior e dizemos que é fechamento, não mesmo dia. */
  if (!l) {
    cartoes.push(numerao({ rotulo: 'Faturado no mês', motivo: p.erro || 'o ERP não devolveu linha de pulso' }));
  } else {
    const meses = s.linhas.filter((x) => x && x.mes);
    const anterior = meses.length >= 2 ? meses[meses.length - 2] : null;
    cartoes.push(numerao({
      rotulo: 'Faturado no mês',
      valor: abreviar(l.receita_mes),
      exato: f.dinheiro(l.receita_mes),
      apoio: [
        el('span', { texto: `${f.numero(l.ctes_mes)} CT-es no mês` }),
        anterior
          ? el('span', { title: f.dinheiro(anterior.receita), texto: `${mesCurto(anterior.mes)} fechou em ${abreviar(anterior.receita)}` })
          : el('span', { texto: 'sem série mensal para comparar' }),
        el('span.frio', { texto: 'mês em curso; a série do ERP é mensal, não dá para comparar com o mesmo dia do mês anterior' }),
      ],
    }));
  }

  /* 3 e 4. Carteira. id_tipo 1 = a receber, id_tipo 2 = a pagar. */
  const carteira = (tipo, rotulo) => {
    const linha = c.linhas.find((x) => Number(x.id_tipo) === tipo);
    if (!linha) {
      return numerao({
        rotulo,
        motivo: c.erro || `o ERP não devolveu a linha de tipo ${tipo} da carteira`,
      });
    }
    const pct = linha.aberto ? (linha.vencido / linha.aberto) * 100 : null;
    return numerao({
      rotulo,
      valor: abreviar(linha.aberto),
      exato: f.dinheiro(linha.aberto),
      apoio: [
        el('span', { texto: `${f.numero(linha.qt)} títulos em aberto` }),
        el('span.ceo-vermelho', {
          title: f.dinheiro(linha.vencido),
          texto: `vencido ${abreviar(linha.vencido)}${pct === null ? '' : ` (${f.numero(pct, 1)}%)`} · ${f.numero(linha.qt_vencido)} títulos`,
        }),
      ],
    });
  };

  cartoes.push(carteira(1, 'A receber em aberto'));
  cartoes.push(carteira(2, 'A pagar em aberto'));

  const hoje = l
    ? el('div.ceo-hoje', null, [
      el('i.pulso.vivo'),
      el('b', { texto: 'hoje, até agora:' }),
      el('span', { texto: `${f.numero(l.ctes_hoje)} CT-es · ${f.dinheiro(l.receita_hoje)}` }),
    ])
    : el('div.ceo-hoje', null, [
      el('i.pulso'),
      el('b', { texto: 'hoje:' }),
      el('span', { texto: `sem leitura — ${p.erro || 'o ERP não devolveu o pulso do dia'}` }),
    ]);

  return el('section.ceo-faixa', null, [
    hoje,
    el('div.ceo-numeroes', null, cartoes),
    carimbo(p, 'Receita e CT-es'),
  ]);
}

/* --------------------------------------------------------- curva mensal --- */

function grafico(d) {
  const s = bloco(d.erp, 'serie');
  if (!s.linhas.length) {
    return painel({
      titulo: 'A curva do faturamento',
      corpo: el('div.aviso-erro', { texto: `Sem série mensal: ${s.erro || 'o ERP não devolveu meses'}` }),
    });
  }

  const linhas = s.linhas.filter((x) => x && x.mes);
  const n = linhas.length;
  const max = Math.max(...linhas.map((x) => Number(x.receita) || 0)) || 1;
  const ns = 'http://www.w3.org/2000/svg';

  /* Escala não uniforme (preserveAspectRatio none) para as barras acompanharem
     a largura da tela; texto e rótulo ficam em HTML, para não distorcerem. */
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${n * 100} 100`);
  svg.setAttribute('preserveAspectRatio', 'none');
  svg.setAttribute('class', 'ceo-svg');
  svg.setAttribute('aria-hidden', 'true');

  [25, 50, 75].forEach((y) => {
    const g = document.createElementNS(ns, 'line');
    g.setAttribute('x1', 0); g.setAttribute('x2', n * 100);
    g.setAttribute('y1', y); g.setAttribute('y2', y);
    g.setAttribute('class', 'ceo-grade-linha');
    g.setAttribute('vector-effect', 'non-scaling-stroke');
    svg.appendChild(g);
  });

  linhas.forEach((x, i) => {
    const parcial = i === n - 1;
    const h = Math.max((Number(x.receita) || 0) / max * 96, 0.8);
    const r = document.createElementNS(ns, 'rect');
    r.setAttribute('x', i * 100 + 20);
    r.setAttribute('width', 60);
    r.setAttribute('y', 100 - h);
    r.setAttribute('height', h);
    r.setAttribute('class', parcial ? 'ceo-barra parcial' : 'ceo-barra');
    if (parcial) r.setAttribute('vector-effect', 'non-scaling-stroke');
    svg.appendChild(r);
  });

  const leitura = el('div.ceo-leitura');
  const dizer = (x, i) => {
    limpar(leitura);
    juntar(leitura, [
      el('b', { texto: mesLongo(x.mes) }),
      el('span', { texto: f.dinheiro(x.receita) }),
      el('span', { texto: `${f.numero(x.qt)} CT-es` }),
      i === n - 1 ? etiqueta('mês em curso, parcial', 'atencao') : null,
    ]);
  };
  dizer(linhas[n - 1], n - 1);

  const colunas = el('div.ceo-colunas', null, linhas.map((x, i) => el('div.ceo-coluna', {
    tabindex: '0',
    title: `${mesLongo(x.mes)} — ${f.dinheiro(x.receita)} · ${f.numero(x.qt)} CT-es${i === n - 1 ? ' (parcial)' : ''}`,
    onmouseenter: () => dizer(x, i),
    onfocus: () => dizer(x, i),
  })));

  const rotulos = el('div.ceo-rotulos', null, linhas.map((x, i) =>
    el(`span${i === n - 1 ? '.parcial' : ''}`, { texto: mesCurto(x.mes) })));

  return painel({
    titulo: 'A curva do faturamento',
    nota: `${f.numero(n)} meses · maior mês ${abreviar(max)}`,
    corpo: [
      leitura,
      el('div.ceo-area', null, [svg, colunas]),
      rotulos,
      el('p.ceo-nota-grafico', { texto: 'A última barra é vazada porque o mês está em curso: comparar com um mês fechado dá falsa impressão de queda.' }),
      carimbo(s, 'Meses'),
    ],
  });
}

/* ---------------------------------------------------- concentração ------- */

function concentracao(d) {
  const c = bloco(d.erp, 'concentracao');
  if (!c.linhas.length) {
    return painel({
      titulo: 'Risco de concentração',
      corpo: el('div.aviso-erro', { texto: `Sem apuração de concentração: ${c.erro || 'o ERP não devolveu grupos'}` }),
    });
  }

  const linhas = c.linhas.slice();
  const soma = linhas.reduce((a, x) => a + (Number(x.pct) || 0), 0);
  const restoPct = Math.max(100 - soma, 0);
  const primeiro = linhas[0];
  const pct1 = Number(primeiro.pct) || 0;
  const tom = pct1 > 35 ? 'erro' : pct1 > 25 ? 'atencao' : 'neutro';

  const segmentos = linhas.map((x, i) => el('span.ceo-seg', {
    style: `width:${(Number(x.pct) || 0)}%;opacity:${(1 - i * 0.09).toFixed(2)}`,
    classe: i === 0 && tom !== 'neutro' ? `forte-${tom}` : '',
    title: `${x.nome} — ${f.dinheiro(x.receita)} · ${f.numero(x.pct, 2)}% da receita`,
  }));
  if (restoPct > 0) {
    segmentos.push(el('span.ceo-seg.demais', {
      style: `width:${restoPct}%`,
      title: `Demais clientes — ${f.numero(restoPct, 2)}% da receita`,
    }));
  }

  const alerta = pct1 > 25
    ? el(`div.ceo-alerta.${tom}`, null, [
      icone('alerta', 18),
      el('div', null, [
        el('b', { texto: `${f.numero(pct1, 1)}% da receita vem de um cliente só.` }),
        el('p', {
          texto: pct1 > 35
            ? `Se ${primeiro.nome} sair, sai mais de um terço da empresa. É o maior risco estrutural da Pianetto hoje.`
            : `Se ${primeiro.nome} sair, sai um quarto da empresa. Vale acompanhar de perto.`,
        }),
      ]),
    ])
    : null;

  const lista = el('ul.ceo-conc-lista', null, linhas.map((x, i) => el('li', null, [
    el('span.pos', { texto: String(i + 1) }),
    el('span.nome', { texto: x.nome, title: `raiz do CNPJ ${x.raiz}` }),
    el('span.receita', { texto: f.dinheiro(x.receita) }),
    el(`span.pct${i === 0 && tom !== 'neutro' ? `.${tom}` : ''}`, { texto: `${f.numero(x.pct, 2)}%` }),
  ])).concat(restoPct > 0 ? [el('li.demais', null, [
    el('span.pos', { texto: '—' }),
    el('span.nome', { texto: 'Demais clientes somados (a consulta não detalha um por um)' }),
    el('span.receita', { texto: f.NADA }),
    el('span.pct', { texto: `${f.numero(restoPct, 2)}%` }),
  ])] : []));

  return painel({
    titulo: 'Risco de concentração',
    nota: `${f.numero(linhas.length)} maiores grupos · receita de 12 meses`,
    corpo: [alerta, el('div.ceo-barra-emp', null, segmentos), lista, carimbo(c, 'Grupos')],
  });
}

/* -------------------------------------------- resultado por setor da empresa */

/* A Pianetto tem dois negócios dentro do mesmo CNPJ, e o custo de cada um mora
   em lugar diferente do ERP. No agenciamento o custo é a carta frete paga ao
   transportador. Na frota própria a carta frete é paga à própria Pianetto — é
   transferência interna, e somá-la como custo inventaria prejuízo; o custo de
   verdade é o caixa amarrado à placa.

   Nada aqui é lucro. É margem de contribuição: não desconta imposto sobre
   receita, comissão, folha da administração nem depreciação. A tela diz isso
   por escrito, porque um número grande sem essa frase vira decisão errada. */

const N = (v) => (v === null || v === undefined || Number.isNaN(Number(v)) ? null : Number(v));

function cartaoSetor({ titulo, apoio, receita, custoRotulo, custo, margem, pct, rodape, tom }) {
  const p = N(pct);
  return el(`div.ceo-setor${tom ? `.${tom}` : ''}`, null, [
    el('header', null, [
      el('h4', { texto: titulo }),
      el('span.ceo-setor-apoio', { texto: apoio }),
    ]),
    el('div.ceo-setor-margem', null, [
      el('b', { texto: p === null ? f.NADA : `${f.numero(p, 1)}%` }),
      el('span', { texto: 'de margem de contribuição' }),
    ]),
    el('dl.ceo-setor-linhas', null, [
      el('div', null, [el('dt', { texto: 'Receita' }), el('dd', { texto: f.dinheiro(receita) })]),
      el('div', null, [el('dt', { texto: custoRotulo }), el('dd', { texto: f.dinheiro(custo) })]),
      el('div.forte', null, [el('dt', { texto: 'Sobra' }), el('dd', { texto: f.dinheiro(margem) })]),
    ]),
    rodape ? el('p.ceo-setor-rodape', { texto: rodape }) : null,
  ]);
}

function setores(d) {
  const s = bloco(d.erp, 'setor');
  const a = bloco(d.erp, 'agencia');
  const dias = (d.erp && d.erp.setor && d.erp.setor.janela_dias) || 90;

  if (!s.linhas.length) {
    return painel({
      titulo: 'Resultado por setor',
      corpo: el('div.aviso-erro', {
        texto: `Sem apuração por setor: ${s.erro || 'o ERP não devolveu linha de setor'}. Nenhum valor foi estimado no lugar.`,
      }),
    });
  }

  const por = {};
  s.linhas.forEach((l) => { por[l.setor] = l; });
  const frota = por.frota_propria || {};
  const terc = por.terceiro || {};
  const agreg = por.agregado || {};
  const semClasse = por.sem_classificacao || null;

  /* Agregado é veículo de terceiro com vínculo fixo: o custo continua sendo
     carta frete que sai da empresa. Soma com terceiro para formar o setor de
     agenciamento, e fica escrito embaixo que ele está dentro. */
  const agRec = (N(terc.vl_receita) || 0) + (N(agreg.vl_receita) || 0);
  const agCusto = (N(terc.vl_frete_terceiro) || 0) + (N(agreg.vl_frete_terceiro) || 0);
  const agMargem = agRec - agCusto;
  const agPct = agRec ? (agMargem / agRec) * 100 : null;
  const agCtes = (N(terc.qt_ctes) || 0) + (N(agreg.qt_ctes) || 0);
  const semCusto = (N(terc.qt_sem_custo) || 0) + (N(agreg.qt_sem_custo) || 0);
  const semCustoVl = (N(terc.vl_sem_custo) || 0) + (N(agreg.vl_sem_custo) || 0);

  const frRec = N(frota.vl_receita) || 0;
  const frCusto = N(frota.vl_custo_frota) || 0;
  const frMargem = N(frota.vl_margem);
  const frPct = N(frota.pr_margem);

  const cartoes = el('div.ceo-setores', null, [
    cartaoSetor({
      titulo: 'Agenciamento',
      apoio: `${f.numero(agCtes)} CT-e(s) em ${dias} dias · veículo de terceiro e agregado`,
      receita: agRec,
      custoRotulo: 'Carta frete paga a terceiro',
      custo: agCusto,
      margem: agMargem,
      pct: agPct,
      tom: 'agencia',
      rodape: `Inclui ${f.numero(N(agreg.qt_ctes) || 0)} CT-e(s) de agregado, ${f.dinheiro(N(agreg.vl_receita) || 0)} de receita.`,
    }),
    cartaoSetor({
      titulo: 'Frota própria',
      apoio: `${f.numero(N(frota.qt_ctes) || 0)} CT-e(s) em ${dias} dias · ${f.numero(N(frota.lancamentos_de_caixa) || N(frota.qt_lancamentos_frota) || 0)} lançamentos de caixa nos veículos`,
      receita: frRec,
      custoRotulo: 'Caixa lançado nos veículos',
      custo: frCusto,
      margem: frMargem,
      pct: frPct,
      tom: 'frota',
      rodape: `A carta frete destes CT-es, ${f.dinheiro(N(frota.vl_carta_interna) || 0)}, é paga à própria Pianetto: é transferência interna e ficou fora do custo.`,
    }),
  ]);

  const ressalvas = [
    'Isto é margem de contribuição, não lucro: não desconta ICMS, PIS/COFINS, comissão, folha da administração nem depreciação.',
  ];
  if (semCusto) {
    ressalvas.push(`${f.numero(semCusto)} CT-e(s) de terceiro, ${f.dinheiro(semCustoVl)} de receita, ainda não têm carta frete lançada: entraram na receita e não no custo, então a margem do agenciamento está por cima.`);
  }
  ressalvas.push('O que não foi apontado a uma placa — pneu em estoque, oficina, administração da frota — não está no custo da frota.');
  if (semClasse && N(semClasse.qt_ctes)) {
    ressalvas.push(`${f.numero(N(semClasse.qt_ctes))} CT-e(s), ${f.dinheiro(N(semClasse.vl_receita) || 0)}, estão sem o tipo de proprietário do veículo preenchido e não couberam em setor nenhum.`);
  }

  /* ---------------------------------------------------------- as agências */
  let tabela;
  if (!a.linhas.length) {
    tabela = el('div.aviso-erro', {
      texto: `Sem quebra por agência: ${a.erro || 'o ERP não devolveu agências'}.`,
    });
  } else {
    const linhas = a.linhas.map((l) => {
      const rec = N(l.vl_receita) || 0;
      const desp = N(l.vl_despesa_agencia) || 0;
      const recFrota = N(l.vl_receita_frota) || 0;
      const engole = rec > 0 && desp / rec > 0.40;
      const soFrota = rec > 0 && recFrota / rec > 0.20;
      return {
        ...l,
        comparavel: !(engole || soFrota),
        motivo: engole
          ? 'o centro de custo ligado a esta unidade recebe despesa que não é dela — matriz e administração caem aqui'
          : soFrota
            ? 'a receita é de frota própria, e o custo do veículo não é rateado por agência: o resultado sobe sozinho'
            : null,
      };
    });
    const comp = linhas.filter((l) => l.comparavel).sort((x, y) => (N(y.vl_resultado) || 0) - (N(x.vl_resultado) || 0));
    const fora = linhas.filter((l) => !l.comparavel).sort((x, y) => (N(y.vl_receita) || 0) - (N(x.vl_receita) || 0));
    const negativas = comp.filter((l) => (N(l.vl_resultado) || 0) < 0);

    const corpo = (arr, dentro) => arr.map((l) => {
      const res = N(l.vl_resultado);
      const pr = N(l.pr_resultado);
      const tom = !dentro ? 'fora' : res < 0 ? 'erro' : pr !== null && pr < 5 ? 'atencao' : '';
      return el(`tr${tom ? `.${tom}` : ''}`, null, [
        el('td.nome', null, [
          el('span', { texto: (l.nm_agencia || '').replace(/^PIANETTO\s*-*\s*/i, '') || l.nm_agencia || f.NADA }),
          l.motivo ? el('span.selo-fora', { texto: 'fora da comparação', title: l.motivo }) : null,
          !l.id_centro_custo_ligado ? el('span.selo-fora', { texto: 'sem centro de custo', title: 'nenhum centro de custo está ligado a esta agência, então a despesa dela não aparece' }) : null,
        ]),
        el('td.num', { texto: f.numero(N(l.qt_ctes) || 0) }),
        el('td.num', { texto: abreviar(N(l.vl_receita)) , title: f.dinheiro(N(l.vl_receita)) }),
        el('td.num', { texto: abreviar(N(l.vl_margem_bruta)), title: `receita menos carta frete: ${f.dinheiro(N(l.vl_margem_bruta))}` }),
        el('td.num', { texto: abreviar(N(l.vl_despesa_agencia)), title: `despesa do centro de custo: ${f.dinheiro(N(l.vl_despesa_agencia))}` }),
        el('td.num.res', { texto: dentro ? abreviar(res) : f.NADA, title: dentro ? f.dinheiro(res) : (l.motivo || '') }),
        el('td.num.pct', { texto: dentro && pr !== null ? `${f.numero(pr, 1)}%` : f.NADA }),
      ]);
    });

    tabela = el('div.ceo-agencias', null, [
      /* No celular a tabela nao cabe: a coluna do nome fica ancorada e o resto
         corre por baixo dela. Sem este aviso, meia coluna cortada na borda
         passa por numero inteiro. */
      el('p.ceo-arrasta', {
        texto: 'No celular esta tabela mostra receita, resultado e margem. CT-e emitidos, frete pago e despesa lançada ficam na tela grande.',
      }),
      el('table.tab', null, [
        el('thead', null, [el('tr', null, [
          el('th', { texto: 'Agência' }),
          el('th.num', { texto: 'CT-e' }),
          el('th.num', { texto: 'Receita' }),
          el('th.num', { texto: 'Menos frete' }),
          el('th.num', { texto: 'Despesa' }),
          el('th.num', { texto: 'Resultado' }),
          el('th.num', { texto: '%' }),
        ])]),
        el('tbody', null, corpo(comp, true)),
        fora.length ? el('tbody.ceo-fora', null, [
          el('tr.sep', null, [el('td', { colspan: '7', texto: `${f.numero(fora.length)} unidade(s) fora da comparação — o número delas não é comparável com o das outras, e por isso não é apresentado como resultado` })]),
          ...corpo(fora, false),
        ]) : null,
      ]),
      el('p.ceo-carimbo', {
        texto: `${f.numero(comp.length)} agência(s) comparáveis, ${f.numero(negativas.length)} no vermelho · janela de ${dias} dias`,
      }),
    ]);
  }

  return painel({
    titulo: 'Resultado por setor',
    nota: `Últimos ${dias} dias · margem de contribuição, não lucro`,
    corpo: [
      cartoes,
      contraprova(d),
      el('ul.ceo-ressalvas', null, ressalvas.map((t) => el('li', { texto: t }))),
      el('h4.ceo-sub', { texto: 'Por agência' }),
      tabela,
      el('h4.ceo-sub', { texto: 'Por veículo — frota própria' }),
      veiculos(d, dias),
      planoFrota(d),
      carimbo(s, 'Setores'),
    ],
  });
}

/* ------------------------------------------- o que fazer com cada placa -- */

/* Saber quem está no vermelho não tira ninguém do vermelho. Este bloco é a
   parte que vira ordem do dia: por placa, o que está fora da mediana da casa,
   a medida concreta, quem executa e quanto vale se for feita. O ganho é
   estimativa de contribuição, nunca lucro, e vem sempre com a dúvida do
   auditor ao lado — o plano se apoia na quilometragem declarada no CT-e, e é
   ela que a Vera confere pelo hodômetro do abastecimento. */
function planoFrota(d) {
  const p = d.plano_frota || null;
  if (!p) {
    return el('div.ceo-plano.falha', null, [
      el('h4', { texto: 'Plano por veículo' }),
      el('p', {
        texto: 'O Controller ainda não entregou o plano placa a placa. A varredura roda todo dia às 18h; enquanto ela não fechar, a tabela acima diz quem está no vermelho mas não diz o que fazer.',
      }),
    ]);
  }

  const dd = p.dados || {};
  const linhas = Array.isArray(dd.plano) ? dd.plano : [];
  const c = p.contestacao || null;
  const contesta = c && c.veredito === 'contradiz';

  const numero = (rot, valor, apoio) => el('div.ceo-plano-num', null, [
    el('span.rot', { texto: rot }),
    el('b', { texto: valor, title: valor }),
    el('span.apoio', { texto: apoio }),
  ]);

  const cabeca = el('div.ceo-plano-topo', null, [
    el('h4', { texto: 'Plano por veículo' }),
    el('span.ceo-plano-quem', {
      texto: `${p.analista || 'Controladoria'} · ${diaPorExtenso(p.dita_em)} às ${horaSeg(p.dita_em)} · missão ${p.missao_id}`,
    }),
  ]);

  const resumo = el('div.ceo-plano-nums', null, [
    numero('Cavalos lidos', f.numero(N(dd.veiculos_analisados) || 0),
      `${f.numero(N(dd.veiculos_com_apontamento) || 0)} com ponto fora da mediana`),
    numero('No vermelho', f.numero(N(dd.veiculos_no_vermelho) || 0),
      `${f.dinheiro(Math.abs(N(dd.vermelho_total) || 0))} de contribuição negativa`),
    numero('Preço e consumo na mediana', f.dinheiro(N(dd.ganho_estimado_total) || 0),
      'se cada placa fora da curva voltar para a mediana da casa'),
    numero('Encher a agenda das paradas', f.dinheiro(N(dd.ganho_giro_total) || 0),
      'estimativa mais frágil: depende de haver carga na praça'),
    N(dd.litros_periodo) ? numero('Diesel da frota',
      f.dinheiro(N(dd.diesel_periodo) || 0),
      `${f.numero(N(dd.litros_periodo))} litros · mediana ${f.dinheiro(N(dd.mediana_preco_litro) || 0)} o litro`) : null,
    N(dd.mediana_km_por_litro) ? numero('Consumo da casa',
      `${f.numero(N(dd.mediana_km_por_litro), 2)} km/l`,
      `mediana de ${f.numero(N(dd.placas_com_km_litro) || 0)} placas com painel lido em todo abastecimento`) : null,
  ]);

  const medida = (m) => el('li', null, [
    el('span.acao', { texto: m.acao }),
    el('span.porque', { texto: m.porque }),
    el('span.quem', null, [
      el('b', { texto: m.quem }),
      N(m.ganho) ? el('span.ganho', { texto: `vale ${f.dinheiro(N(m.ganho))}` }) : null,
    ]),
  ]);

  const cartao = (l) => el(`div.ceo-placa${l.no_vermelho ? '.vermelho' : ''}`, null, [
    el('div.ceo-placa-topo', null, [
      el('b.mono', { texto: l.placa }),
      el('span.modelo', { texto: l.modelo || 'sem modelo no cadastro' }),
      el('span.contrib', {
        texto: `${f.dinheiro(N(l.contribuicao) || 0)} de contribuição`,
      }),
      el(`span.confianca.${l.confianca || 'media'}`, {
        texto: `confiança ${l.confianca || 'media'}`,
      }),
    ]),
    el('div.ceo-placa-nums', {
      texto: `${f.numero(N(l.ctes) || 0)} CT-e · ${f.numero(N(l.km) || 0)} km · ${f.numero(N(l.km_dia) || 0, 1)} km/dia · receita ${f.numero(N(l.receita_por_km) || 0, 2)}/km · combustível ${f.numero(N(l.combustivel_por_km) || 0, 2)}/km`,
    }),
    /* O diesel aberto: litro comprado, preço pago e quilômetro por litro medido
       no painel. Placa sem painel lido em todo abastecimento não recebe km/l
       inventado — recebe o motivo escrito. */
    N(l.litros) ? el('div.ceo-placa-diesel', {
      texto: `${f.numero(N(l.litros))} litros · ${f.dinheiro(N(l.preco_litro) || 0)} o litro · ${
        N(l.km_por_litro)
          ? `${f.numero(N(l.km_por_litro), 2)} km por litro`
          : (N(l.abast_sem_hodometro)
            ? `sem km/l: ${f.numero(N(l.abast_sem_hodometro))} de ${f.numero(N(l.abastecimentos) || 0)} abastecimentos sem hodômetro`
            : 'sem km/l: leitura de painel fora da faixa aferível')
      }`,
    }) : null,
    el('ul.ceo-sintomas', null,
      (l.sintomas || []).map((t) => el('li', { texto: t }))),
    el('ul.ceo-medidas', null, (l.medidas || []).map(medida)),
  ]);

  const corpo = [cabeca, resumo, el('p.ceo-plano-frase', { texto: p.resumo })];

  if (contesta) {
    corpo.push(el('div.ceo-plano-duvida', null, [
      el('span.ceo-selo-veredito.erro', { texto: 'o auditor contesta este plano' }),
      el('p', { texto: `${c.auditor}: ${c.resumo}` }),
      el('span.ceo-plano-quem', {
        texto: `dito ${haQuanto(c.dita_em) || ''} — conferência pelo hodômetro do abastecimento, caminho que não passa pelo conhecimento`,
      }),
    ]));
  } else if (c) {
    corpo.push(el('div.ceo-plano-duvida.ok', null, [
      el('span.ceo-selo-veredito.ok', { texto: 'quilometragem conferida' }),
      el('p', { texto: `${c.auditor}: ${c.resumo}` }),
    ]));
  } else {
    corpo.push(el('p.ceo-contra-nota', {
      texto: 'Nenhum auditor conferiu esta quilometragem ainda. O plano acima se apoia na distância declarada no conhecimento, sem segunda fonte.',
    }));
  }

  corpo.push(el('div.ceo-placas', null, linhas.map(cartao)));

  const semMedida = dd.vermelho_sem_apontamento || [];
  if (semMedida.length) {
    corpo.push(el('p.ceo-plano-limpas', {
      texto: `No vermelho sem apontamento: ${semMedida.join(', ')}. Estas placas fecharam com custo acima da receita, mas estão dentro da mediana da casa em giro, preço e consumo — o prejuízo delas não tem causa isolada nesta janela, e por isso entram na conta do vermelho sem medida atribuída.`,
    }));
  }

  const limpas = dd.veiculos_sem_apontamento || [];
  if (limpas.length) {
    corpo.push(el('p.ceo-plano-limpas', {
      texto: `Sem apontamento: ${limpas.join(', ')}. Estas placas estão dentro da mediana da casa em giro, preço e consumo — nada a fazer com elas nesta rodada.`,
    }));
  }

  return el(`div.ceo-plano${contesta ? '.diverge' : ''}`, null, corpo);
}

/* ------------------------------------------------- resultado por veículo -- */

/* A frota própria não é um bloco só. Trinta cavalos puxam CT-e e têm receita
   com nome; o resto do cadastro — carretas, dollys, carros, moto — só gera
   despesa, e despesa sem receita própria não é prejuízo, é custo de apoio.
   Misturar os dois num número só esconde as duas coisas ao mesmo tempo. */

/* O que sobra depois de combustível e manutenção: pedágio, pessoal, lavagem,
   estacionamento, carga e descarga. Vem por subtração para nunca somar mais
   que o total lançado na placa. */
function outros(l) {
  const t = N(l.vl_custo_identificavel) || 0;
  const c = (N(l.vl_combustivel) || 0) + (N(l.vl_manutencao) || 0);
  return Math.max(0, t - c);
}

function veiculos(d, dias) {
  const q = bloco(d.erp, 'veiculo');
  if (!q.linhas.length) {
    return el('div.aviso-erro', {
      texto: `Sem quebra por veículo: ${q.erro || 'o ERP não devolveu placas'}.`,
    });
  }

  /* Frota própria é o que o cadastro diz que é próprio. Placa da casa que
     emitiu conhecimento como agregado ou terceiro tem essa receita contada
     aqui: o custo dela já está inteiro nesta tabela, e metade da conta não é
     resultado. A parcela reclassificada aparece no rótulo, nunca diluída. */
  const puxa = [];
  const apoio = [];
  q.linhas.forEach((l) => {
    l._ctesAgr = N(l.qt_ctes_agregado) || 0;
    l._recAgr = N(l.vl_receita_agregado) || 0;
    l._ctes = (N(l.qt_ctes) || 0) + l._ctesAgr;
    l._rec = (N(l.vl_receita) || 0) + l._recAgr;
    l._con = l._rec - (N(l.vl_custo_identificavel) || 0);
    l._pr = l._rec ? (l._con / l._rec) * 100 : null;
    (l._ctes > 0 ? puxa : apoio).push(l);
  });
  puxa.sort((x, y) => y._con - x._con);
  apoio.sort((x, y) => (N(y.vl_custo_identificavel) || 0) - (N(x.vl_custo_identificavel) || 0));

  const recPuxa = puxa.reduce((t, l) => t + l._rec, 0);
  const cusPuxa = puxa.reduce((t, l) => t + (N(l.vl_custo_identificavel) || 0), 0);
  const cusApoio = apoio.reduce((t, l) => t + (N(l.vl_custo_identificavel) || 0), 0);
  const negativos = puxa.filter((l) => l._con < 0);
  const cusTotal = cusPuxa + cusApoio;
  const combTotal = q.linhas.reduce((t, l) => t + (N(l.vl_combustivel) || 0), 0);
  const manutTotal = q.linhas.reduce((t, l) => t + (N(l.vl_manutencao) || 0), 0);
  const perdaNeg = negativos.reduce((t, l) => t + l._con, 0);
  const mistas = puxa.filter((l) => l._ctesAgr > 0);
  const recMista = mistas.reduce((t, l) => t + l._recAgr, 0);

  const linha = (l) => {
    const con = l._con;
    const pr = l._pr;
    const tom = con < 0 ? 'erro' : pr !== null && pr < 10 ? 'atencao' : '';
    return el(`tr${tom ? `.${tom}` : ''}`, null, [
      el('td.nome', null, [
        el('span', { texto: l.ds_placa || f.NADA }),
        el('span.ceo-modelo', { texto: `${l.nr_frota ? `frota ${l.nr_frota} · ` : ''}${l.ds_modelo || l.nm_tipo_veiculo || ''}` }),
      ]),
      el('td.num', {
        texto: f.numero(l._ctes),
        title: l._ctesAgr ? `${f.numero(N(l.qt_ctes) || 0)} como frota própria e ${f.numero(l._ctesAgr)} emitidos como agregado ou terceiro na mesma placa` : '',
      }),
      el(`td.num${l._ctesAgr ? '.reclass' : ''}`, {
        texto: abreviar(l._rec),
        title: l._ctesAgr ? `${f.dinheiro(l._rec)}, dos quais ${f.dinheiro(l._recAgr)} vieram de CT-e classificado como agregado ou terceiro nesta placa própria` : f.dinheiro(l._rec),
      }),
      el('td.num', { texto: abreviar(N(l.vl_combustivel)), title: `combustível: ${f.dinheiro(N(l.vl_combustivel))}` }),
      el('td.num', { texto: abreviar(N(l.vl_manutencao)), title: `manutenção, peça, pneu e borracharia lançados nesta placa: ${f.dinheiro(N(l.vl_manutencao))}` }),
      el('td.num', { texto: abreviar(outros(l)), title: `pedágio, pessoal, lavagem, estacionamento e demais lançamentos: ${f.dinheiro(outros(l))}` }),
      el('td.num', { texto: abreviar(N(l.vl_custo_identificavel)), title: `tudo que foi lançado nesta placa: ${f.dinheiro(N(l.vl_custo_identificavel))}` }),
      el('td.num.res', { texto: abreviar(con), title: f.dinheiro(con) }),
      el('td.num.pct', { texto: pr !== null ? `${f.numero(pr, 1)}%` : f.NADA }),
    ]);
  };

  const linhaApoio = (l) => el('tr.fora', null, [
    el('td.nome', null, [
      el('span', { texto: l.ds_placa || f.NADA }),
      el('span.ceo-modelo', { texto: l.nm_tipo_veiculo || l.ds_modelo || '' }),
    ]),
    el('td.num', { texto: '0' }),
    el('td.num', { texto: f.NADA }),
    el('td.num', { texto: abreviar(N(l.vl_combustivel)), title: f.dinheiro(N(l.vl_combustivel)) }),
    el('td.num', { texto: abreviar(N(l.vl_manutencao)), title: f.dinheiro(N(l.vl_manutencao)) }),
    el('td.num', { texto: abreviar(outros(l)), title: f.dinheiro(outros(l)) }),
    el('td.num', { texto: abreviar(N(l.vl_custo_identificavel)), title: f.dinheiro(N(l.vl_custo_identificavel)) }),
    el('td.num.res', { texto: f.NADA, title: 'não emite CT-e no próprio nome: a receita entra no cavalo que puxa' }),
    el('td.num.pct', { texto: f.NADA }),
  ]);

  /* Cavalo é veículo de tração: ele existe para puxar CT-e. Cavalo com custo e
     sem nenhum CT-e no período não é apoio, é veículo parado gastando — e isso
     não pode ficar escondido no meio das carretas. */
  const paradosTracao = apoio.filter((l) => l.id_tracao);
  const custoParado = paradosTracao.reduce((t, l) => t + (N(l.vl_custo_identificavel) || 0), 0);

  return el('div.ceo-agencias.ceo-veiculos', null, [
    el('p.ceo-arrasta', {
      texto: 'No celular esta tabela mostra receita, despesa, sobra e margem. CT-e, combustível, manutenção e outros ficam na tela grande.',
    }),
    el('p.ceo-linha-topo', {
      texto: `${f.numero(puxa.length)} veículo(s) puxam receita: ${f.dinheiro(recPuxa)} contra ${f.dinheiro(cusPuxa)} de despesa lançada na placa, sobra de ${f.dinheiro(recPuxa - cusPuxa)}. Outros ${f.numero(apoio.length)} — carreta, dolly, carro, moto — somam ${f.dinheiro(cusApoio)} de despesa sem receita própria.`,
    }),
    mistas.length ? el('p.ceo-contra-nota', {
      texto: `${f.numero(mistas.length)} placa(s) do cadastro próprio emitiram conhecimento como agregado ou terceiro no período — ${mistas.map((l) => l.ds_placa).join(', ')}, ${f.dinheiro(recMista)}. Como o cavalo é da casa e a despesa dele está inteira nesta tabela, essa receita está contada aqui e sai do agenciamento na mesma medida. A classificação do documento continua a corrigir.`,
    }) : null,
    paradosTracao.length ? el('p.ceo-contra-nota.erro', {
      texto: `${f.numero(paradosTracao.length)} veículo(s) de tração gastaram ${f.dinheiro(custoParado)} sem emitir um único CT-e em ${dias} dias: ${paradosTracao.map((l) => l.ds_placa).join(', ')}. Cavalo existe para puxar carga — parado, é só custo.`,
    }) : null,
    el('table.tab', null, [
      el('thead', null, [el('tr', null, [
        el('th', { texto: 'Placa' }),
        el('th.num', { texto: 'CT-e' }),
        el('th.num', { texto: 'Receita' }),
        el('th.num', { texto: 'Combustível' }),
        el('th.num', { texto: 'Manutenção' }),
        el('th.num', { texto: 'Outros' }),
        el('th.num', { texto: 'Despesa' }),
        el('th.num', { texto: 'Sobra' }),
        el('th.num', { texto: '%' }),
      ])]),
      el('tbody', null, puxa.map(linha)),
      apoio.length ? el('tbody.ceo-fora', null, [
        el('tr.sep', null, [el('td', {
          colspan: '9',
          texto: `${f.numero(apoio.length)} unidade(s) de apoio — não emitem CT-e no próprio nome, então têm despesa e não têm receita. Isto não é prejuízo: é custo da frota que já está no cálculo do setor.`,
        })]),
        /* Só as dez mais caras aparecem. Setenta e cinco linhas de carreta e
           carro empurram o resto da Sala do CEO para fora da tela, e o que
           decide aqui é o topo da lista, não a cauda. */
        ...apoio.slice(0, 10).map(linhaApoio),
        apoio.length > 10 ? el('tr.sep', null, [el('td', {
          colspan: '9',
          texto: `As outras ${f.numero(apoio.length - 10)} unidades de apoio somam ${f.dinheiro(apoio.slice(10).reduce((t, l) => t + (N(l.vl_custo_identificavel) || 0), 0))} — nenhuma passa de ${f.dinheiro(N(apoio[10].vl_custo_identificavel) || 0)}.`,
        })]) : null,
      ]) : null,
    ]),
    el('p.ceo-contra-nota', {
      texto: `Combustível é ${f.numero(cusTotal ? (combTotal / cusTotal) * 100 : 0, 0)}% de tudo que desce na placa; manutenção lançada por placa é só ${f.numero(cusTotal ? (manutTotal / cusTotal) * 100 : 0, 0)}%. Oficina própria, peça em estoque e administração da frota não são apontadas a um veículo — a despesa real de cada placa é maior que a desta tabela.`,
    }),
    el('p.ceo-carimbo', {
      texto: negativos.length
        ? `${f.numero(negativos.length)} de ${f.numero(puxa.length)} veículos gastaram mais do que faturaram: ${f.dinheiro(perdaNeg)} · janela de ${dias} dias`
        : `Nenhum veículo com receita fechou no vermelho · janela de ${dias} dias`,
    }),
    carimbo(q, 'Resultado por veículo'),
  ]);
}

/* ------------------------------------------- contraprova do custo da frota */

/* A margem da frota vale o que vale o custo dela. Aqui o custo é refeito por
   outro caminho do banco — o centro de custo, que é como a contabilidade
   enxerga a mesma despesa — e o resultado dos dois caminhos fica lado a lado.
   Se divergirem muito, o número de cima é teto, não fato.

   Quem assina a contestação é um agente, com nome e hora. Contraprova sem
   autor é auditoria de enfeite. */

function contraprova(d) {
  const q = bloco(d.erp, 'contraprova_frota');
  const dito = d.contraprova_frota || null;

  const custo = {};
  let cartaFora = 0;
  let cartaInterna = null;
  q.linhas.forEach((l) => {
    if (l.linha === 'custo') custo[l.caminho] = l;
    else if (l.linha === 'carta_frete_propria') {
      if (/PIANETTO/i.test(String(l.nm_recebedor || ''))) cartaInterna = l;
      else cartaFora += N(l.vl) || 0;
    }
  });
  const cv = custo.caixa_veiculo || null;
  const cc = custo.centro_custo || null;

  if (!cv || !cc) {
    return el('div.ceo-contra.falha', null, [
      el('p', { texto: `Contraprova indisponível: ${q.erro || 'o ERP não devolveu os dois caminhos de custo'}. O custo da frota acima segue sem conferência independente.` }),
    ]);
  }

  const vCv = N(cv.vl) || 0;
  const vCc = N(cc.vl) || 0;
  const dif = vCv - vCc;
  const prDif = vCv ? (Math.abs(dif) / vCv) * 100 : 0;
  const fecha = prDif <= 10 && cartaFora === 0;

  const via = (rot, l, valor, apoio, forte) => el(`div.ceo-via${forte ? '.forte' : ''}`, null, [
    el('span.rot', { texto: rot }),
    el('b', { texto: f.dinheiro(valor), title: f.dinheiro(valor) }),
    el('span.apoio', { texto: apoio }),
  ]);

  const selo = el(`span.ceo-selo-veredito.${fecha ? 'ok' : 'erro'}`, {
    texto: fecha ? 'os dois caminhos fecham' : 'os dois caminhos não fecham',
  });

  const frase = fecha
    ? `Diferença de ${f.dinheiro(Math.abs(dif))} entre os dois caminhos, ${f.numero(prDif, 1)}% — dentro do que se explica pelas ${f.numero(N(cv.qt_chaves) || 0)} placas ativas contra apenas ${f.numero(N(cc.qt_chaves) || 0)} centros de custo de frota abertos. O custo da frota se sustenta.`
    : `Diferença de ${f.dinheiro(Math.abs(dif))} entre os dois caminhos, ${f.numero(prDif, 1)}%. Enquanto isso não for explicado, a margem da frota é um teto, não um número fechado.`;

  const corpo = [
    el('div.ceo-contra-topo', null, [
      el('h4', { texto: 'Contraprova do custo da frota' }),
      selo,
    ]),
    el('div.ceo-vias', null, [
      via('Pelo caixa do veículo', cv, vCv,
        `${f.numero(N(cv.qt) || 0)} lançamentos em ${f.numero(N(cv.qt_chaves) || 0)} placas ativas · caminho usado no cálculo acima`, true),
      el('span.ceo-vs', { texto: 'contra' }),
      via('Pelo centro de custo', cc, vCc,
        `${f.numero(N(cc.qt) || 0)} lançamentos em ${f.numero(N(cc.qt_chaves) || 0)} centros de custo de frota · caminho da contabilidade`),
    ]),
    el('p.ceo-contra-frase', { texto: frase }),
  ];

  /* O teste que decide se a carta frete da frota é custo ou transferência: o
     nome de quem recebeu. Enquanto for a própria Pianetto, é dinheiro trocando
     de bolso dentro de casa. */
  if (cartaInterna) {
    corpo.push(el('p.ceo-contra-nota', {
      texto: `Carta frete dos CT-es de frota própria: ${f.dinheiro(N(cartaInterna.vl) || 0)} em ${f.numero(N(cartaInterna.qt) || 0)} cartas, todas pagas a ${cartaInterna.nm_recebedor}. É a própria empresa — por isso ficou fora do custo.`,
    }));
  }
  if (cartaFora > 0) {
    corpo.push(el('p.ceo-contra-nota.erro', {
      texto: `Atenção: ${f.dinheiro(cartaFora)} de carta frete de CT-e de frota própria foram para transportador de fora. Esse valor é custo de verdade e não está no cálculo acima.`,
    }));
  }

  if (dito) {
    const vd = String(dito.veredito || '');
    const rotulo = vd === 'confirma' ? 'confirmou' : vd === 'contradiz' ? 'contestou' : 'não conseguiu verificar';
    /* A contraprova é diária. Se a última palavra tem mais de trinta horas, a
       varredura falhou, e isso precisa aparecer: veredito velho exibido sem
       ressalva vira aval que ninguém deu hoje. */
    const t = Date.parse(dito.dita_em || '');
    const horas = Number.isNaN(t) ? null : (Date.now() - t) / 3600000;
    const velho = horas !== null && horas > 30;
    corpo.push(el(`div.ceo-assinatura.${velho ? 'velho' : vd === 'contradiz' ? 'erro' : vd === 'confirma' ? 'ok' : ''}`, null, [
      el('span.quem', { texto: `${dito.auditor}${dito.papel ? `, ${dito.papel}` : ''}, ${rotulo}` }),
      el('p', { texto: dito.resumo }),
      el('span.quando', {
        texto: `dito ${haQuanto(dito.dita_em) || ''} — ${diaPorExtenso(dito.dita_em)} às ${horaSeg(dito.dita_em)} · missão ${dito.missao_id}`,
      }),
      velho ? el('span.atraso', {
        texto: 'esta contraprova roda todo dia às 17h; a última não é de hoje, então os números acima estão sem conferência de hoje',
      }) : null,
    ]));
  } else {
    corpo.push(el('p.ceo-contra-nota', {
      texto: 'Nenhum auditor se pronunciou ainda sobre este custo. Os dois caminhos acima são leitura direta do banco, sem veredito de agente. A varredura que chama o Controller roda todo dia às 17h.',
    }));
  }

  corpo.push(carimbo(q, 'Caminhos de custo'));
  return el(`div.ceo-contra${fecha ? '' : '.diverge'}`, null, corpo);
}

/* --------------------------------------------------------------- equipe -- */

function cartaoAgente(a) {
  const trabalhando = a.trabalhando_agora === true;
  const habilitado = a.situacao === 'habilitado';
  const classe = trabalhando ? '.trabalhando' : habilitado ? '.pronto' : '.parado';
  const inicial = (a.nome || a.codigo || '?').trim().charAt(0).toUpperCase();

  let estado;
  if (trabalhando) {
    estado = el('div.estado.acento', null, [el('i.pulso.vivo'), el('span', { texto: 'trabalhando agora' })]);
  } else if (habilitado) {
    const q = haQuanto(a.ultima_vez);
    estado = el('div.estado.ok', null, [
      el('i.pulso'),
      el('span', {
        title: a.ultima_vez ? f.dataHora(a.ultima_vez) : 'nunca operou',
        texto: `de prontidão · ${f.numero(a.tarefas)} tarefas${q ? ` · última ${q}` : ' · sem registro de última vez'}`,
      }),
    ]);
  } else {
    estado = el('div.estado.frio', null, [
      el('i.pulso.apagado'),
      el('span', { texto: a.limitacao || 'sem integração declarada' }),
    ]);
  }

  return el(`div.ceo-agente${classe}`, null, [
    el('div.mono-inicial', { texto: inicial }),
    el('div.quem', null, [
      el('b', { texto: a.nome || a.codigo }),
      el('span.papel', { texto: a.papel || a.codigo }),
      el('span.area', { texto: a.area || '—' }),
    ]),
    estado,
  ]);
}

function equipe(d) {
  const lista = Array.isArray(d.equipe) ? d.equipe : [];
  if (!lista.length) {
    return painel({
      titulo: 'A equipe de agentes',
      corpo: el('div.aviso-erro', { texto: 'A API não devolveu a equipe. Nenhum agente foi inventado para preencher o espaço.' }),
    });
  }
  const operando = lista.filter((a) => a.situacao === 'habilitado').length;
  const esperando = lista.length - operando;
  const agora = lista.filter((a) => a.trabalhando_agora === true).length;

  return painel({
    titulo: 'A equipe de agentes',
    nota: `${f.numero(operando)} de ${f.numero(lista.length)} operando · ${f.numero(esperando)} esperando integração${agora ? ` · ${f.numero(agora)} trabalhando agora` : ''}`,
    corpo: [
      el('div.ceo-equipe', null, lista.map(cartaoAgente)),
      el('p.ceo-carimbo', { texto: 'Quem está sem integração não é erro nem enfeite: é o mapa do que falta construir.' }),
    ],
  });
}

/* ------------------------------------------------------------- operação -- */

function operacao(d, ir) {
  const o = d.operacao || {};
  const emCurso = Array.isArray(o.em_curso) ? o.em_curso : [];

  const missoes = emCurso.length
    ? el('ul.ceo-missoes', null, emCurso.map((m) => el('li', null,
      el('button.ceo-missao', { type: 'button', onclick: () => ir(`missoes/${m.id}`) }, [
        el('div', null, [
          el('b', { texto: f.textoBr(m.objetivo || `Missão ${m.id}`) }),
          el('span.meta', { texto: `#${m.id} · aberta ${haQuanto(m.criada_em) || f.dataHora(m.criada_em)}` }),
        ]),
        el('div.direita', null, [etiqueta(f.estadoMissao(m.estado).texto, f.estadoMissao(m.estado).tom, true), icone('seta', 14)]),
      ]))))
    : el('p.ceo-tranquilo', { texto: 'Nenhuma missão em curso. As próximas abrem sozinhas amanhã às 6h30.' });

  const numero = (rotulo, valor, tom, destino, titulo) => {
    const conteudo = [el('span.v', { texto: f.numero(valor) }), el('span.r', { texto: rotulo })];
    if (destino) {
      return el(`a.ceo-dia${tom ? `.${tom}` : ''}`, { href: `#/${destino}`, title: titulo || rotulo }, conteudo);
    }
    return el(`div.ceo-dia${tom ? `.${tom}` : ''}`, { title: titulo || rotulo }, conteudo);
  };

  const rep = Number(o.reprovacoes_abertas) || 0;
  const apr = Number(o.aprovacoes_pendentes) || 0;

  const dia = el('div.ceo-dias', null, [
    numero('missões concluídas hoje', o.concluidas_hoje, null, null, 'missões encerradas no dia'),
    numero('evidências geradas hoje', o.evidencias_hoje, null, null, 'toda afirmação relevante carrega uma'),
    numero('consultas a fontes hoje', o.consultas_hoje, null, null, 'leituras registradas em ferramenta'),
    numero('reprovações abertas', rep, rep > 0 ? 'erro' : null, rep > 0 ? 'visao' : null,
      rep > 0 ? 'ver os achados abertos na visão geral' : 'nenhuma validação reprovada em aberto'),
    numero('aprovações pendentes', apr, apr > 0 ? 'atencao' : null, apr > 0 ? 'aprovacoes' : null,
      apr > 0 ? 'ver a fila de aprovações' : 'nada aguardando decisão humana'),
  ]);

  return el('div.grade.g-2-1.ceo-operacao', null, [
    painel({
      titulo: 'A operação acontecendo',
      nota: d.gerado_em ? `leitura do núcleo às ${horaSeg(d.gerado_em)}` : null,
      corpo: [missoes, dia],
    }),
    painel({
      titulo: 'Fluxo ao vivo',
      nota: 'leitura a cada 4 s',
      acoes: el('span.etq.acento', null, [el('i.pulso.vivo'), 'ao vivo']),
      corpo: el('div.log.ceo-log', { id: 'ceo-fluxo', 'aria-live': 'polite' }),
    }),
  ]);
}

/* ------------------------------------------------------ ritmo do dia ---- */
/* Esta faixa existe por uma frase do dono: "parece que está tudo parado, nada
   acontece". Ele estava certo sobre a tela e errado sobre o sistema — entre uma
   varredura e outra a NÓRIA fica em silêncio, e silêncio sem agenda visível é
   indistinguível de defeito. Aqui o repouso ganha hora marcada. */

const RITMO_MS = 20000;   /* a faixa se refaz sozinha sem tocar nos grandes números */
const HORA_INI = 6;       /* a agenda do dia vai das 6h (conciliação) ... */
const HORA_FIM = 18;      /* ... às 18h (fechamento do dia) */

const DIAS_SEMANA = ['domingo', 'segunda-feira', 'terça-feira', 'quarta-feira',
  'quinta-feira', 'sexta-feira', 'sábado'];
const MESES_LONGOS = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
  'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];

/** Hora em fração do dia (14:30 → 14,5) a partir de um ISO com fuso. */
function horaFracao(iso) {
  const m = String(iso || '').match(/[T ](\d{2}):(\d{2})/);
  if (!m) return null;
  return Number(m[1]) + Number(m[2]) / 60;
}

/** Posição na régua, em porcentagem, presa entre as bordas. */
function posicao(h) {
  const p = ((h - HORA_INI) / (HORA_FIM - HORA_INI)) * 100;
  return Math.min(100, Math.max(0, p));
}

/** "sábado, 5 de setembro" — quem lê numa TV não decifra 2026-09-05. */
function diaPorExtenso(iso) {
  const m = String(iso || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return f.NADA;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return `${DIAS_SEMANA[d.getDay()]}, ${Number(m[3])} de ${MESES_LONGOS[Number(m[2]) - 1]}`;
}

/** O código do agente só aparece quando não se sabe o nome dele. */
function nomeAgente(id, nomes) {
  if (!id) return 'sem agente declarado';
  return (nomes && nomes[id]) || id;
}

/* Status declarado pelo agente. "bloqueada" não é falha do sistema: é o agente
   dizendo que não havia o que fazer. Pintar isso de vermelho ensina o dono a
   ignorar vermelho — e aí o vermelho de verdade também passa batido. */
const DECLARADO = {
  concluida: ['entregou o resultado', 'ok'],
  bloqueada: ['não havia o que fazer', 'neutro'],
  parcial: ['entregou em parte', 'atencao'],
  falha: ['não conseguiu concluir', 'erro'],
};

function declarado(s) {
  const v = DECLARADO[s];
  return v ? { texto: v[0], tom: v[1] } : { texto: s || 'sem status declarado', tom: 'neutro' };
}

/** A frase honesta embaixo da régua: o que vem depois, com nome, hora e agente. */
function fraseDoDia(itens, agoraH) {
  const pendentes = itens.filter((i) => i.estado !== 'feito');
  const atrasados = pendentes.filter((i) => i.estado === 'atrasado');
  const previstos = pendentes
    .filter((i) => i.estado === 'previsto')
    .sort((a, b) => a.hora - b.hora);
  const proxima = previstos.find((i) => i.hora >= Math.floor(agoraH === null ? 0 : agoraH))
    || previstos[0] || null;

  if (!itens.length) {
    return {
      principal: 'Hoje a NÓRIA não tem varredura marcada.',
      apoio: 'A agenda de cada dia é montada na virada — a sentinela continua olhando o faturamento.',
      tom: 'calmo',
    };
  }
  if (proxima) {
    return {
      principal: `Próxima: ${proxima.nome}, às ${proxima.hora}h, com ${proxima.agente}.`,
      apoio: atrasados.length
        ? `${atrasados.length === 1 ? 'Uma varredura passou' : `${atrasados.length} varreduras passaram`} da hora sem rodar: ${atrasados.map((i) => `${i.nome} (${i.hora}h)`).join('; ')}.`
        : 'Até lá a NÓRIA fica em repouso — só a sentinela continua olhando o faturamento.',
      tom: atrasados.length ? 'atencao' : 'calmo',
    };
  }
  if (atrasados.length) {
    return {
      principal: `${atrasados.length === 1 ? 'Falta rodar' : 'Faltam rodar'}: ${atrasados.map((i) => `${i.nome} (${i.hora}h, com ${i.agente})`).join('; ')}.`,
      apoio: 'Passou da hora marcada e a varredura ainda não abriu missão.',
      tom: 'atencao',
    };
  }
  return {
    principal: 'A NÓRIA já fez tudo o que tinha para hoje. A próxima varredura é amanhã às 6h.',
    apoio: 'A agenda é remontada na virada do dia — o silêncio daqui até lá é repouso, não pane.',
    tom: 'calmo',
  };
}

/* ------------------------------------------------------- 1. linha do dia -- */

const ESTADO_TXT = {
  feito: 'já rodou',
  atrasado: 'passou da hora',
  previsto: 'ainda vai rodar',
};

function linhaDoDia(dados, leitura) {
  const itens = Array.isArray(dados.itens) ? dados.itens : [];
  const agoraH = horaFracao(dados.agora);
  const marcas = [6, 8, 10, 12, 14, 16, 18];

  const trilho = el('div.ritmo-trilho', { 'aria-hidden': 'true' }, [
    el('div.ritmo-eixo'),
    /* O trecho já vencido do dia fica mais aceso: o olho lê de imediato
       quanto do dia a NÓRIA já percorreu. */
    agoraH === null ? null : el('div.ritmo-percorrido', { style: `width:${posicao(agoraH)}%` }),
    ...marcas.map((h) => el('i.ritmo-marca', { style: `left:${posicao(h)}%` })),
  ]);

  /* O "agora" é a única linha vertical da régua — se houvesse outra, deixaria
     de ser a referência imediata do olhar. */
  if (agoraH !== null) {
    const dentro = agoraH >= HORA_INI && agoraH <= HORA_FIM;
    /* Perto do fim da régua o rótulo centrado sai da tela — no celular sobrava
       "fora da jan" cortado na borda. Passando de 60% ele passa a crescer
       para a esquerda, ancorado no próprio traço. */
    const pos = posicao(agoraH);
    juntar(trilho, el(`div.ritmo-agora${pos > 60 ? '.fim' : ''}`, { style: `left:${pos}%` }, [
      el('span.ritmo-agora-rot', {
        texto: dentro ? `agora ${f.hora(dados.agora)}` : `${f.hora(dados.agora)} · fora da janela`,
      }),
      el('i.ritmo-agora-traco'),
    ]));
  }

  itens.forEach((i) => {
    juntar(trilho, el(`div.ritmo-ponto.${i.estado}`, {
      style: `left:${posicao(i.hora)}%`,
      tabindex: '0',
      title: `${i.hora}h · ${i.nome} · com ${i.agente} · ${ESTADO_TXT[i.estado] || i.estado}`,
      onmouseenter: () => leitura(i),
      onmouseleave: () => leitura(null),
      onfocus: () => leitura(i),
      onblur: () => leitura(null),
    }, [el('i')]));
  });

  const rotulos = el('div.ritmo-horas', { 'aria-hidden': 'true' }, marcas.map((h) =>
    el('span', { style: `left:${posicao(h)}%`, texto: `${h}h` })));

  /* A régua é gráfica; a lista abaixo é o mesmo dia escrito. No celular ela vira
     a forma principal — encolher a régua até virar borrão seria fingir que cabe. */
  const lista = el('ul.ritmo-itens', null, itens.map((i) => el(`li.${i.estado}`, null, [
    el('span.ritmo-h', { texto: `${i.hora}h` }),
    el('i.ritmo-pt'),
    el('span.ritmo-n', { texto: i.nome }),
    el('span.ritmo-ag', { texto: `com ${i.agente}` }),
    el('span.ritmo-est', { texto: ESTADO_TXT[i.estado] || i.estado }),
  ])));

  return el('div.ritmo-regua', null, [trilho, rotulos, itens.length ? lista : null]);
}

/* ---------------------------------------------------- 2. pulso da vigília -- */

function pulsoVigilia(dados) {
  const v = dados.vigilia || {};
  const intervalo = Number(v.intervalo_s) || 0;
  const ag = dados.agentes || {};

  const ns = 'http://www.w3.org/2000/svg';
  const anel = document.createElementNS(ns, 'svg');
  anel.setAttribute('viewBox', '0 0 28 28');
  anel.setAttribute('class', 'ritmo-anel');
  anel.setAttribute('aria-hidden', 'true');
  const trilha = document.createElementNS(ns, 'circle');
  trilha.setAttribute('cx', '14'); trilha.setAttribute('cy', '14'); trilha.setAttribute('r', '11');
  trilha.setAttribute('class', 'trilha');
  const arco = document.createElementNS(ns, 'circle');
  arco.setAttribute('cx', '14'); arco.setAttribute('cy', '14'); arco.setAttribute('r', '11');
  arco.setAttribute('class', 'arco');
  const volta = 2 * Math.PI * 11;
  arco.setAttribute('stroke-dasharray', volta.toFixed(2));
  arco.setAttribute('stroke-dashoffset', volta.toFixed(2));
  anel.appendChild(trilha);
  anel.appendChild(arco);

  const nucleo = el('i.ritmo-nucleo');
  const quando = el('span.ritmo-vig-quando');

  /* O pulso não é enfeite: o arco fecha uma volta a cada `intervalo_s` reais,
     contados desde a última leitura. Assim dá para ver quanto falta para a
     próxima — um GIF girando diria "vivo" mesmo com a sentinela morta. */
  function bater() {
    if (!v.ultima_leitura || !intervalo) {
      arco.setAttribute('stroke-dashoffset', volta.toFixed(2));
      nucleo.classList.add('parado');
      quando.textContent = 'ainda não fez a primeira leitura de hoje';
      return;
    }
    const t = Date.parse(v.ultima_leitura);
    if (Number.isNaN(t)) {
      nucleo.classList.add('parado');
      quando.textContent = 'a última leitura veio com data ilegível';
      return;
    }
    const decorrido = Math.max(0, (Date.now() - t) / 1000);
    const fracao = Math.min(1, (decorrido % intervalo) / intervalo);
    arco.setAttribute('stroke-dashoffset', (volta * (1 - fracao)).toFixed(2));
    nucleo.classList.remove('parado');
    const min = Math.floor(decorrido / 60);
    quando.textContent = decorrido < 90
      ? `última leitura há ${Math.floor(decorrido)} segundos`
      : `última leitura há ${min} ${min === 1 ? 'minuto' : 'minutos'}`;
  }
  bater();

  const minutos = intervalo ? Math.round(intervalo / 60) : null;
  const total = Number(ag.total);
  const operando = Number(ag.operando);
  const temEquipe = Number.isFinite(total) && Number.isFinite(operando);

  const no = el('div.ritmo-pulso', null, [
    el('div.ritmo-vigilia', null, [
      el('div.ritmo-marcador', null, [anel, nucleo]),
      el('div.ritmo-vig-texto', null, [
        el('b', {
          texto: minutos
            ? `A sentinela olha o faturamento a cada ${minutos} ${minutos === 1 ? 'minuto' : 'minutos'}`
            : 'A sentinela olha o faturamento em intervalo não informado',
        }),
        quando,
      ]),
    ]),
    el('div.ritmo-equipe', null, [
      el('b', {
        texto: temEquipe
          ? `${f.numero(operando)} de ${f.numero(total)} agentes com trabalho ligado`
          : 'a API não informou quantos agentes estão ligados',
      }),
      temEquipe
        ? el('span', {
          texto: `Os outros ${f.numero(total - operando)} não são defeito: são o mapa do que ainda falta construir.`,
        })
        : null,
    ]),
  ]);

  return { no, bater };
}

/* ------------------------------------------------- 3. o que a NÓRIA disse -- */

function acabouDeDizer(dados, nomes) {
  const emCurso = Array.isArray(dados.em_curso) ? dados.em_curso : [];
  const entregas = Array.isArray(dados.ultimas_entregas) ? dados.ultimas_entregas : [];
  const linhas = [];

  emCurso.forEach((t) => {
    linhas.push(el('li.ritmo-fala.agora', null, [
      el('div.ritmo-fala-marca', null, [el('i.pulso.vivo')]),
      el('div.ritmo-fala-corpo', null, [
        el('div.ritmo-cabeca', null, [
          el('b', { texto: nomeAgente(t.agente_id, nomes) }),
          el('span.ritmo-decl.acento', { texto: 'acontecendo agora' }),
        ]),
        el('p', { texto: f.textoBr(t.objetivo || `tarefa ${t.id}`) }),
        el('span.ritmo-meta', {
          texto: `${f.estadoTarefa(t.estado).texto.toLowerCase()} · ${haQuanto(t.atualizada_em) || f.dataHora(t.atualizada_em)}`,
        }),
      ]),
    ]));
  });

  entregas.slice(0, emCurso.length ? 4 : 5).forEach((e) => {
    const d = declarado(e.status_declarado);
    const ver = f.estadoTarefa(e.veredito);
    linhas.push(el(`li.ritmo-fala.${d.tom}`, null, [
      el('div.ritmo-fala-marca', null, [el('i.ritmo-pt')]),
      el('div.ritmo-fala-corpo', null, [
        el('div.ritmo-cabeca', null, [
          el('b', { texto: nomeAgente(e.agente_id, nomes) }),
          el(`span.ritmo-decl.${d.tom}`, { texto: d.texto }),
        ]),
        el('p', { texto: f.textoBr(e.resumo || 'entrega sem resumo escrito') }),
        el('span.ritmo-meta', {
          title: f.dataHora(e.criada_em),
          texto: `${haQuanto(e.criada_em) || f.dataHora(e.criada_em)} · validação: ${ver.texto.toLowerCase()}`,
        }),
      ]),
    ]));
  });

  if (!linhas.length) {
    return el('div.ritmo-dito', null,
      el('p.ritmo-quieto', {
        texto: 'Nenhuma entrega registrada ainda. Quando um agente concluir, a frase dele aparece aqui.',
      }));
  }

  return el('div.ritmo-dito', null, el('ul.ritmo-falas', null, linhas));
}

/* ------------------------------------------------------ montagem da faixa -- */

/** A faixa cuida da própria atualização: 20 s, sem redesenhar a tela nem piscar
    os grandes números, que têm outro ritmo (60 s) e outro custo no ERP. */
function faixaRitmo({ nomes }) {
  const caixa = el('section.ritmo');
  let baterVigilia = null;
  let vivo = true;
  let ultimos = null;   /* última resposta desenhada, para redesenhar sem reler */

  function desenhar(dados) {
    const itens = Array.isArray(dados.itens) ? dados.itens : [];
    const feitos = Number.isFinite(Number(dados.feitos))
      ? Number(dados.feitos)
      : itens.filter((i) => i.estado === 'feito').length;
    const frase = fraseDoDia(itens, horaFracao(dados.agora));

    const resumo = itens.length
      ? `${f.numero(itens.length)} ${itens.length === 1 ? 'varredura marcada hoje' : 'varreduras marcadas hoje'} · ${f.numero(feitos)} já ${feitos === 1 ? 'rodou' : 'rodaram'}`
      : 'nenhuma varredura marcada para hoje';

    const leitor = el('p.ritmo-leitor', { texto: resumo });
    /* Um só lugar de leitura em vez de balão flutuante: o balão tapa a régua
       justamente onde o olho está. */
    function leitura(i) {
      leitor.textContent = i
        ? `${i.hora}h · ${i.nome} · com ${i.agente} · ${ESTADO_TXT[i.estado] || i.estado}`
        : resumo;
      leitor.classList.toggle('vivo', !!i);
    }

    const pulso = pulsoVigilia(dados);
    baterVigilia = pulso.bater;

    limpar(caixa);
    juntar(caixa, [
      el('div.ritmo-cab', null, [
        el('h3', { texto: 'Ritmo do dia' }),
        el('p.ritmo-nota', {
          texto: `${diaPorExtenso(dados.hoje)}${dados.dia_util === false ? ' · fora do dia útil' : ''} · agenda lida às ${horaSeg(dados.agora)}`,
        }),
      ]),
      el('div.ritmo-corpo', null, [
        el('div.ritmo-coluna', null, [
          leitor,
          linhaDoDia(dados, leitura),
          el(`div.ritmo-frase.${frase.tom}`, null, [
            el('b', { texto: frase.principal }),
            el('span', { texto: frase.apoio }),
          ]),
          pulso.no,
        ]),
        el('div.ritmo-lado', null, [
          el('h4', { texto: 'O que a NÓRIA acabou de dizer' }),
          acabouDeDizer(dados, nomes),
        ]),
      ]),
    ]);
  }

  function falhar(e) {
    baterVigilia = null;
    limpar(caixa);
    juntar(caixa, [
      el('div.ritmo-cab', null, [el('h3', { texto: 'Ritmo do dia' })]),
      el('div.ritmo-falha', null, [
        el('b', { texto: 'A agenda do dia não respondeu.' }),
        el('span', {
          texto: `${e && e.message ? e.message : 'erro inesperado'} — nada foi desenhado de memória: sem resposta, a faixa fica em branco em vez de fingir um dia que não foi lido.`,
        }),
      ]),
    ]);
  }

  async function atualizar() {
    try {
      const d = await api.agenda();
      if (!vivo) return;
      ultimos = d;
      desenhar(d);
    } catch (e) {
      if (vivo) falhar(e);
    }
  }

  atualizar();
  const timer = setInterval(atualizar, RITMO_MS);
  /* O arco da vigília anda a cada segundo; o dado só é relido a cada 20 s. */
  const segundo = setInterval(() => {
    if (typeof baterVigilia === 'function') baterVigilia();
  }, 1000);

  return {
    no: caixa,
    /* A agenda responde antes de /ceo e só traz o código do agente. Quando os
       nomes chegam, a faixa se redesenha com o dado que já tinha — reler a API
       só para trocar "fiscal.documento" por "Alan" seria desperdício. */
    redesenhar: () => { if (vivo && ultimos) desenhar(ultimos); },
    parar: () => { vivo = false; clearInterval(timer); clearInterval(segundo); },
  };
}

/* ---------------------------------------------------------------- tela --- */

export async function montar(raiz, _params, { pulso, ir }) {
  const caixa = el('div.ceo');
  const painelDados = el('div');   /* os grandes números */
  const resto = el('div');         /* curva, concentração e equipe */
  const barra = el('div.ceo-topo');
  const fluxo = el('div');

  /* Os nomes dos agentes vêm da equipe de /ceo; a agenda só devolve o código.
     O objeto é o mesmo entre recargas, então a faixa lê sempre o mais recente
     sem precisar ser remontada. */
  const nomes = {};
  const ritmo = faixaRitmo({ nomes });

  /* A faixa entra entre os grandes números e o resto: o dono lê o dinheiro,
     depois pergunta "e a NÓRIA, está fazendo alguma coisa?" — a resposta tem
     que estar exatamente aí, antes de qualquer gráfico. */
  juntar(caixa, [barra, painelDados, ritmo.no, resto, fluxo]);
  juntar(raiz, caixa);

  let timer = 0;
  let desassinar = null;
  let vivo = true;

  const carimboTopo = el('span.ceo-topo-hora');
  const btn = el('button.btn.btn-peq', { type: 'button' }, [icone('relogio', 14), el('span', { texto: 'Reler agora' })]);
  juntar(barra, [carimboTopo, el('div.vao'), btn]);

  async function desenhar(forcar) {
    btn.disabled = true;
    try {
      const d = await api.ceo(forcar);
      if (!vivo) return;
      let nomeNovo = false;
      (Array.isArray(d.equipe) ? d.equipe : []).forEach((a) => {
        if (a && a.codigo && nomes[a.codigo] !== (a.nome || a.codigo)) {
          nomes[a.codigo] = a.nome || a.codigo;
          nomeNovo = true;
        }
      });
      if (nomeNovo) ritmo.redesenhar();
      limpar(painelDados);
      juntar(painelDados, faixaNumeros(d));
      limpar(resto);
      juntar(resto, [
        el('div.grade.g2.ceo-meio', null, [grafico(d), concentracao(d)]),
        setores(d),
        equipe(d),
      ]);
      /* O fluxo ao vivo é remontado junto porque o log fica dentro do painel;
         a assinatura antiga é encerrada para não escrever em nó descartado. */
      if (typeof desassinar === 'function') desassinar();
      limpar(fluxo);
      juntar(fluxo, operacao(d, ir));
      const log = fluxo.querySelector('#ceo-fluxo');
      desassinar = pulso.assinar((todos) => {
        if (!log.isConnected) return;
        limpar(log);
        if (!todos.length) {
          juntar(log, el('p.ajuda', { texto: 'Nenhum evento registrado ainda.' }));
          return;
        }
        todos.slice(0, 8).forEach((ev) => juntar(log, linhaEvento(ev)));
      });

      limpar(carimboTopo);
      juntar(carimboTopo, [
        el('b', { texto: (d.empresa && d.empresa.nome) || 'Pianetto Transportes' }),
        el('span', {
          texto: `CNPJ ${(d.empresa && d.empresa.cnpj) || '—'} · números do ERP lidos às ${horaSeg(d.lido_em)} · tela relida sozinha a cada 60 s`,
        }),
      ]);
    } catch (e) {
      if (!vivo) return;
      limpar(painelDados);
      limpar(resto);
      juntar(painelDados, el('div.aviso-erro', {
        texto: `Não deu para ler os números: ${e && e.message ? e.message : 'erro inesperado'}. Nenhum valor antigo foi reaproveitado como se fosse de agora.`,
      }));
    } finally {
      if (vivo) btn.disabled = false;
    }
  }

  btn.addEventListener('click', () => desenhar(true));

  await desenhar(false);
  timer = setInterval(() => desenhar(false), INTERVALO_MS);

  return () => {
    vivo = false;
    clearInterval(timer);
    ritmo.parar();
    if (typeof desassinar === 'function') desassinar();
  };
}
