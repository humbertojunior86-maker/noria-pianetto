/* Gera arquivos de exemplo (OFX do banco + CSV do ATUA) para demonstração. */
const fs = require('fs');
const path = require('path');

const CLIENTES = [
  'AMAGGI EXPORTACAO E IMPORTACAO LTDA', 'LDC LOUIS DREYFUS COMPANY BRASIL',
  'CHS AGRONEGOCIO INDUSTRIA E COMERCIO', 'NOVA AGRI INDUSTRIA E COMERCIO',
  'NEOMILLE ALIMENTOS SA', 'AGROMERCANTIL COMERCIO DE GRAOS',
  'COFCO INTERNATIONAL BRASIL SA', 'MOTZ TRANSPORTES E LOGISTICA',
];
const FORNECEDORES = [
  'POSTO IPIRANGA RIO VERDE', 'PNEUS GOIAS DISTRIBUIDORA', 'AUTO PECAS JATAI',
  'SEGURADORA CARGA SEGURA', 'DETRAN GO LICENCIAMENTO', 'OFICINA DIESEL MINEIROS',
];

let seed = 20260904;
function rnd() { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; }
const pick = a => a[Math.floor(rnd() * a.length)];
const money = (min, max) => Math.round((min + rnd() * (max - min)) * 100) / 100;

const DIAS = ['20260828', '20260831', '20260901', '20260902', '20260903', '20260904'];

const banco = [];
const atua = [];
let fit = 764100;
let titulo = 88100;

DIAS.forEach(dia => {
  // recebimentos de clientes
  const nRec = 3 + Math.floor(rnd() * 3);
  for (let i = 0; i < nRec; i++) {
    const cli = pick(CLIENTES);
    const v = money(8000, 95000);
    const t = ++titulo;
    const via = rnd() > 0.5 ? 'TED' : 'PIX';
    banco.push({ dia, tipo: 'CREDIT', valor: v, fitid: `${++fit}`, memo: `${via} ${cli}`, doc: `${t}` });
    // ATUA registra a baixa do título — na maioria dos casos
    const sorte = rnd();
    if (sorte > 0.14) {
      const atrasa = sorte > 0.92 ? 1 : 0;
      const centavos = sorte > 0.88 && sorte <= 0.92 ? -0.03 : 0;
      atua.push({ dia, atrasa, valor: v + centavos, hist: `Baixa titulo ${t} - ${cli.split(' ')[0]}`, doc: `${t}`, tipo: 'C' });
    }
  }

  // pagamentos a fornecedores
  const nPag = 2 + Math.floor(rnd() * 3);
  for (let i = 0; i < nPag; i++) {
    const forn = pick(FORNECEDORES);
    const v = money(900, 28000);
    const t = ++titulo;
    banco.push({ dia, tipo: 'DEBIT', valor: -v, fitid: `${++fit}`, memo: `PAGAMENTO ${forn}`, doc: `${t}` });
    if (rnd() > 0.12) atua.push({ dia, atrasa: 0, valor: -v, hist: `Pagto ${forn.split(' ').slice(0, 2).join(' ')}`, doc: `${t}`, tipo: 'D' });
  }

  // tarifas bancárias — quase nunca lançadas no ATUA
  if (rnd() > 0.3) {
    const v = money(19, 240);
    banco.push({ dia, tipo: 'FEE', valor: -v, fitid: `${++fit}`, memo: 'TARIFA PACOTE / CESTA SERVICOS', doc: '' });
  }

  // um crédito agrupando 2 títulos (regra R3)
  if (dia === '20260902' || dia === '20260904') {
    const cli = pick(CLIENTES);
    const a = money(6000, 18000), b = money(6000, 18000);
    const t1 = ++titulo, t2 = ++titulo;
    banco.push({ dia, tipo: 'CREDIT', valor: Math.round((a + b) * 100) / 100, fitid: `${++fit}`, memo: `TED ${cli}`, doc: '' });
    atua.push({ dia, atrasa: 0, valor: a, hist: `Baixa titulo ${t1} - ${cli.split(' ')[0]}`, doc: `${t1}`, tipo: 'C' });
    atua.push({ dia, atrasa: 0, valor: b, hist: `Baixa titulo ${t2} - ${cli.split(' ')[0]}`, doc: `${t2}`, tipo: 'C' });
  }
});

