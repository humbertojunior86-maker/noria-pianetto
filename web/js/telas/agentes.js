/* Agentes — habilitados e sem integração no mesmo lugar.
   Nenhuma bolinha verde falsa: quem não pode operar diz por quê. */

import * as api from '../api.js';
import * as f from '../fmt.js';
import { el, juntar, painel, vazio, etiqueta, icone, tabela, secao, migalhas, metrica, par } from '../ui.js';

function selo(situacao) {
  return situacao === 'habilitado'
    ? etiqueta('Habilitado', 'ok', true)
    : etiqueta('Sem integração', 'atencao', true);
}

function cartao(a, ir) {
  return el('article.painel', null, [
    el('div.painel-corpo', null, [
      el('div', { style: 'display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap' }, [
        el('div', { style: 'flex:1 1 200px;min-width:0' }, [
          el('h3', { style: 'font-size:var(--t-base)', texto: `${a.nome} · ${a.papel}` }),
          el('p.ajuda', { style: 'margin:4px 0 0', texto: `${a.area} · ${a.id} · v${a.versao}` }),
        ]),
        selo(a.situacao),
      ]),
      el('p', { style: 'margin:12px 0 0;font-size:var(--t-peq);color:var(--tinta-2)', texto: a.promessa }),
      a.situacao !== 'habilitado' && a.limitacao
        ? el('p.aviso-linha', null, [icone('alerta', 14), `Limitação: ${a.limitacao}`])
        : null,
      el('div.par-linhas', { style: 'margin-top:16px' }, [
        par('Tarefas aprovadas', f.numero(a.tarefas_aprovadas)),
        par('Ferramentas', (a.ferramentas || []).join(', ') || f.NADA),
        par('Ações declaradas', f.numero((a.acoes || []).length)),
      ]),
      el('div.linha-acoes', { style: 'margin-top:16px' },
        el('button.btn.btn-peq', { type: 'button', texto: 'Ver ficha', onclick: () => ir(`agentes/${a.id}`) })),
    ]),
  ]);
}

async function lista(raiz, { ir }) {
  const d = await api.agentes();
  const itens = d.agentes || [];
  const hab = itens.filter((a) => a.situacao === 'habilitado');
  const sem = itens.filter((a) => a.situacao !== 'habilitado');

  const porArea = {};
  sem.forEach((a) => { (porArea[a.area] = porArea[a.area] || []).push(a); });

  juntar(raiz, [
    el('div.grade.g3', { style: 'margin-bottom:32px' }, [
      metrica('Cadastrados', f.numero(itens.length), 'catálogo completo de agentes'),
      metrica('Habilitados', f.numero(hab.length), 'com ferramenta e executor prontos', { destaque: hab.length > 0 }),
      metrica('Sem integração', f.numero(sem.length), 'cada um com a limitação escrita'),
    ]),

    secao('Habilitados', 'Podem receber tarefa agora, com as ações limitadas às fontes autorizadas.',
      hab.length
        ? el('div.grade.g2', null, hab.map((a) => cartao(a, ir)))
        : painel({ corpo: vazio('Nenhum agente habilitado.', 'Sem executor e sem ferramenta disponível, a NÓRIA não despacha tarefa.'), semFolga: true })),

    secao('Sem integração', 'Existem no catálogo, mas não podem operar. A limitação é a declarada pelo próprio agente.',
      sem.length
        ? painel({
          corpo: tabela(
            [{ titulo: 'Agente' }, { titulo: 'Área' }, { titulo: 'Promessa' }, { titulo: 'Situação' }, { titulo: 'Limitação declarada' }, { titulo: '' }],
            sem.map((a) => [
              el('div', null, [el('strong', { texto: `${a.nome} · ${a.papel}` }),
                el('div.ajuda', { texto: a.id })]),
              a.area,
              el('span.ajuda', { texto: a.promessa }),
              selo(a.situacao),
              el('span.ajuda', { texto: a.limitacao || f.NADA }),
              el('button.btn.btn-peq', { type: 'button', texto: 'Ficha', onclick: () => ir(`agentes/${a.id}`) }),
            ]),
          ),
          semFolga: true,
        })
        : painel({ corpo: vazio('Todos os agentes estão habilitados.'), semFolga: true })),
  ]);
  return null;
}

async function ficha(raiz, id, { ir }) {
  const d = await api.agente(id);
  const a = d.agente;
  const hist = d.historico || [];

  juntar(raiz, [
    migalhas([{ texto: 'Agentes', destino: '#/agentes' }, { texto: a.nome }]),
    el('div', { style: 'display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap;margin-bottom:24px' }, [
      el('div', { style: 'flex:1 1 360px;min-width:0' }, [
        el('h2', { style: 'font-size:var(--t-xl)', texto: `${a.nome} · ${a.papel}` }),
        el('p.ajuda', { style: 'margin:6px 0 0', texto: `${a.area} · ${a.id} · versão ${a.versao}` }),
      ]),
      selo(a.situacao),
    ]),

    a.situacao !== 'habilitado'
      ? el('div.aviso-erro', { style: 'margin-bottom:24px' },
        `Este agente não pode operar. Limitação declarada: ${a.limitacao || 'não informada'}.`)
      : null,

    painel({
      titulo: 'Contrato do agente',
      nota: a.promessa,
      corpo: [
        el('div.par-linhas', null, [
          par('Ferramentas', (a.ferramentas || []).join(', ') || f.NADA),
          par('Entradas esperadas', Object.keys(a.entradas || {}).join(', ') || f.NADA),
          par('Saídas declaradas', Object.keys(a.saidas || {}).join(', ') || f.NADA),
        ]),
        (a.acoes || []).length ? el('div', { style: 'margin-top:20px' }, [
          el('h4', { style: 'font-size:var(--t-peq);margin-bottom:8px', texto: 'Ações permitidas' }),
          el('div.chips', null, a.acoes.map((x) => el('span.chip', { texto: x }))),
        ]) : null,
        (a.criterios || []).length ? el('div', { style: 'margin-top:20px' }, [
          el('h4', { style: 'font-size:var(--t-peq);margin-bottom:8px', texto: 'Critérios que o agente aceita ser medido' }),
          el('div.chips', null, a.criterios.map((x) => el('span.chip', {
            texto: typeof x === 'string' ? x : JSON.stringify(x),
          }))),
        ]) : null,
      ],
    }),

    el('div', { style: 'margin-top:24px' }, painel({
      titulo: 'Histórico de tarefas',
      nota: `${f.numero(hist.length)} registro(s)`,
      corpo: hist.length
        ? tabela(
          [{ titulo: 'Tarefa' }, { titulo: 'Missão' }, { titulo: 'Estado' }, { titulo: 'Atualizada' }],
          hist.map((t) => {
            const r = f.estadoTarefa(t.estado);
            return [
              f.textoBr(t.titulo),
              el('a', { href: `#/missoes/${t.missao_id}`, texto: `#${t.missao_id}` }),
              etiqueta(r.texto, r.tom, true),
              f.dataHora(t.atualizada_em),
            ];
          }),
        )
        : vazio('Este agente ainda não recebeu nenhuma tarefa.'),
      semFolga: true,
    })),
  ]);
  return null;
}

export async function montar(raiz, params, contexto) {
  if (params[0]) return ficha(raiz, params.join('/'), contexto);
  return lista(raiz, contexto);
}
