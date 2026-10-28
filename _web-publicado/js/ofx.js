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
  return txs.map((t, i) => {
    const historico = limpaTexto([t.nome, t.memo].filter(Boolean).join(' · ')) || '(sem histórico)';
    return {
      ...t,
      historico,
      valor: t.valor || 0,
      idx: i,
      sem: normalizaMemo(historico, [t.documento, t.referencia, t.pagadorId].filter(Boolean).join(' ')),
    };
  }).filter(t => t.data && t.valor !== 0);
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

/* ---------- normalizacao semantica do historico bancario ---------- */

/*
 * Regras calibradas contra 17.787 movimentos reais do ATUA, cobrindo
 * Banco do Brasil, Itau, BTG, Bradesco, Safra e GoFlux/FitBank.
 * A ordem importa: a primeira regra que casa vira a natureza principal,
 * as demais ficam em `tags`.
 */
const NATUREZAS = [
  { id: 'estorno',  rot: 'Estorno ou devolucao', re: /\b(ESTORNO|ESTORNAD\w*|DEVOLUC\w*|DEVOLVID\w*|CANCELAMENTO|REEMBOLSO)\b/i },
  // Atencao ao Bradesco: "REM:" e o remetente (dinheiro entrando) e "DES:"
  // e o destinatario (dinheiro saindo). Inverter isso custa 142 classificacoes.
  { id: 'pix_rec',  rot: 'PIX recebido',        re: /\bPIX\b[\s\S]*\bREM:/i, sinal: 1 },
  { id: 'pix_env',  rot: 'PIX enviado',         re: /\bPIX\b[\s\S]*\bDES:/i, sinal: -1 },
  { id: 'pix_env', rot: 'PIX enviado',         re: /\bPIX\b[\s\S]*\b(ENV\w*|DEB\w*|SAIDA|PAGAMENTO|PAGTO|PAGO|PARA)\b|\bTRANSFERENCIA\s+(VIA\s+)?PIX\b|\bPAGAMENTOS?\s+PIX\b/i, sinal: -1 },
  { id: 'pix_rec', rot: 'PIX recebido',        re: /\bPIX\b[\s\S]*\b(REC\w*|CRED\w*|ENTRADA)\b|\bRECEBIMENTO\s+(VIA\s+)?PIX\b|\bENTRADA\s+PIX\b/i, sinal: 1 },
  { id: 'pix_agend', rot: 'PIX agendado',       re: /\bPIX\b[\s\S]*\bAGENDAMENTO\b/i },
  { id: 'pix',      rot: 'PIX',                 re: /\bPIX\b/i },
  { id: 'cobranca', rot: 'Boleto e cobranca',   re: /\b(LIQ|LIQUID)\w*\.?\s*(DE\s+)?COBRAN|TIT\.?\s*COBRAN|BLOQUETO|BOLETO|DUPLICATA|COBRANCA/i },
  { id: 'recebim',  rot: 'Recebimento de cliente', re: /\bRECEBIMENTOS?\b|\bSISPAG\b|\bCREDITO\s+EM\s+CONTA\b/i, sinal: 1 },
  // sem sinal: o BB rotula credito recebido como "TED-PAG FORNECEDORES"
  { id: 'ted',      rot: 'TED, DOC ou TEF',     re: /\b(TED|DOC|TEV|TEF)\b|\bTRANSFERENCIA?\b|\bTRANSF\b/i },
  { id: 'rendim',   rot: 'Rendimento de aplicacao', re: /\bREND\w*\b|\bREMUNERA|\bRENTAB|\bJUROS\s+CREDIT/i, sinal: 1 },
  { id: 'aplic',    rot: 'Aplicacao ou resgate', re: /\b(APLIC\w*|RESGATE|CDB|LCI|LCA|POUPANC\w*|FUNDO|RENDA\s+FIXA|INVESTIMENTO|AUTOMATIC\w*\s+APLIC)\b/i },
  { id: 'imposto',  rot: 'Tributo ou guia',     re: /\b(DARF|DARE|DAS|DAM|GPS|FGTS|GNRE|ICMS|ISS|INSS|SIMPLES|GRU|IPVA|DAE|DPVAT|TRIBUTO|IMPOSTOS?|SEFAZ|PREVIDENC\w*)\b/i, sinal: -1 },
  { id: 'folha',    rot: 'Folha e pessoal',     re: /\b(SALARIO|FOLHA|RESCIS\w*|FERIAS|VALE|PRO.?LABORE|ADIANT\w*\s+SALAR|13\s*SALARIO)\b/i, sinal: -1 },
  { id: 'frota',    rot: 'Frota, pedagio e combustivel', re: /\b(SEM\s*PARAR|CONECTCAR|VELOE|MOVE\s*MAIS|IPIRANGA|SHELL|PETROBRAS|POSTO|COMBUSTIVEL|PEDAGIO|ARTERIS|ECORODOVIAS|REPOM|ROADCARD|VOLUS|TRUCKPAG|NSTECH|STRADA\s*PAY|E-?FRETE|TARGET\s*PAY)\b/i },
  { id: 'consorcio', rot: 'Consorcio',          re: /\bCONSORCIO\b/i, sinal: -1 },
  { id: 'emprest',  rot: 'Emprestimo ou financiamento', re: /\b(EMPREST\w*|FINANC\w*|CDC|LEASING|CONSIGN\w*|ANTECIP\w*|CAPITAL\s+DE?\s*GIRO|PEAC|FGI|FINAME|DESCONTO\s+DE\s+TITULO\w*|CREDITO\s+ROTATIVO|PRONAMPE|BB\s+GIRO|OPER\w*\s+CREDITO|PARCELA)\b/i },
  { id: 'cartao',   rot: 'Cartao de credito',   re: /\bCARTAO\b|\bCARTOES\b|\bFATURA\s+CARTAO\b/i, sinal: -1 },
  { id: 'seguro',   rot: 'Seguro',              re: /\bSEGURO\w*\b|\bAPOLICE\b|\bSINISTRO\b/i, sinal: -1 },
  { id: 'concess',  rot: 'Concessionaria e utilidades', re: /\b(TELEFONE|CELULAR|VIVO|CLARO|TIM|OI\s|INTERNET|ENERGIA|ENEL|EQUATORIAL|CELG|ELETRO|SANEAGO|CAESB|AGUA|ESGOTO|GAS)\b/i, sinal: -1 },
  { id: 'tarifa',   rot: 'Tarifa bancaria',     re: /\b(TAR|TARIFA|TAXA|CESTA|PACOTE|MANUTENC\w*|MENSALIDADE|IOF|ENCARGO|ANUIDADE|CUSTAS|DEB\.?\s*SERVICO|DEBITO\s+SERVICO)\b|\bJUROS\b/i, sinal: -1 },
  { id: 'cheque',   rot: 'Cheque',              re: /CHEQUE|\bCH\.?\s*COMPENS|\bCOMPE\b|\bDEV\s*CH\d|\bCH\d{4,}|\bCHQ\b|\bSEM\s+FUNDOS\b/i },
  { id: 'capitaliz', rot: 'Titulo de capitalizacao', re: /\bCAPITALIZACAO\b/i, sinal: -1 },
  { id: 'titulo',   rot: 'Titulo em carteira',  re: /\bTBI\b|\bPFOR\s+TIT\b|\bDESC\s+DP\b|\bJR\s+MORA\b/i },
  { id: 'debauto',  rot: 'Debito automatico',   re: /\b(DEB(ITO)?\.?\s*AUT|DEBITO\s+PROGRAMADO|CONVENIO)\b/i, sinal: -1 },
  { id: 'pagto',    rot: 'Pagamento a fornecedor', re: /\bPAG(AMENTOS?|TO|AMENTO)?\b.*\b(FORNEC\w*|ELETRON\w*|CONTA)\b|\bPAG\s+FORNEC/i },
];

