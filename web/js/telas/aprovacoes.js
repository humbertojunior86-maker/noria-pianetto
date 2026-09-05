/* Aprovações — ação externa aguardando decisão humana.
   Vazio é dito com clareza: nada de linha de exemplo. */

import * as api from '../api.js';
import * as f from '../fmt.js';
import { el, juntar, limpar, painel, vazio, etiqueta, icone, secao, par, carregando } from '../ui.js';

function cartao(a, recarregar) {
  const aviso = el('div.aviso-erro.oculto');

  async function decidir(decisao, texto) {
    if (decisao === 'rejeitar' && !confirm('Rejeitar esta ação?')) return;
    let observacao = null;
    if (decisao === 'ajustar') {
      observacao = prompt('O que precisa ser ajustado antes de aprovar?');
      if (observacao === null) return;
    }
    aviso.classList.add('oculto');
    try {
      await api.decidir(a.id, decisao, observacao);
      recarregar();
    } catch (e) {
      aviso.textContent = `${texto} não foi aplicado: ${e.message}`;
      aviso.classList.remove('oculto');
    }
  }

  let conteudo = a.conteudo;
  try { conteudo = JSON.stringify(JSON.parse(a.conteudo), null, 2); } catch { /* texto puro */ }

  return painel({
    titulo: f.textoBr(a.titulo || a.tipo || `Ação #${a.id}`),
    nota: `ação #${a.id} · missão #${a.missao_id ?? f.NADA} · proposta em ${f.dataHora(a.criada_em)}`,
    acoes: etiqueta(a.estado === 'ambigua' ? 'Ambígua — reconciliação humana' : 'Aguardando decisão',
      a.estado === 'ambigua' ? 'erro' : 'atencao', true),
    corpo: [
      aviso,
      el('div.par-linhas', null, [
        par('Tipo', a.tipo || f.NADA),
        par('Destino', a.destino || f.NADA),
        par('Impacto declarado', a.impacto || f.NADA),
        par('Válida até', a.valida_ate ? f.dataHora(a.valida_ate) : 'sem prazo declarado'),
        par('Chave de idempotência', a.chave_idem || f.NADA),
      ]),
      conteudo ? el('div', { style: 'margin-top:16px' }, [
        el('h4', { style: 'font-size:var(--t-peq);margin-bottom:8px', texto: 'Conteúdo exato que será enviado' }),
        el('pre.poco', { texto: String(conteudo) }),
      ]) : el('p.aviso-linha', null, [icone('alerta', 14), 'Esta ação não trouxe conteúdo para conferência.']),
      el('div.linha-acoes', { style: 'margin-top:20px' }, [
        el('button.btn.btn-forte.btn-peq', { type: 'button', texto: 'Aprovar', onclick: () => decidir('aprovar', 'A aprovação') }),
        el('button.btn.btn-peq', { type: 'button', texto: 'Pedir ajuste', onclick: () => decidir('ajustar', 'O ajuste') }),
        el('button.btn.btn-peq', { type: 'button', texto: 'Rejeitar', onclick: () => decidir('rejeitar', 'A rejeição') }),
      ]),
    ],
  });
}

export async function montar(raiz, _params, _contexto) {
  const alvo = el('div');
  juntar(raiz, [
    secao(null,
      'Ação externa só sai depois de decisão humana registrada, com o hash do conteúdo aprovado. '
      + 'Hoje a NÓRIA escreve apenas em e-mail, arquivo e artefato — o ATUA é somente leitura.',
      alvo),
  ]);

  async function carregar() {
    limpar(alvo);
    juntar(alvo, carregando(2));
    let d;
    try {
      d = await api.aprovacoes();
    } catch (e) {
      limpar(alvo);
      juntar(alvo, el('div.aviso-erro', { texto: e.message }));
      return;
    }
    const itens = d.acoes || [];
    limpar(alvo);
    if (!itens.length) {
      juntar(alvo, painel({
        corpo: vazio(
          'Nenhuma ação aguardando decisão.',
          'Quando um agente propuser um envio, ele aparece aqui com o conteúdo exato, o destino e o impacto — nunca antes disso.',
        ),
        semFolga: true,
      }));
      return;
    }
    juntar(alvo, el('div.grade', { style: 'gap:24px' }, itens.map((a) => cartao(a, carregar))));
  }

  await carregar();
  return null;
}
