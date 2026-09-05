/* ==========================================================================
   CORTEX — o Grafo
   Não é enfeite: cada nó é uma entidade real da Pianetto, com número apurado
   no banco do ATUA, e cada aresta é uma relação que o sistema sabe percorrer.
   ========================================================================== */

export let RETRATO = null;

export async function carregarRetrato() {
  if (RETRATO) return RETRATO;
  const r = await fetch('dados/retrato.json', { cache: 'no-store' });
  if (!r.ok) throw new Error(`retrato.json indisponível (${r.status})`);
  RETRATO = await r.json();
  return RETRATO;
}

const brl = (v) => v >= 1e6
  ? `R$ ${(v / 1e6).toFixed(1).replace('.', ',')} mi`
  : v >= 1e3 ? `R$ ${Math.round(v / 1e3)} mil` : `R$ ${Math.round(v)}`;
const nf = (v) => (v ?? 0).toLocaleString('pt-BR');

const CORES = {
  nucleo: '#e9a23b',
  dominio: '#c9c2b4',
  filial: '#63c9ae',
  cliente: '#8e82f0',
  banco: '#6fa8c7',
  carteira: '#e2564f',
  frota: '#63c9ae',
  rota: '#d9a066',
  alerta: '#e2564f',
};

/* ---------- monta nós e arestas a partir do retrato real ---------- */
export function montaGrafo(R) {
  const nos = [];
  const ar = [];
  const add = (n) => { nos.push(n); return n.id; };
  const lig = (a, b, f = 1) => ar.push({ a, b, f });

  add({ id: 'cortex', rot: 'CÓRTEX', tipo: 'nucleo', r: 26, fixo: true,
        det: [['Fonte', 'ERP ATUA · PostgreSQL'], ['Extração', R.meta.data_extracao],
              ['CT-es no acervo', nf(R.empresa.ctes_validos_total)],
              ['Receita no acervo', brl(R.empresa.receita_total_periodo)]] });

  const doms = [
    { id: 'd_filiais', rot: 'Filiais', n: R.filiais.filter(f => f.ctes_12m > 0).length },
    { id: 'd_clientes', rot: 'Clientes', n: R.concentracao_clientes.clientes_ativos_12m },
    { id: 'd_carteira', rot: 'Carteira', n: R.carteira.a_receber.quantidade + R.carteira.a_pagar.quantidade },
    { id: 'd_bancos', rot: 'Bancos', n: R.contas_bancarias.length },
    { id: 'd_frota', rot: 'Frota', n: R.frota.veiculos_usados_12m },
    { id: 'd_rotas', rot: 'Rotas', n: R.rotas_top.length },
    { id: 'd_alertas', rot: 'Alertas', n: R.alertas.length },
  ];
  doms.forEach(d => {
    add({ id: d.id, rot: d.rot, tipo: 'dominio', r: 13, cont: d.n,
          det: [['Entidades indexadas', nf(d.n)]] });
    lig('cortex', d.id, 1.6);
  });

  /* filiais que efetivamente operaram */
  R.filiais.filter(f => f.ctes_12m > 0).forEach(f => {
    const id = `fil_${f.cd_pessoa_filial}`;
    const curto = f.nome.replace(/PIANETTO TRANSPORTES\s*-*\s*/i, '').replace(/E LOGISTICA LTDA/i, 'Matriz GO').trim() || 'Matriz';
    add({ id, rot: curto, tipo: 'filial', r: 5 + Math.sqrt(f.participacao_receita_pct) * 2.1,
          det: [['Razão social', f.razao_social], ['CT-es 12m', nf(f.ctes_12m)],
                ['Receita 12m', brl(f.receita_12m)], ['Participação', `${f.participacao_receita_pct.toFixed(1)}%`],
                ['Ticket médio', brl(f.ticket_medio)]] });
    lig('d_filiais', id, 1);
  });

  /* maiores pagadores */
  R.clientes_top.slice(0, 8).forEach(c => {
    const id = `cli_${c.cd_pessoa}`;
    add({ id, rot: c.nome.slice(0, 22), tipo: 'cliente', r: 5 + Math.sqrt(c.participacao_receita_pct) * 2.1,
          det: [['Razão social', c.razao_social], ['CT-es 12m', nf(c.ctes_12m)],
                ['Receita 12m', brl(c.receita_12m)], ['Participação', `${c.participacao_receita_pct.toFixed(1)}%`]] });
    lig('d_clientes', id, 1);
  });

  /* contas bancárias */
  R.contas_bancarias.forEach(c => {
    const id = `ban_${c.cd_conta}`;
    const risco = c.conciliados_pct < 90;
    add({ id, rot: `${c.banco.split(' ')[0]} ${c.conta}`, tipo: 'banco', alerta: risco,
          r: 5 + Math.log10(Math.max(c.movimentos, 10)) * 2.4,
          det: [['Banco', c.banco], ['Agência / conta', `${c.agencia} / ${c.conta}`],
                ['Movimentos', nf(c.movimentos)], ['Conciliado', `${c.conciliados_pct.toFixed(1)}%`],
                ['Entradas 90d', brl(c.entradas_90d)], ['Saídas 90d', brl(Math.abs(c.saidas_90d))]] });
    lig('d_bancos', id, 1);
  });

  /* faixas da carteira a receber */
  const fx = R.carteira.a_receber.faixas;
  [['a_vencer', 'A vencer'], ['atraso_1_30', '1 a 30 dias'], ['atraso_31_60', '31 a 60'],
   ['atraso_61_90', '61 a 90'], ['atraso_mais_90', 'Mais de 90']].forEach(([k, rot]) => {
    const f = fx[k]; if (!f) return;
    const id = `car_${k}`;
    add({ id, rot, tipo: 'carteira', alerta: k === 'atraso_mais_90',
          r: 5 + Math.sqrt(f.saldo / 1e6) * 3.4,
          det: [['Títulos', nf(f.quantidade)], ['Saldo em aberto', brl(f.saldo)],
                ['Valor bruto', brl(f.valor_bruto)]] });
    lig('d_carteira', id, 1);
  });

  /* frota */
  [['Veículos usados', R.frota.veiculos_usados_12m, 'em 12 meses, de ' + nf(R.frota.veiculos_total) + ' cadastrados'],
   ['Motoristas', R.frota.motoristas_usados_12m, 'em 12 meses, de ' + nf(R.frota.motoristas_total) + ' cadastrados'],
   ['Manifestos', R.frota.manifestos_12m, 'MDF-e emitidos em 12 meses'],
   ['Cartas-frete', R.frota.cartas_frete_12m, brl(R.frota.valor_cartas_frete_12m) + ' em 12 meses'],
   ['Funcionários', R.frota.funcionarios_ativos, 'ativos de ' + nf(R.frota.funcionarios_total) + ' cadastrados']]
  .forEach(([rot, v, obs], i) => {
    const id = `fro_${i}`;
    add({ id, rot, tipo: 'frota', r: 5 + Math.log10(Math.max(v, 10)) * 2.2,
          det: [['Quantidade', nf(v)], ['Observação', obs]] });
    lig('d_frota', id, 1);
  });

  /* rotas */
  R.rotas_top.slice(0, 8).forEach((r, i) => {
    const id = `rot_${i}`;
    add({ id, rot: `${r.origem} → ${r.destino}`.slice(0, 26), tipo: 'rota',
          r: 4.5 + Math.log10(Math.max(r.ctes_12m, 10)) * 2,
          det: [['CT-es 12m', nf(r.ctes_12m)], ['Receita 12m', brl(r.receita_12m)],
                ['Ticket médio', brl(r.ticket_medio)]] });
    lig('d_rotas', id, 1);
  });

  /* alertas */
  R.alertas.forEach((a, i) => {
    const id = `ale_${i}`;
    add({ id, rot: a.titulo.slice(0, 26), tipo: 'alerta', sev: a.severidade,
          alerta: a.severidade === 'critica',
          r: a.severidade === 'critica' ? 7 : a.severidade === 'atencao' ? 5.5 : 4.5,
          det: [['Severidade', a.severidade], ['Ocorrências', nf(a.quantidade)],
                ['Valor envolvido', brl(a.valor)], ['Leitura', a.descricao || a.explicacao || '—']] });
    lig('d_alertas', id, 1);
  });

  /* pontes reais entre domínios: o que dá sentido ao grafo */
  const motz = nos.find(n => n.tipo === 'cliente' && /MOTZ.*GO/i.test(n.rot));
  const matriz = nos.find(n => n.id === 'fil_2') || nos.find(n => n.tipo === 'filial');
  if (motz && matriz) lig(motz.id, matriz.id, .5);
  const goflux = nos.filter(n => n.tipo === 'banco' && n.alerta);
  const aleGof = nos.find(n => n.tipo === 'alerta' && /GOFLUX/i.test(n.rot));
  if (aleGof) goflux.forEach(g => lig(aleGof.id, g.id, .5));
  const aleCart = nos.find(n => n.tipo === 'alerta' && /90 dias/i.test(n.rot));
  if (aleCart) lig(aleCart.id, 'car_atraso_mais_90', .5);

  return { nos, ar };
}

