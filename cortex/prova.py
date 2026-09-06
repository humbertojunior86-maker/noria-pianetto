"""Mesa de prova — onde a regra volta a mandar.

A hipótese que o córtex levantou só existe de verdade depois que um SELECT
determinístico roda no ATUA, em transação somente leitura, e devolve linhas.
Nenhum número desta etapa foi escrito por modelo: todos vêm do cursor.
"""
from __future__ import annotations

import decimal
import json
from datetime import date, datetime

from ferramentas import atua
from nucleo import bd
from . import guarda


def _serial(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()[:19]
    return v


def rodar_sql(sql: str, respeitar_janela: bool = True) -> dict:
    """Confere o SQL, roda somente leitura e devolve linhas + carimbo."""
    limpo = guarda.conferir(sql, respeitar_janela)
    conn = atua._conn()
    try:
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = 0")
            cur.execute(limpo)
            cols = [d[0] for d in cur.description]
            linhas = [{c: _serial(v) for c, v in zip(cols, r)}
                      for r in cur.fetchmany(guarda.LIMITE_MAX)]
        conn.rollback()
    finally:
        conn.close()
    return {"sql": limpo, "colunas": cols, "linhas": linhas,
            "consultada_em": bd.agora()}


def executar_proposta(cp_id: int, respeitar_janela: bool = True) -> dict:
    """Roda uma consulta_proposta e grava o resultado ou o motivo da recusa."""
    cp = bd.linha("SELECT * FROM consulta_proposta WHERE id=?", (cp_id,))
    if not cp:
        return {"ok": False, "erro": f"consulta {cp_id} não existe"}
    try:
        r = rodar_sql(cp["sql"], respeitar_janela)
    except guarda.Recusa as e:
        bd.executar("UPDATE consulta_proposta SET recusa=?, rodou_em=? WHERE id=?",
                    (str(e), bd.agora(), cp_id))
        return {"ok": False, "recusa": str(e)}
    except Exception as e:
        bd.executar("UPDATE consulta_proposta SET erro=?, rodou_em=? WHERE id=?",
                    (str(e)[:400], bd.agora(), cp_id))
        return {"ok": False, "erro": str(e)[:400]}

    bd.executar(
        "UPDATE consulta_proposta SET sql=?, resultado_json=?, linhas=?, "
        "erro=NULL, recusa=NULL, rodou_em=? WHERE id=?",
        (r["sql"], json.dumps(r["linhas"][:200], ensure_ascii=False),
         len(r["linhas"]), r["consultada_em"], cp_id))
    return {"ok": True, "linhas": r["linhas"], "sql": r["sql"],
            "consultada_em": r["consultada_em"]}
