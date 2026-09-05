// CORTEX — sequência de inicialização e malha neural procedural
const AMBER = [240, 180, 41];
const STEEL = [111, 168, 199];

function makeCloud(n, seed = 7) {
  let s = seed;
  const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
  const pts = [];
  for (let i = 0; i < n; i++) {
    const side = i % 2 === 0 ? 1 : -1;
    const u = rnd() * 2 - 1;
    const t = rnd() * Math.PI * 2;
    const r = Math.sqrt(1 - u * u);
    let x = r * Math.cos(t), y = u, z = r * Math.sin(t);
    // deforma em lobos cerebrais
    const fold = 0.14 * Math.sin(y * 9 + z * 5) + 0.1 * Math.sin(x * 7 - y * 4);
    const scale = 1 + fold;
    x *= scale * 0.62; y *= scale * 0.78; z *= scale * 0.86;
    x = side * (Math.abs(x) + 0.16); // separa hemisférios
    // achata a base e alonga a frente
    if (y < -0.45) y = -0.45 + (y + 0.45) * 0.45;
    z *= 1 + 0.16 * Math.max(0, y);
    const d = Math.hypot(x, y, z);
    pts.push({ x, y, z, d, seed: rnd() });
  }
  // tronco encefálico
  for (let i = 0; i < Math.round(n * 0.07); i++) {
    const k = i / (n * 0.07);
    pts.push({ x: (rnd() - 0.5) * 0.12, y: -0.5 - k * 0.5, z: (rnd() - 0.5) * 0.14 + 0.05, d: 1, seed: rnd() });
  }
  return pts;
}

function makeEdges(pts, k = 2, maxLen = 0.34) {
  const edges = [];
  for (let i = 0; i < pts.length; i += 1) {
    const cand = [];
    for (let j = i + 1; j < Math.min(pts.length, i + 90); j++) {
      const dx = pts[i].x - pts[j].x, dy = pts[i].y - pts[j].y, dz = pts[i].z - pts[j].z;
      const l = Math.hypot(dx, dy, dz);
      if (l < maxLen) cand.push([l, j]);
    }
    cand.sort((a, b) => a[0] - b[0]);
    for (let m = 0; m < Math.min(k, cand.length); m++) edges.push([i, cand[m][1], cand[m][0]]);
  }
  return edges;
}

export function createBrain(canvas, opts = {}) {
  const ctx = canvas.getContext('2d');
  const count = opts.count || 900;
  const pts = makeCloud(count);
  const edges = makeEdges(pts, opts.k || 2);
  let w = 0, h = 0, dpr = Math.min(window.devicePixelRatio || 1, 2);
  let raf, t0 = performance.now();
  const state = { progress: opts.progress ?? 1, spin: opts.spin ?? 0.00022, scale: opts.scale ?? 0.34, hud: opts.hud !== false };

  function size() {
    const r = canvas.getBoundingClientRect();
    w = Math.max(1, r.width); h = Math.max(1, r.height);
    canvas.width = w * dpr; canvas.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  size();
  const ro = new ResizeObserver(size); ro.observe(canvas);

  function frame(now) {
    const t = (now - t0);
    const ry = t * state.spin * 6.2;
    const rx = Math.sin(t * 0.00018) * 0.22;
    const cx = w / 2, cy = h / 2;
    const R = Math.min(w, h) * state.scale;
    ctx.clearRect(0, 0, w, h);

    const P = state.progress;
    const proj = pts.map((p, i) => {
      const cosY = Math.cos(ry), sinY = Math.sin(ry);
      let x = p.x * cosY - p.z * sinY;
      let z = p.x * sinY + p.z * cosY;
      let y = p.y * Math.cos(rx) - z * Math.sin(rx);
      z = p.y * Math.sin(rx) + z * Math.cos(rx);
      const persp = 2.6 / (2.6 + z);
      const on = p.seed < P + 0.001;
      const puls = 0.6 + 0.4 * Math.sin(t * 0.0016 + p.seed * 22);
      return { X: cx + x * R * persp, Y: cy - y * R * persp, z, persp, on, puls };
    });

    // halo central
    if (state.hud) {
      const gl = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 1.5);
      gl.addColorStop(0, 'rgba(240,180,41,.07)');
      gl.addColorStop(0.45, 'rgba(111,168,199,.035)');
      gl.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = gl;
      ctx.fillRect(cx - R * 1.6, cy - R * 1.6, R * 3.2, R * 3.2);
    }

    // conexões
    ctx.lineWidth = 0.65;
    for (let e = 0; e < edges.length; e++) {
      const a = proj[edges[e][0]], b = proj[edges[e][1]];
      if (!a || !b || !a.on || !b.on) continue;
      const depth = (a.z + b.z) / 2;
      const alpha = (0.2 + 0.42 * (1 - (depth + 1) / 2)) * (0.55 + 0.45 * a.puls);
      const c = e % 9 === 0 ? AMBER : STEEL;
      ctx.strokeStyle = `rgba(${c[0]},${c[1]},${c[2]},${alpha.toFixed(3)})`;
      ctx.beginPath(); ctx.moveTo(a.X, a.Y); ctx.lineTo(b.X, b.Y); ctx.stroke();
    }
    // nós
    for (let i = 0; i < proj.length; i++) {
      const p = proj[i];
      if (!p.on) continue;
      const hot = i % 23 === 0;
      const rad = (hot ? 1.9 : 1.05) * p.persp * (0.7 + 0.5 * p.puls);
      const c = hot ? AMBER : STEEL;
      const a = (hot ? 0.95 : 0.66) * (0.5 + 0.5 * (1 - (p.z + 1) / 2));
      ctx.fillStyle = `rgba(${c[0]},${c[1]},${c[2]},${a.toFixed(3)})`;
      ctx.beginPath(); ctx.arc(p.X, p.Y, rad, 0, 6.2832); ctx.fill();
    }

    if (state.hud) {
      // anéis e varredura
      const rings = [R * 1.3, R * 1.5, R * 1.72];
      rings.forEach((rr, i) => {
        ctx.strokeStyle = `rgba(150,180,200,${0.07 + i * 0.015})`;
        ctx.lineWidth = 0.7;
        ctx.beginPath(); ctx.arc(cx, cy, rr, 0, 6.2832); ctx.stroke();
        const a0 = t * (0.0004 + i * 0.00018) * (i % 2 ? -1 : 1);
        ctx.strokeStyle = i === 1 ? `rgba(240,180,41,.5)` : `rgba(111,168,199,.35)`;
        ctx.lineWidth = 1.1;
        ctx.beginPath(); ctx.arc(cx, cy, rr, a0, a0 + 0.5 + i * 0.25); ctx.stroke();
      });
      // ticks
      ctx.strokeStyle = 'rgba(150,180,200,.18)';
      for (let a = 0; a < 72; a++) {
        const ang = (a / 72) * 6.2832;
        const r1 = R * 1.72, r2 = r1 + (a % 6 === 0 ? 7 : 3);
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(ang) * r1, cy + Math.sin(ang) * r1);
        ctx.lineTo(cx + Math.cos(ang) * r2, cy + Math.sin(ang) * r2);
        ctx.stroke();
      }
      // varredura horizontal restrita ao núcleo
      const span = R * 1.9;
      const sy = ((t * 0.075) % (span * 2)) - span + cy;
      const g = ctx.createLinearGradient(0, sy - 22, 0, sy + 22);
      g.addColorStop(0, 'rgba(240,180,41,0)');
      g.addColorStop(0.5, 'rgba(240,180,41,.09)');
      g.addColorStop(1, 'rgba(240,180,41,0)');
      ctx.save();
      ctx.beginPath(); ctx.arc(cx, cy, R * 1.72, 0, 6.2832); ctx.clip();
      ctx.fillStyle = g;
      ctx.fillRect(cx - span, sy - 22, span * 2, 44);
      ctx.strokeStyle = 'rgba(240,180,41,.22)';
      ctx.lineWidth = 0.8;
      ctx.beginPath(); ctx.moveTo(cx - span, sy); ctx.lineTo(cx + span, sy); ctx.stroke();
      ctx.restore();
    }
    raf = requestAnimationFrame(frame);
  }
  raf = requestAnimationFrame(frame);
  return {
    set progress(v) { state.progress = v; },
    get progress() { return state.progress; },
    destroy() { cancelAnimationFrame(raf); ro.disconnect(); },
  };
}

