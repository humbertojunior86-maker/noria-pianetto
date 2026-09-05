/* ============================================================
   CORTEX · Parser de OFX e motor de conciliação
   Roda inteiramente no navegador. Nenhum arquivo sai da máquina.
   Suporta OFX 1.x (SGML) e OFX 2.x (XML), extratos bancários
   (STMTTRNRS) e de cartão (CCSTMTTRNRS).
   ============================================================ */

/* ---------- utilitários ---------- */

function ofxDate(v) {
  // 20260904, 20260904120000, 20260904120000[-3:BRT]
  if (!v) return null;
  const s = String(v).trim().replace(/\[.*$/, '');
  const y = +s.slice(0, 4), m = +s.slice(4, 6), d = +s.slice(6, 8);
  if (!y || !m || !d) return null;
  return new Date(Date.UTC(y, m - 1, d));
}

function iso(d) { return d ? d.toISOString().slice(0, 10) : '—'; }
function br(d) { return d ? iso(d).split('-').reverse().slice(0, 2).join('/') : '—'; }

function ofxAmount(v) {
  if (v == null) return 0;
  let s = String(v).trim();
  // OFX usa ponto decimal, mas há bancos que exportam vírgula
  if (s.includes(',') && !s.includes('.')) s = s.replace(',', '.');
  else if (s.includes(',') && s.includes('.')) s = s.replace(/\./g, '').replace(',', '.');
  const n = parseFloat(s);
  return isNaN(n) ? 0 : n;
}

function limpaTexto(s) {
  return (s || '')
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&#(\d+);/g, (_, c) => String.fromCharCode(+c))
    .replace(/\s+/g, ' ').trim();
}

/* Normaliza o histórico para comparação semântica:
   maiúsculas sem acento, sem pontuação, sem ruído bancário. */
const RUIDO = /\b(TED|DOC|PIX|TEV|TRANSF|TRANSFERENCIA|CREDITO|CREDITO EM CONTA|DEBITO|LIQUIDACAO|COBRANCA|RECEBIMENTO|PAGAMENTO|PAGTO|REF|CTA|AG|C\/C|CNPJ|CPF|LTDA|SA|S\/A|ME|EIRELI|EPP)\b/g;

function chaveTexto(s) {
  return limpaTexto(s).toUpperCase()
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^A-Z0-9 ]/g, ' ')
    .replace(RUIDO, ' ')
    .replace(/\s+/g, ' ').trim();
}

function tokens(s) {
  return chaveTexto(s).split(' ').filter(t => t.length >= 4);
}

/* Similaridade de Jaccard entre conjuntos de tokens */
function similaridade(a, b) {
  const A = new Set(tokens(a)), B = new Set(tokens(b));
  if (!A.size || !B.size) return 0;
  let inter = 0;
  A.forEach(t => { if (B.has(t)) inter++; });
  return inter / (A.size + B.size - inter);
}

/* Extrai possíveis identificadores do histórico: nosso número,
   número do título, documento, EndToEndId do PIX. */
function identificadores(s) {
  const t = limpaTexto(s).toUpperCase();
  const ids = new Set();
  (t.match(/\b\d{5,20}\b/g) || []).forEach(n => ids.add(n));
  (t.match(/\bE\d{8,}\b/g) || []).forEach(n => ids.add(n));
  return [...ids];
}

const diasEntre = (a, b) => Math.round(Math.abs(a - b) / 86400000);

/* Nomes dos bancos pelo código COMPE que vem no BANKID. */
const BANCOS = {
  '001': 'Banco do Brasil', '033': 'Santander', '041': 'Banrisul', '070': 'BRB',
  '077': 'Inter', '104': 'Caixa Econômica', '133': 'Cresol', '136': 'Unicred',
  '208': 'BTG Pactual', '212': 'Banco Original', '237': 'Bradesco', '260': 'Nubank',
  '318': 'Banco BMG', '336': 'C6 Bank', '341': 'Itaú Unibanco', '389': 'Mercantil',
  '422': 'Safra', '655': 'Votorantim', '707': 'Daycoval', '748': 'Sicredi',
  '756': 'Sicoob', '336x': 'C6', '000': 'Conta digital',
};

