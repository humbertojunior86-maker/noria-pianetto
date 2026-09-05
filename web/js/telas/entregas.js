/* Entregas — resumo, afirmações e o lastro de cada uma.
   Afirmação com natureza diferente de "fato" aparece marcada, nunca escondida.
   Afirmação sem evidência é dita como tal. */

import * as api from '../api.js';
import * as f from '../fmt.js';
import { el, juntar, painel, vazio, etiqueta, icone, tabela, secao, par } from '../ui.js';

function afirmacao(a) {
  const nat = f.natureza(a.natureza);
  const temLastro = !!(a.evidencia_id && (a.origem || a.trecho));
  const hipotese = a.natureza !== 'fato';

  return el('article.afirmacao', null, [
    el('div.cab', null, [
      etiqueta(nat.texto, nat.tom, true),
      hipotese ? etiqueta('não é fato: trate como hipótese', 'atencao') : null,
      temLastro ? etiqueta(`evidência #${a.evidencia_id}`, 'neutra') : etiqueta('sem evidência', 'erro'),
    ]),
    el('p', { texto: f.textoBr(a.texto) }),
    temLastro
      ? el('div.lastro', null, [
        par('Origem', a.origem || f.NADA),
        par('Raiz', a.raiz || f.NADA),
        par('Consultada em', f.dataHora(a.consultada_em)),
        par('Referência', a.referencia || f.NADA),
        el('div.par', { style: 'grid-column:1/-1' }, [
          el('span', { texto: 'Trecho que sustenta' }),
          el('b', { texto: f.textoBr(a.trecho || f.NADA) }),
        ]),
      ])
      : el('p.sem-lastro', { texto: 'Esta afirmação não tem evidência ligada. Sem lastro, ela não vale como fato.' }),
  ]);
}

function entrega(e, missao) {
  const listas = [
    ['Incertezas declaradas', e.incertezas || []],
    ['Conflitos', e.conflitos || []],
    ['Pendências', e.pendencias || []],
  ].filter(([, v]) => v.length);

  const semEvidencia = (e.afirmacoes || []).filter((a) => !a.evidencia_id).length;
  const hipoteses = (e.afirmacoes || []).filter((a) => a.natureza !== 'fato').length;

  return painel({
    titulo: f.textoBr(e.titulo || `Entrega #${e.id}`),
    nota: `missão #${e.missao_id} · tarefa #${e.tarefa_id} · tentativa ${f.numero(e.tentativa)} · ${f.dataHora(e.criada_em)}`,
    acoes: el('a.btn.btn-peq', { href: `#/missoes/${e.missao_id}`, texto: 'Abrir missão' }),
    corpo: [
      el('p', { style: 'margin:0 0 16px;font-size:var(--t-md)', texto: f.textoBr(e.resumo || f.NADA) }),
      el('div.par-linhas', { style: 'margin-bottom:20px' }, [
        par('Agente', e.agente_id || f.NADA),
        par('Status declarado', e.status_declarado || f.NADA),
        par('Afirmações', f.numero((e.afirmacoes || []).length)),
        par('Sem evidência', f.numero(semEvidencia)),
        par('Marcadas como hipótese', f.numero(hipoteses)),
        missao ? par('Estado da missão', f.estadoMissao(missao.estado).texto) : null,
      ]),
      el('h4', { style: 'font-size:var(--t-peq);margin-bottom:12px', texto: 'Afirmações e lastro' }),
      (e.afirmacoes || []).length
        ? el('div', null, e.afirmacoes.map(afirmacao))
        : el('p.ajuda', { texto: 'Esta entrega não declarou nenhuma afirmação.' }),
      listas.length
        ? el('div', { style: 'margin-top:20px' }, listas.map(([t, v]) => el('div', { style: 'margin-top:12px' }, [
          el('h4', { style: 'font-size:var(--t-peq);margin-bottom:8px', texto: t }),
          el('ul', { style: 'margin:0;padding-left:20px;font-size:var(--t-peq);color:var(--tinta-2)' },
            v.map((x) => el('li', { texto: f.textoBr(typeof x === 'string' ? x : JSON.stringify(x)) }))),
        ])))
        : null,
      e.resultado && Object.keys(e.resultado).length
        ? el('details', { style: 'margin-top:20px' }, [
          el('summary', { style: 'cursor:pointer;font-size:var(--t-peq);color:var(--tinta-3)', texto: 'Resultado estruturado, como a API devolveu' }),
          el('pre.poco', { style: 'margin-top:12px;max-height:320px', texto: JSON.stringify(e.resultado, null, 2) }),
        ])
        : null,
    ],
  });
}

