/* Conhecimento — importação de arquivos com o parser OFX existente
   (js/ofx.js, window.NoriaOFX) e o acervo que a API expõe hoje.

   Regra: a leitura do arquivo acontece no navegador. Enquanto não existir a
   rota de ingestão, isso é dito na tela — nada é apresentado como indexado. */

import * as api from '../api.js';
import * as f from '../fmt.js';
import { el, juntar, limpar, painel, vazio, etiqueta, icone, tabela, secao, par, metrica } from '../ui.js';

const OFX = window.NoriaOFX;

function resumoExtrato(x) {
  const d = OFX.diagnosticoSemantico(x.transacoes);
  const int = x.integridade;
  return el('div', null, [
    el('div.grade.g4', { style: 'margin-bottom:20px' }, [
      metrica('Movimentos', f.numero(x.resumo.total), `${f.numero(x.resumo.creditos)} crédito(s), ${f.numero(x.resumo.debitos)} débito(s)`),
      metrica('Créditos', f.dinheiro(x.resumo.somaCreditos), 'entradas no período', { menor: true }),
      metrica('Débitos', f.dinheiro(x.resumo.somaDebitos), 'saídas no período', { menor: true }),
      metrica('Líquido', f.dinheiro(x.resumo.liquido), x.saldo ? `saldo declarado ${f.dinheiro(x.saldo.valor)}` : 'sem saldo declarado no arquivo', { menor: true }),
    ]),
    el('div.par-linhas', { style: 'margin-bottom:20px' }, [
      par('Arquivo', x.arquivo),
      par('Versão', x.versao),
      par('Banco', x.conta.banco),
      par('Agência / conta', `${x.conta.agencia} / ${x.conta.numero}`),
      par('Período', `${f.data(OFX.iso(x.periodo.inicio))} a ${f.data(OFX.iso(x.periodo.fim))}`),
      par('Moeda', x.conta.moeda),
    ]),
    el('h4', { style: 'font-size:var(--t-peq);margin-bottom:8px', texto: 'Integridade do arquivo' }),
    el('div.chips', { style: 'margin-bottom:20px' }, [
      el('span.chip', { texto: `${f.numero(int.fitidRepetidos.length)} identificador(es) repetido(s)` }),
      el('span.chip', { texto: `${f.numero(int.semFitid)} movimento(s) sem identificador` }),
      el('span.chip', { texto: `${f.numero(int.buracos.length)} dia(s) útil(eis) sem movimento` }),
      el('span.chip', { texto: `${f.numero(d.naoClassificados)} histórico(s) não classificado(s)` }),
      el('span.chip', { texto: `${f.porcento(d.pctChaveForte)} com chave forte (end-to-end ou nosso número)` }),
    ]),
    el('h4', { style: 'font-size:var(--t-peq);margin-bottom:8px', texto: 'Naturezas encontradas no histórico' }),
    tabela([{ titulo: 'Natureza' }, { titulo: 'Movimentos', num: true }, { titulo: 'Participação', num: true }],
      d.porNatureza.map(([nome, n]) => [nome, f.numero(n), f.porcento(n / x.resumo.total)])),
    el('h4', { style: 'font-size:var(--t-peq);margin:20px 0 8px', texto: 'Primeiros movimentos lidos' }),
    tabela([{ titulo: 'Data' }, { titulo: 'Histórico' }, { titulo: 'Identificador' }, { titulo: 'Valor', num: true }],
      x.transacoes.slice(0, 12).map((t) => [
        f.data(OFX.iso(t.data)),
        f.textoBr(t.memo || t.historico || f.NADA),
        el('span.mono', { texto: t.fitid || f.NADA }),
        f.dinheiro(t.valor),
      ])),
    el('p.ajuda', { style: 'margin-top:12px', texto: `Exibindo 12 de ${f.numero(x.transacoes.length)} movimentos lidos do arquivo.` }),
  ]);
}

function resumoAtua(a) {
  return el('div', null, [
    el('div.par-linhas', { style: 'margin-bottom:16px' }, [
      par('Arquivo', a.arquivo),
      par('Separador', a.separador),
      par('Modo de valor', a.modoValor),
      par('Linhas viradas em lançamento', f.numero(a.resumo.total)),
      par('Linhas descartadas', f.numero(a.resumo.descartadas)),
      par('Líquido', f.dinheiro(a.resumo.liquido)),
    ]),
    a.naoMapeadas && a.naoMapeadas.length
      ? el('p.aviso-linha', null, [icone('alerta', 14), `Colunas não mapeadas: ${a.naoMapeadas.join(', ')}`])
      : null,
  ]);
}

function resumoConfronto(c) {
  const t = c.totais;
  return el('div', null, [
    el('div.grade.g4', { style: 'margin-bottom:20px' }, [
      metrica('Pareados', `${f.numero(t.casados)}/${f.numero(t.banco)}`, `taxa ${f.porcento(t.taxa)}`, { destaque: true }),
      metrica('Sem par no banco', f.numero(t.semParBanco), 'movimento do extrato sem lançamento'),
      metrica('Sem par no ATUA', f.numero(t.semParAtua), 'lançamento sem movimento no extrato'),
      metrica('Valor em divergência', f.dinheiro(t.valorSemPar), 'soma absoluta das divergências', { menor: true }),
    ]),
    c.divergencias.length
      ? tabela([{ titulo: 'Tipo' }, { titulo: 'Data' }, { titulo: 'Histórico' }, { titulo: 'Severidade' }, { titulo: 'Valor', num: true }],
        c.divergencias.slice(0, 15).map((x) => [
          x.tipo,
          f.data(OFX.iso(x.data)),
          f.textoBr(x.historico || f.NADA),
          etiqueta(x.severidade, x.severidade === 'alta' ? 'erro' : x.severidade === 'media' ? 'atencao' : 'neutra'),
          f.dinheiro(x.valor),
        ]))
      : el('p.ajuda', { texto: 'Nenhuma divergência encontrada entre os dois arquivos.' }),
    el('p.ajuda', {
      style: 'margin-top:12px',
      texto: 'Confronto feito no navegador, sobre os arquivos carregados agora. É leitura de apoio: '
        + 'a conciliação oficial é a que roda no núcleo, dentro de uma missão, com evidência gravada.',
    }),
  ]);
}