function nomeBanco(codigo, org) {
  const c = String(codigo || '').replace(/\D/g, '').padStart(3, '0');
  if (BANCOS[c]) return BANCOS[c];
  if (org && org.length > 2) return limpaTexto(org);
  return codigo ? `Banco ${codigo}` : null;
}

/* ---------- leitura do OFX ---------- */

/* OFX 1.x é SGML: tags sem fechamento. Convertemos para uma
   estrutura navegável sem depender de DOMParser. */
function tokenizaSGML(corpo) {
  const nos = [];
  const re = /<(\/?[^>\s]+)>([^<]*)/g;
  let m;
  while ((m = re.exec(corpo)) !== null) {
    const tag = m[1].toUpperCase();
    const valor = limpaTexto(m[2]);
    nos.push({ tag, valor });
  }
  // tags de fechamento explícitas (arquivos híbridos)
  return nos;
}

/* Percorre a lista de tags e agrupa transações. */
function extraiTransacoes(nos) {
  const txs = [];
  let atual = null;
  for (const { tag, valor } of nos) {
    if (tag === 'STMTTRN') { atual = {}; continue; }
    if (tag === '/STMTTRN') { if (atual) { txs.push(atual); atual = null; } continue; }
    if (!atual) continue;
    switch (tag) {
      case 'TRNTYPE': atual.tipo = valor.toUpperCase(); break;
      case 'DTPOSTED': atual.data = ofxDate(valor); break;
      case 'DTAVAIL': atual.dataDisp = ofxDate(valor); break;
      case 'TRNAMT': atual.valor = ofxAmount(valor); break;
      case 'FITID': atual.fitid = valor; break;
      case 'CHECKNUM': atual.documento = valor; break;
      case 'REFNUM': atual.referencia = valor; break;
      case 'MEMO': atual.memo = limpaTexto((atual.memo ? atual.memo + ' ' : '') + valor); break;
      case 'NAME': atual.nome = limpaTexto(valor); break;
      case 'PAYEEID': atual.pagadorId = valor; break;
    }
  }
  // fallback: arquivos sem </STMTTRN>
  if (atual && Object.keys(atual).length) txs.push(atual);
  return txs.map((t, i) => ({
    ...t,
    historico: limpaTexto([t.nome, t.memo].filter(Boolean).join(' · ')) || '(sem histórico)',
    valor: t.valor || 0,
    idx: i,
  })).filter(t => t.data && t.valor !== 0);
}

function valorTag(nos, tag) {
  const n = nos.find(x => x.tag === tag && x.valor);
  return n ? n.valor : null;
}

/**
 * Lê o conteúdo de um arquivo OFX e devolve um objeto estruturado.
 * Lança erro descritivo quando o arquivo não é reconhecido.
 */
