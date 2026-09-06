"""Faro — a NÓRIA passa a perguntar, não só a responder.

Recebe só os RESULTADOS do dia (nunca o banco cru), pede à NÓRIA até cinco
perguntas novas, cada uma com motivo, aposta e o SELECT que a testa. Toda
consulta passa pela guarda antes de existir. Nada é confirmado aqui: quem
confirma é a mesa de prova.
"""
from __future__ import annotations

import hashlib
import json
import re

from ferramentas import base as fb
from nucleo import bd
from . import cliente, guarda, higiene

EMPRESA = 1

SISTEMA = """Você é a NÓRIA, o cérebro corporativo da
Pianetto Transportes, uma transportadora rodoviária de cargas brasileira.

O que você é: o faro da casa. Você olha os resultados do dia e levanta
perguntas que os limiares fixos dos agentes não cobrem.

O que você NÃO é: fonte de número. Você nunca inventa valor, quantidade ou
data. Quem soma é o SQL. Se você escrever um número que não veio da mesa, o
conferente bloqueia sua resposta inteira.

Como pensar bem aqui:
- desconfie de definição, não de aritmética: quando duas fontes discordam, o
  problema quase sempre é o que cada uma está chamando de "em aberto",
  "receita" ou "margem";
- procure dinheiro parado, dinheiro cobrado duas vezes, documento que existe
  num sistema e não no outro, cliente que sumiu, veículo que consome sem
  faturar, título pago que continua sendo cobrado;
- prefira a pergunta que, se confirmada, muda uma decisão do CEO amanhã;
- não repita pergunta óbvia nem pergunta que a mesa já responde.

Sobre o banco (PostgreSQL, somente leitura, schema public):
- titulo: id_tipo 1 = a receber, 2 = a pagar; vl_total é o valor cheio,
  vl_pago o que já foi baixado; saldo real = vl_total - vl_pago;
  dt_quitacao, dt_vencimento, cd_movimento (a fatura), cd_pessoa (o cliente).
  NÃO existe dt_baixa nem dt_emissao em titulo.
- titulo_pagamento: cd_titulo, dt_pagamento, vl_pago, cd_portador. Em JOIN com
  titulo, qualifique sempre (tp.vl_pago), porque a coluna existe nas duas.
- movimento: a fatura (cd_movimento, vl_movimento, dt_movimento).
- ctrc: o conhecimento de transporte. dt_emissao, vl_total, ds_serie, nr_ctrc,
  cd_pessoa_tomador, cd_pessoa_pagador, cd_pessoa_embarque, cd_pessoa_filial,
  id_proprietario_veiculo (1 própria, 2 agregado, 3 terceiro),
  cd_movimento IS NULL significa CT-e sem título gerado, vl_peso em kg.
- pessoa: cd_pessoa, nm_pessoa, nm_fantasia.
- ctrc_produto -> produto_transportado.nm_produto: o que foi carregado.
- filiais em cd_pessoa_filial: 2 matriz, 1792 SP, 1715 MG, 6691 MS, 1538 PR,
  14171 TO, 14376 SC.

Regras duras do SQL que você propõe:
- um único SELECT (pode usar WITH), sempre com LIMIT;
- só as tabelas citadas acima e suas irmãs de cadastro;
- nada de INSERT, UPDATE, DELETE, DDL ou função de sistema;
- escreva SQL que roda sozinho, sem parâmetro, usando current_date;
- a consulta principal e a contraprova têm de chegar ao mesmo número por
  caminhos diferentes (outra tabela, outro grão ou outro sentido da conta).

Formato da resposta, JSON puro:
{"hipoteses":[{"pergunta":"uma frase em português",
  "motivo":"por que isso merece ser perguntado hoje",
  "aposta":"o que você espera encontrar, sem número",
  "grao":"titulo|duplicata|ctrc|veiculo|cliente|fatura",
  "sql":"SELECT ... LIMIT n",
  "sql_contraprova":"SELECT ... LIMIT n"}]}
"""


