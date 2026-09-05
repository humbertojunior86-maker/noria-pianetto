#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extrai o retrato quantitativo da Pianetto Transportes do ERP ATUA (PostgreSQL, somente leitura)."""
import sys, json, datetime, decimal, collections
sys.path.insert(0, '/home/user/workspace/cortex/tools')
from jhn import q

Q = {}          # registro de queries para o EXTRACAO.md
def run(nome, sql, args=None):
    Q.setdefault(nome, []).append(sql.strip())
    return q(sql, args)

def n(v):
    if v is None: return 0
    if isinstance(v, decimal.Decimal): return float(round(v, 2))
    return v

def pct(a, b): return round(100.0 * a / b, 2) if b else 0.0

R = {}
HOJE = run('meta', "select current_date d")[0]['d']
R['meta'] = {'data_extracao': str(datetime.date.today()),
             'data_referencia_banco': str(HOJE),
             'fonte': 'ERP ATUA - PostgreSQL schema public (usuario somente leitura jhn_ro)'}

# ------------------------------------------------------------------ 1. EMPRESA
emp = run('empresa', """
select p.nm_pessoa, p.nm_fantasia, p.nr_cnpj_cpf
from filial f join pessoa p on p.cd_pessoa = f.cd_pessoa_filial
where f.cd_pessoa_filial = f.cd_pessoa_matriz and f.cd_pessoa_matriz = 2
""")[0]
grp = run('empresa', """
select count(*) filter (where id_ativo = 2) ativas_2,
       count(*) filter (where id_ativo = 1) ativas_1,
       count(*) total,
       count(*) filter (where cd_pessoa_matriz = 2) grupo_pianetto,
       count(distinct cd_pessoa_matriz) matrizes
from filial
""")[0]
per = run('empresa', """
select min(dt_emissao) ini, max(dt_emissao) fim, count(*) ctes_validos, sum(vl_total) receita_total
from ctrc where dt_cancelamento is null
""")[0]
R['empresa'] = {
    'razao_social': emp['nm_pessoa'],
    'nome_fantasia': emp['nm_fantasia'],
    'cnpj': emp['nr_cnpj_cpf'],
    'cd_pessoa_matriz': 2,
    'filiais_ativas': grp['ativas_1'],
    'filiais_total_cadastradas': grp['total'],
    'filiais_grupo_pianetto': grp['grupo_pianetto'],
    'matrizes_no_banco': grp['matrizes'],
    'periodo_dados': {'inicio': str(per['ini']), 'fim': str(per['fim'])},
    'ctes_validos_total': per['ctes_validos'],
    'receita_total_periodo': n(per['receita_total']),
}

# ------------------------------------------------------------------ 2. FILIAIS
fil = run('filiais', """
with base as (
  select c.cd_pessoa_filial, count(*) qt, sum(c.vl_total) receita,
         coalesce(sum((select sum(cf.vl_frete) from carta_frete cf where cf.cd_ctrc = c.cd_ctrc)), 0) custo,
         sum(c.vl_resultado) resultado
  from ctrc c
  where c.dt_cancelamento is null and c.dt_emissao >= current_date - interval '12 months'
  group by 1
)
select f.cd_pessoa_filial, coalesce(nullif(p.nm_fantasia,''), p.nm_pessoa) nome,
       p.nm_pessoa, p.nr_cnpj_cpf, f.id_ativo, f.cd_pessoa_matriz,
       coalesce(b.qt,0) qt, coalesce(b.receita,0) receita,
       coalesce(b.custo,0) custo, coalesce(b.resultado,0) resultado
from filial f
left join base b on b.cd_pessoa_filial = f.cd_pessoa_filial
left join pessoa p on p.cd_pessoa = f.cd_pessoa_filial
order by coalesce(b.receita,0) desc
""")
tot_fil = sum(n(f['receita']) for f in fil)
R['filiais'] = [{
    'nome': f['nome'], 'razao_social': f['nm_pessoa'], 'cd_pessoa_filial': f['cd_pessoa_filial'],
    'cnpj': (f['nr_cnpj_cpf'] or '').strip() or None, 'cd_pessoa_matriz': f['cd_pessoa_matriz'],
    'ativa': f['id_ativo'] == 1, 'ctes_12m': f['qt'], 'receita_12m': n(f['receita']),
    'custo_carta_frete_12m': n(f['custo']), 'resultado_12m': n(f['resultado']),
    'ticket_medio': round(n(f['receita']) / f['qt'], 2) if f['qt'] else 0.0,
    'participacao_receita_pct': pct(n(f['receita']), tot_fil),
} for f in fil]
R['receita_12m_total'] = round(tot_fil, 2)

