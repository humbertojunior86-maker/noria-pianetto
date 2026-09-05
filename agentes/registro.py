"""Cadastro de agentes e seus executores.

Um agente é código determinístico + ferramentas declaradas. O adaptador de
modelo é opcional: sem ele o agente continua entregando, porque o raciocínio
está nas regras, não no texto gerado. Agente sem ferramenta configurada aparece
como 'sem_integracao' e diz qual é a limitação — nunca finge que opera.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
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
    # Contraprova: recalcula o número de OUTRO agente por um caminho diferente
    # do banco. Recebe `alvo` (a entrega que está sendo contestada) além dos
    # argumentos normais. Um agente pode ter auditor sem ter executor: quem só
    # revisa não abre missão própria, e isso é dito em vez de escondido.
    auditor: Callable[..., Entrega] | None = None

    def situacao(self) -> tuple[str, str | None]:
        if self.executor is None:
            if self.auditor is not None:
                return ("revisor",
                        "contesta o trabalho de outros agentes, mas ainda não "
                        "abre missão própria")
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


def _f(v) -> float:
    """Número do Postgres chega como Decimal; aritmética exige float."""
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _linha(l: dict, campos: tuple[str, ...]) -> dict:
    """Recorta a linha para a amostra da tela.

    Data e Decimal viram texto/número aqui, e não no front: a interface não pode
    ser responsável por adivinhar o tipo que o ERP devolveu. Texto continua
    texto — CNPJ com zero à esquerda convertido em número deixa de ser CNPJ.
    """
    def _valor(v):
        if v is None or isinstance(v, (bool, int, float, str)):
            return v
        if isinstance(v, Decimal):
            return round(float(v), 2)
        if isinstance(v, list):
            return [_valor(x) for x in v]
        return str(v)   # data, hora e o que mais o driver devolver

    return {c: _valor(l.get(c)) for c in campos}


def exec_pagar_duplicidade(*, empresa_id, missao_id, tarefa_id, entradas,
                           acoes) -> Entrega:
    """Fila de conferência de possível pagamento repetido a fornecedor.

    O que a consulta encontra é coincidência — mesmo fornecedor, mesmo valor,
    vencimentos próximos. Dois caminhões iguais comprados no mesmo dia do mesmo
    revendedor têm exatamente esta assinatura. Por isso nenhuma afirmação deste
    executor sai como fato: sai como indício, ordenado por dinheiro em risco.
    """
    dias = int(entradas.get("dias", 5))
    dias_retro = int(entradas.get("dias_retro", 365))
    vl_min = float(entradas.get("vl_min", 100))
    max_parcelas = int(entradas.get("max_parcelas", 3))
    limite = int(entradas.get("limite", 200))
    r = fb.rodar("atua", "pagar.duplicidade_suspeita",
                 {"dias": dias, "dias_retro": dias_retro, "vl_min": vl_min,
                  "max_parcelas": max_parcelas, "limite": limite,
                  "cd_pessoa_filial": entradas.get("cd_pessoa_filial")},
                 empresa_id=empresa_id, missao_id=missao_id,
                 tarefa_id=tarefa_id, acoes_permitidas=acoes)
    if not r.ok:
        return Entrega("bloqueada", f"consulta indisponível: {r.erro}", {},
                       pendencias=[r.erro or "falha na varredura de duplicidade"])
    linhas = r.dados["linhas"]

    # A consulta não devolve total da janela: o corte por `limite` esconde o
    # tamanho real do conjunto. Quando o limite é atingido, os números abaixo
    # valem para os grupos trazidos — dizer que são todos seria falso.
    truncado = len(linhas) >= limite

    grupos = len(linhas)
    titulos = sum(int(l["qt_titulos"] or 0) for l in linhas)
    exposicao = sum(_f(l["vl_exposicao"]) for l in linhas)
    altas = [l for l in linhas if l.get("confianca") == "alta"]
    exposicao_alta = sum(_f(l["vl_exposicao"]) for l in altas)
    pago_alta = sum(_f(l["vl_ja_pago"]) for l in altas)

    campos = ("fornecedor", "nr_cnpj_cpf", "vl_titulo", "qt_titulos",
              "vl_exposicao", "qt_pagos", "vl_ja_pago", "venc_ini", "venc_fim",
              "dias_entre", "confianca", "ar_cd_titulo")
    resultado = {
        "grupos": grupos, "titulos": titulos,
        "exposicao": round(exposicao, 2),
        "grupos_confianca_alta": len(altas),
        "exposicao_confianca_alta": round(exposicao_alta, 2),
        "valor_ja_pago_confianca_alta": round(pago_alta, 2),
        "janela_dias": dias, "dias_retro": dias_retro,
        "valor_minimo": round(vl_min, 2), "max_parcelas": max_parcelas,
        "linhas_trazidas": grupos, "truncado": truncado,
        "amostra": [_linha(l, campos) for l in linhas[:15]],
    }
    evid = [_ev("consulta", "atua:pagar.duplicidade_suspeita", r.referencia,
                f"{grupos} grupo(s) de títulos a pagar com fornecedor e valor "
                f"repetidos e vencimentos a menos de {dias} dias de distância, "
                f"nos últimos {dias_retro} dias",
                "atua:titulo", r.dados["consultada_em"])]
    afirm = [
        {"texto": f"Há {grupos} grupo(s) de títulos a pagar que repetem o mesmo "
                  f"fornecedor e o mesmo valor com vencimentos a menos de "
                  f"{dias} dias de distância — {titulos} títulos no total, com "
                  f"exposição de {brl(exposicao)} caso cada repetição seja "
                  f"mesmo um pagamento a mais. É coincidência a conferir, não "
                  f"duplicidade comprovada.",
         "natureza": "indicio", "evidencia": 0},
    ]
    if altas:
        afirm.append({
            "texto": f"{len(altas)} desses grupos vencem todos no mesmo dia e "
                     f"já estão inteiramente quitados: {brl(pago_alta)} saíram "
                     f"do caixa nesses grupos, dos quais {brl(exposicao_alta)} "
                     f"correspondem às repetições.",
            "natureza": "indicio", "evidencia": 0})

    incert = [
        "a consulta prova coincidência, não duplicidade: dois veículos iguais "
        "comprados no mesmo dia do mesmo revendedor geram exatamente esta "
        "assinatura, e os maiores valores da lista têm essa cara",
        "seguro por veículo é falso positivo estrutural — a seguradora emite "
        "uma apólice por placa e frota igual gera prêmio igual",
        f"títulos abaixo de {brl(vl_min)} ficaram fora, então duplicidade "
        f"pequena e repetitiva (tarifa bancária, pedágio avulso) não aparece",
        "o agrupamento é por valor exato com duas casas: repetição com centavo "
        "de diferença por juro ou desconto escapa",
        f"parcelamentos em mais de {max_parcelas} vezes foram descartados para "
        f"tirar financiamento de frota da frente; duplicidade dentro de uma "
        f"compra parcelada em 4 vezes ou mais não entra aqui",
        "nada aqui olhou o extrato bancário: dois títulos quitados no ERP não "
        "são prova de duas saídas de caixa — a confirmação é abrir os títulos e "
        "conferir o pagamento no banco",
    ]
    if truncado:
        incert.append(
            f"o limite de {limite} grupos foi atingido, então existem outros "
            f"grupos além dos trazidos: a contagem e a exposição acima são dos "
            f"{limite} de maior valor, não do conjunto inteiro")

    return Entrega(
        "concluida",
        f"{grupos} grupo(s) suspeitos de pagamento repetido, {brl(exposicao)} "
        f"de exposição a conferir ({len(altas)} de confiança alta).",
        resultado, afirm, evid, incert, bruto={"linhas": linhas},
    )


def exec_faturamento_cte_sem_titulo(*, empresa_id, missao_id, tarefa_id,
                                    entradas, acoes) -> Entrega:
    """CT-e autorizado na SEFAZ que não gerou título a receber.

    O teste é binário e recomputável: `ctrc.cd_movimento IS NULL` foi validado
    como equivalente a "não existe título". Por isso a contagem e a soma são
    fato — o que não é fato é o motivo de cada CT-e estar assim.
    """
    dias = int(entradas.get("dias", 30))
    carencia = int(entradas.get("carencia_dias", 0))
    limite = int(entradas.get("limite", 200))
    r = fb.rodar("atua", "faturamento.cte_sem_titulo",
                 {"dias": dias, "carencia_dias": carencia, "limite": limite,
                  "cd_pessoa_filial": entradas.get("cd_pessoa_filial")},
                 empresa_id=empresa_id, missao_id=missao_id,
                 tarefa_id=tarefa_id, acoes_permitidas=acoes)
    if not r.ok:
        return Entrega("bloqueada", f"consulta indisponível: {r.erro}", {},
                       pendencias=[r.erro or "falha na varredura de faturamento"])
    linhas = r.dados["linhas"]

    # A consulta traz o total da janela em toda linha (count/sum OVER ()).
    # Quando o corte por `limite` age, o detalhamento é parcial mas o total
    # continua correto — o número exibido é o do conjunto, nunca o das linhas.
    qt_total = int(linhas[0]["qt_total"]) if linhas else 0
    vl_total = _f(linhas[0]["vl_total_geral"]) if linhas else 0.0
    truncado = qt_total > len(linhas)

    velhos = [l for l in linhas if int(l.get("dias_sem_faturar") or 0) >= 30]
    vl_velhos = sum(_f(l["vl_total"]) for l in velhos)
    campos = ("nr_ctrc", "ds_serie", "dt_emissao", "vl_total", "cliente",
              "nr_cnpj_cpf", "filial", "dias_sem_faturar", "id_frete",
              "id_tipo_ctrc", "nr_chave")
    resultado = {
        "quantidade": qt_total, "valor": round(vl_total, 2),
        "janela_dias": dias, "carencia_dias": carencia,
        "linhas_trazidas": len(linhas), "truncado": truncado,
        "trazidos_com_30_dias_ou_mais": len(velhos),
        "valor_trazidos_com_30_dias_ou_mais": round(vl_velhos, 2),
        "amostra": [_linha(l, campos) for l in linhas[:15]],
    }
    evid = [_ev("consulta", "atua:faturamento.cte_sem_titulo", r.referencia,
                f"{qt_total} CT-e(s) autorizados pela SEFAZ e não cancelados, "
                f"emitidos nos últimos {dias} dias, sem título a receber "
                f"vinculado, somando {brl(vl_total)}",
                "atua:ctrc", r.dados["consultada_em"])]
    afirm = [
        {"texto": f"{qt_total} CT-e(s) autorizados pela SEFAZ nos últimos "
                  f"{dias} dias não têm nenhum título a receber no ERP, "
                  f"somando {brl(vl_total)} de frete.",
         "natureza": "fato", "evidencia": 0},
    ]
    if velhos:
        afirm.append({
            "texto": f"Entre os CT-es detalhados, {len(velhos)} já passaram de "
                     f"30 dias da emissão sem gerar título ({brl(vl_velhos)}) — "
                     f"tempo em que qualquer rotina normal de faturamento já "
                     f"teria rodado.",
            "natureza": "indicio", "evidencia": 0})

    incert = [
        "CT-e sem título não é necessariamente frete não cobrado: "
        "subcontratação, redespacho e complemento podem ser faturados por fora "
        "ou não gerar cobrança própria — a modalidade e o tipo vão na amostra "
        "justamente para o analista separar, porque não existe regra limpa de "
        "exclusão",
        f"a carência usada foi de {carencia} dia(s), então o lote de "
        f"faturamento que ainda está rodando entra na lista; se a Pianetto "
        f"fatura quinzenal, esse parâmetro deveria subir",
        "o que está provado é que o ERP não tem título: cobrança feita por fora "
        "do sistema não apareceria aqui",
        "só entram CT-es autorizados pela SEFAZ; documento não transmitido é "
        "assunto do Analista Fiscal, não deste levantamento",
    ]
    if truncado:
        incert.append(
            f"o detalhamento traz os {len(linhas)} de maior valor; a contagem e "
            f"a soma acima são do conjunto inteiro ({qt_total} CT-es)")

    return Entrega(
        "concluida",
        f"{qt_total} CT-e(s) autorizados sem título a receber nos últimos "
        f"{dias} dias, {brl(vl_total)} não faturados.",
        resultado, afirm, evid, incert, bruto={"linhas": linhas},
    )


def exec_comercial_cliente_sumiu(*, empresa_id, missao_id, tarefa_id, entradas,
                                 acoes) -> Entrega:
    """Cliente regular que parou de emitir CT-e ou caiu muito de volume.

    A comparação é entre duas janelas do mesmo ano, e a carteira da Pianetto é
    agro: entressafra contra safra acusa o setor inteiro. Nada aqui é fato de
    perda de cliente — é queda medida, que ainda precisa de leitura humana.
    """
    dias_base = int(entradas.get("dias_base", 180))
    dias_recente = int(entradas.get("dias_recente", 60))
    meses_min = int(entradas.get("meses_min", 3))
    vl_mensal_min = float(entradas.get("vl_mensal_min", 5000))
    pr_queda_min = float(entradas.get("pr_queda_min", 60))
    limite = int(entradas.get("limite", 100))
    r = fb.rodar("atua", "comercial.cliente_que_sumiu",
                 {"dias_base": dias_base, "dias_recente": dias_recente,
                  "meses_min": meses_min, "vl_mensal_min": vl_mensal_min,
                  "pr_queda_min": pr_queda_min, "limite": limite,
                  "cd_pessoa_filial": entradas.get("cd_pessoa_filial")},
                 empresa_id=empresa_id, missao_id=missao_id,
                 tarefa_id=tarefa_id, acoes_permitidas=acoes)
    if not r.ok:
        return Entrega("bloqueada", f"consulta indisponível: {r.erro}", {},
                       pendencias=[r.erro or "falha na varredura comercial"])
    linhas = r.dados["linhas"]
    # Sem total da janela na saída: se o limite encheu, o corte é invisível.
    truncado = len(linhas) >= limite

    pararam = [l for l in linhas if l.get("situacao") == "parou"]
    cairam = [l for l in linhas if l.get("situacao") == "caiu"]
    perda = sum(_f(l["vl_perda_mensal"]) for l in linhas)
    perda_parou = sum(_f(l["vl_perda_mensal"]) for l in pararam)
    # Um único cliente grande distorce o total; quem lê precisa ver isso.
    maior = max(linhas, key=lambda l: _f(l["vl_perda_mensal"])) if linhas else None
    perda_maior = _f(maior["vl_perda_mensal"]) if maior else 0.0

    campos = ("cliente", "nr_cnpj_cpf", "meses_ativos", "qt_base",
              "vl_media_mensal_anterior", "qt_recente",
              "vl_media_mensal_recente", "pr_queda", "vl_perda_mensal",
              "dt_ultimo_cte", "dias_sem_cte", "situacao")
    resultado = {
        "clientes": len(linhas), "pararam": len(pararam), "cairam": len(cairam),
        "perda_mensal": round(perda, 2),
        "perda_mensal_de_quem_parou": round(perda_parou, 2),
        "maior_perda_cliente": (maior["cliente"] if maior else None),
        "maior_perda_mensal": round(perda_maior, 2),
        "perda_mensal_sem_o_maior": round(perda - perda_maior, 2),
        "dias_base": dias_base, "dias_recente": dias_recente,
        "queda_minima_pct": pr_queda_min,
        "linhas_trazidas": len(linhas), "truncado": truncado,
        "amostra": [_linha(l, campos) for l in linhas[:15]],
    }
    evid = [_ev("consulta", "atua:comercial.cliente_que_sumiu", r.referencia,
                f"{len(linhas)} cliente(s) com pelo menos {meses_min} meses de "
                f"emissão nos {dias_base} dias anteriores e queda acima de "
                f"{pr_queda_min:.0f}% nos últimos {dias_recente} dias",
                "atua:ctrc", r.dados["consultada_em"])]
    afirm = [
        {"texto": f"{len(linhas)} cliente(s) que faturavam com regularidade "
                  f"caíram mais de {pr_queda_min:.0f}% nos últimos "
                  f"{dias_recente} dias em relação à média mensal dos "
                  f"{dias_base} dias anteriores, o equivalente a {brl(perda)} "
                  f"por mês de receita que deixou de entrar.",
         "natureza": "indicio", "evidencia": 0},
    ]
    if pararam:
        afirm.append({
            "texto": f"{len(pararam)} desses clientes não emitiram nenhum CT-e "
                     f"nos últimos {dias_recente} dias — pararam por completo, "
                     f"e respondem por {brl(perda_parou)} por mês.",
            "natureza": "indicio", "evidencia": 0})
    if maior:
        afirm.append({
            "texto": f"A maior queda isolada é de {maior['cliente']}, "
                     f"{brl(perda_maior)} por mês "
                     f"({pct(_f(maior['pr_queda']) / 100)} de queda, situação "
                     f"'{maior['situacao']}'); sem esse cliente a lista soma "
                     f"{brl(perda - perda_maior)} por mês.",
            "natureza": "indicio", "evidencia": 0})

    incert = [
        "quem está marcado como 'caiu' não sumiu: pode ter emitido CT-e hoje. "
        "A consulta mede queda de volume, não abandono — separe pela situação "
        "antes de mandar alguém ligar",
        "a comparação é entre dois períodos do mesmo ano e a carteira é agro: "
        "entressafra contra safra derruba o setor inteiro e vira falso positivo "
        "em massa; a leitura honesta seria contra o mesmo período do ano "
        "anterior",
        "o agrupamento é pelo CNPJ pagador, não por grupo econômico: cliente "
        "que passou a faturar por outro CNPJ aparece como perdido aqui e como "
        "novo em outro lugar",
        f"a janela olhada é de {dias_base + dias_recente} dias: cliente parado "
        f"há mais tempo que isso não entra na lista, porque não sobra base de "
        f"comparação",
        "nada aqui olhou título nem inadimplência: cliente bloqueado por débito "
        "de propósito aparece como perda, quando foi decisão da empresa",
    ]
    if truncado:
        incert.append(
            f"o limite de {limite} clientes foi atingido: existem outros além "
            f"dos trazidos, e os números acima são dos {limite} de maior perda")

    return Entrega(
        "concluida",
        f"{len(linhas)} cliente(s) em queda forte, {brl(perda)}/mês a menos "
        f"({len(pararam)} pararam de emitir).",
        resultado, afirm, evid, incert, bruto={"linhas": linhas},
    )


def exec_controladoria_margem(*, empresa_id, missao_id, tarefa_id, entradas,
                              acoes) -> Entrega:
    """Receita do CT-e contra custo de carta frete: agregado e piores casos.

    A consulta devolve linhas mistas: uma linha 'total' com o agregado da janela
    e N linhas 'pior_caso' de CT-e individual. As duas nunca se somam — a linha
    total já cobre a janela inteira, inclusive os CT-es que não vieram no
    detalhamento.
    """
    dias = int(entradas.get("dias", 30))
    pr_margem_min = float(entradas.get("pr_margem_min", 5))
    limite = int(entradas.get("limite", 100))
    r = fb.rodar("atua", "controladoria.margem_por_cte",
                 {"dias": dias, "pr_margem_min": pr_margem_min,
                  "limite": limite,
                  "cd_pessoa_filial": entradas.get("cd_pessoa_filial")},
                 empresa_id=empresa_id, missao_id=missao_id,
                 tarefa_id=tarefa_id, acoes_permitidas=acoes)
    if not r.ok:
        return Entrega("bloqueada", f"consulta indisponível: {r.erro}", {},
                       pendencias=[r.erro or "falha na consulta de margem"])
    linhas = r.dados["linhas"]
    totais = [l for l in linhas if l.get("linha") == "total"]
    piores = [l for l in linhas if l.get("linha") == "pior_caso"]
    if not totais:
        return Entrega("parcial", "a consulta não devolveu a linha de agregado",
                       {"linhas_trazidas": len(linhas)},
                       pendencias=["linha 'total' ausente: sem ela não há "
                                   "margem do período para declarar"])
    t = totais[0]

    qt = int(t["qt_ctes"] or 0)
    receita = _f(t["vl_receita"])
    custo = _f(t["vl_custo"])
    margem = _f(t["vl_margem"])
    pr_margem = _f(t["pr_margem"]) / 100.0
    qt_sem_carta = int(t["qt_sem_carta_frete"] or 0)
    vl_sem_carta = _f(t["vl_sem_carta_frete"])
    qt_negativa = int(t["qt_margem_negativa"] or 0)
    vl_negativa = _f(t["vl_margem_negativa"])

    # O corte por `limite` age sobre o detalhamento (a linha total ocupa uma
    # posição). Se encheu, há mais CT-es ruins do que os listados — e a
    # contagem confiável dos negativos continua sendo a do agregado.
    truncado = len(linhas) >= limite

    campos = ("nr_ctrc", "ds_serie", "dt_emissao", "cliente", "vl_receita",
              "vl_custo", "vl_margem", "pr_margem", "cd_pessoa_filial")
    resultado = {
        "janela_dias": dias, "margem_minima_pct": pr_margem_min,
        "ctes_com_custo_conhecido": qt,
        "receita": round(receita, 2), "custo_carta_frete": round(custo, 2),
        "margem_contribuicao": round(margem, 2),
        "margem_contribuicao_pct": round(pr_margem, 4),
        "ctes_sem_carta_frete": qt_sem_carta,
        "receita_sem_carta_frete": round(vl_sem_carta, 2),
        "ctes_custo_zero": int(t["qt_custo_zero"] or 0),
        "ctes_margem_negativa": qt_negativa,
        "valor_margem_negativa": round(vl_negativa, 2),
        "piores_casos_trazidos": len(piores), "truncado": truncado,
        "amostra": [_linha(l, campos) for l in piores[:15]],
    }
    evid = [_ev("consulta", "atua:controladoria.margem_por_cte", r.referencia,
                f"{qt} CT-e(s) dos últimos {dias} dias com carta frete "
                f"lançada: receita {brl(receita)}, custo {brl(custo)}, "
                f"diferença {brl(margem)}; {qt_sem_carta} CT-e(s) sem carta "
                f"frete ficaram fora do cálculo",
                "atua:ctrc", r.dados["consultada_em"])]
    afirm = [
        {"texto": f"Nos últimos {dias} dias, os {qt} CT-e(s) com carta frete "
                  f"lançada somaram {brl(receita)} de receita bruta contra "
                  f"{brl(custo)} de carta frete, deixando {brl(margem)} — "
                  f"{pct(pr_margem, 2)} de margem de contribuição de frete, que "
                  f"não é lucro porque não desconta imposto, comissão nem "
                  f"estrutura.",
         "natureza": "indicio", "evidencia": 0},
        {"texto": f"{qt_negativa} CT-e(s) do período ficaram com custo de carta "
                  f"frete acima da própria receita, {brl(vl_negativa)} no "
                  f"conjunto; são fila de investigação, porque parte disso é "
                  f"custo de uma viagem inteira caindo em um CT-e só.",
         "natureza": "indicio", "evidencia": 0},
        {"texto": f"{qt_sem_carta} CT-e(s) do período, {brl(vl_sem_carta)} de "
                  f"receita, não têm carta frete lançada e por isso ficaram "
                  f"inteiramente fora do cálculo de margem.",
         "natureza": "fato", "evidencia": 0},
    ]

    incert = [
        "margem por CT-e é frágil quando uma viagem carrega vários CT-es: uma "
        "carta frete alta contra CT-es pequenos joga todo o custo em cima de um "
        "deles. A leitura confiável é o agregado; o pior caso é fila de "
        "conferência, não conclusão",
        "a receita usada é o valor bruto do CT-e, sem desconto de ICMS, "
        "PIS/COFINS ou comissão — o que se apura aqui é margem de contribuição "
        "de frete, não lucro",
        "o único custo considerado é a carta frete: pedágio pago fora dela, "
        "quebra, avaria, seguro e despesa de filial não entram",
        f"os {qt_sem_carta} CT-es sem carta frete não são de graça — são frota "
        f"própria, cujo custo está no caixa do veículo, ou carta ainda não "
        f"lançada; tratá-los como margem cheia seria mentira, por isso ficaram "
        f"fora do cálculo em vez de entrar como custo zero",
        "CT-e com carta frete de valor zero entra no cálculo e é contado à "
        "parte, para não se confundir com quem simplesmente não tem carta",
    ]
    if truncado:
        incert.append(
            f"o limite de {limite} linhas foi atingido: os {len(piores)} piores "
            f"casos listados não são todos os CT-es abaixo de "
            f"{pr_margem_min:.0f}% de margem — a contagem completa dos "
            f"negativos é a do agregado ({qt_negativa})")

    return Entrega(
        "concluida",
        f"Margem de contribuição de frete em {dias} dias: {pct(pr_margem, 2)} "
        f"({brl(margem)} sobre {brl(receita)}), com {qt_negativa} CT-e(s) "
        f"negativos.",
        resultado, afirm, evid, incert, bruto={"linhas": linhas},
    )


def exec_frota_resultado(*, empresa_id, missao_id, tarefa_id, entradas,
                         acoes) -> Entrega:
    """Receita e custo identificável por placa da frota própria.

    A receita nasce no cavalo: é ele que aparece no CT-e. Carreta, dolly e carro
    administrativo entram só com custo, então comparar cavalo com carreta é
    injusto por construção — os dois grupos são apurados separados aqui. E a
    diferença entre receita e custo é contribuição, nunca lucro: falta
    depreciação, IPVA, seguro e estrutura.
    """
    dias = int(entradas.get("dias", 90))
    limite = int(entradas.get("limite", 100))
    r = fb.rodar("atua", "frota.resultado_veiculo",
                 {"dias": dias, "limite": limite,
                  "cd_pessoa_filial": entradas.get("cd_pessoa_filial")},
                 empresa_id=empresa_id, missao_id=missao_id,
                 tarefa_id=tarefa_id, acoes_permitidas=acoes)
    if not r.ok:
        return Entrega("bloqueada", f"consulta indisponível: {r.erro}", {},
                       pendencias=[r.erro or "falha na consulta de frota"])
    linhas = r.dados["linhas"]

    # A consulta ordena da pior contribuição para a melhor e corta em `limite`.
    # Quando o corte age, o que ficou na mão é a ponta ruim da frota: chamar
    # esses totais de resultado da frota seria falso.
    truncado = len(linhas) >= limite

    tratores = [l for l in linhas if l.get("id_tracao")]
    apoio = [l for l in linhas if not l.get("id_tracao")]
    rec_tr = sum(_f(l["vl_receita"]) for l in tratores)
    cus_tr = sum(_f(l["vl_custo_identificavel"]) for l in tratores)
    ctes_tr = sum(int(l["qt_ctes"] or 0) for l in tratores)
    contrib_tr = rec_tr - cus_tr
    negativos = [l for l in tratores if _f(l["vl_contribuicao"]) < 0]
    cus_apoio = sum(_f(l["vl_custo_identificavel"]) for l in apoio)
    apoio_sem_cte = [l for l in apoio if int(l["qt_ctes"] or 0) == 0]
    carros = [l for l in apoio
              if (l.get("nm_tipo_veiculo") or "").upper().startswith("CARRO")]
    cus_carros = sum(_f(l["vl_custo_identificavel"]) for l in carros)

    campos = ("ds_placa", "nr_frota", "ds_modelo", "nm_tipo_veiculo",
              "id_tracao", "qt_ctes", "vl_receita", "vl_combustivel",
              "vl_manutencao", "vl_pedagio", "vl_pessoal",
              "vl_custo_identificavel", "vl_contribuicao", "pr_contribuicao",
              "vl_km", "dt_ultimo_cte", "qt_lancamentos_caixa")
    resultado = {
        "janela_dias": dias,
        "veiculos_trazidos": len(linhas), "truncado": truncado,
        "tratores": len(tratores), "tratores_ctes": ctes_tr,
        "tratores_receita": round(rec_tr, 2),
        "tratores_custo_identificavel": round(cus_tr, 2),
        "tratores_contribuicao": round(contrib_tr, 2),
        "tratores_contribuicao_pct": (round(contrib_tr / rec_tr, 4)
                                      if rec_tr else None),
        "tratores_contribuicao_negativa": len(negativos),
        "apoio_veiculos": len(apoio),
        "apoio_custo_identificavel": round(cus_apoio, 2),
        "apoio_sem_nenhum_cte": len(apoio_sem_cte),
        "automoveis": len(carros), "automoveis_custo": round(cus_carros, 2),
        # A consulta já vem da pior contribuição para a melhor.
        "amostra": [_linha(l, campos) for l in tratores[:15]],
    }
    evid = [_ev("consulta", "atua:frota.resultado_veiculo", r.referencia,
                f"{len(linhas)} veículo(s) próprios com movimento nos últimos "
                f"{dias} dias, dos quais {len(tratores)} unidades tratoras com "
                f"{ctes_tr} CT-e(s), receita {brl(rec_tr)} e custo lançado no "
                f"caixa do veículo de {brl(cus_tr)}",
                "atua:veiculo_proprio", r.dados["consultada_em"])]
    afirm = [
        {"texto": f"Nos últimos {dias} dias, as {len(tratores)} unidades "
                  f"tratoras trazidas puxaram {ctes_tr} CT-e(s) de frota "
                  f"própria, com {brl(rec_tr)} de receita e {brl(cus_tr)} de "
                  f"custo lançado no caixa do veículo.",
         "natureza": "fato", "evidencia": 0},
        {"texto": f"A diferença entre essa receita e esse custo é de "
                  f"{brl(contrib_tr)} de contribuição — que não é lucro: falta "
                  f"depreciação, IPVA, seguro, estrutura e o salário de "
                  f"motorista que não é lançado na placa.",
         "natureza": "indicio", "evidencia": 0},
    ]
    if negativos:
        pior = negativos[0]
        afirm.append({
            "texto": f"{len(negativos)} unidade(s) tratora(s) fecharam a janela "
                     f"com custo acima da receita; a pior é a placa "
                     f"{pior['ds_placa']}, com {int(pior['qt_ctes'] or 0)} "
                     f"CT-e(s), {brl(_f(pior['vl_receita']))} de receita contra "
                     f"{brl(_f(pior['vl_custo_identificavel']))} de custo no "
                     f"caixa do veículo.",
            "natureza": "indicio", "evidencia": 0})
    if apoio:
        afirm.append({
            "texto": f"{len(apoio)} veículo(s) sem tração (carreta, dolly, "
                     f"automóvel) consumiram {brl(cus_apoio)} no período, "
                     f"sendo {brl(cus_carros)} em {len(carros)} automóvel(is). "
                     f"Eles não recebem receita porque o CT-e é emitido no "
                     f"cavalo, então esse valor não pode ser lido como "
                     f"prejuízo do veículo.",
            "natureza": "fato", "evidencia": 0})

    incert = [
        "não existe rateio de carreta neste ERP: a receita nasce no cavalo e a "
        "carreta que carregou a carga aparece apenas como custo — comparar "
        "cavalos entre si é justo, comparar cavalo com carreta não é",
        "a diferença entre receita e custo é contribuição, não lucro: falta "
        "depreciação, seguro de frota, IPVA, estrutura e o motorista quando o "
        "salário não é lançado com o veículo",
        "receita e custo estão em datas diferentes: a receita é a data de "
        "emissão do CT-e e o custo é a data do documento no caixa, então nota "
        "de manutenção lançada com atraso cai no período errado e derruba a "
        "placa injustamente",
        "veículo com custo e nenhum CT-e não é necessariamente ocioso: pode ser "
        "carreta, carro administrativo ou cavalo parado em oficina",
        "a carta frete emitida nos CT-es de frota própria é transferência "
        "interna, contra a própria Pianetto, e por isso ficou fora do "
        "resultado — somá-la ao combustível seria contar o mesmo custo duas "
        "vezes",
        "a abertura do custo por natureza (combustível, manutenção, pedágio, "
        "pessoal) vem do texto do histórico do lançamento e serve de "
        "orientação: as naturezas não fecham com o total, e foi o total do "
        "caixa do veículo que entrou na conta",
        "a frota própria é uma fração pequena do movimento: a Pianetto opera "
        "essencialmente com terceiros, então este resultado não representa a "
        "operação inteira",
    ]
    if truncado:
        incert.append(
            f"o limite de {limite} veículos foi atingido e a consulta ordena da "
            f"pior contribuição para a melhor: os veículos de melhor resultado "
            f"ficaram fora, então os totais acima valem para os {len(linhas)} "
            f"trazidos e não para a frota inteira")

    return Entrega(
        "concluida",
        f"Frota própria em {dias} dias: {len(tratores)} unidade(s) tratora(s) "
        f"com {brl(rec_tr)} de receita e {brl(contrib_tr)} de contribuição, "
        f"{len(negativos)} com custo acima da receita.",
        resultado, afirm, evid, incert, bruto={"linhas": linhas},
    )


def exec_fiscal_cte_pendente(*, empresa_id, missao_id, tarefa_id, entradas,
                             acoes) -> Entrega:
    """Situação na SEFAZ de cada documento de transporte da janela.

    Linhas mistas: 'resumo' traz uma linha por situação cobrindo a janela
    inteira, 'pendente' traz o documento aberto, um por linha. Os totais saem
    sempre do resumo — contar as linhas de detalhe daria o número do corte.
    """
    dias = int(entradas.get("dias", 90))
    limite = int(entradas.get("limite", 200))
    r = fb.rodar("atua", "fiscal.cte_pendente",
                 {"dias": dias, "limite": limite,
                  "cd_pessoa_filial": entradas.get("cd_pessoa_filial")},
                 empresa_id=empresa_id, missao_id=missao_id,
                 tarefa_id=tarefa_id, acoes_permitidas=acoes)
    if not r.ok:
        return Entrega("bloqueada", f"consulta indisponível: {r.erro}", {},
                       pendencias=[r.erro or "falha na consulta fiscal"])
    linhas = r.dados["linhas"]
    resumo_l = [l for l in linhas if l.get("linha") == "resumo"]
    pend_l = [l for l in linhas if l.get("linha") == "pendente"]

    # A ordenação coloca o detalhe antes do resumo; num período muito sujo o
    # corte por `limite` pode comer as linhas de resumo. Sem resumo não há
    # totais da janela, e deduzi-los do detalhe truncado seria inventar número.
    if not resumo_l:
        return Entrega("parcial",
                       "a consulta devolveu só o detalhe: o resumo por "
                       "situação foi cortado pelo limite",
                       {"pendentes_trazidos": len(pend_l), "truncado": True},
                       pendencias=[f"repetir com limite acima de {limite} para "
                                   f"obter o resumo por situação"])

    por_situacao = {l["situacao"]: {"quantidade": int(l["qt"] or 0),
                                   "valor": round(_f(l["vl"]), 2)}
                    for l in resumo_l}
    total_docs = sum(v["quantidade"] for v in por_situacao.values())
    autorizados = por_situacao.get("autorizado", {}).get("quantidade", 0)

    # O resumo conta também o que foi cancelado depois; a lista de detalhe já
    # exclui cancelado. Por isso a contagem de pendências vem do detalhe.
    abertos = len(pend_l)
    vl_abertos = sum(_f(l["vl_total"]) for l in pend_l)
    truncado = len(linhas) >= limite
    por_classe: dict[str, int] = {}
    for l in pend_l:
        por_classe[l["situacao"]] = por_classe.get(l["situacao"], 0) + 1
    parados = [l for l in pend_l if int(l.get("dias_parado") or 0) >= 15]

    campos = ("situacao", "nr_ctrc", "ds_serie", "dt_emissao", "vl_total",
              "cd_status", "ds_status", "cliente", "cd_pessoa_filial",
              "dias_parado")
    ordenada = sorted(pend_l, key=lambda l: -_f(l["vl_total"]))
    resultado = {
        "janela_dias": dias, "documentos_na_janela": total_docs,
        "por_situacao": por_situacao,
        "pendentes_abertos": abertos, "valor_pendentes": round(vl_abertos, 2),
        "pendentes_por_classe": por_classe,
        "pendentes_parados_15d_ou_mais": len(parados),
        "linhas_trazidas": len(linhas), "truncado": truncado,
        "amostra": [_linha(l, campos) for l in ordenada[:15]],
    }
    evid = [_ev("consulta", "atua:fiscal.cte_pendente", r.referencia,
                f"{total_docs} documento(s) emitidos nos últimos {dias} dias "
                f"classificados pelo código de retorno da SEFAZ: "
                + ", ".join(f"{k} {v['quantidade']}"
                            for k, v in sorted(por_situacao.items())),
                "atua:ctrc_cte", r.dados["consultada_em"])]
    afirm = [
        {"texto": f"Dos {total_docs} documentos emitidos nos últimos {dias} "
                  f"dias, {autorizados} estão autorizados pela SEFAZ no ERP.",
         "natureza": "fato", "evidencia": 0},
        {"texto": f"{abertos} documento(s) continuam sem autorização e não "
                  f"foram cancelados, somando {brl(vl_abertos)}: "
                  + ", ".join(f"{q} {c.replace('_', ' ')}"
                              for c, q in sorted(por_classe.items(),
                                                 key=lambda x: -x[1])) + ".",
         "natureza": "fato", "evidencia": 0},
    ]
    if parados:
        afirm.append({
            "texto": f"{len(parados)} desses documentos estão parados há 15 "
                     f"dias ou mais desde a emissão, o que torna improvável "
                     f"que sejam rascunho em uso.",
            "natureza": "indicio", "evidencia": 0})

    incert = [
        "'nunca transmitido' mistura duas coisas que o ERP não separa: "
        "documento digitado e esquecido, e rascunho legítimo — o tempo parado é "
        "o melhor separador prático",
        "'sem retorno da SEFAZ' pode ser registro antigo, criado antes da "
        "transmissão e nunca atualizado; a maior parte desses casos termina "
        "cancelada, e o cancelado já está fora da lista",
        "documento de modelo 55 é nota fiscal, não CT-e, e foi separado em "
        "classe própria para não virar falso positivo; esse corte é decisão da "
        "consulta e não marcação do ERP, então se a emissão mudar de modelo "
        "esses documentos saem da vigilância sem aviso",
        "o motivo mostrado é a descrição genérica do código no catálogo da "
        "SEFAZ, não a mensagem recebida por aquele documento específico",
        "nada aqui consultou a SEFAZ: a conferência é contra o banco do ERP, "
        "então se o ERP perdeu um retorno a consulta repete o erro dele",
        "o resumo por situação conta a janela inteira, inclusive o que foi "
        "cancelado depois; a lista de pendências exclui cancelado, por isso os "
        "dois números não fecham entre si, de propósito",
    ]
    if truncado:
        incert.append(
            f"o limite de {limite} linhas foi atingido: a lista de pendências "
            f"trazida pode não ser toda; o resumo por situação continua sendo "
            f"da janela inteira")

    return Entrega(
        "concluida",
        f"{abertos} documento(s) sem autorização da SEFAZ em {dias} dias, "
        f"{brl(vl_abertos)} em risco fiscal ({autorizados} autorizados).",
        resultado, afirm, evid, incert, bruto={"linhas": linhas},
    )


# ===========================================================================
# Auditores (contraprova)
# ===========================================================================
# Cada função abaixo recebe `alvo`: a entrega de OUTRO agente, já registrada.
# A regra é uma só e é dura: não repetir a consulta do apurador. O auditor
# chega ao mesmo fato por outra porta do banco. Se chegasse pela mesma, o
# "confere" dele não valeria nada — seria o mesmo SQL dizendo duas vezes a
# mesma coisa.
#
# O veredito é sempre um de três: confirma, contradiz, nao_verificavel. E
# "contradiz" não é acusação de erro: é dois caminhos discordando sobre o
# mesmo número, o que é exatamente o que se quer descobrir.

def _pr(v: float) -> str:
    """Percentual com vírgula. Ponto decimal em número brasileiro é ruído."""
    return f"{v:.1f}".replace(".", ",")


def _veredito(nome_do_auditor, veredito, resumo, dados, evid,
              incert=None, status="concluida") -> Entrega:
    dados = {**dados, "veredito": veredito}
    afirm = [{"texto": resumo, "natureza":
              "fato" if veredito != "nao_verificavel" else "ausencia",
              "evidencia": 0 if evid else None}]
    return Entrega(status, resumo, dados, afirm, evid, incert or [])


def _rodar(op, params, *, empresa_id, missao_id, tarefa_id, acoes):
    return fb.rodar("atua", op, params, empresa_id=empresa_id,
                    missao_id=missao_id, tarefa_id=tarefa_id,
                    acoes_permitidas=acoes)


def _bloqueada(msg) -> Entrega:
    return Entrega("bloqueada", msg, {"veredito": "nao_verificavel"},
                   pendencias=[msg])


def aud_cte_sem_titulo(*, empresa_id, missao_id, tarefa_id, entradas, acoes,
                       alvo) -> Entrega:
    """Contesta Bruno: os CT-es sem título estão mesmo autorizados na SEFAZ?

    Bruno conta CT-e sem `cd_movimento`. Isso mede ausência de título, não
    direito a faturar: um CT-e cancelado na SEFAZ também não tem título, e
    cobrar por ele seria erro. O caminho daqui é outro — `ctrc_cte.cd_status`.
    """
    dias = int(entradas.get("dias") or 30)
    carencia = int(entradas.get("carencia_dias") or 0)
    r = _rodar("contraprova.cte_sem_titulo_situacao",
               {"dias": dias, "carencia_dias": carencia,
                "cd_pessoa_filial": entradas.get("cd_pessoa_filial")},
               empresa_id=empresa_id, missao_id=missao_id,
               tarefa_id=tarefa_id, acoes=acoes)
    if not r.ok:
        return _bloqueada(f"situação na SEFAZ indisponível: {r.erro}")

    linhas = r.dados["linhas"]
    tot = next((l for l in linhas if l["linha"] == "total"), None)
    aut = next((l for l in linhas if l["linha"] == "subtotal"
                and l["situacao"] == "AUTORIZADO_VIGENTE"), None)
    if tot is None or aut is None:
        return _bloqueada("a contraprova não devolveu os subtotais por situação")

    universo = int(tot["qt_ctes"] or 0)
    qt_aut = int(aut["qt_ctes"] or 0)
    vl_aut = _f(aut["vl_ctes"])
    declarado = int((alvo.get("resultado") or {}).get("quantidade") or 0)
    fora = universo - qt_aut
    detalhe = [l for l in linhas if l["linha"] == "situacao"
               and l["situacao"] != "autorizado_vigente"]
    porque = ", ".join(f"{int(l['qt_ctes'])} {l['situacao'].replace('_', ' ')}"
                       for l in detalhe[:5])

    evid = [_ev("consulta", "atua", "contraprova.cte_sem_titulo_situacao",
                f"{qt_aut} autorizados de {universo} sem título",
                r.dados.get("raiz", "atua:contraprova.cte_sem_titulo_situacao"),
                r.dados.get("consultada_em", ""))]
    dados = {"declarado_pelo_apurador": declarado,
             "autorizados_na_sefaz": qt_aut, "valor_autorizado": round(vl_aut, 2),
             "universo_sem_titulo": universo, "fora_de_faturamento": fora,
             "por_situacao": {l["situacao"]: int(l["qt_ctes"] or 0)
                              for l in detalhe}}

    if declarado and qt_aut == declarado:
        return _veredito("fiscal", "confirma",
                         f"Confere por outro caminho: os {declarado} CT-es sem "
                         f"título estão todos autorizados na SEFAZ "
                         f"({brl(vl_aut)}). Fora deles há mais {fora} sem "
                         f"título que não podem ser faturados — {porque}.",
                         dados, evid)
    if declarado:
        return _veredito("fiscal", "contradiz",
                         f"Não confere: o apurador declarou {declarado} CT-es "
                         f"a faturar, mas só {qt_aut} estão autorizados na "
                         f"SEFAZ. A diferença de {abs(declarado - qt_aut)} não "
                         f"pode virar título — {porque}.",
                         {**dados, "divergencia": declarado - qt_aut}, evid)
    return _veredito("fiscal", "nao_verificavel",
                     "a apuração não declarou quantidade comparável", dados,
                     evid)


def aud_cte_pendente_faturado(*, empresa_id, missao_id, tarefa_id, entradas,
                              acoes, alvo) -> Entrega:
    """Contesta Alan: algum documento sem autorização já virou dinheiro?

    Alan conta o que está pendente na SEFAZ. A pergunta que ele não faz é a
    que dói: desses pendentes, quantos já foram faturados e recebidos? Aí
    deixa de ser pendência fiscal e vira receita sem lastro.
    """
    dias = int(entradas.get("dias") or 90)
    r = _rodar("contraprova.cte_pendente_faturado",
               {"dias": dias, "cd_pessoa_filial": entradas.get("cd_pessoa_filial")},
               empresa_id=empresa_id, missao_id=missao_id,
               tarefa_id=tarefa_id, acoes=acoes)
    if not r.ok:
        return _bloqueada(f"cruzamento com faturamento indisponível: {r.erro}")

    linhas = r.dados["linhas"]
    res = [l for l in linhas if l["linha"] == "resumo"]
    com = next((l for l in res if l["classe"] == "com_titulo"), None)
    sem = next((l for l in res if l["classe"] == "sem_titulo"), None)
    if com is None or sem is None:
        return _bloqueada("a contraprova não devolveu o resumo por classe")

    qt_com = int(com["qt_ctes"] or 0)
    vl_com = _f(com["vl_ctes"])
    universo = qt_com + int(sem["qt_ctes"] or 0)
    declarado = int((alvo.get("resultado") or {}).get("abertos")
                    or (alvo.get("resultado") or {}).get("pendentes") or 0)
    piores = [l for l in linhas if l["linha"] == "detalhe"][:3]

    evid = [_ev("consulta", "atua", "contraprova.cte_pendente_faturado",
                f"{qt_com} pendentes já com título, {brl(vl_com)}",
                r.dados.get("raiz", "atua:contraprova.cte_pendente_faturado"),
                r.dados.get("consultada_em", ""))]
    dados = {"declarado_pelo_apurador": declarado,
             "pendentes_no_universo": universo,
             "pendentes_ja_faturados": qt_com,
             "valor_ja_faturado": round(vl_com, 2),
             "amostra": [{k: l.get(k) for k in
                          ("cd_ctrc", "nr_ctrc", "dt_emissao", "vl_total",
                           "cliente", "situacao")} for l in piores]}

    if qt_com:
        cli = piores[0].get("cliente") if piores else None
        return _veredito("comercial", "contradiz",
                         f"O número está certo, a leitura não: dos {universo} "
                         f"documentos sem autorização, {qt_com} já foram "
                         f"faturados — {brl(vl_com)} cobrados sem lastro "
                         f"fiscal" + (f", o pior deles em {cli}." if cli else "."),
                         {**dados, "divergencia": qt_com}, evid)
    return _veredito("comercial", "confirma",
                     f"Confere: nenhum dos {universo} documentos sem "
                     f"autorização foi faturado. A pendência é fiscal e parou "
                     f"antes de virar cobrança.", dados, evid)


def aud_duplicidade_documento(*, empresa_id, missao_id, tarefa_id, entradas,
                              acoes, alvo) -> Entrega:
    """Contesta Íris: é o mesmo documento fiscal ou são compras diferentes?

    Íris agrupa por fornecedor, valor e vencimento. Isso encontra pagamento em
    duplicidade, mas encontra junto duas notas legítimas de mesmo valor. O
    caminho daqui é o número do documento em `caixa.nr_documento` e o
    parcelamento em `movimento` — não o formato do título.
    """
    r = _rodar("contraprova.duplicidade_documento",
               {"dias": int(entradas.get("dias") or 5),
                "dias_retro": int(entradas.get("dias_retro") or 365),
                "vl_min": entradas.get("vl_min") or 100,
                "cd_pessoa_filial": entradas.get("cd_pessoa_filial")},
               empresa_id=empresa_id, missao_id=missao_id,
               tarefa_id=tarefa_id, acoes=acoes)
    if not r.ok:
        return _bloqueada(f"conferência por documento indisponível: {r.erro}")

    tot = [l for l in r.dados["linhas"] if l["linha"] == "total"]
    if not tot:
        return _bloqueada("a contraprova não devolveu a classificação dos grupos")
    por = {l["classificacao"]: l for l in tot}
    distintos = int(por.get("documentos_distintos", {}).get("qt_grupos") or 0)
    parcelas = int(por.get("mesmo_movimento_parcelado", {}).get("qt_grupos") or 0)
    incerto = int(por.get("documento_desconhecido", {}).get("qt_grupos") or 0)
    total = distintos + parcelas + incerto
    vl_expl = (_f(por.get("documentos_distintos", {}).get("vl_exposicao"))
               + _f(por.get("mesmo_movimento_parcelado", {}).get("vl_exposicao")))
    declarado = int((alvo.get("resultado") or {}).get("grupos") or 0)
    expo = _f((alvo.get("resultado") or {}).get("exposicao"))

    evid = [_ev("consulta", "atua", "contraprova.duplicidade_documento",
                f"{distintos} documentos distintos, {parcelas} parcelas do "
                f"mesmo movimento, {incerto} sem documento no banco",
                r.dados.get("raiz", "atua:contraprova.duplicidade_documento"),
                r.dados.get("consultada_em", ""))]
    dados = {"declarado_pelo_apurador": declarado,
             "exposicao_declarada": round(expo, 2),
             "grupos_conferidos": total,
             "documentos_distintos": distintos,
             "parcelas_do_mesmo_movimento": parcelas,
             "sem_documento_no_banco": incerto,
             "valor_explicado": round(vl_expl, 2)}

    if distintos + parcelas == 0:
        return _veredito("auditoria", "confirma",
                         f"Confere: nenhum dos {total} grupos tem explicação "
                         f"legítima pelo número do documento. A suspeita de "
                         f"duplicidade se mantém.", dados, evid)
    pr = _pr(100.0 * (distintos + parcelas) / total if total else 0.0)
    return _veredito("auditoria", "contradiz",
                     f"Não é duplicidade: dos {total} grupos apontados, "
                     f"{distintos} são documentos fiscais diferentes e "
                     f"{parcelas} são parcelas do mesmo movimento — {pr}% da "
                     f"suspeita, {brl(vl_expl)}, tem explicação. Sobram "
                     f"{incerto} grupos sem número de documento no banco, e "
                     f"só esses continuam de pé.",
                     {**dados, "divergencia": distintos + parcelas}, evid)


def aud_margem_frota_propria(*, empresa_id, missao_id, tarefa_id, entradas,
                             acoes, alvo) -> Entrega:
    """Contesta Caio: quanto da margem negativa é transferência interna?

    Caio soma carta frete como custo. Em veículo de terceiro isso é dinheiro
    que sai. Em frota própria é dinheiro que troca de bolso dentro da mesma
    empresa — vira custo no CT-e e receita no caixa do veículo. Somar dos dois
    lados inventa prejuízo. O caminho daqui é `ctrc.id_proprietario_veiculo`.
    """
    r = _rodar("contraprova.margem_frota_propria",
               {"dias": int(entradas.get("dias") or 30),
                "pr_margem_min": entradas.get("pr_margem_min") or 5,
                "cd_pessoa_filial": entradas.get("cd_pessoa_filial")},
               empresa_id=empresa_id, missao_id=missao_id,
               tarefa_id=tarefa_id, acoes=acoes)
    if not r.ok:
        return _bloqueada(f"quebra por propriedade do veículo indisponível: {r.erro}")

    linhas = r.dados["linhas"]
    tot = next((l for l in linhas if l["linha"] == "total"), None)
    quebras = {l["tipo_proprietario"]: l for l in linhas if l["linha"] == "quebra"}
    if tot is None or not quebras:
        return _bloqueada("a contraprova não devolveu a quebra por proprietário")

    pro = quebras.get("frota_propria", {})
    qt_pro = int(pro.get("qt_ctes") or 0)
    custo_pro = _f(pro.get("vl_custo"))
    neg_pro = int(pro.get("qt_margem_negativa") or 0)
    universo = int(tot["qt_ctes"] or 0)
    neg_total = sum(int(q.get("qt_margem_negativa") or 0) for q in quebras.values())
    declarado_neg = int((alvo.get("resultado") or {}).get("ctes_margem_negativa")
                        or (alvo.get("resultado") or {}).get("qt_margem_negativa")
                        or 0)

    evid = [_ev("consulta", "atua", "contraprova.margem_frota_propria",
                f"{qt_pro} de {universo} CT-es abaixo do mínimo são frota "
                f"própria; {brl(custo_pro)} de custo é transferência interna",
                r.dados.get("raiz", "atua:contraprova.margem_frota_propria"),
                r.dados.get("consultada_em", ""))]
    dados = {"declarado_margem_negativa": declarado_neg,
             "margem_negativa_conferida": neg_total,
             "ctes_abaixo_do_minimo": universo,
             "ctes_frota_propria": qt_pro,
             "custo_que_e_transferencia_interna": round(custo_pro, 2),
             "margem_negativa_em_frota_propria": neg_pro,
             "por_proprietario": {k: {"ctes": int(v.get("qt_ctes") or 0),
                                      "margem": round(_f(v.get("vl_margem")), 2)}
                                  for k, v in quebras.items()}}

    if declarado_neg and neg_total != declarado_neg:
        return _veredito("frota", "contradiz",
                         f"Não fecha: o apurador declarou {declarado_neg} CT-es "
                         f"com margem negativa e a quebra por proprietário "
                         f"soma {neg_total}.",
                         {**dados, "divergencia": declarado_neg - neg_total}, evid)
    if qt_pro:
        pr = _pr(100.0 * qt_pro / universo if universo else 0.0)
        return _veredito("frota", "contradiz",
                         f"A conta fecha, a conclusão não: {qt_pro} dos "
                         f"{universo} CT-es abaixo do mínimo ({pr}%) rodaram em "
                         f"frota própria, onde {brl(custo_pro)} de carta frete "
                         f"é transferência dentro de casa, não custo. O "
                         f"prejuízo real está nos {universo - qt_pro} de "
                         f"terceiro.",
                         {**dados, "divergencia": qt_pro}, evid)
    return _veredito("frota", "confirma",
                     f"Confere: todos os {universo} CT-es abaixo do mínimo são "
                     f"de veículo de terceiro, onde a carta frete é dinheiro "
                     f"que realmente sai. A margem negativa é real.", dados, evid)


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

registrar(Definicao(
    id="contas.pagar", nome="Íris", papel="Analista de Contas a Pagar",
    area="Financeiro & Tesouraria",
    promessa="Nada é pago duas vezes.", versao=1,
    competencias=["duplicidade-a-pagar", "exposicao-de-fornecedor",
                  "fila-de-conferencia"],
    ferramentas=["atua"], acoes=["atua.pagar.duplicidade_suspeita"],
    entradas={"dias": "int", "dias_retro": "int", "vl_min": "num",
              "max_parcelas": "int", "cd_pessoa_filial": "int",
              "limite": "int"},
    saidas={"grupos": "int", "titulos": "int", "exposicao": "num",
            "grupos_confianca_alta": "int",
            "valor_ja_pago_confianca_alta": "num"},
    limites={"tempo_s": 90, "custo_centavos": 0},
    criterios=["exposição confere com valor × repetições",
               "parcelamento longo fora da lista",
               "nenhuma linha declarada como duplicidade provada"],
    executor=exec_pagar_duplicidade,
))

registrar(Definicao(
    id="comercial.faturamento", nome="Bruno", papel="Analista de Faturamento",
    area="Comercial & Faturamento",
    promessa="Todo frete entregue vira fatura.", versao=1,
    competencias=["cte-sem-titulo", "backlog-de-faturamento"],
    ferramentas=["atua"], acoes=["atua.faturamento.cte_sem_titulo",
           "atua.contraprova.cte_pendente_faturado"],
    entradas={"dias": "int", "carencia_dias": "int",
              "cd_pessoa_filial": "int", "limite": "int"},
    saidas={"quantidade": "int", "valor": "num",
            "trazidos_com_30_dias_ou_mais": "int"},
    limites={"tempo_s": 90, "custo_centavos": 0},
    criterios=["total vem da janela, não das linhas trazidas",
               "só CT-e autorizado e não cancelado",
               "carência declarada"],
    executor=exec_faturamento_cte_sem_titulo,
    auditor=aud_cte_pendente_faturado,
))

registrar(Definicao(
    id="comercial.inteligencia", nome="Sofia", papel="Inteligência Comercial",
    area="Comercial & Faturamento",
    promessa="Você sabe exatamente de quem depende.", versao=1,
    competencias=["queda-de-cliente", "concentracao-de-receita"],
    ferramentas=["atua"], acoes=["atua.comercial.cliente_que_sumiu"],
    entradas={"dias_base": "int", "dias_recente": "int", "meses_min": "int",
              "vl_mensal_min": "num", "pr_queda_min": "num",
              "cd_pessoa_filial": "int", "limite": "int"},
    saidas={"clientes": "int", "pararam": "int", "cairam": "int",
            "perda_mensal": "num", "perda_mensal_sem_o_maior": "num"},
    limites={"tempo_s": 90, "custo_centavos": 0},
    criterios=["quem parou separado de quem caiu",
               "efeito de um cliente só isolado do total",
               "sazonalidade declarada"],
    executor=exec_comercial_cliente_sumiu,
))

registrar(Definicao(
    id="controladoria.margem", nome="Caio", papel="Controller",
    area="Controladoria & Custos",
    promessa="A margem que existe atrás de cada conhecimento.", versao=1,
    competencias=["margem-por-cte", "custo-de-carta-frete",
                  "cte-com-margem-negativa"],
    ferramentas=["atua"], acoes=["atua.controladoria.margem_por_cte"],
    entradas={"dias": "int", "pr_margem_min": "num",
              "cd_pessoa_filial": "int", "limite": "int"},
    saidas={"receita": "num", "custo_carta_frete": "num",
            "margem_contribuicao": "num", "margem_contribuicao_pct": "num",
            "ctes_margem_negativa": "int", "ctes_sem_carta_frete": "int"},
    limites={"tempo_s": 120, "custo_centavos": 0},
    criterios=["agregado não soma com detalhe",
               "CT-e sem carta frete fora do cálculo",
               "resultado tratado como contribuição, nunca como lucro"],
    executor=exec_controladoria_margem,
))

registrar(Definicao(
    id="frota.resultado", nome="Davi", papel="Analista de Frota",
    area="Operações & Frota",
    promessa="O veículo que dá prejuízo não passa despercebido.", versao=1,
    competencias=["resultado-por-placa", "custo-de-veiculo",
                  "frota-administrativa"],
    ferramentas=["atua"],
    acoes=["atua.frota.resultado_veiculo",
           "atua.contraprova.margem_frota_propria"],
    entradas={"dias": "int", "cd_pessoa_filial": "int", "limite": "int"},
    saidas={"tratores": "int", "tratores_receita": "num",
            "tratores_custo_identificavel": "num",
            "tratores_contribuicao": "num",
            "tratores_contribuicao_negativa": "int",
            "apoio_custo_identificavel": "num"},
    limites={"tempo_s": 120, "custo_centavos": 0},
    criterios=["unidade tratora apurada separada de carreta e automóvel",
               "carta frete interna fora do resultado",
               "contribuição nunca apresentada como lucro"],
    executor=exec_frota_resultado,
    auditor=aud_margem_frota_propria,
))

registrar(Definicao(
    id="fiscal.documento", nome="Alan", papel="Analista Fiscal",
    area="Fiscal & Contábil",
    promessa="CT-e e MDF-e sem pendência com o fisco.", versao=1,
    competencias=["situacao-sefaz", "cte-nao-transmitido", "rejeicao-sefaz"],
    ferramentas=["atua"], acoes=["atua.fiscal.cte_pendente",
           "atua.contraprova.cte_sem_titulo_situacao"],
    entradas={"dias": "int", "cd_pessoa_filial": "int", "limite": "int"},
    saidas={"documentos_na_janela": "int", "por_situacao": "dict",
            "pendentes_abertos": "int", "valor_pendentes": "num",
            "pendentes_parados_15d_ou_mais": "int"},
    limites={"tempo_s": 90, "custo_centavos": 0},
    criterios=["resumo por situação separado do detalhe",
               "cancelado fora da lista de pendência",
               "nota fiscal modelo 55 fora da cobrança de CT-e"],
    executor=exec_fiscal_cte_pendente,
    auditor=aud_cte_sem_titulo,
))

# Declarados, sem ferramenta ligada. Aparecem na interface com a limitação
# escrita — é o teste de aceitação nº 15. Continuam aqui de propósito: são o
# mapa do que ainda falta ligar.
for _id, _nome, _papel, _area, _prom, _fer in [
    ("auditoria.interna", "Lívia", "Auditora Interna", "Controladoria & Custos",
     "O erro aparece no mesmo dia, não no fechamento.", ["atua", "documento"]),
    ("frota.viagem", "Nina", "Analista de Viagem", "Operações & Frota",
     "Adiantamento, saldo e acerto sempre batendo.", ["atua"]),
    ("frota.combustivel", "Rui", "Analista de Combustível", "Operações & Frota",
     "Cada litro tem dono e tem destino.", ["x7bank"]),
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

# Lívia é o primeiro agente que existe só para contestar. Ela não abre missão
# própria: entra quando outro agente já entregou um número, e confere esse
# número por um caminho diferente do banco. Aparece na interface como
# "revisor", não como "sem integração" — porque ela opera de verdade.
_livia = obter("auditoria.interna")
_livia.competencias = ["contraprova-de-duplicidade", "conferencia-por-documento"]
_livia.acoes = ["atua.contraprova.duplicidade_documento"]
_livia.criterios = ["nunca repete a consulta do agente auditado",
                    "toda contestação nomeia o caminho alternativo usado"]
_livia.auditor = aud_duplicidade_documento
