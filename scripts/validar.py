#!/usr/bin/env python3
"""Valida data/events.json, data/descartados.json e os YAML de .github.

Roda em todo PR (GitHub Actions) e localmente:

    python scripts/validar.py

PyYAML só é obrigatório no Action (pip install pyyaml). Sem ele, a checagem
dos .yml avisa e não falha.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORMATS = {"presencial", "online", "hibrido"}
COSTS = {"gratis", "pago", "desconhecido"}
REGS = {"livre", "inscricao", "aprovacao", "ingresso"}
STATUS = {"confirmado", "a-confirmar"}
REQUIRED = ["id", "title", "start", "format", "cost", "registration", "url", "tags"]
DESCARTADOS = ROOT / "data" / "descartados.json"


def url_chave(url: str) -> str:
    """Chave de comparação: sem query, sem barra final, em minúsculas.

    Sem esquema, assume https://. Tira www. e trata lu.ma como luma.com.
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    partes = urllib.parse.urlsplit(raw)
    host = partes.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host == "lu.ma":
        host = "luma.com"
    path = partes.path.rstrip("/").lower()
    return f"{host}{path}"


def ler_descartados(path: Path | None = None) -> dict | str:
    """Devolve o JSON ou uma mensagem de erro."""
    arquivo = path or DESCARTADOS
    if not arquivo.exists():
        return {"urls": []}
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return f"data/descartados.json não é JSON válido ({exc.msg})"
    if not isinstance(dados, dict):
        return "data/descartados.json precisa ser um objeto"
    return dados


def erros_descartados(dados: dict) -> list[str]:
    errs: list[str] = []
    urls = dados.get("urls")
    if not isinstance(urls, list):
        return ["data/descartados.json precisa de uma lista «urls»"]
    vistas: set[str] = set()
    for i, item in enumerate(urls, 1):
        onde = f"data/descartados.json item {i}"
        if not isinstance(item, dict):
            errs.append(f"{onde}: precisa ser um objeto")
            continue
        if not str(item.get("url") or "").strip():
            errs.append(f"{onde}: falta «url»")
        if not str(item.get("motivo") or "").strip():
            errs.append(f"{onde}: falta «motivo»")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(item.get("data") or "")):
            errs.append(f"{onde}: «data» precisa ser AAAA-MM-DD")
        chave = url_chave(item.get("url") or "")
        if chave and chave in vistas:
            errs.append(f"{onde}: url repetida")
        if chave:
            vistas.add(chave)
    return errs


def chaves_descartadas(path: Path | None = None) -> set[str]:
    dados = ler_descartados(path)
    if isinstance(dados, str):
        return set()
    chaves = set()
    for item in dados.get("urls") or []:
        if isinstance(item, dict):
            chave = url_chave(item.get("url") or "")
            if chave:
                chaves.add(chave)
    return chaves


def check(data: dict, vocab: set[str], descartadas: set[str] | None = None) -> list[str]:
    errs: list[str] = []
    if descartadas is None:
        descartadas = chaves_descartadas()
    if not isinstance(data.get("events"), list):
        return ["o arquivo precisa de uma lista «events»"]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(data.get("updated", ""))):
        errs.append("«updated» precisa ser AAAA-MM-DD")
    ids, urls = set(), set()
    for i, e in enumerate(data["events"]):
        where = f"evento {i + 1} ({e.get('id') or e.get('title') or '?'})"
        for k in REQUIRED:
            if e.get(k) in (None, "", []):
                errs.append(f"{where}: falta «{k}»")
        if e.get("id") in ids:
            errs.append(f"{where}: id repetido")
        ids.add(e.get("id"))
        chave = url_chave(e.get("url") or "")
        if chave and chave in urls:
            errs.append(f"{where}: url repetida")
        if chave:
            urls.add(chave)
        if chave and chave in descartadas:
            errs.append(f"{where}: url também está em data/descartados.json")
        if e.get("url") and not str(e["url"]).startswith("https://"):
            errs.append(f"{where}: a url precisa começar com https://")
        for k in ("start", "end"):
            v = e.get(k)
            if v is None:
                continue
            try:
                if len(v) == 10:
                    dt.date.fromisoformat(v)
                else:
                    d = dt.datetime.fromisoformat(v)
                    if d.tzinfo is None:
                        errs.append(f"{where}: «{k}» sem fuso (use -03:00)")
            except (TypeError, ValueError):
                errs.append(f"{where}: «{k}» não é uma data ISO válida ({v})")
        if e.get("start") and e.get("end") and e["end"][:10] < e["start"][:10]:
            errs.append(f"{where}: termina antes de começar")
        if e.get("format") not in FORMATS:
            errs.append(f"{where}: format deve ser um de {sorted(FORMATS)}")
        if (e.get("cost") or {}).get("type") not in COSTS:
            errs.append(f"{where}: cost.type deve ser um de {sorted(COSTS)}")
        if e.get("registration") not in REGS:
            errs.append(f"{where}: registration deve ser um de {sorted(REGS)}")
        if e.get("status", "confirmado") not in STATUS:
            errs.append(f"{where}: status deve ser um de {sorted(STATUS)}")
        bad = [t for t in e.get("tags", []) if t not in vocab]
        if bad:
            errs.append(f"{where}: tags fora do vocabulário {bad} (veja data/tags.json)")
        if len(e.get("tags", [])) > 6:
            errs.append(f"{where}: no máximo 6 tags")
        desc = (e.get("description") or {}).get("pt") or ""
        if len(desc) > 280:
            errs.append(f"{where}: descrição com mais de 280 caracteres; resuma com suas palavras")
    return errs


