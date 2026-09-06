"""O mandato da NÓRIA: caçar margem, dentro da coleira.

Antes disto ela procurava "algo estranho". Um cérebro corporativo sem direção
acha muita coisa curiosa e pouca coisa que paga a conta. O CEO deu a direção:
**margem**. Este arquivo é o texto que ela lê antes de pensar — e é também onde
está escrito, na cara dela, o que ela não pode fazer.

Aqui moram três coisas:
  1. o mandato (a direção e os limites, em português);
  2. a árvore da margem (por onde o dinheiro vaza numa transportadora);
  3. a proposta de vigias — ela olhando o dia e dizendo o que merece virar
     vigilância permanente.
"""
from __future__ import annotations

import json
import logging

from nucleo import bd
from nucleo import vigia as nv
from . import cliente, higiene

log = logging.getLogger("noria.mandato")
EMPRESA = 1

# ------------------------------------------------------------------ mandato
MANDATO = """MANDATO DA CASA — leia antes de qualquer coisa.

Sua missão não é achar curiosidade: é achar MARGEM. A Pianetto fatura muito e
sobra pouco. Toda pergunta sua deve poder terminar em uma frase do tipo "se a
casa fizer X, sobra mais dinheiro no fim do mês".

Onde a margem vaza numa transportadora rodoviária de cargas:
- PREÇO: cliente ou rota faturando abaixo do custo por quilômetro; tabela sem
  reajuste enquanto o custo subiu; frete de retorno vazio ou mal precificado.
- CUSTO: veículo próprio com custo por quilômetro acima da média da frota;
  terceiro custando mais que rodar com frota própria na mesma rota;
  manutenção concentrada em poucas placas.
- OCIOSIDADE: veículo que consome sem faturar; quilômetro rodado vazio; carga
  que volta pela metade.
- VAZAMENTO: CT-e autorizado sem título gerado; frete abaixo do mínimo legal;
  desconto fora de política; refaturamento; título pago que segue cobrado.
- MIX: filial, produto ou tipo de veículo com contribuição estruturalmente
  menor puxando a média para baixo.

Regras que não se negociam:
- contribuição NÃO é lucro. Nunca apresente uma como a outra.
- todo número tem porta, grão e data de corte. Sem isso ele não vale.
- quando duas portas discordam, ache a DEFINIÇÃO que difere. Não escolha a
  maior.

O QUE VOCÊ NÃO PODE, EM NENHUMA HIPÓTESE:
- alterar o código da NÓRIA, qualquer arquivo, serviço ou configuração. O
  motor não é seu território. Você escreve perguntas e consultas, não sistema.
- escrever no ATUA. Sua conexão é somente leitura, no nível do banco.
- dar voz a si mesma: o vigia que você criar nasce mudo e só o CEO o promove.
- mandar informação para fora da casa sem aprovação de gente.
"""

