"""Agendador de varreduras. É quem faz a NÓRIA perguntar sem ser perguntada.

Cada varredura tem uma chave de idempotência por período: rodar duas vezes no
mesmo dia não cria duas missões iguais. O que ele faz é abrir missão; quem
executa é o trabalhador.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ferramentas import atua, base as fb      # noqa: E402,F401
from nucleo import bd                         # noqa: E402
from nucleo import orquestrador as orq        # noqa: E402
import sentinela                              # noqa: E402

log = logging.getLogger("noria.agendador")

EMPRESA = 1

# De quanto em quanto tempo a sentinela olha a empresa. Dez minutos é o ponto
# em que a tela parece viva sem transformar o ERP em alvo de consulta.
INTERVALO_VIGILIA = 600


def _ja_existe(chave: str) -> bool:
    """Já existe missão viva com esta chave?

    Cancelada não conta. Antes contava, e uma missão cancelada por engano
    trancava a varredura daquele dia para sempre — o operador cancelava o
    item errado e a NÓRIA simplesmente parava de perguntar, sem avisar.
    """
    return bd.linha(
        "SELECT id FROM missao WHERE origem IN ('agendador','sentinela') AND "
        "estado <> 'cancelada' AND json_extract(contexto, '$.chave') = ?",
        (chave,)) is not None


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



# --------------------------------------------------- varreduras de vigilância
# Cada uma dá trabalho a um agente que antes ficava parado. O contexto carrega
# `agente_id` porque o orquestrador confia em quem abriu a missão mais do que
# no texto do objetivo — "duplicidade de pagamento" contém a palavra "pagar" e
# ia parar no agente de cobrança.
VIGILANCIA = {
    "duplicidade": (
        "contas.pagar",
        "Procurar pagamentos em duplicidade entre os títulos a pagar",
        {"dias": 5, "dias_retro": 365}),
    "cte_sem_titulo": (
        "comercial.faturamento",
        "Encontrar CT-es autorizados que não geraram título a receber",
        {"dias": 30, "carencia_dias": 7}),
    "cliente_sumiu": (
        "comercial.inteligencia",
        "Identificar clientes regulares que pararam de faturar",
        {"dias_base": 180, "dias_recente": 60}),
    "margem_cte": (
        "controladoria.margem",
        "Apurar a margem por CT-e do último mês contra o custo de carta frete",
        {"dias": 30, "pr_margem_min": 5}),
    "frota_veiculo": (
        "frota.resultado",
        "Apurar receita e custo por veículo da frota própria",
        {"dias": 90}),
    "setor_lucratividade": (
        "controladoria.lucratividade",
        "Apurar o resultado por setor: frota própria contra agenciamento e por agência",
        {"dias": 90, "limite": 60}),
    "cte_pendente": (
        "fiscal.documento",
        "Levantar CT-es sem autorização da SEFAZ",
        {"dias": 90}),
}


def _rodar_vigilancia(chave: str, d: date) -> list[int]:
    agente, objetivo, params = VIGILANCIA[chave]
    mid = _abrir(objetivo, {"agente_id": agente, **params},
                 f"{chave}:{d.isoformat()}")
    return [mid] if mid else []


ROTINAS = [
    # (chave, nome, hora, dias_da_semana ou None p/ todos, função)
    #
    # As varreduras estão espalhadas pelo dia de propósito. Antes eram duas, e
    # a empresa ficava sem ninguém olhando das 6h40 até a manhã seguinte —
    # quem abria o sistema à tarde via um cérebro parado, porque ele estava
    # mesmo. Também evitam a janela 8h-11h, que é o pico da operação no ERP.
    ("conciliacao", "conciliação diária", 6, None, conciliacao_diaria),
    ("receber90", "cobrança: a receber +90 dias", 7, {0}, None),
    ("pagar30", "contas a pagar: vencidos +30 dias", 7, {2}, None),
    ("cte_sem_titulo", "faturamento: frete entregue sem título", 11,
     {1, 3, 5}, None),
    # Sábado entra aqui de propósito: CT-e preso na SEFAZ e frete entregue sem
    # título não esperam segunda-feira, e a operação da Pianetto roda no
    # sábado. Domingo a NÓRIA concilia e apura o resultado por setor; o resto
    # descansa, porque descanso também é decisão.
    ("cte_pendente", "fiscal: CT-e sem autorização da SEFAZ", 12,
     {0, 1, 2, 3, 4, 5}, None),
    ("receber30", "cobrança: a receber +30 dias", 13, {0, 2, 4}, None),
    ("duplicidade", "contas a pagar: pagamento em duplicidade", 14, {0}, None),
    ("cliente_sumiu", "comercial: cliente que parou de faturar", 15, {3}, None),
    ("pagar15", "contas a pagar: vencidos +15 dias", 16, {1, 3}, None),
    ("frota_veiculo", "frota: resultado por veículo", 17, {0}, None),
    ("margem_cte", "controladoria: margem por CT-e", 17, {4}, None),
    # Todo dia, sem exceção de domingo. Esta varredura carrega a contraprova
    # do custo da frota, e contraprova que só roda duas vezes por semana
    # sustenta um número de até três dias atrás na tela do CEO. O peso é
    # baixo: três consultas de menos de um segundo, fora do pico do ERP.
    ("setor_lucratividade", "controladoria: resultado por setor e contraprova "
     "do custo da frota", 17, None, None),
    ("receber_fim_de_dia", "cobrança: fechamento do dia", 18, {0, 1, 2, 3, 4},
     None),
]


# As rotinas de carteira só mudam o parâmetro, então compartilham o executor.
CARTEIRA = {
    "receber90": (1, 90, "Levantar os títulos a receber vencidos há mais de 90 dias"),
    "pagar30": (2, 30, "Levantar os títulos a pagar vencidos há mais de 30 dias"),
    "receber30": (1, 30, "Levantar os títulos a receber vencidos há mais de 30 dias"),
    "pagar15": (2, 15, "Levantar os títulos a pagar vencidos há mais de 15 dias"),
    "receber_fim_de_dia": (1, 60,
                           "Fechar o dia com os títulos a receber vencidos há "
                           "mais de 60 dias"),
}


def _rodar_carteira(chave: str, d: date) -> list[int]:
    id_tipo, dias, texto = CARTEIRA[chave]
    mid = _abrir(texto, {"id_tipo": id_tipo, "dias": dias},
                 f"{chave}:{d.isoformat()}")
    return [mid] if mid else []


def rodar_devidas(agora: datetime | None = None) -> int:
    """Roda o que já passou da hora e ainda não rodou hoje.

    A versão anterior comparava hora e dezena de minuto com o relógio: se o
    processo estivesse reiniciando naquele instante exato, a varredura do dia
    simplesmente não acontecia e ninguém ficava sabendo. Agora a pergunta é
    "já passou da hora e ainda não rodou hoje?", que sobrevive a reinício,
    queda de máquina e atraso.
    """
    a = agora or datetime.now(bd.FUSO)
    hoje = a.date()
    total = 0
    for chave, nome, h, dias, fn in ROTINAS:
        if dias is not None and a.weekday() not in dias:
            continue
        if a.hour < h:
            continue
        if ler_marcador(f"rotina:{chave}") == hoje.isoformat():
            continue
        try:
            if fn:
                criadas = fn()
            elif chave in CARTEIRA:
                criadas = _rodar_carteira(chave, hoje)
            else:
                criadas = _rodar_vigilancia(chave, hoje)
            gravar_marcador(f"rotina:{chave}", hoje.isoformat())
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


# --------------------------------------------------------------- marcadores
def ler_marcador(chave: str) -> str | None:
    r = bd.linha("SELECT valor FROM marcador WHERE chave=?", (chave,))
    return json.loads(r["valor"]) if r else None


def gravar_marcador(chave: str, valor) -> None:
    bd.executar(
        "INSERT INTO marcador (chave, valor, atualizado_em) VALUES (?,?,?) "
        "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor, "
        "atualizado_em=excluded.atualizado_em",
        (chave, json.dumps(valor, ensure_ascii=False), bd.agora()))


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    bd.migrar()
    log.info("agendador da NÓRIA no ar")
    proxima_vigilia = 0.0
    while True:
        try:
            rodar_devidas()
        except Exception:  # noqa: BLE001
            log.exception("erro no agendador")
        # A sentinela roda muito mais que as varreduras: é ela que mantém a
        # empresa sob observação entre um horário marcado e outro.
        if time.monotonic() >= proxima_vigilia:
            try:
                sentinela.rodada()
            except Exception:  # noqa: BLE001
                log.exception("erro na sentinela")
            proxima_vigilia = time.monotonic() + INTERVALO_VIGILIA
        time.sleep(60)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "agora":
        bd.migrar()
        print("conciliação:", conciliacao_diaria())
        print("carteira:", carteira_semanal())
    elif len(sys.argv) > 1 and sys.argv[1] == "vigiar":
        bd.migrar()
        print("sentinela:", sentinela.rodada())
    else:
        main()
