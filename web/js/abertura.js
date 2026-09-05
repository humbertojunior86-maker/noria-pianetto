/* ==========================================================================
   NÓRIA — sequência de abertura
   --------------------------------------------------------------------------
   Módulo ES sem dependências. Desenha em <canvas> a inicialização do sistema:
   um núcleo ciano pulsante e seis nós satélites (as funções reais da NÓRIA)
   ligados por trilhas curvas por onde correm partículas de luz.

   Quatro atos, ~9 s no total:
     1  isolamento da instância e integridade do banco
     2  acendimento das seis funções, uma a uma
     3  fontes autorizadas (ATUA somente leitura, OFX, acervo)
     4  núcleo em operação — aguardando objetivo

   Uso:
     import { abertura, pular } from './js/abertura.js';
     abertura(document.querySelector('#abertura'), () => { ... });
     botaoPular.onclick = pular;

   Contenção deliberada: poucas partículas, nenhum gradiente berrante.
   A força vem da precisão do movimento.
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

/* ----- As seis funções, na posição do logo ------------------------------ */
/* ang em graus: 0 = direita, cresce no sentido do relógio na tela         */
const FUNCOES = [
  { id: 'dados',        rotulo: 'dados',        ang: -145, icone: 'grafico',  ordem: 0 },
  { id: 'processos',    rotulo: 'processos',    ang: -35,  icone: 'engrenagem', ordem: 1 },
  { id: 'investigacao', rotulo: 'investigação', ang: 180,  icone: 'lupa',     ordem: 2 },
  { id: 'pessoas',      rotulo: 'pessoas',      ang: 0,    icone: 'pessoas',  ordem: 3 },
  { id: 'validacao',    rotulo: 'validação',    ang: 145,  icone: 'visto',    ordem: 4 },
  { id: 'decisao',      rotulo: 'decisão',      ang: 35,   icone: 'visto2',   ordem: 5 }
];

/* ----- Roteiro: tempo (ms) → linha de log ------------------------------- */
const T_ATO2 = 2300;    // início do acendimento das funções
const PASSO = 560;      // intervalo entre funções
const T_ATO3 = T_ATO2 + PASSO * 6 + 240;
const T_ATO4 = T_ATO3 + 1700;
const T_FIM = T_ATO4 + 1100;

const ROTEIRO = [
  { t: 180,  tipo: 'info', txt: 'instância isolada — noria-prod-01' },
  { t: 760,  tipo: 'info', txt: 'cofre de credenciais selado · rede restrita' },
  { t: 1340, tipo: 'ok',   txt: 'integridade do banco verificada — 0 divergências' },
  { t: 2020, tipo: 'info', txt: 'acendendo funções operacionais' },
  ...FUNCOES.slice().sort((a, b) => a.ordem - b.ordem).map((f) => ({
    t: T_ATO2 + f.ordem * PASSO + 200,
    tipo: 'ok',
    txt: `função ${f.rotulo} · ativa`
  })),
  { t: T_ATO3 + 60,   tipo: 'info', txt: 'fontes autorizadas' },
  { t: T_ATO3 + 480,  tipo: 'ok',   txt: 'atua · somente leitura' },
  { t: T_ATO3 + 900,  tipo: 'ok',   txt: 'extrato ofx · conciliação bancária' },
  { t: T_ATO3 + 1320, tipo: 'ok',   txt: 'acervo interno · documentos e evidências' },
  { t: T_ATO4 + 120,  tipo: 'nucleo', txt: 'núcleo em operação — aguardando objetivo' }
].sort((a, b) => a.t - b.t);

const MAX_LINHAS = 7;

/* ----- Utilidades ------------------------------------------------------- */
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const rad = (g) => (g * Math.PI) / 180;
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

/* ----- Instância única (para que `pular()` funcione sem referência) ----- */
let atual = null;

/**
 * Inicia a sequência de abertura dentro de `el`.
 * @param {HTMLElement} el container (recebe o canvas)
 * @param {Function} aoTerminar chamado uma vez, ao fim da sequência
 * @returns {{pular:Function, destruir:Function}}
 */