def check_issue_form(doc: object, nome: str) -> list[str]:
    """Plantilha de issue: name, description e body; cada campo com id único."""
    errs: list[str] = []
    if not isinstance(doc, dict):
        return [f"{nome}: a plantilha precisa ser um mapa YAML"]
    if not isinstance(doc.get("name"), str) or not str(doc.get("name")).strip():
        errs.append(f"{nome}: falta «name»")
    desc = doc.get("description")
    if not isinstance(desc, str) or not desc.strip():
        errs.append(f"{nome}: «description» precisa ser texto (use aspas se tiver «: »)")
    body = doc.get("body")
    if not isinstance(body, list) or not body:
        errs.append(f"{nome}: falta «body»")
        return errs
    ids: list[str] = []
    for i, campo in enumerate(body, 1):
        if not isinstance(campo, dict):
            errs.append(f"{nome}: campo {i} inválido")
            continue
        if campo.get("type") == "markdown":
            continue
        fid = campo.get("id")
        if not isinstance(fid, str) or not fid.strip():
            errs.append(f"{nome}: campo {i} ({campo.get('type') or '?'}) sem id")
        elif fid in ids:
            errs.append(f"{nome}: id repetido «{fid}»")
        else:
            ids.append(fid)
    return errs


def check_github_yaml(root: Path | None = None) -> tuple[list[str], str | None]:
    """Valida os .yml de .github. Sem PyYAML, avisa e não falha."""
    base_root = root or ROOT
    base = base_root / ".github"
    try:
        import yaml
    except ImportError:
        return [], "PyYAML não está instalado; a checagem dos .yml de .github foi pulada."
    errs: list[str] = []
    arquivos = sorted(base.rglob("*.yml")) + sorted(base.rglob("*.yaml"))
    if not arquivos:
        errs.append(f"{base}: nenhum .yml encontrado")
    for path in arquivos:
        rel = path.relative_to(base_root).as_posix()
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            errs.append(f"{rel}: YAML inválido ({exc})")
            continue
        if doc is None:
            errs.append(f"{rel}: YAML vazio")
            continue
        if "ISSUE_TEMPLATE" in path.parts and path.name != "config.yml":
            errs.extend(check_issue_form(doc, rel))
    return errs, None


def main() -> int:
    data = json.loads((ROOT / "data" / "events.json").read_text(encoding="utf-8"))
    vocab = set(json.loads((ROOT / "data" / "tags.json").read_text(encoding="utf-8"))["tags"])
    errs = check(data, vocab)
    bruto = ler_descartados()
    if isinstance(bruto, str):
        errs.append(bruto)
    else:
        errs.extend(erros_descartados(bruto))
    yerrs, aviso = check_github_yaml()
    if aviso:
        print(f"⚠️ {aviso}")
    errs.extend(yerrs)
    if errs:
        print("❌ a agenda tem problemas:")
        print("\n".join(f"  - {e}" for e in errs))
        return 1
    print(f"✅ {len(data['events'])} eventos válidos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
