/* ==========================================================================
   CORTEX — Quadro de Especialistas
   Cada área da Pianetto tem gente com nome, promessa e capacidade declarada.
   Duas ações são universais: consultar o Córtex e emitir artefato.
   ========================================================================== */

export const DEPARTAMENTOS = [
  {
    id: 'tesouraria',
    nome: 'Financeiro & Tesouraria',
    lede: 'Quem guarda o caixa e não deixa nada passar em branco',
    cor: 'var(--teal)',
  },
  {
    id: 'controladoria',
    nome: 'Controladoria & Custos',
    lede: 'Quem confere se o número está contando a verdade',
    cor: 'var(--ember)',
  },
  {
    id: 'comercial',
    nome: 'Comercial & Faturamento',
    lede: 'Quem garante que todo frete entregue vira dinheiro',
    cor: 'var(--violet)',
  },
  {
    id: 'operacoes',
    nome: 'Operações & Frota',
    lede: 'Quem faz o caminhão rodar sem rodar no prejuízo',
    cor: 'var(--teal)',
  },
  {
    id: 'fiscal',
    nome: 'Fiscal & Contábil',
    lede: 'Quem mantém a empresa em dia com o fisco, antes da fiscalização',
    cor: 'var(--ember)',
  },
  {
    id: 'gente',
    nome: 'Gente, Jurídico & Processos',
    lede: 'Quem protege a empresa de dentro para fora',
    cor: 'var(--violet)',
  },
];

