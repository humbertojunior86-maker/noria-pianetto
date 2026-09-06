"""Vigias — os agentes que a NÓRIA cria sozinha.

Um agente da NÓRIA sempre foi código Python. Se ela pudesse criar agentes desse
jeito, estaria escrevendo código em produção — exatamente o que foi proibido.
Então separamos as duas camadas: este arquivo é o MOTOR, fixo e revisado por
gente; o vigia é uma linha na tabela `vigia`, escrita por ela.

Ela decide a pergunta, a consulta e o limiar. Ela nunca decide como o motor
roda, o que ele pode ler nem para quem ele grita. Vigia errado some apagando um
registro, não fazendo um deploy.

Os freios, todos aqui e todos por escrito:
  - teto de vigias vivos ao mesmo tempo;
  - o SELECT passa pela mesma guarda do pensamento (só leitura, tabela na lista
    branca, LIMIT obrigatório, janela 8h-11h proibida);
  - nasce MUDO: em observação o achado vai para o painel e não toca o sino;
  - três falhas seguidas suspendem sozinho;
  - trinta dias sem achar nada aposentam sozinho;
  - quem dá voz a um vigia é o CEO, nunca ela.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from nucleo import bd
from nucleo.formato import brl

log = logging.getLogger("noria.vigia")

# ------------------------------------------------------------------ limites
# Doze é o quanto um CEO consegue olhar numa tela sem desistir. Acima disso a
# vigilância vira lista e lista ninguém lê.
TETO_VIVOS = 12
FALHAS_PARA_SUSPENDER = 3
DIAS_SEM_ACHADO_PARA_APOSENTAR = 30
ESTADOS_VIVOS = ("observacao", "ativo")


class Recusado(Exception):
    """A NÓRIA pediu algo que o motor não concede. O motivo vai no texto."""


# ------------------------------------------------------------------- criação
def criar(empresa_id: int, nome: str, area: str, pergunta: str, motivo: str,
          consulta: str, campo_valor: str | None = None,
          campo_rotulo: str | None = None, limiar: float = 0.0,
          especie: str = "margem", gravidade: str = "alta",
          foco: str = "margem", criado_por: str = "pensamento",
          hipotese_id: int | None = None) -> dict:
    """Cria um vigia novo — já nascendo em observação, isto é, mudo.

    A consulta é conferida ANTES de virar registro. Vigia com SQL proibido não
    chega a existir: é melhor recusar na porta do que descobrir na hora em que
    ele roda sozinho, de madrugada, sem ninguém olhando.
    """
    from pensamento import guarda

    vivos = bd.linha(
        "SELECT COUNT(*) AS n FROM vigia WHERE empresa_id=? AND estado IN "
        "('observacao','ativo')", (empresa_id,))["n"]
    if vivos >= TETO_VIVOS:
        raise Recusado(
            f"já existem {vivos} vigias vivos e o teto é {TETO_VIVOS}. "
            "Aposente um antes de criar outro.")

    if bd.linha("SELECT id FROM vigia WHERE empresa_id=? AND pergunta=? AND "
                "estado IN ('observacao','ativo')", (empresa_id, pergunta)):
        raise Recusado("já existe um vigia vivo com essa mesma pergunta")

    try:
        limpa = guarda.conferir(consulta, respeitar_janela=False)
    except Exception as e:  # guarda.Recusa e afins
        raise Recusado(f"a consulta não passou na guarda: {e}") from e

    vid = bd.inserir("vigia", {
        "empresa_id": empresa_id, "nome": nome.strip()[:80],
        "apelido": _proximo_nome(empresa_id), "area": area,
        "foco": foco, "pergunta": pergunta.strip(), "motivo": motivo.strip(),
        "consulta": limpa, "campo_valor": campo_valor,
        "campo_rotulo": campo_rotulo, "limiar": float(limiar or 0),
        "especie": especie, "gravidade": gravidade, "cadencia": "diaria",
        "estado": "observacao", "criado_por": criado_por,
        "hipotese_id": hipotese_id, "criada_em": bd.agora(),
    })
    bd.evento(empresa_id, "vigia.criado",
              f"A NÓRIA criou o vigia {vid} sem ninguém pedir: {nome}. "
              f"Nasce em observação — não toca o sino até o CEO aprovar.",
              ator="pensamento", dados={"vigia_id": vid, "pergunta": pergunta})
    return {"id": vid, "estado": "observacao"}


# -------------------------------------------------------------------- batismo
# Vigia nasce com dois nomes. O primeiro é a tarefa — "Inadimplência +30 dias
# acima de R$ 1,5 MM" — que serve para saber o que ele faz. O segundo é o nome
# dele, curto, do mesmo feitio dos agentes de código. Sem isso, o anel da
# abertura vira uma parede de frases e a equipe deixa de parecer uma equipe.
# Ninguém chama o colega pelo cargo escrito por extenso.
NOMES = [
    "Hugo", "Elis", "Bento", "Laís", "Ivo", "Nara", "Célia", "Tales",
    "Selma", "Duda", "Décio", "Alba", "Noel", "Rita", "Lino", "Zita",
    "Ciro", "Malu", "Baltazar", "Neusa", "Elias", "Wanda",
]


def _proximo_nome(empresa_id: int) -> str:
    """Escolhe o primeiro nome livre. Livre de verdade: não repete nome de
    agente de código nem de vigia já batizado, vivo ou aposentado — dois
    'Hugo' na mesma casa confundem quem lê o alerta às sete da manhã."""
    usados = set()
    for r in bd.linhas("SELECT apelido FROM vigia WHERE apelido IS NOT NULL"):
        usados.add((r["apelido"] or "").strip().lower())
    try:
        from agentes import registro as ar
        for d in ar.todos():
            usados.add((d.nome or "").strip().lower())
    except Exception:  # noqa: BLE001 — registro indisponível não impede batismo
        pass
    for n in NOMES:
        if n.lower() not in usados:
            return n
    # Lista esgotada: numera em vez de repetir. Feio, mas honesto.
    return f"Vigia {bd.linha('SELECT COUNT(*) AS n FROM vigia')['n'] + 1}"


def batizar_pendentes(empresa_id: int) -> int:
    """Dá nome a quem nasceu antes desta regra existir. Idempotente."""
    n = 0
    for v in bd.linhas("SELECT id FROM vigia WHERE empresa_id=? AND "
                       "(apelido IS NULL OR apelido='') ORDER BY id",
                       (empresa_id,)):
        bd.atualizar("vigia", v["id"], {"apelido": _proximo_nome(empresa_id)})
        n += 1
    return n


# ------------------------------------------------------------------ execução
def _valor_e_linhas(linhas: list[dict], campo: str | None) -> tuple[float, int]:
    """Soma o dinheiro do achado. Sem campo declarado, o valor é a contagem."""
    if not campo:
        return float(len(linhas)), len(linhas)
    total = 0.0
    for r in linhas:
        try:
            total += float(r.get(campo) or 0)
        except (TypeError, ValueError):
            continue
    return total, len(linhas)


def rodar(vid: int, respeitar_janela: bool = True) -> dict:
    """Roda um vigia. Nenhuma falha dele pode derrubar os outros."""
    from pensamento import prova

    v = bd.linha("SELECT * FROM vigia WHERE id=?", (vid,))
    if not v:
        return {"ok": False, "erro": f"vigia {vid} não existe"}
    if v["estado"] not in ESTADOS_VIVOS:
        return {"ok": False, "erro": f"vigia {vid} está {v['estado']}"}

    agora = bd.agora()
    try:
        r = prova.rodar_sql(v["consulta"], respeitar_janela)
    except Exception as e:  # noqa: BLE001
        erro = str(e)[:400]
        seguidas = int(v["falhas_seguidas"] or 0) + 1
        estado = "suspenso" if seguidas >= FALHAS_PARA_SUSPENDER else v["estado"]
        bd.executar(
            "UPDATE vigia SET execucoes=execucoes+1, falhas=falhas+1, "
            "falhas_seguidas=?, estado=?, ultima_execucao=? WHERE id=?",
            (seguidas, estado, agora, vid))
        bd.inserir("vigia_execucao", {"vigia_id": vid, "quando": agora,
                                      "ok": 0, "erro": erro})
        if estado == "suspenso":
            bd.evento(v["empresa_id"], "vigia.suspenso",
                      f"O vigia {vid} ({v['nome']}) falhou {seguidas} vezes "
                      f"seguidas e foi suspenso sozinho. Último erro: {erro}",
                      ator="nucleo", dados={"vigia_id": vid})
        return {"ok": False, "erro": erro, "estado": estado}

    linhas = r["linhas"]
    valor, qt = _valor_e_linhas(linhas, v["campo_valor"])
    achou = valor >= float(v["limiar"] or 0) and qt > 0

    ex_id = bd.inserir("vigia_execucao", {
        "vigia_id": vid, "quando": agora, "ok": 1, "linhas": qt,
        "valor": round(valor, 2), "achou": 1 if achou else 0,
        "amostra": json.dumps(linhas[:5], ensure_ascii=False, default=str),
    })
    bd.executar(
        "UPDATE vigia SET execucoes=execucoes+1, falhas_seguidas=0, "
        "ultima_execucao=?, achados=achados+?, ultimo_achado=? WHERE id=?",
        (agora, 1 if achou else 0, agora if achou else v["ultimo_achado"], vid))

    aviso_id = None
    if achou:
        aviso_id = _pendurar_achado(v, valor, qt, linhas, ex_id)
    return {"ok": True, "linhas": qt, "valor": valor, "achou": achou,
            "aviso_id": aviso_id}


def _pendurar_achado(v: dict, valor: float, qt: int, linhas: list[dict],
                     ex_id: int) -> int | None:
    """Grava o achado na fila de avisos.

    Em observação a gravidade cai para 'media' de propósito: o corte do alerta
    crítico só olha 'alta' e 'critica', então o vigia novo aparece no painel sem
    interromper o dia de ninguém. É a coleira curta em uma linha de código.
    """
    # Duas travas, não uma. A gravidade cai para 'media' E a espécie vira
    # 'observacao', que não está em nenhuma lista do corte crítico. Só baixar a
    # gravidade não bastava: o sino também toca por espécie e valor, e no
    # primeiro teste um vigia recém-nascido, ainda sem voz, chegou a aparecer
    # em /api/criticos com R$ 1.773.987,54. Vigia sem aprovação não interrompe
    # o dia de ninguém, por nenhum caminho.
    ativo = v["estado"] == "ativo"
    grav = v["gravidade"] if ativo else "media"
    especie = v["especie"] if ativo else "observacao"
    dinheiro = bool(v["campo_valor"])
    titulo = (f"{v['nome']} — {brl(valor)}" if dinheiro
              else f"{v['nome']} — {qt} caso(s)")
    rot = v["campo_rotulo"]
    exemplo = ""
    if rot and linhas:
        nomes = [str(x.get(rot)) for x in linhas[:3] if x.get(rot) is not None]
        if nomes:
            exemplo = " Primeiros: " + ", ".join(nomes) + "."
    texto = (f"{v['pergunta']} {qt} linha(s) no corte de "
             f"{brl(v['limiar']) if dinheiro else int(v['limiar'])}.{exemplo}")
    chave = f"vigia:{v['id']}:{round(valor)}"
    if bd.linha("SELECT id FROM aviso WHERE chave=?", (chave,)):
        return None
    aid = bd.inserir("aviso", {
        "empresa_id": v["empresa_id"], "agente_id": f"vigia.{v['id']}",
        "agente_nome": v["nome"], "especie": especie, "gravidade": grav,
        "titulo": titulo, "texto": texto, "valor": round(valor, 2) if dinheiro else None,
        "quantidade": qt, "chave": chave, "estado": "pendente",
        "criado_em": bd.agora(),
    })
    bd.executar("UPDATE vigia_execucao SET aviso_id=? WHERE id=?", (aid, ex_id))
    bd.evento(v["empresa_id"], "vigia.achado",
              f"O vigia {v['id']} ({v['nome']}) achou {titulo}.",
              ator=f"vigia:{v['id']}", dados={"vigia_id": v["id"], "valor": valor})
    return aid


# ------------------------------------------------------------------ rodada
def _aposentar_ociosos(empresa_id: int) -> list[int]:
    """Vigia que não acha nada há trinta dias vira ruído. Ela mesma desliga."""
    corte = (datetime.now().astimezone()
             - timedelta(days=DIAS_SEM_ACHADO_PARA_APOSENTAR)).isoformat()
    fora = []
    for v in bd.linhas(
        "SELECT id, nome, criada_em, ultimo_achado FROM vigia WHERE empresa_id=? "
        "AND estado IN ('observacao','ativo') AND execucoes >= 10", (empresa_id,)):
        ref = v["ultimo_achado"] or v["criada_em"]
        if ref and ref < corte:
            bd.executar("UPDATE vigia SET estado='aposentado' WHERE id=?", (v["id"],))
            bd.evento(empresa_id, "vigia.aposentado",
                      f"O vigia {v['id']} ({v['nome']}) passou "
                      f"{DIAS_SEM_ACHADO_PARA_APOSENTAR} dias sem achar nada e "
                      "foi aposentado sozinho.", ator="nucleo")
            fora.append(v["id"])
    return fora


def rodada(empresa_id: int = 1, respeitar_janela: bool = True) -> dict:
    """Uma passada por todos os vigias vivos que ainda não rodaram hoje."""
    hoje = bd.agora()[:10]
    feitos, achados = [], 0
    for v in bd.linhas(
        "SELECT id FROM vigia WHERE empresa_id=? AND estado IN "
        "('observacao','ativo') ORDER BY id", (empresa_id,)):
        atual = bd.linha("SELECT ultima_execucao FROM vigia WHERE id=?", (v["id"],))
        if (atual["ultima_execucao"] or "")[:10] == hoje:
            continue
        try:
            r = rodar(v["id"], respeitar_janela)
        except Exception as e:  # noqa: BLE001
            log.exception("vigia %s explodiu", v["id"])
            r = {"ok": False, "erro": str(e)[:200]}
        feitos.append({"vigia": v["id"], **r})
        achados += 1 if r.get("achou") else 0
    return {"rodou": len(feitos), "achados": achados,
            "aposentados": _aposentar_ociosos(empresa_id), "detalhe": feitos}


# ------------------------------------------------------------------ governo
def aprovar(vid: int, quem: str) -> dict:
    """Dar voz a um vigia é ato humano. A NÓRIA não promove a si mesma."""
    v = bd.linha("SELECT * FROM vigia WHERE id=?", (vid,))
    if not v:
        return {"ok": False, "erro": "vigia não existe"}
    bd.executar("UPDATE vigia SET estado='ativo', aprovado_em=?, aprovado_por=? "
                "WHERE id=?", (bd.agora(), quem, vid))
    bd.evento(v["empresa_id"], "vigia.aprovado",
              f"{quem} aprovou o vigia {vid} ({v['nome']}). A partir de agora "
              "ele pode tocar o alerta crítico.", ator=f"usuario:{quem}")
    return {"ok": True, "estado": "ativo"}


def desligar(vid: int, quem: str, motivo: str = "") -> dict:
    v = bd.linha("SELECT * FROM vigia WHERE id=?", (vid,))
    if not v:
        return {"ok": False, "erro": "vigia não existe"}
    bd.executar("UPDATE vigia SET estado='aposentado' WHERE id=?", (vid,))
    bd.evento(v["empresa_id"], "vigia.desligado",
              f"{quem} desligou o vigia {vid} ({v['nome']}). {motivo}".strip(),
              ator=f"usuario:{quem}")
    return {"ok": True, "estado": "aposentado"}
