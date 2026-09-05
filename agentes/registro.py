"""Cadastro de agentes e seus executores.

Um agente é código determinístico + ferramentas declaradas. O adaptador de
modelo é opcional: sem ele o agente continua entregando, porque o raciocínio
está nas regras, não no texto gerado. Agente sem ferramenta configurada aparece
como 'sem_integracao' e diz qual é a limitação — nunca finge que opera.
"""
from __future__ import annotations

import json
from datetime import date as _date
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
    # Um agente pode ter mais de uma frente e cada frente devolve outra coisa.
    # Sem isto, o verificador estrutural cobra da apuração por placa os campos
    # da apuração por conhecimento e reprova uma entrega correta.
    saidas_foco: dict[str, dict] = field(default_factory=dict)
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


def f_num(v, casas: int = 0) -> str:
    """Número solto em pt-BR: milhar com ponto, decimal com vírgula."""
    try:
        n = float(v or 0)
    except (TypeError, ValueError):
        return "0"
    s = f"{n:,.{casas}f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return s


def f_reais_km(v) -> str:
    """Preço por quilômetro. Duas casas, sempre com o R$ na frente."""
    return brl(v)


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



def exec_controladoria(*, empresa_id, missao_id, tarefa_id, entradas,
                       acoes) -> Entrega:
    """Porta de entrada do Caio. Ele tem duas frentes, não duas identidades.

    Sem `foco`, apura margem por conhecimento — o que sempre fez. Com
    `foco=veiculo`, desce ao nível da placa e volta com o que fazer em cada
    uma. É a mesma pessoa olhando o mesmo custo por dois recortes, e por isso
    fica no mesmo agente em vez de virar um agente novo sem histórico.
    """
    if str(entradas.get("foco") or "").lower() in ("veiculo", "veiculos",
                                                   "placa"):
        return exec_plano_por_veiculo(
            empresa_id=empresa_id, missao_id=missao_id, tarefa_id=tarefa_id,
            entradas=entradas, acoes=acoes)
    return exec_controladoria_margem(
        empresa_id=empresa_id, missao_id=missao_id, tarefa_id=tarefa_id,
        entradas=entradas, acoes=acoes)


