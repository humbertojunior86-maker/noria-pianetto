/* ==========================================================================
   NÓRIA — sequência de abertura
   --------------------------------------------------------------------------
   Módulo ES sem dependências. Desenha em <canvas> o núcleo acordando.

   A malha é um cérebro procedural de verdade: nuvem de pontos dobrada em
   dois hemisférios, com tronco encefálico, e sinapses ligando cada nó aos
   vizinhos mais próximos. Os pontos acendem conforme a inicialização avança
   — o cérebro se forma na frente de quem abre o sistema.

   Quatro atos, ~9,2 s no total:
     1  a malha se forma — instância isolada, banco em somente leitura
     2  os 15 agentes acendem em volta e se ligam ao núcleo
     3  os pares de contraprova se ligam entre si
     4  núcleo em operação — aguardando objetivo

   Uso:
     import { abertura, pular } from './js/abertura.js';
     abertura(document.querySelector('#abertura'), () => { ... });
     botaoPular.onclick = pular;

   Nada aqui é enfeite solto: os nomes, as áreas e os pares desenhados são os
   que existem no núcleo. Se a API responder a tempo, vêm dela; se não,
   caem no retrato abaixo, que é o mesmo cadastro.
   ========================================================================== */

/* ----- Cores: lidas dos tokens CSS, com fallback literal ----------------- */
const PADRAO = {
  '--fundo': '#101318',
  '--painel': '#191E26',
  '--painel-alto': '#222936',
  '--tinta': '#F3F5F7',
  '--tinta-2': '#ADB7C6',
  '--tinta-3': '#6F7B8C',
  '--tinta-4': '#4A5464',
  '--acento': '#50D6BC',
  '--ok': '#68D391',
  '--atencao': '#F2C66D',
  '--erro': '#F08080',
  '--cromo': '#C6CFDA',
  '--cromo-2': '#8E99A8',
  '--mono': '"JetBrains Mono", ui-monospace, monospace',
  '--display': '"Cabinet Grotesk", sans-serif'
};

function lerTokens() {
  const cs = getComputedStyle(document.documentElement);
  const t = {};
  for (const k in PADRAO) {
    const v = (cs.getPropertyValue(k) || '').trim();
    t[k] = v || PADRAO[k];
  }
  return t;
}

/* ----- Retrato do cadastro (espelho de agentes/registro.py) ------------- */
const AGENTES = [
  { id: 'comercial.faturamento',  nome: 'Bruno',  area: 'faturamento',    fam: 'Comercial & Faturamento' },
  { id: 'comercial.inteligencia', nome: 'Sofia',  area: 'comercial',      fam: 'Comercial & Faturamento' },
  { id: 'controladoria.margem',   nome: 'Caio',   area: 'controladoria',  fam: 'Controladoria & Custos' },
  { id: 'auditoria.interna',      nome: 'Lívia',  area: 'auditoria',      fam: 'Controladoria & Custos' },
  { id: 'tesouraria.conciliador', nome: 'Marta',  area: 'tesouraria',     fam: 'Financeiro & Tesouraria' },
  { id: 'cobranca.carteira',      nome: 'Otávio', area: 'cobrança',       fam: 'Financeiro & Tesouraria' },
  { id: 'contas.pagar',           nome: 'Íris',   area: 'contas a pagar', fam: 'Financeiro & Tesouraria' },
  { id: 'fiscal.documento',       nome: 'Alan',   area: 'fiscal',         fam: 'Fiscal & Contábil' },
  { id: 'fiscal.tributos',        nome: 'Téo',    area: 'tributos',       fam: 'Fiscal & Contábil' },
  { id: 'gente.documentos',       nome: 'Clara',  area: 'gente',          fam: 'Gente & Conformidade' },
  { id: 'processos.rotina',       nome: 'Otto',   area: 'processos',      fam: 'Gente & Conformidade' },
  { id: 'gente.jornada',          nome: 'Paula',  area: 'jornada',        fam: 'Gente & Conformidade' },
  { id: 'frota.resultado',        nome: 'Davi',   area: 'frota',          fam: 'Operações & Frota' },
  { id: 'frota.viagem',           nome: 'Nina',   area: 'viagem',         fam: 'Operações & Frota' },
  { id: 'frota.combustivel',      nome: 'Rui',    area: 'combustível',    fam: 'Operações & Frota' }
];

/* Agrupa por área — o campo vem do cadastro, não é invenção da abertura.
   Devolve [{ fam, ids:[...], pares:[[i,j],...] }] com todos os pares da área. */
function familias(lista) {
  const mapa = new Map();
  lista.forEach((a) => {
    const k = a.fam || a.area || '—';
    if (!mapa.has(k)) mapa.set(k, []);
    mapa.get(k).push(a.id);
  });
  return [...mapa.entries()].map(([fam, ids]) => {
    const pares = [];
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) pares.push([ids[i], ids[j]]);
    }
    return { fam, ids, pares };
  });
}

const FAMILIAS_PADRAO = familias(AGENTES);

/* Pares de contraprova ligados no núcleo (nucleo/orquestrador.py CONTRAPROVA) */
const PARES = [
  ['contas.pagar', 'auditoria.interna'],
  ['comercial.faturamento', 'fiscal.documento'],
  ['controladoria.margem', 'frota.resultado']
];

