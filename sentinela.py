"""Sentinela: a vigilância contínua da NÓRIA.

O agendador abre missões em horários marcados. Entre um horário e outro a
empresa continua andando — e ninguém estava olhando. A sentinela olha.

A cada rodada ela lê um punhado de indicadores baratos no ATUA, compara com a
leitura anterior guardada em `marcador` e registra um evento **só quando algo
mudou**. Repetir o mesmo número de dez em dez minutos não é vigilância, é
ruído: quem lê para de prestar atenção, e aí o sinal de verdade passa batido.

Quando a mudança cruza um limite que importa (frete não faturado, título
vencendo em volume, receita do dia parada num dia útil), ela não se limita a
registrar: abre missão. É assim que a NÓRIA pergunta sem ser perguntada.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta

from ferramentas import atua, base as fb  # noqa: F401 (registra a ferramenta)
from nucleo import bd
from nucleo import orquestrador as orq
from nucleo.formato import brl

log = logging.getLogger("noria.sentinela")

EMPRESA = 1

# Um dia útil sem CT-e nenhum até as 11h é anormal numa transportadora deste
# porte (média de ~120 CT-es/dia). Abaixo disso a sentinela pergunta.
HORA_ESPERA_MOVIMENTO = 11


# --------------------------------------------------------------- marcadores
def ler_marcador(chave: str) -> dict | None:
    r = bd.linha("SELECT valor FROM marcador WHERE chave=?", (chave,))
    return json.loads(r["valor"]) if r else None


def gravar_marcador(chave: str, valor: dict) -> None:
    bd.executar(
        "INSERT INTO marcador (chave, valor, atualizado_em) VALUES (?,?,?) "
        "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor, "
        "atualizado_em=excluded.atualizado_em",
        (chave, json.dumps(valor, ensure_ascii=False), bd.agora()))


# ------------------------------------------------------------------ o pulso
def pulso_do_faturamento() -> dict:
    """Lê o faturamento do dia e conta o que entrou desde a última olhada.

    É a batida de coração da tela: enquanto o ERP registra CT-e, a NÓRIA
    registra que viu. Um evento por mudança real, nunca por rodada.
    """
    r = fb.rodar("atua", "ceo.pulso", {}, empresa_id=EMPRESA,
                 acoes_permitidas=["atua.ceo.pulso"])
    if not r.ok:
        # Falha de leitura também é notícia: se o ERP some, quem vê a tela
        # precisa saber que o número congelou por falta de resposta, não por
        # falta de movimento.
        bd.evento(EMPRESA, "sentinela.cega",
                  f"A sentinela não conseguiu ler o ERP: {r.erro}",
                  ator="sentinela")
        return {"ok": False, "erro": r.erro}

    linha = (r.dados["linhas"] or [{}])[0]
    agora = datetime.now(bd.FUSO)
    hoje = agora.date().isoformat()
    atual = {"dia": hoje,
             "ctes": int(linha.get("ctes_hoje") or 0),
             "receita": float(linha.get("receita_hoje") or 0.0),
             "em": bd.agora()}

    anterior = ler_marcador("pulso.faturamento")
    gravar_marcador("pulso.faturamento", atual)

    # Primeira leitura do dia (ou de sempre): não há com o que comparar.
    if not anterior or anterior.get("dia") != hoje:
        bd.evento(EMPRESA, "sentinela.pulso",
                  f"Primeira leitura do dia: {atual['ctes']} CT-e(s), "
                  f"{brl(atual['receita'])} faturados até agora.",
                  ator="sentinela", dados=atual)
        return {"ok": True, "novos": atual["ctes"], "primeira": True}

    d_ctes = atual["ctes"] - int(anterior.get("ctes") or 0)
    d_receita = atual["receita"] - float(anterior.get("receita") or 0.0)

    if d_ctes > 0 or abs(d_receita) >= 0.01:
        bd.evento(EMPRESA, "sentinela.pulso",
                  f"+{d_ctes} CT-e(s) e {brl(d_receita)} desde a última "
                  f"leitura. O dia está em {atual['ctes']} CT-e(s), "
                  f"{brl(atual['receita'])}.",
                  ator="sentinela", dados={"delta_ctes": d_ctes,
                                           "delta_receita": round(d_receita, 2),
                                           **atual})
        return {"ok": True, "novos": d_ctes}

    # Nada mudou. Só vira notícia se for hora de já ter mudado.
    if (agora.hour >= HORA_ESPERA_MOVIMENTO and agora.weekday() < 5
            and atual["ctes"] == 0):
        abrir_se_novo(
            "Investigar por que nenhum CT-e foi emitido hoje até agora",
            {"data": agora.date().isoformat(), "motivo": "dia util sem emissao"},
            f"sem_emissao:{hoje}", prioridade="alta")
    return {"ok": True, "novos": 0}


# ------------------------------------------------------------------ missões
def abrir_se_novo(objetivo: str, contexto: dict, chave: str,
                  prioridade: str = "normal") -> int | None:
    """Abre missão sem repetir. A chave é o que impede a enxurrada.

    Sem isso, uma sentinela que roda de 10 em 10 minutos abriria 144 missões
    idênticas por dia e o painel viraria lixo.
    """
    ja = bd.linha("SELECT id FROM missao WHERE origem IN ('sentinela','agendador') "
                  "AND json_extract(contexto, '$.chave') = ?", (chave,))
    if ja:
        return None
    mid = orq.abrir_missao(EMPRESA, objetivo, contexto={**contexto, "chave": chave},
                           origem="sentinela", prioridade=prioridade)
    bd.evento(EMPRESA, "sentinela.missao",
              f"A sentinela abriu a missão {mid} sem ninguém pedir: {objetivo}",
              ator="sentinela", missao_id=mid)
    return mid


# --------------------------------------------------------------- a vigília
def vigiar_carteira() -> dict:
    """Acompanha o vencido a receber e avisa quando ele piora de verdade.

    Um vencido que oscila R$ 5 mil não é notícia. Um salto de 3% ou de meio
    milhão num dia é — e merece missão, não só evento.
    """
    r = fb.rodar("atua", "ceo.carteira", {}, empresa_id=EMPRESA,
                 acoes_permitidas=["atua.ceo.carteira"])
    if not r.ok:
        return {"ok": False, "erro": r.erro}

    receber = next((x for x in r.dados["linhas"] if int(x.get("id_tipo", 0)) == 1),
                   None)
    if not receber:
        return {"ok": True, "sem_dado": True}

    atual = {"vencido": float(receber.get("vencido") or 0.0),
             "qt_vencido": int(receber.get("qt_vencido") or 0),
             "em": bd.agora()}
    anterior = ler_marcador("vigia.carteira")
    gravar_marcador("vigia.carteira", atual)
    if not anterior:
        return {"ok": True, "primeira": True}

    antes = float(anterior.get("vencido") or 0.0)
    delta = atual["vencido"] - antes
    piorou_muito = delta >= 500_000 or (antes > 0 and delta / antes >= 0.03)

    if piorou_muito:
        bd.evento(EMPRESA, "sentinela.alerta",
                  f"O vencido a receber subiu {brl(delta)} e está em "
                  f"{brl(atual['vencido'])} ({atual['qt_vencido']} títulos).",
                  ator="sentinela", dados={"delta": round(delta, 2), **atual})
        abrir_se_novo(
            "Levantar os títulos a receber vencidos há mais de 30 dias após "
            "salto na carteira",
            {"id_tipo": 1, "dias": 30, "salto": round(delta, 2)},
            f"salto_receber:{date.today().isoformat()}", prioridade="alta")
    elif delta <= -500_000:
        # Queda grande também é informação: alguém pagou, ou alguém baixou
        # título indevidamente. Vale registro, não vale missão automática.
        bd.evento(EMPRESA, "sentinela.pulso",
                  f"O vencido a receber caiu {brl(abs(delta))} e está em "
                  f"{brl(atual['vencido'])}.", ator="sentinela")
    return {"ok": True, "delta": delta}


def rodada() -> dict:
    """Uma passada completa da sentinela. Nenhuma falha derruba as outras."""
    resultado = {}
    for nome, fn in (("faturamento", pulso_do_faturamento),
                     ("carteira", vigiar_carteira)):
        try:
            resultado[nome] = fn()
        except Exception as e:  # noqa: BLE001
            log.exception("vigília '%s' falhou", nome)
            resultado[nome] = {"ok": False, "erro": str(e)}
            bd.evento(EMPRESA, "sentinela.falha",
                      f"A vigília '{nome}' falhou: {e}", ator="sentinela")
    return resultado


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    bd.migrar()
    print(json.dumps(rodada(), ensure_ascii=False, indent=2))
