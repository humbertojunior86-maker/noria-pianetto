/* ============================================================
   CORTEX · Tela "Arquivos do dia"
   Lê OFX de banco e extrato do ATUA direto no navegador,
   concilia de verdade e mostra o que ficou sem par.
   ============================================================ */

const brl = (v, c = 2) => v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: c, maximumFractionDigits: c });
const pct = (v, d = 1) => `${(v * 100).toFixed(d).replace('.', ',')}%`;
const esc = (s) => String(s).replace(/[<>&]/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));

export const ARQ = { ofx: [], atua: null, rec: null, erros: [] };

let refresh = () => {};
export function ligaArquivos(fn) { refresh = fn; }

/* ---------- leitura de arquivos ---------- */

/* OFX brasileiro costuma vir em Windows-1252. Detecta e reconverte. */
async function leTexto(file) {
  const buf = await file.arrayBuffer();
  let t = new TextDecoder('utf-8', { fatal: false }).decode(buf);
  if (/\uFFFD/.test(t)) t = new TextDecoder('windows-1252').decode(buf);
  return t;
}

export async function ingerir(files) {
  const { parseOFX, parseATUA, conciliar } = window.CortexOFX;
  ARQ.erros = [];
  for (const f of files) {
    let texto;
    try { texto = await leTexto(f); }
    catch { ARQ.erros.push({ arquivo: f.name, msg: 'Não consegui abrir o arquivo.' }); continue; }

    const ofxLike = /\.ofx$/i.test(f.name) || texto.toUpperCase().includes('<OFX>');
    try {
      if (ofxLike) {
        const r = parseOFX(texto, f.name);
        const jaTem = ARQ.ofx.find(x => x.arquivo === r.arquivo);
        if (jaTem) ARQ.ofx = ARQ.ofx.filter(x => x !== jaTem);
        ARQ.ofx.push(r);
      } else {
        ARQ.atua = parseATUA(texto, f.name);
      }
    } catch (e) {
      ARQ.erros.push({ arquivo: f.name, msg: e.message });
    }
  }

  ARQ.rec = null;
  if (ARQ.ofx.length && ARQ.atua) {
    const todas = ARQ.ofx.flatMap(f => f.transacoes);
    ARQ.rec = conciliar(todas, ARQ.atua.lancamentos);
  }
  refresh();
}

export async function carregarExemplos() {
  const alvos = [
    'exemplos/extrato-bb-3054-121204.ofx',
    'exemplos/atua-lancamentos-28-08-a-04-09.csv',
  ];
  const files = [];
  for (const url of alvos) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`Não achei ${url}`);
    const b = await r.blob();
    files.push(new File([b], url.split('/').pop()));
  }
  ARQ.ofx = []; ARQ.atua = null;
  await ingerir(files);
}

export function limpar() {
  ARQ.ofx = []; ARQ.atua = null; ARQ.rec = null; ARQ.erros = [];
  refresh();
}

/* ---------- render ---------- */

const NIVEL_CLS = { alto: 'crit', medio: 'warn', baixo: 'steel' };
const SEV_CLS = { alta: 'crit', media: 'warn', baixa: 'steel' };

function zonaUpload() {
  return `
  <section class="panel">
    <header><h3>Arquivos do dia</h3><span class="eyebrow">processado no seu navegador · nada é enviado</span></header>
    <div class="body">
      <div class="drops">
        <label class="drop" data-drop="ofx">
          <input type="file" accept=".ofx,.OFX,text/plain" multiple hidden />
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><path d="M12 16V4m0 0L8 8m4-4l4 4"/><path d="M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3"/></svg>
          <b>Extrato do banco · OFX</b>
          <span>Mesmo arquivo que você importa no ATUA. Aceita vários bancos de uma vez.</span>
        </label>
        <label class="drop" data-drop="atua">
          <input type="file" accept=".csv,.txt,text/csv" hidden />
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/></svg>
          <b>Lançamentos do ATUA · CSV</b>
          <span>Exporte o razão do período com data, documento, histórico e valor.</span>
        </label>
      </div>
      <div class="drop-acts">
        <button class="btn" type="button" data-arq="exemplo">Rodar com arquivos de exemplo</button>
        ${(ARQ.ofx.length || ARQ.atua) ? '<button class="btn" type="button" data-arq="limpar">Limpar tudo</button>' : ''}
        <span class="hint">O arquivo não sai da sua máquina: a leitura e a conciliação acontecem aqui dentro.</span>
      </div>
      ${ARQ.erros.length ? `<div class="erros">${ARQ.erros.map(e => `<div><b>${esc(e.arquivo)}</b> — ${esc(e.msg)}</div>`).join('')}</div>` : ''}
    </div>
  </section>`;
}

