/* Missões — lista, criação por objetivo em texto livre e detalhe completo. */

import * as api from '../api.js';
import * as f from '../fmt.js';
import { el, juntar, limpar, painel, vazio, etiqueta, etiquetaEstado, icone, tabela,
  linhaEvento, secao, migalhas, metrica } from '../ui.js';

/* ------------------------------------------------------- leitura de dados -- */
const ROTULOS = {
  cd_conta: 'Conta',
  data: 'Data de referência',
  movimentos_extrato: 'Movimentos no extrato',
  lancamentos_erp: 'Lançamentos no ERP',
  sem_par_extrato: 'Movimentos sem par',
  valor_divergente: 'Movimentos com valor divergente',
  valor_movimentado: 'Valor movimentado',
  valor_sem_par: 'Valor sem par',
  taxa_conciliacao: 'Taxa de conciliação',
};

function valorFormatado(chave, v) {
  if (v === null || v === undefined) return f.NADA;
  if (/^taxa_|_pct$/.test(chave)) return f.porcento(v);
  if (/^valor_/.test(chave) && chave !== 'valor_divergente') return f.dinheiro(v);
  if (chave === 'data' || /_em$/.test(chave)) return f.data(v);
  // número com centavos é dinheiro no domínio da NORIA: não some com os centavos.
  if (typeof v === 'number' && !Number.isInteger(v)) return f.dinheiro(v);
  if (typeof v === 'number') return f.numero(v);
  return f.textoBr(String(v));
}

function tabelaLancamentos(linhas) {
  return tabela(
    [{ titulo: 'Código' }, { titulo: 'Data' }, { titulo: 'Histórico' }, { titulo: 'Valor', num: true }],
    linhas.map((l) => [
      el('span.mono', { texto: String(l.cd_conciliado ?? f.NADA) }),
      f.data(l.data),
      f.textoBr(l.ds_lancamento || f.NADA),
      f.dinheiro(l.vl_lancamento),
    ]),
  );
}

/* Tabela para qualquer lista de objetos devolvida pela API, sem inventar campo. */
function tabelaGenerica(linhas) {
  const chaves = [];
  linhas.slice(0, 5).forEach((o) => Object.keys(o || {}).forEach((k) => {
    if (!chaves.includes(k) && (o[k] === null || typeof o[k] !== 'object')) chaves.push(k);
  }));
  if (!chaves.length) return el('pre.poco', { texto: JSON.stringify(linhas.slice(0, 6), null, 2) });
  const dinheiroK = (k) => /(^|_)(vl|valor|valores|saldo)(_|$)/.test(k);
  const dataK = (k) => /(^|_)(dt|data)(_|$)/.test(k);
  // código e documento são identificadores: nunca ganham separador de milhar.
  const codigoK = (k) => /(^|_)(cd|nr|id|cod|codigo|documento|doc)(_|$)/.test(k);
  return tabela(
    chaves.map((k) => ({ titulo: ROTULOS[k] || k.replace(/_/g, ' '), num: dinheiroK(k) })),
    linhas.slice(0, 10).map((o) => chaves.map((k) => {
      const v = o ? o[k] : null;
      if (v === null || v === undefined || v === '') return f.NADA;
      // API às vezes devolve número como texto; converte antes de formatar.
      const n = typeof v === 'number' ? v
        : (typeof v === 'string' && /^-?\d+(\.\d+)?$/.test(v.trim()) ? Number(v) : null);
      if (codigoK(k)) return el('span.mono', { texto: String(v) });
      if (dinheiroK(k) && n !== null) return f.dinheiro(n);
      if (dataK(k) || (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}/.test(v))) return f.data(v);
      if (n !== null) return f.numero(n);
      if (typeof v === 'boolean') return v ? 'sim' : 'não';
      return f.textoBr(String(v));
    })),
  );
}

