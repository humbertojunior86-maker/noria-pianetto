"""Prepara o banco da NÓRIA: esquema, empresa, alçadas, integrações, agentes."""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agentes import registro as ar          # noqa: E402
from ferramentas import atua, base as fb    # noqa: E402,F401
from nucleo import bd                       # noqa: E402

EMPRESA_ID = 1


def senha(p: str) -> str:
    return hashlib.sha256(("noria$" + p).encode()).hexdigest()


def main() -> None:
    bd.migrar()

    if not bd.linha("SELECT id FROM empresa WHERE id=?", (EMPRESA_ID,)):
        bd.inserir("empresa", {
            "id": EMPRESA_ID, "nome": "PIANETTO TRANSPORTES E LOGISTICA LTDA",
            "cnpj": "43.976.512/0001-09", "cd_matriz": 2, "ativa": 1,
            "criada_em": bd.agora()})

    if not bd.linha("SELECT id FROM usuario WHERE email=?",
                    ("humbertojunior86@gmail.com",)):
        bd.inserir("usuario", {
            "empresa_id": EMPRESA_ID, "nome": "José Humberto Júnior",
            "email": "humbertojunior86@gmail.com",
            "senha_hash": senha(os.environ.get("NORIA_SENHA_INICIAL", "pianetto")),
            "papel": "ceo", "ativo": 1, "criado_em": bd.agora()})

    # Modo saguão: usuário só de exibição. O painel da parede fica visível para
    # cliente e visitante, então esta conta não enxerga dinheiro, nome de
    # cliente nem nada da Sala do CEO — a própria API recusa (ver api/main.py).
    if not bd.linha("SELECT id FROM usuario WHERE email=?",
                    ("saguao@pianetto.com.br",)):
        bd.inserir("usuario", {
            "empresa_id": EMPRESA_ID, "nome": "Painel do saguão",
            "email": "saguao@pianetto.com.br",
            "senha_hash": senha(os.environ.get("NORIA_SENHA_SAGUAO", "saguao")),
            "papel": "saguao", "ativo": 1, "criado_em": bd.agora()})

    # Ponte: a conta que o carteiro usa para levar aviso para fora e trazer
    # demanda para dentro. Só alcança a fila de avisos e a caixa de demandas
    # (ver PREFIXOS_DA_PONTE em api/main.py). Ela existe para que o canal de
    # e-mail não precise da senha do CEO.
    if not bd.linha("SELECT id FROM usuario WHERE email=?",
                    ("ponte@pianetto.com.br",)):
        bd.inserir("usuario", {
            "empresa_id": EMPRESA_ID, "nome": "Ponte de mensagens",
            "email": "ponte@pianetto.com.br",
            "senha_hash": senha(os.environ.get("NORIA_SENHA_PONTE", "ponte-noria")),
            "papel": "ponte", "ativo": 1, "criado_em": bd.agora()})

    # Alçada: sem isto, nada de impacto executa sozinho.
    if not bd.linha("SELECT id FROM alcada WHERE empresa_id=?", (EMPRESA_ID,)):
        for tipo, ate, papel, auto in [
            ("email", 0, "gestor", 0),
            ("mensagem", 0, "gestor", 0),
            ("escrita_erp", None, "ceo", 0),
            ("pagamento", None, "ceo", 0),
            ("publicacao", 0, "ceo", 0),
        ]:
            bd.inserir("alcada", {
                "empresa_id": EMPRESA_ID, "tipo_acao": tipo,
                "ate_centavos": ate, "papel_minimo": papel, "automatica": auto})

    # Integrações: estado real, nunca verde de enfeite.
    for iid, nome, tipo, perms, escreve, estado, erro in [
        ("atua", "ATUA (ERP)", "banco_de_dados", ["leitura"], 0,
         "conectada" if fb.obter("atua").disponivel() else "nao_configurada",
         fb.obter("atua").limitacao),
        ("x7bank", "X7 Bank (combustível)", "api", ["leitura"], 0,
         "nao_configurada", "credencial não fornecida"),
        ("gobrax", "Gobrax (telemetria)", "api", ["leitura"], 0,
         "nao_configurada", "credencial não fornecida"),
        ("t4s", "T4S (rastreamento)", "api", ["leitura"], 0,
         "nao_configurada", "credencial não fornecida"),
        ("email", "E-mail transacional", "smtp", ["envio"], 1,
         "nao_configurada", "remetente não configurado"),
    ]:
        if not bd.linha("SELECT id FROM integracao WHERE id=?", (iid,)):
            bd.inserir("integracao", {
                "id": iid, "empresa_id": EMPRESA_ID, "nome": nome, "tipo": tipo,
                "permissoes": bd.j(perms), "escreve": escreve, "estado": estado,
                "ultimo_teste": None, "ultimo_erro": erro,
                "ambiente": "producao"})

    ar.sincronizar(EMPRESA_ID)

    hab = sum(1 for d in ar.todos() if d.situacao()[0] == "habilitado")
    print(f"banco: {bd.CAMINHO}")
    print(f"agentes: {len(ar.todos())} cadastrados, {hab} habilitados")
    print(f"ferramentas: {[f.id for f in fb.todas()]}")


if __name__ == "__main__":
    main()