function vazio() {
  return `
  ${zonaUpload()}
  <div class="grid g-2" style="margin-top:14px">
    <section class="panel"><header><h3>O que o CORTEX faz com o OFX</h3></header>
      <div class="body passo">
        <div class="p"><i>01</i><div><b>Lê o arquivo na origem</b><span>O mesmo OFX que entra no ATUA é lido aqui de forma independente. Se o CORTEX consultasse o extrato já importado, estaria comparando o ATUA com ele mesmo.</span></div></div>
        <div class="p"><i>02</i><div><b>Confere a integridade do arquivo</b><span>Identificador repetido, movimento sem FITID, período sobreposto entre dois arquivos e ausência de saldo de fechamento.</span></div></div>
        <div class="p"><i>03</i><div><b>Casa contra o ATUA em 4 regras</b><span>Documento exato, tolerância de centavos e dias, agrupamento de títulos e similaridade de histórico.</span></div></div>
        <div class="p"><i>04</i><div><b>Transforma o que sobrou em hipótese</b><span>Crédito sem título, baixa sem dinheiro, pagamento fora do sistema e divergência de valor viram caso com dono e prazo.</span></div></div>
      </div>
    </section>
    <section class="panel"><header><h3>Onde baixar o OFX em cada banco</h3><span class="eyebrow">fase 1</span></header>
      <table>
        <thead><tr><th>Banco</th><th>Caminho no internet banking</th><th>Janela</th></tr></thead>
        <tbody>
          <tr><td>Banco do Brasil</td><td style="color:var(--ink-2)">Conta corrente › Extrato › Salvar em outros formatos › Money (OFX)</td><td class="num">até 90 dias</td></tr>
          <tr><td>Sicredi</td><td style="color:var(--ink-2)">Conta › Extrato › Exportar › OFX</td><td class="num">até 90 dias</td></tr>
          <tr><td>Itaú</td><td style="color:var(--ink-2)">Extrato › Salvar › OFX / Money</td><td class="num">até 6 meses</td></tr>
          <tr><td>Bradesco</td><td style="color:var(--ink-2)">Extrato › Exportar › OFX · retorno CNAB pelo Net Empresa</td><td class="num">até 90 dias</td></tr>
        </tbody>
      </table>
      <div class="body" style="border-top:1px solid var(--line)">
        <p style="margin:0;font-size:12.2px;color:var(--ink-3);line-height:1.65">Na fase 2 esse download deixa de ser manual: as APIs bancárias e o retorno CNAB alimentam o núcleo sozinhos, com saldo em tempo real e identificação do pagador.</p>
      </div>
    </section>
  </div>`;
}

