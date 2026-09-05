"""Registro de ferramentas. Toda execução é gravada — inclusive as que falham.

Um agente só executa o que está na sua lista de ferramentas E na lista de
ações permitidas da tarefa. As duas precisam concordar. Ferramenta que escreve
exige idempotência e, quando tem impacto, passa por aprovação antes.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from nucleo import bd


@dataclass
class Resultado:
    ok: bool
    dados: Any = None
    resumo: str = ""
    linhas: int = 0
    erro: str | None = None
    # origem-raiz da informação: duas evidências com a mesma raiz NÃO contam
    # como confirmação independente.
    raiz: str | None = None
    referencia: str = ""


@dataclass
class Ferramenta:
    id: str
    nome: str
    descricao: str
    escreve: bool
    executar: Callable[..., Resultado]
    operacoes: list[str] = field(default_factory=list)
    # o que impede esta ferramenta de funcionar hoje, se algo impede
    limitacao: str | None = None

    def disponivel(self) -> bool:
        return self.limitacao is None


_REGISTRO: dict[str, Ferramenta] = {}


def registrar(f: Ferramenta) -> Ferramenta:
    _REGISTRO[f.id] = f
    return f


def obter(id_: str) -> Ferramenta | None:
    return _REGISTRO.get(id_)


def todas() -> list[Ferramenta]:
    return list(_REGISTRO.values())


def hash_saida(dados: Any) -> str:
    bruto = json.dumps(dados, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:32]


def rodar(
    ferramenta_id: str,
    operacao: str,
    entrada: dict,
    *,
    empresa_id: int,
    missao_id: int | None = None,
    tarefa_id: int | None = None,
    acoes_permitidas: list[str] | None = None,
    chave_idem: str | None = None,
) -> Resultado:
    """Ponto único de execução. Nada chama uma ferramenta por fora daqui."""
    f = obter(ferramenta_id)
    alvo = f"{ferramenta_id}.{operacao}"

    if f is None:
        return Resultado(False, erro=f"ferramenta '{ferramenta_id}' não existe")
    if acoes_permitidas is not None and alvo not in acoes_permitidas:
        return Resultado(
            False,
            erro=f"ação '{alvo}' fora do escopo autorizado da tarefa",
        )
    if not f.disponivel():
        return Resultado(False, erro=f"ferramenta indisponível: {f.limitacao}")

    # Idempotência: se já rodou com esta chave e deu certo, devolve o registro
    # anterior em vez de repetir o efeito.
    if chave_idem and f.escreve:
        ant = bd.linha(
            "SELECT * FROM execucao_ferramenta WHERE chave_idem=? AND estado='ok'",
            (chave_idem,),
        )
        if ant:
            return Resultado(
                True,
                dados=bd.dj(ant["saida_resumo"], {}),
                resumo="execução anterior reaproveitada (idempotência)",
                linhas=int(ant["linhas"] or 0),
            )

    exec_id = bd.inserir("execucao_ferramenta", {
        "empresa_id": empresa_id, "missao_id": missao_id, "tarefa_id": tarefa_id,
        "ferramenta": ferramenta_id, "operacao": operacao,
        "escreve": 1 if f.escreve else 0,
        "entrada": bd.j(entrada), "chave_idem": chave_idem,
        "estado": "executando", "iniciada_em": bd.agora(),
    })

    t0 = time.monotonic()
    try:
        r = f.executar(operacao=operacao, empresa_id=empresa_id, **entrada)
    except TimeoutError as e:
        # Timeout em escrita não repete cegamente: marca ambíguo.
        estado = "ambiguo" if f.escreve else "timeout"
        bd.atualizar("execucao_ferramenta", exec_id, {
            "estado": estado, "erro": str(e),
            "ms": int((time.monotonic() - t0) * 1000),
            "terminada_em": bd.agora()})
        return Resultado(False, erro=f"{estado}: {e}")
    except Exception as e:  # noqa: BLE001 — falha de ferramenta não derruba o núcleo
        bd.atualizar("execucao_ferramenta", exec_id, {
            "estado": "erro", "erro": str(e)[:800],
            "ms": int((time.monotonic() - t0) * 1000),
            "terminada_em": bd.agora()})
        return Resultado(False, erro=str(e)[:800])

    bd.atualizar("execucao_ferramenta", exec_id, {
        "estado": "ok" if r.ok else "erro",
        "saida_resumo": bd.j(r.dados)[:20000] if r.ok else None,
        "linhas": r.linhas, "erro": r.erro,
        "ms": int((time.monotonic() - t0) * 1000),
        "terminada_em": bd.agora()})
    return r