# --------------------------------------------------- 3. FATURAMENTO MENSAL 24m
fm = run('faturamento_mensal', """
select to_char(date_trunc('month', c.dt_emissao), 'YYYY-MM') mes,
       count(*) qt, sum(c.vl_total) receita, sum(c.vl_custo) custo_campo,
       sum(c.vl_resultado) resultado, sum(c.vl_peso) peso, sum(c.vl_frete) frete,
       coalesce(sum((select sum(cf.vl_frete) from carta_frete cf where cf.cd_ctrc = c.cd_ctrc)), 0) custo_carta_frete
from ctrc c
where c.dt_cancelamento is null
  and c.dt_emissao >= date_trunc('month', current_date) - interval '23 months'
group by 1 order by 1
""")
R['faturamento_mensal'] = [{
    'mes': m['mes'], 'ctes': m['qt'], 'receita': n(m['receita']), 'frete': n(m['frete']),
    'custo': n(m['custo_carta_frete']), 'custo_campo_vl_custo': n(m['custo_campo']),
    'resultado': n(m['resultado']), 'peso_kg': n(m['peso']),
    'margem_pct': pct(n(m['resultado']), n(m['receita'])),
} for m in fm]
R['observacao_custo'] = ('O campo ctrc.vl_custo esta praticamente sem uso (apenas 5 CT-es dos ultimos 12 meses '
                         'possuem valor, total R$ 4.838,86). O custo efetivo de tracao esta em carta_frete.vl_frete, '
                         'usado como "custo" na serie mensal e nas filiais. O campo ctrc.vl_resultado, por outro lado, '
                         'esta populado e foi mantido como resultado oficial do ERP.')

# ------------------------------------------------------------- 4. CLIENTES TOP
cli = run('clientes_top', """
select c.cd_pessoa_pagador, coalesce(nullif(p.nm_fantasia,''), p.nm_pessoa) nome,
       p.nm_pessoa, p.nr_cnpj_cpf,
       count(*) qt, sum(c.vl_total) receita, sum(c.vl_resultado) resultado
from ctrc c left join pessoa p on p.cd_pessoa = c.cd_pessoa_pagador
where c.dt_cancelamento is null and c.dt_emissao >= current_date - interval '12 months'
group by 1,2,3,4 order by receita desc nulls last limit 15
""")
tot_rec_12 = round(tot_fil, 2)
R['clientes_top'] = [{
    'cd_pessoa': c['cd_pessoa_pagador'], 'nome': c['nome'], 'razao_social': c['nm_pessoa'],
    'cnpj_cpf': (c['nr_cnpj_cpf'] or '').strip() or None,
    'ctes_12m': c['qt'], 'receita_12m': n(c['receita']), 'resultado_12m': n(c['resultado']),
    'ticket_medio': round(n(c['receita']) / c['qt'], 2) if c['qt'] else 0.0,
    'participacao_receita_pct': pct(n(c['receita']), tot_rec_12),
} for c in cli]
conc = run('clientes_top', """
with t as (
  select cd_pessoa_pagador, sum(vl_total) r
  from ctrc where dt_cancelamento is null and dt_emissao >= current_date - interval '12 months'
  group by 1
), tot as (select sum(r) total, count(*) clientes from t)
select (select sum(r) from (select r from t order by r desc limit 5) x) top5,
       (select sum(r) from (select r from t order by r desc limit 10) y) top10,
       (select sum(r) from (select r from t order by r desc limit 20) z) top20,
       total, clientes from tot
""")[0]
R['concentracao_clientes'] = {
    'clientes_ativos_12m': conc['clientes'],
    'receita_12m': n(conc['total']),
    'top5_pct': pct(n(conc['top5']), n(conc['total'])),
    'top10_pct': pct(n(conc['top10']), n(conc['total'])),
    'top20_pct': pct(n(conc['top20']), n(conc['total'])),
    'top5_valor': n(conc['top5']),
}