export const ESPECIALISTAS = [
  /* ---------------- Financeiro & Tesouraria ---------------- */
  {
    id: 'marta', nome: 'Marta', dep: 'tesouraria', papel: 'Analista de Tesouraria',
    promessa: 'O caixa fecha antes de você perguntar.',
    habs: ['conciliacao-ofx', 'saldo-diario', 'previsao-de-caixa'],
    dentro: true,
    fontes: ['Extrato OFX na origem', 'caixa_financeiro_lancamento', 'conta + banco'],
    faz: [
      'Lê o extrato direto do banco, nunca pelo ATUA, e amarra cada movimento ao lançamento correspondente.',
      'Aponta todo movimento bancário sem par no razão há mais de 2 dias úteis.',
      'Projeta o saldo dos próximos 30 dias a partir da carteira e dos títulos a pagar.',
    ],
    artefatos: ['Posição diária de caixa', 'Relatório de itens não conciliados', 'Projeção de 30 dias'],
  },
  {
    id: 'otavio', nome: 'Otávio', dep: 'tesouraria', papel: 'Analista de Cobrança',
    promessa: 'Nenhum título vence sem alguém saber.',
    habs: ['carteira-vencida', 'regua-de-cobranca', 'risco-de-cliente'],
    dentro: true,
    fontes: ['titulo', 'pessoa', 'histórico de quitação'],
    faz: [
      'Classifica a carteira por faixa de atraso e por risco do sacado.',
      'Dispara a régua de cobrança e registra a evidência de cada contato.',
      'Sinaliza cliente que mudou de comportamento de pagamento antes de virar perda.',
    ],
    artefatos: ['Carteira por faixa de atraso', 'E-mail executivo de cobrança', 'Parecer de risco do sacado'],
  },
  {
    id: 'iris', nome: 'Íris', dep: 'tesouraria', papel: 'Analista de Contas a Pagar',
    promessa: 'Nada é pago duas vezes.',
    habs: ['duplicidade-de-pagamento', 'rateio-centro-de-custo', 'fatura-a-pagar'],
    dentro: false,
    fontes: ['titulo_pagamento', 'caixa_financeiro_lancamento', 'centro de custo'],
    faz: [
      'Cruza fornecedor, valor e vencimento para achar pagamento repetido.',
      'Aponta lançamento sem centro de custo e despesa rateável que não foi rateada.',
      'Confere se o título pago tem fatura a pagar gerada.',
    ],
    artefatos: ['Relatório de duplicidades', 'Lista de lançamentos sem centro de custo'],
  },

  /* ---------------- Controladoria & Custos ---------------- */
  {
    id: 'caio', nome: 'Caio', dep: 'controladoria', papel: 'Controller',
    promessa: 'A margem que existe atrás de cada conhecimento.',
    habs: ['dre-conciliada', 'margem-por-viagem', 'custo-por-km'],
    dentro: true,
    fontes: ['ctrc', 'caixa_viagem', 'caixa_veiculo', 'DRE'],
    faz: [
      'Monta a DRE conciliada e explica cada variação relevante contra o mês anterior.',
      'Calcula resultado por viagem, por veículo e por rota, com custo direto e indireto.',
      'Aponta operação que fatura bem e entrega margem negativa.',
    ],
    artefatos: ['DRE conciliada do mês', 'Ranking de margem por rota', 'Custo por km da frota'],
  },
  {
    id: 'livia', nome: 'Lívia', dep: 'controladoria', papel: 'Auditora Interna',
    promessa: 'O erro aparece no mesmo dia, não no fechamento.',
    habs: ['confronto-de-fontes', 'lancamento-orfao', 'trilha-de-evidencia'],
    dentro: true,
    fontes: ['Todas as fontes conectadas', 'Matriz de confronto'],
    faz: [
      'Roda os confrontos cruzados entre fontes independentes e abre caso quando divergem.',
      'Procura lançamento órfão, valor fora da curva e sequência numérica com buraco.',
      'Guarda a trilha de evidência de tudo que apurou, para auditoria externa.',
    ],
    artefatos: ['Boletim diário de divergências', 'Dossiê de caso com evidências'],
  },

  /* ---------------- Comercial & Faturamento ---------------- */
  {
    id: 'bruno', nome: 'Bruno', dep: 'comercial', papel: 'Analista de Faturamento',
    promessa: 'Todo frete entregue vira fatura.',
    habs: ['ctrc-sem-fatura', 'pendencia-de-faturamento', 'prazo-de-faturamento'],
    dentro: true,
    fontes: ['ctrc', 'titulo', 'manifesto'],
    faz: [
      'Encontra conhecimento emitido e entregue que ainda não virou título a receber.',
      'Mede o tempo entre entrega e faturamento por cliente e por filial.',
      'Aponta CT-e travado por pendência de faturamento há mais de 5 dias.',
    ],
    artefatos: ['Relatório de CT-e sem fatura', 'Painel de prazo entrega → faturamento'],
  },
  {
    id: 'sofia', nome: 'Sofia', dep: 'comercial', papel: 'Inteligência Comercial',
    promessa: 'Você sabe exatamente de quem depende.',
    habs: ['concentracao-de-clientes', 'tabela-de-frete', 'rota-rentavel'],
    dentro: false,
    fontes: ['ctrc', 'pessoa', 'cidade origem/destino'],
    faz: [
      'Mede a concentração de receita e alerta quando poucos clientes viram risco.',
      'Compara o frete praticado com a tabela e com o piso mínimo da ANTT.',
      'Mostra qual rota merece esforço comercial e qual só ocupa caminhão.',
    ],
    artefatos: ['Mapa de concentração de receita', 'Comparativo tabela × praticado'],
  },

  /* ---------------- Operações & Frota ---------------- */
  {
    id: 'davi', nome: 'Davi', dep: 'operacoes', papel: 'Analista de Frota',
    promessa: 'O veículo que dá prejuízo não passa despercebido.',
    habs: ['resultado-por-veiculo', 'manutencao-preventiva', 'ociosidade'],
    dentro: true,
    fontes: ['veiculo', 'caixa_veiculo', 'ctrc', 'Gobrax'],
    faz: [
      'Fecha receita menos custo por placa e ordena do pior para o melhor.',
      'Cruza quilometragem com plano de manutenção e antecipa a preventiva.',
      'Aponta veículo parado, subutilizado ou fora de rota.',
    ],
    artefatos: ['Ranking de resultado por placa', 'Plano de manutenção do mês'],
  },
  {
    id: 'nina', nome: 'Nina', dep: 'operacoes', papel: 'Analista de Viagem',
    promessa: 'Adiantamento, saldo e acerto sempre batendo.',
    habs: ['acerto-de-viagem', 'carta-frete', 'vale-pedagio'],
    dentro: false,
    fontes: ['viagem_receita', 'carta_frete', 'caixa_viagem'],
    faz: [
      'Confere adiantamento contra saldo e fecha o acerto da viagem com o motorista.',
      'Verifica carta-frete emitida sem comprovante e vale-pedágio não utilizado.',
      'Aponta viagem encerrada sem acerto financeiro.',
    ],
    artefatos: ['Acerto de viagem', 'Relatório de cartas-frete pendentes'],
  },
  {
    id: 'rui', nome: 'Rui', dep: 'operacoes', papel: 'Analista de Combustível',
    promessa: 'Cada litro tem dono e tem destino.',
    habs: ['desvio-de-diesel', 'consumo-por-rota', 'km-por-litro'],
    dentro: false,
    fontes: ['X7 Bank', 'Gobrax', 'caixa_veiculo'],
    faz: [
      'Cruza abastecimento pago com quilometragem rodada e consumo esperado.',
      'Aponta abastecimento fora de rota, fora de horário ou acima da capacidade do tanque.',
      'Compara km/l por motorista na mesma rota e no mesmo veículo.',
    ],
    artefatos: ['Relatório de desvio de diesel', 'Ranking de km/l por motorista'],
  },

  /* ---------------- Fiscal & Contábil ---------------- */
  {
    id: 'alan', nome: 'Alan', dep: 'fiscal', papel: 'Auditor Fiscal',
    promessa: 'CT-e e MDF-e sem susto na SEFAZ.',
    habs: ['validacao-cte', 'mdfe-em-aberto', 'credito-icms'],
    dentro: true,
    fontes: ['ctrc', 'manifesto_mdfe', 'ctrc_icms', 'SEFAZ'],
    faz: [
      'Valida CFOP, CST, base de cálculo e alíquota antes da transmissão.',
      'Aponta MDF-e não encerrado e conhecimento sem averbação.',
      'Levanta crédito de ICMS não aproveitado e risco de glosa.',
    ],
    artefatos: ['Dossiê fiscal do período', 'Lista de MDF-e em aberto'],
  },
  {
    id: 'teo', nome: 'Téo', dep: 'fiscal', papel: 'Analista Contábil',
    promessa: 'O balanço espelha a operação, não o contrário.',
    habs: ['conciliacao-contabil', 'provisao', 'fechamento'],
    dentro: false,
    fontes: ['Razão contábil', 'caixa_financeiro_lancamento', 'DRE'],
    faz: [
      'Concilia o razão contábil com o financeiro e aponta conta com saldo inexplicado.',
      'Confere provisões e competência de despesa.',
      'Monta o roteiro de fechamento com responsável e prazo por item.',
    ],
    artefatos: ['Conciliação contábil × financeira', 'Checklist de fechamento'],
  },

  /* ---------------- Gente, Jurídico & Processos ---------------- */
  {
    id: 'paula', nome: 'Paula', dep: 'gente', papel: 'Analista de RH',
    promessa: 'Jornada, folha e ponto sem passivo escondido.',
    habs: ['jornada-do-motorista', 'folha-x-ponto', 'admissao-e-desligamento'],
    dentro: false,
    fontes: ['funcionario', 'ATS Via RH', 'WorkMonitor', 'motorista'],
    faz: [
      'Cruza jornada registrada com viagem realizada e aponta risco de hora extra não paga.',
      'Confere folha contra ponto e contra o que foi efetivamente pago.',
      'Acompanha documentação de admissão e desligamento com prazo legal.',
    ],
    artefatos: ['Relatório de risco de jornada', 'Conferência folha × ponto'],
  },
  {
    id: 'clara', nome: 'Clara', dep: 'gente', papel: 'Jurídico',
    promessa: 'Contrato revisado antes de ser assinado.',
    habs: ['contrato-tac', 'risco-de-vinculo', 'notificacao-extrajudicial'],
    dentro: true,
    fontes: ['Contratos', 'Base de processos', 'motorista', 'carta_frete'],
    faz: [
      'Revisa contrato de TAC, agregado e parceiro apontando cláusula de risco.',
      'Mede indício de vínculo empregatício em relação com autônomo.',
      'Prepara notificação, defesa e dossiê probatório quando o caso escala.',
    ],
    artefatos: ['Parecer contratual', 'Dossiê probatório', 'Notificação extrajudicial'],
  },
  {
    id: 'otto', nome: 'Otto', dep: 'gente', papel: 'Analista de Processos',
    promessa: 'A empresa que roda mesmo sem você olhar.',
    habs: ['pop-de-processo', 'rotina-nao-executada', 'segregacao-de-funcoes'],
    dentro: true,
    fontes: ['Rotinas e entregáveis', 'Logs dos sistemas', 'SGI'],
    faz: [
      'Verifica se a rotina foi executada de fato, com evidência, e não apenas declarada.',
      'Aponta processo duplicado, lento ou sem dono definido.',
      'Testa a segregação de funções e sinaliza acúmulo perigoso na mesma pessoa.',
    ],
    artefatos: ['POP do processo', 'Painel de rotinas não executadas', 'Matriz de segregação'],
  },
];