/* ----- Tempos do roteiro (ms) ------------------------------------------ */
const T_MALHA = 2400;                    // cérebro totalmente formado
const T_AG = 2150;                       // primeiro agente acende
const PASSO_AG = 235;                    // intervalo entre agentes
const T_AG_FIM = T_AG + PASSO_AG * (AGENTES.length - 1) + 420;
const T_FAM = T_AG_FIM + 240;            // as áreas se fecham entre si
const PASSO_FAM = 300;
const T_FAM_FIM = T_FAM + PASSO_FAM * FAMILIAS_PADRAO.length + 200;
const T_PAR = T_FAM_FIM + 180;           // primeiro par de contraprova
const PASSO_PAR = 560;
const T_PAR_FIM = T_PAR + PASSO_PAR * PARES.length;
const T_ATO4 = T_PAR_FIM + 320;
const T_REVELA = T_ATO4 + 420;           // clarão e a frase final
const T_FIM = T_ATO4 + 2600;

const MAX_LINHAS = 7;

/* ----- Utilidades ------------------------------------------------------- */
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const facil = (x) => 1 - Math.pow(1 - clamp(x, 0, 1), 3);          // easeOutCubic
const facilInOut = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);

/* Luminância aproximada — decide se estamos em tema claro */
function ehClaro(cor) {
  const c = (cor || '').trim();
  let r = 16, g = 19, b = 24;
  const m = c.match(/rgba?\(([^)]+)\)/);
  if (m) {
    const p = m[1].split(/[,\s/]+/).filter(Boolean).map(Number);
    [r, g, b] = p;
  } else if (c.startsWith('#')) {
    const s = c.slice(1);
    const f = s.length === 3 ? s.split('').map((x) => x + x).join('') : s;
    const n = parseInt(f, 16);
    r = (n >> 16) & 255; g = (n >> 8) & 255; b = n & 255;
  }
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 > 0.5;
}

