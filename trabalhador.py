"""Trabalhador da NÓRIA. Roda como serviço, sem ninguém pedindo.

É isto que faz o sistema ser autônomo: um laço que acorda, procura missão
inacabada, dá um passo, e volta a dormir. Não depende de navegador aberto,
não depende de quem criou o sistema, não depende de nenhum provedor de IA.

Se o processo morre no meio de uma tarefa, a tarefa fica em 'executando' e é
recuperada na próxima volta — por isso o estado mora no banco, não na memória.
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agentes import registro as ar            # noqa: E402
from ferramentas import atua, base as fb      # noqa: E402,F401
from nucleo import bd, estados                # noqa: E402
from nucleo import orquestrador as orq        # noqa: E402

INTERVALO = int(os.environ.get("NORIA_INTERVALO", "5"))
ORFA_APOS_MIN = int(os.environ.get("NORIA_ORFA_MIN", "15"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("noria")

_parar = False


def _sinal(*_):
    global _parar
    _parar = True
    log.info("sinal recebido — encerrando após o passo atual")


def recuperar_orfas() -> int:
    """Tarefa presa em 'executando' por queda do processo volta para a fila.

    Só volta se ainda tem tentativa. Senão vira falha explícita — nunca some.
    """
    corte = (datetime.now(bd.FUSO) - timedelta(minutes=ORFA_APOS_MIN)).isoformat(
        timespec="seconds")
    presas = bd.linhas(
        "SELECT * FROM tarefa WHERE estado IN ('despachada','executando') "
        "AND atualizada_em < ?", (corte,))
    for t in presas:
        if int(t["tentativas"]) < int(t["max_tentativas"]):
            estados.mover_tarefa(
                t["id"], "falha",
                motivo=f"sem sinal há mais de {ORFA_APOS_MIN} min — o processo "
                       f"provavelmente caiu no meio")
            estados.mover_tarefa(t["id"], "pendente",
                                 motivo="recolocada na fila após recuperação")
        else:
            estados.mover_tarefa(
                t["id"], "falha",
                motivo="sem sinal e sem tentativas restantes")
        log.warning("tarefa %s recuperada", t["id"])
    return len(presas)


def missoes_abertas() -> list[dict]:
    return bd.linhas(
        "SELECT id, empresa_id, estado, prioridade FROM missao WHERE estado NOT IN "
        "('concluida','parcial','cancelada','bloqueada') "
        "ORDER BY CASE prioridade WHEN 'alta' THEN 0 WHEN 'normal' THEN 1 "
        "ELSE 2 END, id")


def volta() -> int:
    """Uma volta do laço. Devolve quantos passos deu."""
    recuperar_orfas()
    passos = 0
    for m in missoes_abertas():
        if _parar:
            break
        try:
            r = orq.avancar(m["id"])
            passos += 1
            log.info("missão %s · %s · %s", m["id"], r.get("passo", "-"),
                     r.get("veredito") or r.get("estado") or "")
        except Exception as e:  # noqa: BLE001 — uma missão ruim não derruba o serviço
            log.exception("falha na missão %s", m["id"])
            bd.evento(m["empresa_id"], "missao.erro_interno",
                      f"O núcleo falhou ao avançar esta missão: {e}",
                      missao_id=m["id"])
            estados.mover_missao(m["id"], "bloqueada",
                                 motivo="erro interno do núcleo")
    return passos


def main() -> None:
    signal.signal(signal.SIGTERM, _sinal)
    signal.signal(signal.SIGINT, _sinal)
    bd.migrar()
    ar.sincronizar(1)
    log.info("trabalhador da NÓRIA no ar · banco %s · intervalo %ss",
             bd.CAMINHO, INTERVALO)

    ocioso = 0
    while not _parar:
        try:
            passos = volta()
        except Exception:  # noqa: BLE001
            log.exception("erro na volta do laço")
            passos = 0
        if passos:
            ocioso = 0
            time.sleep(0.4)          # há trabalho: volta rápido
        else:
            ocioso = min(ocioso + 1, 12)
            time.sleep(INTERVALO)    # ocioso: espera sem gastar
    log.info("trabalhador encerrado")


if __name__ == "__main__":
    main()