# --------------------------------------------------------- proposta de vigia
SISTEMA_VIGIA = MANDATO + """
Agora um poder novo: você pode CRIAR AGENTES.

Um vigia é um agente permanente e simples: uma pergunta, um SELECT que a
responde todo dia, e um limiar de dinheiro a partir do qual aquilo vira achado.
Ele existe para o que precisa ser olhado SEMPRE, não para a curiosidade de
hoje — curiosidade de hoje já é hipótese, e hipótese você levanta no faro.

Crie vigia quando:
- o ponto é recorrente (vai vazar de novo mês que vem);
- dá para medir com um SELECT só, sem interpretação;
- o dinheiro envolvido justifica alguém olhar todo dia.

Não crie vigia quando:
- a pergunta é de uma vez só (isso é hipótese);
- o número já aparece na Sala do CEO;
- você não sabe declarar o limiar.

Regras do SQL do vigia:
- SÓ estas tabelas existem para você. Qualquer outra é recusada na porta e o
  vigia nem chega a nascer: {TABELAS}.
- as colunas que você já conhece: titulo(id_tipo 1 receber / 2 pagar, vl_total,
  vl_pago, dt_vencimento, dt_quitacao, cd_movimento, cd_pessoa);
  titulo_pagamento(cd_titulo, dt_pagamento, vl_pago); movimento(cd_movimento,
  vl_movimento, dt_movimento); ctrc(dt_emissao, vl_total, vl_peso, ds_serie,
  nr_ctrc, cd_pessoa_tomador, cd_pessoa_pagador, cd_pessoa_embarque,
  cd_pessoa_filial, id_proprietario_veiculo 1 própria / 2 agregado /
  3 terceiro, cd_movimento NULL = CT-e sem título); pessoa(cd_pessoa,
  nm_pessoa, nm_fantasia); ctrc_produto -> produto_transportado(nm_produto).
  NÃO existe dt_baixa nem dt_emissao em titulo, nem cd_autorizacao_sefaz em
  ctrc, nem cd_pessoa_cliente.
- um único SELECT (pode usar WITH), sempre com LIMIT;
- roda sozinho, sem parâmetro, usando current_date;
- devolva UMA coluna de rótulo (quem é o culpado: placa, cliente, rota, filial)
  e UMA coluna numérica de valor (o dinheiro em jogo);
- só as tabelas do ATUA que você já conhece.

Formato da resposta, JSON puro e nada mais:
{"vigias":[{"nome":"até 60 caracteres, direto",
  "area":"comercial|financeiro|frota|controladoria|fiscal|operacao",
  "pergunta":"a frase que ele responde todo dia",
  "motivo":"por que a casa precisa disso olhado sempre",
  "sql":"SELECT ... LIMIT n",
  "campo_rotulo":"nome da coluna de rótulo",
  "campo_valor":"nome da coluna numérica",
  "limiar": 250000,
  "especie":"margem|dinheiro_parado|prejuizo|custo|inadimplencia"}]}

Se hoje nada merece virar vigia, devolva {"vigias":[]}. Silêncio declarado vale
mais que vigia inventado para parecer produtivo.
"""


def _sistema_vigia() -> str:
    """Monta o texto com a lista branca REAL da guarda.

    Antes esta lista era um parágrafo escrito à mão e ela propunha tabela que
    não existe — dois vigias morreram na porta no primeiro teste. Agora o
    prompt lê a mesma constante que recusa: uma fonte só, sem desencontro.
    """
    from . import guarda
    return SISTEMA_VIGIA.replace(
        "{TABELAS}", ", ".join(sorted(guarda.TABELAS_OK)))


def _catalogo(empresa_id: int) -> list[dict]:
    """O que já é vigiado. Sem isto ela recria o mesmo vigia toda semana."""
    return [dict(v) for v in bd.linhas(
        "SELECT id, nome, pergunta, estado, achados FROM vigia WHERE "
        "empresa_id=? AND estado IN ('observacao','ativo','suspenso') "
        "ORDER BY id", (empresa_id,))]


def _material(empresa_id: int) -> dict:
    """O que ela olha para decidir: achados recentes e o que já foi provado."""
    m = {"data": bd.agora()[:10], "ja_vigiado": _catalogo(empresa_id),
         "achados_recentes": [], "hipoteses_confirmadas": []}
    for a in bd.linhas(
            "SELECT titulo, texto, especie, valor FROM aviso WHERE empresa_id=? "
            "ORDER BY id DESC LIMIT 20", (empresa_id,)):
        m["achados_recentes"].append(dict(a))
    for h in bd.linhas(
            "SELECT pergunta, leitura FROM hipotese WHERE empresa_id=? AND "
            "estado='confirmada' ORDER BY id DESC LIMIT 10", (empresa_id,)):
        m["hipoteses_confirmadas"].append(dict(h))
    return m