// Alguns extratos do BB chegam com o historico corrompido por repeticao
// ("CHEQUEEQUEEQUE COMPENSADO"). Colapsa o pedaco repetido antes de classificar.
function reparaMemo(txt) {
  let s = txt;
  // so letras: colapsar digitos destruiria numero de conta e EndToEnd
  for (let i = 0; i < 3; i++) s = s.replace(/([A-Za-z]{3,8})\1+/g, '$1');
  return s;
}

// exige que o bloco de 14 digitos esteja isolado, senao um "nosso numero"
// de 17 digitos e confundido com CNPJ e a chave forte se perde
const RE_CNPJ = /(?<!\d)(\d{2})[.\s]?(\d{3})[.\s]?(\d{3})[\/\s]?(\d{4})[-\s]?(\d{2})(?!\d)/;
const RE_CPF = /(?<!\d)(\d{3})[.\s]?(\d{3})[.\s]?(\d{3})[-\s]?(\d{2})(?!\d)/;
const RE_E2E = /\bE\d{8}[0-9A-Z]{20,}\b/i;

const RUIDO_NOME = /^(PIX|TED|DOC|TEV|CRED|CREDITO|DEB|DEBITO|TRANSF|TRANSFERENCIA|LIQ|LIQUIDACAO|COBRANCA|RECEBIMENTO|PAGAMENTO|PAGTO|REF|CTA|AG|CC|BCO|BANCO|ENVIADO|RECEBIDO|MESMA|TITULARIDADE|OUTRA|INST|DE|DA|DO|EM|PARA|POR|VIA|NR|NUM)$/i;