function parseOFX(texto, nomeArquivo) {
  if (!texto || texto.length < 30) throw new Error('Arquivo vazio ou ilegível.');

  const bruto = texto.replace(/\r/g, '');
  const marca = bruto.toUpperCase();
  if (!marca.includes('<OFX>') && !marca.includes('OFXHEADER')) {
    throw new Error('Não parece um arquivo OFX. Verifique se o download foi de extrato em formato OFX / Money.');
  }

  // Cabeçalho (OFX 1.x traz chave:valor antes do <OFX>)
  const cab = {};
  const idxOfx = marca.indexOf('<OFX>');
  const cabTexto = idxOfx > 0 ? bruto.slice(0, idxOfx) : '';
  cabTexto.split('\n').forEach(l => {
    const p = l.split(':');
    if (p.length === 2 && p[0].trim()) cab[p[0].trim().toUpperCase()] = p[1].trim();
  });

  const corpo = idxOfx >= 0 ? bruto.slice(idxOfx) : bruto;
  const nos = tokenizaSGML(corpo);
  const nomesTags = new Set(nos.map(n => n.tag));

  const cartao = nomesTags.has('CCSTMTTRNRS') || nomesTags.has('CCACCTFROM');

  const codigo = valorTag(nos, 'BANKID');
  const conta = {
    codigo: codigo || '',
    banco: nomeBanco(codigo, valorTag(nos, 'ORG')) || (cartao ? 'Cartão de crédito' : '—'),
    agencia: valorTag(nos, 'BRANCHID') || '—',
    numero: valorTag(nos, 'ACCTID') || '—',
    tipo: valorTag(nos, 'ACCTTYPE') || (cartao ? 'CREDITCARD' : 'CHECKING'),
    moeda: valorTag(nos, 'CURDEF') || 'BRL',
  };

  const transacoes = extraiTransacoes(nos);
  if (!transacoes.length) throw new Error('OFX lido, mas sem nenhuma transação (STMTTRN) reconhecida.');

  const inicio = ofxDate(valorTag(nos, 'DTSTART')) || transacoes.reduce((a, t) => (!a || t.data < a ? t.data : a), null);
  const fim = ofxDate(valorTag(nos, 'DTEND')) || transacoes.reduce((a, t) => (!a || t.data > a ? t.data : a), null);

  const saldoValor = valorTag(nos, 'BALAMT');
  const saldoData = ofxDate(valorTag(nos, 'DTASOF'));

  const creditos = transacoes.filter(t => t.valor > 0);
  const debitos = transacoes.filter(t => t.valor < 0);

  // duplicidade de FITID dentro do próprio arquivo
  const porFitid = new Map();
  transacoes.forEach(t => {
    const k = t.fitid || `sem-fitid-${t.idx}`;
    porFitid.set(k, (porFitid.get(k) || 0) + 1);
  });
  const fitidRepetidos = [...porFitid.entries()].filter(([k, n]) => n > 1 && !k.startsWith('sem-fitid'));
  const semFitid = transacoes.filter(t => !t.fitid).length;

  // dias úteis sem movimento dentro da janela declarada
  const diasComMov = new Set(transacoes.map(t => iso(t.data)));
  const buracos = [];
  if (inicio && fim) {
    for (let d = new Date(inicio); d <= fim; d.setUTCDate(d.getUTCDate() + 1)) {
      const dow = d.getUTCDay();
      if (dow === 0 || dow === 6) continue;
      if (!diasComMov.has(iso(d))) buracos.push(iso(d));
    }
  }

  return {
    arquivo: nomeArquivo || 'ofx',
    versao: cab.VERSION ? `OFX ${cab.VERSION}` : (bruto.trim().startsWith('<?xml') ? 'OFX 2.x' : 'OFX 1.x'),
    cartao,
    conta,
    periodo: { inicio, fim },
    saldo: saldoValor != null ? { valor: ofxAmount(saldoValor), data: saldoData } : null,
    transacoes,
    resumo: {
      total: transacoes.length,
      creditos: creditos.length,
      debitos: debitos.length,
      somaCreditos: creditos.reduce((a, t) => a + t.valor, 0),
      somaDebitos: debitos.reduce((a, t) => a + t.valor, 0),
      liquido: transacoes.reduce((a, t) => a + t.valor, 0),
    },
    integridade: { fitidRepetidos, semFitid, buracos },
  };
}

/* ---------- leitura do extrato do ATUA (CSV / TXT) ---------- */

function detectaSeparador(linha) {
  const cand = [';', '\t', ',', '|'];
  let melhor = ';', max = 0;
  cand.forEach(c => {
    const n = linha.split(c).length;
    if (n > max) { max = n; melhor = c; }
  });
  return melhor;
}

function quebraLinha(linha, sep) {
  const out = []; let cur = ''; let aspas = false;
  for (let i = 0; i < linha.length; i++) {
    const ch = linha[i];
    if (ch === '"') { aspas = !aspas; continue; }
    if (ch === sep && !aspas) { out.push(cur); cur = ''; continue; }
    cur += ch;
  }
  out.push(cur);
  return out.map(s => s.trim());
}

