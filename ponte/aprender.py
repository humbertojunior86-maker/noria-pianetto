"""Grava na NÓRIA o que foi lido no e-mail da empresa.

Roda no servidor, com um arquivo JSON ao lado. Cada tema vira um trecho do
documento; cada conclusão vira um aprendizado *proposto* — nunca aprovado
sozinho. Número que veio de e-mail entra como hipótese, não como fato: quem
confirma é o banco do ATUA, por outra porta. É essa a diferença entre o
cérebro aprender e o cérebro repetir o que leu.

Uso: python3 aprender.py aprendizado_outlook.json
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nucleo import bd  # noqa: E402

EMPRESA = 1


def main(caminho: str) -> None:
    dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    bd.migrar()

    titulo = dados["titulo"]
    ja = bd.linha("SELECT id, versao FROM documento WHERE empresa_id=? AND "
                  "titulo=? ORDER BY versao DESC LIMIT 1", (EMPRESA, titulo))
    doc = bd.inserir("documento", {
        "empresa_id": EMPRESA, "titulo": titulo,
        "assunto": dados.get("assunto", "empresa"),
        "origem": dados.get("origem", "outlook"),
        "caminho": dados.get("caminho"), "mime": "text/plain",
        "nivel_acesso": "interno", "situacao": "hipotese",
        "data_doc": dados.get("data_doc"),
        "versao": (ja["versao"] + 1) if ja else 1,
        "substitui": ja["id"] if ja else None,
        "ingerido_em": bd.agora(), "processado": "indexado"})
    if ja:
        bd.executar("UPDATE documento SET situacao='substituido' WHERE id=?",
                    (ja["id"],))

    for i, t in enumerate(dados.get("trechos") or []):
        texto = f"{t['tema']}\n{t['texto']}"
        bd.inserir("trecho", {
            "documento_id": doc, "ordem": i, "texto": texto,
            "hash": hashlib.sha256(texto.encode()).hexdigest()[:32]})

    novos = 0
    for a in dados.get("aprendizados") or []:
        if bd.linha("SELECT id FROM aprendizado WHERE empresa_id=? AND "
                    "enunciado=?", (EMPRESA, a["enunciado"])):
            continue
        bd.inserir("aprendizado", {
            "empresa_id": EMPRESA, "enunciado": a["enunciado"],
            "origem": a.get("origem", "e-mail da empresa (Outlook)"),
            "escopo": a.get("escopo", "empresa"),
            "validade": a.get("validade"), "estado": "proposto",
            "criado_em": bd.agora()})
        novos += 1

    print(f"documento {doc} · trechos {len(dados.get('trechos') or [])} · "
          f"aprendizados propostos {novos}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "aprendizado_outlook.json")