function normalizaMemo(bruto, extra) {
  const txt = limpaTexto(`${bruto || ''} ${extra || ''}`);
  const up = reparaMemo(txt.toUpperCase());

  const tags = NATUREZAS.filter(n => n.re.test(up));
  const natureza = tags[0] || null;

  const mC = up.match(RE_CNPJ);
  const cnpj = mC ? `${mC[1]}.${mC[2]}.${mC[3]}/${mC[4]}-${mC[5]}` : null;
  const mP = !cnpj ? up.match(RE_CPF) : null;
  const cpf = mP ? `${mP[1]}.${mP[2]}.${mP[3]}-${mP[4]}` : null;
  const mE = up.match(RE_E2E);
  const e2e = mE ? mE[0].toUpperCase() : null;

  const semDoc = up.replace(RE_CNPJ, ' ').replace(RE_CPF, ' ').replace(RE_E2E, ' ');
  const blocos = (semDoc.match(/(?<!\d)\d{6,17}(?!\d)/g) || [])
    .filter(b => !/^(19|20)\d{6}$/.test(b));
  const nossoNumero = blocos.sort((a, b) => b.length - a.length)[0] || null;

  const contraparte = up
    .replace(RE_CNPJ, ' ').replace(RE_CPF, ' ').replace(RE_E2E, ' ')
    .replace(/\d+/g, ' ')
    .split(/[\s\-\/.,]+/)
    .filter(p => p.length > 2 && !RUIDO_NOME.test(p))
    .slice(0, 6).join(' ').trim() || null;

  return {
    natureza: natureza ? natureza.id : 'outros',
    naturezaRotulo: natureza ? natureza.rot : 'Nao classificado',
    tags: tags.map(t => t.id),
    // so o sinal da natureza principal vale: herdar de uma tag secundaria
    // faz um estorno de PIX enviado parecer incoerente por ser credito
    sinalEsperado: (natureza && natureza.sinal) || null,
    cnpj, cpf, e2e, nossoNumero, contraparte,
    chaveForte: e2e || nossoNumero || null,
  };
}

