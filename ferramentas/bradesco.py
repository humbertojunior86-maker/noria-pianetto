"""Bradesco — API Saldos e Extratos (plataforma Bradesco Developers).

Segunda porta do dinheiro: o ATUA guarda o extrato que alguém importou por
OFX; aqui a NÓRIA pergunta o saldo e o extrato ao próprio banco. As duas
raízes são diferentes (`bradesco:*` × `atua:*`), então uma pode servir de
contraprova da outra — o que o OFX importado nunca conseguiu.

Só biblioteca padrão de propósito: o servidor não tem `requests` nem
`cryptography`, e cada dependência nova é uma porta a mais para quebrar.
mTLS sai pelo `ssl` do Python; a assinatura RS256 sai pelo `openssl` do
sistema.

Credencial: `client_id` + `client_secret` gerados no portal DEPOIS do upload
do certificado público. Toda chamada exige mTLS com o MESMO certificado e a
chave privada correspondente. Sem chave privada não há chamada — e o bloco
diz isso por escrito em vez de mostrar zero.

Autenticação: testado em produção em 14/09/2026 — o servidor de
autorização reconhece o Client ID pelo fluxo `jwt-bearer` (JWT RS256
assinado com a chave privada do certificado; sem a chave certa responde
código 104 "invalid signature") e não reconhece `client_credentials`
(código 100). O fluxo `auto` tenta JWT primeiro, cai para o outro, e grava
qual funcionou para não tatear de novo.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

from nucleo import bd
from .base import Ferramenta, Resultado, registrar

PASTA = Path(os.environ.get("NORIA_SEGREDOS", "/home/user/workspace/.secrets"))
_SEGREDO = PASTA / "bradesco.json"
_CERT = PASTA / "bradesco.cert.pem"
_CHAVE = PASTA / "bradesco.key.pem"

# Hosts publicados na página "First steps / Certificados" do portal.
HOSTS = {
    "sandbox": "https://openapisandbox.prebanco.com.br",
    "homologacao": "https://proxy.api.prebanco.com.br",
    "producao": "https://openapi.bradesco.com.br",
}
CAMINHO_TOKEN = "/auth/server/v1.1/token"
CAMINHO_SALDO = "/v1/contas/fornecimento/saldos"
CAMINHO_EXTRATO = "/v1/contas/fornecimento/extratos"
TEMPO_LIMITE_S = 25
BANCO = "237"

_token_cache: dict[str, tuple[str, float]] = {}


# ------------------------------------------------------------------ segredo
def ler_config() -> dict:
    if not _SEGREDO.exists():
        return {}
    try:
        return json.loads(_SEGREDO.read_text())
    except Exception:  # noqa: BLE001
        return {}


def gravar_config(novo: dict) -> dict:
    """Mescla e grava. Certificado e chave viram arquivos 600 separados.

    Campo vazio não apaga o que já está gravado — quem quer apagar manda
    o marcador `null`. Assim o formulário pode ser reenviado só com a parte
    que mudou sem derrubar o resto.
    """
    PASTA.mkdir(parents=True, exist_ok=True)
    cfg = ler_config()
    for k in ("client_id", "client_secret", "ambiente", "fluxo"):
        if k in novo:
            v = novo[k]
            if v is None:
                cfg.pop(k, None)
            elif str(v).strip():
                cfg[k] = str(v).strip()
    if "contas" in novo and novo["contas"] is not None:
        cfg["contas"] = _normalizar_contas(novo["contas"])
    for chave, arq in (("certificado_pem", _CERT), ("chave_privada_pem", _CHAVE)):
        if chave in novo:
            v = novo[chave]
            if v is None:
                arq.unlink(missing_ok=True)
            elif str(v).strip():
                arq.write_text(_normalizar_pem(str(v)))
                os.chmod(arq, 0o600)
    cfg.setdefault("ambiente", "producao")
    cfg.setdefault("fluxo", "auto")
    _SEGREDO.write_text(json.dumps(cfg, ensure_ascii=False, indent=1))
    os.chmod(_SEGREDO, 0o600)
    _token_cache.clear()
    # a ferramenta registrada nasce com a limitação da hora do import;
    # depois de gravar credencial nova ela precisa reler.
    FERRAMENTA.limitacao = limitacao()
    return cfg


def _normalizar_pem(txt: str) -> str:
    txt = txt.strip().replace("\r", "")
    if "-----BEGIN" in txt:
        return txt + "\n"
    # corpo puro em base64 (o portal manda assim) -> embrulha como certificado
    corpo = "".join(txt.split())
    linhas = [corpo[i:i + 64] for i in range(0, len(corpo), 64)]
    return "-----BEGIN CERTIFICATE-----\n" + "\n".join(linhas) + "\n-----END CERTIFICATE-----\n"


def _normalizar_contas(contas) -> list[dict]:
    saida = []
    if isinstance(contas, str):
        contas = [l for l in contas.splitlines() if l.strip()]
    for c in contas or []:
        if isinstance(c, str):
            partes = [p.strip() for p in c.replace(",", ";").split(";")]
            c = {"agencia": partes[0] if partes else "",
                 "conta": partes[1] if len(partes) > 1 else "",
                 "tipo": partes[2] if len(partes) > 2 else "cc",
                 "apelido": partes[3] if len(partes) > 3 else ""}
        ag = "".join(ch for ch in str(c.get("agencia", "")) if ch.isdigit())
        ct = "".join(ch for ch in str(c.get("conta", "")) if ch.isdigit())
        if not ag or not ct:
            continue
        # a API pede agência com 4 dígitos sem DV e conta com 7 dígitos
        saida.append({"agencia": ag[-4:].zfill(4), "conta": ct[-7:].zfill(7),
                      "tipo": (c.get("tipo") or "cc").lower()[:2],
                      "apelido": (c.get("apelido") or "").strip()[:60]})
    return saida


def estado_config() -> dict:
    cfg = ler_config()
    cid = cfg.get("client_id") or ""
    return {
        "tem_client_id": bool(cid),
        "client_id_mascarado": (cid[:4] + "…" + cid[-4:]) if len(cid) > 8 else ("•" * len(cid)),
        "tem_client_secret": bool(cfg.get("client_secret")),
        "tem_certificado": _CERT.exists(),
        "tem_chave_privada": _CHAVE.exists(),
        "ambiente": cfg.get("ambiente", "producao"),
        "fluxo": cfg.get("fluxo", "auto"),
        "fluxo_confirmado": cfg.get("fluxo_confirmado"),
        "contas": cfg.get("contas", []),
        "host": HOSTS.get(cfg.get("ambiente", "producao"), HOSTS["producao"]),
        "limitacao": limitacao(),
    }


def limitacao() -> str | None:
    cfg = ler_config()
    faltas = []
    if not cfg.get("client_id"):
        faltas.append("o Client ID")
    if not cfg.get("client_secret"):
        faltas.append("o Client Secret")
    if not _CERT.exists():
        faltas.append("o certificado público (o mesmo enviado ao portal)")
    if not _CHAVE.exists():
        faltas.append("a chave privada do certificado")
    if faltas:
        if len(faltas) == 1:
            return "falta " + faltas[0]
        return "faltam " + ", ".join(faltas[:-1]) + " e " + faltas[-1]
    if not cfg.get("contas"):
        return "nenhuma agência/conta cadastrada para consultar"
    return None


# --------------------------------------------------------------- transporte
def _contexto_ssl() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.load_cert_chain(certfile=str(_CERT), keyfile=str(_CHAVE))
    return ctx


def _http(metodo: str, url: str, corpo: bytes | None, cabecalhos: dict) -> tuple[int, str]:
    req = urllib.request.Request(url, data=corpo, method=metodo, headers=cabecalhos)
    try:
        with urllib.request.urlopen(req, timeout=TEMPO_LIMITE_S, context=_contexto_ssl()) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except ssl.SSLError as e:
        raise RuntimeError(f"TLS recusado pelo banco: {e.reason or e}. Certificado e chave "
                           "precisam ser os mesmos enviados ao portal.") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"não foi possível falar com o Bradesco: {e.reason}") from e


def _assinar_rs256(texto: bytes) -> bytes:
    """SHA256withRSA (PKCS#1 v1.5) com a chave privada, via openssl do sistema."""
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(texto)
        nome = f.name
    try:
        p = subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(_CHAVE), nome],
                           capture_output=True, timeout=20)
    finally:
        os.unlink(nome)
    if p.returncode != 0:
        raise RuntimeError("a chave privada não assina: " + p.stderr.decode("utf-8", "replace").strip()[:200])
    return p.stdout


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _jwt_assertion(cfg: dict, url_token: str) -> str:
    agora = int(time.time())
    cab = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    corpo = _b64url(json.dumps({
        "aud": url_token, "sub": cfg["client_id"], "iat": agora,
        "exp": agora + 3600, "jti": str(agora * 1000), "ver": "1.1",
    }).encode())
    ass = _b64url(_assinar_rs256(f"{cab}.{corpo}".encode()))
    return f"{cab}.{corpo}.{ass}"


