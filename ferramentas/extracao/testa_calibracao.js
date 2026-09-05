/* Bateria de calibração: layouts reais de banco e do ATUA que o parser precisa engolir. */
const fs = require('fs');
global.window = {};
new Function('window', fs.readFileSync(__dirname + '/../js/ofx.js', 'utf8'))(global.window);
const { parseOFX, parseATUA, conciliar, normalizaMemo, diagnosticoSemantico } = window.NoriaOFX;

let falhas = 0;
const ok = (c, m) => { console.log((c ? '  ok   ' : '  FALHA') + ' ' + m); if (!c) falhas++; };

console.log('\n== 1. Histórico bancário: extração de natureza e chave forte ==');
const memos = [
  ['PIX RECEBIDO E12345678202609051230abcdef1234567890 AGROPECUARIA SANTA FE LTDA 12.345.678/0001-90', 'pix_rec', true],
  ['PIX QRS DEB 05/09 TRANSPORTES CARGAS BRASIL', 'pix_env', false],
  ['CRED LIQUIDACAO COBRANCA 00000012345678901 NF 4471', 'cobranca', true],
  ['TED-CREDITO CLIENTE 987.654.321-00', 'ted', false],
  ['TAR PACOTE DE SERVICOS', 'tarifa', false],
  ['PAGTO DARF 1234567890123', 'imposto', true],
  ['DEB AUT SEM PARAR PEDAGIO', 'frota', false],
  ['PAGAMENTO SALARIO FOLHA AGOSTO', 'folha', false],
];
memos.forEach(([m, esperado, temChave]) => {
  const r = normalizaMemo(m);
  ok(r.natureza === esperado, `"${m.slice(0, 42)}…" -> ${r.natureza} (esperado ${esperado})`);
  if (temChave) ok(!!r.chaveForte, `   chave forte extraída: ${r.chaveForte}`);
});

console.log('\n== 2. Layouts do ATUA que a detecção automática precisa cobrir ==');
const layouts = {
  'ponto e vírgula clássico':
    'Data;Documento;Historico;Valor;Tipo\n' +
    '01/09/2026;4471;RECEBIMENTO AGROPECUARIA SANTA FE;15.000,00;C\n' +
    '02/09/2026;4472;PAGAMENTO POSTO IPIRANGA;2.340,55;D\n' +
    'TOTAL;;;12.659,45;\n',

  'débito e crédito em colunas separadas':
    'Data Lanc.;Nº Título;Descrição;Débito;Crédito;Centro de Custo\n' +
    '01/09/2026;4471;Recebimento cliente;;15.000,00;FILIAL RV\n' +
    '02/09/2026;4472;Combustível;2.340,55;;FROTA\n',

  'tabulação com cabeçalho depois de 4 linhas de relatório':
    'PIANETTO TRANSPORTES LTDA\nRelatório de Movimentação Financeira\nPeríodo: 01/09/2026 a 05/09/2026\n\n' +
    'Data\tDoc\tFavorecido\tValor (R$)\tD/C\n' +
    '01/09/2026\t4471\tAGROPECUARIA SANTA FE\t15.000,00\tC\n' +
    '02/09/2026\t4472\tPOSTO IPIRANGA\t2.340,55\tD\n',

  'valores com sinal negativo e data ISO':
    'data|documento|historico|valor\n' +
    '2026-09-01|4471|Recebimento|15000.00\n' +
    '2026-09-02|4472|Pagamento|-2340.55\n',

  'valor entre parênteses para débito':
    'Data,Titulo,Descricao,Valor\n' +
    '01/09/2026,4471,Recebimento,"15.000,00"\n' +
    '02/09/2026,4472,Pagamento,"(2.340,55)"\n',
};
Object.entries(layouts).forEach(([nome, txt]) => {
  try {
    const r = parseATUA(txt, nome + '.csv');
    const liq = r.resumo.liquido.toFixed(2);
    ok(r.lancamentos.length === 2 && liq === '12659.45',
      `${nome}: ${r.lancamentos.length} lançamentos, líquido ${liq}, sep "${r.separador}", ${r.modoValor}`);
  } catch (e) { ok(false, `${nome}: ${e.message}`); }
});

