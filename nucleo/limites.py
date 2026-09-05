"""Limites, reserva de orçamento e detecção de ciclo improdutivo.

A reserva acontece ANTES do despacho. Sem isso, dez tarefas concorrentes
passam pelo teto simultaneamente porque cada uma leu o saldo antes das outras
gastarem. Reserva-se dentro da mesma transação que despacha.
"""
from __future__ import annotations

import hashlib
import json

from . import bd

PADRAO = {
    "missao": {
        "tempo_s": 1800,
        "custo_centavos": 500,
        "tokens": 400_000,
        "max_tarefas": 40,
        "concorrencia": 4,
        "max_replanejamentos": 3,
    },
    "tarefa": {
        "tempo_s": 240,
        "custo_centavos": 80,
        "tokens": 60_000,
        "max_tentativas": 2,
    },
    "global_dia": {
        "custo_centavos": 5_000,
        "max_tarefas": 600,
    },
}


class LimiteEstourado(Exception):
    def __init__(self, chave: str, teto: int, pedido: int):
        self.chave, self.teto, self.pedido = chave, teto, pedido
        super().__init__(f"limite '{chave}' estourado: teto {teto}, pedido {pedido}")


def teto(empresa_id: int, escopo: str, chave: str) -> int:
    r = bd.linha(
        "SELECT valor FROM limite WHERE empresa_id=? AND escopo=? AND chave=?",
        (empresa_id, escopo, chave),
    )
    if r:
        return int(r["valor"])
    return int(PADRAO.get(escopo, {}).get(chave, 0))


def _saldo_missao(missao_id: int) -> tuple[int, int]:
    """(reservado+realizado, tokens) já comprometidos na missão."""
    r = bd.linha(
        """SELECT
             COALESCE(SUM(CASE WHEN tipo='estorno' THEN -custo_centavos
                               ELSE custo_centavos END), 0) AS custo,
             COALESCE(SUM(CASE WHEN tipo='estorno' THEN -tokens
                               ELSE tokens END), 0) AS tokens
           FROM consumo WHERE missao_id = ?""",
        (missao_id,),
    )
    return int(r["custo"] or 0), int(r["tokens"] or 0)


def reservar(empresa_id: int, missao_id: int, tarefa_id: int,
             custo_centavos: int, tokens: int = 0) -> int:
    """Reserva orçamento. Chame DENTRO da transação que despacha a tarefa."""
    t_custo = teto(empresa_id, "missao", "custo_centavos")
    t_tokens = teto(empresa_id, "missao", "tokens")
    usado_c, usado_t = _saldo_missao(missao_id)

    if t_custo and usado_c + custo_centavos > t_custo:
        raise LimiteEstourado("custo_centavos", t_custo, usado_c + custo_centavos)
    if t_tokens and tokens and usado_t + tokens > t_tokens:
        raise LimiteEstourado("tokens", t_tokens, usado_t + tokens)

    dia = bd.linha(
        """SELECT COALESCE(SUM(CASE WHEN tipo='estorno' THEN -custo_centavos
                                    ELSE custo_centavos END),0) AS c
           FROM consumo WHERE empresa_id=? AND substr(criado_em,1,10)=substr(?,1,10)""",
        (empresa_id, bd.agora()),
    )
    t_dia = teto(empresa_id, "global_dia", "custo_centavos")
    if t_dia and int(dia["c"] or 0) + custo_centavos > t_dia:
        raise LimiteEstourado("custo_dia", t_dia, int(dia["c"] or 0) + custo_centavos)

    return bd.inserir("consumo", {
        "empresa_id": empresa_id, "missao_id": missao_id, "tarefa_id": tarefa_id,
        "tipo": "reserva", "custo_centavos": custo_centavos, "tokens": tokens,
        "ms": 0, "criado_em": bd.agora(),
    })


def realizar(empresa_id: int, missao_id: int, tarefa_id: int, reserva_id: int,
             custo_centavos: int, tokens: int, ms: int) -> None:
    """Fecha a reserva: estorna o reservado e lança o realizado."""
    r = bd.linha("SELECT * FROM consumo WHERE id=?", (reserva_id,))
    if r:
        bd.inserir("consumo", {
            "empresa_id": empresa_id, "missao_id": missao_id, "tarefa_id": tarefa_id,
            "tipo": "estorno", "custo_centavos": r["custo_centavos"],
            "tokens": r["tokens"], "ms": 0, "criado_em": bd.agora(),
        })
    bd.inserir("consumo", {
        "empresa_id": empresa_id, "missao_id": missao_id, "tarefa_id": tarefa_id,
        "tipo": "realizado", "custo_centavos": custo_centavos, "tokens": tokens,
        "ms": ms, "criado_em": bd.agora(),
    })


def concorrencia_livre(empresa_id: int, missao_id: int) -> bool:
    limite = teto(empresa_id, "missao", "concorrencia")
    r = bd.linha(
        "SELECT COUNT(*) AS n FROM tarefa WHERE missao_id=? AND estado IN "
        "('despachada','executando')", (missao_id,))
    return int(r["n"] or 0) < limite


# ------------------------------------------------------ ciclo improdutivo
def assinatura(agente_id: str | None, entradas: dict) -> str:
    bruto = json.dumps([agente_id, entradas], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:32]


def registrar_ciclo(missao_id: int, assin: str, hash_saida: str | None) -> int:
    """Devolve quantas vezes esta mesma (agente, entrada) já rodou sem ganho.

    Ganho = hash de saída diferente do anterior. Saída idêntica significa que
    repetir de novo não vai produzir informação nova.
    """
    r = bd.linha(
        "SELECT * FROM assinatura_exec WHERE missao_id=? AND assinatura=?",
        (missao_id, assin))
    if not r:
        bd.inserir("assinatura_exec", {
            "missao_id": missao_id, "assinatura": assin, "vezes": 1,
            "ultimo_hash_saida": hash_saida, "atualizada_em": bd.agora()})
        return 1
    mesmo = hash_saida is not None and hash_saida == r["ultimo_hash_saida"]
    vezes = int(r["vezes"]) + 1 if mesmo else 1
    bd.atualizar("assinatura_exec", r["id"], {
        "vezes": vezes, "ultimo_hash_saida": hash_saida,
        "atualizada_em": bd.agora()})
    return vezes


IMPRODUTIVO_APOS = 2