def _pedir_token(cfg: dict, fluxo: str) -> tuple[bool, str, str]:
    host = HOSTS.get(cfg.get("ambiente", "producao"), HOSTS["producao"])
    url = host + CAMINHO_TOKEN
    if fluxo == "jwt":
        dados = {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                 "assertion": _jwt_assertion(cfg, url)}
        cab = {"Content-Type": "application/x-www-form-urlencoded"}
    else:
        dados = {"grant_type": "client_credentials", "client_id": cfg["client_id"],
                 "client_secret": cfg["client_secret"]}
        basico = base64.b64encode(f"{cfg['client_id']}:{cfg['client_secret']}".encode()).decode()
        cab = {"Content-Type": "application/x-www-form-urlencoded",
               "Authorization": f"Basic {basico}"}
    cab["Accept"] = "application/json"
    status, texto = _http("POST", url, urllib.parse.urlencode(dados).encode(), cab)
    if status != 200:
        return False, "", f"HTTP {status} no token ({fluxo}): {_traduzir_erro(texto)}"
    try:
        j = json.loads(texto.replace("\xa0", " "))
    except ValueError:
        return False, "", f"token ({fluxo}): resposta não é JSON: {texto[:120]}"
    tok = j.get("access_token")
    if not tok:
        return False, "", f"token ({fluxo}): resposta sem access_token: {texto[:160]}"
    exp = float(j.get("expires_in") or 3600)
    return True, tok, str(exp)


