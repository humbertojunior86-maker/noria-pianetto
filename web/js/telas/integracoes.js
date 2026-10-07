/* Integrações — estado real, teste real. Nada aparece verde sem conexão. */

import * as api from '../api.js';
import * as f from '../fmt.js';
import { el, juntar, limpar, painel, vazio, etiqueta, icone, secao, par, metrica, carregando } from '../ui.js';

/* ------------------------------------------------------------- Bradesco --
   Credencial entra aqui e nunca volta inteira: a tela vê o Client ID mascarado
   e se certificado e chave existem. Campo vazio não apaga o que já foi
   gravado — dá para reenviar só a parte que mudou. */
function campo(rotulo, entrada, ajuda) {
  return el('div.campo', null, [
    el('label', { texto: rotulo }),
    entrada,
    ajuda ? el('span.ajuda', { texto: ajuda }) : null,
  ]);
}

function pecaEstado(ok, texto) {
  return el('span.brad-peca' + (ok ? '.ok' : '.falta'), { texto: `${ok ? 'tem' : 'falta'} ${texto}` });
}

function blocoBradesco(i, contexto, recarregar) {
  const papel = contexto && contexto.ctx && contexto.ctx.usuario ? contexto.ctx.usuario.papel : '';
  const podeVer = papel === 'ceo' || papel === 'gestor';
  const podeGravar = papel === 'ceo';
  const caixa = el('div.brad');
  if (!podeVer) {
    juntar(caixa, el('p.ajuda', { texto: 'A configuração do banco só aparece para CEO e gestor.' }));
    return caixa;
  }

  async function desenhar() {
    limpar(caixa);
    juntar(caixa, carregando(2));
    let c;
    try {
      c = await api.bradescoConfig();
    } catch (e) {
      limpar(caixa);
      juntar(caixa, el('div.aviso-erro', { texto: `Não deu para ler a configuração: ${e.message}` }));
      return;
    }
    limpar(caixa);

    juntar(caixa, el('div.brad-estado', null, [
      pecaEstado(c.tem_client_id, c.tem_client_id ? `Client ID ${c.client_id_mascarado}` : 'Client ID'),
      pecaEstado(c.tem_client_secret, 'Client Secret'),
      pecaEstado(c.tem_certificado, 'certificado público'),
      pecaEstado(c.tem_chave_privada, 'chave privada'),
      pecaEstado((c.contas || []).length > 0, (c.contas || []).length
        ? `${c.contas.length} conta(s) para consultar` : 'conta para consultar'),
    ]));
    juntar(caixa, el('p.ajuda', {
      texto: `Ambiente ${c.ambiente} · ${c.host} · autenticação ${c.fluxo_confirmado
        ? `confirmada: ${c.fluxo_confirmado}` : `${c.fluxo} (ainda não confirmada pelo banco)`}`,
    }));
    if (c.limitacao) {
      juntar(caixa, el('p.aviso-linha', null, [icone('alerta', 14),
        `Ainda não consulta o banco — ${c.limitacao}.`]));
    }

    if (!podeGravar) return;

    const cid = el('input', { type: 'text', autocomplete: 'off', placeholder: c.tem_client_id ? 'já gravado — preencha só para trocar' : 'Client ID do portal Bradesco Developers' });
    const csec = el('input', { type: 'password', autocomplete: 'new-password', placeholder: c.tem_client_secret ? 'já gravado — preencha só para trocar' : 'Client Secret (visível 3 dias no portal)' });
    const amb = el('select');
    [['producao', 'produção — openapi.bradesco.com.br'], ['sandbox', 'sandbox — openapisandbox.prebanco.com.br'],
      ['homologacao', 'homologação — proxy.api.prebanco.com.br']].forEach(([v, t]) => {
      const o = el('option', { value: v, texto: t });
      if (v === c.ambiente) o.selected = true;
      amb.appendChild(o);
    });
    const fluxo = el('select');
    [['auto', 'automático — mTLS (orientação do banco) primeiro'], ['mtls', 'mTLS: server-mtls/v1/token (orientação do Bradesco, 07/10/2026)'], ['client_credentials', 'credencial cliente/segredo (portal novo)'],
      ['jwt', 'JWT assinado com a chave privada (o que o banco reconheceu)']].forEach(([v, t]) => {
      const o = el('option', { value: v, texto: t });
      if (v === c.fluxo) o.selected = true;
      fluxo.appendChild(o);
    });
    const cert = el('textarea', { placeholder: c.tem_certificado ? 'já gravado — cole só para trocar' : '-----BEGIN CERTIFICATE----- … (ou só o corpo em base64, como o portal aceita)', rows: 4, spellcheck: 'false' });
    const chave = el('textarea', { placeholder: c.tem_chave_privada ? 'já gravada — cole só para trocar' : '-----BEGIN PRIVATE KEY----- … (a chave do MESMO certificado enviado ao portal)', rows: 4, spellcheck: 'false' });
    const contas = el('textarea', {
      rows: 3, spellcheck: 'false',
      placeholder: 'uma conta por linha: agência;conta;tipo;apelido\nex.: 1234;0012345;cc;Conta movimento',
    });
    contas.value = (c.contas || []).map((k) => [k.agencia, k.conta, k.tipo || 'cc', k.apelido || ''].join(';')).join('\n');

    const retorno = el('p.ajuda');
    const salvar = el('button.btn.btn-forte.btn-peq', { type: 'button' }, [icone('integracoes', 14), el('span', { texto: 'Gravar credencial' })]);
    salvar.onclick = async () => {
      salvar.disabled = true;
      retorno.textContent = 'Gravando no servidor da NÓRIA (arquivo restrito, fora do banco de dados)…';
      const dados = { ambiente: amb.value, fluxo: fluxo.value, contas: contas.value };
      if (cid.value.trim()) dados.client_id = cid.value.trim();
      if (csec.value.trim()) dados.client_secret = csec.value.trim();
      if (cert.value.trim()) dados.certificado_pem = cert.value;
      if (chave.value.trim()) dados.chave_privada_pem = chave.value;
      try {
        await api.bradescoGravar(dados);
        retorno.textContent = 'Gravado. Use "Testar conexão" para pedir um token real ao banco.';
        setTimeout(() => { desenhar(); recarregar(); }, 700);
      } catch (e) {
        retorno.textContent = `Não gravou: ${e.message}`;
      } finally {
        salvar.disabled = false;
      }
    };

    // .pfx do e-CNPJ: o servidor separa certificado e chave e confere o par.
    const pfxArq = el('input', { type: 'file', accept: '.pfx,.p12' });
    const pfxSenha = el('input', { type: 'password', autocomplete: 'new-password', placeholder: 'senha do certificado (não é gravada)' });
    const pfxRet = el('p.ajuda');
    const pfxBtn = el('button.btn.btn-forte.btn-peq', { type: 'button' }, [icone('integracoes', 14), el('span', { texto: 'Importar .pfx' })]);
    pfxBtn.onclick = async () => {
      const arq = pfxArq.files && pfxArq.files[0];
      if (!arq) { pfxRet.textContent = 'Escolha o arquivo .pfx primeiro.'; return; }
      pfxBtn.disabled = true;
      pfxRet.textContent = 'Abrindo o certificado no servidor da NÓRIA…';
      try {
        const buf = new Uint8Array(await arq.arrayBuffer());
        let bin = '';
        for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
        const r = await api.bradescoPfx({ pfx_base64: btoa(bin), senha: pfxSenha.value });
        pfxSenha.value = '';
        pfxRet.textContent = `Certificado e chave gravados e conferidos. ${r.certificado || ''}`;
        setTimeout(() => { desenhar(); recarregar(); }, 900);
      } catch (e) {
        pfxRet.textContent = `Não importou: ${e.message}`;
      } finally {
        pfxBtn.disabled = false;
      }
    };
    juntar(caixa, el('div.brad-form', { style: 'margin-bottom:14px' }, [
      campo('Arquivo .pfx do e-CNPJ', pfxArq, 'o jeito mais simples: traz certificado e chave juntos'),
      campo('Senha do .pfx', pfxSenha, 'usada só para abrir o arquivo; não fica gravada em lugar nenhum'),
    ]));
    juntar(caixa, el('div.linha-acoes', { style: 'margin-bottom:18px' }, [pfxBtn, pfxRet]));

    juntar(caixa, [
      el('div.brad-form', null, [
        campo('Client ID', cid),
        campo('Client Secret', csec, 'guardado em arquivo com permissão 600; nunca volta para a tela'),
        campo('Ambiente', amb),
        campo('Autenticação', fluxo),
        campo('Certificado público (PEM)', cert, 'o mesmo arquivo enviado ao portal na hora de gerar a credencial'),
        campo('Chave privada (PEM)', chave, 'sem ela não existe chamada: o banco exige TLS mútuo com este par'),
        campo('Contas a consultar', contas, 'agência com 4 dígitos sem DV, conta com 7 dígitos; tipo cc ou cp'),
      ]),
      el('div.linha-acoes', { style: 'margin-top:12px' }, [salvar, retorno]),
    ]);
  }

  desenhar();
  return caixa;
}

function cartao(i, contexto, recarregar) {
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
      i.id === 'bradesco' ? blocoBradesco(i, contexto, recarregar) : null,
    ],
  });
}

export async function montar(raiz, _params, contexto) {
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
      el('div.grade.g2', { style: 'gap:24px' }, itens.map((i) => cartao(i, contexto, carregar))),
    ]);
  }

  await carregar();
  return null;
}