function dataBR(s) {
  if (!s) return null;
  const t = String(s).trim();
  let m = t.match(/^(\d{2})[\/\-.](\d{2})[\/\-.](\d{2,4})/);
  if (m) {
    const ano = m[3].length === 2 ? 2000 + +m[3] : +m[3];
    return new Date(Date.UTC(ano, +m[2] - 1, +m[1]));
  }
  m = t.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return null;
}

function valorBR(s) {
  if (s == null) return NaN;
  let t = String(s).trim().replace(/R\$\s*/i, '').replace(/\s/g, '');
  const negativo = /^\(.*\)$/.test(t) || /-$/.test(t) || /^-/.test(t) || /\bD$/i.test(t);
  t = t.replace(/[()]/g, '').replace(/[CD]$/i, '').replace(/-/g, '');
  if (t.includes(',')) t = t.replace(/\./g, '').replace(',', '.');
  const n = parseFloat(t);
  if (isNaN(n)) return NaN;
  return negativo ? -n : n;
}

const ACHA = {
  data: /^(data|dt|data.?(lanc|mov|pag|receb|credito|baixa|compensacao))/i,
  valor: /^(valor|vlr|montante|total|valor.?(pago|recebido|liquido|baixa))/i,
  historico: /^(hist|descric|complemento|observ|memo|favorecido|sacado|cliente|fornecedor|nome)/i,
  documento: /^(doc|documento|titulo|numero|n.?titulo|nosso.?numero|ctrc|nf|cte)/i,
  tipo: /^(tipo|natureza|opera[cç][aã]o|d\s?[\/x-]\s?c|deb\s?[\/x-]?\s?cred|debito.?credito)$/i,
};

/**
 * Lê um extrato/relatório do ATUA em CSV ou texto delimitado.
 * Detecta cabeçalho e colunas automaticamente.
 */
function parseATUA(texto, nomeArquivo) {
  const linhas = texto.replace(/\r/g, '').split('\n').filter(l => l.trim());
  if (linhas.length < 2) throw new Error('Arquivo do ATUA sem linhas suficientes.');

  const sep = detectaSeparador(linhas[0]);

  // acha a linha de cabeçalho (primeira que tem pelo menos data e valor)
  let iCab = -1, cols = null;
  for (let i = 0; i < Math.min(linhas.length, 15); i++) {
    const c = quebraLinha(linhas[i], sep).map(x => x.toLowerCase()
      .normalize('NFD').replace(/[\u0300-\u036f]/g, ''));
    const temData = c.some(x => ACHA.data.test(x));
    const temValor = c.some(x => ACHA.valor.test(x));
    if (temData && temValor) { iCab = i; cols = c; break; }
  }
  if (iCab < 0) throw new Error('Não localizei as colunas de data e valor. Exporte o relatório com cabeçalho.');

  const idx = {};
  ['data', 'valor', 'historico', 'documento', 'tipo'].forEach(campo => {
    idx[campo] = cols.findIndex(c => ACHA[campo].test(c));
  });

  const linhs = [];
  for (let i = iCab + 1; i < linhas.length; i++) {
    const c = quebraLinha(linhas[i], sep);
    if (c.length < 2) continue;
    const data = dataBR(c[idx.data]);
    let valor = valorBR(c[idx.valor]);
    if (!data || isNaN(valor)) continue;
    const tipo = idx.tipo >= 0 ? (c[idx.tipo] || '') : '';
    if (/^(d|deb|debito|pagamento|saida)/i.test(tipo.trim()) && valor > 0) valor = -valor;
    linhs.push({
      data,
      valor,
      historico: limpaTexto(idx.historico >= 0 ? c[idx.historico] : '') || '(sem histórico)',
      documento: limpaTexto(idx.documento >= 0 ? c[idx.documento] : ''),
      idx: linhs.length,
    });
  }
  if (!linhs.length) throw new Error('Nenhuma linha válida encontrada no arquivo do ATUA.');

  return {
    arquivo: nomeArquivo || 'atua.csv',
    colunas: Object.fromEntries(Object.entries(idx).map(([k, v]) => [k, v >= 0 ? cols[v] : null])),
    lancamentos: linhs,
    resumo: {
      total: linhs.length,
      liquido: linhs.reduce((a, l) => a + l.valor, 0),
      inicio: linhs.reduce((a, l) => (!a || l.data < a ? l.data : a), null),
      fim: linhs.reduce((a, l) => (!a || l.data > a ? l.data : a), null),
    },
  };
}

