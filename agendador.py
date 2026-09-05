"""Agendador de varreduras. É quem faz a NÓRIA perguntar sem ser perguntada.

Cada varredura tem uma chave de idempotência por período: rodar duas vezes no
mesmo dia não cria duas missões iguais. O que ele faz é abrir missão; quem
executa é o trabalhador.
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ferramentas import atua, base as fb      # noqa: E402,F401
from nucleo import bd                         # noqa: E402
from nucleo import orquestrador as orq        # noqa: E402

log = logging.getLogger("noria.agendador")

EMPRESA = 1


def _ja_existe(chave: str) -> bool:
    return bd.linha(
        "SELECT id FROM missao WHERE origem='agendador' AND "
        "json_extract(contexto, '$.chave') = ?", (chave,)) is not None


def _abrir(objetivo: str, contexto: dict, chave: str, prioridade="normal") -> int | None:
    if _ja_existe(chave):
        return None
    ctx = {**contexto, "chave": chave}
    mid = orq.abrir_missao(EMPRESA, objetivo, contexto=ctx, origem="agendador",
                           prioridade=prioridade)
    log.info("varredura agendada: %s (missão %s)", chave, mid)
    return mid


# --------------------------------------------------------------- varreduras
def conciliacao_diaria(dia: date | None = None) -> list[int]:
    """Concilia todas as contas com extrato importado, referente a ontem.

    Ontem, e não hoje: o extrato do dia costuma chegar incompleto.
    """
    d = dia or (datetime.now(bd.FUSO).date() - timedelta(days=1))
    r = fb.rodar("atua", "conta.listar", {}, empresa_id=EMPRESA,
                 acoes_permitidas=["atua.conta.listar"])
    if not r.ok:
        log.warning("varredura de conciliação adiada: %s", r.erro)
        return []
    criadas = []
    for c in r.dados["linhas"]:
        cd = c["cd_conta"]
        banco = (c.get("nm_banco") or "").strip() or f"conta {cd}"
        mid = _abrir(
            f"Conciliar o extrato da conta {cd} em {d.strftime('%d/%m/%Y')} "
            f"contra os lançamentos do ATUA",
            {"cd_conta": cd, "data": d.isoformat(), "banco": banco},
            f"conciliacao:{cd}:{d.isoformat()}")
        if mid:
            criadas.append(mid)
    return criadas


def carteira_semanal(hoje: date | None = None) -> list[int]:
    d = hoje or datetime.now(bd.FUSO).date()
    semana = d.strftime("%G-W%V")
    criadas = []
    for texto, ctx, chave in [
        ("Levantar os títulos a receber vencidos há mais de 90 dias",
         {"id_tipo": 1, "dias": 90}, f"receber90:{semana}"),
        ("Levantar os títulos a pagar vencidos há mais de 30 dias",
         {"id_tipo": 2, "dias": 30}, f"pagar30:{semana}"),
    ]:
        mid = _abrir(texto, ctx, chave)
        if mid:
            criadas.append(mid)
    return criadas


ROTINAS = [
    # (nome, hora, minuto, dias_da_semana ou None p/ todos, função)
    ("conciliação diária", 6, 30, None, conciliacao_diaria),
    ("carteira semanal", 7, 0, {0}, carteira_semanal),   # segunda-feira
]


def rodar_devidas(agora: datetime | None = None) -> int:
    a = agora or datetime.now(bd.FUSO)
    total = 0
    for nome, h, mi, dias, fn in ROTINAS:
        if dias is not None and a.weekday() not in dias:
            continue
        if (a.hour, a.minute // 10) != (h, mi // 10):
            continue
        try:
            criadas = fn()
            total += len(criadas)
            if criadas:
                bd.evento(EMPRESA, "agendador.varredura",
                          f"{nome}: {len(criadas)} missão(ões) abertas "
                          f"sem ninguém pedir.", ator="agendador")
        except Exception as e:  # noqa: BLE001
            log.exception("varredura '%s' falhou", nome)
            bd.evento(EMPRESA, "agendador.falha",
                      f"A varredura '{nome}' falhou: {e}", ator="agendador")
    return total


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    bd.migrar()
    log.info("agendador da NÓRIA no ar")
    while True:
        try:
            rodar_devidas()
        except Exception:  # noqa: BLE001
            log.exception("erro no agendador")
        time.sleep(300)   # confere a cada 5 minutos


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "agora":
        bd.migrar()
        print("conciliação:", conciliacao_diaria())
        print("carteira:", carteira_semanal())
    else:
        main()
