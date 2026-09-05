/* Cérebro — o ciclo do núcleo em operação, montado só com eventos,
   execuções de ferramenta e validações reais da missão mais recente. */

import * as api from '../api.js';
import * as f from '../fmt.js';
import { el, juntar, limpar, painel, metrica, vazio, etiqueta, icone, tabela,
  linhaEvento, secao, tituloLinha, par } from '../ui.js';

const ETAPAS = [
  { id: 'interpretacao', nome: 'Interpretação', diz: 'O objetivo em texto livre vira missão, com contexto e critérios verificáveis.' },
  { id: 'plano', nome: 'Plano', diz: 'Plano versionado: estratégia, tarefas e dependências.' },
  { id: 'despacho', nome: 'Despacho', diz: 'Cada tarefa vai para o agente com as ações permitidas e o orçamento reservado.' },
  { id: 'execucao', nome: 'Execução', diz: 'O agente consulta as fontes autorizadas e devolve entrega estruturada com evidência.' },
  { id: 'validacao', nome: 'Validação em 6 camadas', diz: 'Estrutural, objetiva, documental, especializada, global e operacional — resultado por critério.' },
  { id: 'conclusao', nome: 'Conclusão', diz: 'Encerra validado, parcial ou bloqueado. Nunca concluído com critério reprovado.' },
];

function classificar(eventos) {
  const marca = {};
  const guardar = (id, ev) => { if (!marca[id] || ev.id > marca[id].id) marca[id] = ev; };
  eventos.forEach((ev) => {
    if (ev.tipo === 'missao.aberta') guardar('interpretacao', ev);
    else if (ev.tipo === 'plano.criado') guardar('plano', ev);
    else if (ev.tipo === 'tarefa.estado' && ev.para_estado === 'despachada') guardar('despacho', ev);
    else if (ev.tipo === 'tarefa.estado' && ['executando', 'entregue'].includes(ev.para_estado)) guardar('execucao', ev);
    else if (ev.tipo === 'tarefa.estado' && ['aprovada', 'reprovada', 'nao_verificavel'].includes(ev.para_estado)) guardar('validacao', ev);
    else if (ev.tipo === 'missao.estado' && ev.para_estado === 'validando') guardar('validacao', ev);
    else if (ev.tipo === 'missao.encerrada') guardar('conclusao', ev);
    else if (ev.tipo === 'missao.estado' && ['concluida', 'parcial', 'bloqueada', 'cancelada'].includes(ev.para_estado)) guardar('conclusao', ev);
  });
  return marca;
}

function ciclo(marca, det) {
  const caixa = el('div.ciclo');
  ETAPAS.forEach((et, i) => {
    const ev = marca[et.id];
    const pilhas = [];
    if (et.id === 'plano' && det) {
      const p = det.planos[det.planos.length - 1];
      if (p) {
        pilhas.push(etiqueta(`plano v${p.versao}`, 'neutra'));
        pilhas.push(etiqueta(String(p.estrategia).replace(/_/g, ' '), 'neutra'));
        pilhas.push(etiqueta(`${f.numero(det.tarefas.length)} tarefa(s)`, 'neutra'));
      }
    }
    if (et.id === 'despacho' && det) {
      det.tarefas.forEach((t) => pilhas.push(etiqueta(t.agente_id, 'neutra')));
    }
    if (et.id === 'execucao' && det) {
      const acoes = new Set();
      det.tarefas.forEach((t) => (t.acoes_permitidas || []).forEach((a) => acoes.add(a)));
      [...acoes].slice(0, 4).forEach((a) => pilhas.push(etiqueta(a, 'neutra')));
    }
    if (et.id === 'validacao' && det) {
      f.CAMADAS.forEach((c) => {
        const v = det.validacoes.filter((x) => x.camada === c);
        if (!v.length) { pilhas.push(etiqueta(`${f.camada(c)}: ausente`, 'neutra')); return; }
        const pior = v.some((x) => x.resultado === 'reprovado') ? 'reprovado'
          : v.every((x) => x.resultado === 'aprovado') ? 'aprovado' : 'nao_verificavel';
        const r = f.resultado(pior);
        pilhas.push(etiqueta(`${f.camada(c)}: ${r.texto.toLowerCase()}`, r.tom));
      });
    }
    if (et.id === 'conclusao' && det) {
      const r = f.estadoMissao(det.missao.estado);
      pilhas.push(etiqueta(r.texto, r.tom, true));
      if (det.missao.resultado && det.missao.resultado.natureza) {
        const n = f.natureza(det.missao.resultado.natureza);
        pilhas.push(etiqueta(`natureza: ${n.texto.toLowerCase()}`, n.tom));
      }
    }

    juntar(caixa, el(`div.etapa${ev ? '.viva' : ''}${et.id === 'validacao' ? '.nucleo' : ''}`, null, [
      el('div.selo', { texto: String(i + 1) }),
      el('div.caixa', null, [
        el('div', { style: 'display:flex;gap:12px;align-items:baseline;flex-wrap:wrap' }, [
          el('h4', { texto: et.nome }),
          el('span.quando', { texto: ev ? f.dataHora(ev.criado_em) : 'sem registro' }),
        ]),
        el('p', { texto: et.diz }),
        ev ? el('p', {
          style: 'color:var(--tinta-3)',
          texto: `Último registro: ${f.textoBr(ev.texto || f.tipoEvento(ev.tipo))}`,
        }) : null,
        pilhas.length ? el('div.pilhas', null, pilhas) : null,
      ]),
    ]));
  });
  return caixa;
}

