"""Linha de comando da NÓRIA.

    python -m pensamento.rodar estado      -> chave, gasto do dia e do mês
    python -m pensamento.rodar preparar    -> cria as tabelas da NÓRIA
    python -m pensamento.rodar faro        -> levanta as hipóteses do dia
    python -m pensamento.rodar provar      -> prova as hipóteses pendentes
    python -m pensamento.rodar ciclo       -> faro + prova, na sequência
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from nucleo import bd
from . import cliente


def preparar() -> None:
    sql = (Path(__file__).resolve().parent / "esquema.sql").read_text(encoding="utf-8")
    with bd.conexao() as c:
        c.executescript(sql)
    print("tabelas do pensamento prontas")


def main(argv: list[str]) -> int:
    cmd = (argv[1] if len(argv) > 1 else "estado").lower()
    janela = "--ignorar-janela" not in argv

    if cmd == "preparar":
        preparar(); return 0
    if cmd == "estado":
        print(json.dumps(cliente.estado(), ensure_ascii=False, indent=2)); return 0

    from . import faro, veredito
    try:
        if cmd in ("faro", "ciclo"):
            r = faro.levantar(respeitar_janela=janela)
            print(json.dumps(r, ensure_ascii=False, indent=2))
        if cmd in ("provar", "ciclo"):
            r = veredito.provar_pendentes(respeitar_janela=janela)
            print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    except cliente.PensamentoIndisponivel as e:
        print(json.dumps({"pensamento": "indisponivel", "motivo": str(e)},
                         ensure_ascii=False))
        return 0            # degradação segura: nunca derruba o ciclo
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
