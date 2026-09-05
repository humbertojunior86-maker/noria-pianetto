"""Máquina de estados. Transição inválida levanta erro — nunca é ignorada."""
from __future__ import annotations

from . import bd


class TransicaoInvalida(Exception):
    pass


MISSAO: dict[str, set[str]] = {
    "rascunho":     {"planejada", "cancelada", "bloqueada"},
    "planejada":    {"executando", "cancelada", "bloqueada"},
    "executando":   {"validando", "replanejando", "bloqueada", "cancelada"},
    "replanejando": {"executando", "bloqueada", "cancelada", "parcial"},
    "validando":    {"executando", "replanejando", "concluida", "parcial",
                     "bloqueada", "cancelada"},
    "pausada":      {"executando", "cancelada"},
    "concluida":    set(),
    "parcial":      set(),
    "bloqueada":    {"executando", "replanejando", "cancelada"},
    "cancelada":    set(),
}

TAREFA: dict[str, set[str]] = {
    "pendente":       {"despachada", "cancelada", "substituida"},
    "despachada":     {"executando", "falha", "cancelada", "substituida"},
    "executando":     {"entregue", "falha", "cancelada"},
    "entregue":       {"aprovada", "reprovada", "nao_verificavel"},
    "reprovada":      {"pendente", "cancelada", "substituida"},   # devolução
    "nao_verificavel": {"pendente", "cancelada", "substituida"},
    "falha":          {"pendente", "cancelada"},                  # retentativa
    "aprovada":       set(),
    "cancelada":      set(),
    "substituida":    set(),
}

TERMINAIS_MISSAO = {"concluida", "parcial", "cancelada"}
TERMINAIS_TAREFA = {"aprovada", "cancelada", "substituida"}


def _mover(tabela: str, mapa: dict, id_: int, novo: str, *, ator: str, motivo: str):
    reg = bd.linha(f"SELECT * FROM {tabela} WHERE id = ?", (id_,))
    if not reg:
        raise TransicaoInvalida(f"{tabela} {id_} não existe")
    atual = reg["estado"]
    if novo == atual:
        return reg
    if novo not in mapa.get(atual, set()):
        raise TransicaoInvalida(
            f"{tabela} {id_}: não é permitido ir de '{atual}' para '{novo}'"
        )
    campos = {"estado": novo, "atualizada_em": bd.agora()}
    if tabela == "missao" and novo in TERMINAIS_MISSAO:
        campos["encerrada_em"] = bd.agora()
    bd.atualizar(tabela, id_, campos)
    bd.evento(
        reg["empresa_id"],
        f"{tabela}.estado",
        motivo,
        ator=ator,
        missao_id=reg["missao_id"] if tabela == "tarefa" else id_,
        tarefa_id=id_ if tabela == "tarefa" else None,
        de=atual,
        para=novo,
    )
    reg["estado"] = novo
    return reg


def mover_missao(id_: int, novo: str, *, ator: str = "nucleo", motivo: str = ""):
    return _mover("missao", MISSAO, id_, novo, ator=ator, motivo=motivo or f"missão → {novo}")


def mover_tarefa(id_: int, novo: str, *, ator: str = "nucleo", motivo: str = ""):
    return _mover("tarefa", TAREFA, id_, novo, ator=ator, motivo=motivo or f"tarefa → {novo}")
