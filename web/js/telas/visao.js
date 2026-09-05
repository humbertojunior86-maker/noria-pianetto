/* Visão geral — o pulso real. Todo número vem de /api/panorama. */

import * as api from '../api.js';
import * as f from '../fmt.js';
import { el, juntar, limpar, painel, metrica, vazio, etiqueta, etiquetaEstado, icone,
  linhaEvento, secao, tabela } from '../ui.js';

function cartoesMissao(p) {
  const porEstado = p.missoes.por_estado || {};
  const ordem = f.ESTADOS_MISSAO.filter((e) => porEstado[e]);
  const corpo = ordem.length
    ? el('div.chips', null, ordem.map((e) => {
      const r = f.estadoMissao(e);
      return el(`span.etq.${r.tom}`, null, [el('i.ponto'), `${r.texto} · ${f.numero(porEstado[e])}`]);
    }))
    : el('p.ajuda', { texto: 'Nenhuma missão registrada até agora.' });

  return painel({
    titulo: 'Missões por estado',
    nota: `${f.numero(p.missoes.total)} no total`,
    corpo: [
      corpo,
      el('div.par-linhas', { style: 'margin-top:16px' }, [
        el('div.par', null, [el('span', { texto: 'Em curso' }),
          el('b', { texto: f.numero(p.missoes.em_curso) })]),
        el('div.par', null, [el('span', { texto: 'Evidências' }),
          el('b', { texto: f.numero(p.evidencias) })]),
        el('div.par', null, [el('span', { texto: 'Artefatos' }),
          el('b', { texto: f.numero(p.artefatos) })]),
      ]),
    ],
  });
}

function painelIntegracoes(p, aoTestar) {
  const itens = p.integracoes || [];
  if (!itens.length) {
    return painel({
      titulo: 'Integrações',
      corpo: vazio('Nenhuma integração cadastrada.', 'Sem conexão declarada, a NÓRIA só opera sobre o que já está no banco.'),
      semFolga: true,
    });
  }
  const linhas = itens.map((i) => {
    const r = f.estadoIntegracao(i.estado);
    return [
      el('div', null, [
        el('strong', { texto: i.nome }),
        el('div.ajuda', { texto: i.escreve ? 'pode escrever no destino' : 'somente leitura' }),
      ]),
      etiqueta(r.texto, r.tom, true),
      i.limitacao ? el('span.ajuda', { texto: i.limitacao }) : el('span.ajuda', { texto: '—' }),
    ];
  });
  return painel({
    titulo: 'Integrações',
    nota: `${itens.filter((i) => i.estado === 'conectada').length} conectada(s) de ${itens.length}`,
    acoes: el('button.btn.btn-peq', { type: 'button', texto: 'Ver todas', onclick: aoTestar }),
    corpo: tabela(
      [{ titulo: 'Conexão' }, { titulo: 'Estado' }, { titulo: 'Limitação declarada' }],
      linhas,
    ),
    semFolga: true,
  });
}

function painelUltimas(p, ir) {
  const itens = p.ultimas_missoes || [];
  if (!itens.length) {
    return painel({
      titulo: 'Últimas missões',
      corpo: vazio(
        'Nenhuma missão registrada.',
        'Descreva um objetivo em texto livre e a NÓRIA monta o plano.',
        el('a.btn.btn-forte', { href: '#/missoes', texto: 'Abrir uma missão' }),
      ),
      semFolga: true,
    });
  }
  const lista = el('ul.lista', null, itens.map((m) => el('li', null,
    el('button.item', {
      type: 'button', onclick: () => ir(`missoes/${m.id}`),
    }, [
      el('div.corpo', null, [
        el('p.tit', { texto: f.textoBr(m.objetivo) }),
        el('div.meta', null, [
          el('span', { texto: `#${m.id}` }),
          el('span', { texto: `aberta ${f.dataHora(m.criada_em)}` }),
          m.encerrada_em ? el('span', { texto: `encerrada ${f.dataHora(m.encerrada_em)}` }) : null,
          m.natureza ? el('span', { texto: f.natureza(m.natureza).texto.toLowerCase() }) : null,
        ]),
      ]),
      el('div.direita', null, [etiquetaEstado(m.estado), icone('seta', 14)]),
    ]))));
  return painel({ titulo: 'Últimas missões', nota: 'clique para abrir o detalhe', corpo: lista, semFolga: true });
}

function painelAchados(p) {
  const itens = p.achados_abertos || [];
  if (!itens.length) {
    return painel({
      titulo: 'Achados abertos',
      corpo: el('p.ajuda', { texto: 'Nenhuma validação reprovada em aberto. Achado só aparece aqui quando uma camada reprova.' }),
    });
  }
  return painel({
    titulo: 'Achados abertos',
    nota: `${f.numero(itens.length)} validação(ões) reprovada(s)`,
    corpo: tabela(
      [{ titulo: 'Camada' }, { titulo: 'Missão' }, { titulo: 'Justificativa' }, { titulo: 'Quando' }],
      itens.map((a) => [
        etiqueta(f.camada(a.camada), 'erro'),
        el('a', { href: `#/missoes/${a.missao_id}`, texto: `#${a.missao_id}` }),
        f.textoBr(a.justificativa || '—'),
        f.dataHora(a.criada_em),
      ]),
    ),
    semFolga: true,
  });
}

export async function montar(raiz, _params, { pulso, ir }) {
  const p = await api.panorama();

  const topo = el('div.grade.g4', null, [
    metrica('Missões em curso', f.numero(p.missoes.em_curso),
      `${f.numero(p.missoes.total)} registradas desde o início`,
      { destaque: p.missoes.em_curso > 0 }),
    metrica('Agentes habilitados', `${f.numero(p.agentes.habilitados)}/${f.numero(p.agentes.cadastrados)}`,
      `${f.numero(p.agentes.sem_integracao)} sem integração`),
    metrica('Aprovações pendentes', f.numero(p.aprovacoes_pendentes),
      p.aprovacoes_pendentes ? 'ação externa aguardando decisão' : 'nada aguardando decisão'),
    metrica('Achados abertos', f.numero((p.achados_abertos || []).length),
      'validações reprovadas sem tratamento'),
  ]);

  const log = el('div.log', { id: 'fluxo', 'aria-live': 'polite' });
  const fluxo = painel({
    titulo: 'Fluxo de eventos',
    nota: 'leitura a cada 4 s',
    acoes: el('span.etq.acento', null, [el('i.pulso.vivo'), 'ao vivo']),
    corpo: log,
  });

  juntar(raiz, [
    secao(null, null, topo),
    el('div.grade.g-2-1', { style: 'margin-bottom:32px' }, [
      painelUltimas(p, ir),
      cartoesMissao(p),
    ]),
    el('div.grade.g-2-1', { style: 'margin-bottom:32px' }, [
      painelIntegracoes(p, () => ir('integracoes')),
      fluxo,
    ]),
    painelAchados(p),
  ]);

  const desassinar = pulso.assinar((todos) => {
    limpar(log);
    if (!todos.length) {
      juntar(log, el('p.ajuda', { texto: 'Nenhum evento registrado ainda.' }));
      return;
    }
    todos.slice(0, 40).forEach((ev) => juntar(log, linhaEvento(ev)));
  });

  return desassinar;
}