function diagnosticoSemantico(transacoes) {
  const n = transacoes.length || 1;
  const cont = {};
  let comChave = 0, comCnpj = 0, comContraparte = 0, sinalIncoerente = 0;
  transacoes.forEach(t => {
    const s = t.sem || {};
    const rot = s.naturezaRotulo || 'Nao classificado';
    cont[rot] = (cont[rot] || 0) + 1;
    if (s.chaveForte) comChave++;
    if (s.cnpj || s.cpf) comCnpj++;
    if (s.contraparte) comContraparte++;
    if (s.sinalEsperado && Math.sign(t.valor) !== s.sinalEsperado) sinalIncoerente++;
  });
  return {
    porNatureza: Object.entries(cont).sort((a, b) => b[1] - a[1]),
    chaveForte: comChave, pctChaveForte: comChave / n,
    documento: comCnpj, pctDocumento: comCnpj / n,
    contraparte: comContraparte, pctContraparte: comContraparte / n,
    naoClassificados: cont['Nao classificado'] || 0,
    sinalIncoerente,
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
  data: /^(data|dt|emissao|vencimento|competencia|data.?(lanc|mov|pag|receb|credito|baixa|compensacao|quitacao|liquidacao))/i,
  valor: /^(valor|vlr|montante|v\.?\s?total|valor.?(pago|recebido|liquido|baixa|titulo|documento|bruto))/i,
  debito: /^(debito|deb|saida|pagamento|pago|valor.?debito)$/i,
  credito: /^(credito|cred|entrada|recebimento|recebido|valor.?credito)$/i,
  historico: /^(hist|descric|complemento|observ|memo|favorecido|sacado|cliente|fornecedor|razao|nome|participante|beneficiario|pagador)/i,
  documento: /^(doc|documento|titulo|numero|num|n.?titulo|nosso.?numero|nossonumero|ctrc|ct.?e|nf|nfe|nfse|duplicata|parcela|chave)/i,
  tipo: /^(tipo|natureza|opera[cç][aã]o|d\s?[\/x-]\s?c|deb\s?[\/x-]?\s?cred|debito.?credito|sinal|especie)$/i,
  conta: /^(conta|banco|c.?corrente|conta.?corrente|caixa|portador|agencia)/i,
  centro: /^(centro|c\.?custo|centro.?de.?custo|filial|unidade|departamento)/i,
};

const CAMPOS_ATUA = ['data', 'valor', 'debito', 'credito', 'historico', 'documento', 'tipo', 'conta', 'centro'];

/** Linhas de fechamento que o relatório imprime e não são lançamento. */
const LINHA_TOTAL = /^\s*(total|totais|subtotal|soma|saldo|resumo|acumulado|geral|-{3,}|={3,})/i;

function normalizaCabecalho(x) {
  return String(x || '').toLowerCase()
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[()\[\]]/g, ' ')
    .replace(/\s+/g, ' ').trim();
}

/**
 * Lê um relatório do ATUA em CSV, TXT delimitado ou texto colado.
 * Detecta cabeçalho e colunas sozinho; aceita mapa manual quando a
 * detecção automática erra — é isso que permite calibrar sem mexer no código.
 *
 * opts.mapa = { data: 2, valor: 5, historico: 3, ... } (índices de coluna)
 * opts.sep  = separador forçado
 * opts.linhaCabecalho = índice da linha de cabeçalho
 */