function cabecalhoArquivos() {
  const { coberturaArquivos } = window.CortexOFX;
  const cob = coberturaArquivos(ARQ.ofx);
  const mov = ARQ.ofx.reduce((a, f) => a + f.transacoes.length, 0);
  const saldos = ARQ.ofx.map(f => f.saldo).filter(Boolean);
  const saldoTotal = saldos.reduce((a, s) => a + s.valor, 0);
  const ini = ARQ.ofx.reduce((a, f) => (!a || f.periodo.inicio < a ? f.periodo.inicio : a), null);
  const fim = ARQ.ofx.reduce((a, f) => (!a || f.periodo.fim > a ? f.periodo.fim : a), null);
  const { br } = window.CortexOFX;

  return `
  <div class="grid g-4">
    <div class="panel metric"><span class="eyebrow">Arquivos lidos</span>
      <div class="v">${ARQ.ofx.length}${ARQ.atua ? ' + 1' : ''}</div>
      <div class="d">${ARQ.ofx.length} extrato${ARQ.ofx.length > 1 ? 's' : ''} OFX${ARQ.atua ? ' · 1 razão do ATUA' : ' · ATUA não carregado'}</div></div>
    <div class="panel metric"><span class="eyebrow">Movimentos no extrato</span>
      <div class="v">${mov.toLocaleString('pt-BR')}</div>
      <div class="d">${br(ini)} a ${br(fim)}</div></div>
    <div class="panel metric"><span class="eyebrow">Saldo declarado no arquivo</span>
      <div class="v ${saldos.length ? '' : 'crit'}" style="font-size:20px">${saldos.length ? brl(saldoTotal, 2) : 'ausente'}</div>
      <div class="d">${saldos.length ? `${saldos.length} de ${ARQ.ofx.length} arquivo(s) trazem LEDGERBAL` : 'sem saldo de fechamento — não amarra o caixa'}</div></div>
    <div class="panel metric"><span class="eyebrow">Alertas de integridade</span>
      <div class="v ${cob.alertas.some(a => a.nivel === 'alto') ? 'crit' : cob.alertas.length ? 'amber' : 'ok'}">${cob.alertas.length}</div>
      <div class="d">${cob.alertas.length ? 'risco de importação duplicada ou incompleta' : 'nenhum problema estrutural detectado'}</div></div>
  </div>

  <div class="grid g-main" style="margin-top:14px;align-items:start">
    <section class="panel">
      <header><h3>Contas identificadas nos arquivos</h3><span class="eyebrow">lido do próprio OFX</span></header>
      <table>
        <thead><tr><th>Banco</th><th>Agência / conta</th><th>Arquivo</th><th class="r">Mov.</th><th class="r">Líquido</th><th class="r">Saldo</th><th>Período</th></tr></thead>
        <tbody>${ARQ.ofx.map(f => `
          <tr>
            <td style="white-space:nowrap">${esc(f.conta.banco)}${f.cartao ? ' <span class="chip">cartão</span>' : ''}</td>
            <td class="mono" style="color:var(--ink-3)">${esc(f.conta.agencia)} / ${esc(f.conta.numero)}</td>
            <td class="mono" style="color:var(--ink-3);max-width:170px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(f.arquivo)}">${esc(f.arquivo)}</td>
            <td class="r num">${f.transacoes.length}</td>
            <td class="r num" style="color:${f.resumo.liquido >= 0 ? 'var(--ok)' : 'var(--crit)'}">${brl(f.resumo.liquido, 2)}</td>
            <td class="r num">${f.saldo ? brl(f.saldo.valor, 2) : '—'}</td>
            <td class="num" style="color:var(--ink-3)">${br(f.periodo.inicio)}–${br(f.periodo.fim)}</td>
          </tr>`).join('')}
          ${ARQ.atua ? `<tr>
            <td colspan="3" style="color:var(--amber);max-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(ARQ.atua.arquivo)}">Razão do ATUA · ${esc(ARQ.atua.arquivo)}</td>
            <td class="r num">${ARQ.atua.lancamentos.length}</td>
            <td class="r num" style="color:${ARQ.atua.resumo.liquido >= 0 ? 'var(--ok)' : 'var(--crit)'}">${brl(ARQ.atua.resumo.liquido, 2)}</td>
            <td class="r">—</td>
            <td class="num" style="color:var(--ink-3)">${br(ARQ.atua.resumo.inicio)}–${br(ARQ.atua.resumo.fim)}</td>
          </tr>` : ''}
        </tbody>
      </table>
    </section>
    <section class="panel">
      <header><h3>Integridade dos arquivos</h3><span class="eyebrow">${cob.alertas.length} apontamento(s)</span></header>
      <div class="body" style="display:grid;gap:9px">
        ${cob.alertas.length ? cob.alertas.map(a => `
          <div class="ev"><div class="t"><span class="dot ${NIVEL_CLS[a.nivel]}"></span><b>${esc(a.tipo)}</b><span class="ref">${a.nivel}</span></div>
          <div class="n">${esc(a.texto)}</div></div>`).join('')
        : '<p style="margin:0;font-size:12.2px;color:var(--ink-3);line-height:1.6">Nenhum identificador repetido, nenhum período sobreposto e todos os arquivos trazem saldo de fechamento. O extrato pode ser importado no ATUA sem risco de duplicidade.</p>'}
      </div>
    </section>
  </div>`;
}