function bloco(dados) {
  const simples = [];
  const listas = [];
  Object.entries(dados || {}).forEach(([k, v]) => {
    if (Array.isArray(v)) listas.push([k, v]);
    else if (v !== null && typeof v === 'object') listas.push([k, [v]]);
    else simples.push([k, v]);
  });
  return el('div', null, [
    simples.length ? el('div.par-linhas', null, simples.map(([k, v]) =>
      el('div.par', null, [
        el('span', { texto: ROTULOS[k] || k.replace(/_/g, ' ') }),
        el('b', { texto: valorFormatado(k, v) }),
      ]))) : null,
    ...listas.map(([k, v]) => el('div', { style: 'margin-top:20px' }, [
      el('h4', { style: 'font-size:var(--t-peq);margin-bottom:8px', texto: ROTULOS[k] || k.replace(/_/g, ' ') }),
      v.length && v[0] && v[0].ds_lancamento !== undefined
        ? tabelaLancamentos(v.slice(0, 10))
        : (v.length && v[0] !== null && typeof v[0] === 'object'
          ? tabelaGenerica(v)
          : el('pre.poco', { texto: JSON.stringify(v.slice(0, 40), null, 2) })),
      el('p.ajuda', {
        style: 'margin-top:8px',
        texto: v.length > 10
          ? `Mostrando 10 de ${f.numero(v.length)} linha(s) da amostra devolvida pela API.`
          : `${f.numero(v.length)} linha(s) — amostra devolvida pela API.`,
      }),
    ])),
  ]);
}

/* -------------------------------------------------------------- criação --- */
function formulario(aoCriar) {
  const objetivo = el('textarea', {
    id: 'objetivo',
    placeholder: 'Ex.: Conciliar o extrato da conta 1 em 10/08/2026 contra os lançamentos do ATUA',
  });
  const aviso = el('div.aviso-erro.oculto');
  const btn = el('button.btn.btn-forte', { type: 'submit', texto: 'Abrir missão' });

  const form = el('form', {
    onsubmit: async (ev) => {
      ev.preventDefault();
      aviso.classList.add('oculto');
      btn.disabled = true;
      btn.textContent = 'Interpretando o objetivo…';
      try {
        const r = await api.criarMissao(objetivo.value.trim());
        objetivo.value = '';
        aoCriar(r);
      } catch (e) {
        aviso.textContent = e.message;
        aviso.classList.remove('oculto');
      } finally {
        btn.disabled = false;
        btn.textContent = 'Abrir missão';
      }
    },
  }, [
    aviso,
    el('div.campo', null, [
      el('label', { for: 'objetivo', texto: 'Objetivo em texto livre' }),
      objetivo,
    ]),
    el('p.ajuda', {
      texto: 'A NÓRIA interpreta o objetivo, define critérios verificáveis e monta o plano. '
        + 'Se não houver agente habilitado para o assunto, ela diz isso em vez de improvisar.',
    }),
    el('div.linha-acoes', { style: 'margin-top:16px' }, btn),
  ]);
  return form;
}