# Códigos observados no servidor de autorização de produção (14/09/2026):
# 100 "invalid token" = credencial/grant não reconhecido; 104 "invalid
# signature" = client_id reconhecido, mas a assinatura não bate com o
# certificado cadastrado no portal — ou seja, chave privada errada.
_ERROS_TOKEN = {
    "100": "credencial não reconhecida pelo banco (código 100)",
    "104": "assinatura recusada: a chave privada não corresponde ao certificado cadastrado no portal (código 104)",
}


def _traduzir_erro(texto: str) -> str:
    # o servidor de autorização devolve JSON com espaço duro (U+00A0) entre
    # chave e valor; o parser padrão recusa — troca antes de ler.
    try:
        j = json.loads(texto.replace("\xa0", " "))
        cod = str(j.get("code", "")).strip()
        if cod in _ERROS_TOKEN:
            return _ERROS_TOKEN[cod]
        return f"{j.get('message') or texto.strip()[:200]} (código {cod or '?'})"
    except ValueError:
        return texto.strip()[:240] or "sem corpo"


def token() -> str:
    """Token válido, do cache quando dá. Grava qual fluxo funcionou."""
    cfg = ler_config()
    chave = cfg.get("ambiente", "producao")
    t = _token_cache.get(chave)
    if t and t[1] > time.time() + 30:
        return t[0]
    fluxo = cfg.get("fluxo", "auto")
    ordem = [fluxo] if fluxo in ("client_credentials", "jwt") else \
        ([cfg["fluxo_confirmado"]] if cfg.get("fluxo_confirmado") in ("client_credentials", "jwt") else []) \
        + [f for f in ("jwt", "client_credentials") if f != cfg.get("fluxo_confirmado")]
    erros = []
    for fl in ordem:
        try:
            ok, tok, extra = _pedir_token(cfg, fl)
        except RuntimeError as e:
            erros.append(str(e))
            break
        if ok:
            _token_cache[chave] = (tok, time.time() + float(extra))
            if cfg.get("fluxo_confirmado") != fl:
                cfg["fluxo_confirmado"] = fl
                _SEGREDO.write_text(json.dumps(cfg, ensure_ascii=False, indent=1))
            return tok
        erros.append(extra)
    raise RuntimeError(" | ".join(erros) or "nenhum fluxo de autenticação tentado")