function rgba(hex, a) {
  const h = (hex || '').trim();
  if (h.startsWith('rgb')) return h.replace(/rgba?\(([^)]+)\)/, (m, p) => {
    const n = p.split(/[,\s/]+/).filter(Boolean).slice(0, 3).join(',');
    return `rgba(${n},${a})`;
  });
  const s = h.replace('#', '');
  const f = s.length === 3 ? s.split('').map((c) => c + c).join('') : s;
  const n = parseInt(f || '000000', 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

/* ==========================================================================
   Cérebro procedural
   ========================================================================== */

/* Nuvem em forma de encéfalo: esfera deformada em lobos, hemisférios
   separados, base achatada e um tronco descendo. */
function nuvemCerebro(n, semente = 7) {
  let s = semente;
  const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
  const pts = [];
  for (let i = 0; i < n; i++) {
    const lado = i % 2 === 0 ? 1 : -1;
    const u = rnd() * 2 - 1;
    const t = rnd() * Math.PI * 2;
    const r = Math.sqrt(1 - u * u);
    let x = r * Math.cos(t), y = u, z = r * Math.sin(t);
    const dobra = 0.14 * Math.sin(y * 9 + z * 5) + 0.1 * Math.sin(x * 7 - y * 4);
    const k = 1 + dobra;
    x *= k * 0.62; y *= k * 0.78; z *= k * 0.86;
    x = lado * (Math.abs(x) + 0.16);
    if (y < -0.45) y = -0.45 + (y + 0.45) * 0.45;
    z *= 1 + 0.16 * Math.max(0, y);
    pts.push({ x, y, z, semente: rnd() });
  }
  const tronco = Math.round(n * 0.07);
  for (let i = 0; i < tronco; i++) {
    const k = i / tronco;
    pts.push({
      x: (rnd() - 0.5) * 0.12,
      y: -0.5 - k * 0.5,
      z: (rnd() - 0.5) * 0.14 + 0.05,
      semente: rnd()
    });
  }
  return pts;
}

/* Sinapses: cada nó liga aos k vizinhos mais próximos dentro de um raio. */
function sinapses(pts, k = 3, maxLen = 0.34) {
  const arestas = [];
  for (let i = 0; i < pts.length; i++) {
    const cand = [];
    for (let j = i + 1; j < Math.min(pts.length, i + 90); j++) {
      const dx = pts[i].x - pts[j].x;
      const dy = pts[i].y - pts[j].y;
      const dz = pts[i].z - pts[j].z;
      const l = Math.hypot(dx, dy, dz);
      if (l < maxLen) cand.push([l, j]);
    }
    cand.sort((a, b) => a[0] - b[0]);
    for (let m = 0; m < Math.min(k, cand.length); m++) arestas.push([i, cand[m][1]]);
  }
  return arestas;
}

/* ----- Instância única (para que `pular()` funcione sem referência) ----- */
let atual = null;

/**
 * Inicia a sequência de abertura dentro de `el`.
 * @param {HTMLElement} el container (recebe o canvas e o log)
 * @param {Function} aoTerminar chamado uma vez, ao fim da sequência
 * @returns {{pular:Function, destruir:Function}}
 */
/* Decide se a abertura já começa aliviada: respeita ?leve=1 / ?leve=0 na
   barra de endereço, depois a lembrança da última vez naquela máquina,
   depois um palpite pelo número de núcleos. */
function pesoInicial() {
  try {
    const q = new URLSearchParams(location.search).get('leve');
    if (q === '1') return true;
    if (q === '0') return false;
    const g = localStorage.getItem('noria.leve');
    if (g === '1') return true;
    if (g === '0') return false;
  } catch (e) { /* sem acesso ao armazenamento: segue no palpite */ }
  return (navigator.hardwareConcurrency || 4) <= 2;
}

function lembrarPeso(v) {
  try { localStorage.setItem('noria.leve', v ? '1' : '0'); } catch (e) { /* ok */ }
}

export function abertura(el, aoTerminar) {
  if (atual) atual.destruir();

  let T = lerTokens();
  let claro = ehClaro(T['--fundo']);

  /* ----- DOM ------------------------------------------------------------ */
  const tela = document.createElement('canvas');
  tela.className = 'abertura-tela';
  el.appendChild(tela);

  const marca = document.createElement('div');
  marca.className = 'abertura-marca';
  marca.innerHTML =
    '<div class="abertura-nome">NÓRIA</div>' +
    '<div class="abertura-sub">Pianetto Transportes</div>';
  el.appendChild(marca);

  const logEl = document.createElement('div');
  logEl.className = 'abertura-log';
  el.appendChild(logEl);

  const desfecho = document.createElement('div');
  desfecho.className = 'abertura-desfecho';
  el.appendChild(desfecho);

  const barra = document.createElement('div');
  barra.className = 'abertura-barra';
  barra.innerHTML = '<i></i>';
  el.appendChild(barra);
  const barraInterna = barra.querySelector('i');

  /* ----- Cadastro vivo, se a API responder a tempo ---------------------- */
  let agentes = AGENTES.map((a) => ({ ...a, situacao: null }));
  let resumoEquipe = null;
  try {
    const tok = localStorage.getItem('noria.token');
    if (tok) {
      fetch('/api/agentes', { headers: { Authorization: `Bearer ${tok}` } })
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
          const lista = d && d.agentes;
          if (!Array.isArray(lista) || lista.length === 0) return;
          const porId = new Map(lista.map((a) => [a.id, a]));
          agentes.forEach((a) => {
            const v = porId.get(a.id);
            if (v) {
              a.nome = v.nome || a.nome;
              a.situacao = v.situacao || null;
              a.fam = v.area || a.fam;
            }
          });
          const hab = lista.filter((a) => a.situacao === 'habilitado').length;
          const rev = lista.filter((a) => a.situacao === 'revisor').length;
          const sem = lista.length - hab - rev;
          resumoEquipe = `${hab} habilitados · ${rev} revisor · ${sem} sem integração`;
        })
        .catch(() => { /* silencioso: a abertura não depende disso */ });
    }
  } catch { /* storage bloqueado */ }

  /* Peso do desenho. Numa parede modesta o quadro cheio derrubava a
     animação para 5 quadros por segundo — bonito parado, travado em
     movimento. Aqui ele mede a si mesmo nos primeiros instantes e, se não
     estiver dando conta, alivia sozinho. A escolha fica guardada para as
     próximas aberturas daquela máquina. */
  let leve = pesoInicial();
  let dpr = Math.min(window.devicePixelRatio || 1, leve ? 1 : 1.5);
  /* Fator de resolução do desenho. O gargalo medido não é conta, é pintura:
     numa tela de parede sem placa de vídeo decente, encher 1920x1080 a cada
     quadro já consome o orçamento inteiro. Aqui o cérebro é desenhado numa
     grade menor e esticado pelo próprio navegador — na parede, a poucos
     metros, a diferença não se vê; a fluidez, sim. */
  let fPix = leve ? 0.7 : 1;
  el.dataset.peso = leve ? 'leve' : 'cheio';   // visível na inspeção da tela

  /* ----- Poeira de fundo: dá profundidade numa tela grande -------------- */
  const poeira = (() => {
    let sp = 991;
    const rnd = () => (sp = (sp * 16807) % 2147483647) / 2147483647;
    return Array.from({ length: leve ? 55 : 170 }, () => ({
      x: rnd(), y: rnd(), z: 0.25 + rnd() * 0.75, f: rnd() * 6.2832
    }));
  })();

  /* ----- Malha ---------------------------------------------------------- */
  const N_BASE = 1200;
  const pts = nuvemCerebro(N_BASE);
  const arestas = sinapses(pts, 3);
  // Metade dos nós, mais o tronco inteiro: no modo leve a silhueta continua
  // sendo um encéfalo, só com menos fios.
  const ativoLeve = pts.map((_, i) => i % 2 === 0 || i >= N_BASE);
  const arestasLeve = arestas.filter((e) => ativoLeve[e[0]] && ativoLeve[e[1]]);

  /* ----- Estado --------------------------------------------------------- */
  let w = 0, h = 0, compacto = false, esc = 1;
  const ctx = tela.getContext('2d');
  const t0 = performance.now();
  let raf = 0;
  let encerrado = false;
  let escritas = 0;         // linhas de log já emitidas
  let halo = null, haloChave = '';
  let vinheta = null, vinhetaChave = '';
  let brilho = null;        // selo de brilho pré-desenhado, no lugar do borrão
  let brilhoCor = '';
  let ultimoQuadro = 0;     // instante do último desenho, para segurar a taxa
  const amostras = [];      // duração dos primeiros quadros, para pesar a máquina
  let pesado = false;       // já decidiu o peso nesta execução
  const NIVEIS = 5;         // faixas de opacidade em que os fios são agrupados
  const cestos = [];        // 2 cores x NIVEIS faixas, reaproveitados a cada quadro
  for (let i = 0; i < NIVEIS * 2; i++) cestos.push([]);
  const cestosNo = [];
  for (let i = 0; i < NIVEIS; i++) cestosNo.push([]);

  /* O brilho dos nós quentes saía de shadowBlur, que o navegador refaz do
     zero a cada círculo. Desenhado uma vez num selo e carimbado depois,
     custa uma fração disso. */
  function selo(cor) {
    if (brilho && brilhoCor === cor) return brilho;
    const r = Math.max(8, Math.round(11 * esc));
    const c = document.createElement('canvas');
    c.width = c.height = r * 2;
    const g = c.getContext('2d');
    const grad = g.createRadialGradient(r, r, 0, r, r, r);
    grad.addColorStop(0, rgba(cor, 0.95));
    grad.addColorStop(0.35, rgba(cor, 0.28));
    grad.addColorStop(1, rgba(cor, 0));
    g.fillStyle = grad;
    g.fillRect(0, 0, r * 2, r * 2);
    brilho = c; brilhoCor = cor;
    return c;
  }
  const roteiro = [];       // preenchido abaixo (depende de `agentes`)

  function medir() {
    const r = el.getBoundingClientRect();
    w = Math.max(1, r.width); h = Math.max(1, r.height);
    compacto = w < 760;
    // Numa tela de parede o público está longe: tudo cresce com a largura.
    esc = clamp(w / 1440, 0.86, 2.1);
    el.style.setProperty('--esc-ab', esc.toFixed(3));
    const k = dpr * fPix;
    tela.width = Math.max(1, Math.round(w * k));
    tela.height = Math.max(1, Math.round(h * k));
    tela.style.width = `${w}px`;
    tela.style.height = `${h}px`;
    ctx.setTransform(k, 0, 0, k, 0, 0);
    brilho = null; halo = null; haloChave = ''; vinheta = null; vinhetaChave = '';
  }
  medir();
  const ro = new ResizeObserver(medir);
  ro.observe(el);

  /* ----- Roteiro do log ------------------------------------------------- */
  function montarRoteiro() {
    roteiro.length = 0;
    roteiro.push(
      { t: 200,  tipo: 'info', txt: 'instância isolada · noria-prod-01' },
      { t: 760,  tipo: 'ok',   txt: 'banco atua aberto em somente leitura' },
      { t: 1320, tipo: 'ok',   txt: '20 consultas nomeadas · nenhuma escrita permitida' },
      { t: 1880, tipo: 'info', txt: 'seis camadas de validação armadas' },
      { t: 2060, tipo: 'info', txt: 'acordando a equipe' }
    );
    agentes.forEach((a, i) => roteiro.push({
      t: T_AG + i * PASSO_AG + 120,
      tipo: 'ok',
      txt: `${a.nome.toLowerCase()} · ${a.area}`
    }));
    roteiro.push({
      t: T_AG_FIM,
      tipo: 'ok',
      // resolvido na hora de escrever: a API pode ter respondido depois daqui
      txt: () => resumoEquipe || `${agentes.length} agentes no cadastro`
    });
    roteiro.push({ t: T_FAM - 60, tipo: 'info', txt: 'fechando as áreas' });
    FAMILIAS_PADRAO.forEach((f, i) => roteiro.push({
      t: T_FAM + i * PASSO_FAM + 120,
      tipo: 'ok',
      txt: `${f.fam.toLowerCase()} · ${f.ids.length} agentes`
    }));
    roteiro.push({ t: T_PAR - 60, tipo: 'info', txt: 'ligando os pares de contraprova' });
    PARES.forEach((p, i) => {
      const a = agentes.find((x) => x.id === p[0]);
      const b = agentes.find((x) => x.id === p[1]);
      roteiro.push({
        t: T_PAR + i * PASSO_PAR + 140,
        tipo: 'ok',
        txt: `${(a ? a.nome : p[0]).toLowerCase()} × ${(b ? b.nome : p[1]).toLowerCase()} · outro caminho do banco`
      });
    });
    roteiro.push({ t: T_ATO4 + 80, tipo: 'nucleo', txt: 'núcleo em operação — aguardando objetivo' });
    roteiro.sort((a, b) => a.t - b.t);
  }
  montarRoteiro();

  function emitir(linha) {
    const d = document.createElement('div');
    d.className = `l ${linha.tipo}`;
    const n = String(escritas + 1).padStart(2, '0');
    const txt = typeof linha.txt === 'function' ? linha.txt() : linha.txt;
    d.textContent = `${n} › ${txt}`;
    logEl.appendChild(d);
    // reflow para a transição pegar
    void d.offsetWidth;
    d.classList.add('entrou');
    while (logEl.children.length > MAX_LINHAS) logEl.removeChild(logEl.firstChild);
  }

  /* ----- Geometria dos agentes na tela ---------------------------------- */
  /* Devolve {x, y, ang} de cada agente num anel elíptico em volta do cérebro. */
  function anel(cx, cy, R) {
    const rx = Math.min(w * 0.385, R * 3.0);
    const ry = Math.min(h * 0.345, R * 2.25);
    return agentes.map((a, i) => {
      const ang = -Math.PI / 2 + (i / agentes.length) * Math.PI * 2;
      return {
        ref: a,
        i,
        ang,
        x: cx + Math.cos(ang) * rx,
        y: cy + Math.sin(ang) * ry,
        direita: Math.cos(ang) >= 0
      };
    });
  }

  /* Curva do núcleo até o agente, puxada de leve para fora do centro. */
  function curva(cx, cy, p) {
    const mx = (cx + p.x) / 2;
    const my = (cy + p.y) / 2;
    const nx = -(p.y - cy), ny = (p.x - cx);
    const l = Math.hypot(nx, ny) || 1;
    const desvio = 0.13;
    return {
      cx1: mx + (nx / l) * l * desvio * 0.5,
      cy1: my + (ny / l) * l * desvio * 0.5
    };
  }

  /* Arco entre dois nós do anel, curvado por fora pelo lado curto.
     Usar o ponto médio falha quando os dois são quase opostos: o meio cai
     em cima do núcleo e a direção da curva vira ruído. */
  function arcoEntre(a, b, cx, cy, folga) {
    let dif = b.ang - a.ang;
    while (dif > Math.PI) dif -= Math.PI * 2;
    while (dif < -Math.PI) dif += Math.PI * 2;
    const meio = a.ang + dif / 2;
    const largo = Math.abs(dif) / Math.PI;
    const fora = Math.hypot(a.x - cx, a.y - cy) * (1 + folga * (0.35 + largo));
    return { cx1: cx + Math.cos(meio) * fora, cy1: cy + Math.sin(meio) * fora * 0.86 };
  }

  function pontoNaCurva(ax, ay, c1x, c1y, bx, by, t) {
    const u = 1 - t;
    return {
      x: u * u * ax + 2 * u * t * c1x + t * t * bx,
      y: u * u * ay + 2 * u * t * c1y + t * t * by
    };
  }

  /* ----- Quadro --------------------------------------------------------- */
  function quadro(agora) {
    const t = agora - t0;

    // Segura em ~32 quadros por segundo no modo leve: a animação é toda
    // baseada no relógio, então pular quadros não altera a coreografia.
    if (leve && agora - ultimoQuadro < 30) { raf = requestAnimationFrame(quadro); return; }
    // O primeiro segundo e meio não conta: ali ainda há carga de fontes e
    // de rede, e puniria a máquina por algo que não é o desenho.
    if (ultimoQuadro && t > 1500) amostras.push(agora - ultimoQuadro);
    ultimoQuadro = agora;

    /* Governo do desempenho. A cada punhado de quadros olha a mediana: se
       está engasgando, alivia mais um degrau e redesenha menor. Nunca sobe
       de volta, para não ficar oscilando na frente de quem assiste. */
    if (amostras.length >= 30) {
      const ord = amostras.slice().sort((a, b) => a - b);
      const meio = ord[Math.floor(ord.length / 2)];
      amostras.length = 0;
      if (meio > 30 && fPix > 0.45) {
        if (!leve) { leve = true; dpr = Math.min(dpr, 1); el.dataset.peso = 'leve'; }
        fPix = Math.max(0.45, fPix * 0.84);
        el.dataset.pixel = fPix.toFixed(2);
        medir();
      }
      if (!pesado) { pesado = true; lembrarPeso(leve); }
    }

    // log
    while (escritas < roteiro.length && roteiro[escritas].t <= t) {
      emitir(roteiro[escritas]);
      escritas++;
    }
    const prog = clamp(t / T_ATO4, 0, 1);
    barraInterna.style.transform = `scaleX(${prog.toFixed(4)})`;

    // saída
    if (t >= T_FIM) { terminar(); return; }

    ctx.clearRect(0, 0, w, h);

    const cx = w / 2;
    const cy = h * (compacto ? 0.42 : 0.44);
    // Câmera: entra afastada e aproxima nos primeiros segundos; depois
    // respira devagar, para a imagem nunca ficar estática na parede.
    const camera = 0.80 + 0.20 * facilInOut(clamp(t / 3400, 0, 1));
    const respira = 1 + 0.016 * Math.sin(t * 0.00062);
    const Rbase = Math.min(w * 0.5, h * 0.62) * (compacto ? 0.40 : 0.35);
    const R = Rbase * camera * respira;

    const aceso = clamp(t / T_MALHA, 0, 1);   // fração da malha já acesa
    // Balanço em vez de giro completo. Com a volta inteira, por volta dos
    // 10 s a câmera ficava exatamente sobre o vão entre os hemisférios e o
    // cérebro parecia partido em dois. O balanço nunca chega nesse ângulo.
    const gy = Math.sin(t * 0.00040) * 0.85 + Math.sin(t * 0.00017) * 0.16;
    const gx = Math.sin(t * 0.00018) * 0.22;

    const cCromo = T['--cromo-2'];
    const cAcento = T['--acento'];
    const cAtencao = T['--atencao'];
    const forca = claro ? 1.35 : 1;            // no claro, mais contraste
    // Clarão do desfecho: tudo que já está na tela acende de uma vez.
    const dtRev = t - T_REVELA;
    const clarao = dtRev >= 0 && dtRev < 620 ? 1 - dtRev / 620 : 0;

    // projeção
    const ativos = leve ? ativoLeve : null;
    const proj = new Array(pts.length);
    const cosY = Math.cos(gy), sinY = Math.sin(gy);
    const cosX = Math.cos(gx), sinX = Math.sin(gx);
    for (let i = 0; i < pts.length; i++) {
      if (ativos && !ativos[i]) { proj[i] = null; continue; }
      const p = pts[i];
      let x = p.x * cosY - p.z * sinY;
      let z = p.x * sinY + p.z * cosY;
      const y = p.y * cosX - z * sinX;
      z = p.y * sinX + z * cosX;
      const persp = 2.6 / (2.6 + z);
      proj[i] = {
        X: cx + x * R * persp,
        Y: cy - y * R * persp,
        z,
        persp,
        on: p.semente < aceso + 0.001,
        puls: 0.6 + 0.4 * Math.sin(t * 0.0016 + p.semente * 22)
      };
    }

    // poeira: anda devagar e acompanha a câmera, criando paralaxe
    ctx.fillStyle = rgba(cCromo, 0.11 * forca);
    ctx.beginPath();
    for (let i = 0; i < poeira.length; i++) {
      const d = poeira[i];
      const px = ((d.x + t * 0.0000075 * d.z) % 1) * w;
      const py = ((d.y + Math.sin(d.f + t * 0.0002) * 0.004 + 1) % 1) * h;
      const dx = (px - cx) * (camera - 1) * 0.5;
      const dy = (py - cy) * (camera - 1) * 0.5;
      const r = d.z * 1.3 * esc;
      ctx.moveTo(px + dx + r, py + dy);
      ctx.arc(px + dx, py + dy, r, 0, 6.2832);
    }
    ctx.fill();

    // halo
    // O halo só muda quando o raio muda de verdade; refazer o gradiente a
    // cada quadro era desperdício puro.
    const chaveHalo = `${Math.round(cx)}|${Math.round(cy)}|${Math.round(R / 4)}|${claro}`;
    if (chaveHalo !== haloChave) {
      halo = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 1.9);
      halo.addColorStop(0, rgba(cAcento, claro ? 0.05 : 0.075));
      halo.addColorStop(0.45, rgba(cCromo, claro ? 0.02 : 0.03));
      halo.addColorStop(1, rgba(cCromo, 0));
      haloChave = chaveHalo;
    }
    ctx.fillStyle = halo;
    ctx.fillRect(cx - R * 2, cy - R * 2, R * 4, R * 4);

    /* Sinapses e nós em lote. Antes cada fio virava um traço próprio —
       milhares de chamadas por quadro. Agora a opacidade é arredondada em
       cinco faixas e cada faixa vira um traço só. */
    const fios = leve ? arestasLeve : arestas;
    for (let i = 0; i < cestos.length; i++) cestos[i].length = 0;
    for (let e = 0; e < fios.length; e++) {
      const a = proj[fios[e][0]], b = proj[fios[e][1]];
      if (!a || !b || !a.on || !b.on) continue;
      const prof = (a.z + b.z) / 2;
      const al = clamp((0.16 + 0.36 * (1 - (prof + 1) / 2)) * (0.55 + 0.45 * a.puls) * forca, 0, 1);
      const n = Math.min(NIVEIS - 1, Math.floor(al * NIVEIS));
      const c = cestos[(e % 9 === 0 ? NIVEIS : 0) + n];
      c.push(a.X, a.Y, b.X, b.Y);
    }
    ctx.lineWidth = 0.65;
    for (let k = 0; k < cestos.length; k++) {
      const c = cestos[k];
      if (!c.length) continue;
      ctx.strokeStyle = rgba(k >= NIVEIS ? cAcento : cCromo,
        ((k % NIVEIS) + 0.5) / NIVEIS);
      ctx.beginPath();
      for (let j = 0; j < c.length; j += 4) {
        ctx.moveTo(c[j], c[j + 1]); ctx.lineTo(c[j + 2], c[j + 3]);
      }
      ctx.stroke();
    }

    for (let i = 0; i < cestosNo.length; i++) cestosNo[i].length = 0;
    const carimbo = selo(cAcento);
    const meioSelo = carimbo.width / 2;
    for (let i = 0; i < proj.length; i++) {
      const p = proj[i];
      if (!p || !p.on) continue;
      const quente = i % 23 === 0;
      const raio = (quente ? 1.9 : 1.05) * esc * p.persp * (0.7 + 0.5 * p.puls);
      const al = clamp((quente ? 0.95 : 0.6) * (0.5 + 0.5 * (1 - (p.z + 1) / 2)) * forca, 0, 1);
      if (quente) {
        const g = (0.5 + 0.5 * p.puls) * (leve ? 1.5 : 2.1) * esc * p.persp;
        ctx.globalAlpha = al;
        ctx.drawImage(carimbo, p.X - meioSelo * g, p.Y - meioSelo * g,
          carimbo.width * g, carimbo.height * g);
        ctx.globalAlpha = 1;
      }
      const n = Math.min(NIVEIS - 1, Math.floor(al * NIVEIS));
      cestosNo[n].push(p.X, p.Y, raio, quente ? 1 : 0);
    }
    for (let k = 0; k < NIVEIS; k++) {
      const c = cestosNo[k];
      if (!c.length) continue;
      ctx.fillStyle = rgba(cCromo, (k + 0.5) / NIVEIS);
      ctx.beginPath();
      for (let j = 0; j < c.length; j += 4) {
        if (c[j + 3]) continue;
        ctx.moveTo(c[j] + c[j + 2], c[j + 1]);
        ctx.arc(c[j], c[j + 1], c[j + 2], 0, 6.2832);
      }
      ctx.fill();
      ctx.fillStyle = rgba(cAcento, (k + 0.5) / NIVEIS);
      ctx.beginPath();
      for (let j = 0; j < c.length; j += 4) {
        if (!c[j + 3]) continue;
        ctx.moveTo(c[j] + c[j + 2], c[j + 1]);
        ctx.arc(c[j], c[j + 1], c[j + 2], 0, 6.2832);
      }
      ctx.fill();
    }

    // anéis e varredura do instrumento
    const aneis = [R * 1.45, R * 1.66, R * 1.9];
    aneis.forEach((rr, i) => {
      ctx.strokeStyle = rgba(cCromo, (0.06 + i * 0.012) * forca);
      ctx.lineWidth = 0.7;
      ctx.beginPath(); ctx.arc(cx, cy, rr, 0, 6.2832); ctx.stroke();
      const a0 = t * (0.0004 + i * 0.00018) * (i % 2 ? -1 : 1);
      ctx.strokeStyle = rgba(i === 1 ? cAcento : cCromo, (i === 1 ? 0.42 : 0.28) * forca);
      ctx.lineWidth = 1.1;
      ctx.beginPath(); ctx.arc(cx, cy, rr, a0, a0 + 0.5 + i * 0.25); ctx.stroke();
    });
    ctx.strokeStyle = rgba(cCromo, 0.16 * forca);
    ctx.lineWidth = 0.7;
    const marcas = leve ? 36 : 72;
    ctx.beginPath();
    for (let a = 0; a < marcas; a++) {
      const ang = (a / marcas) * 6.2832;
      const r1 = R * 1.9, r2 = r1 + (a % 6 === 0 ? 7 : 3);
      ctx.moveTo(cx + Math.cos(ang) * r1, cy + Math.sin(ang) * r1);
      ctx.lineTo(cx + Math.cos(ang) * r2, cy + Math.sin(ang) * r2);
    }
    ctx.stroke();
    // varredura contida no núcleo
    if (t < T_ATO4) {
      const vao = R * 2.1;
      const sy = ((t * 0.075) % (vao * 2)) - vao + cy;
      const g = ctx.createLinearGradient(0, sy - 22, 0, sy + 22);
      g.addColorStop(0, rgba(cAcento, 0));
      g.addColorStop(0.5, rgba(cAcento, 0.09));
      g.addColorStop(1, rgba(cAcento, 0));
      ctx.save();
      ctx.beginPath(); ctx.arc(cx, cy, R * 1.9, 0, 6.2832); ctx.clip();
      ctx.fillStyle = g;
      ctx.fillRect(cx - vao, sy - 22, vao * 2, 44);
      ctx.strokeStyle = rgba(cAcento, 0.2);
      ctx.lineWidth = 0.8;
      ctx.beginPath(); ctx.moveTo(cx - vao, sy); ctx.lineTo(cx + vao, sy); ctx.stroke();
      ctx.restore();
    }

    /* Posições dos agentes: os pares desenham por baixo, os nós por cima. */
    const nos = anel(cx, cy, R);

    /* ----- Áreas: cada agente ligado aos colegas da mesma área ---------- */
    const fams = familias(agentes);
    fams.forEach((f, iF) => {
      const nasce = T_FAM + iF * PASSO_FAM;
      const k = facilInOut(clamp((t - nasce) / 560, 0, 1));
      if (k <= 0) return;
      f.pares.forEach((par, iP) => {
        const a = nos.find((n) => n.ref.id === par[0]);
        const b = nos.find((n) => n.ref.id === par[1]);
        if (!a || !b) return;
        const arc = arcoEntre(a, b, cx, cy, 0.16);
        ctx.save();
        ctx.lineWidth = 1;
        ctx.strokeStyle = rgba(cAcento, 0.34 * k * forca);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        const passos = 24;
        for (let sN = 1; sN <= passos * k; sN++) {
          const q = pontoNaCurva(a.x, a.y, arc.cx1, arc.cy1, b.x, b.y, sN / passos);
          ctx.lineTo(q.x, q.y);
        }
        ctx.stroke();
        ctx.restore();

        // troca contínua dentro da área
        if (k >= 1) {
          const ciclo = 2200;
          const fase = ((t - nasce - 560 + iP * 480 + iF * 260) % ciclo) / ciclo;
          const pos = pontoNaCurva(a.x, a.y, arc.cx1, arc.cy1, b.x, b.y, fase);
          ctx.fillStyle = rgba(cAcento, 0.8 * Math.sin(fase * Math.PI));
          ctx.beginPath(); ctx.arc(pos.x, pos.y, 1.8, 0, 6.2832); ctx.fill();
        }
      });
    });

    /* ----- Pares de contraprova ----------------------------------------- */
    PARES.forEach((par, i) => {
      const nasce = T_PAR + i * PASSO_PAR;
      const k = facilInOut(clamp((t - nasce) / 620, 0, 1));
      if (k <= 0) return;
      const a = nos.find((n) => n.ref.id === par[0]);
      const b = nos.find((n) => n.ref.id === par[1]);
      if (!a || !b) return;

      const arc = arcoEntre(a, b, cx, cy, 0.42);
      const c1x = arc.cx1, c1y = arc.cy1;

      ctx.save();
      ctx.lineWidth = 1.35;
      ctx.strokeStyle = rgba(cAtencao, 0.55 * k * forca);
      ctx.setLineDash([4, 4]);
      ctx.lineDashOffset = -t * 0.03;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      const passos = 30;
      for (let s = 1; s <= passos * k; s++) {
        const q = pontoNaCurva(a.x, a.y, c1x, c1y, b.x, b.y, s / passos);
        ctx.lineTo(q.x, q.y);
      }
      ctx.stroke();
      ctx.restore();

      if (k >= 1) {
        const fase = ((t - nasce - 620) % 1500) / 1500;
        const pos = pontoNaCurva(a.x, a.y, c1x, c1y, b.x, b.y, fase);
        ctx.fillStyle = rgba(cAtencao, 0.9 * Math.sin(fase * Math.PI));
        ctx.beginPath(); ctx.arc(pos.x, pos.y, 2.4, 0, 6.2832); ctx.fill();
      }
    });

    /* ----- Agentes em volta --------------------------------------------- */
    const fonte = (compacto ? 9 : 10.5) * (compacto ? 1 : esc);
    ctx.font = `600 ${fonte}px ${T['--mono']}`;
    ctx.textBaseline = 'middle';

    nos.forEach((p) => {
      const nasce = T_AG + p.i * PASSO_AG;
      const k = facil((t - nasce) / 620);
      if (k <= 0) return;

      const c = curva(cx, cy, p);
      // trilha núcleo → agente, desenhada progressivamente
      const kt = facilInOut(clamp((t - nasce) / 520, 0, 1));
      ctx.save();
      ctx.lineWidth = 0.9;
      ctx.strokeStyle = rgba(cCromo, 0.2 * k * forca);
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      const passos = 26;
      for (let s = 1; s <= passos * kt; s++) {
        const q = pontoNaCurva(cx, cy, c.cx1, c.cy1, p.x, p.y, s / passos);
        ctx.lineTo(q.x, q.y);
      }
      ctx.stroke();
      ctx.restore();

      // pulso correndo na trilha — o núcleo pede, o agente devolve
      if (kt >= 1) {
        const ciclo = 1900;
        const fase = ((t - nasce - 520) % ciclo) / ciclo;
        const ida = fase < 0.5;
        const u = ida ? fase * 2 : (fase - 0.5) * 2;
        const pos = pontoNaCurva(cx, cy, c.cx1, c.cy1, p.x, p.y, ida ? u : 1 - u);
        const brilho = Math.sin(clamp(u, 0, 1) * Math.PI);
        ctx.fillStyle = rgba(ida ? cAcento : cAtencao, 0.85 * brilho);
        ctx.beginPath(); ctx.arc(pos.x, pos.y, 2.1, 0, 6.2832); ctx.fill();
      }

      // ping de sonar no instante em que acende
      const dtPing = t - nasce;
      if (dtPing >= 0 && dtPing < 900) {
        const kp = dtPing / 900;
        ctx.strokeStyle = rgba(cAcento, 0.42 * (1 - kp));
        ctx.lineWidth = 1.2 * (1 - kp) + 0.3;
        ctx.beginPath(); ctx.arc(p.x, p.y, (4 + kp * 30) * esc, 0, 6.2832); ctx.stroke();
      }

      // nó do agente
      const revisor = p.ref.situacao === 'revisor';
      const cor = revisor ? cAtencao : cAcento;
      const pul = 0.75 + 0.25 * Math.sin(t * 0.0022 + p.i * 1.7);
      ctx.fillStyle = rgba(cor, 0.16 * k);
      ctx.beginPath(); ctx.arc(p.x, p.y, 8 * esc * k * pul, 0, 6.2832); ctx.fill();
      ctx.save();
      if (!leve) { ctx.shadowColor = rgba(cor, 0.85); ctx.shadowBlur = 14 * esc; }
      ctx.fillStyle = rgba(cor, 0.95 * k);
      ctx.beginPath(); ctx.arc(p.x, p.y, 3.2 * esc * k, 0, 6.2832); ctx.fill();
      ctx.restore();

      // Rótulo virado para fora. Ganha um halo da cor do fundo porque os
      // arcos das áreas passam por cima e comeriam a legibilidade do nome.
      ctx.save();
      ctx.textAlign = p.direita ? 'left' : 'right';
      if (!leve) { ctx.shadowColor = rgba(T['--fundo'], 0.95); ctx.shadowBlur = 8 * esc; }
      const dx = (p.direita ? 12 : -12) * esc;
      ctx.fillStyle = rgba(T['--tinta-2'], 0.95 * k);
      ctx.fillText(p.ref.nome, p.x + dx, p.y - (compacto ? 0 : 5 * esc));
      if (!compacto) {
        ctx.font = `400 ${fonte - 1.5}px ${T['--mono']}`;
        ctx.fillStyle = rgba(T['--tinta-3'], 0.95 * k);
        ctx.fillText(p.ref.area, p.x + dx, p.y + 7 * esc);
        ctx.font = `600 ${fonte}px ${T['--mono']}`;
      }
      ctx.restore();
    });

    /* ----- Desfecho: onda de choque e a conta do que ficou armado ------- */
    if (dtRev >= 0 && dtRev < 1500) {
      const ko = facilInOut(clamp(dtRev / 1500, 0, 1));
      const raio = ko * Math.hypot(w, h) * 0.62;
      ctx.strokeStyle = rgba(cAcento, 0.5 * (1 - ko));
      ctx.lineWidth = (3.5 * (1 - ko) + 0.5) * esc;
      ctx.beginPath(); ctx.arc(cx, cy, raio, 0, 6.2832); ctx.stroke();
      ctx.strokeStyle = rgba(cAcento, 0.16 * (1 - ko));
      ctx.lineWidth = 1 * esc;
      ctx.beginPath(); ctx.arc(cx, cy, raio * 0.86, 0, 6.2832); ctx.stroke();
    }
    if (clarao > 0) {
      ctx.save();
      ctx.globalCompositeOperation = claro ? 'multiply' : 'lighter';
      ctx.fillStyle = rgba(cAcento, 0.11 * clarao);
      ctx.fillRect(0, 0, w, h);
      ctx.restore();
    }
    // o log sai um pouco antes, para não disputar espaço com a frase
    if (t >= T_REVELA - 600) logEl.classList.add('recolhido');
    if (dtRev >= 0 && !desfecho.classList.contains('no-ar')) {
      desfecho.textContent =
        `${agentes.length} agentes · ${fams.length} áreas · `
        + `${PARES.length} pares de contraprova · 6 camadas de validação`;
      desfecho.classList.add('no-ar');
    }

    // vinheta: puxa o olho para o centro numa tela grande
    const chaveVin = `${Math.round(w)}|${Math.round(h)}|${claro}`;
    if (chaveVin !== vinhetaChave) {
      vinheta = ctx.createRadialGradient(cx, cy, Math.min(w, h) * 0.28,
        cx, cy, Math.hypot(w, h) * 0.62);
      vinheta.addColorStop(0, rgba(T['--fundo'], 0));
      vinheta.addColorStop(1, rgba(T['--fundo'], claro ? 0.28 : 0.62));
      vinhetaChave = chaveVin;
    }
    ctx.fillStyle = vinheta;
    ctx.fillRect(0, 0, w, h);

    // esmaecimento final
    if (t > T_FIM - 900) {
      const f = clamp((t - (T_FIM - 900)) / 900, 0, 1);
      ctx.fillStyle = rgba(T['--fundo'], f * 0.55);
      ctx.fillRect(0, 0, w, h);
    }

    raf = requestAnimationFrame(quadro);
  }

  raf = requestAnimationFrame(quadro);

  /* ----- Troca de tema recarrega os tokens em uso ------------------------ */
  const obsTema = new MutationObserver(() => {
    T = lerTokens();
    claro = ehClaro(T['--fundo']);
  });
  obsTema.observe(document.documentElement, { attributes: true, attributeFilter: ['data-tema'] });

  /* ----- Encerramento --------------------------------------------------- */
  function destruir() {
    cancelAnimationFrame(raf);
    ro.disconnect();
    obsTema.disconnect();
    if (atual && atual.destruir === destruir) atual = null;
  }

  function terminar() {
    if (encerrado) return;
    encerrado = true;
    destruir();
    try { aoTerminar(); } catch (e) { console.error(e); }
  }

  atual = { pular: terminar, destruir };
  return atual;
}

/** Encerra a abertura em curso, se houver. */
export function pular() {
  if (atual && atual.pular) atual.pular();
}

/** Duração total da sequência, em ms. */
export const DURACAO = T_FIM;