function grafoExecucao(det) {
  if (!det) return null;
  const nucleo = el('div.no.nucleo', null, [
    el('span.qual', { texto: 'núcleo' }),
    el('div.nome', { texto: `Missão #${det.missao.id}` }),
    el('div.det', { texto: `${f.numero(det.criterios.length)} critério(s) · plano v${det.missao.plano_vigente ?? '—'}` }),
  ]);
  const tarefas = el('div.grafo-fila', null, det.tarefas.map((t) => {
    const r = f.estadoTarefa(t.estado);
    return el('div.no', null, [
      el('span.qual', { texto: t.agente_id }),
      el('div.nome', { texto: t.titulo.split(':')[0] }),
      el('div.det', { texto: `${(t.acoes_permitidas || []).length} ação(ões) permitida(s) · tentativa ${t.tentativas}/${t.max_tentativas}` }),
      el('div', { style: 'margin-top:8px' }, etiqueta(r.texto, r.tom, true)),
    ]);
  }));
  const validacao = el('div.no', null, [
    el('span.qual', { texto: 'validação' }),
    el('div.nome', { texto: `${f.numero(det.validacoes.length)} aferição(ões)` }),
    el('div.det', {
      texto: `${f.numero(det.validacoes.filter((v) => v.resultado === 'aprovado').length)} aprovada(s) · `
        + `${f.numero(det.validacoes.filter((v) => v.resultado === 'reprovado').length)} reprovada(s) · `
        + `${f.numero(det.validacoes.filter((v) => v.resultado === 'nao_verificavel').length)} não verificável(is)`,
    }),
  ]);
  return el('div.grafo-exec', null, [
    el('div.grafo-fila', null, nucleo),
    el('div.seta', null, icone('seta', 16)),
    tarefas,
    el('div.seta', null, icone('seta', 16)),
    el('div.grafo-fila', null, validacao),
    el('p.aviso-linha', null, [icone('alerta', 14),
      'Este é o grafo de execução da missão — o que rodou. O que a NÓRIA sabe fica na tela Conhecimento.']),
  ]);
}

function tabelaCamadas(det) {
  const linhas = f.CAMADAS.map((c) => {
    const v = det ? det.validacoes.filter((x) => x.camada === c) : [];
    if (!v.length) {
      return [f.camada(c), f.camadaConfere(c), etiqueta('sem aferição', 'neutra'),
        el('span.ajuda', { texto: 'nenhuma aferição registrada nesta camada' }), '—'];
    }
    const pior = v.some((x) => x.resultado === 'reprovado') ? 'reprovado'
      : v.every((x) => x.resultado === 'aprovado') ? 'aprovado' : 'nao_verificavel';
    const r = f.resultado(pior);
    return [
      f.camada(c),
      f.camadaConfere(c),
      etiqueta(r.texto, r.tom, true),
      el('div', null, v.map((x) => el('div.ajuda', { texto: f.textoBr(x.justificativa || '—') }))),
      el('div', null, v.map((x) => el('div.ajuda', {
        texto: `${x.revisor}${x.independente ? '' : ' (não independente)'}`,
      }))),
    ];
  });
  return tabela(
    [{ titulo: 'Camada' }, { titulo: 'O que confere' }, { titulo: 'Resultado' },
      { titulo: 'Justificativa' }, { titulo: 'Revisor' }],
    linhas,
  );
}