function blocoConciliacao() {
  const r = ARQ.rec;
  const { br } = window.CortexOFX;
  if (!r) {
    return `
    <h3 class="sec">Conciliação contra o ATUA</h3>
    <section class="panel"><div class="body" style="display:grid;gap:8px">
      <p style="margin:0;font-size:12.6px;color:var(--ink-2)">Carregue também o razão do ATUA em CSV para o CORTEX cruzar as duas pontas.</p>
      <p style="margin:0;font-size:12.2px;color:var(--ink-3);line-height:1.65">Sem a segunda ponta o sistema só consegue auditar o arquivo do banco. O confronto que gera dinheiro é o cruzamento entre fontes independentes.</p>
    </div></section>`;
  }

  const t = r.totais;
  const criticas = r.divergencias.filter(d => d.severidade === 'alta').length;

  return `
  <h3 class="sec">Conciliação contra o ATUA</h3>
  <div class="grid g-4">
    <div class="panel metric"><span class="eyebrow">Casamento automático</span>
      <div class="v ${t.taxa >= 0.9 ? 'ok' : t.taxa >= 0.75 ? 'amber' : 'crit'}">${pct(t.taxa)}</div>
      <div class="d">${t.casados} de ${t.banco} movimentos do extrato</div></div>
    <div class="panel metric"><span class="eyebrow">Sem par no ATUA</span>
      <div class="v ${t.semParBanco ? 'crit' : 'ok'}">${t.semParBanco}</div>
      <div class="d">dinheiro que entrou ou saiu sem registro</div></div>
    <div class="panel metric"><span class="eyebrow">Sem par no banco</span>
      <div class="v ${t.semParAtua ? 'crit' : 'ok'}">${t.semParAtua}</div>
      <div class="d">baixa ou pagamento sem lastro no extrato</div></div>
    <div class="panel metric"><span class="eyebrow">Valor em divergência</span>
      <div class="v crit" style="font-size:20px">${brl(t.valorSemPar, 2)}</div>
      <div class="d">${criticas} acima de R$ 20 mil</div></div>
  </div>

  <div class="grid g-main" style="margin-top:14px;align-items:start">
    <section class="panel">
      <header><h3>Divergências encontradas</h3><span class="eyebrow">clique para abrir a hipótese</span></header>
      ${r.divergencias.length ? `<table>
        <thead><tr><th>Origem</th><th>Tipo</th><th>Data</th><th>Histórico</th><th class="r">Valor</th></tr></thead>
        <tbody>${r.divergencias.slice(0, 40).map((d, i) => `
          <tr class="click" data-arqdiv="${i}" tabindex="0">
            <td><span class="chip ${d.lado === 'banco' ? 'amber' : ''}">${d.lado === 'banco' ? 'extrato' : 'ATUA'}</span></td>
            <td><span class="dot ${SEV_CLS[d.severidade]}"></span>${esc(d.tipo)}</td>
            <td class="num" style="color:var(--ink-3)">${br(d.data)}</td>
            <td style="color:var(--ink-2);max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(d.historico)}</td>
            <td class="r num" style="color:${d.valor < 0 ? 'var(--crit)' : 'var(--ink)'}">${brl(d.valor, 2)}</td>
          </tr>`).join('')}</tbody>
      </table>${r.divergencias.length > 40 ? `<div class="body" style="border-top:1px solid var(--line)"><span class="hint">mostrando as 40 maiores de ${r.divergencias.length}</span></div>` : ''}`
      : '<div class="body"><p style="margin:0;color:var(--ok);font-size:12.6px">Todos os movimentos do extrato encontraram par no ATUA. Nada a tratar.</p></div>'}
    </section>

    <div class="grid" style="gap:14px">
      <section class="panel">
        <header><h3>Regras que casaram</h3><span class="eyebrow">cascata</span></header>
        <div class="body" style="display:grid;gap:12px">
          ${r.porRegra.map(g => `
            <div>
              <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:6px">
                <span class="mono" style="font-size:10.5px;color:var(--amber)">${g.id}</span>
                <b style="font-size:12.2px;font-weight:500">${g.nome}</b>
                <span class="num" style="margin-left:auto;font-size:12px">${g.n}</span>
              </div>
              <div class="bar"><i class="${g.n ? 'ok' : ''}" style="width:${(g.pct * 100).toFixed(1)}%"></i></div>
              <span class="hint" style="margin-top:5px;display:block">${g.desc}</span>
            </div>`).join('')}
        </div>
      </section>
      <section class="panel">
        <header><h3>Amarração dos totais</h3></header>
        <table>
          <tbody>
            <tr><td>Líquido do extrato</td><td class="r num">${brl(t.somaBanco, 2)}</td></tr>
            <tr><td>Líquido do ATUA</td><td class="r num">${brl(t.somaAtua, 2)}</td></tr>
            <tr><td style="color:var(--amber)">Diferença</td><td class="r num" style="color:${Math.abs(t.somaBanco - t.somaAtua) < 0.01 ? 'var(--ok)' : 'var(--crit)'}">${brl(t.somaBanco - t.somaAtua, 2)}</td></tr>
          </tbody>
        </table>
        <div class="body" style="border-top:1px solid var(--line)">
          <span class="hint">A diferença precisa ser explicada linha a linha. Enquanto houver saldo aqui, o caixa do dia não está fechado.</span>
        </div>
      </section>
    </div>
  </div>`;
}