export async function montar(raiz, _params, _contexto) {
  const saida = el('div');
  const estado = { extrato: null, atua: null };

  function redesenhar() {
    limpar(saida);
    const partes = [];
    if (estado.extrato) {
      partes.push(painel({
        titulo: 'Extrato bancário lido',
        nota: `${estado.extrato.conta.banco} · ${estado.extrato.arquivo}`,
        corpo: resumoExtrato(estado.extrato),
      }));
    }
    if (estado.atua) {
      partes.push(painel({
        titulo: 'Lançamentos do ATUA lidos do arquivo',
        nota: estado.atua.arquivo,
        corpo: resumoAtua(estado.atua),
      }));
    }
    if (estado.extrato && estado.atua) {
      let c = null;
      try { c = OFX.conciliar(estado.extrato.transacoes, estado.atua.lancamentos); } catch (e) {
        partes.push(el('div.aviso-erro', { texto: `Não deu para confrontar os arquivos: ${e.message}` }));
      }
      if (c) partes.push(painel({ titulo: 'Confronto extrato × ATUA', nota: 'cálculo local, no navegador', corpo: resumoConfronto(c) }));
    }
    if (!partes.length) {
      partes.push(painel({
        corpo: vazio('Nenhum arquivo carregado nesta sessão.',
          'Carregue um extrato OFX (e, se quiser, o CSV de lançamentos do ATUA) para conferir cobertura, integridade e naturezas.'),
        semFolga: true,
      }));
    }
    juntar(saida, el('div.grade', { style: 'gap:24px' }, partes));
  }

  const aviso = el('div.aviso-erro.oculto');

  async function receber(arquivos) {
    aviso.classList.add('oculto');
    for (const arq of arquivos) {
      const texto = await arq.text();
      try {
        if (/\.ofx$/i.test(arq.name) || texto.toUpperCase().includes('<OFX>')) {
          estado.extrato = OFX.parseOFX(texto, arq.name);
        } else {
          estado.atua = OFX.parseATUA(texto, arq.name);
        }
      } catch (e) {
        aviso.textContent = `${arq.name}: ${e.message}`;
        aviso.classList.remove('oculto');
      }
    }
    redesenhar();
  }

  const entrada = el('input', {
    type: 'file', id: 'arquivo', multiple: true, accept: '.ofx,.csv,.txt',
    onchange: (ev) => receber([...ev.target.files]),
  });

  const zona = el('label.zona-arquivo', { for: 'arquivo' }, [
    entrada,
    el('div', null, [
      icone('conhecimento', 22),
      el('p', { style: 'margin:8px 0 4px;color:var(--tinta-2)', texto: 'Solte aqui o extrato OFX ou o CSV de lançamentos do ATUA' }),
      el('p.ajuda', { texto: 'Leitura feita no navegador pelo parser da própria NÓRIA. Nada é enviado sem missão.' }),
    ]),
  ]);
  zona.addEventListener('dragover', (ev) => { ev.preventDefault(); zona.classList.add('sobre'); });
  zona.addEventListener('dragleave', () => zona.classList.remove('sobre'));
  zona.addEventListener('drop', (ev) => {
    ev.preventDefault();
    zona.classList.remove('sobre');
    receber([...ev.dataTransfer.files]);
  });

  const arte = await api.artefatos();
  const artefatos = arte.artefatos || [];

  juntar(raiz, [
    secao('Importar arquivo', null, painel({ corpo: [aviso, zona] })),
    secao('Leitura do arquivo', null, saida),
    secao('Acervo da NÓRIA', 'Documentos que o núcleo gerou e mantém em disco, com origem e versão.',
      painel({
        titulo: 'Artefatos indexados',
        nota: `${f.numero(artefatos.length)} arquivo(s)`,
        corpo: artefatos.length
          ? tabela(
            [{ titulo: 'Documento' }, { titulo: 'Missão' }, { titulo: 'Formato' },
              { titulo: 'Tamanho', num: true }, { titulo: 'Versão', num: true }, { titulo: 'Criado em' }, { titulo: '' }],
            artefatos.map((a) => [
              el('div', null, [el('strong', { texto: f.textoBr(a.nome) }), el('div.ajuda', { texto: a.caminho })]),
              el('a', { href: `#/missoes/${a.missao_id}`, texto: `#${a.missao_id}` }),
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
          )
          : vazio('Nenhum documento no acervo.', 'Artefato aparece aqui quando uma missão o gera.'),
        semFolga: true,
      })),
    el('p.aviso-linha', null, [icone('alerta', 14),
      'Esta versão da API não expõe rota de ingestão nem índice de documentos (/api/conhecimento). '
      + 'Enquanto isso não existir, o que é lido aqui fica só nesta sessão do navegador e não é apresentado como indexado.']),
  ]);

  redesenhar();
  return null;
}
