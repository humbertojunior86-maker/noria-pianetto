"""O que é crítico na Pianetto — e o que não é.

Um sistema que grita por tudo é igual a um sistema que não grita: em duas
semanas o dono desliga o aviso. Por isso o corte está escrito aqui, em um
arquivo só, com o número na frente de cada regra. Quem discorda muda o número
e passa a valer no mesmo dia — não é preciso mexer em código espalhado.

Regra de ouro: alerta crítico é o que muda uma decisão HOJE. Se o dono lê e
pensa "amanhã eu vejo", não era crítico e não devia ter tocado o telefone.
"""
from __future__ import annotations

from nucleo import bd
from nucleo.formato import brl

# ------------------------------------------------------------------ limites
# Dinheiro que, sozinho, justifica interromper o dia do dono.
DINHEIRO_CRITICO = 250_000.0

# Salto na carteira vencida dentro do mesmo dia.
SALTO_CARTEIRA = 500_000.0

# Espécies que são críticas por natureza, independentemente do valor: o
# problema não é o tamanho, é o tipo.
ESPECIES_SEMPRE = {
    "divergencia",      # dois lugares da casa dizem números diferentes
    "falha_sistema",    # o ERP calou, e número congelado engana mais que erro
    "fraude",           # suspeita de desvio
    "risco_legal",      # prazo processual, autuação, multa
}

# Espécies que só sobem a crítico quando passam do limite de dinheiro.
ESPECIES_POR_VALOR = {"dinheiro_parado", "prejuizo", "custo", "inadimplencia"}

# Eventos da sentinela que valem toque imediato.
EVENTOS_CRITICOS = {
    "sentinela.alerta",   # a carteira deu um salto
    "sentinela.falha",    # a própria vigilância caiu
}


def e_critico(aviso: dict) -> tuple[bool, str]:
    """Diz se um aviso é crítico e POR QUÊ — o motivo vai junto na tela.

    Devolver o motivo é parte da regra: aviso que chega sem explicar o corte
    vira ruído na terceira vez que toca.
    """
    esp = (aviso.get("especie") or "").strip()
    grav = (aviso.get("gravidade") or "").strip()
    valor = float(aviso.get("valor") or 0.0)

    if grav == "critica":
        return True, "marcado como crítico pelo agente que apurou"
    if esp in ESPECIES_SEMPRE:
        return True, f"espécie {esp} é crítica por natureza, independente do valor"
    if esp in ESPECIES_POR_VALOR and valor >= DINHEIRO_CRITICO:
        return True, f"{brl(valor)} acima do corte de {brl(DINHEIRO_CRITICO)}"
    if grav == "alta" and valor >= DINHEIRO_CRITICO:
        return True, "gravidade alta com dinheiro acima do corte"
    return False, ""


def marcador_visto(chave: str) -> int:
    """Até onde o dono já foi avisado. Zero significa 'nunca avisei nada'."""
    r = bd.linha("SELECT valor FROM marcador WHERE chave=?", (chave,))
    if not r:
        return 0
    try:
        return int(str(r["valor"]).strip('"'))
    except (TypeError, ValueError):
        return 0


def gravar_visto(chave: str, id_: int) -> None:
    bd.executar(
        "INSERT INTO marcador (chave, valor, atualizado_em) VALUES (?,?,?) "
        "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor, "
        "atualizado_em=excluded.atualizado_em",
        (chave, str(int(id_)), bd.agora()))