export function viewArquivos() {
  if (!ARQ.ofx.length) return vazio();
  return `${zonaUpload()}<div style="margin-top:14px">${cabecalhoArquivos()}</div>${blocoConciliacao()}`;
}

export function drawerArqDivergencia(i, openDrawer) {
  const d = ARQ.rec.divergencias[+i];
  const { br } = window.CortexOFX;
  const acao = d.lado === 'banco'
    ? (d.valor > 0 ? 'Emitir fatura ou localizar o título correspondente' : 'Classificar a saída e lançar no ATUA com centro de custo')
    : 'Exigir motivo e alçada para a baixa sem lastro';

  openDrawer(`
    <header>
      <div style="flex:1">
        <span class="mono" style="font-size:10.5px;color:var(--ink-3)">Divergência da conciliação · ${d.lado === 'banco' ? 'extrato bancário' : 'razão do ATUA'}</span>
        <h3>${esc(d.tipo)} — ${brl(d.valor, 2)}</h3>
      </div>
      <button class="close" data-close aria-label="Fechar">✕</button>
    </header>
    <div class="content">
      <div class="dsec"><span class="eyebrow">Movimento original</span>
        <div class="ev">
          <div class="t"><span class="dot ${SEV_CLS[d.severidade]}"></span><b>${d.lado === 'banco' ? 'Extrato bancário' : 'Razão do ATUA'}</b><span class="ref">${br(d.data)}</span></div>
          <div class="n">${esc(d.historico)}</div>
          ${d.fitid !== '—' ? `<div class="n mono" style="font-size:10.5px">FITID ${esc(d.fitid)}</div>` : ''}
        </div>
      </div>
      <div class="dsec"><span class="eyebrow">Severidade</span>
        <p style="color:var(--${SEV_CLS[d.severidade] === 'steel' ? 'steel' : SEV_CLS[d.severidade]})">${d.severidade === 'alta' ? 'Alta — acima de R$ 20 mil, exige tratativa no mesmo dia' : d.severidade === 'media' ? 'Média — entre R$ 3 mil e R$ 20 mil' : 'Baixa — abaixo de R$ 3 mil, tratativa em lote'}</p></div>
      <div class="dsec"><span class="eyebrow">Hipótese do agente</span><p>${esc(d.hipotese)}</p></div>
      <div class="dsec"><span class="eyebrow">Por que passou pelas 4 regras</span>
        <p>Não houve documento coincidente, valor equivalente dentro de D+2, combinação de lançamentos que somasse o valor, nem histórico com similaridade suficiente. É divergência real, não falha de casamento.</p></div>
      <div class="dsec"><span class="eyebrow">Ação sugerida</span><p>${acao}</p></div>
    </div>
    <footer>
      <button class="btn primary" data-act="Caso aberto com dono e prazo">Abrir caso</button>
      <button class="btn" data-act="Divergência marcada como justificada">Justificar</button>
    </footer>`);
}