/* ---------- motor de conciliação ---------- */

const REGRAS = [
  { id: 'R1', nome: 'Par exato', desc: 'valor + data + documento' },
  { id: 'R2', nome: 'Par por tolerância', desc: '±R$ 0,05 e janela de D+2' },
  { id: 'R3', nome: 'Agrupamento', desc: 'n lançamentos = 1 crédito' },
  { id: 'R4', nome: 'Semântico', desc: 'similaridade de histórico ≥ 0,45' },
];

/**
 * Concilia transações do extrato (OFX) contra lançamentos do ATUA.
 * Aplica as regras em cascata; cada lado só casa uma vez.
 */
function conciliar(banco, atua, opts = {}) {
  const tolValor = opts.tolValor ?? 0.05;
  const tolDias = opts.tolDias ?? 2;
  const minSim = opts.minSim ?? 0.45;

  const B = banco.map(t => ({ ...t, casado: null }));
  const A = atua.map(l => ({ ...l, casado: null }));
  const pares = [];

  const casa = (b, a, regra, nota) => {
    b.casado = regra; a.casado = regra;
    pares.push({ regra, banco: b, atua: a, nota: nota || '' });
  };

  /* R1 — valor idêntico, mesma data e documento coincidente */
  B.forEach(b => {
    if (b.casado) return;
    const idsB = identificadores(`${b.historico} ${b.documento || ''} ${b.fitid || ''}`);
    const alvo = A.find(a => !a.casado
      && Math.abs(a.valor - b.valor) < 0.005
      && diasEntre(a.data, b.data) === 0
      && a.documento && idsB.includes(a.documento.replace(/\D/g, '')));
    if (alvo) casa(b, alvo, 'R1', `documento ${alvo.documento}`);
  });

  /* R1b — valor e data idênticos, documento ausente nos dois lados */
  B.forEach(b => {
    if (b.casado) return;
    const cands = A.filter(a => !a.casado
      && Math.abs(a.valor - b.valor) < 0.005
      && diasEntre(a.data, b.data) === 0);
    if (cands.length === 1) casa(b, cands[0], 'R1', 'valor e data exatos');
  });

  /* R2 — tolerância de centavos e janela de dias */
  B.forEach(b => {
    if (b.casado) return;
    const cands = A.filter(a => !a.casado
      && Math.abs(a.valor - b.valor) <= tolValor
      && diasEntre(a.data, b.data) <= tolDias);
    if (!cands.length) return;
    cands.sort((x, y) => (Math.abs(x.valor - b.valor) - Math.abs(y.valor - b.valor))
      || (diasEntre(x.data, b.data) - diasEntre(y.data, b.data)));
    const a = cands[0];
    const dd = diasEntre(a.data, b.data);
    const dv = Math.abs(a.valor - b.valor);
    casa(b, a, 'R2', `${dd ? `D+${dd}` : 'mesmo dia'}${dv > 0.004 ? ` · dif. de R$ ${dv.toFixed(2)}` : ''}`);
  });

  /* R3 — um crédito no banco = soma de n lançamentos no ATUA (até 4) */
  B.forEach(b => {
    if (b.casado) return;
    const pool = A.filter(a => !a.casado
      && Math.sign(a.valor) === Math.sign(b.valor)
      && diasEntre(a.data, b.data) <= tolDias
      && Math.abs(a.valor) <= Math.abs(b.valor) + tolValor);
    if (pool.length < 2) return;
    const alvo = Math.round(b.valor * 100);
    let combo = null;
    const busca = (i, restante, acc) => {
      if (combo || acc.length > 4) return;
      if (Math.abs(restante) <= Math.round(tolValor * 100) && acc.length >= 2) { combo = [...acc]; return; }
      for (let j = i; j < pool.length; j++) {
        const v = Math.round(pool[j].valor * 100);
        if (Math.abs(v) > Math.abs(restante) + Math.round(tolValor * 100)) continue;
        acc.push(pool[j]);
        busca(j + 1, restante - v, acc);
        acc.pop();
        if (combo) return;
      }
    };
    busca(0, alvo, []);
    if (combo) {
      b.casado = 'R3';
      combo.forEach(a => { a.casado = 'R3'; });
      pares.push({ regra: 'R3', banco: b, atua: combo[0], grupo: combo, nota: `${combo.length} lançamentos somam o crédito` });
    }
  });

  /* R4 — semântico: valor próximo e histórico parecido */
  B.forEach(b => {
    if (b.casado) return;
    let melhor = null, melhorSim = 0;
    A.forEach(a => {
      if (a.casado) return;
      if (Math.sign(a.valor) !== Math.sign(b.valor)) return;
      if (diasEntre(a.data, b.data) > tolDias + 3) return;
      const dif = Math.abs(a.valor - b.valor);
      const rel = dif / Math.max(Math.abs(b.valor), 1);
      if (rel > 0.05) return;
      const s = similaridade(b.historico, `${a.historico} ${a.documento || ''}`);
      if (s > melhorSim) { melhorSim = s; melhor = a; }
    });
    if (melhor && melhorSim >= minSim) {
      const dif = Math.abs(melhor.valor - b.valor);
      casa(b, melhor, 'R4', `similaridade ${(melhorSim * 100).toFixed(0)}%${dif > 0.004 ? ` · dif. de R$ ${dif.toFixed(2)}` : ''}`);
    }
  });

  /* ---------- divergências ---------- */
  const semParBanco = B.filter(b => !b.casado);
  const semParAtua = A.filter(a => !a.casado);

  const divergencias = [];

  semParBanco.forEach(b => {
    const proximo = semParAtua.find(a => Math.abs(a.valor - b.valor) <= Math.abs(b.valor) * 0.02
      && diasEntre(a.data, b.data) <= 5);
    divergencias.push({
      lado: 'banco',
      tipo: b.valor > 0 ? 'Crédito sem lançamento' : 'Débito sem lançamento',
      data: b.data,
      valor: b.valor,
      historico: b.historico,
      fitid: b.fitid || '—',
      hipotese: b.valor > 0
        ? (proximo ? 'Valor próximo existe no ATUA em outra data — possível divergência de competência' : 'Recebimento sem título correspondente — fatura não emitida ou baixa não realizada')
        : (proximo ? 'Pagamento lançado com valor divergente no ATUA' : 'Saída sem contrapartida — tarifa, débito automático ou pagamento fora do sistema'),
      severidade: Math.abs(b.valor) > 20000 ? 'alta' : Math.abs(b.valor) > 3000 ? 'media' : 'baixa',
    });
  });

  semParAtua.forEach(a => {
    divergencias.push({
      lado: 'atua',
      tipo: a.valor > 0 ? 'Baixa sem crédito' : 'Pagamento sem débito',
      data: a.data,
      valor: a.valor,
      historico: `${a.historico}${a.documento ? ` · doc ${a.documento}` : ''}`,
      fitid: '—',
      hipotese: a.valor > 0
        ? 'Título baixado no ATUA sem dinheiro correspondente no extrato — exige alçada e motivo'
        : 'Pagamento registrado no ATUA sem débito no banco — pode estar agendado ou não efetivado',
      severidade: Math.abs(a.valor) > 20000 ? 'alta' : Math.abs(a.valor) > 3000 ? 'media' : 'baixa',
    });
  });

  divergencias.sort((x, y) => Math.abs(y.valor) - Math.abs(x.valor));

  const porRegra = REGRAS.map(r => {
    const n = pares.filter(p => p.regra === r.id).length;
    return { ...r, n, pct: B.length ? n / B.length : 0 };
  });

  const casados = B.filter(b => b.casado).length;

  return {
    pares,
    porRegra,
    divergencias,
    totais: {
      banco: B.length,
      atua: A.length,
      casados,
      taxa: B.length ? casados / B.length : 0,
      semParBanco: semParBanco.length,
      semParAtua: semParAtua.length,
      valorSemPar: divergencias.reduce((a, d) => a + Math.abs(d.valor), 0),
      somaBanco: B.reduce((a, b) => a + b.valor, 0),
      somaAtua: A.reduce((a, b) => a + b.valor, 0),
    },
  };
}