function parseATUA(texto, nomeArquivo, opts = {}) {
  if (/^PK\x03\x04/.test(texto) || /\x00/.test(texto.slice(0, 400)) || /^%PDF/.test(texto)) {
    throw new Error('Este arquivo é XLSX, PDF ou binário. No ATUA, exporte o relatório como CSV ou TXT delimitado.');
  }
  const cru = texto.replace(/\r/g, '').split('\n');
  const linhas = cru.filter(l => l.trim());
  if (linhas.length < 2) throw new Error('Arquivo do ATUA sem linhas suficientes. Exporte o relatório em CSV com cabeçalho.');


  // Escolhe o separador pelo bloco mais largo e mais repetido, ignorando o
  // cabecalho do relatorio. Sem isso, uma virgula solta num titulo vence a tabulacao.
  const sep = opts.sep || (() => {
    const cand = [';', '\t', '|', ','];
    let melhor = ';', score = 0;
    cand.forEach(c => {
      const larguras = linhas.slice(0, 25)
        .map(l => quebraLinha(l, c).length).filter(n => n >= 2);
      if (!larguras.length) return;
      const cont = {};
      larguras.forEach(n => { cont[n] = (cont[n] || 0) + 1; });
      const [moda, vezes] = Object.entries(cont)
        .sort((a, b) => (b[1] - a[1]) || (+b[0] - +a[0]))[0];
      const s = +moda * vezes;
      if (s > score) { score = s; melhor = c; }
    });
    return melhor;
  })();

  // cabeçalho: aceita data + (valor OU débito/crédito)
  let iCab = opts.linhaCabecalho ?? -1, cols = null;
  if (iCab >= 0) {
    cols = quebraLinha(linhas[iCab], sep).map(normalizaCabecalho);
  } else {
    for (let i = 0; i < Math.min(linhas.length, 30); i++) {
      const c = quebraLinha(linhas[i], sep).map(normalizaCabecalho);
      if (c.length < 2) continue;
      const temData = c.some(x => ACHA.data.test(x));
      const temValor = c.some(x => ACHA.valor.test(x))
        || (c.some(x => ACHA.debito.test(x)) && c.some(x => ACHA.credito.test(x)));
      if (temData && temValor) { iCab = i; cols = c; break; }
    }
  }
  if (iCab < 0) {
    const amostra = linhas.slice(0, 3).map(l => l.slice(0, 90)).join(' | ');
    throw new Error(`Não localizei as colunas de data e valor. Exporte o relatório com a linha de cabeçalho. Início do arquivo: ${amostra}`);
  }

  // mapeamento: automático, sobreposto pelo manual quando houver
  const idx = {};
  CAMPOS_ATUA.forEach(campo => { idx[campo] = cols.findIndex(c => ACHA[campo].test(c)); });
  // "valor" não pode roubar a coluna de débito ou crédito
  if (idx.debito >= 0 && idx.credito >= 0 && idx.valor === idx.debito) idx.valor = -1;
  Object.entries(opts.mapa || {}).forEach(([k, v]) => {
    if (CAMPOS_ATUA.includes(k)) idx[k] = (v === '' || v == null) ? -1 : +v;
  });

  const temParDebCred = idx.debito >= 0 && idx.credito >= 0;
  if (idx.valor < 0 && !temParDebCred) {
    throw new Error('Encontrei a data mas não a coluna de valor. Use o mapeamento manual na tela para apontar qual coluna é o valor.');
  }

  const lancs = [];
  const descartadas = [];
  for (let i = iCab + 1; i < linhas.length; i++) {
    const linha = linhas[i];
    if (LINHA_TOTAL.test(linha)) { descartadas.push({ i, motivo: 'linha de total', txt: linha.slice(0, 60) }); continue; }
    const c = quebraLinha(linha, sep);
    if (c.length < 2) continue;

    const data = dataBR(c[idx.data]);
    if (!data) { descartadas.push({ i, motivo: 'data ilegível', txt: (c[idx.data] || linha).slice(0, 40) }); continue; }

    let valor;
    if (temParDebCred) {
      const d = valorBR(c[idx.debito]);
      const cr = valorBR(c[idx.credito]);
      const vd = isNaN(d) ? 0 : Math.abs(d);
      const vc = isNaN(cr) ? 0 : Math.abs(cr);
      if (!vd && !vc) { descartadas.push({ i, motivo: 'sem valor', txt: linha.slice(0, 40) }); continue; }
      valor = vc - vd;
    } else {
      valor = valorBR(c[idx.valor]);
      if (isNaN(valor)) { descartadas.push({ i, motivo: 'valor ilegível', txt: (c[idx.valor] || '').slice(0, 40) }); continue; }
      const tipo = idx.tipo >= 0 ? String(c[idx.tipo] || '').trim() : '';
      if (/^(d|deb|debito|pagamento|paga|saida|s)$/i.test(tipo) && valor > 0) valor = -valor;
      if (/^(c|cred|credito|recebimento|receb|entrada|e)$/i.test(tipo) && valor < 0) valor = Math.abs(valor);
    }
    if (valor === 0) { descartadas.push({ i, motivo: 'valor zero', txt: linha.slice(0, 40) }); continue; }

    const historico = limpaTexto(idx.historico >= 0 ? c[idx.historico] : '') || '(sem histórico)';
    const documento = limpaTexto(idx.documento >= 0 ? c[idx.documento] : '');
    lancs.push({
      data, valor, historico, documento,
      conta: idx.conta >= 0 ? limpaTexto(c[idx.conta]) : '',
      centro: idx.centro >= 0 ? limpaTexto(c[idx.centro]) : '',
      idx: lancs.length,
      linhaArquivo: i + 1,
      sem: normalizaMemo(historico, documento),
    });
  }

  if (!lancs.length) {
    throw new Error(`Li o cabeçalho mas nenhuma linha virou lançamento (${descartadas.length} descartadas). Confira o mapeamento das colunas na tela.`);
  }

  return {
    arquivo: nomeArquivo || 'atua.csv',
    separador: sep === '\t' ? 'tabulação' : sep,
    linhaCabecalho: iCab,
    cabecalho: cols,
    mapa: idx,
    colunas: Object.fromEntries(CAMPOS_ATUA.map(k => [k, idx[k] >= 0 ? cols[idx[k]] : null])),
    naoMapeadas: cols.filter((c, i) => c && !Object.values(idx).includes(i)),
    modoValor: temParDebCred ? 'colunas separadas de débito e crédito' : 'coluna única de valor',
    descartadas,
    lancamentos: lancs,
    resumo: {
      total: lancs.length,
      lidas: linhas.length - iCab - 1,
      descartadas: descartadas.length,
      liquido: lancs.reduce((a, l) => a + l.valor, 0),
      creditos: lancs.filter(l => l.valor > 0).reduce((a, l) => a + l.valor, 0),
      debitos: lancs.filter(l => l.valor < 0).reduce((a, l) => a + l.valor, 0),
      inicio: lancs.reduce((a, l) => (!a || l.data < a ? l.data : a), null),
      fim: lancs.reduce((a, l) => (!a || l.data > a ? l.data : a), null),
      comDocumento: lancs.filter(l => l.documento).length,
    },
  };
}

