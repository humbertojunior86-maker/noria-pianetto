/* Roda o classificador contra os historicos reais extraidos do banco do ATUA. */
const fs = require('fs');
global.window = {};
new Function('window', fs.readFileSync(__dirname + '/../js/ofx.js', 'utf8'))(global.window);
const { normalizaMemo } = window.CortexOFX;

const dados = JSON.parse(fs.readFileSync('/tmp/ofx_real.json', 'utf8'));
const BANCO = { '1': 'Banco do Brasil', '341': 'Itau', '208': 'BTG', '237': 'Bradesco', '422': 'Safra', '450': 'GoFlux/FitBank' };

const porBanco = {};
const naoClassificado = {};
const semContraparte = {};
let total = 0, classificados = 0, comChave = 0, comDoc = 0, comContraparte = 0, sinalErrado = 0;

dados.forEach(d => {
  const memo = d.ds_lancamento || '';
  const valor = parseFloat(d.vl_lancamento);
  const r = normalizaMemo(memo, d.id_checknum || '');
  const b = d.nr_banco;
  porBanco[b] = porBanco[b] || { n: 0, cls: 0, chave: 0, doc: 0, cp: 0, nat: {} };
  const p = porBanco[b];
  total++; p.n++;
  const ok = r.natureza !== 'outros';
  if (ok) { classificados++; p.cls++; } else {
    const k = memo.slice(0, 40).toUpperCase();
    naoClassificado[k] = (naoClassificado[k] || 0) + 1;
  }
  p.nat[r.naturezaRotulo] = (p.nat[r.naturezaRotulo] || 0) + 1;
  if (r.chaveForte) { comChave++; p.chave++; }
  if (r.cnpj || r.cpf) { comDoc++; p.doc++; }
  if (r.contraparte) { comContraparte++; p.cp++; }
  else { const k = memo.slice(0, 40).toUpperCase(); semContraparte[k] = (semContraparte[k] || 0) + 1; }
  if (r.sinalEsperado && Math.sign(valor) !== r.sinalEsperado) sinalErrado++;
});

const pct = (a, b) => ((a / b) * 100).toFixed(1) + '%';
console.log(`\n=== ${total} movimentos reais, ${Object.keys(porBanco).length} bancos ===`);
console.log(`classificados     ${pct(classificados, total)}  (${classificados})`);
console.log(`com chave forte   ${pct(comChave, total)}  (${comChave})`);
console.log(`com CNPJ ou CPF   ${pct(comDoc, total)}  (${comDoc})`);
console.log(`com contraparte   ${pct(comContraparte, total)}  (${comContraparte})`);
console.log(`sinal incoerente  ${pct(sinalErrado, total)}  (${sinalErrado})`);

console.log('\n=== por banco ===');
Object.entries(porBanco).sort((a, b) => b[1].n - a[1].n).forEach(([b, p]) => {
  console.log(`${(BANCO[b] || b).padEnd(16)} ${String(p.n).padStart(6)} mov | classif ${pct(p.cls, p.n).padStart(6)} | chave ${pct(p.chave, p.n).padStart(6)} | CNPJ ${pct(p.doc, p.n).padStart(6)} | contraparte ${pct(p.cp, p.n).padStart(6)}`);
});

console.log('\n=== 25 padroes NAO classificados mais frequentes ===');
Object.entries(naoClassificado).sort((a, b) => b[1] - a[1]).slice(0, 25)
  .forEach(([k, n]) => console.log(`${String(n).padStart(5)}  ${k}`));

const somaNC = Object.values(naoClassificado).reduce((a, b) => a + b, 0);
console.log(`\ntotal nao classificado: ${somaNC} (${pct(somaNC, total)})`);

console.log('\n=== 10 sem contraparte identificada ===');
Object.entries(semContraparte).sort((a, b) => b[1] - a[1]).slice(0, 10)
  .forEach(([k, n]) => console.log(`${String(n).padStart(5)}  ${k}`));