/* ---------- verificação de cobertura de arquivos ---------- */

/**
 * Confere se todos os dias úteis do período têm arquivo carregado
 * e se algum arquivo foi carregado duas vezes.
 */
function coberturaArquivos(arquivos) {
  const porConta = new Map();
  arquivos.forEach(f => {
    const k = `${f.conta.banco}·${f.conta.numero}`;
    if (!porConta.has(k)) porConta.set(k, []);
    porConta.get(k).push(f);
  });

  const alertas = [];
  const contas = [];

  porConta.forEach((fs, k) => {
    const [banco, numero] = k.split('·');
    const inicio = fs.reduce((a, f) => (!a || f.periodo.inicio < a ? f.periodo.inicio : a), null);
    const fim = fs.reduce((a, f) => (!a || f.periodo.fim > a ? f.periodo.fim : a), null);

    // sobreposição de período entre arquivos da mesma conta
    for (let i = 0; i < fs.length; i++) {
      for (let j = i + 1; j < fs.length; j++) {
        const a = fs[i], b = fs[j];
        if (a.periodo.inicio <= b.periodo.fim && b.periodo.inicio <= a.periodo.fim) {
          alertas.push({ tipo: 'Sobreposição de período', nivel: 'alto', texto: `${a.arquivo} e ${b.arquivo} cobrem o mesmo intervalo em ${banco} ${numero} — risco de importar em duplicidade` });
        }
      }
    }

    const todosFitid = new Set(); let repetidos = 0;
    fs.forEach(f => f.transacoes.forEach(t => {
      if (!t.fitid) return;
      const k2 = `${t.fitid}`;
      if (todosFitid.has(k2)) repetidos++; else todosFitid.add(k2);
    }));
    if (repetidos) alertas.push({ tipo: 'FITID repetido', nivel: 'alto', texto: `${repetidos} transações com identificador repetido em ${banco} ${numero} — o ATUA pode ter importado duas vezes` });

    fs.forEach(f => {
      if (f.integridade.semFitid) alertas.push({ tipo: 'Transação sem FITID', nivel: 'medio', texto: `${f.integridade.semFitid} movimentos sem identificador em ${f.arquivo} — impossível detectar reimportação` });
      if (f.integridade.buracos.length > 2) alertas.push({ tipo: 'Dias úteis sem movimento', nivel: 'baixo', texto: `${f.integridade.buracos.length} dias úteis sem nenhum lançamento em ${f.arquivo}` });
      if (!f.saldo) alertas.push({ tipo: 'Arquivo sem saldo', nivel: 'medio', texto: `${f.arquivo} não traz o saldo de fechamento — não dá para amarrar o caixa pelo arquivo` });
    });

    contas.push({
      banco, numero,
      arquivos: fs.length,
      movimentos: fs.reduce((a, f) => a + f.transacoes.length, 0),
      inicio, fim,
      saldo: fs.map(f => f.saldo).filter(Boolean).sort((a, b) => b.data - a.data)[0] || null,
      liquido: fs.reduce((a, f) => a + f.resumo.liquido, 0),
    });
  });

  return { contas, alertas };
}

window.CortexOFX = { parseOFX, parseATUA, conciliar, coberturaArquivos, REGRAS, iso, br, similaridade };