/* ---------- glifo de identidade: uma onda determinística por especialista ---------- */
export function glifo(id, cor = 'var(--ink-3)') {
  let s = 0;
  for (let i = 0; i < id.length; i++) s = (s * 31 + id.charCodeAt(i)) % 100000;
  const rnd = () => { s = (s * 1103515245 + 12345) % 2147483648; return s / 2147483648; };
  const n = 22, w = 44, h = 22, mid = h / 2;
  let d = '';
  for (let i = 0; i < n; i++) {
    const x = (i / (n - 1)) * w;
    const amp = (0.25 + rnd() * 0.75) * (mid - 2.5);
    const y = mid + (i % 2 ? -amp : amp) * (0.35 + 0.65 * Math.sin((i / n) * Math.PI));
    d += `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
  }
  return `<svg class="spark" width="44" height="22" viewBox="0 0 ${w} ${h}" aria-hidden="true">
    <path d="${d}" fill="none" stroke="${cor}" stroke-width="1.1" stroke-linejoin="round" stroke-linecap="round"/>
  </svg>`;
}

/* ---------- cartão ---------- */
function cartao(e, cor) {
  return `<article class="espec ${e.dentro ? 'dentro' : ''}" data-espec="${e.id}">
    <div class="cab">
      <div class="glifo">${glifo(e.id, e.dentro ? cor : 'var(--ink-4)')}</div>
      <div>
        <div class="nome">${e.nome}</div>
        <div class="papel">${e.papel}</div>
      </div>
    </div>
    <p class="promessa">${e.promessa}</p>
    <div class="habs">${e.habs.map(h => `<span class="hab">${h}</span>`).join('')}</div>
    <div class="habs">
      <button class="hab" type="button" data-acao="consultar" data-espec="${e.id}">Consultar o Córtex</button>
      <button class="hab" type="button" data-acao="artefato" data-espec="${e.id}">Emitir artefato</button>
    </div>
    <div class="rodape">
      <span class="sit ${e.dentro ? 'dentro' : ''}">
        <span class="dot ${e.dentro ? 'ok' : ''}"></span>${e.dentro ? 'No seu time' : 'Disponível'}
      </span>
      <span class="abrir">Conhecer →</span>
    </div>
  </article>`;
}

/* ---------- tela ---------- */
export function viewEspecialistas() {
  const dentro = ESPECIALISTAS.filter(e => e.dentro).length;
  const total = ESPECIALISTAS.length;

  const secoes = DEPARTAMENTOS.map(d => {
    const eqp = ESPECIALISTAS.filter(e => e.dep === d.id);
    const n = eqp.filter(e => e.dentro).length;
    return `<section>
      <div class="secao">
        <h3>${d.nome}</h3>
        <p class="lede">${d.lede}</p>
        <span class="cont">${eqp.length} especialistas · ${n} no time</span>
      </div>
      <div class="grid g-3">${eqp.map(e => cartao(e, d.cor)).join('')}</div>
    </section>`;
  }).join('');

  return `
    <div class="secao" style="border:none;padding-bottom:0;margin-bottom:26px">
      <div style="flex:1;min-width:280px">
        <p class="eyebrow" style="margin-bottom:10px">Sua empresa, 24 horas por dia</p>
        <h3 style="font-size:var(--t-2xl);max-width:18ch;margin-bottom:8px">Um time que não dorme e não esquece</h3>
        <p class="lede" style="max-width:60ch">
          Quinze especialistas prontos, cada um com uma área, uma promessa e uma fonte de dados
          declarada. Todos consultam o mesmo Córtex e emitem artefato assinado.
        </p>
      </div>
      <div style="min-width:230px">
        <p class="eyebrow" style="margin-bottom:8px">${dentro} de ${total} no seu time</p>
        <div class="bar" style="height:4px"><i class="ok" style="width:${(dentro / total * 100).toFixed(0)}%"></i></div>
        <p class="hint" style="margin-top:9px">
          Os que estão fora seguem disponíveis: entram em operação assim que a fonte de dados deles é conectada.
        </p>
      </div>
    </div>

    <div class="sob-medida" style="margin-bottom:12px">
      <div class="ico">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round">
          <path d="M12 5v14M5 12h14"/>
        </svg>
      </div>
      <div style="flex:1">
        <h4>Criar um especialista sob medida</h4>
        <p>Descreva o que precisa ser vigiado. O Córtex entrevista você, conecta a fonte certa,
           define o confronto que prova o resultado e entrega o especialista pronto.</p>
      </div>
      <button class="btn" type="button" data-acao="sobmedida">Descrever</button>
    </div>

    ${secoes}
  `;
}

/* ---------- gaveta ---------- */
export function drawerEspecialista(id) {
  const e = ESPECIALISTAS.find(x => x.id === id);
  if (!e) return null;
  const d = DEPARTAMENTOS.find(x => x.id === e.dep);
  return {
    titulo: e.nome,
    cabecalho: `<div class="glifo" style="width:52px;height:40px;border-radius:9px;background:rgba(236,228,214,.035);border:1px solid var(--line);display:grid;place-items:center">${glifo(e.id, d.cor)}</div>
      <div><p class="eyebrow">${d.nome}</p><h4>${e.nome} · ${e.papel}</h4></div>`,
    corpo: `
      <div class="dsec">
        <p class="serif" style="font-size:18px;color:var(--ink-2);margin:0">${e.promessa}</p>
      </div>
      <div class="dsec">
        <span class="eyebrow">O que ele faz sozinho</span>
        ${e.faz.map(f => `<p>· ${f}</p>`).join('')}
      </div>
      <div class="dsec">
        <span class="eyebrow">De onde tira o dado</span>
        <div class="habs" style="display:flex;flex-wrap:wrap;gap:6px">
          ${e.fontes.map(f => `<span class="chip">${f}</span>`).join('')}
        </div>
      </div>
      <div class="dsec">
        <span class="eyebrow">Artefatos que emite</span>
        ${e.artefatos.map(a => `<p>· ${a}</p>`).join('')}
      </div>
      <div class="dsec">
        <span class="eyebrow">Capacidades</span>
        <div class="habs" style="display:flex;flex-wrap:wrap;gap:6px">
          ${e.habs.map(h => `<span class="hab">${h}</span>`).join('')}
        </div>
      </div>
      <div class="dsec">
        <span class="eyebrow">Situação</span>
        <p>${e.dentro
          ? 'Em operação. Executa a rotina dele e abre caso quando encontra divergência.'
          : 'Disponível, ainda não ativado. Depende de conectar a fonte de dados listada acima.'}</p>
      </div>`,
    rodape: `<button class="btn prim" type="button" data-acao="consultar" data-espec="${e.id}">Consultar o Córtex</button>
             <button class="btn" type="button" data-acao="artefato" data-espec="${e.id}">Emitir artefato</button>`,
  };
}