export async function montar(raiz, _params, { pulso, ir }) {
  const [p, ex] = await Promise.all([api.panorama(), api.execucoes()]);
  const ultima = (p.ultimas_missoes || [])[0];
  let det = null;
  if (ultima) {
    det = await api.missao(ultima.id);
  }

  const execucoes = ex.execucoes || [];
  const msTotal = execucoes.reduce((a, e) => a + (e.ms || 0), 0);
  const linhasTotal = execucoes.reduce((a, e) => a + (e.linhas || 0), 0);

  juntar(raiz, [
    el('div.grade.g4', { style: 'margin-bottom:32px' }, [
      metrica('Estado do núcleo', p.missoes.em_curso ? 'operando' : 'aguardando objetivo',
        p.missoes.em_curso ? `${f.numero(p.missoes.em_curso)} missão(ões) em curso` : 'nenhuma missão em curso',
        { destaque: true, menor: true }),
      metrica('Consultas a ferramenta', f.numero(execucoes.length),
        execucoes.length ? `${f.numero(linhasTotal)} linha(s) lida(s)` : 'nada executado ainda'),
      metrica('Tempo medido em ferramenta', execucoes.length ? f.duracao(msTotal) : f.NADA,
        execucoes.length ? 'soma das execuções registradas' : 'só aparece quando medido'),
      metrica('Evidências ligadas', f.numero(p.evidencias),
        'toda afirmação relevante carrega uma'),
    ]),

    secao('O ciclo, do objetivo ao encerramento',
      ultima
        ? `Etapas destacadas são as que têm registro real. Referência: missão #${ultima.id}, aberta em ${f.dataHora(ultima.criada_em)}.`
        : 'Nenhuma missão foi aberta ainda — as etapas aparecem sem registro, e nenhum número é inventado.',
      ciclo(classificar(pulso.eventos.length ? pulso.eventos : (det ? det.eventos : [])), det)),

    det ? secao('Grafo de execução da missão mais recente', null,
      painel({
        titulo: `Missão #${det.missao.id}`,
        nota: f.textoBr(det.missao.objetivo),
        acoes: el('button.btn.btn-peq', {
          type: 'button', texto: 'Abrir missão', onclick: () => ir(`missoes/${det.missao.id}`),
        }),
        corpo: grafoExecucao(det),
      })) : null,

    secao('Validação em camadas',
      det ? 'Resultado real por camada na missão mais recente. Camada sem aferição aparece como tal.'
        : 'Sem missão, nenhuma camada foi aferida.',
      painel({ corpo: tabelaCamadas(det), semFolga: true })),

    el('div.grade.g-2-1', null, [
      painel({
        titulo: 'Execuções de ferramenta',
        nota: 'toda consulta é registrada',
        corpo: execucoes.length
          ? tabela(
            [{ titulo: 'Ferramenta' }, { titulo: 'Operação' }, { titulo: 'Estado' },
              { titulo: 'Linhas', num: true }, { titulo: 'Tempo', num: true }, { titulo: 'Início' }],
            execucoes.map((e) => [
              e.ferramenta,
              el('span.mono', { texto: e.operacao }),
              etiqueta(e.estado === 'ok' ? 'ok' : e.estado, e.estado === 'ok' ? 'ok' : 'erro', true),
              f.numero(e.linhas),
              f.duracao(e.ms),
              f.dataHora(e.iniciada_em),
            ]),
          )
          : vazio('Nenhuma consulta a ferramenta registrada.', 'Cada leitura no ATUA ou em arquivo aparece aqui com tempo e volume medidos.'),
        semFolga: true,
      }),
      painel({
        titulo: 'Fluxo do núcleo',
        nota: 'leitura a cada 4 s',
        acoes: el('span.etq.acento', null, [el('i.pulso.vivo'), 'ao vivo']),
        corpo: el('div.log', { id: 'log-cerebro', 'aria-live': 'polite' }),
      }),
    ]),
  ]);

  const log = raiz.querySelector('#log-cerebro');
  return pulso.assinar((todos) => {
    limpar(log);
    if (!todos.length) { juntar(log, el('p.ajuda', { texto: 'Nenhum evento registrado ainda.' })); return; }
    todos.slice(0, 40).forEach((ev) => juntar(log, linhaEvento(ev)));
  });
}
