#!/usr/bin/env python3
"""Importa eventos para data/events.json.

Fontes:
  --url URL            uma página de evento (Luma, Meetup, Sympla, Even3, Eventbrite…)
  --whatsapp ARQUIVO   exportação do chat do WhatsApp (_chat.txt): só os links de eventos são lidos
  --fontes fontes.json calendários iCal e páginas listadas no repositório

Regras:
  - Nunca sobrescreve um campo já preenchido à mão: só completa campos vazios.
  - Eventos passados e fora do Rio (que não sejam online) ficam de fora.
  - Do WhatsApp só se guardam links: nada de nomes, telefones ou mensagens.

Só usa a biblioteca padrão do Python (3.10+).
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "data" / "events.json"
TAGS = ROOT / "data" / "tags.json"
RIO = dt.timezone(dt.timedelta(hours=-3))
UA = "Mozilla/5.0 (compatible; AgendaRioTech/1.0; +https://github.com)"

EVENT_HOSTS = re.compile(
    r"(luma\.com|lu\.ma|meetup\.com|sympla\.com\.br|even3\.com\.br|doity\.com\.br|eventbrite\.[a-z.]+|"
    r"gdg\.community\.dev|usergroups\.databricks\.com)",
    re.I,
)
TRACKING = {"tk", "fbclid", "gclid", "ref", "src"}

# Palavras-chave → tags do vocabulário (data/tags.json)
KEYWORDS = [
    (r"\b(ia|ai|intelig[eê]ncia artificial|llm|gpt|claude|agentes?|machine learning|genai)\b", "ia"),
    (r"\bpython|pyladies|django|fastapi\b", "python"),
    (r"\b(react|javascript|typescript|frontend|front-end|wordpress|web)\b", "web"),
    (r"\b(android|ios|flutter|mobile)\b", "mobile"),
    (r"\b(dados|data|analytics|databricks|sql)\b", "dados"),
    (r"\b(aws|azure|gcp|cloud|kubernetes|docker)\b", "cloud"),
    (r"\b(devops|sre|ci/cd)\b", "devops"),
    (r"\b(seguran[cç]a|security|cyber|ciberseguran[cç]a)\b", "seguranca"),
    (r"\b(web3|blockchain|cripto|crypto|solana|ethereum|defi)\b", "web3"),
    (r"\b(game|games|jogos)\b", "games"),
    (r"\b(design|ux|ui)\b", "design"),
    (r"\b(produto|product)\b", "produto"),
    (r"\bstartups?\b", "startups"),
    (r"\b(investidor(es)?|investimento|venture|vc|anjo|angel)\b", "investimento"),
    (r"\b(founders?|fundador(es|as)?)\b", "founders"),
    (r"\bempreend", "empreendedorismo"),
    (r"\b(inova[cç][aã]o|innovation)\b", "inovacao"),
    (r"\b(networking|happy hour|meet & greet)\b", "networking"),
    (r"\b(confer[eê]ncia|summit|congresso|festival|devfest)\b", "conferencia"),
    (r"\bmeetup\b", "meetup"),
    (r"\b(workshop|oficina|imers[aã]o|bootcamp|hands-on)\b", "workshop"),
    (r"\b(hackathon|hackaton|game jam)\b", "hackathon"),
    (r"\b(palestra|talk|keynote|painel)\b", "palestra"),
    (r"\b(carreira|vagas|career|mentoria)\b", "carreira"),
    (r"\b(comunidade|community)\b", "comunidade"),
    (r"\b(impacto social|favela|periferia)\b", "impacto-social"),
    (r"\b(mulheres|women|diversidade|lgbt|pretos?|negras?)\b", "diversidade"),
    (r"\b(open source|c[oó]digo aberto)\b", "open-source"),
]


# ---------------------------------------------------------------- utilidades
def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:48]


def clean_url(url: str) -> str:
    url = url.strip().rstrip(".,;:!?)*]>")
    p = urllib.parse.urlsplit(url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query) if k.lower() not in TRACKING and not k.lower().startswith("utm_")]
    path = p.path.rstrip("/") or "/"
    path = re.sub(r"/checkout.*$", "", path)
    return urllib.parse.urlunsplit(("https", p.netloc.lower().replace("lu.ma", "luma.com"), path, urllib.parse.urlencode(q), ""))


def fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (URLs públicas de eventos)
        charset = r.headers.get_content_charset() or "utf-8"
        return r.read().decode(charset, errors="replace")


def to_iso(value: str | None) -> str | None:
    """Normaliza datas para ISO com fuso -03:00. Datas sem hora ficam AAAA-MM-DD."""
    if not value:
        return None
    v = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return v
    try:
        d = dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=RIO)
    return d.astimezone(RIO).replace(microsecond=0).isoformat()


def auto_tags(text: str, limit: int = 5) -> list[str]:
    vocab = set(json.loads(TAGS.read_text(encoding="utf-8"))["tags"])
    low = text.lower()
    found: list[str] = []
    for pat, tag in KEYWORDS:
        if tag in vocab and tag not in found and re.search(pat, low):
            found.append(tag)
    return found[:limit] or ["comunidade"]


def short(text: str | None, n: int = 220) -> str | None:
    if not text:
        return None
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()
    return t if len(t) <= n else t[: n - 1].rsplit(" ", 1)[0] + "…"


# ------------------------------------------------------------ páginas web
def jsonld_events(page: str) -> list[dict]:
    out: list[dict] = []
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(html.unescape(m.group(1).strip()))
        except json.JSONDecodeError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue
            if "@graph" in item:
                stack.extend(item["@graph"])
            types = item.get("@type")
            types = types if isinstance(types, list) else [types]
            if any(isinstance(x, str) and x.endswith("Event") for x in types):
                out.append(item)
    return out


def meta_tags(page: str) -> dict:
    meta = {}
    for m in re.finditer(r"<meta\s+([^>]+)>", page, re.I):
        attrs = dict(re.findall(r'([\w:-]+)\s*=\s*["\']([^"\']*)["\']', m.group(1)))
        key = attrs.get("property") or attrs.get("name")
        if key and "content" in attrs:
            meta[key.lower()] = html.unescape(attrs["content"])
    return meta


def first(x):
    if isinstance(x, list):
        return x[0] if x else None
    return x


def from_jsonld(ld: dict, url: str, meta: dict) -> dict:
    loc = first(ld.get("location")) or {}
    venue = address = city = None
    fmt = "presencial"
    mode = str(ld.get("eventAttendanceMode", ""))
    if "Online" in mode:
        fmt = "online"
    elif "Mixed" in mode:
        fmt = "hibrido"
    if isinstance(loc, dict):
        if loc.get("@type") == "VirtualLocation":
            fmt = "online" if fmt == "presencial" else fmt
        venue = loc.get("name")
        a = loc.get("address")
        if isinstance(a, dict):
            address = a.get("streetAddress")
            city = a.get("addressLocality")
        elif isinstance(a, str):
            address = a
    elif isinstance(loc, str):
        venue = loc

    offers = first(ld.get("offers")) or {}
    price = None
    if isinstance(offers, dict):
        price = offers.get("price", offers.get("lowPrice"))
    try:
        price_f = float(price) if price not in (None, "") else None
    except (TypeError, ValueError):
        price_f = None
    if price_f == 0:
        cost = {"type": "gratis", "text": "Grátis"}
        reg = "inscricao"
    elif price_f:
        cost = {"type": "pago", "text": f"R$ {price_f:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")}
        reg = "ingresso"
    else:
        cost = {"type": "desconhecido", "text": None}
        reg = "inscricao"

    image = first(ld.get("image"))
    if isinstance(image, dict):
        image = image.get("url")
    org = first(ld.get("organizer"))
    if isinstance(org, dict):
        org = org.get("name")

    title = html.unescape(ld.get("name") or meta.get("og:title") or "").strip()
    desc = short(ld.get("description") or meta.get("og:description"))
    start = to_iso(ld.get("startDate"))
    return {
        "title": title,
        "start": start,
        "end": to_iso(ld.get("endDate")),
        "time_known": bool(start and len(start) > 10),
        "venue": venue,
        "address": address,
        "city": city,
        "format": fmt,
        "cost": cost,
        "registration": reg,
        "url": url,
        "image": image or meta.get("og:image"),
        "organizer": org,
        "description": {"pt": desc} if desc else {},
        "tags": auto_tags(" ".join(filter(None, [title, desc or ""]))),
        "status": "confirmado" if start else "a-confirmar",
    }


def event_from_url(url: str) -> dict | None:
    url = clean_url(url)
    page = fetch(url)
    meta = meta_tags(page)
    evs = jsonld_events(page)
    if evs:
        return from_jsonld(evs[0], url, meta)
    if meta.get("og:title"):
        # Sem dados estruturados: entra como «a confirmar» e sem data, para revisão no PR.
        return {
            "title": meta["og:title"], "start": None, "end": None, "time_known": False,
            "venue": None, "address": None, "city": "Rio de Janeiro", "format": "presencial",
            "cost": {"type": "desconhecido", "text": None}, "registration": "inscricao", "url": url,
            "image": meta.get("og:image"), "organizer": None,
            "description": {"pt": short(meta.get("og:description"))} if meta.get("og:description") else {},
            "tags": auto_tags(meta["og:title"] + " " + (meta.get("og:description") or "")),
            "status": "a-confirmar",
        }
    return None


# ------------------------------------------------------------------ iCal
def ics_events(text: str) -> list[dict]:
    text = re.sub(r"\r?\n[ \t]", "", text)  # desdobra linhas
    out = []
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        f: dict[str, tuple[dict, str]] = {}
        for line in block.strip().splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            name, *params = k.split(";")
            f[name.upper()] = (dict(p.split("=", 1) for p in params if "=" in p), v)

        def val(k):
            return f.get(k, ({}, None))[1]

        def ics_date(k):
            params, v = f.get(k, ({}, None))
            if not v:
                return None
            if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", v):
                return f"{v[:4]}-{v[4:6]}-{v[6:8]}"
            d = dt.datetime.strptime(v.rstrip("Z"), "%Y%m%dT%H%M%S")
            d = d.replace(tzinfo=dt.timezone.utc) if v.endswith("Z") else d.replace(tzinfo=RIO)
            return d.astimezone(RIO).isoformat()

        def unesc(s):
            return s.replace("\\n", " ").replace("\\,", ",").replace("\\;", ";") if s else s

        summary = unesc(val("SUMMARY")) or ""
        desc = unesc(val("DESCRIPTION"))
        url = val("URL") or (re.search(r"https?://\S+", desc or "") or [None])[0]
        start = ics_date("DTSTART")
        loc = unesc(val("LOCATION"))
        online = bool(loc and re.search(r"https?://|zoom|meet\.google|online", loc, re.I))
        out.append({
            "title": summary, "start": start, "end": ics_date("DTEND"),
            "time_known": bool(start and len(start) > 10),
            "venue": None if online else loc, "address": None, "city": "Rio de Janeiro",
            "format": "online" if online else "presencial",
            "cost": {"type": "desconhecido", "text": None}, "registration": "inscricao",
            "url": clean_url(url) if url else None, "image": None, "organizer": None,
            "description": {"pt": short(desc)} if desc else {},
            "tags": auto_tags(summary + " " + (desc or "")),
            "status": "confirmado" if start else "a-confirmar",
        })
    return out


# -------------------------------------------------------------- WhatsApp
def whatsapp_links(path: Path, since: dt.date | None = None) -> list[str]:
    """Só devolve links de plataformas de eventos. Não guarda autor nem texto."""
    links: list[str] = []
    seen = set()
    current: dt.date | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"‎?\[(\d{2})[./](\d{2})[./](\d{2,4}),", line)
        if m:
            d, mo, y = m.groups()
            y = int(y) + (2000 if len(y) == 2 else 0)
            try:
                current = dt.date(y, int(mo), int(d))
            except ValueError:
                current = None
        if since and current and current < since:
            continue
        for u in re.findall(r"https?://\S+", line):
            if EVENT_HOSTS.search(u):
                cu = clean_url(u)
                if cu not in seen:
                    seen.add(cu)
                    links.append(cu)
    return links


# ------------------------------------------------------------------ mescla
def key_of(e: dict) -> tuple:
    return (e.get("url") or "").lower(), slug(e.get("title") or ""), (e.get("start") or "")[:10]


def merge(existing: list[dict], new: dict, today: dt.date) -> str:
    """Devolve 'novo', 'completado', 'igual' ou o motivo de ter ficado de fora."""
    if not new.get("title"):
        return "sem título"
    start = new.get("start")
    if not start:
        return "sem data na página (adicione à mão)"
    end = (new.get("end") or start)[:10]
    if dt.date.fromisoformat(end) < today:
        return "passado"
    url, title, day = key_of(new)
    for e in existing:
        eu, et, ed = key_of(e)
        if (url and eu == url) or (et == title and ed == day and day):
            changed = False
            for k, v in new.items():
                if v in (None, "", [], {}):
                    continue
                if e.get(k) in (None, "", [], {}):
                    e[k] = v
                    changed = True
            return "completado" if changed else "igual"

    city = (new.get("city") or "").lower()
    if new.get("format") != "online" and city and not re.search(r"rio de janeiro|\brj\b|niter[oó]i|duque de caxias|nova igua[cç]u|petr[oó]polis", city):
        return "fora do Rio"
    new = dict(new)
    new["city"] = new.get("city") or "Rio de Janeiro"

    new["id"] = f"{start[:10]}-{slug(new['title'])}"
    new["source"] = new.get("source") or urllib.parse.urlsplit(new.get("url") or "").netloc.replace("www.", "")
    new["added"] = today.isoformat()
    existing.append(new)
    return "novo"


# -------------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", action="append", default=[])
    ap.add_argument("--whatsapp", type=Path)
    ap.add_argument("--desde", help="AAAA-MM-DD: só links do WhatsApp a partir desta data")
    ap.add_argument("--fontes", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="não grava data/events.json")
    ap.add_argument("--relatorio", type=Path, help="grava um resumo em Markdown (corpo do PR)")
    args = ap.parse_args(argv)

    today = dt.datetime.now(RIO).date()
    data = json.loads(EVENTS.read_text(encoding="utf-8"))
    events = data["events"]
    report: list[str] = []

    urls = list(args.url)
    if args.whatsapp:
        since = dt.date.fromisoformat(args.desde) if args.desde else None
        found = whatsapp_links(args.whatsapp, since)
        report.append(f"WhatsApp: {len(found)} links de eventos encontrados.")
        urls += found

    candidates: list[tuple[str, dict | None, str | None]] = []
    for u in urls:
        try:
            candidates.append((u, event_from_url(u), None))
        except Exception as exc:  # noqa: BLE001
            candidates.append((u, None, f"erro ao abrir: {exc.__class__.__name__}"))

    if args.fontes:
        for f in json.loads(args.fontes.read_text(encoding="utf-8")).get("fontes", []):
            if f.get("ativo") is False:
                continue
            try:
                if f["tipo"] == "ics":
                    for ev in ics_events(fetch(f["url"])):
                        ev["source"] = f.get("nome")
                        candidates.append((ev.get("url") or f["url"], ev, None))
                elif f["tipo"] == "url":
                    candidates.append((f["url"], event_from_url(f["url"]), None))
            except Exception as exc:  # noqa: BLE001
                report.append(f"⚠️ Fonte «{f.get('nome')}» falhou: {exc.__class__.__name__}")

    counts: dict[str, int] = {}
    for url, ev, err in candidates:
        result = err or ("sem dados de evento" if ev is None else merge(events, ev, today))
        counts[result] = counts.get(result, 0) + 1
        if result in ("novo", "completado"):
            report.append(f"- **{result}**: [{ev['title']}]({ev.get('url') or url}) · {(ev.get('start') or 'sem data')[:16]}")
        elif result not in ("igual", "passado"):
            report.append(f"- {result}: {url}")

    events.sort(key=lambda e: e.get("start") or "9999")
    data["updated"] = today.isoformat()
    summary = " · ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "nada a importar"
    report.insert(0, f"Resumo: {summary}")

    if not args.dry_run and (counts.get("novo") or counts.get("completado")):
        EVENTS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.relatorio:
        args.relatorio.write_text("\n".join(report) + "\n\nRevise datas, preço e tags antes de aprovar.\n", encoding="utf-8")
    print("\n".join(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