# ----------------------------------------------------------------- 5. CARTEIRA
CART_SQL = """
select case when dt_vencimento >= current_date then 'a_vencer'
            when current_date - dt_vencimento between 1 and 30  then 'atraso_1_30'
            when current_date - dt_vencimento between 31 and 60 then 'atraso_31_60'
            when current_date - dt_vencimento between 61 and 90 then 'atraso_61_90'
            else 'atraso_mais_90' end faixa,
       count(*) qt, sum(vl_titulo - coalesce(vl_pago,0)) saldo, sum(vl_titulo) bruto
from titulo
where dt_quitacao is null and id_tipo = %s and vl_titulo - coalesce(vl_pago,0) > 0
group by 1
"""
def carteira(tipo, rotulo):
    rows = run('carteira', CART_SQL, (tipo,))
    faixas = {r['faixa']: {'quantidade': r['qt'], 'saldo': n(r['saldo']), 'valor_bruto': n(r['bruto'])} for r in rows}
    for k in ('a_vencer','atraso_1_30','atraso_31_60','atraso_61_90','atraso_mais_90'):
        faixas.setdefault(k, {'quantidade': 0, 'saldo': 0.0, 'valor_bruto': 0.0})
    total = round(sum(v['saldo'] for v in faixas.values()), 2)
    qtot = sum(v['quantidade'] for v in faixas.values())
    venc = round(total - faixas['a_vencer']['saldo'], 2)
    qvenc = qtot - faixas['a_vencer']['quantidade']
    return {'rotulo': rotulo, 'id_tipo': tipo, 'total_aberto': total, 'quantidade': qtot,
            'vencido': venc, 'quantidade_vencida': qvenc,
            'vencido_pct': pct(venc, total), 'faixas': faixas}

R['carteira'] = {'a_receber': carteira(1, 'Titulos a receber (credito)'),
                 'a_pagar':   carteira(2, 'Titulos a pagar (debito)')}
R['carteira']['observacao'] = ('id_tipo=1 identificado como A RECEBER (100% dos titulos deste tipo '
                               'possuem registro em titulo_credito_vencimento; 99,4% dos pagadores de CT-e); '
                               'id_tipo=2 como A PAGAR (100% com registro em titulo_debito). '
                               'Saldo = vl_titulo - vl_pago, apenas titulos sem dt_quitacao e com saldo > 0.')

# ------------------------------------------------------- 6. CONTAS BANCARIAS
cb = run('contas_bancarias', """
with mov as (
  select cd_conta, count(*) qt, min(dt_documento) ini, max(dt_documento) fim,
         count(*) filter (where id_conciliacao = 1) conciliados,
         sum(case when dt_documento >= current_date - 90 and vl_lancamento > 0 then vl_lancamento else 0 end) entradas90,
         sum(case when dt_documento >= current_date - 90 and vl_lancamento < 0 then vl_lancamento else 0 end) saidas90,
         count(*) filter (where dt_documento >= current_date - 90) qt90
  from caixa_financeiro_lancamento_ofx group by 1
)
select m.*, b.nm_banco, b.nr_banco, ct.nr_agencia, ct.nr_conta, ct.nr_digito_conta,
       ct.nm_titular, coalesce(nullif(p.nm_fantasia,''), p.nm_pessoa) titular_pessoa
from mov m
left join conta ct on ct.cd_conta = m.cd_conta
left join banco b on b.cd_banco = ct.cd_banco
left join pessoa p on p.cd_pessoa = ct.cd_pessoa
order by m.qt desc
""")
R['contas_bancarias'] = [{
    'cd_conta': c['cd_conta'], 'banco': c['nm_banco'], 'numero_banco': c['nr_banco'],
    'agencia': (c['nr_agencia'] or '').strip() or None,
    'conta': ((c['nr_conta'] or '').strip() + ('-' + c['nr_digito_conta'].strip() if c['nr_digito_conta'] else '')) or None,
    'titular': c['nm_titular'] or c['titular_pessoa'],
    'movimentos': c['qt'],
    'periodo': {'inicio': str(c['ini'])[:10], 'fim': str(c['fim'])[:10]},
    'movimentos_90d': c['qt90'],
    'entradas_90d': n(c['entradas90']),
    'saidas_90d': n(c['saidas90']),
    'saldo_liquido_90d': round(n(c['entradas90']) + n(c['saidas90']), 2),
    'conciliados': c['conciliados'],
    'conciliados_pct': pct(c['conciliados'], c['qt']),
    'nao_conciliados': c['qt'] - c['conciliados'],
} for c in cb]

