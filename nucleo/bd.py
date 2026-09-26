"""Acesso ao banco da NÓRIA. SQLite é a fonte de verdade de missões e tarefas."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CAMINHO = Path(os.environ.get("NORIA_DB", RAIZ / "dados" / "noria.db"))
ESQUEMA = Path(__file__).resolve().parent / "esquema.sql"

_local = threading.local()
FUSO = timezone(timedelta(hours=-3))  # America/Sao_Paulo, sem horário de verão


def agora() -> str:
    """Carimbo ISO no fuso da empresa. Toda data gravada passa por aqui."""
    return datetime.now(FUSO).isoformat(timespec="seconds")


def conexao() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        CAMINHO.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(CAMINHO), timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=30000")
        _local.c = c
    return c


@contextmanager
def transacao():
    """Tudo que muda estado roda aqui dentro. Erro reverte."""
    c = conexao()
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise


# Colunas acrescentadas depois que o esquema já rodava em produção.
# CREATE TABLE IF NOT EXISTS não altera tabela que já existe, então coluna
# nova precisa entrar aqui ALÉM de entrar no esquema.sql.
_COLUNAS_NOVAS: list[tuple[str, str, str]] = [
    ("criterio", "tarefa_chave", "TEXT"),
    ("vigia", "apelido", "TEXT"),
    ("vigia_execucao", "todas", "TEXT"),
]


def migrar() -> None:
    c = conexao()
    c.executescript(ESQUEMA.read_text(encoding="utf-8"))
    for tabela, coluna, tipo in _COLUNAS_NOVAS:
        tem = any(r["name"] == coluna
                  for r in c.execute(f"PRAGMA table_info({tabela})"))
        if not tem:
            c.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")


# --------------------------------------------------------------------- helpers
def linhas(sql: str, args: tuple = ()) -> list[dict]:
    return [dict(r) for r in conexao().execute(sql, args).fetchall()]


def linha(sql: str, args: tuple = ()) -> dict | None:
    r = conexao().execute(sql, args).fetchone()
    return dict(r) if r else None


def executar(sql: str, args: tuple = ()) -> sqlite3.Cursor:
    return conexao().execute(sql, args)


def inserir(tabela: str, dados: dict) -> int:
    campos = ", ".join(dados)
    marcas = ", ".join("?" for _ in dados)
    cur = conexao().execute(
        f"INSERT INTO {tabela} ({campos}) VALUES ({marcas})", tuple(dados.values())
    )
    return int(cur.lastrowid)


def atualizar(tabela: str, id_: int, dados: dict) -> None:
    sets = ", ".join(f"{k} = ?" for k in dados)
    conexao().execute(
        f"UPDATE {tabela} SET {sets} WHERE id = ?", (*dados.values(), id_)
    )


def j(valor) -> str:
    """Serializa para coluna json. Nunca grava None cru."""
    # default=str cobre date, datetime e Decimal vindos do ERP
    return json.dumps(valor if valor is not None else [],
                      ensure_ascii=False, default=str)


def dj(texto: str | None, padrao=None):
    if not texto:
        return padrao if padrao is not None else []
    try:
        return json.loads(texto)
    except (ValueError, TypeError):
        return padrao if padrao is not None else []


# ---------------------------------------------------------------------- evento
def evento(
    empresa_id: int,
    tipo: str,
    texto: str,
    *,
    ator: str = "nucleo",
    missao_id: int | None = None,
    tarefa_id: int | None = None,
    de: str | None = None,
    para: str | None = None,
    dados: dict | None = None,
) -> int:
    """Trilha de auditoria. Append only — nada aqui é editado ou apagado."""
    return inserir(
        "evento",
        {
            "empresa_id": empresa_id,
            "missao_id": missao_id,
            "tarefa_id": tarefa_id,
            "tipo": tipo,
            "ator": ator,
            "de_estado": de,
            "para_estado": para,
            "texto": texto,
            "dados": j(dados) if dados is not None else None,
            "criado_em": agora(),
        },
    )