/* ---------------------------------------------------------------- lista --- */
async function lista(raiz, { ir }) {
  let estado = '';
  const alvo = el('div');

  const seletor = el('select', { 'aria-label': 'Filtrar por estado' }, [
    el('option', { value: '', texto: 'Todos os estados' }),
    ...f.ESTADOS_MISSAO.map((e) => el('option', { value: e, texto: f.estadoMissao(e).texto })),
  ]);
  seletor.addEventListener('change', () => { estado = seletor.value; carregar(); });

  async function carregar() {
    limpar(alvo);
    juntar(alvo, el('div.esqueleto', { style: 'height:120px' }));
    const d = await api.missoes(estado || undefined);
    const itens = d.missoes || [];
    limpar(alvo);
    if (!itens.length) {
      juntar(alvo, painel({
        corpo: vazio(
          estado ? `Nenhuma missão no estado "${f.estadoMissao(estado).texto}".` : 'Nenhuma missão registrada.',
          'Descreva um objetivo no campo acima para a NÓRIA montar o plano.',
        ),
        semFolga: true,
      }));
      return;
    }
    juntar(alvo, painel({
      titulo: 'Missões',
      nota: `${f.numero(itens.length)} listada(s)`,
      corpo: el('ul.lista', null, itens.map((m) => el('li', null, el('button.item', {
        type: 'button', onclick: () => ir(`missoes/${m.id}`),
      }, [
        el('div.corpo', null, [
          el('p.tit', { texto: f.textoBr(m.objetivo) }),
          el('div.meta', null, [
            el('span', { texto: `#${m.id}` }),
            el('span', { texto: `origem ${m.origem || f.NADA}` }),
            el('span', { texto: `prioridade ${m.prioridade || f.NADA}` }),
            el('span', { texto: `aberta ${f.dataHora(m.criada_em)}` }),
            m.encerrada_em ? el('span', { texto: `encerrada ${f.dataHora(m.encerrada_em)}` }) : null,
          ]),
        ]),
        el('div.direita', null, [etiquetaEstado(m.estado), icone('seta', 14)]),
      ])))),
      semFolga: true,
    }));
  }

  juntar(raiz, [
    secao('Abrir uma missão', null, painel({ corpo: formulario((r) => ir(`missoes/${r.missao_id}`)) })),
    el('div.filtros', null, [
      el('span.ajuda', { texto: 'Filtrar:' }), seletor,
      el('button.btn.btn-peq', { type: 'button', texto: 'Recarregar', onclick: () => carregar() }),
    ]),
    alvo,
  ]);
  await carregar();
  return null;
}

/* --------------------------------------------------------------- detalhe -- */
function tabelaCamadas(validacoes) {
  return tabela(
    [{ titulo: 'Camada' }, { titulo: 'O que confere' }, { titulo: 'Resultado' },
      { titulo: 'Justificativa' }, { titulo: 'Revisor' }],
    f.CAMADAS.map((c) => {
      const v = validacoes.filter((x) => x.camada === c);
      if (!v.length) {
        return [f.camada(c), f.camadaConfere(c), etiqueta('sem aferição', 'neutra'),
          el('span.ajuda', { texto: 'nenhuma aferição registrada nesta camada' }), f.NADA];
      }
      const pior = v.some((x) => x.resultado === 'reprovado') ? 'reprovado'
        : v.every((x) => x.resultado === 'aprovado') ? 'aprovado' : 'nao_verificavel';
      const r = f.resultado(pior);
      return [
        f.camada(c),
        f.camadaConfere(c),
        etiqueta(r.texto, r.tom, true),
        el('div', null, v.map((x) => el('div.ajuda', { texto: f.textoBr(x.justificativa || f.NADA) }))),
        el('div', null, v.map((x) => el('div.ajuda', {
          texto: `${x.revisor}${x.independente ? '' : ' (não independente)'}`,
        }))),
      ];
    }),
  );
}