# -------------------------------------------------------------------- 7. FROTA
fr = run('frota', """
select (select count(*) from veiculo) veiculos_total,
       (select count(*) from veiculo where id_situacao = 2) veiculos_ativos,
       (select count(distinct cd_veiculo) from ctrc
          where dt_cancelamento is null and dt_emissao >= current_date - interval '12 months'
            and cd_veiculo is not null) veiculos_usados_12m,
       (select count(*) from motorista) motoristas_total,
       (select count(*) from motorista where id_situacao = 2) motoristas_ativos,
       (select count(distinct cd_pessoa_motorista) from ctrc
          where dt_cancelamento is null and dt_emissao >= current_date - interval '12 months'
            and cd_pessoa_motorista is not null) motoristas_usados_12m,
       (select count(*) from funcionario) funcionarios_total,
       (select count(*) from funcionario where dt_demissao is null) funcionarios_ativos,
       (select count(*) from manifesto
          where dt_cancelamento is null and dt_emissao >= current_date - interval '12 months') manifestos_12m,
       (select count(*) from manifesto) manifestos_total,
       (select count(*) from carta_frete
          where dt_emissao >= current_date - interval '12 months') cartas_frete_12m,
       (select count(*) from carta_frete) cartas_frete_total,
       (select coalesce(sum(vl_frete),0) from carta_frete
          where dt_emissao >= current_date - interval '12 months') valor_cartas_frete_12m,
       (select count(*) from viagem) viagens_total
""")[0]
R['frota'] = {k: n(v) for k, v in fr.items()}
R['frota']['observacao_status'] = ('id_situacao=2 confirmado como ATIVO/liberado: 4.457 dos 4.725 veiculos '
                                   'usados em CT-es dos ultimos 90 dias estao nesse status (idem motoristas). '
                                   'Cadastro inclui veiculos e motoristas de terceiros/agregados.')
tv = run('frota', """
select coalesce(tv.ds_tipo_veiculo, 'NAO INFORMADO') tipo, count(distinct c.cd_veiculo) veiculos, count(*) ctes
from ctrc c
left join veiculo v on v.cd_veiculo = c.cd_veiculo
left join tipo_veiculo tv on tv.cd_tipo_veiculo = v.cd_tipo_veiculo
where c.dt_cancelamento is null and c.dt_emissao >= current_date - interval '12 months'
group by 1 order by ctes desc limit 10
""") if run('frota', """select count(*) c from information_schema.columns
              where table_schema='public' and table_name='tipo_veiculo' and column_name='ds_tipo_veiculo'""")[0]['c'] else []
if tv:
    R['frota']['tipos_veiculo_12m'] = [{'tipo': t['tipo'], 'veiculos': t['veiculos'], 'ctes': t['ctes']} for t in tv]

# ---------------------------------------------------------------- 8. ROTAS TOP
rt = run('rotas_top', """
select co.nm_cidade || '/' || uo.ds_sigla origem,
       cd.nm_cidade || '/' || ud.ds_sigla destino,
       count(*) qt, sum(c.vl_total) receita, sum(c.vl_resultado) resultado, sum(c.vl_peso) peso
from ctrc c
join cidade co on co.cd_cidade = c.cd_cidade_origem
join cidade cd on cd.cd_cidade = c.cd_cidade_destino
join uf uo on uo.cd_uf = co.cd_uf
join uf ud on ud.cd_uf = cd.cd_uf
where c.dt_cancelamento is null and c.dt_emissao >= current_date - interval '12 months'
group by 1,2 order by qt desc limit 12
""")
R['rotas_top'] = [{
    'origem': r['origem'], 'destino': r['destino'], 'ctes_12m': r['qt'],
    'receita_12m': n(r['receita']), 'resultado_12m': n(r['resultado']), 'peso_kg': n(r['peso']),
    'ticket_medio': round(n(r['receita']) / r['qt'], 2) if r['qt'] else 0.0,
} for r in rt]

# ----------------------------------------------------------------- 9. ALERTAS
al = []