/* ---------- motor de conciliação ---------- */

const REGRAS = [
  { id: 'R0', nome: 'Chave forte', desc: 'EndToEnd do PIX, nosso número ou CNPJ' },
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

  /* R0 — chave forte extraída do histórico: EndToEnd, nosso número ou CNPJ + valor.
     É a única regra que casa sem depender de data, porque o identificador é único. */
  const indiceChave = new Map();
  A.forEach(a => {
    const chaves = new Set();
    if (a.sem && a.sem.chaveForte) chaves.add(a.sem.chaveForte);
    if (a.sem && a.sem.e2e) chaves.add(a.sem.e2e);
    if (a.documento) chaves.add(a.documento.replace(/\D/g, ''));
    chaves.forEach(k => {
      if (!k || k.length < 6) return;
      if (!indiceChave.has(k)) indiceChave.set(k, []);
      indiceChave.get(k).push(a);
    });
  });

  B.forEach(b => {
    if (b.casado || !b.sem) return;
    const cand = [b.sem.e2e, b.sem.chaveForte, b.sem.nossoNumero].filter(k => k && k.length >= 6);
    for (const k of cand) {
      const lista = (indiceChave.get(k) || []).filter(a => !a.casado);
      if (!lista.length) continue;
      const exato = lista.find(a => Math.abs(a.valor - b.valor) < 0.005);
      const alvo = exato || (lista.length === 1 && Math.abs(lista[0].valor - b.valor) <= tolValor ? lista[0] : null);
      if (alvo) {
        const rot = b.sem.e2e === k ? `EndToEnd ${k.slice(0, 12)}…` : `identificador ${k}`;
        casa(b, alvo, 'R0', rot);
        return;
      }
    }
    // CNPJ do pagador + valor exato dentro da janela
    const doc = b.sem.cnpj || b.sem.cpf;
    if (!doc) return;
    const porDoc = A.filter(a => !a.casado && a.sem && (a.sem.cnpj === doc || a.sem.cpf === doc)
      && Math.abs(a.valor - b.valor) < 0.005 && diasEntre(a.data, b.data) <= tolDias);
    if (porDoc.length === 1) casa(b, porDoc[0], 'R0', `mesmo CNPJ ${doc}`);
  });

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

window.CortexOFX = {
  parseOFX, parseATUA, conciliar, coberturaArquivos, REGRAS, iso, br, similaridade,
  normalizaMemo, diagnosticoSemantico, CAMPOS_ATUA, NATUREZAS,
};
