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

/* ---------------------------------------------------------------- tela --- */

export async function montar(raiz, _params, { pulso, ir }) {
  const caixa = el('div.ceo');
  const painelDados = el('div');
  const barra = el('div.ceo-topo');
  const fluxo = el('div');
  juntar(caixa, [barra, painelDados, fluxo]);
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
      limpar(painelDados);
      juntar(painelDados, [
        faixaNumeros(d),
        el('div.grade.g2.ceo-meio', null, [grafico(d), concentracao(d)]),
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
    if (typeof desassinar === 'function') desassinar();
  };
}