a = run('alertas', """
select count(*) qt, sum(vl_resultado) prejuizo, sum(vl_total) receita
from ctrc where dt_cancelamento is null and dt_emissao >= current_date - interval '12 months'
  and vl_resultado < 0
""")[0]
tot12 = run('alertas', """select count(*) qt from ctrc where dt_cancelamento is null
              and dt_emissao >= current_date - interval '12 months'""")[0]['qt']
al.append({'titulo': 'CT-es com resultado negativo nos ultimos 12 meses', 'severidade': 'critica',
           'valor': abs(n(a['prejuizo'])), 'quantidade': a['qt'],
           'descricao': f"{a['qt']} CT-es ({pct(a['qt'], tot12)}% do total de {tot12}) fecharam com prejuizo, "
                        f"somando R$ {abs(n(a['prejuizo'])):,.2f} de resultado negativo."})

a = run('alertas', """
select count(*) qt, sum(vl_titulo - coalesce(vl_pago,0)) saldo
from titulo where id_tipo = 1 and dt_quitacao is null
  and vl_titulo - coalesce(vl_pago,0) > 0 and current_date - dt_vencimento > 90
""")[0]
al.append({'titulo': 'Titulos a receber vencidos ha mais de 90 dias', 'severidade': 'critica',
           'valor': n(a['saldo']), 'quantidade': a['qt'],
           'descricao': f"{a['qt']} titulos a receber, R$ {n(a['saldo']):,.2f}, com atraso superior a 90 dias - "
                        f"candidatos a provisao de perda."})

a = run('alertas', """
select count(*) qt, sum(vl_titulo - coalesce(vl_pago,0)) saldo
from titulo where id_tipo = 2 and dt_quitacao is null
  and vl_titulo - coalesce(vl_pago,0) > 0 and current_date - dt_vencimento > 90
""")[0]
al.append({'titulo': 'Titulos a pagar vencidos ha mais de 90 dias', 'severidade': 'atencao',
           'valor': n(a['saldo']), 'quantidade': a['qt'],
           'descricao': f"{a['qt']} obrigacoes em aberto, R$ {n(a['saldo']):,.2f}, vencidas ha mais de 90 dias."})

a = run('alertas', """
select count(*) filter (where coalesce(id_conciliacao,0) <> 1) nao_conc, count(*) total,
       sum(abs(vl_lancamento)) filter (where coalesce(id_conciliacao,0) <> 1) valor
from caixa_financeiro_lancamento_ofx where dt_documento >= current_date - 60
""")[0]
al.append({'titulo': 'Movimentos bancarios nao conciliados nos ultimos 60 dias',
           'severidade': 'critica' if pct(a['nao_conc'], a['total']) > 30 else 'atencao',
           'valor': n(a['valor']), 'quantidade': a['nao_conc'],
           'descricao': f"{a['nao_conc']} de {a['total']} lancamentos OFX ({pct(a['nao_conc'], a['total'])}%) "
                        f"seguem com id_conciliacao=0 (nao conciliados), movimentando R$ {n(a['valor']):,.2f} em valor absoluto."})

al.append({'titulo': 'Concentracao de receita nos 5 maiores clientes',
           'severidade': 'critica' if R['concentracao_clientes']['top5_pct'] >= 50 else 'atencao',
           'valor': R['concentracao_clientes']['top5_valor'], 'quantidade': 5,
           'descricao': f"Os 5 maiores pagadores respondem por {R['concentracao_clientes']['top5_pct']}% da receita "
                        f"de 12 meses (R$ {R['concentracao_clientes']['top5_valor']:,.2f}) entre "
                        f"{R['concentracao_clientes']['clientes_ativos_12m']} clientes ativos."})

a = run('alertas', """
select count(*) qt, sum(vl_total) receita
from ctrc where dt_cancelamento is null and dt_emissao >= current_date - interval '12 months'
  and coalesce(vl_custo,0) = 0
""")[0]
al.append({'titulo': 'CT-es sem custo lancado no campo vl_custo', 'severidade': 'atencao',
           'valor': n(a['receita']), 'quantidade': a['qt'],
           'descricao': f"{a['qt']} CT-es ({pct(a['qt'], tot12)}%) dos ultimos 12 meses estao com vl_custo zerado "
                        f"(R$ {n(a['receita']):,.2f} de receita); o campo e inutilizado e o custo real precisa ser "
                        f"lido de carta_frete, o que quebra qualquer relatorio de margem baseado em vl_custo."})