// baixas manuais no ATUA sem dinheiro no banco
atua.push({ dia: '20260904', atrasa: 0, valor: 27180.5, hist: 'Baixa manual titulo 88121 - ajuste', doc: '88121', tipo: 'C' });
atua.push({ dia: '20260903', atrasa: 0, valor: 12300.0, hist: 'Pagto fornecedor pneus - 2a conta', doc: '90144', tipo: 'D' });

/* ---------- monta o OFX 1.x (SGML) ---------- */
const somaBanco = banco.reduce((a, t) => a + t.valor, 0);
const saldo = Math.round((418230.55 + somaBanco) * 100) / 100;

const linhasTrn = banco.map(t => `<STMTTRN>
<TRNTYPE>${t.tipo}
<DTPOSTED>${t.dia}120000[-3:BRT]
<TRNAMT>${t.valor.toFixed(2)}
<FITID>${t.fitid}
${t.doc ? `<CHECKNUM>${t.doc}\n` : ''}<MEMO>${t.memo}
</STMTTRN>`).join('\n');

const ofx = `OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX>
<SIGNONMSGSRSV1>
<SONRS>
<STATUS><CODE>0<SEVERITY>INFO</STATUS>
<DTSERVER>20260905083000[-3:BRT]
<LANGUAGE>POR
<FI><ORG>Banco do Brasil<FID>001</FI>
</SONRS>
</SIGNONMSGSRSV1>
<BANKMSGSRSV1>
<STMTTRNRS>
<TRNUID>1001
<STATUS><CODE>0<SEVERITY>INFO</STATUS>
<STMTRS>
<CURDEF>BRL
<BANKACCTFROM>
<BANKID>001
<BRANCHID>3054
<ACCTID>121204-7
<ACCTTYPE>CHECKING
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20260828000000[-3:BRT]
<DTEND>20260904235959[-3:BRT]
${linhasTrn}
</BANKTRANLIST>
<LEDGERBAL>
<BALAMT>${saldo.toFixed(2)}
<DTASOF>20260904235959[-3:BRT]
</LEDGERBAL>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
`;

/* ---------- monta o CSV do ATUA ---------- */
function dataBR(dia, atrasa) {
  const y = +dia.slice(0, 4), m = +dia.slice(4, 6), d = +dia.slice(6, 8);
  const dt = new Date(Date.UTC(y, m - 1, d + (atrasa || 0)));
  return `${String(dt.getUTCDate()).padStart(2, '0')}/${String(dt.getUTCMonth() + 1).padStart(2, '0')}/${dt.getUTCFullYear()}`;
}
const csv = ['Data Lancamento;Documento;Historico;Tipo;Valor']
  .concat(atua.map(l => [
    dataBR(l.dia, l.atrasa),
    l.doc,
    l.hist,
    l.tipo,
    Math.abs(l.valor).toFixed(2).replace('.', ','),
  ].join(';')))
  .join('\n');

const dir = path.join(__dirname, '..', 'exemplos');
fs.mkdirSync(dir, { recursive: true });
fs.writeFileSync(path.join(dir, 'extrato-bb-3054-121204.ofx'), ofx, 'latin1');
fs.writeFileSync(path.join(dir, 'atua-lancamentos-28-08-a-04-09.csv'), csv, 'utf8');
console.log(`OFX: ${banco.length} movimentos · ATUA: ${atua.length} lançamentos · saldo ${saldo.toFixed(2)}`);
