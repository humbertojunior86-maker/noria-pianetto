"""Verificadores de código: recomputam o resultado por conta própria.

Esta é a camada objetiva da validação. Um verificador NÃO lê a conclusão do
agente e diz se concorda — ele refaz a conta a partir da evidência bruta e
compara. Se o agente afirmou 41 divergências e o verificador conta 43, reprova.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from nucleo import bd

TOLERANCIA = Decimal("0.01")   # um centavo
_REG: dict[str, Callable] = {}


def verificador(nome: str):
    def deco(f):
        _REG[nome] = f
        return f
    return deco


def obter(nome: str) -> Callable | None:
    return _REG.get(nome)


def _dec(v: Any) -> Decimal:
    try:
        return Decimal(str(v if v is not None else 0))
    except (InvalidOperation, ValueError):
        return Decimal(0)


# ------------------------------------------------------------------ genéricos
@verificador("soma_confere")
def soma_confere(afirmado: dict, bruto: dict, params: dict) -> tuple[str, str]:
    """Refaz a soma de um campo sobre as linhas brutas."""
    campo = params.get("campo", "vl_lancamento")
    chave = params.get("chave", "total")
    linhas = bruto.get("linhas", [])
    calc = sum((_dec(l.get(campo)) for l in linhas), Decimal(0))
    dito = _dec(afirmado.get(chave))

    # Conjunto cortado pelo limite da consulta: a soma do todo não pode ser
    # recomputada a partir da parte. Dizer "aprovado" aqui seria mentira, e
    # dizer "reprovado" acusaria o agente de um erro que ele não cometeu.
    if afirmado.get("truncado"):
        if calc - dito > TOLERANCIA:
            return "reprovado", (
                f"a parte trazida ({calc}) é maior que o total afirmado "
                f"({dito}) — o total está errado")
        return "nao_verificavel", (
            f"o conjunto foi cortado em {len(linhas)} linha(s) de "
            f"{afirmado.get('quantidade')}; a soma do todo veio da própria "
            f"consulta e não pôde ser refeita aqui. A parte trazida "
            f"({calc}) cabe dentro do total afirmado ({dito})")

    if abs(calc - dito) <= TOLERANCIA:
        return "aprovado", f"soma de {campo} confere: {calc}"
    return "reprovado", (
        f"soma de {campo} não confere — agente disse {dito}, "
        f"recomputado {calc} sobre {len(linhas)} linha(s)")


@verificador("contagem_confere")
def contagem_confere(afirmado: dict, bruto: dict, params: dict) -> tuple[str, str]:
    chave = params.get("chave", "quantidade")
    linhas = bruto.get("linhas", [])
    # Consulta que devolve linha de total junto com linha de detalhe não pode
    # ser conferida contra o total bruto de linhas. `onde` diz qual subconjunto
    # o agente afirmou ter contado — sem isso o verificador reprovava o agente
    # honesto por comparar laranja com o caixote inteiro.
    onde = params.get("onde") or {}
    if onde:
        linhas = [r for r in linhas
                  if all(r.get(k) == v for k, v in onde.items())]
    dito = int(afirmado.get(chave) or 0)
    if afirmado.get("truncado"):
        if len(linhas) > dito:
            return "reprovado", (
                f"vieram {len(linhas)} linha(s) mas o total afirmado é {dito}")
        return "nao_verificavel", (
            f"conjunto cortado em {len(linhas)} linha(s); a contagem do todo "
            f"({dito}) veio da própria consulta e não pôde ser refeita aqui")
    if dito == len(linhas):
        return "aprovado", f"contagem confere: {len(linhas)}"
    return "reprovado", (
        f"contagem não confere — agente disse {dito}, recomputado {len(linhas)}")


@verificador("sem_duplicidade")
def sem_duplicidade(afirmado: dict, bruto: dict, params: dict) -> tuple[str, str]:
    campos = params.get("campos", ["cd_conciliado"])
    fonte = (bruto.get("ofx") or bruto or {})
    vistos, dups = set(), 0
    for l in fonte.get("linhas", []):
        k = tuple(l.get(c) for c in campos)
        if k in vistos:
            dups += 1
        vistos.add(k)
    if dups == 0:
        return "aprovado", "nenhuma linha duplicada no conjunto analisado"
    return "reprovado", f"{dups} linha(s) duplicada(s) por {campos}"


@verificador("periodo_coberto")
def periodo_coberto(afirmado: dict, bruto: dict, params: dict) -> tuple[str, str]:
    """Confere se as linhas realmente pertencem ao período afirmado."""
    de, ate = params.get("de"), params.get("ate")
    campo = params.get("campo", "data")
    if not de or not ate:
        return "nao_verificavel", "período de referência não informado"
    fonte = (bruto.get("par") or bruto.get("ofx") or bruto or {})
    fora = [str(l.get(campo)) for l in fonte.get("linhas", [])
            if l.get(campo) and not (str(de) <= str(l[campo])[:10] <= str(ate))]
    if not fora:
        return "aprovado", f"todas as linhas dentro de {de} a {ate}"
    return "reprovado", f"{len(fora)} linha(s) fora do período (ex.: {fora[0]})"


@verificador("toda_afirmacao_tem_evidencia")
def toda_afirmacao_tem_evidencia(afirmado: dict, bruto: dict,
                                 params: dict) -> tuple[str, str]:
    """Entrega sem lastro é recusada. É o teste de aceitação nº 3."""
    entrega_id = params.get("entrega_id")
    if not entrega_id:
        return "nao_verificavel", "entrega não identificada"
    # Cobre fato E indício. Antes olhava só `fato`, e um agente honesto que
    # marcava suas conclusões como indício — que é o certo para duplicidade,
    # margem e cliente que sumiu — passava por agente que não afirmou nada.
    # A exigência de lastro é maior no indício, não menor.
    fatos = bd.linhas(
        "SELECT id, texto, evidencia_id, natureza FROM afirmacao "
        "WHERE entrega_id=? AND natureza IN ('fato','indicio')", (entrega_id,))
    orfas = [f for f in fatos if not f["evidencia_id"]]
    if not fatos:
        return "nao_verificavel", "a entrega não declarou nenhuma afirmação"
    if not orfas:
        qt_i = sum(1 for f in fatos if f["natureza"] == "indicio")
        detalhe = f"{len(fatos)} afirmação(ões) com evidência ligada"
        if qt_i:
            detalhe += f" ({qt_i} declarada(s) como indício, não como fato)"
        return "aprovado", detalhe
    return "reprovado", (
        f"{len(orfas)} de {len(fatos)} afirmação(ões) sem evidência — "
        f"ex.: “{orfas[0]['texto'][:90]}”")


@verificador("fontes_independentes")
def fontes_independentes(afirmado: dict, bruto: dict, params: dict) -> tuple[str, str]:
    """Duas evidências com a mesma raiz contam como uma só confirmação."""
    missao_id = params.get("missao_id")
    minimo = int(params.get("minimo", 2))
    raizes = bd.linhas(
        "SELECT DISTINCT raiz FROM evidencia WHERE missao_id=? AND raiz IS NOT NULL",
        (missao_id,))
    n = len({r["raiz"] for r in raizes})
    if n >= minimo:
        return "aprovado", f"{n} origem(ns)-raiz distintas sustentam a conclusão"
    return "nao_verificavel", (
        f"apenas {n} origem-raiz distinta — repetição da mesma fonte não "
        f"confirma o fato de forma independente")


@verificador("artefato_existe")
def artefato_existe(afirmado: dict, bruto: dict, params: dict) -> tuple[str, str]:
    """Arquivo prometido precisa existir e abrir. Nada de link morto."""
    from pathlib import Path
    missao_id = params.get("missao_id")
    arts = bd.linhas("SELECT * FROM artefato WHERE missao_id=?", (missao_id,))
    if not arts:
        return "nao_verificavel", "nenhum artefato declarado"
    faltando = [a["nome"] for a in arts
                if not Path(a["caminho"]).is_file()
                or Path(a["caminho"]).stat().st_size == 0]
    if not faltando:
        return "aprovado", f"{len(arts)} artefato(s) existem e têm conteúdo"
    return "reprovado", f"artefato(s) inexistente(s) ou vazio(s): {', '.join(faltando)}"


# ------------------------------------------------------------- conciliação
@verificador("conciliacao_fecha")
def conciliacao_fecha(afirmado: dict, bruto: dict, params: dict) -> tuple[str, str]:
    """Recompõe o pareamento extrato × ATUA a partir das linhas brutas.

    Não lê a conclusão do agente para concordar com ela: refaz a contagem de
    movimentos sem quitação e de valores divergentes, e compara.
    """
    linhas = bruto.get("par", {}).get("linhas", [])
    if not linhas:
        return "nao_verificavel", "pareamento bruto não veio junto da entrega"

    por_mov: dict = {}
    for l in linhas:
        por_mov.setdefault(l.get("cd_conciliado"), []).append(l)

    sem_par = 0
    diverg = 0
    for itens in por_mov.values():
        quitas = [i for i in itens if i.get("cd_lancamento")]
        if not quitas:
            sem_par += 1
            continue
        if any(int(i.get("qt_movimentos") or 0) != 1 for i in quitas):
            continue
        v_ext = _dec(itens[0].get("vl_extrato")).copy_abs()
        v_erp = sum((_dec(i.get("vl_erp")).copy_abs() for i in quitas), Decimal(0))
        if abs(v_ext - v_erp) > TOLERANCIA:
            diverg += 1

    dito_sem = int(afirmado.get("sem_par_extrato") or 0)
    dito_div = int(afirmado.get("valor_divergente") or 0)
    dito_mov = int(afirmado.get("movimentos_extrato") or 0)

    erros = []
    if dito_mov != len(por_mov):
        erros.append(f"movimentos: disse {dito_mov}, recomputado {len(por_mov)}")
    if dito_sem != sem_par:
        erros.append(f"sem par: disse {dito_sem}, recomputado {sem_par}")
    if dito_div != diverg:
        erros.append(f"valor divergente: disse {dito_div}, recomputado {diverg}")

    if erros:
        return "reprovado", "pareamento não bate — " + "; ".join(erros)
    return "aprovado", (
        f"pareamento recomputado bate: {len(por_mov)} movimento(s), "
        f"{sem_par} sem lançamento no ATUA, {diverg} com valor divergente")