a = run('alertas', """
select count(*) qt, sum(c.vl_total) valor from ctrc c
where c.dt_cancelamento is null and c.dt_emissao >= current_date - interval '12 months'
  and not exists (select 1 from carta_frete cf where cf.cd_ctrc = c.cd_ctrc)
""")[0]
al.append({'titulo': 'CT-es sem carta-frete vinculada (sem custo de tracao rastreavel)',
           'severidade': 'atencao', 'valor': n(a['valor']), 'quantidade': a['qt'],
           'descricao': f"{a['qt']} CT-es dos ultimos 12 meses ({pct(a['qt'], tot12)}%), R$ {n(a['valor']):,.2f} "
                        f"de receita, nao possuem carta-frete associada - custo do frete nao rastreavel."})

a = run('alertas', """
select count(*) qt, sum(vl_total) valor from ctrc
where dt_emissao >= current_date - interval '12 months' and dt_cancelamento is not null
""")[0]
al.append({'titulo': 'CT-es cancelados nos ultimos 12 meses', 'severidade': 'informativa',
           'valor': n(a['valor']), 'quantidade': a['qt'],
           'descricao': f"{a['qt']} CT-es cancelados no periodo, equivalentes a R$ {n(a['valor']):,.2f} "
                        f"em documentos emitidos e desfeitos."})

a = run('alertas', """
select count(*) qt, sum(vl_total) valor from ctrc
where dt_cancelamento is null and dt_emissao >= current_date - interval '12 months'
  and cd_pessoa_motorista is null
""")[0]
if a['qt']:
    al.append({'titulo': 'CT-es sem motorista vinculado', 'severidade': 'informativa',
               'valor': n(a['valor']), 'quantidade': a['qt'],
               'descricao': f"{a['qt']} CT-es dos ultimos 12 meses nao possuem cd_pessoa_motorista preenchido, "
                            f"prejudicando rastreabilidade operacional."})

a = run('alertas', """
select count(*) qt, sum(vl_saldo) valor from carta_frete
where dt_emissao >= current_date - interval '12 months'
  and dt_retorno_comprovante is null and coalesce(vl_saldo,0) > 0
""")[0]
al.append({'titulo': 'Cartas-frete sem retorno de comprovante e com saldo em aberto',
           'severidade': 'atencao', 'valor': n(a['valor']), 'quantidade': a['qt'],
           'descricao': f"{a['qt']} cartas-frete emitidas nos ultimos 12 meses seguem sem comprovante de entrega "
                        f"e com R$ {n(a['valor']):,.2f} de saldo a pagar retido."})

a = run('alertas', """
select count(*) qt, sum(vl_titulo - coalesce(vl_pago,0)) saldo from titulo
where id_tipo = 1 and dt_quitacao is null and vl_titulo - coalesce(vl_pago,0) > 0
  and dt_vencimento < current_date
""")[0]
al.append({'titulo': 'Inadimplencia total da carteira a receber',
           'severidade': 'critica' if R['carteira']['a_receber']['vencido_pct'] > 20 else 'atencao',
           'valor': n(a['saldo']), 'quantidade': a['qt'],
           'descricao': f"R$ {n(a['saldo']):,.2f} em {a['qt']} titulos vencidos representam "
                        f"{R['carteira']['a_receber']['vencido_pct']}% da carteira a receber em aberto."})

a = run('alertas', """
select count(*) qt, sum(abs(o.vl_lancamento)) valor, count(distinct o.cd_conta) contas
from caixa_financeiro_lancamento_ofx o
join conta ct on ct.cd_conta = o.cd_conta
join banco b on b.cd_banco = ct.cd_banco
where b.nr_banco = 450 and coalesce(o.id_conciliacao,0) <> 1
""")[0]
al.append({'titulo': 'Contas GOFLUX/FitBank praticamente sem conciliacao', 'severidade': 'critica',
           'valor': n(a['valor']), 'quantidade': a['qt'],
           'descricao': f"{a['qt']} lancamentos em {a['contas']} contas GOFLUX/FitBank (banco 450) estao nao "
                        f"conciliados, R$ {n(a['valor']):,.2f} - as contas 8189 e 16061 tem menos de 10% de "
                        f"conciliacao, concentrando quase todo o backlog de conciliacao da empresa."})

