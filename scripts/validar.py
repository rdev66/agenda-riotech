#!/usr/bin/env python3
"""Valida data/events.json. Roda em todo PR (GitHub Actions) e localmente:

    python scripts/validar.py
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORMATS = {"presencial", "online", "hibrido"}
COSTS = {"gratis", "pago", "desconhecido"}
REGS = {"livre", "inscricao", "aprovacao", "ingresso"}
STATUS = {"confirmado", "a-confirmar"}
REQUIRED = ["id", "title", "start", "format", "cost", "registration", "url", "tags"]


def check(data: dict, vocab: set[str]) -> list[str]:
    errs: list[str] = []
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
        url = (e.get("url") or "").lower().rstrip("/")
        if url in urls:
            errs.append(f"{where}: url repetida")
        urls.add(url)
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


def main() -> int:
    data = json.loads((ROOT / "data" / "events.json").read_text(encoding="utf-8"))
    vocab = set(json.loads((ROOT / "data" / "tags.json").read_text(encoding="utf-8"))["tags"])
    errs = check(data, vocab)
    if errs:
        print("❌ data/events.json tem problemas:")
        print("\n".join(f"  - {e}" for e in errs))
        return 1
    print(f"✅ {len(data['events'])} eventos válidos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