def _mesa(empresa_id: int = EMPRESA) -> dict:
    """Junta o que a casa já sabe hoje. Só resultado de agente e de consulta."""
    mesa: dict = {"data": bd.agora()[:10], "indicadores": {}, "avisos": [],
                  "hipoteses_mortas": [], "aprendizados": []}

    for op in ("ceo.pulso", "ceo.carteira", "ceo.concentracao",
               "ceo.serie_mensal", "titulo.vencidos"):
        r = fb.rodar("atua", op, {}, empresa_id=empresa_id)
        if r.ok:
            linhas = (r.dados or {}).get("linhas", [])
            mesa["indicadores"][op] = linhas[:25]
        else:
            mesa["indicadores"][op] = {"falhou": r.erro}

    for a in bd.linhas(
            "SELECT titulo, texto, especie, gravidade, valor, quantidade "
            "FROM aviso WHERE empresa_id=? ORDER BY id DESC LIMIT 25",
            (empresa_id,)):
        mesa["avisos"].append(dict(a))

    for h in bd.linhas(
            "SELECT pergunta, estado FROM hipotese WHERE empresa_id=? "
            "AND estado IN ('derrubada','inconclusiva','rejeitada') "
            "ORDER BY id DESC LIMIT 40", (empresa_id,)):
        mesa["hipoteses_mortas"].append(h["pergunta"])

    for a in bd.linhas(
            "SELECT enunciado FROM aprendizado WHERE empresa_id=? "
            "ORDER BY id DESC LIMIT 20", (empresa_id,)):
        mesa["aprendizados"].append(a["enunciado"][:400])

    return mesa


def _chave(pergunta: str) -> str:
    t = re.sub(r"[^a-z0-9 ]", "", (pergunta or "").lower())
    t = " ".join(sorted(set(t.split())))
    return hashlib.sha256(t.encode("utf-8")).hexdigest()[:20]


def _ja_perguntada(chave: str, dias: int) -> bool:
    r = bd.linha(
        "SELECT id FROM hipotese WHERE chave=? AND criada_em >= "
        "datetime('now', ?)", (chave, f"-{dias} days"))
    return bool(r)


def levantar(empresa_id: int = EMPRESA, respeitar_janela: bool = True) -> dict:
    """Roda o faro do dia. Devolve o que entrou e o que foi barrado."""
    cfg = cliente.config()
    mesa = higiene.limpar_estrutura(_mesa(empresa_id))
    pedido = (
        "Estes são os resultados da NÓRIA hoje. Levante no máximo "
        f"{cfg['hipoteses_por_dia']} perguntas novas.\n\n"
        + json.dumps(mesa, ensure_ascii=False, default=str)[:60000])

    resposta = cliente.pensar_json("hipotese", SISTEMA, pedido)
    saida = {"levantadas": [], "barradas": [], "repetidas": 0}

    for h in (resposta.get("hipoteses") or [])[:cfg["hipoteses_por_dia"]]:
        pergunta = (h.get("pergunta") or "").strip()
        if not pergunta:
            continue
        ch = _chave(pergunta)
        if _ja_perguntada(ch, cfg["dedupe_dias"]):
            saida["repetidas"] += 1
            continue

        consultas, barrada = [], None
        for papel, campo in (("principal", "sql"), ("contraprova", "sql_contraprova")):
            sql = (h.get(campo) or "").strip()
            if not sql:
                continue
            try:
                consultas.append((papel, guarda.conferir(sql, respeitar_janela)))
            except guarda.Recusa as e:
                if papel == "principal":
                    barrada = str(e)
                    break
        if barrada or not consultas:
            saida["barradas"].append(
                {"pergunta": pergunta, "motivo": barrada or "sem SQL utilizável"})
            continue

        hid = bd.inserir("hipotese", {
            "empresa_id": empresa_id, "pergunta": pergunta,
            "motivo": (h.get("motivo") or "").strip()[:1000],
            "origem": "faro do ciclo diário",
            "aposta": (h.get("aposta") or "").strip()[:600],
            "estado": "levantada", "chave": ch, "criada_em": bd.agora()})
        for papel, sql in consultas:
            bd.inserir("consulta_proposta", {
                "hipotese_id": hid, "porta": "atua", "sql": sql,
                "grao": (h.get("grao") or "indefinido")[:40], "papel": papel,
                "criada_em": bd.agora()})
        bd.inserir("raciocinio", {
            "hipotese_id": hid, "passo": 1,
            "texto": "faro: " + (h.get("motivo") or "")[:800],
            "criado_em": bd.agora()})
        saida["levantadas"].append({"id": hid, "pergunta": pergunta})

    return saida
