"""O que merece sair da NÓRIA e chegar em quem decide.

Um agente entrega dezenas de números por dia. Quase nenhum é notícia. Este
módulo é a régua que separa o que é achado — dinheiro parado, resultado no
vermelho, risco fiscal, auditor contradizendo o analista, agente travado — do
que é só rotina que fechou.

A régua é declarada, não adivinhada. Para cada agente está escrito qual campo
da entrega carrega o dinheiro, a partir de que valor aquilo vira aviso e como
a frase é montada. Campo que não existe na entrega não vira aviso: a fila
prefere ficar vazia a inventar motivo.

Quem entrega o aviso (e-mail, mensagem, o que for) não mora aqui. Aqui só se
decide o que sai. A fila é do sistema; o carteiro é trocável.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from nucleo import bd
from nucleo.formato import brl

log = logging.getLogger("noria.avisos")


@dataclass(frozen=True)
class Regra:
    """Um motivo para incomodar o dono da empresa."""
    campo: str            # onde está o número na entrega
    especie: str          # dinheiro_parado | vermelho | risco | divergencia
    titulo: str           # assunto curto
    piso: float           # abaixo disto não vira aviso
    campo_qt: str = ""    # quantidade, quando existir
    dinheiro: bool = True  # o número é reais? (senão é contagem)


# Cada linha aqui foi conferida contra entrega real em produção: o campo
# existe, tem esse nome e carrega esse significado. Inventar campo aqui faria
# a fila calar justamente quando tivesse notícia.
REGRAS: dict[str, list[Regra]] = {
    "comercial.faturamento": [
        Regra("valor", "dinheiro_parado",
              "CT-e autorizado sem título a receber", 50_000, "quantidade"),
    ],
    "cobranca.carteira": [
        Regra("total", "dinheiro_parado",
              "Título vencido em aberto", 100_000, "quantidade"),
    ],
    "fiscal.documento": [
        Regra("valor_pendentes", "risco",
              "Documento sem autorização da SEFAZ", 50_000,
              "pendentes_abertos"),
    ],
    "controladoria.margem": [
        Regra("vermelho_total", "vermelho",
              "Veículo próprio no vermelho", 10_000, "veiculos_no_vermelho"),
        Regra("ganho_estimado_total", "dinheiro_parado",
              "Preço e consumo fora da mediana da casa", 50_000),
        Regra("valor_margem_negativa", "vermelho",
              "CT-e com margem negativa", 50_000, "ctes_margem_negativa"),
        Regra("receita_reclassificada_total", "risco",
              "Receita de placa própria classificada como agenciamento",
              50_000, "placas_reclassificadas"),
    ],
    "controladoria.lucratividade": [
        Regra("agencias_no_vermelho", "vermelho",
              "Agência com resultado negativo", 1, dinheiro=False),
    ],
    "tesouraria.conciliador": [
        Regra("valor_sem_par", "risco",
              "Movimento de extrato sem par no ATUA", 20_000, "sem_par_extrato"),
    ],
    "contas.pagar": [
        Regra("valor", "dinheiro_parado",
              "Pagamento suspeito de duplicidade", 20_000, "quantidade"),
        Regra("total", "dinheiro_parado",
              "Pagamento suspeito de duplicidade", 20_000, "quantidade"),
    ],
    "comercial.inteligencia": [
        Regra("valor", "dinheiro_parado",
              "Cliente regular que parou de faturar", 100_000, "quantidade"),
    ],
}


def _num(d: dict, campo: str):
    v = d.get(campo)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _gravar(dados: dict) -> bool:
    """Insere se a chave for nova. Chave repetida é o mesmo achado de novo."""
    if bd.linha("SELECT id FROM aviso WHERE chave=?", (dados["chave"],)):
        return False
    bd.inserir("aviso", dados)
    return True


def _pendura(e: dict, nome: str, especie: str, gravidade: str, titulo: str,
             texto: str, chave: str, valor=None, qt=None) -> bool:
    return _gravar({
        "empresa_id": e["empresa_id"], "entrega_id": e["id"],
        "missao_id": e["missao_id"], "agente_id": e["agente_id"],
        "agente_nome": nome, "especie": especie, "gravidade": gravidade,
        "titulo": titulo, "texto": texto, "valor": valor, "quantidade": qt,
        "chave": chave, "estado": "pendente", "criado_em": bd.agora(),
    })


def varrer(empresa_id: int, desde_id: int = 0) -> int:
    """Lê as entregas novas e pendura na fila o que é notícia.

    Roda junto da vigilância. Não chama nada de fora: a NÓRIA decide sozinha
    o que quer contar, mesmo que ninguém esteja escutando naquele instante.
    """
    from agentes import registro as ar

    ultima = desde_id
    if not ultima:
        m = bd.linha("SELECT valor FROM marcador WHERE chave='aviso:ultima_entrega'")
        ultima = int(bd.dj(m["valor"], 0) or 0) if m else 0

    novas = bd.linhas(
        "SELECT e.id, e.empresa_id, e.missao_id, e.status_declarado, e.resumo, "
        "e.resultado, t.agente_id FROM entrega e JOIN tarefa t ON t.id=e.tarefa_id "
        "WHERE e.empresa_id=? AND e.id>? ORDER BY e.id", (empresa_id, ultima))
    if not novas:
        return 0

    criados = 0
    for e in novas:
        res = bd.dj(e["resultado"], {}) or {}
        d = ar.obter(e["agente_id"]) if e["agente_id"] else None
        nome = d.nome if d else (e["agente_id"] or "NÓRIA")
        resumo = (e["resumo"] or "").strip()

        # 1. O executor não conseguiu terminar. Isto é notícia: parte da
        #    empresa ficou sem olhar hoje, e ninguém saberia disso sozinho.
        if e["status_declarado"] == "bloqueada":
            criados += _pendura(
                e, nome, "travado", "media",
                f"{nome} não conseguiu concluir",
                resumo or "sem motivo declarado",
                f"travado:{e['agente_id']}:{e['id']}")
            continue

        # 2. Auditor contradizendo o analista. O número está em dúvida por
        #    outro caminho do banco — sai na frente de qualquer valor.
        if str(res.get("veredito") or "") == "contradiz":
            criados += _pendura(
                e, nome, "divergencia", "alta",
                f"{nome} contradiz a apuração",
                resumo, f"contradiz:{e['agente_id']}:{e['id']}",
                valor=_num(res, "divergencia"))
            continue

        # 3. Achado com dinheiro em cima.
        for r in REGRAS.get(e["agente_id"] or "", []):
            v = _num(res, r.campo)
            if v is None:
                continue
            v = abs(v)
            if v < r.piso:
                continue
            qt = _num(res, r.campo_qt) if r.campo_qt else None
            medida = brl(v) if r.dinheiro else f"{int(v)}"
            grav = "alta" if (r.dinheiro and v >= 500_000) or \
                             r.especie in ("vermelho", "risco") else "media"
            # A chave arredonda ao milhar: enquanto o número não se mexe de
            # verdade, é o mesmo achado, e não sai duas vezes.
            chave = f"{e['agente_id']}:{r.campo}:{int(v // 1000)}"
            criados += _pendura(
                e, nome, r.especie, grav, f"{r.titulo} — {medida}",
                resumo, chave, valor=v if r.dinheiro else None,
                qt=int(qt) if qt is not None else (None if r.dinheiro else int(v)))

    bd.executar(
        "INSERT INTO marcador(chave, valor, atualizado_em) VALUES(?,?,?) "
        "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor, "
        "atualizado_em=excluded.atualizado_em",
        ("aviso:ultima_entrega", str(novas[-1]["id"]), bd.agora()))
    if criados:
        log.info("avisos pendurados na fila: %s", criados)
    return criados
