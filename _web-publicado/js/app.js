import { runBoot, createBrain } from './boot.js';
import { META, PULSO, ETAPAS, AGENTES, CASOS, CONCILIACAO, CONFRONTOS, ROTINAS, ENTREGAVEIS, FLUXO, INTEGRACOES } from './data.js';
import { viewArquivos, ingerir, carregarExemplos, limpar, ligaArquivos, drawerArqDivergencia, ARQ } from './arquivos.js';
import { viewEspecialistas, drawerEspecialista, ESPECIALISTAS } from './especialistas.js';
import { viewCortex, ligaCortex, drawerNo } from './grafo.js';

/* ---------- helpers ---------- */
const brl = (v, c = 0) => v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: c, maximumFractionDigits: c });
const kbrl = (v) => v >= 1e6 ? `R$ ${(v / 1e6).toFixed(2).replace('.', ',')} mi` : `R$ ${Math.round(v / 1000)} mil`;
const pct = (v, d = 0) => `${(v * 100).toFixed(d).replace('.', ',')}%`;
const $ = (s) => document.querySelector(s);
const saudeCls = (s) => s >= 80 ? 'ok' : s >= 60 ? 'warn' : 'crit';
const nivelChip = (n) => ['', 'Informativo', 'Cobrança', 'Caso', 'Bloqueio', 'CEO'][n];

