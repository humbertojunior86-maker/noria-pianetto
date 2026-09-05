/* Integrações — estado real, teste real. Nada aparece verde sem conexão. */

import * as api from '../api.js';
import * as f from '../fmt.js';
import { el, juntar, limpar, painel, vazio, etiqueta, icone, secao, par, metrica, carregando } from '../ui.js';

function cartao(i, recarregar) {
  const r = f.estadoIntegracao(i.estado);
  const retorno = el('p.ajuda', { style: 'margin-top:12px' });

  const btn = el('button.btn.btn-peq', {
    type: 'button',
    onclick: async () => {
      btn.disabled = true;
      limpar(retorno);
      retorno.textContent = 'Testando de verdade contra o destino…';
      try {
        const d = await api.testarIntegracao(i.id);
        const rr = f.estadoIntegracao(d.estado);
        retorno.textContent = `Resultado do teste: ${rr.texto.toLowerCase()}${d.detalhe ? ` — ${d.detalhe}` : ''}`;
        setTimeout(recarregar, 900);
      } catch (e) {
        retorno.textContent = `O teste falhou: ${e.message}`;
      } finally {
        btn.disabled = false;
      }
    },
  }, [icone('integracoes', 14), el('span', { texto: 'Testar conexão' })]);

  return painel({
    titulo: i.nome,
    nota: `${i.id} · ${i.tipo} · ambiente ${i.ambiente || f.NADA}`,
    acoes: etiqueta(r.texto, r.tom, true),
    corpo: [
      el('div.par-linhas', null, [
        par('Permissões', (i.permissoes || []).join(', ') || f.NADA),
        par('Escrita', i.escreve ? 'permitida no destino' : 'somente leitura'),
        par('Último teste', i.ultimo_teste ? f.dataHora(i.ultimo_teste) : 'nunca testada'),
      ]),
      i.ultimo_erro
        ? el('p.aviso-linha', null, [icone('alerta', 14), `Erro ou limitação registrada: ${i.ultimo_erro}`])
        : null,
      el('div.linha-acoes', { style: 'margin-top:16px' }, btn),
      retorno,
    ],
  });
}

export async function montar(raiz, _params, _contexto) {
  const alvo = el('div');
  juntar(raiz, secao(null,
    'O estado vem do banco e do último teste executado. O teste consulta o destino de verdade — nunca é simulado.',
    alvo));

  async function carregar() {
    limpar(alvo);
    juntar(alvo, carregando(3));
    const d = await api.integracoes();
    const itens = d.integracoes || [];
    limpar(alvo);
    if (!itens.length) {
      juntar(alvo, painel({ corpo: vazio('Nenhuma integração cadastrada.'), semFolga: true }));
      return;
    }
    const conectadas = itens.filter((i) => i.estado === 'conectada');
    const escrita = itens.filter((i) => i.escreve);
    juntar(alvo, [
      el('div.grade.g3', { style: 'margin-bottom:24px' }, [
        metrica('Conectadas', `${f.numero(conectadas.length)}/${f.numero(itens.length)}`,
          conectadas.map((i) => i.nome).join(', ') || 'nenhuma conexão ativa',
          { destaque: conectadas.length > 0 }),
        metrica('Somente leitura', f.numero(itens.length - escrita.length),
          'nenhuma escrita possível nessas conexões'),
        metrica('Com permissão de escrita', f.numero(escrita.length),
          escrita.length ? 'exigem aprovação humana por ação' : 'nenhuma escrita autorizada'),
      ]),
      el('div.grade.g2', { style: 'gap:24px' }, itens.map((i) => cartao(i, carregar))),
    ]);
  }

  await carregar();
  return null;
}