a = run('alertas', """
with g as (
  select left(p.nr_cnpj_cpf, 8) raiz, sum(c.vl_total) receita, count(*) qt
  from ctrc c join pessoa p on p.cd_pessoa = c.cd_pessoa_pagador
  where c.dt_cancelamento is null and c.dt_emissao >= current_date - interval '12 months'
    and p.nr_cnpj_cpf is not null and length(trim(p.nr_cnpj_cpf)) = 14
  group by 1
)
select raiz, receita, qt from g order by receita desc limit 1
""")[0]
al.append({'titulo': 'Dependencia de um unico grupo economico pagador', 'severidade': 'critica',
           'valor': n(a['receita']), 'quantidade': a['qt'],
           'descricao': f"Agrupando pagadores pela raiz de CNPJ, o grupo {a['raiz']} (MOTZ TRANSPORTES) responde por "
                        f"R$ {n(a['receita']):,.2f} em {a['qt']} CT-es, ou {pct(n(a['receita']), tot_rec_12)}% da "
                        f"receita de 12 meses - risco de dependencia comercial."})
R['concentracao_grupos'] = {'maior_grupo_raiz_cnpj': a['raiz'], 'receita_12m': n(a['receita']),
                            'ctes_12m': a['qt'], 'participacao_pct': pct(n(a['receita']), tot_rec_12)}

meses_neg = [m for m in R['faturamento_mensal'][:-1] if m['resultado'] < 0]
if meses_neg:
    al.append({'titulo': 'Meses com resultado consolidado negativo', 'severidade': 'atencao',
               'valor': round(sum(m['resultado'] for m in meses_neg), 2), 'quantidade': len(meses_neg),
               'descricao': f"{len(meses_neg)} mes(es) da serie de 24 meses fecharam com resultado negativo: "
                            + ', '.join(m['mes'] for m in meses_neg) + '.'})

R['alertas'] = sorted(al, key=lambda x: {'critica': 0, 'atencao': 1, 'informativa': 2}[x['severidade']])

# --------------------------------------------------------------- NAO APURADO
R['nao_apurado'] = {}
R['nao_apurado']['documentos_pessoa'] = ('Nao existem tabelas pessoa_juridica/pessoa_fisica neste banco; '
                                         'CNPJ/CPF foi lido diretamente de pessoa.nr_cnpj_cpf.')
R['nao_apurado']['nm_fantasia_filiais'] = ('Nenhuma filial possui nm_fantasia preenchido em pessoa; '
                                            'foi usada a razao social (nm_pessoa) como nome.')
R['nao_apurado']['dt_lancamento_ofx'] = ('caixa_financeiro_lancamento_ofx.dt_lancamento reflete o instante da '
                                          'importacao do arquivo, nao a data do movimento; todas as metricas de '
                                          'periodo usam dt_documento, que e a data real do lancamento bancario.')
R['nao_apurado']['serie_24_meses'] = ('A janela de 24 meses vai de 2024-10 a 2026-09. O banco tem CT-es desde 2024-08-26, '
                                       'mas os meses 2024-08 e 2024-09 ficam fora da janela; 2026-09 e parcial (ate o dia 5).')
R['nao_apurado']['conciliacao_ofx'] = ('id_conciliacao e um flag 0/1 (nao nulo em 100% das linhas), nao uma FK. '
                                       'O percentual de conciliacao foi calculado como id_conciliacao = 1.')
R['nao_apurado']['saldo_bancario'] = ('Nao foi apurado saldo contabil das contas: o OFX importado nao traz campo '
                                       'de saldo e nao foi localizada tabela de saldo consolidado por conta confiavel.')

with open('/home/user/workspace/cortex/dados/retrato.json', 'w', encoding='utf-8') as f:
    json.dump(R, f, ensure_ascii=False, indent=2)
with open('/home/user/workspace/cortex/dados/_queries.json', 'w', encoding='utf-8') as f:
    json.dump(Q, f, ensure_ascii=False, indent=2)
print('OK')
print(json.dumps({k: (v if not isinstance(v, (list, dict)) else f'<{type(v).__name__} {len(v)}>') for k, v in R.items()}, ensure_ascii=False, indent=1))