function sparkline(vals, color = 'var(--steel)') {
  const w = 100, h = 26, min = Math.min(...vals), max = Math.max(...vals);
  const d = vals.map((v, i) => `${i === 0 ? 'M' : 'L'}${(i / (vals.length - 1) * w).toFixed(1)},${(h - ((v - min) / (max - min || 1)) * (h - 4) - 2).toFixed(1)}`).join(' ');
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><path d="${d}" fill="none" stroke="${color}" stroke-width="1.2" vector-effect="non-scaling-stroke"/></svg>`;
}

const ICON = {
  ceo: '<path d="M3 3v18h18"/><path d="M7 15l4-5 3 3 5-7"/>',
  conc: '<path d="M3 7h13l-3-3"/><path d="M21 17H8l3 3"/>',
  cadeia: '<rect x="3" y="4" width="7" height="6" rx="1"/><rect x="14" y="14" width="7" height="6" rx="1"/><path d="M10 7h4a3 3 0 013 3v4"/>',
  agentes: '<circle cx="12" cy="12" r="3"/><circle cx="5" cy="6" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="5" cy="18" r="2"/><circle cx="19" cy="18" r="2"/><path d="M7 7l3 3m4 0l3-3M7 17l3-3m4 0l3 3"/>',
  confronto: '<path d="M4 5h7v14H4z"/><path d="M13 5h7v14h-7z"/><path d="M11 12h2"/>',
  rotinas: '<path d="M9 11l2 2 4-4"/><rect x="3" y="4" width="18" height="16" rx="2"/>',
  integra: '<path d="M12 3v6m0 6v6M3 12h6m6 0h6"/><circle cx="12" cy="12" r="3"/>',
  arquivo: '<path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8z"/><path d="M14 3v5h5"/><path d="M9 15l2.5-2.5L14 15"/><path d="M11.5 12.5V18"/>',
  cortex: '<circle cx="12" cy="12" r="2.6"/><circle cx="5" cy="6" r="1.6"/><circle cx="19" cy="7" r="1.6"/><circle cx="6" cy="18" r="1.6"/><circle cx="18" cy="17" r="1.6"/><path d="M6.3 7.1l3.6 3.4M17.6 8.2l-3.8 2.4M7.2 16.8l3.2-2.9M16.6 15.9l-2.9-2"/>',
  espec: '<circle cx="9" cy="8" r="3"/><path d="M3.5 19a5.5 5.5 0 0111 0"/><path d="M16 6.5a3 3 0 010 5.4"/><path d="M18.5 19a5 5 0 00-2.2-3.6"/>',
};

const VIEWS = [
  { id: 'ceo', nome: 'Sala do CEO', icon: 'ceo', tag: '4', crit: true, sub: 'Fila de decisões · atualizado agora' },
  { id: 'cortex', nome: 'O Córtex', icon: 'cortex', tag: 'vivo', sub: 'Grafo de conhecimento · entidades reais do ATUA' },
  { id: 'conciliacao', nome: 'Conciliação ATUA × Bancos', icon: 'conc', tag: 'piloto', sub: 'Base 04/09/2026 · amarração das 09:15' },
  { id: 'arquivos', nome: 'Arquivos e OFX', icon: 'arquivo', tag: 'fase 1', sub: 'Leitura do extrato na origem · conciliação real' },
  { id: 'cadeia', nome: 'Cadeia de valor', icon: 'cadeia', tag: '18', sub: '18 etapas monitoradas ponta a ponta' },
  { id: 'especialistas', nome: 'Especialistas', icon: 'espec', tag: '15', sub: 'Time por área · consulta o Córtex e emite artefato' },
  { id: 'agentes', nome: 'Agentes do núcleo', icon: 'agentes', tag: '20', sub: '14 de área + 6 transversais' },
  { id: 'confrontos', nome: 'Matriz de confronto', icon: 'confronto', tag: '15', sub: 'Cruzamentos entre fontes independentes' },
  { id: 'rotinas', nome: 'Rotinas e entregáveis', icon: 'rotinas', tag: '10', sub: 'Execução comprovada, não declarada' },
  { id: 'integracoes', nome: 'Integrações', icon: 'integra', tag: '16', sub: 'Fontes conectadas ao núcleo' },
];

/* ---------- views ---------- */
function viewCEO() {
  const criticos = CASOS.filter(c => c.nivel >= 4);
  const serie = CONCILIACAO.serie.map(s => s.extrato - s.atua);
  return `
  <div class="grid g-4">
    <div class="panel metric"><span class="eyebrow">Dinheiro em risco</span>
      <div class="v crit">${kbrl(PULSO.dinheiroEmRisco)}</div>
      <div class="d">23 casos abertos · 4 aguardam sua decisão</div>${sparkline(serie, 'var(--crit)')}</div>
    <div class="panel metric"><span class="eyebrow">Recuperado no mês</span>
      <div class="v ok">${kbrl(PULSO.recuperadoMes)}</div>
      <div class="d">17 casos encerrados com valor confirmado</div>${sparkline([120, 180, 210, 260, 300, 340, 390, 417], 'var(--ok)')}</div>
    <div class="panel metric"><span class="eyebrow">Sinais processados hoje</span>
      <div class="v"><span id="sinaisLive">${PULSO.sinaisHoje.toLocaleString('pt-BR')}</span></div>
      <div class="d">61 hipóteses ativas · 118 detectores</div>${sparkline([610, 780, 940, 1020, 1180, 1290, 1400, 1487])}</div>
    <div class="panel metric"><span class="eyebrow">Precisão dos detectores</span>
      <div class="v amber">${pct(PULSO.precisaoMedia)}</div>
      <div class="d">6 detectores suspensos automaticamente</div>${sparkline([72, 75, 79, 81, 84, 85, 86, 87], 'var(--amber)')}</div>
  </div>

  <div class="grid g-main" style="margin-top:14px">
    <section class="panel">
      <header><h3>Fila de decisões</h3><span class="eyebrow">${criticos.length} exigem assinatura humana</span></header>
      <div>${CASOS.map(c => `
        <article class="case" data-caso="${c.id}" tabindex="0">
          <div class="l1">
            <span class="chip ${c.nivel >= 5 ? 'crit' : c.nivel === 4 ? 'warn' : ''}">N${c.nivel} ${nivelChip(c.nivel)}</span>
            <span class="chip">${c.classe}</span>
            <span class="id">${c.id}</span>
            <span class="val" style="color:${c.impacto ? 'var(--ink)' : 'var(--ink-3)'}">${c.impacto ? brl(c.impacto) : '—'}</span>
          </div>
          <h4>${c.titulo}</h4>
          <div class="l3">
            <span>${c.area} · ${c.filial}</span>
            <span>Dono: ${c.dono}</span>
            <span>Prazo ${c.prazo}</span>
            <span>Confiança ${pct(c.confianca)}</span>
            <span style="color:var(--steel)">${c.estado}</span>
          </div>
        </article>`).join('')}</div>
    </section>

    <div class="grid" style="gap:14px">
      <section class="panel">
        <header><h3>Fluxo do córtex</h3><span class="eyebrow">ao vivo</span></header>
        <div class="flow" id="flowLive">${FLUXO.map(f => `<div><span class="h">${f.hora}</span><span class="a">${f.agente}</span><span>${f.texto}</span></div>`).join('')}</div>
      </section>
      <section class="panel">
        <header><h3>Etapas em pior saúde</h3></header>
        <div class="body" style="display:grid;gap:11px">
          ${[...ETAPAS].sort((a, b) => a.saude - b.saude).slice(0, 5).map(e => `
            <div>
              <div style="display:flex;justify-content:space-between;margin-bottom:5px;font-size:11.8px">
                <span>${e.ordem}. ${e.nome}</span><span class="num" style="color:var(--ink-3)">${e.saude}</span>
              </div>
              <div class="bar"><i class="${saudeCls(e.saude)}" style="width:${e.saude}%"></i></div>
            </div>`).join('')}
        </div>
      </section>
    </div>
  </div>`;
}

function viewConciliacao() {
  const c = CONCILIACAO;
  const maxDif = Math.max(...c.serie.map(s => s.extrato - s.atua));
  const maxVal = Math.max(...c.serie.map(s => s.extrato));
  return `
  <div class="grid g-4">
    <div class="panel metric"><span class="eyebrow">Status da amarração</span>
      <div class="v crit" style="font-size:19px">${c.status}</div>
      <div class="d">Fechamento previsto ${c.fechamento}</div></div>
    <div class="panel metric"><span class="eyebrow">Extrato consolidado</span>
      <div class="v" style="font-size:20px">${brl(c.totalExtrato)}</div>
      <div class="d">737 movimentos em 4 bancos</div></div>
    <div class="panel metric"><span class="eyebrow">Lançado no ATUA</span>
      <div class="v" style="font-size:20px">${brl(c.totalAtua)}</div>
      <div class="d">${pct(c.conciliadoPct, 1)} conciliado automaticamente</div></div>
    <div class="panel metric"><span class="eyebrow">Diferença sem par</span>
      <div class="v crit" style="font-size:20px">${brl(c.diferenca)}</div>
      <div class="d">68 movimentos escalados para caso</div></div>
  </div>

  <div class="grid g-main" style="margin-top:14px">
   <div class="grid" style="gap:14px">
    <section class="panel">
      <header><h3>Divergências abertas</h3><span class="eyebrow">clique para abrir a hipótese</span></header>
      <table>
        <thead><tr><th>ID</th><th>Tipo</th><th>Banco</th><th>Histórico do extrato</th><th class="r">Valor</th><th class="r">Confiança</th></tr></thead>
        <tbody>${c.divergencias.map(d => `
          <tr class="click" data-div="${d.id}">
            <td class="mono" style="color:var(--ink-3)">${d.id}</td>
            <td><span class="dot ${d.tipo.includes('Baixa') || d.tipo === 'Duplicidade' ? 'crit' : 'warn'}"></span>${d.tipo}</td>
            <td>${d.banco}</td>
            <td style="color:var(--ink-2)">${d.historico}</td>
            <td class="r num">${brl(d.valor, 2)}</td>
            <td class="r num" style="color:${d.confianca > .9 ? 'var(--amber)' : 'var(--ink-2)'}">${pct(d.confianca)}</td>
          </tr>`).join('')}</tbody>
      </table>
    </section>
    <section class="panel">
      <header><h3>Contas monitoradas</h3><span class="eyebrow">4 bancos · 737 movimentos</span></header>
      <table>
        <thead><tr><th>Banco</th><th>Conta</th><th class="r">Mov.</th><th class="r">Conciliados</th><th class="r">Volume</th><th class="r">Sem par</th><th>Situação</th></tr></thead>
        <tbody>${c.bancos.map(b => `
          <tr><td>${b.banco}</td><td class="mono" style="color:var(--ink-3)">${b.conta}</td>
          <td class="r num">${b.movimentos}</td><td class="r num">${b.conciliados}</td>
          <td class="r num">${brl(b.valor)}</td>
          <td class="r num" style="color:${b.divergencia ? 'var(--crit)' : 'var(--ink-3)'}">${b.divergencia ? brl(b.divergencia, 2) : '—'}</td>
          <td><span class="dot ${b.status === 'ok' ? 'ok' : 'crit'}"></span>${b.status === 'ok' ? 'Fechado' : 'Divergente'}</td></tr>`).join('')}</tbody>
      </table>
    </section>
   </div>

    <div class="grid" style="gap:14px">
      <section class="panel">
        <header><h3>Extrato × ATUA · 8 dias</h3></header>
        <div class="body">
          <div style="display:grid;gap:9px">
          ${c.serie.map(s => {
            const dif = s.extrato - s.atua;
            return `<div>
              <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--ink-3);margin-bottom:4px">
                <span class="mono">${s.d}</span><span class="mono" style="color:${dif > 60 ? 'var(--crit)' : 'var(--ink-2)'}">Δ ${dif} mil</span>
              </div>
              <div class="bar" style="height:5px"><i style="width:${(s.extrato / maxVal * 100).toFixed(1)}%;background:rgba(111,168,199,.45)"></i></div>
              <div class="bar" style="height:5px;margin-top:2px"><i class="${dif > 60 ? 'crit' : 'ok'}" style="width:${(s.atua / maxVal * 100).toFixed(1)}%"></i></div>
            </div>`;
          }).join('')}
          </div>
          <p style="margin:10px 0 0;font-size:11px;color:var(--ink-3)">Barra superior: extrato bancário. Inferior: lançado no ATUA.</p>
        </div>
      </section>
      <section class="panel">
        <header><h3>Regras de casamento</h3></header>
        <table>
          <tbody>${c.regras.map(r => `
            <tr><td style="width:34%">${r.nome}<br><span style="color:var(--ink-3);font-size:11px">${r.criterio}</span></td>
            <td class="r num">${r.casados}</td>
            <td style="width:38%"><div class="bar"><i class="${r.id === 'R5' ? 'crit' : ''}" style="width:${(r.pct * 100).toFixed(0)}%"></i></div></td>
            <td class="r num" style="color:var(--ink-3)">${pct(r.pct, 1)}</td></tr>`).join('')}</tbody>
        </table>
      </section>
    </div>
  </div>

  `;
}


function viewCadeia() {
  return `
  <div class="grid g-4">
    ${[['Etapas monitoradas', ETAPAS.length, ''], ['Etapas abaixo de 60', ETAPAS.filter(e => e.saude < 60).length, 'crit'],
       ['Achados abertos na cadeia', ETAPAS.reduce((a, e) => a + e.achados, 0), 'amber'], ['SLA estourado', ETAPAS.filter(e => e.saude < 70).length, 'warn']]
      .map(([k, v, cls]) => `<div class="panel metric"><span class="eyebrow">${k}</span><div class="v ${cls}">${v}</div></div>`).join('')}
  </div>
  <h3 class="sec">Do primeiro contato ao fechamento contábil</h3>
  <div class="chain">
    ${ETAPAS.map(e => `
      <article class="stage" data-etapa="${e.id}" tabindex="0">
        <span class="ord">${String(e.ordem).padStart(2, '0')}</span>
        <div class="nm">${e.nome}<small>${e.sistemas.join(' · ')}</small></div>
        <div class="ar">${e.area}<br><span style="color:var(--ink-3);font-size:11px">${e.dono}</span></div>
        <div class="sl">${e.leadTime}<br><span style="color:var(--ink-3)">SLA ${e.sla}</span></div>
        <div><span class="chip ${e.achados > 5 ? 'crit' : e.achados > 2 ? 'warn' : ''}">${e.achados} achados</span></div>
        <div style="display:grid;gap:4px;justify-items:end">
          <span class="num" style="font-size:11px;color:var(--ink-3)">${e.saude}</span>
          <div class="bar" style="width:52px"><i class="${saudeCls(e.saude)}" style="width:${e.saude}%"></i></div>
        </div>
      </article>`).join('')}
  </div>`;
}

function viewAgentes() {
  const est = { ativo: 'ok', investigando: 'warn', ocioso: 'idle' };
  return `
  <div class="grid g-4">
    ${[['Agentes ativos', AGENTES.filter(a => a.estado !== 'ocioso').length, ''], ['Investigando agora', AGENTES.filter(a => a.estado === 'investigando').length, 'amber'],
       ['Ciclos nas últimas 24h', AGENTES.reduce((a, x) => a + x.ciclos, 0).toLocaleString('pt-BR'), ''], ['Custo do dia', brl(PULSO.custoDia, 2), '']]
      .map(([k, v, cls]) => `<div class="panel metric"><span class="eyebrow">${k}</span><div class="v ${cls}" style="font-size:22px">${v}</div></div>`).join('')}
  </div>
  <h3 class="sec">Agentes de área</h3>
  <section class="panel">
    <table>
      <thead><tr><th>Agente</th><th>ID</th><th>Foco</th><th class="r">Ciclos 24h</th><th class="r">Achados</th><th class="r">Precisão</th><th class="r">Último ciclo</th><th>Estado</th></tr></thead>
      <tbody>${AGENTES.filter(a => a.tipo === 'Área').map(a => `
        <tr class="click" data-agente="${a.id}"><td>${a.nome}</td><td class="mono" style="color:var(--ink-3)">${a.id}</td>
        <td style="color:var(--ink-2)">${a.foco}</td><td class="r num">${a.ciclos}</td><td class="r num">${a.achados}</td>
        <td class="r num">${pct(a.precisao)}</td><td class="r num" style="color:var(--ink-3)">${a.ultimo}</td>
        <td><span class="dot ${est[a.estado]}"></span>${a.estado}</td></tr>`).join('')}</tbody>
    </table>
  </section>
  <h3 class="sec">Agentes transversais</h3>
  <section class="panel">
    <table>
      <thead><tr><th>Agente</th><th>ID</th><th>Foco</th><th class="r">Ciclos 24h</th><th class="r">Achados</th><th class="r">Precisão</th><th class="r">Último ciclo</th><th>Estado</th></tr></thead>
      <tbody>${AGENTES.filter(a => a.tipo === 'Transversal').map(a => `
        <tr class="click" data-agente="${a.id}"><td>${a.nome}</td><td class="mono" style="color:var(--ink-3)">${a.id}</td>
        <td style="color:var(--ink-2)">${a.foco}</td><td class="r num">${a.ciclos}</td><td class="r num">${a.achados}</td>
        <td class="r num">${pct(a.precisao)}</td><td class="r num" style="color:var(--ink-3)">${a.ultimo}</td>
        <td><span class="dot ${est[a.estado]}"></span>${a.estado}</td></tr>`).join('')}</tbody>
    </table>
  </section>`;
}

function viewConfrontos() {
  const cls = { ativo: 'ok', piloto: 'amber', calibrando: 'warn' };
  return `
  <section class="panel">
    <header><h3>Confrontos entre fontes independentes</h3><span class="eyebrow">${CONFRONTOS.length} cruzamentos · 3 em piloto</span></header>
    <table>
      <thead><tr><th>ID</th><th>Fonte A</th><th>Fonte B</th><th>Chave</th><th>O que expõe</th><th class="r">Achados</th><th>Estado</th></tr></thead>
      <tbody>${CONFRONTOS.map(c => `
        <tr><td class="mono" style="color:var(--ink-3)">${c.id}</td><td>${c.a}</td><td>${c.b}</td>
        <td class="mono" style="font-size:11px;color:var(--ink-3)">${c.chave}</td>
        <td style="color:var(--ink-2)">${c.expoe}</td><td class="r num">${c.achados}</td>
        <td><span class="chip ${cls[c.estado]}">${c.estado}</span></td></tr>`).join('')}</tbody>
    </table>
  </section>`;
}

function viewRotinas() {
  const st = { ok: 'ok', parcial: 'warn', atrasado: 'crit' };
  return `
  <div class="grid g-4">
    ${[['Rotinas do dia', ROTINAS.reduce((a, r) => a + r.total, 0), ''], ['Executadas', ROTINAS.reduce((a, r) => a + r.feitas, 0), 'ok'],
       ['Sem evidência', ROTINAS.reduce((a, r) => a + (r.feitas - r.evidencia), 0), 'crit'], ['Tarefa crítica aberta', ROTINAS.reduce((a, r) => a + r.criticaAberta, 0), 'amber']]
      .map(([k, v, cls]) => `<div class="panel metric"><span class="eyebrow">${k}</span><div class="v ${cls}">${v}</div></div>`).join('')}
  </div>
  <h3 class="sec">Execução por função · 05/09/2026</h3>
  <section class="panel">
    <table>
      <thead><tr><th>Função</th><th class="r">Rotinas</th><th class="r">Executadas</th><th class="r">Com evidência</th><th class="r">Em atraso</th><th class="r">Crítica aberta</th><th style="width:150px">Score</th></tr></thead>
      <tbody>${ROTINAS.map(r => `
        <tr><td>${r.funcao}</td><td class="r num">${r.total}</td><td class="r num">${r.feitas}</td>
        <td class="r num" style="color:${r.evidencia < r.feitas ? 'var(--crit)' : 'var(--ink)'}">${r.evidencia}</td>
        <td class="r num">${r.atraso || '—'}</td>
        <td class="r num" style="color:${r.criticaAberta ? 'var(--crit)' : 'var(--ink-3)'}">${r.criticaAberta || '—'}</td>
        <td><div style="display:flex;align-items:center;gap:9px"><div class="bar" style="flex:1"><i class="${saudeCls(r.score)}" style="width:${r.score}%"></i></div><span class="num" style="font-size:11px;width:22px">${r.score}</span></div></td></tr>`).join('')}</tbody>
    </table>
  </section>
  <h3 class="sec">Entregáveis com prova</h3>
  <section class="panel">
    <table>
      <thead><tr><th>Entregável</th><th>Periodicidade</th><th>Dono</th><th>Prova coletada pelo agente</th><th>Situação</th></tr></thead>
      <tbody>${ENTREGAVEIS.map(e => `
        <tr><td>${e.titulo}</td><td class="mono" style="font-size:11px;color:var(--ink-3)">${e.periodicidade}</td><td>${e.dono}</td>
        <td style="color:var(--ink-2)">${e.prova}</td>
        <td><span class="dot ${st[e.status]}"></span>${e.status === 'ok' ? 'Entregue' : e.status === 'parcial' ? 'Parcial' : 'Não entregue'}</td></tr>`).join('')}</tbody>
    </table>
  </section>`;
}

function viewIntegracoes() {
  const st = { online: 'ok', degradado: 'warn', pendente: 'crit' };
  return `
  <div class="grid g-4">
    ${[['Fontes conectadas', INTEGRACOES.length, ''], ['Online', INTEGRACOES.filter(i => i.estado === 'online').length, 'ok'],
       ['Degradadas', INTEGRACOES.filter(i => i.estado === 'degradado').length, 'warn'], ['Pendentes', INTEGRACOES.filter(i => i.estado === 'pendente').length, 'crit']]
      .map(([k, v, cls]) => `<div class="panel metric"><span class="eyebrow">${k}</span><div class="v ${cls}">${v}</div></div>`).join('')}
  </div>
  <h3 class="sec">Fontes do núcleo</h3>
  <section class="panel">
    <table>
      <thead><tr><th>Fonte</th><th>Modo</th><th class="r">Latência</th><th class="r">Última carga</th><th>Estado</th></tr></thead>
      <tbody>${INTEGRACOES.map(i => `
        <tr><td>${i.nome}</td><td style="color:var(--ink-2)">${i.tipo}</td>
        <td class="r num">${i.latencia}</td><td class="r num" style="color:var(--ink-3)">${i.ultimo}</td>
        <td><span class="dot ${st[i.estado]}"></span>${i.estado}</td></tr>`).join('')}</tbody>
    </table>
  </section>
  <h3 class="sec">Isolamento da instância</h3>
  <section class="panel"><div class="body" style="display:grid;gap:10px;font-size:12.4px;color:var(--ink-2);max-width:760px">
    <p style="margin:0">Banco dedicado <span class="mono" style="color:var(--amber)">cortex-prod-01</span>, sem escrita em nenhum sistema de origem. Toda leitura passa por réplica ou API somente leitura.</p>
    <p style="margin:0">RLS por empresa em 100% das tabelas · ledger append-only com hash encadeado · chave de serviço restrita ao worker.</p>
    <p style="margin:0">Ações de nível 4 e 5 nunca são executadas pelo sistema: exigem assinatura nominal registrada no ledger.</p>
  </div></section>`;
}

const RENDER = { ceo: viewCEO, cortex: viewCortex, conciliacao: viewConciliacao, arquivos: viewArquivos, cadeia: viewCadeia, especialistas: viewEspecialistas, agentes: viewAgentes, confrontos: viewConfrontos, rotinas: viewRotinas, integracoes: viewIntegracoes };

/* ---------- drawer ---------- */
function openDrawer(html) {
  $('#drawer').innerHTML = html;
  $('#drawer').classList.add('on');
  $('#drawer').setAttribute('aria-hidden', 'false');
  $('#drawerBg').classList.add('on');
}
function closeDrawer() {
  $('#drawer').classList.remove('on');
  $('#drawer').setAttribute('aria-hidden', 'true');
  $('#drawerBg').classList.remove('on');
}
function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.classList.add('on');
  clearTimeout(t._t); t._t = setTimeout(() => t.classList.remove('on'), 2600);
}

function drawerCaso(id) {
  const c = CASOS.find(x => x.id === id);
  openDrawer(`
    <header>
      <div style="flex:1">
        <div style="display:flex;gap:8px;align-items:center">
          <span class="chip ${c.nivel >= 5 ? 'crit' : c.nivel === 4 ? 'warn' : ''}">N${c.nivel} ${nivelChip(c.nivel)}</span>
          <span class="chip">${c.classe}</span>
          <span class="mono" style="font-size:10.5px;color:var(--ink-3)">${c.id} · aberto ${c.abertoEm}</span>
        </div>
        <h3>${c.titulo}</h3>
      </div>
      <button class="close" data-close aria-label="Fechar">✕</button>
    </header>
    <div class="content">
      <div class="grid g-2" style="gap:10px">
        <div class="panel metric" style="padding:11px"><span class="eyebrow">Impacto estimado</span><div class="v" style="font-size:19px">${c.impacto ? brl(c.impacto) : 'Sem valor direto'}</div></div>
        <div class="panel metric" style="padding:11px"><span class="eyebrow">Confiança</span><div class="v amber" style="font-size:19px">${pct(c.confianca)}</div></div>
      </div>
      <div class="dsec"><span class="eyebrow">O que aconteceu</span><p>${c.resumo}</p></div>
      <div class="dsec"><span class="eyebrow">Evidências coletadas</span>
        ${c.evidencias.map(e => `<div class="ev"><div class="t"><span class="dot ${e.peso === 'alta' ? 'ok' : 'warn'}"></span><b>${e.fonte}</b><span class="ref">${e.ref}</span></div><div class="n">${e.nota}</div></div>`).join('')}
      </div>
      <div class="dsec"><span class="eyebrow">Contraprova do Advogado do Diabo</span><p>${c.contraprova}</p>
        <p style="color:var(--amber)">${c.veredito}</p></div>
      <div class="dsec"><span class="eyebrow">Ação recomendada</span><p>${c.acao}</p>
        <p style="font-size:11.5px;color:var(--ink-3)">Dono: ${c.dono} · Prazo ${c.prazo} · ${c.area} / ${c.filial}</p></div>
    </div>
    <footer>
      <button class="btn primary" data-act="Ação aprovada e registrada no ledger">Aprovar ação</button>
      <button class="btn" data-act="Caso devolvido ao agente para mais evidência">Pedir mais evidência</button>
      <button class="btn" data-act="Caso rejeitado — detector recalibrado">Rejeitar</button>
    </footer>`);
}

function drawerEtapa(id) {
  const e = ETAPAS.find(x => x.id === id);
  const ags = AGENTES.filter(a => e.area.includes(a.nome) || a.nome === 'Analista de Processo').slice(0, 3);
  openDrawer(`
    <header>
      <div style="flex:1">
        <span class="mono" style="font-size:10.5px;color:var(--ink-3)">Etapa ${String(e.ordem).padStart(2, '0')} · ${e.id}</span>
        <h3>${e.nome}</h3>
      </div>
      <button class="close" data-close aria-label="Fechar">✕</button>
    </header>
    <div class="content">
      <div class="grid g-2" style="gap:10px">
        <div class="panel metric" style="padding:11px"><span class="eyebrow">Saúde</span><div class="v ${saudeCls(e.saude)}" style="font-size:19px">${e.saude}/100</div></div>
        <div class="panel metric" style="padding:11px"><span class="eyebrow">Lead time · SLA</span><div class="v" style="font-size:19px">${e.leadTime} <span style="color:var(--ink-3);font-size:13px">/ ${e.sla}</span></div></div>
      </div>
      <div class="dsec"><span class="eyebrow">Responsável</span><p>${e.area} — ${e.dono}</p></div>
      <div class="dsec"><span class="eyebrow">Entradas e saídas</span>
        <p>Entra: ${e.entradas.join(', ')}<br>Sai: ${e.saidas.join(', ')}</p></div>
      <div class="dsec"><span class="eyebrow">Sistemas envolvidos</span><p>${e.sistemas.join(' · ')}</p></div>
      <div class="dsec"><span class="eyebrow">Risco em aberto</span><p style="color:var(--warn)">${e.risco}</p>
        <p style="font-size:11.5px;color:var(--ink-3)">${e.achados} achados vinculados a esta etapa</p></div>
      <div class="dsec"><span class="eyebrow">Agentes que vigiam a etapa</span>
        ${ags.map(a => `<div class="ev"><div class="t"><span class="dot ${a.estado === 'ocioso' ? 'idle' : 'ok'}"></span><b>${a.nome}</b><span class="ref">${a.id}</span></div><div class="n">${a.foco}</div></div>`).join('')}
      </div>
    </div>
    <footer><button class="btn primary" data-act="Varredura profunda enfileirada para a etapa">Rodar varredura profunda</button>
    <button class="btn" data-act="Etapa marcada para revisão de processo">Marcar para revisão</button></footer>`);
}

function drawerDivergencia(id) {
  const d = CONCILIACAO.divergencias.find(x => x.id === id);
  const ag = AGENTES.find(a => a.id === d.agente);
  openDrawer(`
    <header>
      <div style="flex:1">
        <span class="mono" style="font-size:10.5px;color:var(--ink-3)">Divergência ${d.id} · base ${CONCILIACAO.dataBase}</span>
        <h3>${d.tipo} — ${brl(d.valor, 2)}</h3>
      </div>
      <button class="close" data-close aria-label="Fechar">✕</button>
    </header>
    <div class="content">
      <div class="dsec"><span class="eyebrow">Movimento no extrato</span>
        <div class="ev"><div class="t"><b>${d.banco}</b><span class="ref">${d.data}</span></div><div class="n">${d.historico}</div></div></div>
      <div class="dsec"><span class="eyebrow">Contrapartida no ATUA</span>
        <div class="ev"><div class="t"><span class="dot crit"></span><b>Não localizada</b><span class="ref">R1–R4 sem par</span></div>
        <div class="n">Testadas as 4 regras de casamento, incluindo tolerância de ±R$ 0,05 e janela D+2.</div></div></div>
      <div class="dsec"><span class="eyebrow">Hipótese do agente ${ag.nome}</span><p>${d.hipotese}</p>
        <p style="color:var(--amber)">Confiança ${pct(d.confianca)} · sustentada após contraprova</p></div>
      <div class="dsec"><span class="eyebrow">Efeito na amarração</span>
        <p>Impede o fechamento das 09:15 e mantém ${brl(CONCILIACAO.diferenca)} sem explicação no caixa do dia.</p></div>
    </div>
    <footer><button class="btn primary" data-act="Divergência elevada a caso e enviada ao dono">Elevar a caso</button>
    <button class="btn" data-act="Vínculo manual solicitado à tesouraria">Solicitar vínculo</button></footer>`);
}

function drawerAgente(id) {
  const a = AGENTES.find(x => x.id === id);
  openDrawer(`
    <header>
      <div style="flex:1"><span class="mono" style="font-size:10.5px;color:var(--ink-3)">${a.id} · agente ${a.tipo.toLowerCase()}</span><h3>${a.nome}</h3></div>
      <button class="close" data-close aria-label="Fechar">✕</button>
    </header>
    <div class="content">
      <div class="grid g-2" style="gap:10px">
        <div class="panel metric" style="padding:11px"><span class="eyebrow">Precisão</span><div class="v amber" style="font-size:19px">${pct(a.precisao)}</div></div>
        <div class="panel metric" style="padding:11px"><span class="eyebrow">Ciclos 24h</span><div class="v" style="font-size:19px">${a.ciclos}</div></div>
      </div>
      <div class="dsec"><span class="eyebrow">Foco de vigilância</span><p>${a.foco}</p></div>
      <div class="dsec"><span class="eyebrow">Últimas execuções</span>
        ${FLUXO.filter(f => f.agente === a.id).concat(FLUXO.slice(0, 2)).slice(0, 3)
          .map(f => `<div class="ev"><div class="t"><b>Ciclo concluído</b><span class="ref">${f.hora}</span></div><div class="n">${f.texto}</div></div>`).join('')}
      </div>
      <div class="dsec"><span class="eyebrow">Limites do agente</span>
        <p>Leitura somente. Não escreve em sistema de origem, não aprova pagamento e não identifica colaborador antes do quorum de duas fontes independentes.</p></div>
    </div>
    <footer><button class="btn primary" data-act="Ciclo extra enfileirado">Rodar agora</button>
    <button class="btn" data-act="Agente pausado até nova ordem">Pausar agente</button></footer>`);
}

/* ---------- especialistas ---------- */
function abreEspecialista(id) {
  const d = drawerEspecialista(id);
  if (!d) return;
  openDrawer(`<header>${d.cabecalho}<button class="close" data-close aria-label="Fechar">✕</button></header>
    <div class="content">${d.corpo}</div>
    <footer>${d.rodape}</footer>`);
}

function acaoEspecialista(acao, id) {
  if (acao === 'sobmedida') return toast('Entrevista de novo especialista — disponível na fase 2');
  const e = ESPECIALISTAS.find(x => x.id === id);
  if (!e) return;
  if (acao === 'consultar') {
    closeDrawer();
    return toast(`${e.nome} consultou o Córtex · ${e.fontes.length} fontes varridas`);
  }
  if (acao === 'artefato') {
    closeDrawer();
    return toast(`${e.nome} emitiu: ${e.artefatos[0]}`);
  }
}

/* ---------- ações da tela de arquivos ---------- */
async function acaoArquivo(cmd) {
  if (cmd === 'limpar') { limpar(); return toast('Arquivos descartados'); }
  if (cmd === 'exemplo') {
    toast('Lendo arquivos de exemplo…');
    try { await carregarExemplos(); toast('Extrato e razão processados'); }
    catch (e) { toast(`Falha ao carregar exemplos: ${e.message}`); }
  }
}

/* ---------- navegação ---------- */
let atual = 'ceo';
function nav(id) {
  atual = id;
  const v = VIEWS.find(x => x.id === id);
  $('#topTitle').textContent = v.nome;
  $('#topSub').textContent = v.sub;
  document.querySelectorAll('#nav button').forEach(b => b.classList.toggle('on', b.dataset.view === id));
  $('#main').innerHTML = `<div class="view on">${RENDER[id]()}</div>`;
  $('#main').scrollTop = 0;
  if (id === 'cortex') ligaCortex(n => openDrawer(drawerNo(n)));
}

function montaNav() {
  const GRUPO = { 0: 'Núcleo', 2: 'Financeiro', 4: 'Empresa', 7: 'Controle' };
  $('#nav').innerHTML =
    VIEWS.map((v, i) => `${GRUPO[i] ? `<p class="nav-label eyebrow">${GRUPO[i]}</p>` : ''}
      <button data-view="${v.id}" type="button">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round">${ICON[v.icon]}</svg>
        <span class="nm">${v.nome}</span><span class="tag ${v.crit ? 'crit' : ''}">${v.tag}</span>
      </button>`).join('');
  $('#nav').addEventListener('click', e => {
    const b = e.target.closest('button[data-view]');
    if (b) { nav(b.dataset.view); document.querySelector('.side').classList.remove('on'); }
  });
  const mb = $('#menuBtn');
  if (mb) mb.addEventListener('click', () => document.querySelector('.side').classList.toggle('on'));
}

function liga() {
  $('#topRisco').textContent = kbrl(PULSO.dinheiroEmRisco);
  $('#topRec').textContent = kbrl(PULSO.recuperadoMes);
  $('#topVar').textContent = META.ultimaVarredura.split(' ')[1];
  $('#footSinais').textContent = PULSO.sinaisHoje.toLocaleString('pt-BR');
  $('#footCusto').textContent = brl(PULSO.custoDia, 2);

  $('#main').addEventListener('click', e => {
    const ac = e.target.closest('[data-acao]');
    if (ac) { e.stopPropagation(); return acaoEspecialista(ac.dataset.acao, ac.dataset.espec); }
    const es = e.target.closest('[data-espec]');
    if (es) return abreEspecialista(es.dataset.espec);
    const caso = e.target.closest('[data-caso]');
    if (caso) return drawerCaso(caso.dataset.caso);
    const et = e.target.closest('[data-etapa]');
    if (et) return drawerEtapa(et.dataset.etapa);
    const dv = e.target.closest('[data-div]');
    if (dv) return drawerDivergencia(dv.dataset.div);
    const ag = e.target.closest('[data-agente]');
    if (ag) return drawerAgente(ag.dataset.agente);
    const ad = e.target.closest('[data-arqdiv]');
    if (ad) return drawerArqDivergencia(ad.dataset.arqdiv, openDrawer);
    const ab = e.target.closest('[data-arq]');
    if (ab) return acaoArquivo(ab.dataset.arq);
  });

  ligaArquivos(() => { if (atual === 'arquivos') nav('arquivos'); });
  $('#main').addEventListener('change', async (e) => {
    const inp = e.target.closest('.drop input[type=file]');
    if (!inp || !inp.files.length) return;
    const n = inp.files.length;
    await ingerir([...inp.files]);
    toast(`${n} arquivo${n > 1 ? 's' : ''} processado${n > 1 ? 's' : ''}${ARQ.erros.length ? ` · ${ARQ.erros.length} com erro` : ''}`);
  });
  ['dragover', 'dragenter'].forEach(ev => $('#main').addEventListener(ev, e => {
    const d = e.target.closest('.drop'); if (!d) return;
    e.preventDefault(); d.classList.add('over');
  }));
  ['dragleave', 'drop'].forEach(ev => $('#main').addEventListener(ev, e => {
    const d = e.target.closest('.drop'); if (d) d.classList.remove('over');
  }));
  $('#main').addEventListener('drop', async (e) => {
    const d = e.target.closest('.drop'); if (!d) return;
    e.preventDefault();
    const fs = [...(e.dataTransfer?.files || [])];
    if (!fs.length) return;
    await ingerir(fs);
    toast(`${fs.length} arquivo${fs.length > 1 ? 's' : ''} processado${fs.length > 1 ? 's' : ''}${ARQ.erros.length ? ` · ${ARQ.erros.length} com erro` : ''}`);
  });
  $('#main').addEventListener('keydown', e => {
    if (e.key !== 'Enter') return;
    const c = e.target.closest('[data-caso]'); if (c) drawerCaso(c.dataset.caso);
    const et = e.target.closest('[data-etapa]'); if (et) drawerEtapa(et.dataset.etapa);
  });
  $('#drawer').addEventListener('click', e => {
    if (e.target.closest('[data-close]')) return closeDrawer();
    const ac = e.target.closest('[data-acao]');
    if (ac) return acaoEspecialista(ac.dataset.acao, ac.dataset.espec);
    const a = e.target.closest('[data-act]');
    if (a) { closeDrawer(); toast(a.dataset.act); }
  });
  $('#drawerBg').addEventListener('click', closeDrawer);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });

  // pulso ao vivo
  const NOVOS = [
    ['AG-COB', 'Promessa de pagamento vencida — Agromercantil S/A'],
    ['AG-TES', 'Tarifa bancária acima do contratado detectada no Bradesco'],
    ['AG-ROT', 'Rotina de fechamento fiscal sem evidência às 08:00'],
    ['AG-OPE', 'Viagem 44821 sem evento de fim de MDF-e'],
    ['AG-FRD', 'Padrão de conluio descartado após contraprova'],
    ['AG-CMP', 'Fornecedor com 3ª compra sem cotação concorrente'],
    ['AG-CAP', 'Título 90144 com rateio ausente entre 2 centros de custo'],
  ];
  let k = 0;
  setInterval(() => {
    const s = document.getElementById('sinaisLive');
    if (s) s.textContent = (parseInt(s.textContent.replace(/\D/g, ''), 10) + Math.ceil(Math.random() * 3)).toLocaleString('pt-BR');
    const flow = document.getElementById('flowLive');
    if (flow) {
      const [ag, txt] = NOVOS[k++ % NOVOS.length];
      const now = new Date();
      const d = document.createElement('div');
      d.innerHTML = `<span class="h">${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}</span><span class="a">${ag}</span><span>${txt}</span>`;
      d.style.background = 'rgba(240,180,41,.07)';
      flow.prepend(d);
      setTimeout(() => { d.style.transition = 'background .8s'; d.style.background = 'transparent'; }, 60);
      if (flow.children.length > 11) flow.removeChild(flow.lastChild);
    }
  }, 5200);
}

montaNav();
runBoot(() => {
  $('#shell').classList.add('live');
  nav('ceo');
  liga();
  createBrain(document.getElementById('miniBrain'), { count: 330, k: 1, scale: 0.42, hud: false, spin: 0.00016 });
});