def _cabecalhos_assinados(metodo: str, caminho: str, query: str, corpo: str, tok: str) -> dict:
    nonce = str(int(time.time() * 1000))
    carimbo = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S-00:00")
    texto = "\n".join([metodo, caminho, query, corpo, tok, nonce, carimbo, "SHA256"])
    assinatura = base64.b64encode(_assinar_rs256(texto.encode())).decode()
    return {
        "Authorization": f"Bearer {tok}",
        "Accept": "application/json",
        "X-Brad-Signature": assinatura,
        "X-Brad-Nonce": nonce,
        "X-Brad-Timestamp": carimbo,
        "X-Brad-Algorithm": "SHA256",
        "X-Brad-Algoritmo": "SHA256",
        "access-token": tok,
    }


def _get(caminho: str, params: dict) -> dict:
    cfg = ler_config()
    host = HOSTS.get(cfg.get("ambiente", "producao"), HOSTS["producao"])
    tok = token()
    query = urllib.parse.urlencode(params)
    status, texto = _http("GET", f"{host}{caminho}?{query}", None,
                          _cabecalhos_assinados("GET", caminho, query, "", tok))
    if status == 401:
        _token_cache.clear()
    if status != 200:
        raise RuntimeError(f"HTTP {status} em {caminho}: {_traduzir_erro(texto)}")
    try:
        j = json.loads(texto.replace("\xa0", " "))
    except ValueError:
        raise RuntimeError(f"{caminho}: resposta não é JSON: {texto[:120]}")
    cr = str(j.get("codigoRetorno", "0")).strip()
    if cr not in ("0", "00", "", "None"):
        raise RuntimeError(f"banco respondeu codigoRetorno {cr}: {j.get('mensagem') or 'sem mensagem'}")
    return j