async function detalhe(raiz, id, { ir }) {
  const d = await api.missao(id);
  const m = d.missao;
  const est = f.estadoMissao(m.estado);
  const res = m.resultado || {};
  const emCurso = ['planejada', 'executando', 'validando', 'replanejando', 'rascunho'].includes(m.estado);

  const botoes = el('div.linha-acoes');
  if (emCurso) {
    juntar(botoes, [
      el('button.btn.btn-forte.btn-peq', {
        type: 'button', texto: 'Avançar o ciclo',
        onclick: async (ev) => {
          ev.target.disabled = true;
          try { await api.avancarMissao(id); location.reload(); } catch (e) { alert(e.message); ev.target.disabled = false; }
        },
      }),
      el('button.btn.btn-peq', {
        type: 'button', texto: 'Cancelar missão',
        onclick: async () => {
          if (!confirm('Cancelar esta missão? Efeito externo já ocorrido não é desfeito.')) return;
          try { await api.cancelarMissao(id, 'cancelada na interface'); location.reload(); } catch (e) { alert(e.message); }
        },
      }),
    ]);
  }
  juntar(botoes, el('a.btn.btn-peq', { href: `#/entregas/${id}`, texto: 'Ver entregas' }));

  const criterios = d.criterios || [];
  const aprovados = criterios.filter((c) => c.resultado === 'aprovado').length;

  juntar(raiz, [
    migalhas([{ texto: 'Missões', destino: '#/missoes' }, { texto: `#${m.id}` }]),
    el('div', { style: 'display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap;margin-bottom:24px' }, [
      el('div', { style: 'flex:1 1 420px;min-width:0' }, [
        el('h2', { style: 'font-size:var(--t-xl);margin-bottom:8px', texto: f.textoBr(m.objetivo) }),
        el('div.chips', null, [
          etiqueta(est.texto, est.tom, true),
          res.natureza ? etiqueta(`natureza: ${f.natureza(res.natureza).texto.toLowerCase()}`, f.natureza(res.natureza).tom) : null,
          etiqueta(`origem ${m.origem || f.NADA}`, 'neutra'),
          etiqueta(`prioridade ${m.prioridade || f.NADA}`, 'neutra'),
        ]),
      ]),
      botoes,
    ]),

    el('div.grade.g4', { style: 'margin-bottom:32px' }, [
      metrica('Critérios aprovados', `${f.numero(aprovados)}/${f.numero(criterios.length)}`,
        criterios.length ? 'aferidos por código quando possível' : 'nenhum critério registrado'),
      metrica('Tarefas', f.numero(d.tarefas.length),
        `${f.numero(d.tarefas.filter((t) => t.estado === 'aprovada').length)} aprovada(s)`),
      metrica('Aberta em', f.dataHora(m.criada_em),
        m.encerrada_em ? `encerrada ${f.dataHora(m.encerrada_em)}` : 'em aberto', { menor: true }),
      metrica('Artefatos', f.numero(d.artefatos.length), d.artefatos.length ? 'prontos para baixar' : 'nenhum arquivo gerado'),
    ]),

    (res.conferencia || []).length ? secao('Contraprova',
      'Outro agente foi atrás do mesmo fato por outro caminho do banco. Ele não repetiu a consulta — se repetisse, o "confere" não valeria nada.',
      el('div.grade', null, (res.conferencia || []).map((c) => {
        const vd = { confirma: ['Confirma', 'ok'], contradiz: ['Contradiz', 'erro'] }[c.veredito] || ['Não verificável', 'atencao'];
        return painel({
          titulo: c.agente || c.agente_id,
          nota: 'conferiu por outro caminho do banco',
          corpo: [
            el('div.chips', { style: 'margin-bottom:12px' }, [etiqueta(vd[0], vd[1], true)]),
            el('p', { style: 'margin:0', texto: f.textoBr(c.resumo) }),
          ],
        });
      }))) : null,

    res.conclusao ? secao(null, null, painel({
      titulo: 'Conclusão do núcleo',
      nota: res.natureza ? `natureza ${f.natureza(res.natureza).texto.toLowerCase()}` : null,
      corpo: [
        el('p', { style: 'margin:0 0 16px', texto: f.textoBr(res.conclusao) }),
        bloco(res.dados),
        el('p.aviso-linha', null, [icone('relogio', 14),
          `Números herdados de consulta ao ATUA. Última leitura registrada em ${f.dataHora(m.encerrada_em || m.criada_em)}.`]),
      ],
    })) : null,

    secao('Plano e tarefas', null, el('div.grade', null, [
      painel({
        titulo: 'Planos',
        nota: `vigente: v${m.plano_vigente ?? f.NADA}`,
        corpo: d.planos.length ? tabela(
          [{ titulo: 'Versão' }, { titulo: 'Estratégia' }, { titulo: 'Motivo' }, { titulo: 'Criado em' }],
          d.planos.map((p) => [`v${p.versao}`, String(p.estrategia).replace(/_/g, ' '), p.motivo || f.NADA, f.dataHora(p.criado_em)]),
        ) : vazio('Nenhum plano registrado.'),
        semFolga: true,
      }),
      painel({
        titulo: 'Tarefas',
        corpo: d.tarefas.length ? tabela(
          [{ titulo: 'Tarefa' }, { titulo: 'Agente' }, { titulo: 'Estado' },
            { titulo: 'Tentativas', num: true }, { titulo: 'Ações permitidas' }, { titulo: 'Atualizada' }],
          d.tarefas.map((t) => {
            const r = f.estadoTarefa(t.estado);
            return [
              el('div', null, [el('strong', { texto: f.textoBr(t.titulo) }),
                el('div.ajuda', { texto: `chave ${t.chave}` })]),
              t.agente_id,
              etiqueta(r.texto, r.tom, true),
              `${f.numero(t.tentativas)}/${f.numero(t.max_tentativas)}`,
              el('div.chips', null, (t.acoes_permitidas || []).map((a) => el('span.chip', { texto: a }))),
              f.dataHora(t.atualizada_em),
            ];
          }),
        ) : vazio('Nenhuma tarefa criada.'),
        semFolga: true,
      }),
    ])),

    secao('Critérios', 'Cada critério tem resultado próprio. Missão não fecha como concluída com critério obrigatório reprovado.',
      painel({
        corpo: criterios.length ? tabela(
          [{ titulo: '#', num: true }, { titulo: 'Verificador' }, { titulo: 'Camada' },
            { titulo: 'Obrigatório' }, { titulo: 'Resultado' }, { titulo: 'Justificativa' }, { titulo: 'Aferido em' }],
          criterios.map((c) => {
            const r = f.resultado(c.resultado);
            return [
              f.numero(c.ordem),
              el('div', null, [el('strong', { texto: c.verificador || c.descricao }),
                c.parametros && c.parametros !== '{}' ? el('div.ajuda', { texto: c.parametros }) : null]),
              f.camada(c.camada),
              c.obrigatorio ? 'sim' : 'não',
              etiqueta(r.texto, r.tom, true),
              f.textoBr(c.justificativa || f.NADA),
              f.dataHora(c.aferido_em),
            ];
          }),
        ) : vazio('Nenhum critério registrado.'),
        semFolga: true,
      })),

    secao('Validação em 6 camadas', 'Confiança autodeclarada não vale. Duas fontes com a mesma origem contam como uma.',
      painel({ corpo: tabelaCamadas(d.validacoes || []), semFolga: true })),

    secao('Artefatos', null, painel({
      corpo: d.artefatos.length ? tabela(
        [{ titulo: 'Arquivo' }, { titulo: 'Formato' }, { titulo: 'Tamanho', num: true },
          { titulo: 'Versão', num: true }, { titulo: 'Criado em' }, { titulo: '' }],
        d.artefatos.map((a) => [
          el('div', null, [el('strong', { texto: f.textoBr(a.nome) }),
            el('div.ajuda', { texto: a.caminho })]),
          a.formato,
          f.bytes(a.bytes),
          f.numero(a.versao),
          f.dataHora(a.criado_em),
          el('button.btn.btn-peq', {
            type: 'button',
            onclick: async (ev) => {
              const b = ev.currentTarget;
              b.disabled = true;
              try { await api.baixarArtefato(a.id, `${a.nome}.${a.formato}`); } catch (e) { alert(e.message); }
              b.disabled = false;
            },
          }, [icone('baixar', 14), el('span', { texto: 'Baixar' })]),
        ]),
      ) : vazio('Nenhum artefato gerado nesta missão.'),
      semFolga: true,
    })),

    secao('Trilha de eventos', 'Registro append only, em ordem de acontecimento.', painel({
      corpo: (d.eventos || []).length
        ? el('div.log', { style: 'max-height:none' }, d.eventos.map((ev) => linhaEvento(ev)))
        : vazio('Nenhum evento registrado.'),
    })),
  ]);
  return null;
}

export async function montar(raiz, params, contexto) {
  if (params[0] && !/^\d+$/.test(params[0])) {
    juntar(raiz, painel({
      corpo: vazio(`Não existe missão "${params[0]}".`,
        'O endereço da missão é o número dela, como #/missoes/1.'),
    }));
    return null;
  }
  if (params[0]) return detalhe(raiz, params[0], contexto);
  return lista(raiz, contexto);
}