/* ==========================================================================
   simulação de forças + desenho
   ========================================================================== */
export function iniciaGrafo(canvas, dados, aoClicar) {
  const { nos, ar } = dados;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const ctx = canvas.getContext('2d');
  let W = 0, H = 0;
  const idx = new Map(nos.map((n, i) => [n.id, i]));
  const arI = ar.map(a => ({ a: idx.get(a.a), b: idx.get(a.b), f: a.f }))
                .filter(a => a.a != null && a.b != null);

  /* posição inicial: anéis por profundidade, evita o "novelo" */
  const prof = new Map([['cortex', 0]]);
  arI.forEach(a => {
    const na = nos[a.a], nb = nos[a.b];
    if (na.tipo === 'nucleo') prof.set(nb.id, 1);
    else if (na.tipo === 'dominio' && !prof.has(nb.id)) prof.set(nb.id, 2);
  });
  nos.forEach((n, i) => {
    const p = prof.get(n.id) ?? 2;
    const ang = (i / nos.length) * Math.PI * 2 + (p * 0.7);
    const raio = p === 0 ? 0 : p === 1 ? 130 : 260 + (i % 5) * 22;
    n.x = Math.cos(ang) * raio; n.y = Math.sin(ang) * raio;
    n.vx = 0; n.vy = 0;
  });

  let hover = null, arrasta = null, off = { x: 0, y: 0 }, pan = null, zoom = 1;
  let alfa = 1, raf = null;

  function medir() {
    const r = canvas.getBoundingClientRect();
    W = r.width; H = r.height;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    zoom = Math.min(1, W / 1050);
  }

  function passo() {
    /* repulsão */
    for (let i = 0; i < nos.length; i++) {
      for (let j = i + 1; j < nos.length; j++) {
        const a = nos[i], b = nos[j];
        let dx = b.x - a.x, dy = b.y - a.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) { d2 = 1; dx = Math.random() - .5; dy = Math.random() - .5; }
        if (d2 > 260000) continue;
        const d = Math.sqrt(d2);
        const fr = (2600 + (a.r + b.r) * 90) / d2;
        const ux = dx / d, uy = dy / d;
        a.vx -= ux * fr; a.vy -= uy * fr;
        b.vx += ux * fr; b.vy += uy * fr;
      }
    }
    /* molas */
    arI.forEach(l => {
      const a = nos[l.a], b = nos[l.b];
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.hypot(dx, dy) || 1;
      const alvo = a.tipo === 'nucleo' || b.tipo === 'nucleo' ? 150 : 118;
      const fs = (d - alvo) * 0.014 * l.f;
      const ux = dx / d, uy = dy / d;
      a.vx += ux * fs; a.vy += uy * fs;
      b.vx -= ux * fs; b.vy -= uy * fs;
    });
    /* centro + amortecimento */
    nos.forEach(n => {
      if (n.fixo) { n.x = 0; n.y = 0; n.vx = 0; n.vy = 0; return; }
      if (n === arrasta) return;
      n.vx -= n.x * 0.0016; n.vy -= n.y * 0.0026;
      n.vx *= 0.86; n.vy *= 0.86;
      const vmax = 9;
      n.vx = Math.max(-vmax, Math.min(vmax, n.vx));
      n.vy = Math.max(-vmax, Math.min(vmax, n.vy));
      n.x += n.vx * alfa; n.y += n.vy * alfa;
    });
    alfa = Math.max(0.18, alfa * 0.997);
  }

  const cx = () => W / 2 + off.x, cy = () => H / 2 + off.y;
  const px = (n) => cx() + n.x * zoom, py = (n) => cy() + n.y * zoom;

  function desenha() {
    ctx.clearRect(0, 0, W, H);

    /* arestas */
    arI.forEach(l => {
      const a = nos[l.a], b = nos[l.b];
      const ax = px(a), ay = py(a), bx = px(b), by = py(b);
      const forte = hover && (hover === a || hover === b);
      ctx.strokeStyle = forte ? 'rgba(233,162,59,.55)' : 'rgba(236,228,214,.085)';
      ctx.lineWidth = forte ? 1.1 : 0.7;
      ctx.beginPath();
      const mx = (ax + bx) / 2, my = (ay + by) / 2;
      const nx = -(by - ay) * 0.09, ny = (bx - ax) * 0.09;
      ctx.moveTo(ax, ay);
      ctx.quadraticCurveTo(mx + nx, my + ny, bx, by);
      ctx.stroke();
    });

    /* nós */
    nos.forEach(n => {
      const x = px(n), y = py(n), r = n.r * zoom;
      const cor = CORES[n.tipo] || '#9d978b';
      const foco = hover === n;

      if (n.tipo === 'nucleo' || foco || n.alerta) {
        const g = ctx.createRadialGradient(x, y, 0, x, y, r * (n.tipo === 'nucleo' ? 4.6 : 3.2));
        g.addColorStop(0, n.alerta && !foco ? 'rgba(226,86,79,.3)' : 'rgba(233,162,59,.28)');
        g.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(x, y, r * (n.tipo === 'nucleo' ? 4.6 : 3.2), 0, 7); ctx.fill();
      }

      ctx.beginPath(); ctx.arc(x, y, r, 0, 7);
      ctx.fillStyle = n.tipo === 'nucleo' ? cor : foco ? cor : cor + '2e';
      ctx.fill();
      ctx.lineWidth = foco ? 1.6 : 1;
      ctx.strokeStyle = foco ? '#f1ece1' : cor + (n.tipo === 'dominio' ? 'cc' : '88');
      ctx.stroke();

      /* rótulos: núcleo e domínios sempre; folhas só no hover ou se grandes */
      const mostra = n.tipo === 'nucleo' || n.tipo === 'dominio' || foco || n.r > 9;
      if (!mostra) return;
      const grande = n.tipo === 'nucleo';
      ctx.font = grande
        ? `600 ${13 * zoom + 1}px 'Cabinet Grotesk', sans-serif`
        : n.tipo === 'dominio'
          ? `500 ${11.5}px 'Satoshi', sans-serif`
          : `400 ${10.5}px 'Satoshi', sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      const txt = grande ? n.rot : n.rot;
      const ty = y + r + 6;
      if (foco || n.tipo === 'dominio' || grande) {
        const w = ctx.measureText(txt).width;
        ctx.fillStyle = 'rgba(8,8,11,.78)';
        ctx.fillRect(x - w / 2 - 4, ty - 2, w + 8, 15);
      }
      ctx.fillStyle = grande ? '#f1ece1' : n.tipo === 'dominio' ? '#c9c2b4' : foco ? '#f1ece1' : '#6b665d';
      ctx.fillText(txt, x, ty);
      if (n.cont != null) {
        ctx.font = `500 10px 'JetBrains Mono', monospace`;
        ctx.fillStyle = '#6b665d';
        ctx.fillText(nf(n.cont), x, ty + 15);
      }
    });
  }

  function laco() {
    passo(); desenha();
    raf = requestAnimationFrame(laco);
  }

  function achaEm(mx, my) {
    let melhor = null, dmin = 22;
    nos.forEach(n => {
      const d = Math.hypot(px(n) - mx, py(n) - my) - n.r * zoom;
      if (d < dmin) { dmin = d; melhor = n; }
    });
    return melhor;
  }

  const tip = canvas.parentElement.querySelector('.grafo-tip');
  function mostraTip(n, mx, my) {
    if (!tip) return;
    if (!n) { tip.classList.remove('on'); return; }
    tip.innerHTML = `<b>${n.rot}</b>` +
      n.det.map(([k, v]) => `<div><span class="l">${k}:</span> ${v}</div>`).join('');
    tip.classList.add('on');
    const r = canvas.getBoundingClientRect();
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.min(Math.max(mx + 14, 6), r.width - w - 6) + 'px';
    tip.style.top = Math.min(Math.max(my - h - 10, 6), r.height - h - 6) + 'px';
  }

  canvas.addEventListener('mousemove', e => {
    const r = canvas.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    if (arrasta) { arrasta.x = (mx - cx()) / zoom; arrasta.y = (my - cy()) / zoom; alfa = Math.max(alfa, .5); return; }
    if (pan) { off.x = pan.ox + (mx - pan.mx); off.y = pan.oy + (my - pan.my); return; }
    const n = achaEm(mx, my);
    if (n !== hover) { hover = n; canvas.style.cursor = n ? 'pointer' : 'grab'; }
    mostraTip(n, mx, my);
  });
  canvas.addEventListener('mousedown', e => {
    const r = canvas.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    const n = achaEm(mx, my);
    if (n && !n.fixo) arrasta = n;
    else pan = { mx, my, ox: off.x, oy: off.y };
  });
  window.addEventListener('mouseup', () => {
    if (arrasta) { arrasta.vx = 0; arrasta.vy = 0; }
    arrasta = null; pan = null;
  });
  canvas.addEventListener('mouseleave', () => mostraTip(null));
  canvas.addEventListener('click', e => {
    const r = canvas.getBoundingClientRect();
    const n = achaEm(e.clientX - r.left, e.clientY - r.top);
    if (n && aoClicar) aoClicar(n);
  });

  medir();
  for (let i = 0; i < 220; i++) passo();
  alfa = 0.5;
  laco();

  const ro = new ResizeObserver(() => { medir(); });
  ro.observe(canvas);

  return { parar() { cancelAnimationFrame(raf); ro.disconnect(); } };
}

/* ==========================================================================
   tela do Córtex
   ========================================================================== */
let sim = null;

export function viewCortex() {
  return `
    <div class="secao" style="border:none;padding-bottom:0;margin-bottom:22px">
      <div style="flex:1;min-width:280px">
        <p class="eyebrow" style="margin-bottom:10px">O que o sistema sabe</p>
        <h3 style="font-size:var(--t-2xl);max-width:20ch;margin-bottom:8px">O Córtex da Pianetto</h3>
        <p class="lede" style="max-width:64ch">
          Cada ponto é uma entidade real, lida do ERP ATUA. Arraste, aproxime, clique.
          Nenhum número aqui foi estimado.
        </p>
      </div>
      <div id="cxMeta" style="min-width:210px"></div>
    </div>

    <div class="grafo-wrap" style="margin-bottom:26px">
      <canvas id="cxCanvas" style="height:min(66vh,620px)"></canvas>
      <div class="grafo-hud">
        <p class="eyebrow">Grafo de conhecimento</p>
        <p class="t" id="cxTitulo">carregando o acervo…</p>
      </div>
      <div class="grafo-legenda">
        <span><i class="dot" style="background:#e9a23b"></i>núcleo</span>
        <span><i class="dot" style="background:#63c9ae"></i>filial e frota</span>
        <span><i class="dot" style="background:#8e82f0"></i>cliente</span>
        <span><i class="dot" style="background:#6fa8c7"></i>banco</span>
        <span><i class="dot" style="background:#e2564f"></i>carteira e alerta</span>
      </div>
      <div class="grafo-tip"></div>
    </div>

    <div id="cxPaineis"></div>
  `;
}

const _brl = (v) => v >= 1e6
  ? `R$ ${(v / 1e6).toFixed(1).replace('.', ',')} mi`
  : v >= 1e3 ? `R$ ${Math.round(v / 1e3)} mil` : `R$ ${Math.round(v || 0)}`;

function paineis(R) {
  const ar = R.carteira.a_receber, ap = R.carteira.a_pagar;
  const crit = R.alertas.filter(a => a.severidade === 'critica');
  const men = R.faturamento_mensal.slice(-12);
  const maxR = Math.max(...men.map(m => m.receita));

  const barras = men.map(m => {
    const h = (m.receita / maxR * 100).toFixed(1);
    const [, mm] = m.mes.split('-');
    return `<div style="display:grid;gap:6px;justify-items:center">
      <div style="height:104px;display:flex;align-items:flex-end">
        <div title="${m.mes} · ${_brl(m.receita)}" style="width:22px;height:${h}%;min-height:2px;
          background:linear-gradient(180deg,rgba(233,162,59,.85),rgba(233,162,59,.22));border-radius:3px 3px 0 0"></div>
      </div>
      <span class="mono" style="font-size:9.5px;color:var(--ink-4)">${mm}</span>
    </div>`;
  }).join('');

  return `
    <div class="secao"><h3>Retrato apurado</h3>
      <p class="lede">Os números que o Córtex leu sozinho, sem ninguém digitar nada</p>
      <span class="cont">extração ${R.meta.data_extracao}</span></div>

    <div class="grid g-4" style="margin-bottom:16px">
      <div class="metric"><span class="eyebrow">Receita 12 meses</span>
        <div class="v amber">${_brl(R.receita_12m_total)}</div>
        <p class="d">${(R.faturamento_mensal.reduce((s, m) => s + m.ctes, 0)).toLocaleString('pt-BR')} CT-es no acervo de 24 meses</p></div>
      <div class="metric"><span class="eyebrow">A receber vencido</span>
        <div class="v crit">${_brl(ar.vencido)}</div>
        <p class="d">${ar.vencido_pct.toFixed(1)}% da carteira · ${ar.quantidade_vencida.toLocaleString('pt-BR')} títulos</p></div>
      <div class="metric"><span class="eyebrow">A pagar em aberto</span>
        <div class="v">${_brl(ap.total_aberto)}</div>
        <p class="d">${(100 - ap.vencido_pct).toFixed(1)}% ainda a vencer</p></div>
      <div class="metric"><span class="eyebrow">Concentração top 5</span>
        <div class="v crit">${R.concentracao_clientes.top5_pct.toFixed(1)}%</div>
        <p class="d">de ${R.concentracao_clientes.clientes_ativos_12m} pagadores ativos</p></div>
    </div>

    <div class="grid g-main" style="margin-bottom:16px">
      <div class="panel">
        <h>Receita mensal <span class="eyebrow">últimos 12 meses</span></h>
        <div class="body">
          <div style="display:flex;justify-content:space-between;align-items:flex-end;gap:4px">${barras}</div>
          <p class="hint" style="margin-top:14px;border-top:1px solid var(--line);padding-top:12px">
            Margem apurada caiu de ${men[0].margem_pct?.toFixed(1) ?? '—'}% para ${men.at(-1).margem_pct?.toFixed(1) ?? '—'}%
            no período. Custo vem da carta-frete, porque <span class="mono">ctrc.vl_custo</span> está sem uso no ERP.
          </p>
        </div>
      </div>
      <div class="panel">
        <h>Achados críticos <span class="eyebrow">${crit.length}</span></h>
        <div class="body">
          ${crit.map(a => `<div class="ev">
            <span class="dot crit"></span>
            <div class="t">${a.titulo}<small>${(a.quantidade || 0).toLocaleString('pt-BR')} ocorrências</small></div>
            <div class="n" style="color:var(--crit)">${_brl(a.valor)}</div>
          </div>`).join('')}
        </div>
      </div>
    </div>

    <div class="grid g-2">
      <div class="panel"><h>Filiais que operaram <span class="eyebrow">12 meses</span></h>
        <div class="body"><table class="tab">
          <thead><tr><th>Filial</th><th class="n">CT-es</th><th class="n">Receita</th><th class="n">Part.</th></tr></thead>
          <tbody>${R.filiais.filter(f => f.ctes_12m > 0).map(f => `<tr>
            <td>${f.nome.replace(/PIANETTO TRANSPORTES\s*-*\s*/i, '').replace(/E LOGISTICA LTDA/i, 'Matriz GO')}</td>
            <td class="n">${f.ctes_12m.toLocaleString('pt-BR')}</td>
            <td class="n">${_brl(f.receita_12m)}</td>
            <td class="n">${f.participacao_receita_pct.toFixed(1)}%</td></tr>`).join('')}</tbody>
        </table></div></div>
      <div class="panel"><h>Contas bancárias <span class="eyebrow">conciliação</span></h>
        <div class="body"><table class="tab">
          <thead><tr><th>Banco</th><th class="n">Movimentos</th><th class="n">Conciliado</th></tr></thead>
          <tbody>${R.contas_bancarias.map(c => `<tr>
            <td>${c.banco}<br><span class="mono" style="font-size:10.5px;color:var(--ink-3)">ag ${c.agencia} · cc ${c.conta}</span></td>
            <td class="n">${c.movimentos.toLocaleString('pt-BR')}</td>
            <td class="n" style="color:${c.conciliados_pct < 90 ? 'var(--crit)' : 'var(--teal)'}">${c.conciliados_pct.toFixed(1)}%</td></tr>`).join('')}</tbody>
        </table></div></div>
    </div>
  `;
}

export async function ligaCortex(abreNo) {
  const cv = document.querySelector('#cxCanvas');
  if (!cv) return;
  try {
    const R = await carregarRetrato();
    if (!document.querySelector('#cxCanvas')) return;
    document.querySelector('#cxTitulo').textContent =
      `${R.empresa.razao_social.split(' ').slice(0, 2).join(' ')} · ${R.empresa.filiais_ativas} filiais`;
    document.querySelector('#cxMeta').innerHTML = `
      <p class="eyebrow" style="margin-bottom:8px">Acervo indexado</p>
      <p class="num" style="font-size:var(--t-xl);letter-spacing:-.04em">${R.empresa.ctes_validos_total.toLocaleString('pt-BR')}</p>
      <p class="hint">conhecimentos de transporte válidos, de ${R.empresa.periodo_dados.inicio.split('-').reverse().join('/')}
      a ${R.empresa.periodo_dados.fim.split('-').reverse().join('/')}</p>`;
    const dados = montaGrafo(R);
    if (sim) sim.parar();
    sim = iniciaGrafo(cv, dados, abreNo);
    document.querySelector('#cxPaineis').innerHTML = paineis(R);
  } catch (e) {
    document.querySelector('#cxTitulo').textContent = 'falha ao ler o acervo';
    document.querySelector('#cxPaineis').innerHTML =
      `<p class="erros">Não foi possível carregar <b>dados/retrato.json</b>: ${e.message}</p>`;
  }
}

export function drawerNo(n) {
  return `<header>
      <div style="flex:1"><span class="eyebrow">${n.tipo}</span><h4>${n.rot}</h4></div>
      <button class="close" data-close aria-label="Fechar">✕</button>
    </header>
    <div class="content">
      <div class="dsec">
        ${n.det.map(([k, v]) => `<div class="ev"><div class="t">${k}</div><div class="n">${v}</div></div>`).join('')}
      </div>
      <div class="dsec"><span class="eyebrow">Origem do dado</span>
        <p>Apurado diretamente no banco do ERP ATUA em ${RETRATO?.meta?.data_extracao ?? '—'},
           por consulta somente leitura. A consulta usada está registrada em <span class="mono">dados/EXTRACAO.md</span>.</p></div>
    </div>
    <footer><button class="btn primary" data-act="Varredura enfileirada para esta entidade">Varrer entidade</button>
    <button class="btn" data-act="Artefato solicitado">Emitir artefato</button></footer>`;
}