# ---------------------------------------------------------------- leituras
def _num(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(".", "").replace(",", ".") if "," in str(v) else str(v).strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _sinal(s) -> int:
    s = str(s or "").strip().upper()
    return -1 if s in ("-", "D", "DEBITO", "DÉBITO", "NEGATIVO") else 1


def saldo(agencia: str, conta: str) -> dict:
    j = _get(CAMINHO_SALDO, {"agencia": agencia, "conta": conta})
    itens = ((j.get("saldoCC") or {}).get("lstLancamentosSaldos")) or []
    linhas, disponivel = [], None
    for it in itens:
        v = _num(it.get("valorLancamento")) * _sinal(it.get("sinalSaldo"))
        nome = (it.get("nomeProduto") or "").strip()
        linhas.append({"produto": nome, "codigo": it.get("codigoProduto"), "valor": v})
        if disponivel is None and ("DISPON" in nome.upper() or "SALDO" in nome.upper()):
            disponivel = v
    if disponivel is None and linhas:
        disponivel = linhas[0]["valor"]
    return {"agencia": agencia, "conta": conta, "disponivel": disponivel,
            "linhas": linhas, "status_conta": j.get("statusContaCorrente"),
            "consultado_em": bd.agora(), "bruto": j}


def extrato(agencia: str, conta: str, inicio: date, fim: date, tipo: str = "cc") -> dict:
    if (fim - inicio).days > 365:
        raise RuntimeError("o banco só aceita até um ano por consulta de extrato")
    j = _get(CAMINHO_EXTRATO, {"agencia": agencia, "conta": conta,
                               "dataInicio": inicio.strftime("%d%m%Y"),
                               "dataFim": fim.strftime("%d%m%Y"), "tipo": tipo})
    brutos = ((j.get("extratoPorPeriodo") or {}).get("lstLancamentoMensal")) or []
    if not brutos:
        brutos = ((j.get("extratoUltimosLancamentos") or {}).get("listaLancamentos")) or []
    movs = []
    for m in brutos:
        desc = (m.get("descritivoLancamentoCompleto") or m.get("descritivoLancamentoAbreviado") or "").strip()
        if desc.upper().startswith("SALDO ANTERIOR"):
            continue
        d = str(m.get("dataLancamento") or "").strip()
        data_iso = _data_iso(d)
        v = _num(m.get("valorLancamento")) * _sinal(m.get("sinalLancamento"))
        movs.append({
            "data": data_iso, "valor": v, "documento": str(m.get("numeroDocumento") or "").strip(),
            "descricao": desc, "tipo": m.get("tipoLancamento"), "codigo": m.get("codigoLancamento"),
            "saldo_apos": _num(m.get("valorSaldoAposLancamento")) * _sinal(m.get("sinalSaldo")),
        })
    return {"agencia": agencia, "conta": conta, "inicio": inicio.isoformat(),
            "fim": fim.isoformat(), "movimentos": movs, "consultado_em": bd.agora()}


def _data_iso(d: str) -> str:
    for fmt in ("%d/%m/%Y", "%d%m%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(d, fmt).date().isoformat()
        except ValueError:
            continue
    return d


# ------------------------------------------------------------------ colheita
def colher(empresa_id: int, dia: date | None = None, dias: int = 3) -> dict:
    """Guarda saldo de agora e os movimentos dos últimos `dias` dias.

    Movimento repetido não entra duas vezes: o hash cobre conta, data, valor,
    documento e descrição. Falha de uma conta não derruba as outras — cada
    conta sai com o próprio motivo.
    """
    lim = limitacao()
    if lim:
        return {"ok": False, "motivo": lim, "contas": []}
    cfg = ler_config()
    fim = dia or datetime.now(bd.FUSO).date()
    ini = fim - timedelta(days=dias)
    saida = {"ok": True, "contas": [], "novos": 0, "colhido_em": bd.agora()}
    for c in cfg.get("contas", []):
        item = {"agencia": c["agencia"], "conta": c["conta"], "apelido": c.get("apelido")}
        try:
            s = saldo(c["agencia"], c["conta"])
            bd.inserir("banco_saldo", {
                "empresa_id": empresa_id, "banco": BANCO, "agencia": c["agencia"],
                "conta": c["conta"], "apurado_em": s["consultado_em"],
                "disponivel": s["disponivel"], "linhas": bd.j(s["linhas"]),
                "status_conta": s.get("status_conta"), "fonte": "bradesco:saldo"})
            item["disponivel"] = s["disponivel"]
        except Exception as e:  # noqa: BLE001
            item["erro_saldo"] = str(e)[:300]
            saida["ok"] = False
        try:
            e_ = extrato(c["agencia"], c["conta"], ini, fim, c.get("tipo", "cc"))
            novos = 0
            for m in e_["movimentos"]:
                h = hashlib.sha256("|".join([BANCO, c["agencia"], c["conta"], m["data"],
                                             f"{m['valor']:.2f}", m["documento"],
                                             m["descricao"]]).encode()).hexdigest()[:40]
                if bd.linha("SELECT id FROM banco_movimento WHERE hash=?", (h,)):
                    continue
                bd.inserir("banco_movimento", {
                    "empresa_id": empresa_id, "banco": BANCO, "agencia": c["agencia"],
                    "conta": c["conta"], "data": m["data"], "valor": m["valor"],
                    "documento": m["documento"], "descricao": m["descricao"],
                    "tipo": m.get("tipo"), "codigo": m.get("codigo"),
                    "saldo_apos": m.get("saldo_apos"), "hash": h,
                    "colhido_em": e_["consultado_em"], "fonte": "bradesco:extrato"})
                novos += 1
            item["movimentos_lidos"] = len(e_["movimentos"])
            item["movimentos_novos"] = novos
            saida["novos"] += novos
        except Exception as e:  # noqa: BLE001
            item["erro_extrato"] = str(e)[:300]
            saida["ok"] = False
        saida["contas"].append(item)
    estado = "conectada" if saida["ok"] else "erro"
    erro = None if saida["ok"] else "; ".join(
        f"{c['agencia']}/{c['conta']}: {c.get('erro_saldo') or c.get('erro_extrato')}"
        for c in saida["contas"] if c.get("erro_saldo") or c.get("erro_extrato"))[:500]
    bd.executar("UPDATE integracao SET estado=?, ultimo_teste=?, ultimo_erro=? WHERE id='bradesco' AND empresa_id=?",
                (estado, bd.agora(), erro, empresa_id))
    bd.evento(empresa_id, "tesouraria.colheita",
              (f"Bradesco: saldo lido em {len(saida['contas'])} conta(s), "
               f"{saida['novos']} movimento(s) novo(s) guardado(s).") if saida["ok"]
              else f"Bradesco: colheita com falha — {erro}", ator="agendador")
    return saida


def colheita_diaria(empresa_id: int = 1) -> list[int]:
    """Entrada do agendador. Sem credencial completa, silêncio: a limitação
    já aparece por escrito na tela de integrações."""
    if limitacao():
        return []
    colher(empresa_id)
    return []


def retrato(empresa_id: int) -> dict:
    """O que a tesouraria vê: último saldo por conta ou o motivo de não ter."""
    est = estado_config()
    contas = []
    for c in est["contas"]:
        u = bd.linha("SELECT * FROM banco_saldo WHERE empresa_id=? AND agencia=? AND conta=? "
                     "ORDER BY apurado_em DESC LIMIT 1", (empresa_id, c["agencia"], c["conta"]))
        n = bd.linha("SELECT COUNT(*) n, MIN(data) de, MAX(data) ate FROM banco_movimento "
                     "WHERE empresa_id=? AND agencia=? AND conta=?", (empresa_id, c["agencia"], c["conta"]))
        contas.append({**c, "saldo": u and {"disponivel": u["disponivel"], "apurado_em": u["apurado_em"],
                                            "linhas": bd.dj(u["linhas"])},
                       "movimentos": int(n["n"] or 0) if n else 0,
                       "movimentos_de": n and n["de"], "movimentos_ate": n and n["ate"]})
    integ = bd.linha("SELECT estado, ultimo_teste, ultimo_erro FROM integracao WHERE id='bradesco' AND empresa_id=?",
                     (empresa_id,)) or {}
    return {"config": est, "contas": contas, "integracao": integ,
            "motivo": est["limitacao"] or integ.get("ultimo_erro"),
            "total_disponivel": sum((c["saldo"] or {}).get("disponivel") or 0 for c in contas)
            if contas and all(c["saldo"] for c in contas) else None}


def garantir_registro(empresa_id: int) -> None:
    if not bd.linha("SELECT id FROM integracao WHERE id='bradesco'"):
        bd.inserir("integracao", {
            "id": "bradesco", "empresa_id": empresa_id, "nome": "Bradesco (saldo e extrato)",
            "tipo": "api", "permissoes": bd.j(["leitura"]), "escreve": 0,
            "estado": "nao_configurada", "ultimo_teste": None,
            "ultimo_erro": limitacao(), "ambiente": ler_config().get("ambiente", "producao")})


# ------------------------------------------------------------------ ferramenta
def _executar(operacao: str, empresa_id: int, **kw) -> Resultado:
    lim = limitacao()
    if lim:
        return Resultado(False, erro=f"Bradesco indisponível — {lim}")
    try:
        if operacao == "conta.listar":
            cfg = ler_config()
            tok = token()
            dados = [{**c, "token_ok": bool(tok)} for c in cfg.get("contas", [])]
            return Resultado(True, dados={"linhas": dados, "consultada_em": bd.agora()},
                             resumo=f"token emitido pelo banco; {len(dados)} conta(s) cadastrada(s)",
                             linhas=len(dados), raiz="bradesco:token", referencia="bradesco:token")
        if operacao == "saldo":
            s = saldo(kw["agencia"], kw["conta"])
            return Resultado(True, dados=s, resumo=f"saldo disponível {s['disponivel']}",
                             linhas=len(s["linhas"]), raiz="bradesco:saldo",
                             referencia=f"bradesco:saldo {kw['agencia']}/{kw['conta']}")
        if operacao == "extrato":
            ini = date.fromisoformat(kw["inicio"]); fim = date.fromisoformat(kw["fim"])
            e = extrato(kw["agencia"], kw["conta"], ini, fim, kw.get("tipo") or "cc")
            return Resultado(True, dados=e, resumo=f"{len(e['movimentos'])} movimento(s)",
                             linhas=len(e["movimentos"]), raiz="bradesco:extrato",
                             referencia=f"bradesco:extrato {kw['agencia']}/{kw['conta']} {ini}..{fim}")
        if operacao == "colher":
            r = colher(empresa_id)
            return Resultado(r["ok"], dados=r, resumo=f"{r.get('novos', 0)} movimento(s) novo(s)",
                             erro=None if r["ok"] else r.get("motivo") or "falha em pelo menos uma conta",
                             raiz="bradesco:colheita", referencia="bradesco:colheita")
        return Resultado(False, erro=f"operação '{operacao}' não existe no Bradesco")
    except KeyError as e:
        return Resultado(False, erro=f"parâmetro ausente: {e}")
    except Exception as e:  # noqa: BLE001
        return Resultado(False, erro=str(e)[:400])


FERRAMENTA = registrar(Ferramenta(
    id="bradesco",
    nome="Bradesco (saldo e extrato)",
    descricao="Saldo e extrato direto do banco, por API com mTLS. Somente leitura.",
    escreve=False,
    executar=_executar,
    operacoes=["conta.listar", "saldo", "extrato", "colher"],
    limitacao=limitacao(),
))