export async function montar(raiz, params, { ir }) {
  const dm = await api.missoes();
  const missoes = (dm.missoes || []).slice(0, 20);

  if (!missoes.length) {
    juntar(raiz, painel({
      corpo: vazio('Nenhuma entrega existe ainda.',
        'Entrega é o que um agente devolve dentro de uma missão. Abra uma missão para que exista o que conferir.',
        el('a.btn.btn-forte', { href: '#/missoes', texto: 'Abrir uma missão' })),
      semFolga: true,
    }));
    return null;
  }

  const alvo = params[0] ? missoes.filter((m) => String(m.id) === String(params[0])) : missoes;
  const pacotes = await Promise.all(alvo.map(async (m) => ({ m, d: await api.entregas(m.id) })));
  const todas = pacotes.flatMap(({ m, d }) => (d.entregas || []).map((e) => ({ e, m })));

  const totalAfirm = todas.reduce((a, { e }) => a + (e.afirmacoes || []).length, 0);
  const semEvid = todas.reduce((a, { e }) => a + (e.afirmacoes || []).filter((x) => !x.evidencia_id).length, 0);

  juntar(raiz, secao(null,
    params[0] ? `Filtrado pela missão #${params[0]}.` : null,
    el('div.grade.g3', null, [
      el('div.metrica', null, [
        el('span.rot', { texto: 'Entregas listadas' }),
        el('span.val', { texto: f.numero(todas.length) }),
        el('span.obs', { texto: `de ${f.numero(alvo.length)} missão(ões)` }),
      ]),
      el('div.metrica', null, [
        el('span.rot', { texto: 'Afirmações' }),
        el('span.val', { texto: f.numero(totalAfirm) }),
        el('span.obs', { texto: 'cada uma com lastro próprio' }),
      ]),
      el(`div.metrica${semEvid ? '' : ''}`, null, [
        el('span.rot', { texto: 'Sem evidência' }),
        el('span.val', { texto: f.numero(semEvid) }),
        el('span.obs', { texto: semEvid ? 'entram como hipótese, não como fato' : 'toda afirmação tem lastro' }),
      ]),
    ])));

  if (params[0]) {
    juntar(raiz, el('div.linha-acoes', { style: 'margin-bottom:24px' },
      el('a.btn.btn-peq', { href: '#/entregas', texto: 'Ver todas as entregas' })));
  }

  if (!todas.length) {
    juntar(raiz, painel({
      corpo: vazio('Nenhuma entrega registrada nas missões listadas.',
        'A entrega aparece aqui quando um agente conclui a tarefa e devolve resultado com evidência.'),
      semFolga: true,
    }));
    return null;
  }

  // A lista pode ser longa; mostra em blocos para a tela não virar um rolo infinito.
  const LOTE = 5;
  let mostradas = 0;
  const grade = el('div.grade', { style: 'gap:24px' });
  const rodape = el('div.linha-acoes', { style: 'margin-top:24px' });
  const mais = el('button.btn', { type: 'button' });
  const conta = el('p.ajuda');

  function mostrarMais() {
    const fatia = todas.slice(mostradas, mostradas + LOTE);
    juntar(grade, fatia.map(({ e, m }) => entrega(e, m)));
    mostradas += fatia.length;
    conta.textContent = `Mostrando ${f.numero(mostradas)} de ${f.numero(todas.length)} entrega(s).`;
    if (mostradas >= todas.length) rodape.classList.add('oculto');
    else mais.textContent = `Mostrar mais ${f.numero(Math.min(LOTE, todas.length - mostradas))} entrega(s)`;
  }

  mais.addEventListener('click', mostrarMais);
  juntar(rodape, mais);
  juntar(raiz, [grade, rodape, conta]);
  mostrarMais();
  return null;
}
