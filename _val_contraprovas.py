import json,time,decimal,datetime
from ferramentas import atua, base as fb

def dec(o):
    if isinstance(o,decimal.Decimal): return float(o)
    if isinstance(o,(datetime.date,datetime.datetime)): return str(o)
    raise TypeError(str(type(o)))

casos=[
 ('contraprova.cte_sem_titulo_situacao',{}),
 ('contraprova.cte_sem_titulo_situacao',{'carencia_dias':7}),
 ('faturamento.cte_sem_titulo',{}),
 ('faturamento.cte_sem_titulo',{'carencia_dias':7}),
 ('contraprova.cte_pendente_faturado',{}),
 ('fiscal.cte_pendente',{}),
 ('contraprova.duplicidade_documento',{}),
 ('pagar.duplicidade_suspeita',{}),
 ('contraprova.margem_frota_propria',{}),
 ('controladoria.margem_por_cte',{}),
]
out=[]
for op,par in casos:
    t0=time.time(); r=fb.rodar('atua',op,par,empresa_id=1); dt=round(time.time()-t0,2)
    print(f'{op} {par} ok={r.ok} erro={r.erro} {dt}s linhas={r.linhas}')
    out.append({'operacao':op,'parametros':par,'ok':r.ok,'erro':r.erro,
                'segundos':dt,'qt_linhas':r.linhas,
                'consultada_em':(r.dados or {}).get('consultada_em'),
                'linhas':(r.dados or {}).get('linhas')})
json.dump(out,open('/home/user/workspace/teste_contraprovas.json','w'),
          ensure_ascii=False,indent=1,default=dec)
print('gravado')