def exec_lucratividade_setor(*, empresa_id, missao_id, tarefa_id, entradas,
                             acoes) -> Entrega:
    """Resultado por setor: frota própria contra agenciamento, e por agência.

    A empresa tem dois negócios dentro do mesmo CNPJ, e eles não têm o mesmo
    custo. No agenciamento o custo é a carta frete paga ao transportador. Na
    frota própria a carta frete é paga à própria Pianetto — é transferência
    interna, e somá-la como custo inventaria prejuízo; o custo de verdade é o
    caixa amarrado ao veículo.

    O que sai daqui é margem de contribuição por setor, não lucro: nada aqui
    desconta ICMS, PIS/COFINS, folha da administração nem depreciação.
    """
    dias = int(entradas.get("dias", 90))
    limite = int(entradas.get("limite", 60))
    filial = entradas.get("cd_pessoa_filial")

    rs = _rodar("lucratividade.por_setor",
                {"dias": dias, "cd_pessoa_filial": filial},
                empresa_id=empresa_id, missao_id=missao_id,
                tarefa_id=tarefa_id, acoes=acoes)
    if not rs.ok:
        return Entrega("bloqueada", f"consulta indisponível: {rs.erro}", {},
                       pendencias=[rs.erro or "falha na consulta por setor"])
    ra = _rodar("lucratividade.por_agencia",
                {"dias": dias, "cd_pessoa_filial": filial, "limite": limite},
                empresa_id=empresa_id, missao_id=missao_id,
                tarefa_id=tarefa_id, acoes=acoes)

    setores = {l["setor"]: l for l in rs.dados["linhas"]}
    if not setores:
        return Entrega("parcial", "a consulta não devolveu setor algum", {},
                       pendencias=["sem linha de setor para declarar"])

    def bloco(chave):
        l = setores.get(chave) or {}
        return {
            "ctes": int(l.get("qt_ctes") or 0),
            "receita": round(_f(l.get("vl_receita")), 2),
            "custo_frete_terceiro": round(_f(l.get("vl_frete_terceiro")), 2),
            "custo_frota_caixa": round(_f(l.get("vl_custo_frota")), 2),
            "margem": round(_f(l.get("vl_margem")), 2),
            "margem_pct": round(_f(l.get("pr_margem")) / 100.0, 4),
            "ctes_sem_custo": int(l.get("qt_sem_custo") or 0),
            "receita_sem_custo": round(_f(l.get("vl_sem_custo")), 2),
        }

    frota = bloco("frota_propria")
    frota["carta_frete_interna"] = round(
        _f((setores.get("frota_propria") or {}).get("vl_carta_interna")), 2)
    frota["lancamentos_de_caixa"] = int(
        (setores.get("frota_propria") or {}).get("qt_lancamentos_frota") or 0)

    # Agregado é veículo de terceiro com vínculo fixo: o custo continua sendo
    # carta frete que sai da empresa. Some com terceiro para formar o setor de
    # agenciamento, mas fica destacado, porque a negociação é outra.
    ag_partes = [bloco("terceiro"), bloco("agregado")]
    agenciamento = {
        "ctes": sum(b["ctes"] for b in ag_partes),
        "receita": round(sum(b["receita"] for b in ag_partes), 2),
        "custo_frete_terceiro": round(
            sum(b["custo_frete_terceiro"] for b in ag_partes), 2),
        "custo_frota_caixa": 0.0,
        "ctes_sem_custo": sum(b["ctes_sem_custo"] for b in ag_partes),
        "receita_sem_custo": round(sum(b["receita_sem_custo"] for b in ag_partes), 2),
    }
    agenciamento["margem"] = round(
        agenciamento["receita"] - agenciamento["custo_frete_terceiro"], 2)
    agenciamento["margem_pct"] = round(
        agenciamento["margem"] / agenciamento["receita"], 4) \
        if agenciamento["receita"] else 0.0
    agenciamento["agregado"] = bloco("agregado")

    sem_classe = bloco("sem_classificacao")
    receita_total = round(frota["receita"] + agenciamento["receita"]
                          + sem_classe["receita"], 2)

    # ------------------------------------------------------------- agências
    agencias, nao_comparaveis, negativas = [], [], []
    campos = ("cd_agencia", "nm_agencia", "qt_ctes", "vl_receita",
              "vl_receita_frota", "vl_frete_terceiro", "vl_margem_bruta",
              "vl_despesa_agencia", "vl_resultado", "pr_resultado",
              "qt_sem_custo", "vl_sem_custo", "id_centro_custo_ligado")
    erro_agencia = None
    if ra.ok:
        for l in ra.dados["linhas"]:
            d = _linha(l, campos)
            rec = _f(l.get("vl_receita"))
            desp = _f(l.get("vl_despesa_agencia"))
            frota_rec = _f(l.get("vl_receita_frota"))
            # Centro de custo que engole mais de 40% da receita da unidade não
            # é despesa de agência: é rateio institucional caindo ali (matriz,
            # administração, oficina). Marcar em vez de somar como prejuízo.
            demais = rec > 0 and desp / rec > 0.40
            # E agência que despacha frota própria aparece sem o custo do
            # veículo, que não é rateado por unidade: o resultado dela sobe
            # sozinho. Acima de 20% da receita em frota, sai da comparação.
            so_frota = rec > 0 and frota_rec / rec > 0.20
            d["comparavel"] = not (demais or so_frota)
            d["motivo_nao_comparavel"] = (
                "centro de custo recebe despesa que não é da unidade" if demais
                else "receita de frota própria sem o custo do veículo"
                if so_frota else None)
            d["sem_centro_custo"] = not bool(l.get("id_centro_custo_ligado"))
            agencias.append(d)
            if not d["comparavel"]:
                nao_comparaveis.append(d)
            elif _f(l.get("vl_resultado")) < 0:
                negativas.append(d)
    else:
        erro_agencia = ra.erro or "consulta por agência não respondeu"

    comparaveis = [a for a in agencias if a["comparavel"]]
    piores = sorted(comparaveis, key=lambda a: _f(a.get("vl_resultado")))[:8]
    melhores = sorted(comparaveis, key=lambda a: -_f(a.get("vl_resultado")))[:8]

    resultado = {
        "janela_dias": dias,
        "receita_total": receita_total,
        "frota_propria": frota,
        "agenciamento": agenciamento,
        "sem_classificacao": sem_classe,
        "agencias_apuradas": len(agencias),
        "agencias_comparaveis": len(comparaveis),
        "agencias_no_vermelho": len(negativas),
        "agencias_nao_comparaveis": len(nao_comparaveis),
        "melhores_agencias": melhores,
        "piores_agencias": piores,
        "agencias": agencias,
        "erro_agencia": erro_agencia,
    }

    evid = [_ev("consulta", "atua", "lucratividade.por_setor", rs.referencia,
                "atua:ctrc+carta_frete+caixa_veiculo",
                rs.dados["consultada_em"])]
    if ra.ok:
        evid.append(_ev("consulta", "atua", "lucratividade.por_agencia",
                        ra.referencia,
                        "atua:ctrc+agencia_centro_custo+caixa_participacao",
                        ra.dados["consultada_em"]))

    afirm = [
        {"texto": f"Em {dias} dias o agenciamento moveu {brl(agenciamento['receita'])} "
                  f"de receita em {agenciamento['ctes']} CT-e(s) e pagou "
                  f"{brl(agenciamento['custo_frete_terceiro'])} de carta frete, "
                  f"deixando {brl(agenciamento['margem'])} — "
                  f"{pct(agenciamento['margem_pct'], 2)} de margem de "
                  f"contribuição.",
         "natureza": "fato", "evidencia": 0},
        {"texto": f"A frota própria fez {brl(frota['receita'])} em "
                  f"{frota['ctes']} CT-e(s) contra {brl(frota['custo_frota_caixa'])} "
                  f"de caixa lançado nos veículos, deixando "
                  f"{brl(frota['margem'])} — {pct(frota['margem_pct'], 2)}. A "
                  f"carta frete desses CT-es, {brl(frota['carta_frete_interna'])}, "
                  f"é paga à própria Pianetto e por isso ficou fora do custo.",
         "natureza": "fato", "evidencia": 0},
        {"texto": f"Cada real de receita do agenciamento devolve "
                  f"{pct(agenciamento['margem_pct'], 2)}; cada real da frota "
                  f"devolve {pct(frota['margem_pct'], 2)}. A comparação é de "
                  f"margem de contribuição, não de lucro: nenhum dos dois "
                  f"desconta imposto, comissão nem estrutura administrativa.",
         "natureza": "indicio", "evidencia": 0},
    ]
    if ra.ok:
        afirm.append(
            {"texto": f"Das {len(agencias)} agências com CT-e no período, "
                      f"{len(comparaveis)} têm despesa de centro de custo "
                      f"compatível com o próprio movimento e "
                      f"{len(negativas)} delas fecharam no vermelho; "
                      f"{len(nao_comparaveis)} ficaram de fora da comparação "
                      f"porque o centro de custo ligado a elas recebe despesa "
                      f"que não é da unidade.",
             "natureza": "fato", "evidencia": 1})

    incert = [
        "isto é margem de contribuição por setor, não lucro: falta ICMS, "
        "PIS/COFINS, comissão, folha da administração, depreciação e juros",
        f"{agenciamento['ctes_sem_custo']} CT-e(s) de terceiro, "
        f"{brl(agenciamento['receita_sem_custo'])} de receita, não têm carta "
        f"frete lançada; entraram na receita e não no custo, então a margem do "
        f"agenciamento está por cima até essas cartas serem lançadas",
        "o custo da frota é o caixa amarrado ao veículo: o que não foi "
        "apontado a uma placa (pneu comprado para estoque, oficina, "
        "administração da frota) não está aqui",
        "a despesa por agência vem do centro de custo ligado a ela; agência "
        "sem centro de custo aparece só com margem de frete, e o centro de "
        "custo da matriz carrega despesa da empresa inteira",
        "o custo do veículo próprio não é rateado por agência: na tabela de "
        "agências ele não aparece, e por isso a agência que despacha frota "
        "própria parece melhor do que é",
    ]
    if erro_agencia:
        incert.append(f"a quebra por agência não veio: {erro_agencia}")
    if sem_classe["ctes"]:
        incert.append(
            f"{sem_classe['ctes']} CT-e(s), {brl(sem_classe['receita'])}, estão "
            f"sem o tipo de proprietário do veículo preenchido e não puderam "
            f"ser postos em setor nenhum")

    return Entrega(
        "concluida",
        f"Em {dias} dias: agenciamento {pct(agenciamento['margem_pct'], 2)} "
        f"({brl(agenciamento['margem'])}) e frota própria "
        f"{pct(frota['margem_pct'], 2)} ({brl(frota['margem'])}) de margem de "
        f"contribuição.",
        resultado, afirm, evid, incert,
        bruto={"setores": rs.dados["linhas"],
               "agencias": ra.dados["linhas"] if ra.ok else []},
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


def _mediana(vals: list[float]) -> float:
    v = sorted(x for x in vals if x > 0)
    if not v:
        return 0.0
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2.0


def exec_plano_por_veiculo(*, empresa_id, missao_id, tarefa_id, entradas,
                           acoes) -> Entrega:
    """Diagnóstico placa a placa e o que fazer para tirar cada uma do vermelho.

    O resultado por veículo diz QUEM está no vermelho. Isso sozinho não muda
    nada: o que muda é saber POR QUE, e a resposta é sempre uma de poucas —
    o veículo rodou pouco, o frete dele foi barato, o combustível lançado nele
    foi caro ou a manutenção comeu o mês. Cada placa é comparada com a mediana
    dos próprios cavalos da casa, não com número de fora, e o ganho estimado é
    sempre 'trazer para a mediana', nunca 'para o melhor da frota'.

    Duas regras de honestidade ficam no código, não no texto:
    - a receita é a do CT-e no período e o custo é o do caixa no mesmo período;
      um veículo que rodou em junho e teve a nota de manutenção lançada em
      agosto aparece pior do que é, então baixo quilômetro derruba a confiança
      do diagnóstico em vez de virar acusação;
    - combustível por quilômetro aqui é REAIS LANÇADOS por quilômetro, não
      consumo aferido na bomba. Serve para escolher onde medir, não para
      afirmar que o motorista gastou demais.
    """
    dias = int(entradas.get("dias", 90))
    limite = int(entradas.get("limite", 300))
    r = fb.rodar("atua", "frota.resultado_veiculo",
                 {"dias": dias, "limite": limite,
                  "cd_pessoa_filial": entradas.get("cd_pessoa_filial")},
                 empresa_id=empresa_id, missao_id=missao_id,
                 tarefa_id=tarefa_id, acoes_permitidas=acoes)
    if not r.ok:
        return Entrega("bloqueada", f"consulta indisponível: {r.erro}", {},
                       pendencias=[r.erro or "falha na consulta de frota"])
    linhas = r.dados["linhas"]
    # O diesel por dentro. A consulta acima traz o VALOR do combustivel; esta
    # abre o mesmo dinheiro em litro, preco do litro e leitura de painel. Se
    # ela falhar, o plano continua com o que tem e o motivo fica escrito nas
    # incertezas: bloco que falha nao vira zero.
    ab = fb.rodar("atua", "frota.abastecimento_veiculo",
                  {"dias": dias, "limite": 200},
                  empresa_id=empresa_id, missao_id=missao_id,
                  tarefa_id=tarefa_id, acoes_permitidas=acoes)
    diesel: dict[str, dict] = {}
    if ab.ok:
        for a in ab.dados["linhas"]:
            diesel[str(a["ds_placa"]).strip()] = a
    frota = [l for l in linhas
             if l.get("id_tracao")
             and (int(l["qt_ctes"] or 0) > 0
                  or int(l.get("qt_ctes_agregado") or 0) > 0)]
    if not frota:
        return Entrega(
            "parcial", f"nenhum cavalo da frota própria emitiu CT-e em {dias} "
            f"dias — sem base para plano por veículo", {"veiculos": 0},
            pendencias=["nenhum veículo de tração com receita no período"])

    # Referência da casa. Quem quase não rodou distorce mediana de consumo,
    # então o consumo é medido só entre os que rodaram de verdade.
    # Frota própria é o que o cadastro diz que é próprio. Se a placa está em
    # veiculo_proprio e sem baixa, o cavalo é da casa — e então TODO o
    # conhecimento emitido nele é receita da frota, inclusive o que o documento
    # classificou como agregado ou terceiro. O custo dessa placa já estava
    # inteiro aqui; contar só parte da receita fazia o cavalo parecer vazio.
    # Essa parcela fica separada em campo próprio para nunca sumir de vista:
    # ela é ajuste de classificação, não faturamento novo.
    KM_DIA_MIN = 50.0
    for l in frota:
        km = _f(l["vl_km"]) + _f(l.get("vl_km_agregado"))
        l["_km"] = km
        l["_km_dia"] = km / dias if dias else 0.0
        l["_rec_agr"] = _f(l.get("vl_receita_agregado"))
        l["_ctes_agr"] = int(l.get("qt_ctes_agregado") or 0)
        l["_rec"] = _f(l["vl_receita"]) + l["_rec_agr"]
        l["_cus"] = _f(l["vl_custo_identificavel"])
        l["_contrib"] = l["_rec"] - l["_cus"]
        l["_r_km"] = l["_rec"] / km if km else 0.0
        l["_comb_km"] = _f(l["vl_combustivel"]) / km if km else 0.0
        l["_manut"] = _f(l["vl_manutencao"])
        d = diesel.get(str(l["ds_placa"]).strip())
        l["_lt"] = _f(d.get("qt_litros")) if d else 0.0
        l["_rs_lt"] = _f(d.get("vl_preco_litro")) if d else 0.0
        l["_km_hod"] = _f(d.get("vl_km_hodometro")) if d else 0.0
        l["_sem_hod"] = int(d.get("qt_sem_hodometro") or 0) if d else 0
        l["_abast"] = int(d.get("qt_abastecimentos") or 0) if d else 0
        # km/l so vale quando o painel foi lido em todos os abastecimentos e o
        # numero cai na faixa fisica de um cavalo carregado. Fora disso e troca
        # de painel ou leitura faltando, e ai o consumo nao e afirmado.
        kml = (l["_km_hod"] / l["_lt"]) if l["_lt"] else 0.0
        l["_kml"] = kml if (l["_sem_hod"] == 0 and 1.2 <= kml <= 4.0) else 0.0
    rodando = [l for l in frota if l["_km_dia"] >= KM_DIA_MIN]
    med_km_dia = _mediana([l["_km_dia"] for l in frota])
    med_r_km = _mediana([l["_r_km"] for l in frota])
    med_comb_km = _mediana([l["_comb_km"] for l in rodando]) if rodando else 0.0
    med_manut = _mediana([l["_manut"] for l in frota])
    com_litro = [l for l in frota if l["_lt"] > 0 and l["_rs_lt"] > 0]
    med_litro = _mediana([l["_rs_lt"] for l in com_litro]) if com_litro else 0.0
    com_kml = [l for l in frota if l["_kml"] > 0]
    med_kml = _mediana([l["_kml"] for l in com_kml]) if com_kml else 0.0

    hoje = _date.today()
    plano: list[dict] = []
    for l in sorted(frota, key=lambda x: x["_contrib"]):
        sint: list[str] = []
        med: list[dict] = []
        ganho = 0.0      # preço e consumo: diferença medida contra a mediana
        giro = 0.0       # agenda cheia: estimativa, e por isso somada à parte
        km, km_dia = l["_km"], l["_km_dia"]
        parado = None
        try:
            ult = l.get("dt_ultimo_cte")
            if ult:
                d = ult if hasattr(ult, "year") else _date.fromisoformat(str(ult)[:10])
                parado = (hoje - d).days
        except (TypeError, ValueError):
            parado = None

        # 1. Quilômetro. É o sintoma que manda: cavalo parado não tem frete
        # bom nem consumo bom, tem custo correndo sozinho.
        if med_km_dia and km_dia < med_km_dia * 0.6:
            falta = (med_km_dia - km_dia) * dias
            giro = falta * max(l["_r_km"], med_r_km) * 0.15
            sint.append(
                f"rodou {f_num(km)} km em {dias} dias, {f_num(km_dia, 1)} km por "
                f"dia, contra {f_num(med_km_dia, 1)} km por dia da mediana da "
                f"frota — faltaram {f_num(falta)} km de giro")
            med.append({
                "acao": "cobrar programação de carga para esta placa na "
                        "reunião diária da operação, e se não houver carga na "
                        "praça dela, transferir o cavalo para a filial que "
                        "está terceirizando frete",
                "porque": f"esta placa girou {f_num(km_dia, 1)} km/dia e a "
                          f"mediana da casa é {f_num(med_km_dia, 1)} km/dia; "
                          f"parcela grande do custo do veículo corre com ele "
                          f"parado",
                "ganho": (round(giro, 2) if giro else None),
                "quem": "Operações & Frota"})
        if parado is not None and parado > 21:
            sint.append(f"último CT-e foi há {parado} dias")
            med.append({
                "acao": "abrir chamado escrito dizendo onde o veículo está e "
                        "por quê: oficina, motorista afastado, documento "
                        "vencido ou falta de carga. Sem essa resposta em 48h, "
                        "o veículo entra na pauta de venda ou locação",
                "porque": f"{parado} dias sem emitir conhecimento é tempo "
                          f"demais para um cavalo com custo lançado",
                "ganho": None, "quem": "Operações & Frota"})

        # 2. Preço do frete. Só faz sentido comparar quem rodou.
        if km_dia >= KM_DIA_MIN and med_r_km and l["_r_km"] < med_r_km * 0.9:
            g = (med_r_km - l["_r_km"]) * km
            ganho += g
            sint.append(
                f"o frete dela saiu a {f_reais_km(l['_r_km'])} por km contra "
                f"{f_reais_km(med_r_km)} por km da mediana")
            med.append({
                "acao": f"repactuar as rotas desta placa com piso de "
                        f"{f_reais_km(med_r_km)} por km, ou trocar a rota dela "
                        f"pela rota de um cavalo que hoje roda acima da "
                        f"mediana",
                "porque": f"nos {f_num(km)} km rodados, a diferença de preço "
                          f"para a mediana da própria frota vale {brl(g)}",
                "ganho": round(g, 2), "quem": "Comercial"})

        # 3. Combustível. Quando existe o item do abastecimento, o excesso é
        # aberto nas duas causas que o real por quilômetro mistura: pagar caro
        # o litro e queimar litro demais. As duas não se sobrepõem — uma é
        # R$/litro, a outra é litro/km — e por isso somam sem contar duas
        # vezes. Sem item de abastecimento, cai no real por quilômetro de antes.
        tem_litro = l["_lt"] > 0 and l["_rs_lt"] > 0
        if tem_litro and med_litro and l["_rs_lt"] > med_litro * 1.01:
            g = (l["_rs_lt"] - med_litro) * l["_lt"]
            ganho += g
            sint.append(
                f"pagou {brl(l['_rs_lt'])} no litro contra {brl(med_litro)} "
                f"da mediana da frota, em {f_num(l['_lt'])} litros")
            med.append({
                "acao": "levar os postos usados por esta placa para a mesa de "
                        "negociação do cartão de abastecimento e travar preço "
                        "de rota; onde não houver acordo, mudar o ponto de "
                        "abastecimento da rota dela",
                "porque": f"a diferença de {brl(l['_rs_lt'] - med_litro)} por "
                          f"litro sobre {f_num(l['_lt'])} litros vale "
                          f"{brl(g)} em {dias} dias, sem mexer em consumo",
                "ganho": round(g, 2), "quem": "Suprimentos & Abastecimento"})
        if tem_litro and l["_kml"] and med_kml and l["_kml"] < med_kml * 0.9:
            sobra = l["_lt"] - (l["_km_hod"] / med_kml)
            g = max(sobra, 0.0) * l["_rs_lt"]
            ganho += g
            sint.append(
                f"fez {f_num(l['_kml'], 2)} km por litro contra "
                f"{f_num(med_kml, 2)} da mediana, medido pelo painel em "
                f"{f_num(l['_km_hod'])} km")
            med.append({
                "acao": "abrir o consumo desta placa com o motorista: "
                        "telemetria de marcha lenta e excesso de rotação, "
                        "calibragem, e conferência de dois abastecimentos "
                        "seguidos com o painel lido na hora",
                "porque": f"no consumo da mediana os mesmos "
                          f"{f_num(l['_km_hod'])} km pediriam "
                          f"{f_num(max(sobra, 0.0))} litros a menos, "
                          f"{brl(g)}",
                "ganho": round(g, 2), "quem": "Operações & Frota"})
        if tem_litro and l["_abast"] and l["_sem_hod"]:
            sint.append(
                f"{l['_sem_hod']} de {l['_abast']} abastecimentos sem "
                f"hodômetro informado")
            med.append({
                "acao": "exigir a leitura do painel em todo abastecimento e "
                        "recusar o lançamento sem hodômetro na conferência "
                        "diária do cartão",
                "porque": "sem painel lido não existe km por litro, e sem km "
                          "por litro o consumo desta placa não pode ser "
                          "afirmado nem contestado",
                "ganho": None, "quem": "Controladoria & Custos"})
        if (not tem_litro) and km_dia >= KM_DIA_MIN and med_comb_km \
                and l["_comb_km"] > med_comb_km * 1.2:
            g = (l["_comb_km"] - med_comb_km) * km
            ganho += g
            sint.append(
                f"combustível lançado a {f_reais_km(l['_comb_km'])} por km "
                f"contra {f_reais_km(med_comb_km)} por km da mediana")
            med.append({
                "acao": "conferir os abastecimentos desta placa um a um no "
                        "período: hodômetro informado, litragem contra "
                        "capacidade do tanque e abastecimento fora da rota. "
                        "Fechar a média km/l do veículo com o motorista",
                "porque": f"são {brl(g)} acima do que a mediana da frota "
                          f"gastaria nos mesmos {f_num(km)} km — pode ser "
                          f"consumo, pode ser lançamento de outra placa caindo "
                          f"nesta, e as duas coisas se resolvem olhando",
                "ganho": round(g, 2), "quem": "Controladoria & Custos"})

        # 4. Manutenção. Aqui não existe mediana por km confiável: nota grande
        # cai num mês só. O corte é o valor absoluto contra a mediana da casa.
        if med_manut and l["_manut"] > max(med_manut * 2.5, 20000.0):
            sint.append(f"manutenção de {brl(l['_manut'])} no período, "
                        f"{f_num(l['_manut'] / med_manut)} vezes a mediana da "
                        f"frota ({brl(med_manut)})")
            med.append({
                "acao": "levantar o histórico de oficina dos últimos 12 meses "
                        "desta placa e comparar o custo acumulado com a tabela "
                        "de mercado do modelo. Se passar de metade do valor do "
                        "veículo, decidir entre retífica e troca — com data",
                "porque": f"{brl(l['_manut'])} em {dias} dias é gasto de "
                          f"veículo em fim de ciclo, não de manutenção "
                          f"preventiva",
                "ganho": None, "quem": "Operações & Frota"})

        # Placa da casa faturando como agregado. A receita já entrou no
        # resultado acima; o que fica pendente é a classificação, e ela muda
        # imposto, carta frete e comissão — por isso vira medida, não nota.
        if l["_ctes_agr"]:
            sint.append(
                f"{l['_ctes_agr']} conhecimento(s) desta placa própria foram "
                f"emitidos como agregado ou terceiro, {brl(l['_rec_agr'])} — "
                f"contados aqui como receita da frota, porque o cavalo é da "
                f"casa e o custo dele está inteiro aqui")
            med.append({
                "acao": "decidir a classificação desta placa e corrigir o "
                        "cadastro do conhecimento: se o cavalo é da casa, o "
                        "CT-e sai de agregado; se está locado a terceiro, o "
                        "custo dele sai da frota junto com a receita",
                "porque": "a mesma placa aparece nos dois lados do resultado: "
                          "custo na frota própria e receita no agenciamento. "
                          "Enquanto isso durar, os dois números estão errados "
                          "e a carta frete paga nesses CT-es precisa de dono",
                "ganho": None, "quem": "Controladoria & Custos"})

        if not med:
            continue
        confianca = ("baixa" if km_dia < KM_DIA_MIN else
                     "media" if int(l["qt_ctes"] or 0) + l["_ctes_agr"] < 5
                     else "alta")
        plano.append({
            "placa": l["ds_placa"], "modelo": l.get("ds_modelo"),
            "ctes": int(l["qt_ctes"] or 0) + l["_ctes_agr"],
            "ctes_reclassificados": l["_ctes_agr"] or None,
            "receita_reclassificada": (round(l["_rec_agr"], 2)
                                       if l["_ctes_agr"] else None),
            "km": round(km, 0), "km_dia": round(km_dia, 1),
            "receita": round(l["_rec"], 2), "custo": round(l["_cus"], 2),
            "contribuicao": round(l["_contrib"], 2),
            "contribuicao_pct": (round(l["_contrib"] / l["_rec"], 4)
                                 if l["_rec"] else None),
            "receita_por_km": round(l["_r_km"], 2),
            "combustivel_por_km": round(l["_comb_km"], 2),
            "litros": (round(l["_lt"], 0) if l["_lt"] else None),
            "preco_litro": (round(l["_rs_lt"], 3) if l["_rs_lt"] else None),
            "km_por_litro": (round(l["_kml"], 2) if l["_kml"] else None),
            "abastecimentos": l["_abast"] or None,
            "abast_sem_hodometro": l["_sem_hod"] or None,
            "manutencao": round(l["_manut"], 2),
            "dias_sem_cte": parado,
            "no_vermelho": l["_contrib"] < 0,
            "confianca": confianca,
            "sintomas": sint, "medidas": med,
            "ganho_estimado": round(ganho, 2) if ganho else None,
            "ganho_giro": round(giro, 2) if giro else None})

    # O vermelho e contado sobre a FROTA, nao sobre o plano. Ate aqui uma placa
    # negativa que nao tivesse nenhum ponto fora da mediana ficava de fora da
    # lista e o total negativo saia menor do que e. Placa negativa sem
    # apontamento continua sem medida — mas entra na conta e aparece pelo nome.
    negativos = [p for p in plano if p["no_vermelho"]]
    negativas_frota = [l for l in frota if l["_contrib"] < 0]
    vermelho_total = sum(l["_contrib"] for l in negativas_frota)
    negativas_sem_medida = [l["ds_placa"] for l in negativas_frota
                            if l["ds_placa"] not in {p["placa"] for p in plano}]
    ganho_total = sum(p["ganho_estimado"] or 0 for p in plano)
    giro_total = sum(p["ganho_giro"] or 0 for p in plano)
    limpos = [l["ds_placa"] for l in frota
              if l["ds_placa"] not in {p["placa"] for p in plano}]
    mistas = [l for l in frota if l["_ctes_agr"]]
    rec_reclass = sum(l["_rec_agr"] for l in mistas)

    campos = ("ds_placa", "ds_modelo", "qt_ctes", "vl_receita",
              "vl_custo_identificavel", "vl_contribuicao", "vl_km")
    resultado = {
        "janela_dias": dias,
        "veiculos_analisados": len(frota),
        "veiculos_com_apontamento": len(plano),
        "veiculos_no_vermelho": len(negativas_frota),
        "vermelho_sem_apontamento": negativas_sem_medida,
        "vermelho_total": round(vermelho_total, 2),
        "ganho_estimado_total": round(ganho_total, 2),
        "ganho_giro_total": round(giro_total, 2),
        "mediana_km_dia": round(med_km_dia, 1),
        "mediana_receita_por_km": round(med_r_km, 2),
        "mediana_combustivel_por_km": round(med_comb_km, 2),
        "mediana_manutencao": round(med_manut, 2),
        "mediana_preco_litro": round(med_litro, 3),
        "mediana_km_por_litro": round(med_kml, 2),
        "litros_periodo": round(sum(l["_lt"] for l in frota), 0),
        "diesel_periodo": round(sum(l["_lt"] * l["_rs_lt"] for l in frota), 2),
        "placas_com_litro": len(com_litro),
        "placas_com_km_litro": len(com_kml),
        "abastecimento_indisponivel": (None if ab.ok else (ab.erro or "falha")),
        "veiculos_sem_apontamento": limpos,
        "placas_reclassificadas": len(mistas),
        "receita_reclassificada_total": round(rec_reclass, 2),
        "plano": plano,
    }
    evid = [_ev("consulta", "atua:frota.resultado_veiculo", r.referencia,
                f"{len(frota)} cavalo(s) da frota própria com CT-e em {dias} "
                f"dias; mediana da casa: {f_num(med_km_dia, 1)} km/dia, "
                f"{f_reais_km(med_r_km)}/km de receita e "
                f"{f_reais_km(med_comb_km)}/km de combustível lançado",
                "atua:ctrc+caixa_veiculo", r.dados["consultada_em"])]
    i_diesel = i_mistas = 0
    if ab.ok and com_litro:
        i_diesel = len(evid)
        evid.append(_ev(
            "consulta", "atua:frota.abastecimento_veiculo", ab.referencia,
            f"{len(com_litro)} placa(s) com item de diesel no periodo: "
            f"{f_num(sum(l['_lt'] for l in frota))} litros, mediana de "
            f"{brl(med_litro)} por litro"
            + (f" e {f_num(med_kml, 2)} km por litro em {len(com_kml)} placa(s) "
               f"com painel lido em todos os abastecimentos" if med_kml else ""),
            "atua:caixa_produto+caixa_veiculo", ab.dados["consultada_em"]))
    if mistas:
        i_mistas = len(evid)
        evid.append(_ev(
            "consulta", "atua:frota.resultado_veiculo", r.referencia,
            f"{len(mistas)} placa(s) do cadastro próprio com conhecimento "
            f"emitido como agregado ou terceiro: "
            + "; ".join(f"{l['ds_placa']} {l['_ctes_agr']} CT-e "
                        f"{brl(l['_rec_agr'])}" for l in mistas),
            "atua:ctrc.id_proprietario_veiculo", r.dados["consultada_em"]))
    afirm = [
        {"texto": f"Dos {len(frota)} cavalos que puxaram CT-e em {dias} dias, "
                  f"{len(plano)} têm pelo menos um ponto fora da mediana da "
                  f"própria frota e {len(negativas_frota)} fecharam com custo acima "
                  f"da receita, somando {brl(abs(vermelho_total))} negativos.",
         "natureza": "fato", "evidencia": 0},
        {"texto": f"Trazer preço de frete e combustível das placas apontadas "
                  f"para a mediana da própria casa — nem para o melhor "
                  f"caminhão, nem para número de mercado — valeria "
                  f"{brl(ganho_total)} na janela de {dias} dias.",
         "natureza": "estimativa", "evidencia": 0},
        {"texto": f"Encher a agenda das placas que giraram abaixo da mediana "
                  f"valeria outros {brl(giro_total)}, contados a 15% de "
                  f"contribuição sobre o quilômetro que faltou. Essa parcela "
                  f"depende de haver carga, então vai separada da anterior.",
         "natureza": "estimativa", "evidencia": 0},
    ]
    if com_litro:
        afirm.append({
            "texto": f"A frota queimou {f_num(sum(l['_lt'] for l in frota))} "
                     f"litros de diesel em {dias} dias, "
                     f"{brl(sum(l['_lt'] * l['_rs_lt'] for l in frota))}. O "
                     f"litro saiu por {brl(med_litro)} na mediana e o consumo "
                     f"deu {f_num(med_kml, 2)} km por litro nas "
                     f"{len(com_kml)} placas com painel lido em todo "
                     f"abastecimento.",
            "natureza": "fato", "evidencia": i_diesel})
    if mistas:
        afirm.append({
            "texto": f"{len(mistas)} placa(s) do cadastro próprio emitiram "
                     f"conhecimento como agregado ou terceiro, "
                     f"{brl(rec_reclass)}. Como o cavalo é da casa e o custo "
                     f"dele está inteiro na frota, essa receita foi contada "
                     f"aqui como frota própria — e sai do agenciamento na "
                     f"mesma medida.",
            "natureza": "fato", "evidencia": i_mistas})
    for p in negativos[:5]:
        afirm.append({
            "texto": f"{p['placa']}: {p['ctes']} CT-e(s), {f_num(p['km'])} km, "
                     f"{brl(p['receita'])} de receita contra "
                     f"{brl(p['custo'])} de custo. "
                     + " ".join(p["sintomas"][:2]),
            "natureza": "fato", "evidencia": 0})

    incert = [
        "receita e custo estão em datas diferentes: a receita é a emissão do "
        "CT-e e o custo é o documento no caixa, então nota de oficina lançada "
        "com atraso derruba a placa no período errado — por isso veículo de "
        "pouco quilômetro sai com confiança baixa em vez de virar acusação",
        "o km por litro vem do painel lido no abastecimento: mede do primeiro "
        "ao último abastecimento do período e ignora o que a placa rodou antes "
        "do primeiro, então subestima o consumo bom. Placa com abastecimento "
        "sem hodômetro ou com km/l fora da faixa de 1,2 a 4,0 fica sem consumo "
        "afirmado em vez de entrar com número duvidoso",
        "o preço do litro é o do item lançado no caixa, com imposto e frota "
        "misturados como vieram do documento: diferença de estado e de ARLA "
        "podem aparecer como preço, e por isso a medida é sentar com o posto, "
        "não descontar de ninguém",
        "combustível por quilômetro aqui é real lançado por quilômetro rodado, "
        "não consumo aferido na bomba: serve para escolher onde medir, não "
        "para afirmar que o motorista gastou além da conta",
        "a comparação é contra a mediana dos próprios cavalos da casa; se a "
        "frota inteira estiver mal precificada, a mediana também está, e o "
        "ganho estimado fica subestimado",
        "o ganho de preço e consumo supõe o mesmo quilômetro rodado com preço "
        "e consumo de mediana: é o tamanho da diferença, não dinheiro "
        "contratado",
        "o ganho de giro é a estimativa mais frágil da apuração: supõe que "
        "existe carga para o quilômetro que faltou e usa 15% de contribuição, "
        "que é a margem do agenciamento, não a da frota",
        "a contribuição por placa não é lucro: falta depreciação, IPVA, "
        "seguro, estrutura e o salário de motorista que não desce à placa",
    ]
    return Entrega(
        "concluida",
        f"{len(plano)} de {len(frota)} cavalos com ponto fora da mediana da "
        f"casa; {len(negativas_frota)} no vermelho "
        f"({brl(abs(vermelho_total))}). "
        f"Preço e consumo na mediana valem {brl(ganho_total)}; encher a "
        f"agenda das paradas, outros {brl(giro_total)}.",
        resultado, afirm, evid, incert,
        bruto={"linhas": [_linha(l, campos) for l in frota]},
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



def aud_custo_da_frota(*, empresa_id, missao_id, tarefa_id, entradas, acoes,
                       alvo) -> Entrega:
    """Contesta Vera: o custo da frota fecha por outro caminho?

    Vera soma o caixa amarrado à placa (`caixa_veiculo`). Aqui o caminho é o
    centro de custo (`caixa_participacao`), que é como a contabilidade enxerga
    a mesma despesa. Se os dois discordarem muito, a margem da frota está
    apoiada em custo incompleto — e margem calculada sobre custo faltante sai
    alta por construção, nunca baixa.
    """
    dias = int(entradas.get("dias") or 90)
    r = _rodar("contraprova.lucratividade_custo_frota", {"dias": dias},
               empresa_id=empresa_id, missao_id=missao_id,
               tarefa_id=tarefa_id, acoes=acoes)
    if not r.ok:
        return _bloqueada(f"conferência por centro de custo indisponível: {r.erro}")

    linhas = r.dados["linhas"]
    por = {l["caminho"]: l for l in linhas if l["linha"] == "custo"}
    cartas = [l for l in linhas if l["linha"] == "carta_frete_propria"]
    if "centro_custo" not in por or "caixa_veiculo" not in por:
        return _bloqueada("a contraprova não devolveu os dois caminhos de custo")

    cc = _f(por["centro_custo"]["vl"])
    cv = _f(por["caixa_veiculo"]["vl"])
    declarado = _f(((alvo.get("resultado") or {}).get("frota_propria") or {})
                   .get("custo_frota_caixa"))
    receita = _f(((alvo.get("resultado") or {}).get("frota_propria") or {})
                 .get("receita"))
    base = declarado or cv
    dif = base - cc
    pr_dif = abs(dif) / base * 100.0 if base else 0.0

    # Quem recebe a carta frete da frota própria decide se ela é custo.
    externos = [l for l in cartas
                if "PIANETTO" not in str(l.get("nm_recebedor") or "").upper()]
    vl_externo = sum(_f(l.get("vl")) for l in externos)

    evid = [_ev("consulta", "atua", "contraprova.lucratividade_custo_frota",
                f"custo da frota em {dias} dias: {brl(cc)} pelo centro de "
                f"custo contra {brl(cv)} pelo caixa do veículo; carta frete "
                f"da frota própria: "
                + "; ".join(f"{l.get('nm_recebedor')} {brl(_f(l.get('vl')))}"
                            for l in cartas[:3]),
                r.dados.get("raiz", "atua:caixa_participacao+caixa_veiculo"),
                r.dados.get("consultada_em", ""))]
    dados = {"custo_declarado": round(declarado, 2),
             "custo_por_centro_de_custo": round(cc, 2),
             "custo_por_caixa_do_veiculo": round(cv, 2),
             "diferenca": round(dif, 2),
             "diferenca_pct": round(pr_dif / 100.0, 4),
             "centros_de_custo_de_frota": int(por["centro_custo"]["qt_chaves"] or 0),
             "placas_ativas": int(por["caixa_veiculo"]["qt_chaves"] or 0),
             "carta_frete_para_fora": round(vl_externo, 2)}

    if vl_externo > 0:
        return _veredito(
            "auditoria", "contradiz",
            f"A carta frete da frota própria não é toda interna: "
            f"{brl(vl_externo)} foram para transportador de fora. Esse valor é "
            f"custo de verdade e não está no cálculo da frota.",
            {**dados, "divergencia": round(vl_externo, 2)}, evid)

    if pr_dif <= 10.0:
        return _veredito(
            "auditoria", "confirma",
            f"Confere: os dois caminhos chegam ao mesmo custo de frota — "
            f"{brl(cv)} pelo caixa do veículo e {brl(cc)} pelo centro de "
            f"custo, {_pr(pr_dif)}% de diferença. A margem da frota se "
            f"sustenta.", dados, evid,
            incert=[f"os dois caminhos leem a mesma tabela de caixa por chaves "
                    f"diferentes: despesa que não foi apontada nem à placa nem "
                    f"a centro de custo de frota escapa dos dois"])

    falta = ("apenas {0} centros de custo de frota para {1} placas ativas"
             .format(int(por["centro_custo"]["qt_chaves"] or 0),
                     int(por["caixa_veiculo"]["qt_chaves"] or 0)))
    return _veredito(
        "auditoria", "contradiz",
        f"Os dois caminhos não fecham: {brl(cv)} pelo caixa do veículo contra "
        f"{brl(cc)} pelo centro de custo, {brl(abs(dif))} de diferença "
        f"({_pr(pr_dif)}%). Há {falta}, então o custo por centro de custo é "
        f"parcial — e enquanto a diferença não for explicada, a margem da "
        f"frota, apurada sobre {brl(receita)} de receita, é um teto, não um "
        f"número fechado.",
        {**dados, "divergencia": round(abs(dif), 2)}, evid)


def aud_plano_veiculo(*, empresa_id, missao_id, tarefa_id, entradas, acoes,
                      alvo) -> Entrega:
    """Contesta Caio: o quilômetro que sustenta o plano é real?

    O plano por placa se apoia inteiro na distância declarada no conhecimento
    (`ctrc.vl_km_rodado`): é ela que diz quem rodou pouco, quem vendeu frete
    barato e quem gastou combustível demais por quilômetro. Se essa distância
    estiver errada, os três diagnósticos caem juntos.

    A porta usada aqui é outra: o hodômetro lido no abastecimento
    (`caixa_veiculo.vl_medidor`). É leitura de painel, não declaração de
    documento. E a divergência não é só erro de digitação — cavalo cujo painel
    andou muito mais do que os CT-es dele somam é cavalo que rodou sem
    conhecimento emitido na placa, e isso é dinheiro, não estatística.
    """
    dias = int(entradas.get("dias") or 90)
    r = _rodar("contraprova.km_por_hodometro", {"dias": dias, "limite": 300},
               empresa_id=empresa_id, missao_id=missao_id,
               tarefa_id=tarefa_id, acoes=acoes)
    if not r.ok:
        return _bloqueada(f"leitura de hodômetro indisponível: {r.erro}")

    hod = {str(l["ds_placa"]).strip(): l for l in r.dados["linhas"]}
    plano = ((alvo.get("resultado") or {}).get("plano") or [])
    if not plano:
        return _veredito(
            "auditoria", "nao_verificavel",
            "a apuração não apontou nenhuma placa, então não há diagnóstico "
            "por veículo para conferir contra o hodômetro.",
            {"placas_no_plano": 0}, [])

    TOL = 0.30          # 30% de folga: abastecer fora do dia distorce a ponta
    rodou_calado, km_inflado, confere = [], [], []
    fora_da_frota: list[dict] = []
    sem_leitura, com_salto = [], []
    for p in plano:
        h = hod.get(p["placa"])
        if h is None:
            sem_leitura.append(p["placa"])
            continue
        if h["id_salto"]:
            com_salto.append(p["placa"])
            continue
        km_h = _f(h["km_hodometro"])
        km_c = _f(p.get("km"))
        # A mesma placa emitindo CT-e como agregado ou terceiro. A apuração
        # filtra proprietário = 1 e não enxerga esses conhecimentos, então o
        # quilômetro deles some da conta e o painel fica "sobrando".
        km_o = _f(h.get("km_outro"))
        rec_o = _f(h.get("vl_receita_outro"))
        item = {"placa": p["placa"], "km_cte": round(km_c, 0),
                "km_hodometro": round(km_h, 0),
                "diferenca": round(km_h - km_c, 0),
                "km_fora_da_frota": round(km_o, 0),
                "receita_fora_da_frota": round(rec_o, 2),
                "ctes_fora_da_frota": int(h.get("qt_ctes_outro") or 0),
                "leituras": int(h["qt_leituras"] or 0),
                "contribuicao": p.get("contribuicao")}
        # Se o apurador já declarou a reclassificação da placa, o achado está
        # reconhecido e não é contestação — vira conferência de que o número
        # declarado bate com o que o CT-e mostra.
        if item["ctes_fora_da_frota"] and not p.get("ctes_reclassificados"):
            fora_da_frota.append(item)
        if km_c <= 0 or km_h <= 0:
            sem_leitura.append(p["placa"])
        elif km_h > (km_c + km_o) * (1 + TOL) and km_h - km_c - km_o > 1000:
            item["receita_por_km_real"] = (round(_f(p["receita"]) / km_h, 2)
                                           if km_h else None)
            rodou_calado.append(item)
        elif km_h < km_c * (1 - TOL) and km_c - km_h > 1000:
            km_inflado.append(item)
        else:
            confere.append(item)

    evid = [_ev("consulta", "atua:contraprova.km_por_hodometro", r.referencia,
                f"hodômetro de {len(hod)} placa(s) em {dias} dias: "
                + "; ".join(f"{i['placa']} CT-e {f_num(i['km_cte'])} km contra "
                            f"painel {f_num(i['km_hodometro'])} km"
                            for i in (rodou_calado + km_inflado + confere)[:6]),
                "atua:caixa_veiculo.vl_medidor",
                r.dados.get("consultada_em", ""))]
    rec_fora = sum(i["receita_fora_da_frota"] for i in fora_da_frota)
    dados = {"placas_no_plano": len(plano), "conferem": len(confere),
             "rodou_sem_cte": rodou_calado, "km_declarado_acima": km_inflado,
             "placas_com_cte_fora_da_frota": fora_da_frota,
             "receita_fora_da_frota": round(rec_fora, 2),
             "sem_leitura_de_hodometro": sem_leitura,
             "hodometro_com_salto": com_salto,
             "tolerancia_pct": TOL}

    # Placa própria emitindo como agregado é achado maior do que o plano: a
    # receita dela não está no resultado da frota, e o custo dela está.
    if fora_da_frota:
        nomes = ", ".join(f"{i['placa']} ({i['ctes_fora_da_frota']} CT-e, "
                          f"{brl(i['receita_fora_da_frota'])})"
                          for i in sorted(fora_da_frota,
                                          key=lambda x: -x["receita_fora_da_frota"])[:4])
        return _veredito(
            "auditoria", "contradiz",
            f"{len(fora_da_frota)} placa(s) do plano emitiram conhecimento "
            f"como agregado ou terceiro no mesmo período: {nomes}, somando "
            f"{brl(rec_fora)} de receita que não entrou no resultado da frota "
            f"própria — enquanto o custo dessas mesmas placas entrou. O plano "
            f"está tratando como veículo ocioso quem faturou por outra "
            f"classificação. Antes de repactuar frete ou pautar venda, é "
            f"preciso decidir o que essas placas são: se são da casa, a "
            f"receita delas volta para a frota e o vermelho muda de tamanho.",
            {**dados, "divergencia": round(rec_fora, 2)}, evid,
            incert=["a classificação está no conhecimento, não no cadastro do "
                    "veículo: a placa pode estar certa no cadastro e errada no "
                    "CT-e, ou o contrário — os dois casos aparecem iguais "
                    "daqui",
                    "veículo vendido ou repassado no meio do período aparece "
                    "assim por motivo legítimo"])

    if rodou_calado:
        pior = max(rodou_calado, key=lambda i: i["diferenca"])
        nomes = ", ".join(f"{i['placa']} ({f_num(i['km_cte'])} contra "
                          f"{f_num(i['km_hodometro'])} km)"
                          for i in rodou_calado[:4])
        km_extra = sum(i["diferenca"] for i in rodou_calado)
        return _veredito(
            "auditoria", "contradiz",
            f"O painel não bate com o conhecimento em {len(rodou_calado)} das "
            f"{len(plano)} placas do plano: {nomes}. São {f_num(km_extra)} km "
            f"rodados a mais do que os CT-es dessas placas declaram. Chamar "
            f"{pior['placa']} de veículo ocioso é errado — ela andou. O que "
            f"não apareceu foi conhecimento emitido nela, e essa é uma "
            f"pergunta maior do que a do plano: quilômetro rodado sem "
            f"documento no próprio veículo.",
            {**dados, "divergencia": km_extra}, evid,
            incert=["parte da diferença é quilômetro que existe e não vira "
                    "conhecimento por natureza: retorno vazio, deslocamento "
                    "para coleta e desvio de rota. Só a diferença que sobra "
                    "depois disso é frete sem documento",
                    "hodômetro só é lido quando o veículo abastece na conta da "
                    "empresa: viagem inteira paga fora do sistema não aparece "
                    "nem no painel nem no CT-e",
                    "o cavalo pode ter puxado carreta em CT-e emitido em outra "
                    "placa; isso explica o quilômetro sem receita e continua "
                    "sendo problema de apontamento"])

    if km_inflado:
        nomes = ", ".join(f"{i['placa']} ({f_num(i['km_cte'])} declarados "
                          f"contra {f_num(i['km_hodometro'])} no painel)"
                          for i in km_inflado[:4])
        return _veredito(
            "auditoria", "contradiz",
            f"{len(km_inflado)} placa(s) do plano declararam no CT-e mais "
            f"quilômetro do que o painel andou: {nomes}. Como o preço por "
            f"quilômetro do plano divide a receita por essa distância, essas "
            f"placas aparecem mais baratas do que são — e a medida proposta "
            f"para elas, repactuar preço, está mirando um número inflado.",
            {**dados, "divergencia": sum(abs(i["diferenca"])
                                         for i in km_inflado)}, evid)

    if not confere:
        return _veredito(
            "auditoria", "nao_verificavel",
            f"Nenhuma das {len(plano)} placas do plano tem leitura de "
            f"hodômetro suficiente no período para conferir a quilometragem "
            f"({len(sem_leitura)} sem leitura, {len(com_salto)} com troca de "
            f"painel). O plano fica de pé sobre a distância declarada no "
            f"conhecimento, sem segunda fonte.", dados, evid)

    return _veredito(
        "auditoria", "confirma",
        f"O hodômetro do abastecimento confirma a quilometragem de "
        f"{len(confere)} das {len(plano)} placas do plano, dentro de "
        f"{int(TOL * 100)}% de folga. A distância que sustenta o diagnóstico "
        f"de giro, de preço por quilômetro e de consumo é real."
        + (f" Ficaram sem conferência {len(sem_leitura) + len(com_salto)} "
           f"placa(s), por falta de leitura ou troca de painel."
           if sem_leitura or com_salto else ""),
        dados, evid,
        incert=["a folga de 30% existe porque o abastecimento não acontece no "
                "dia do fechamento: a ponta do período fica sempre um pouco "
                "fora dos dois lados"])


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
    promessa="A margem que existe atrás de cada conhecimento.", versao=2,
    competencias=["margem-por-cte", "custo-de-carta-frete",
                  "cte-com-margem-negativa", "plano-por-placa",
                  "diesel-por-litro-e-preco"],
    ferramentas=["atua"],
    acoes=["atua.controladoria.margem_por_cte",
           "atua.contraprova.lucratividade_custo_frota",
           "atua.frota.resultado_veiculo",
           "atua.frota.abastecimento_veiculo"],
    entradas={"dias": "int", "pr_margem_min": "num",
              "cd_pessoa_filial": "int", "limite": "int", "foco": "texto"},
    saidas={"receita": "num", "custo_carta_frete": "num",
            "margem_contribuicao": "num", "margem_contribuicao_pct": "num",
            "ctes_margem_negativa": "int", "ctes_sem_carta_frete": "int"},
    saidas_foco={"veiculo": {
        "veiculos_analisados": "int", "veiculos_com_apontamento": "int",
        "veiculos_no_vermelho": "int", "vermelho_total": "num",
        "ganho_estimado_total": "num", "ganho_giro_total": "num",
        "mediana_preco_litro": "num", "mediana_km_por_litro": "num",
        "plano": "lista"}},
    limites={"tempo_s": 120, "custo_centavos": 0},
    criterios=["agregado não soma com detalhe",
               "CT-e sem carta frete fora do cálculo",
               "resultado tratado como contribuição, nunca como lucro"],
    executor=exec_controladoria,
    auditor=aud_custo_da_frota,
))

