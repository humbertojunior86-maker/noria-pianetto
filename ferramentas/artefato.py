"""Geração de artefatos. O que a missão promete entregar precisa existir em disco."""
from __future__ import annotations

import csv
import os
from pathlib import Path

from nucleo import bd

PASTA = Path(os.environ.get("NORIA_ARTEFATOS",
                            Path(__file__).resolve().parent.parent / "artefatos"))


def _slug(t: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:60] or "artefato"


def registrar(empresa_id: int, missao_id: int, nome: str, formato: str,
              caminho: Path, entrega_id: int | None = None) -> int:
    return bd.inserir("artefato", {
        "empresa_id": empresa_id, "missao_id": missao_id,
        "entrega_id": entrega_id, "nome": nome, "formato": formato,
        "caminho": str(caminho), "bytes": caminho.stat().st_size,
        "versao": 1, "criado_em": bd.agora()})


def relatorio(missao_id: int) -> list[int]:
    """Monta o relatório da missão em Markdown, com a evidência de cada afirmação.

    Afirmação rebaixada a hipótese aparece marcada, não escondida.
    """
    m = bd.linha("SELECT * FROM missao WHERE id=?", (missao_id,))
    emp = m["empresa_id"]
    pasta = PASTA / f"missao-{missao_id}"
    pasta.mkdir(parents=True, exist_ok=True)
    criados: list[int] = []

    L = [f"# {m['objetivo']}", "",
         f"Missão {missao_id} · aberta em {m['criada_em']} · origem: {m['origem']}",
         ""]

    entregas = bd.linhas(
        "SELECT e.*, t.titulo, t.agente_id FROM entrega e "
        "JOIN tarefa t ON t.id = e.tarefa_id WHERE e.missao_id=? ORDER BY e.id",
        (missao_id,))

    for e in entregas:
        L += [f"## {e['titulo']}", "", e["resumo"], ""]
        afirm = bd.linhas(
            "SELECT * FROM afirmacao WHERE entrega_id=? ORDER BY id", (e["id"],))
        if afirm:
            L.append("### Afirmações e lastro")
            L.append("")
            for a in afirm:
                marca = "" if a["natureza"] == "fato" else f" _({a['natureza']})_"
                if a["evidencia_id"]:
                    ev = bd.linha("SELECT * FROM evidencia WHERE id=?",
                                  (a["evidencia_id"],))
                    lastro = (f"  \n  Evidência: `{ev['origem']}` — "
                              f"{ev['trecho']} (consultada em {ev['consultada_em']})")
                else:
                    lastro = "  \n  Sem evidência ligada."
                L.append(f"- {a['texto']}{marca}{lastro}")
            L.append("")
        inc = bd.dj(e["incertezas"])
        if inc:
            L += ["### O que ficou incerto", ""] + [f"- {i}" for i in inc] + [""]
        pen = bd.dj(e["pendencias"])
        if pen:
            L += ["### Pendências", ""] + [f"- {p}" for p in pen] + [""]

        # anexo com as linhas que sustentam o achado
        res = bd.dj(e["resultado"], {}) or {}
        amostra = res.get("amostra_sem_par") or res.get("amostra") or []
        if amostra:
            csvp = pasta / f"{_slug(e['titulo'])}.csv"
            with csvp.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(amostra[0]))
                w.writeheader()
                for r in amostra:
                    w.writerow(r)
            criados.append(registrar(emp, missao_id,
                                     f"Detalhamento — {e['titulo']}", "csv",
                                     csvp, e["id"]))
            L += [f"Detalhamento em `{csvp.name}` ({len(amostra)} linha(s)).", ""]

    val = bd.linhas(
        "SELECT camada, resultado, justificativa FROM validacao "
        "WHERE missao_id=? ORDER BY id", (missao_id,))
    if val:
        L += ["## Como isto foi verificado", "",
              "| Camada | Resultado | Justificativa |", "|---|---|---|"]
        for v in val:
            j = v["justificativa"].replace("|", "\\|")
            L.append(f"| {v['camada']} | {v['resultado']} | {j} |")
        L.append("")

    L += ["---", "",
          "Relatório gerado pela NÓRIA. Cada número acima nasceu de uma "
          "consulta datada ao ATUA, em modo somente leitura."]

    md = pasta / "relatorio.md"
    md.write_text("\n".join(L), encoding="utf-8")
    criados.append(registrar(emp, missao_id, "Relatório da missão", "md", md))
    return criados