export function abertura(el, aoTerminar) {
  if (atual) atual.destruir();

  const cv = document.createElement('canvas');
  cv.setAttribute('aria-hidden', 'true');
  cv.style.cssText = 'display:block;width:100%;height:100%';
  el.appendChild(cv);
  const ctx = cv.getContext('2d');

  let tok = lerTokens();
  let W = 0, H = 0, dpr = 1;
  let raf = 0, t0 = 0, agora = 0;
  let terminado = false, saltado = false;
  const reduzido = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* -- dimensionamento ------------------------------------------------- */
  function medir() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    const r = el.getBoundingClientRect();
    W = Math.max(320, Math.round(r.width || window.innerWidth));
    H = Math.max(360, Math.round(r.height || window.innerHeight));
    cv.width = Math.round(W * dpr);
    cv.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function geometria() {
    const m = Math.min(W, H);
    const rNo = clamp(m * 0.036, 15, 30);
    const fsRotulo = clamp(m * 0.0125, 9, 11.5);
    const fsLog = clamp(Math.min(W * 0.011, H * 0.016), 10.5, 13);

    // largura reservada para o rótulo mais longo, para nada sair da tela
    ctx.font = `${fsRotulo}px ${tok['--mono']}`;
    let largRotulo = 0;
    for (const f of FUNCOES) largRotulo = Math.max(largRotulo, ctx.measureText(f.rotulo).width);

    const estreito = W < 700;
    const folga = largRotulo + rNo + (estreito ? 18 : 30);
    const rx = Math.max(88, Math.min(W * (estreito ? 0.36 : 0.33), W / 2 - folga));
    // em telas estreitas a constelação fica mais vertical, para os nós não se colarem
    const ry = Math.min(rx * (estreito ? 1.0 : 0.62), H * 0.23);
    const cy = H * (estreito ? 0.42 : 0.42);

    return { cx: W / 2, cy, rx, ry, rNo, fsRotulo, fsLog, m };
  }

  /* -- desenho dos ícones (traço fino, geométrico) ---------------------- */
  function icone(tipo, x, y, r, cor, alfa) {
    ctx.save();
    ctx.translate(x, y);
    ctx.strokeStyle = rgba(cor, alfa);
    ctx.fillStyle = rgba(cor, alfa);
    ctx.lineWidth = Math.max(1.1, r * 0.075);
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    const u = r * 0.42; // meia-caixa do glifo

    if (tipo === 'grafico') {
      const bw = u * 0.42;
      [[-u * 0.82, u * 0.5], [0, u * 1.0], [u * 0.82, u * 1.55]].forEach(([bx, bh], i) => {
        ctx.fillRect(bx - bw / 2, u * 0.75 - bh, bw, bh);
      });
    } else if (tipo === 'engrenagem') {
      ctx.lineWidth = Math.max(1.4, r * 0.115);
      ctx.beginPath();
      ctx.arc(0, 0, u * 0.72, 0, Math.PI * 2);
      ctx.stroke();
      ctx.lineWidth = Math.max(1.2, r * 0.085);
      for (let i = 0; i < 6; i++) {
        const a = (i / 6) * Math.PI * 2 + 0.26;
        ctx.beginPath();
        ctx.moveTo(Math.cos(a) * u * 0.86, Math.sin(a) * u * 0.86);
        ctx.lineTo(Math.cos(a) * u * 1.12, Math.sin(a) * u * 1.12);
        ctx.stroke();
      }
      ctx.beginPath();
      ctx.arc(0, 0, u * 0.24, 0, Math.PI * 2);
      ctx.fill();
    } else if (tipo === 'lupa') {
      ctx.beginPath();
      ctx.arc(-u * 0.18, -u * 0.18, u * 0.68, 0, Math.PI * 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(u * 0.32, u * 0.32);
      ctx.lineTo(u * 1.05, u * 1.05);
      ctx.stroke();
    } else if (tipo === 'pessoas') {
      const cab = u * 0.30;
      ctx.beginPath();
      ctx.arc(-u * 0.52, -u * 0.34, cab, 0, Math.PI * 2);
      ctx.arc(u * 0.52, -u * 0.34, cab, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.arc(-u * 0.52, u * 0.72, u * 0.56, Math.PI * 1.12, Math.PI * 1.88);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(u * 0.52, u * 0.72, u * 0.56, Math.PI * 1.12, Math.PI * 1.88);
      ctx.stroke();
    } else if (tipo === 'visto' || tipo === 'visto2') {
      const dx = tipo === 'visto2' ? -u * 0.30 : 0;
      ctx.beginPath();
      ctx.moveTo(dx - u * 0.62, 0);
      ctx.lineTo(dx - u * 0.12, u * 0.52);
      ctx.lineTo(dx + u * 0.72, -u * 0.58);
      ctx.stroke();
      if (tipo === 'visto2') {
        ctx.globalAlpha = 0.55;
        ctx.beginPath();
        ctx.moveTo(u * 0.14, 0);
        ctx.lineTo(u * 0.50, u * 0.40);
        ctx.lineTo(u * 1.10, -u * 0.50);
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  /* -- trilha curva núcleo ↔ nó ---------------------------------------- */
  function pontosTrilha(g, f) {
    const a = rad(f.ang);
    const nx = g.cx + Math.cos(a) * g.rx;
    const ny = g.cy + Math.sin(a) * g.ry;
    // controle deslocado perpendicularmente: curva discreta, sempre pra fora
    const mx = (g.cx + nx) / 2;
    const my = (g.cy + ny) / 2;
    const dx = nx - g.cx, dy = ny - g.cy;
    const L = Math.hypot(dx, dy) || 1;
    const lado = Math.sign(Math.cos(a)) || 1;
    const desv = L * 0.16 * (f.ang < 0 ? -1 : 1) * (Math.abs(f.ang) === 180 ? 0.6 : 1);
    const px = mx + (-dy / L) * desv * lado;
    const py = my + (dx / L) * desv * lado;
    return { nx, ny, px, py };
  }

  const naCurva = (t, a, c, b) => {
    const u = 1 - t;
    return u * u * a + 2 * u * t * c + t * t * b;
  };

  /* -- estado de cada função no tempo ----------------------------------- */
  function estadoFuncao(f, t) {
    const inicio = T_ATO2 + f.ordem * PASSO;
    const p = clamp((t - inicio) / 700, 0, 1);
    return { p: facil(p), aceso: p > 0.02, inicio };
  }

  /* -- quadro ----------------------------------------------------------- */
  function quadro(t) {
    const g = geometria();
    const acento = tok['--acento'];
    const cromo = tok['--cromo'];
    const claro = ehClaro(tok['--fundo']);
    const kLinha = claro ? 1.9 : 1;   // traços do metal precisam de mais peso no claro

    // fundo
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = tok['--fundo'];
    ctx.fillRect(0, 0, W, H);

    // véu radial muito discreto atrás do núcleo
    const veu = ctx.createRadialGradient(g.cx, g.cy, 0, g.cx, g.cy, g.rx * 1.9);
    veu.addColorStop(0, rgba(acento, 0.055));
    veu.addColorStop(0.55, rgba(acento, 0.014));
    veu.addColorStop(1, rgba(acento, 0));
    ctx.fillStyle = veu;
    ctx.fillRect(0, 0, W, H);

    // órbita de referência (metal muito fraco)
    const orb = clamp((t - 500) / 900, 0, 1);
    if (orb > 0) {
      ctx.save();
      ctx.strokeStyle = rgba(cromo, 0.06 * kLinha * orb);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.ellipse(g.cx, g.cy, g.rx, g.ry, 0, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }

    // trilhas + nós
    for (const f of FUNCOES) {
      const { nx, ny, px, py } = pontosTrilha(g, f);
      const st = estadoFuncao(f, t);

      // trilha: traço apagado sempre, aceso progressivo
      ctx.lineWidth = 1;
      ctx.strokeStyle = rgba(cromo, 0.10 * kLinha * orb);
      ctx.beginPath();
      ctx.moveTo(g.cx, g.cy);
      ctx.quadraticCurveTo(px, py, nx, ny);
      ctx.stroke();

      if (st.p > 0) {
        // desenha a curva até a fração acesa (do núcleo para fora)
        ctx.save();
        ctx.strokeStyle = rgba(acento, 0.34 + 0.14 * st.p);
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        const passos = 26;
        for (let i = 0; i <= passos * st.p; i++) {
          const u = i / passos;
          const x = naCurva(u, g.cx, px, nx);
          const y = naCurva(u, g.cy, py, ny);
          i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        }
        ctx.stroke();
        ctx.restore();

        // partículas: nó → núcleo → nó (2 por trilha, discretas)
        if (st.p > 0.95 && !reduzido) {
          for (let k = 0; k < 2; k++) {
            const fase = ((t - st.inicio) / 2100 + k * 0.5) % 1;
            const u = fase < 0.5 ? facilInOut(fase * 2) : 1 - facilInOut((fase - 0.5) * 2);
            const uu = 1 - u; // 0 no nó, 1 no núcleo → inverte para ir do nó
            const x = naCurva(uu, g.cx, px, nx);
            const y = naCurva(uu, g.cy, py, ny);
            const brilho = Math.sin(Math.min(1, u * 2) * Math.PI) * 0.9 + 0.1;
            ctx.fillStyle = rgba(acento, 0.85 * brilho);
            ctx.beginPath();
            ctx.arc(x, y, Math.max(1.4, g.rNo * 0.075), 0, Math.PI * 2);
            ctx.fill();
          }
        }
      }

      // nó
      const r = g.rNo;
      const ent = clamp((t - 620 - f.ordem * 60) / 620, 0, 1);
      if (ent <= 0) continue;
      const rr = r * (0.82 + 0.18 * facil(ent));
      ctx.save();
      ctx.globalAlpha = facil(ent);

      ctx.fillStyle = tok['--painel'];
      ctx.beginPath();
      ctx.arc(nx, ny, rr, 0, Math.PI * 2);
      ctx.fill();

      // anel: cromo quando apagado, acento quando aceso
      ctx.lineWidth = 1.2;
      ctx.strokeStyle = rgba(cromo, (0.30 + 0.10 * (1 - st.p)) * (claro ? 1.5 : 1));
      ctx.beginPath();
      ctx.arc(nx, ny, rr, 0, Math.PI * 2);
      ctx.stroke();

      if (st.p > 0) {
        const pulso = reduzido ? 1 : 0.86 + 0.14 * Math.sin(t / 620 + f.ordem);
        ctx.strokeStyle = rgba(acento, 0.68 * st.p * pulso);
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        ctx.arc(nx, ny, rr, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * st.p);
        ctx.stroke();
        // halo mínimo
        ctx.fillStyle = rgba(acento, 0.06 * st.p);
        ctx.beginPath();
        ctx.arc(nx, ny, rr * 1.34, 0, Math.PI * 2);
        ctx.fill();
      }

      icone(f.icone, nx, ny, rr, st.p > 0.35 ? acento : cromo, 0.42 + 0.5 * st.p);
      ctx.restore();

      // rótulo mono minúsculo, radial para fora, preso dentro da tela
      if (st.p > 0.15) {
        const dir = Math.cos(rad(f.ang)) >= 0 ? 1 : -1;
        ctx.save();
        ctx.globalAlpha = clamp((st.p - 0.15) / 0.5, 0, 1);
        ctx.font = `${g.fsRotulo}px ${tok['--mono']}`;
        ctx.textBaseline = 'middle';
        ctx.fillStyle = rgba(tok['--tinta-2'], 0.9);
        const larg = ctx.measureText(f.rotulo).width;
        let x = nx + dir * (rr + 12);
        if (dir > 0) {
          ctx.textAlign = 'left';
          x = Math.min(x, W - 10 - larg);
        } else {
          ctx.textAlign = 'right';
          x = Math.max(x, 10 + larg);
        }
        ctx.fillText(f.rotulo, x, ny);
        ctx.restore();
      }
    }

    // núcleo
    const nasc = facil(clamp(t / 900, 0, 1));
    const pulso = reduzido ? 1 : 1 + 0.06 * Math.sin(t / 700);
    const acesos = FUNCOES.filter((f) => estadoFuncao(f, t).p > 0.9).length;
    const rn = (g.rNo * 0.80 + g.rNo * 0.10 * acesos * 0.6) * nasc * pulso;

    const gl = ctx.createRadialGradient(g.cx, g.cy, 0, g.cx, g.cy, rn * 4.6);
    gl.addColorStop(0, rgba(acento, 0.34 * nasc));
    gl.addColorStop(0.35, rgba(acento, 0.10 * nasc));
    gl.addColorStop(1, rgba(acento, 0));
    ctx.fillStyle = gl;
    ctx.beginPath();
    ctx.arc(g.cx, g.cy, rn * 4.6, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = rgba(claro ? acento : '#EAFFFA', 0.94 * nasc);
    ctx.beginPath();
    ctx.arc(g.cx, g.cy, rn * 0.42, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = rgba(acento, 0.85 * nasc);
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    ctx.arc(g.cx, g.cy, rn, 0, Math.PI * 2);
    ctx.stroke();
    ctx.strokeStyle = rgba(cromo, 0.22 * kLinha * nasc);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(g.cx, g.cy, rn * 1.7, 0, Math.PI * 2);
    ctx.stroke();

    // varredura de integridade (ato 1): arco fino girando uma vez
    if (t < 2000) {
      const v = clamp((t - 300) / 1500, 0, 1);
      ctx.save();
      ctx.strokeStyle = rgba(acento, 0.5 * (1 - v));
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.arc(g.cx, g.cy, g.rNo * 2.4, rad(-90) + v * Math.PI * 2, rad(-90) + v * Math.PI * 2 + 0.9);
      ctx.stroke();
      ctx.restore();
    }

    // estado central (ato 4)
    if (t > T_ATO4) {
      const a = facil((t - T_ATO4) / 700);
      ctx.save();
      ctx.globalAlpha = a;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.font = `${g.fsRotulo * 1.02}px ${tok['--mono']}`;
      ctx.fillStyle = rgba(acento, 0.95);
      ctx.letterSpacing = '0.16em';
      ctx.fillText('NÚCLEO EM OPERAÇÃO', g.cx, g.cy + g.ry + g.rNo + 34);
      ctx.letterSpacing = '0.02em';
      ctx.font = `${g.fsRotulo}px ${tok['--mono']}`;
      ctx.fillStyle = rgba(tok['--tinta-3'], 1);
      ctx.fillText('aguardando objetivo', g.cx, g.cy + g.ry + g.rNo + 34 + g.fsRotulo * 2.1);
      ctx.restore();
    }

    desenhaLog(t, g);
  }

  /* -- log na base ------------------------------------------------------ */
  function desenhaLog(t, g) {
    const visiveis = ROTEIRO.filter((l) => t >= l.t);
    const janela = visiveis.slice(-MAX_LINHAS);
    const fs = g.fsLog;
    const lh = fs * 1.95;
    const pad = clamp(W * 0.035, 20, 64);
    // em telas estreitas o botão "Pular" fica centralizado embaixo: sobe o log
    const base = H - (W < 700 ? 92 : clamp(H * 0.055, 26, 56));

    const claro = ehClaro(tok['--fundo']);

    ctx.save();
    ctx.font = `${fs}px ${tok['--mono']}`;
    ctx.textBaseline = 'alphabetic';
    ctx.textAlign = 'left';

    // filete vertical do bloco de log
    const alturaBloco = lh * (janela.length - 1) + fs;
    if (janela.length) {
      ctx.strokeStyle = rgba(tok['--tinta'], claro ? 0.14 : 0.10);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(pad - 12, base - alturaBloco + 2);
      ctx.lineTo(pad - 12, base + 3);
      ctx.stroke();
    }

    janela.forEach((l, i) => {
      const y = base - lh * (janela.length - 1 - i);
      const idade = visiveis.length - visiveis.indexOf(l) - 1; // 0 = mais nova
      const entrada = clamp((t - l.t) / 320, 0, 1);
      // no tema claro o texto precisa de piso de opacidade mais alto
      const piso = claro ? [1, 0.86, 0.72, 0.6] : [1, 0.72, 0.5, 0.42];
      let alfa = idade <= 2 ? piso[idade]
        : Math.max(claro ? 0.4 : 0.2, piso[3] - (idade - 3) * 0.07);
      alfa *= entrada;

      const cor = l.tipo === 'ok' ? tok['--ok']
        : l.tipo === 'nucleo' ? tok['--acento']
          : tok['--tinta-3'];

      // marcador
      ctx.fillStyle = rgba(cor, alfa * (l.tipo === 'info' ? 0.8 : 1));
      if (l.tipo === 'info') {
        ctx.fillRect(pad, y - fs * 0.34, fs * 0.30, 1.2);
      } else {
        ctx.beginPath();
        ctx.arc(pad + fs * 0.16, y - fs * 0.32, fs * 0.16, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.fillStyle = rgba(l.tipo === 'nucleo' ? tok['--acento'] : tok['--tinta-2'], alfa);
      const txt = l.txt.slice(0, Math.ceil(l.txt.length * clamp((t - l.t) / 260, 0, 1)));
      ctx.fillText(txt, pad + fs * 1.05, y);
    });
    ctx.restore();
  }

  /* -- laço ------------------------------------------------------------- */
  function passo(ts) {
    if (!t0) t0 = ts;
    agora = ts - t0;
    quadro(Math.min(agora, T_FIM));
    if (agora >= T_FIM) return finalizar();
    raf = requestAnimationFrame(passo);
  }

  function finalizar() {
    if (terminado) return;
    terminado = true;
    cancelAnimationFrame(raf);
    raf = 0;
    if (typeof aoTerminar === 'function') aoTerminar();
  }

  function quadroFinal() {
    medir();
    tok = lerTokens();
    quadro(T_FIM);
  }

  function aoRedimensionar() {
    medir();
    if (terminado || saltado) quadro(T_FIM);
    else quadro(Math.min(agora, T_FIM));
  }

  const obs = new ResizeObserver(aoRedimensionar);
  obs.observe(el);

  // troca de tema (data-tema="claro") recarrega os tokens em uso
  const obsTema = new MutationObserver(() => {
    tok = lerTokens();
    if (terminado || saltado) quadro(T_FIM);
  });
  obsTema.observe(document.documentElement, { attributes: true, attributeFilter: ['data-tema', 'class', 'style'] });
  window.addEventListener('resize', aoRedimensionar);

  const ctrl = {
    pular() {
      saltado = true;
      cancelAnimationFrame(raf);
      raf = 0;
      quadroFinal();
      finalizar();
    },
    destruir() {
      cancelAnimationFrame(raf);
      obs.disconnect();
      obsTema.disconnect();
      window.removeEventListener('resize', aoRedimensionar);
      if (cv.parentNode) cv.parentNode.removeChild(cv);
      if (atual === ctrl) atual = null;
    }
  };
  atual = ctrl;

  medir();

  if (reduzido) {
    // movimento reduzido: quadro final estático e pronto
    saltado = true; // qualquer redesenho (resize/tema) mantém o quadro final
    quadro(T_FIM);
    setTimeout(finalizar, 400);
    return ctrl;
  }

  raf = requestAnimationFrame(passo);
  return ctrl;
}

/** Salta para o quadro final e conclui a sequência em andamento. */
export function pular() {
  if (atual) atual.pular();
}

/** Duração nominal da sequência, em ms. */
export const DURACAO = T_FIM;
