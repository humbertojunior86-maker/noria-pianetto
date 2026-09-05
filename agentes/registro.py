"""Cadastro de agentes e seus executores.

Um agente é código determinístico + ferramentas declaradas. O adaptador de
modelo é opcional: sem ele o agente continua entregando, porque o raciocínio
está nas regras, não no texto gerado. Agente sem ferramenta configurada aparece
como 'sem_integracao' e diz qual é a limitação — nunca finge que opera.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

from ferramentas import base as fb
from nucleo import bd
from nucleo.formato import brl, pct


@dataclass
class Entrega:
    """O que um executor devolve. É declaração, não aprovação."""
    status: str                       # concluida | parcial | bloqueada
    resumo: str
    resultado: dict
    afirmacoes: list[dict] = field(default_factory=list)
    evidencias: list[dict] = field(default_factory=list)
    incertezas: list[str] = field(default_factory=list)
    conflitos: list[str] = field(default_factory=list)
    pendencias: list[str] = field(default_factory=list)
    complemento: dict | None = None
    bruto: dict = field(default_factory=dict)   # material para o verificador


@dataclass
class Definicao:
    id: str
    nome: str
    papel: str
    area: str
    promessa: str
    versao: int
    competencias: list[str]
    ferramentas: list[str]
    acoes: list[str]                  # ferramenta.operacao permitidas
    entradas: dict
    saidas: dict
    limites: dict
    criterios: list[str]
    executor: Callable[..., Entrega] | None = None

    def situacao(self) -> tuple[str, str | None]:
        if self.executor is None:
            return "sem_integracao", "executor ainda não implementado"
        for fid in self.ferramentas:
            f = fb.obter(fid)
            if f is None:
                return "sem_integracao", f"ferramenta '{fid}' não registrada"
            if not f.disponivel():
                return "sem_integracao", f.limitacao
        return "habilitado", None


_REG: dict[str, Definicao] = {}


def registrar(d: Definicao) -> Definicao:
    _REG[d.id] = d
    return d


def obter(id_: str) -> Definicao | None:
    return _REG.get(id_)


def todos() -> list[Definicao]:
    return sorted(_REG.values(), key=lambda d: (d.area, d.nome))


def sincronizar(empresa_id: int) -> None:
    """Grava o cadastro no banco. Missão em curso fixa a versão que usou."""
    for d in todos():
        sit, _lim = d.situacao()
        if not bd.linha("SELECT id FROM agente WHERE id=?", (d.id,)):
            bd.inserir("agente", {
                "id": d.id, "nome": d.nome, "papel": d.papel,
                "area": d.area, "promessa": d.promessa, "ativo": 1})
        ex = bd.linha(
            "SELECT id FROM agente_versao WHERE agente_id=? AND versao=?",
            (d.id, d.versao))
        campos = {
            "competencias": bd.j(d.competencias), "ferramentas": bd.j(d.ferramentas),
            "escopo_dados": bd.j({"empresa_id": empresa_id}),
            "entradas": bd.j(d.entradas), "saidas": bd.j(d.saidas),
            "limites": bd.j(d.limites), "criterios": bd.j(d.criterios),
            "situacao": sit,
        }
        if ex:
            bd.atualizar("agente_versao", ex["id"], campos)
        else:
            bd.inserir("agente_versao", {
                "agente_id": d.id, "versao": d.versao,
                **campos, "criada_em": bd.agora()})


# ===========================================================================
# Executores
# ===========================================================================
def _ev(tipo: str, origem: str, referencia: str, trecho: str, raiz: str,
        consultada_em: str) -> dict:
    return {"tipo": tipo, "origem": origem, "referencia": referencia,
            "trecho": trecho, "raiz": raiz, "consultada_em": consultada_em}


def exec_conciliador(*, empresa_id, missao_id, tarefa_id, entradas,
                     acoes) -> Entrega:
    """Confronta o extrato OFX importado com os lançamentos do ATUA.

    Resultado binário e recomputável: cada movimento do extrato tem par no
    ATUA ou não tem. Nada aqui depende de interpretação.
    """
    cd_conta = entradas.get("cd_conta")
    data = entradas.get("data")
    if not cd_conta or not data:
        return Entrega("bloqueada", "faltou conta ou data",
                       {}, pendencias=["informar cd_conta e data"])

    ofx = fb.rodar("atua", "ofx.movimentos_do_dia",
                   {"cd_conta": cd_conta, "data": data},
                   empresa_id=empresa_id, missao_id=missao_id,
                   tarefa_id=tarefa_id, acoes_permitidas=acoes)
    if not ofx.ok:
        return Entrega("bloqueada", f"extrato indisponível: {ofx.erro}", {},
                       pendencias=[ofx.erro or "falha na consulta do extrato"])

    par = fb.rodar("atua", "lancamento.pareado_com_extrato",
                   {"cd_conta": cd_conta, "data": data},
                   empresa_id=empresa_id, missao_id=missao_id,
                   tarefa_id=tarefa_id, acoes_permitidas=acoes)
    if not par.ok:
        return Entrega("bloqueada", f"pareamento indisponível: {par.erro}", {},
                       pendencias=[par.erro or "falha na consulta de pareamento"])

    lo = ofx.dados["linhas"]
    lp = par.dados["linhas"]

    # Um movimento pode ser quitado por mais de um lançamento: agrupa por id.
    por_mov: dict = {}
    for l in lp:
        por_mov.setdefault(l["cd_conciliado"], []).append(l)

    sem_par_extrato, divergentes = [], []
    for cid, itens in por_mov.items():
        base = itens[0]
        quitas = [i for i in itens if i.get("cd_lancamento")]
        if not quitas:
            sem_par_extrato.append({
                "cd_conciliado": cid, "data": str(base.get("data")),
                "ds_lancamento": base.get("ds_extrato"),
                "vl_lancamento": base.get("vl_extrato")})
            continue
        # Só dá para comparar valor quando cada lançamento quita um único
        # movimento. Lançamento que quita vários tem valor agregado — comparar
        # ali produziria alarme falso.
        if any(int(i.get("qt_movimentos") or 0) != 1 for i in quitas):
            continue
        v_ext = abs(float(base.get("vl_extrato") or 0))
        v_erp = sum(abs(float(i.get("vl_erp") or 0)) for i in quitas)
        if abs(v_ext - v_erp) > 0.01:
            divergentes.append({
                "cd_conciliado": cid, "data": str(base.get("data")),
                "ds_lancamento": base.get("ds_extrato"),
                "vl_extrato": round(v_ext, 2), "vl_erp": round(v_erp, 2),
                "diferenca": round(v_ext - v_erp, 2),
                "lancamentos": len(quitas)})

    total_ofx = sum(abs(float(l.get("vl_lancamento") or 0)) for l in lo)
    valor_aberto = sum(abs(float(l.get("vl_lancamento") or 0))
                       for l in sem_par_extrato)
    n_mov = len(por_mov)
    taxa = (1 - len(sem_par_extrato) / n_mov) if n_mov else 1.0

    resultado = {
        "cd_conta": cd_conta, "data": data,
        "movimentos_extrato": n_mov,
        "lancamentos_erp": sum(1 for l in lp if l.get("cd_lancamento")),
        "sem_par_extrato": len(sem_par_extrato),
        "valor_divergente": len(divergentes),
        "valor_movimentado": round(total_ofx, 2),
        "valor_sem_par": round(valor_aberto, 2),
        "taxa_conciliacao": round(taxa, 4),
        "amostra_sem_par": (sem_par_extrato + divergentes)[:20],
    }

    evid = [
        _ev("consulta", "atua:ofx.movimentos_do_dia", ofx.referencia,
            f"{len(lo)} movimento(s) no extrato da conta {cd_conta} em {data}",
            "atua:caixa_financeiro_lancamento_ofx", ofx.dados["consultada_em"]),
        _ev("consulta", "atua:lancamento.pareado_com_extrato", par.referencia,
            f"{sum(1 for l in lp if l.get('cd_lancamento'))} lançamento(s) do "
            f"ATUA quitando movimentos do extrato da conta {cd_conta} em {data}",
            "atua:caixa_financeiro_lancamento", par.dados["consultada_em"]),
    ]

    afirm = [
        {"texto": f"O extrato da conta {cd_conta} em {data} tem {n_mov} "
                  f"movimento(s), somando {brl(total_ofx)}.",
         "natureza": "fato", "evidencia": 0},
        {"texto": f"{len(sem_par_extrato)} movimento(s) do extrato não têm "
                  f"lançamento correspondente no ATUA, somando "
                  f"{brl(valor_aberto)}.",
         "natureza": "fato", "evidencia": 1},
    ]
    if divergentes:
        afirm.append({
            "texto": f"{len(divergentes)} movimento(s) estão conciliados no ATUA "
                     f"mas com valor diferente do extrato.",
            "natureza": "fato", "evidencia": 1})

    pend, incert = [], []
    if not lo:
        pend.append(f"não há extrato importado para a conta {cd_conta} em {data}")
    incert.append("o pareamento lido é o do próprio ATUA (ar_cd_conciliado); "
                  "um vínculo feito no sistema com o título errado aparece aqui "
                  "como conciliado")

    status = "concluida" if lo else "bloqueada"
    return Entrega(
        status,
        (f"Conciliação da conta {cd_conta} em {data}: {pct(taxa)} pareado, "
         f"{len(sem_par_extrato)} em aberto." if lo else
         f"Conta {cd_conta}: nenhum movimento de extrato importado em {data} — "
         f"não há o que conciliar, e isso pode ser o próprio problema."),
        resultado, afirm, evid, incert, [], pend,
        bruto={"ofx": ofx.dados, "par": par.dados},
    )


def exec_carteira_vencida(*, empresa_id, missao_id, tarefa_id, entradas,
                          acoes) -> Entrega:
    """Levanta títulos vencidos acima de N dias, a receber ou a pagar."""
    id_tipo = int(entradas.get("id_tipo", 1))
    dias = int(entradas.get("dias", 90))
    r = fb.rodar("atua", "titulo.vencidos", {"id_tipo": id_tipo, "dias": dias},
                 empresa_id=empresa_id, missao_id=missao_id,
                 tarefa_id=tarefa_id, acoes_permitidas=acoes)
    if not r.ok:
        return Entrega("bloqueada", f"consulta indisponível: {r.erro}", {},
                       pendencias=[r.erro or "falha"])
    linhas = r.dados["linhas"]
    lado = "a receber" if id_tipo == 1 else "a pagar"

    # A consulta corta em 500 linhas. Se cortou, o número de linhas trazidas
    # NÃO é o número de títulos — dizer que são 500 seria falso. Por isso a
    # própria consulta devolve o total real da janela.
    total_geral = int(linhas[0]["total_geral"]) if linhas else 0
    total = float(linhas[0]["total_saldo"] or 0) if linhas else 0.0
    truncado = total_geral > len(linhas)

    resultado = {"quantidade": total_geral, "total": round(total, 2),
                 "linhas_trazidas": len(linhas), "truncado": truncado,
                 "dias": dias, "lado": lado, "amostra": linhas[:15]}
    evid = [_ev("consulta", "atua:titulo.vencidos", r.referencia,
                f"{total_geral} título(s) {lado} vencidos há mais de {dias} dias",
                "atua:titulo", r.dados["consultada_em"])]
    afirm = [{"texto": f"Há {total_geral} título(s) {lado} vencidos há mais de "
                       f"{dias} dias, somando {brl(total)}.",
              "natureza": "fato", "evidencia": 0}]
    incert = []
    if truncado:
        incert.append(
            f"o detalhamento traz os {len(linhas)} maiores; a contagem e a soma "
            f"acima são do conjunto inteiro ({total_geral} títulos)")
    return Entrega("concluida",
                   f"{total_geral} título(s) {lado} vencidos +{dias}d, "
                   f"{brl(total)} em aberto.",
                   resultado, afirm, evid, incert, bruto={"linhas": linhas})


# ===========================================================================
# Cadastro
# ===========================================================================
registrar(Definicao(
    id="tesouraria.conciliador", nome="Marta", papel="Analista de Tesouraria",
    area="Financeiro & Tesouraria",
    promessa="O caixa fecha antes de você perguntar.", versao=1,
    competencias=["conciliacao-ofx", "saldo-diario", "divergencia-bancaria"],
    ferramentas=["atua"],
    acoes=["atua.ofx.movimentos_do_dia", "atua.lancamento.pareado_com_extrato",
           "atua.ofx.resumo_periodo", "atua.conta.listar"],
    entradas={"cd_conta": "int", "data": "date"},
    saidas={"sem_par_extrato": "int", "valor_divergente": "int",
            "valor_sem_par": "num", "taxa_conciliacao": "num"},
    limites={"tempo_s": 120, "custo_centavos": 0},
    criterios=["pareamento recomputável", "período coberto", "sem duplicidade"],
    executor=exec_conciliador,
))

registrar(Definicao(
    id="cobranca.carteira", nome="Otávio", papel="Analista de Cobrança",
    area="Financeiro & Tesouraria",
    promessa="Nenhum título vence sem alguém saber.", versao=1,
    competencias=["carteira-vencida", "risco-de-cliente"],
    ferramentas=["atua"], acoes=["atua.titulo.vencidos"],
    entradas={"id_tipo": "int", "dias": "int"},
    saidas={"quantidade": "int", "total": "num"},
    limites={"tempo_s": 90, "custo_centavos": 0},
    criterios=["soma confere", "contagem confere"],
    executor=exec_carteira_vencida,
))

# Declarados, sem ferramenta ligada. Aparecem na interface com a limitação
# escrita — é o teste de aceitação nº 15.
for _id, _nome, _papel, _area, _prom, _fer in [
    ("contas.pagar", "Íris", "Analista de Contas a Pagar",
     "Financeiro & Tesouraria", "Nada é pago duas vezes.", ["atua"]),
    ("controladoria.margem", "Caio", "Controller", "Controladoria & Custos",
     "A margem que existe atrás de cada conhecimento.", ["atua"]),
    ("auditoria.interna", "Lívia", "Auditora Interna", "Controladoria & Custos",
     "O erro aparece no mesmo dia, não no fechamento.", ["atua", "documento"]),
    ("comercial.faturamento", "Bruno", "Analista de Faturamento",
     "Comercial & Faturamento", "Todo frete entregue vira fatura.", ["atua"]),
    ("comercial.inteligencia", "Sofia", "Inteligência Comercial",
     "Comercial & Faturamento", "Você sabe exatamente de quem depende.", ["atua"]),
    ("frota.resultado", "Davi", "Analista de Frota", "Operações & Frota",
     "O veículo que dá prejuízo não passa despercebido.", ["atua"]),
    ("frota.viagem", "Nina", "Analista de Viagem", "Operações & Frota",
     "Adiantamento, saldo e acerto sempre batendo.", ["atua"]),
    ("frota.combustivel", "Rui", "Analista de Combustível", "Operações & Frota",
     "Cada litro tem dono e tem destino.", ["x7bank"]),
    ("fiscal.documento", "Alan", "Analista Fiscal", "Fiscal & Contábil",
     "CT-e e MDF-e sem pendência com o fisco.", ["atua"]),
    ("fiscal.tributos", "Téo", "Analista Tributário", "Fiscal & Contábil",
     "Nenhum crédito tributário fica na mesa.", ["atua", "documento"]),
    ("gente.jornada", "Paula", "Analista de Jornada", "Gente & Conformidade",
     "A jornada registrada é a jornada real.", ["atua"]),
    ("gente.documentos", "Clara", "Analista de Documentos",
     "Gente & Conformidade", "Ninguém roda com documento vencido.", ["atua"]),
    ("processos.rotina", "Otto", "Analista de Processos",
     "Gente & Conformidade", "A rotina que não roda aparece no mesmo dia.",
     ["documento"]),
]:
    registrar(Definicao(
        id=_id, nome=_nome, papel=_papel, area=_area, promessa=_prom, versao=1,
        competencias=[], ferramentas=_fer, acoes=[], entradas={}, saidas={},
        limites={"tempo_s": 120, "custo_centavos": 0}, criterios=[],
        executor=None,
    ))