registrar(Definicao(
    id="controladoria.lucratividade", nome="Vera",
    papel="Analista de Lucratividade", area="Controladoria & Custos",
    promessa="Saber qual setor sustenta a empresa e qual é sustentado por ela.",
    versao=1,
    competencias=["resultado-por-setor", "frota-contra-agenciamento",
                  "resultado-por-agencia"],
    ferramentas=["atua"],
    acoes=["atua.lucratividade.por_setor", "atua.lucratividade.por_agencia",
           "atua.contraprova.km_por_hodometro"],
    entradas={"dias": "int", "cd_pessoa_filial": "int", "limite": "int"},
    saidas={"receita_total": "num", "frota_propria": "dict",
            "agenciamento": "dict", "agencias_apuradas": "int",
            "agencias_no_vermelho": "int",
            "agencias_nao_comparaveis": "int"},
    limites={"tempo_s": 120, "custo_centavos": 0},
    criterios=["carta frete da frota própria fora do custo",
               "CT-e sem carta frete fora do custo e contado à parte",
               "centro de custo que engole a receita marcado como não "
               "comparável, em vez de virar prejuízo de agência",
               "resultado tratado como contribuição, nunca como lucro"],
    executor=exec_lucratividade_setor,
    auditor=aud_plano_veiculo,
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