const LOG = [
  ['Instância isolada cortex-prod-01 — região gru-1', 'ok'],
  ['Cofre de credenciais aberto · rotação 24h', 'ok'],
  ['Ledger append-only verificado — 1.284.907 blocos íntegros', 'ok'],
  ['Conectando ATUA / Mais Frete · réplica somente leitura', ''],
  ['ATUA sincronizado — delta de 15 min aplicado', 'ok'],
  ['Extratos bancários: BB, Sicredi, Itaú, Bradesco', ''],
  ['Bradesco em CNAB retorno — última carga 04/09 19:40', 'hi'],
  ['SEFAZ · DFe autorizado — CT-e, MDF-e e eventos', 'ok'],
  ['Power BI, X7 Bank, Gobrax, T4S, Weeke, SGI conectados', 'ok'],
  ['Carregando dicionário semântico · 412 conceitos', ''],
  ['Memória episódica: 3.918 casos históricos indexados', 'ok'],
  ['Ativando 14 agentes de área + 6 transversais', ''],
  ['Advogado do Diabo em prontidão — quorum de 2 fontes', 'hi'],
  ['Detectores: 118 ativos · 6 suspensos por baixa precisão', 'ok'],
  ['Varredura das 18 etapas da cadeia de valor', ''],
  ['1.487 sinais processados · 61 hipóteses ativas', 'ok'],
  ['Conciliação ATUA × bancos não fechou em 04/09', 'hi'],
  ['R$ 1.284.730 em risco · 4 casos críticos aguardam decisão', 'hi'],
  ['CORTEX ONLINE', 'ok'],
];

export function runBoot(onDone) {
  const el = document.getElementById('boot');
  const brain = createBrain(document.getElementById('bootCanvas'), { count: 1500, k: 3, progress: 0, scale: 0.29 });
  const logEl = document.getElementById('bootLog');
  const barEl = document.getElementById('bootBar');
  const pctEl = document.getElementById('bootPct');
  let i = 0, killed = false;

  const step = () => {
    if (killed) return;
    if (i >= LOG.length) { setTimeout(finish, 620); return; }
    const [txt, cls] = LOG[i];
    const d = document.createElement('div');
    d.className = cls;
    d.textContent = `${String(i + 1).padStart(2, '0')} › ${txt}`;
    logEl.appendChild(d);
    if (logEl.children.length > 8) logEl.removeChild(logEl.firstChild);
    i++;
    const p = i / LOG.length;
    brain.progress = Math.min(1, p * 1.05);
    barEl.style.right = `${(1 - p) * 100}%`;
    pctEl.textContent = `${String(Math.round(p * 100)).padStart(3, '0')}%`;
    setTimeout(step, i < 4 ? 300 : 230 + Math.random() * 190);
  };

  function finish() {
    if (killed) return;
    killed = true;
    el.classList.add('done');
    setTimeout(() => { el.remove(); brain.destroy(); }, 780);
    onDone();
  }

  document.getElementById('bootSkip').addEventListener('click', finish);
  setTimeout(step, 380);
}