console.log('\n== 3. Mapeamento manual quando a detecção erra ==');
const confuso = 'Col1;Col2;Col3;Col4\n01/09/2026;4471;Recebimento;15.000,00\n02/09/2026;4472;Pagamento;-2.340,55\n';
try { parseATUA(confuso, 'x.csv'); ok(false, 'deveria falhar sem cabeçalho reconhecível'); }
catch (e) { ok(/n[aã]o localizei/i.test(e.message), 'recusa cabeçalho irreconhecível com mensagem clara'); }
const comMapa = parseATUA(confuso, 'x.csv', { linhaCabecalho: 0, mapa: { data: 0, documento: 1, historico: 2, valor: 3 } });
ok(comMapa.lancamentos.length === 2, `mapa manual recuperou ${comMapa.lancamentos.length} lançamentos`);

console.log('\n== 4. Conciliação usando a chave forte (R0) ==');
const ofx = `OFXHEADER:100
DATA:OFXSGML
VERSION:102
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><CURDEF>BRL
<BANKACCTFROM><BANKID>001<BRANCHID>3054<ACCTID>121204-7<ACCTTYPE>CHECKING</BANKACCTFROM>
<BANKTRANLIST><DTSTART>20260901<DTEND>20260905
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260903<TRNAMT>15000.00<FITID>X1<MEMO>PIX RECEBIDO E12345678202609051230ABCDEF1234567890 AGROPECUARIA SANTA FE</STMTTRN>
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260904<TRNAMT>8200.00<FITID>X2<MEMO>CRED LIQUIDACAO COBRANCA 00000012345678901</STMTTRN>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260904<TRNAMT>-2340.55<FITID>X3<MEMO>TAR PACOTE DE SERVICOS</STMTTRN>
</BANKTRANLIST><LEDGERBAL><BALAMT>20859.45<DTASOF>20260905</LEDGERBAL></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>`;
const b = parseOFX(ofx, 'teste.ofx');
ok(b.transacoes.length === 3, `OFX lido: ${b.transacoes.length} movimentos, ${b.conta.banco} ag ${b.conta.agencia}`);

// ATUA com datas trocadas de propósito: só a chave forte casa
const atuaTxt =
  'Data;Documento;Historico;Valor;Tipo\n' +
  '01/09/2026;;PIX E12345678202609051230ABCDEF1234567890 recebimento;15.000,00;C\n' +
  '02/09/2026;00000012345678901;Baixa titulo cobranca;8.200,00;C\n' +
  '04/09/2026;;Tarifa pacote;2.340,55;D\n';
const a = parseATUA(atuaTxt, 'atua.csv');
const c = conciliar(b.transacoes, a.lancamentos);
const r0 = c.porRegra.find(r => r.id === 'R0').n;
ok(r0 >= 2, `R0 casou ${r0} movimentos apesar das datas divergentes (D+2 e D+2)`);
ok(c.totais.casados === 3, `casamento total: ${c.totais.casados}/3 = ${(c.totais.taxa * 100).toFixed(0)}%`);
console.log('   regras: ' + c.porRegra.filter(r => r.n).map(r => `${r.id}=${r.n}`).join(' '));

console.log('\n== 5. Diagnóstico semântico do extrato ==');
const d = diagnosticoSemantico(b.transacoes);
ok(d.pctChaveForte >= 0.6, `chave forte em ${(d.pctChaveForte * 100).toFixed(0)}% dos movimentos`);
console.log('   naturezas: ' + d.porNatureza.map(([k, v]) => `${k} ${v}`).join(' · '));

console.log('\n== 6. Arquivos malformados dão erro que o usuário entende ==');
[['', 'vazio'], ['linha unica sem nada', 'texto solto'], ['PK\x03\x04binario', 'xlsx disfarçado']]
  .forEach(([txt, nome]) => {
    try { parseATUA(txt, nome); ok(false, `${nome}: deveria falhar`); }
    catch (e) { ok(e.message.length > 25, `${nome}: "${e.message.slice(0, 70)}…"`); }
  });

console.log(falhas ? `\n${falhas} FALHA(S)\n` : '\nTodos os casos passaram.\n');
process.exit(falhas ? 1 : 0);