def propor_vigias(empresa_id: int = EMPRESA, teto: int = 2) -> dict:
    """A NÓRIA olha o dia e cria os vigias que faltam — no máximo dois por vez.

    Dois é de propósito. Um cérebro que cria oito agentes num dia não está
    vigiando, está enchendo tela. Crescimento devagar é o que permite conferir
    cada um enquanto ele ainda está em observação.
    """
    vivos = bd.linha("SELECT COUNT(*) AS n FROM vigia WHERE empresa_id=? AND "
                     "estado IN ('observacao','ativo')", (empresa_id,))["n"]
    if vivos >= nv.TETO_VIVOS:
        return {"criados": [], "recusados": [],
                "motivo": f"teto de {nv.TETO_VIVOS} vigias vivos já alcançado"}

    material = higiene.limpar_estrutura(_material(empresa_id))
    pedido = ("Este é o material da casa hoje. Proponha no máximo "
              f"{teto} vigias novos, ou nenhum.\n\n"
              + json.dumps(material, ensure_ascii=False, default=str)[:40000])

    resposta = cliente.pensar_json("vigia", _sistema_vigia(), pedido)
    criados, recusados = [], []
    for v in (resposta.get("vigias") or [])[:teto]:
        nome = (v.get("nome") or "").strip()
        sql = (v.get("sql") or "").strip()
        if not nome or not sql:
            recusados.append({"nome": nome, "porque": "veio sem nome ou sem SQL"})
            continue
        try:
            r = nv.criar(
                empresa_id, nome=nome, area=(v.get("area") or "controladoria"),
                pergunta=(v.get("pergunta") or nome),
                motivo=(v.get("motivo") or "proposto pelo pensamento"),
                consulta=sql, campo_valor=v.get("campo_valor"),
                campo_rotulo=v.get("campo_rotulo"),
                limiar=float(v.get("limiar") or 0),
                especie=(v.get("especie") or "margem"),
                criado_por="pensamento")
            criados.append({"id": r["id"], "nome": nome})
        except nv.Recusado as e:
            recusados.append({"nome": nome, "porque": str(e)})
        except Exception as e:  # noqa: BLE001
            log.exception("falha ao criar vigia")
            recusados.append({"nome": nome, "porque": str(e)[:200]})
    return {"criados": criados, "recusados": recusados}


# ------------------------------------------------------------- entregáveis
def entregavel_do_dia(empresa_id: int = EMPRESA) -> dict:
    """Informação nova que ninguém pediu, montada com número do banco.

    O texto é dela; os números são do cursor. Nenhum valor aqui é escrito por
    modelo: cada linha vem da execução do vigia, e é por isso que este
    documento pode ser publicado sem passar por revisão de gente.
    """
    achados = bd.linhas(
        "SELECT v.id, v.nome, v.pergunta, v.area, v.especie, e.valor, "
        "e.linhas, e.amostra, e.quando FROM vigia_execucao e "
        "JOIN vigia v ON v.id = e.vigia_id WHERE e.achou = 1 AND "
        "e.quando >= datetime('now','-1 day') ORDER BY e.valor DESC LIMIT 8")
    if not achados:
        return {"criado": False, "motivo": "nenhum vigia achou nada nas 24h"}

    secoes = []
    for a in achados:
        try:
            linhas = json.loads(a["amostra"] or "[]")
        except (TypeError, ValueError):
            linhas = []
        secoes.append({
            "titulo": a["nome"],
            "texto": f"{a['pergunta']} Apurado em {a['quando'][:16]} pelo vigia "
                     f"{a['id']} ({a['area']}). {a['linhas']} linha(s).",
            "valor": a["valor"], "linhas": linhas,
        })

    total = sum(float(s["valor"] or 0) for s in secoes)
    eid = bd.inserir("entregavel", {
        "empresa_id": empresa_id,
        "titulo": f"Margem sob vigilância — {bd.agora()[:10]}",
        "motivo": "Montado pela NÓRIA sem ninguém pedir, a partir do que os "
                  "vigias acharam nas últimas 24 horas.",
        "foco": "margem", "origem": "vigia:varios",
        "secoes": json.dumps(secoes, ensure_ascii=False, default=str),
        "destino": "interno", "estado": "publicado", "criado_em": bd.agora(),
    })
    bd.evento(empresa_id, "entregavel.criado",
              f"A NÓRIA publicou o entregável {eid} sem ninguém pedir: "
              f"{len(secoes)} frente(s) de margem, {total:.2f} em jogo.",
              ator="pensamento", dados={"entregavel_id": eid})
    return {"criado": True, "id": eid, "secoes": len(secoes), "total": total}
