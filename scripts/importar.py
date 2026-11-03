#!/usr/bin/env python3
"""Importa eventos para data/events.json.

Fontes:
  --url URL            uma página de evento (Luma, Meetup, Sympla, Even3, Eventbrite…)
  --whatsapp ARQUIVO   exportação do chat do WhatsApp (_chat.txt): só os links de eventos são lidos
  --fontes fontes.json calendários iCal e páginas listadas no repositório

Regras:
  - Nunca sobrescreve um campo já preenchido à mão: só completa campos vazios.
  - Eventos passados e fora do Rio (que não sejam online) ficam de fora,
    salvo com --historico: aí a origem do link vale, e o passado fica na agenda.
  - URLs em data/descartados.json não entram de novo.
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

import validar

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


def _descolar_luma(path: str) -> str:
    """Separa «/4cy8s78qBora»: no WhatsApp a palavra seguinte gruda no código."""
    m = re.fullmatch(r"/([a-z0-9]{6,12})([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-Za-zÁÉÍÓÚÂÊÔÃÕÇáéíóúâêôãõç]{2,})", path)
    return "/" + m.group(1) if m else path


def clean_url(url: str) -> str:
    url = url.strip().rstrip(".,;:!?)*]>")
    p = urllib.parse.urlsplit(url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query) if k.lower() not in TRACKING and not k.lower().startswith("utm_")]
    path = p.path.rstrip("/") or "/"
    path = re.sub(r"/checkout.*$", "", path)
    host = p.netloc.lower().replace("lu.ma", "luma.com")
    if host == "luma.com":
        path = _descolar_luma(path)
    return urllib.parse.urlunsplit(("https", host, path, urllib.parse.urlencode(q), ""))


def fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (URLs públicas de eventos)
        charset = r.headers.get_content_charset() or "utf-8"
        return r.read().decode(charset, errors="replace")


def to_iso(value: str | None) -> str | None:
    """Normaliza datas para ISO com fuso -03:00. Datas sem hora ficam AAAA-MM-DD."""
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return v
    # Sympla manda «2026-11-26 08:30:00» (espaço). O fromisoformat do 3.10 exige «T».
    if re.match(r"\d{4}-\d{2}-\d{2} ", v):
        v = v.replace(" ", "T", 1)
    # Doity cola o fuso na hora: «2026-09-15-0300:00» é 15/09 00:00 em -03,
    # e «2026-12-04-0323:59» é 04/12 23:59 em -03.
    colada = re.fullmatch(r"(\d{4}-\d{2}-\d{2})-(\d{2})(\d{2}:\d{2})", v)
    if colada:
        v = f"{colada.group(1)}T{colada.group(3)}:00-{colada.group(2)}:00"
    try:
        d = dt.datetime.fromisoformat(v)
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


def _vazio(v) -> bool:
    return v in (None, "", [], {})


def fill_empty(base: dict, extra: dict) -> dict:
    """Copia de extra só o que base ainda não tem. Não apaga campo preenchido."""
    out = dict(base)
    for k, v in extra.items():
        if _vazio(v) or not _vazio(out.get(k)):
            continue
        out[k] = v
    if out.get("start") and _vazio(base.get("start")):
        out["time_known"] = len(str(out["start"])) > 10
        if _vazio(base.get("status")) or base.get("status") == "a-confirmar":
            out["status"] = "confirmado"
    return out


def next_data(page: str) -> dict | None:
    m = re.search(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', page, re.S | re.I)
    if not m:
        return None
    try:
        data = json.loads(html.unescape(m.group(1).strip()))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _sympla_quando(ev: dict, chave: str) -> str | None:
    multi = ev.get(chave + "MultiFormat")
    if isinstance(multi, dict):
        iso = to_iso(multi.get("ISO8601") if isinstance(multi.get("ISO8601"), str) else None)
        if iso:
            return iso
    bruto = ev.get(chave)
    return to_iso(bruto if isinstance(bruto, str) else None)


def from_sympla_next(page: str, url: str, meta: dict) -> dict | None:
    """Sympla (Next.js) não manda JSON-LD. A data está em __NEXT_DATA__."""
    data = next_data(page)
    if not data:
        return None
    try:
        ev = data["props"]["pageProps"]["hydrationData"]["eventHydration"]["event"]
    except (KeyError, TypeError):
        return None
    if not isinstance(ev, dict) or not (ev.get("name") or ev.get("startDate") or ev.get("startDateMultiFormat")):
        return None

    addr = ev.get("eventsAddress") if isinstance(ev.get("eventsAddress"), dict) else {}
    online = isinstance(ev.get("onlineInfo"), dict) and bool(ev.get("onlineInfo"))
    has_place = bool(addr.get("name") or addr.get("city"))
    if online and has_place:
        fmt = "hibrido"
    elif online:
        fmt = "online"
    else:
        fmt = "presencial"
    num = str(addr.get("addressNum") or "").strip()
    street = str(addr.get("address") or "").strip()
    if street and num:
        address = f"{street}, {num}"
    else:
        address = street or None
    images = ev.get("images") if isinstance(ev.get("images"), dict) else {}
    image = images.get("logoLarge") or images.get("logoUrl") or ev.get("logoUrl") or meta.get("og:image")
    host = ev.get("eventsHost") if isinstance(ev.get("eventsHost"), dict) else {}
    title = html.unescape(str(ev.get("name") or meta.get("og:title") or "")).strip()
    desc = short(ev.get("detail") or ev.get("strippedDetail") or meta.get("og:description"))
    start = _sympla_quando(ev, "startDate")
    kind = str(ev.get("paymentEventType") or "").lower()
    if kind in {"free", "gratis", "gratuit"}:
        cost = {"type": "gratis", "text": "Grátis"}
        reg = "inscricao"
    elif kind == "paid":
        cost = {"type": "pago", "text": None}
        reg = "ingresso"
    else:
        cost = {"type": "desconhecido", "text": None}
        reg = "inscricao"
    return {
        "title": title,
        "start": start,
        "end": _sympla_quando(ev, "endDate"),
        "time_known": bool(start and len(start) > 10),
        "venue": addr.get("name") or None,
        "address": address,
        "city": addr.get("city") or None,
        "format": fmt,
        "cost": cost,
        "registration": reg,
        "url": url,
        "image": image,
        "organizer": host.get("name") or None,
        "description": {"pt": desc} if desc else {},
        "tags": auto_tags(" ".join(filter(None, [title, desc or ""]))),
        "status": "confirmado" if start else "a-confirmar",
    }


def from_luma_next(page: str, url: str, meta: dict) -> dict | None:
    """Luma às vezes não manda JSON-LD. A data fica em initialData.data.event.start_at."""
    data = next_data(page)
    if not data:
        return None
    try:
        bloco = data["props"]["pageProps"]["initialData"]["data"]
        ev = bloco["event"]
    except (KeyError, TypeError):
        return None
    if not isinstance(ev, dict) or not (ev.get("name") or ev.get("start_at")):
        return None
    geo = ev.get("geo_address_info") if isinstance(ev.get("geo_address_info"), dict) else {}
    loc = str(ev.get("location_type") or "").lower()
    tem_lugar = bool(geo.get("city") or geo.get("address"))
    if loc in {"", "offline"}:
        fmt = "presencial"
    elif tem_lugar:
        fmt = "hibrido"
    else:
        fmt = "online"
    tickets = bloco.get("ticket_types") if isinstance(bloco.get("ticket_types"), list) else []
    tipos = [str(t.get("type") or "").lower() for t in tickets if isinstance(t, dict)]
    cents = [t.get("cents") for t in tickets if isinstance(t, dict) and isinstance(t.get("cents"), (int, float))]
    approval = any(isinstance(t, dict) and t.get("require_approval") for t in tickets)
    if any(c > 0 for c in cents) or "paid" in tipos:
        cost = {"type": "pago", "text": None}
        reg = "ingresso"
    elif "free" in tipos:
        cost = {"type": "gratis", "text": "Grátis"}
        reg = "aprovacao" if approval else "inscricao"
    else:
        cost = {"type": "desconhecido", "text": None}
        reg = "inscricao"
    hosts = bloco.get("hosts") if isinstance(bloco.get("hosts"), list) else []
    org = next((h.get("name") for h in hosts if isinstance(h, dict) and h.get("name")), None)
    title = html.unescape(str(ev.get("name") or meta.get("og:title") or "")).strip()
    desc = short(meta.get("og:description"))
    start = to_iso(ev.get("start_at") if isinstance(ev.get("start_at"), str) else None)
    venue = geo.get("address") or None
    rua = geo.get("short_address") or None
    if rua and venue and rua == venue:
        rua = None
    return {
        "title": title,
        "start": start,
        "end": to_iso(ev.get("end_at") if isinstance(ev.get("end_at"), str) else None),
        "time_known": bool(start and len(start) > 10),
        "venue": venue,
        "address": rua,
        "city": geo.get("city") or None,
        "format": fmt,
        "cost": cost,
        "registration": reg,
        "url": url,
        "image": ev.get("cover_url") or meta.get("og:image"),
        "organizer": org,
        "description": {"pt": desc} if desc else {},
        "tags": auto_tags(" ".join(filter(None, [title, desc or ""]))),
        "status": "confirmado" if start else "a-confirmar",
    }


def _completar(base: dict | None, extra: dict | None) -> dict | None:
    if base and extra:
        return fill_empty(base, extra)
    return base or extra


def event_from_page(page: str, url: str) -> dict | None:
    url = clean_url(url)
    meta = meta_tags(page)
    evs = jsonld_events(page)
    base = from_jsonld(evs[0], url, meta) if evs else None
    extra = _completar(from_sympla_next(page, url, meta), from_luma_next(page, url, meta))
    pronto = _completar(base, extra)
    if pronto:
        return pronto
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


def event_from_url(url: str) -> dict | None:
    url = clean_url(url)
    return event_from_page(fetch(url), url)


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
RODAPE = "Para descartar um evento, acrescente a URL dele em data/descartados.json neste mesmo PR."

RIO_CITY = re.compile(
    r"rio de janeiro|\brj\b|niter[oó]i|duque de caxias|nova igua[cç]u|petr[oó]polis",
    re.I,
)


def key_of(e: dict) -> tuple:
    return (e.get("url") or "").lower(), slug(e.get("title") or ""), (e.get("start") or "")[:10]


def cidade_rio(city: str | None) -> bool:
    return bool(city and RIO_CITY.search(city))


def _palavras_tech() -> list[str]:
    tags = json.loads(TAGS.read_text(encoding="utf-8"))["tags"]
    words: set[str] = set()
    for tid, labels in tags.items():
        words.add(str(tid).lower())
        words.add(str(tid).lower().replace("-", " "))
        if isinstance(labels, dict):
            for lab in labels.values():
                texto = str(lab).strip().lower()
                if texto:
                    words.add(texto)
    return [w for w in words if w]


def _sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def parece_tech(ev: dict) -> bool:
    """Há alguma palavra do vocabulário de tags no título ou na descrição.

    «Empreendedor» conta como «empreendedorismo»: um termo de 6+ letras
    vale se for prefixo do outro. Palavras curtas («ia», «web») continuam
    exigindo a palavra inteira, para não casar no meio de outra.
    """
    partes = [ev.get("title") or ""]
    desc = ev.get("description") or {}
    if isinstance(desc, dict):
        partes.extend(str(v) for v in desc.values() if v)
    elif isinstance(desc, str):
        partes.append(desc)
    texto = _sem_acento(" ".join(partes))
    tokens = re.findall(r"[a-z0-9]+", texto)
    for palavra in _palavras_tech():
        w = _sem_acento(palavra)
        if not w:
            continue
        if re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", texto):
            return True
        if len(w) >= 6:
            for tok in tokens:
                if len(tok) >= 6 and (tok.startswith(w) or w.startswith(tok)):
                    return True
    return False


def bloco_novo(ev: dict, url: str) -> str:
    lugar = " · ".join(p for p in (ev.get("venue"), ev.get("address"), ev.get("city")) if p) or "—"
    fonte = ev.get("source") or urllib.parse.urlsplit(ev.get("url") or url or "").netloc.replace("www.", "") or "—"
    tags = ", ".join(ev.get("tags") or []) or "—"
    linhas = [
        f"### {ev.get('title') or 'Sem título'}",
        "",
        f"- Data: {(ev.get('start') or 'sem data')[:16]}",
        f"- Lugar: {lugar}",
        f"- Fonte: {fonte}",
        f"- Link: {ev.get('url') or url}",
        f"- Tags: {tags}",
    ]
    avisos = []
    if not parece_tech(ev):
        avisos.append("não parece tech")
    if not cidade_rio(ev.get("city")):
        avisos.append("cidade não é Rio")
    if avisos:
        linhas.append("- ⚠️ revisar: " + "; ".join(avisos))
    return "\n".join(linhas)


def _mesmo_evento(new: dict, e: dict, historico: bool) -> bool:
    chave = validar.url_chave(new.get("url") or "")
    if chave and chave == validar.url_chave(e.get("url") or ""):
        return True
    if historico:
        return False
    _, title, day = key_of(new)
    _, et, ed = key_of(e)
    return bool(et == title and ed == day and day)


def _id_livre(existing: list[dict], start: str, title: str, url: str) -> str:
    base = f"{start[:10]}-{slug(title or 'evento')}"
    usados = {e.get("id") for e in existing}
    if base not in usados:
        return base
    extra = slug(urllib.parse.urlsplit(url or "").path)[:20] or "2"
    cand = f"{base}-{extra}"
    n = 2
    while cand in usados:
        cand = f"{base}-{extra}-{n}"
        n += 1
    return cand


def unicos_por_chave(urls: list[str]) -> list[str]:
    """Uma entrada por URL canônica. A query não cria um segundo evento."""
    out: list[str] = []
    vistos: set[str] = set()
    for url in urls:
        chave = validar.url_chave(url)
        if chave in vistos:
            continue
        vistos.add(chave)
        out.append(url)
    return out


def merge(existing: list[dict], new: dict, today: dt.date, descartadas: set[str] | None = None, historico: bool = False) -> str:
    """Devolve 'novo', 'completado', 'igual', 'descartado' ou o motivo de ter ficado de fora.

    Com historico=True, evento passado e evento de outra cidade entram.
    Não há corte por idade (nem de 3 meses). Campo preenchido não é trocado.
    """
    if descartadas is None:
        descartadas = validar.chaves_descartadas()
    if not new.get("title"):
        return "sem título"
    if validar.url_chave(new.get("url") or "") in descartadas:
        return "descartado"
    start = new.get("start")
    if not start:
        return "sem data na página (adicione à mão)"
    end = (new.get("end") or start)[:10]
    try:
        fim = dt.date.fromisoformat(end)
    except ValueError:
        fim = dt.date.fromisoformat(start[:10])
    if not historico and fim < today:
        return "passado"
    for e in existing:
        if _mesmo_evento(new, e, historico):
            changed = False
            for k, v in new.items():
                if v in (None, "", [], {}):
                    continue
                if e.get(k) in (None, "", [], {}):
                    e[k] = v
                    changed = True
            return "completado" if changed else "igual"

    if not historico and new.get("format") != "online" and (new.get("city") or "") and not cidade_rio(new.get("city")):
        return "fora do Rio"
    new = dict(new)
    new["city"] = new.get("city") or "Rio de Janeiro"
    if new.get("end") and str(new["end"])[:10] < start[:10]:
        new["end"] = None

    new["id"] = _id_livre(existing, start, new["title"], new.get("url") or "")
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
    ap.add_argument("--historico", action="store_true",
                    help="guarda passados e qualquer cidade; não corta eventos com mais de 3 meses")
    ap.add_argument("--fontes", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="não grava data/events.json")
    ap.add_argument("--relatorio", type=Path, help="grava um resumo em Markdown (corpo do PR)")
    args = ap.parse_args(argv)

    today = dt.datetime.now(RIO).date()
    data = json.loads(EVENTS.read_text(encoding="utf-8"))
    events = data["events"]
    report: list[str] = []
    descartadas = validar.chaves_descartadas()

    urls = list(args.url)
    if args.whatsapp:
        since = dt.date.fromisoformat(args.desde) if args.desde else None
        found = whatsapp_links(args.whatsapp, since)
        report.append(f"WhatsApp: {len(found)} links de eventos encontrados.")
        urls += found
    urls = unicos_por_chave(urls)

    candidates: list[tuple[str, dict | None, str | None]] = []
    for i, u in enumerate(urls, 1):
        print(f"… {i}/{len(urls)} {u}", file=sys.stderr)
        if validar.url_chave(u) in descartadas:
            candidates.append((u, None, "descartado"))
            continue
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
                    if validar.url_chave(f["url"]) in descartadas:
                        candidates.append((f["url"], None, "descartado"))
                    else:
                        candidates.append((f["url"], event_from_url(f["url"]), None))
            except Exception as exc:  # noqa: BLE001
                report.append(f"⚠️ Fonte «{f.get('nome')}» falhou: {exc.__class__.__name__}")

    counts: dict[str, int] = {}
    for url, ev, err in candidates:
        if err:
            result = err
        elif ev is not None and validar.url_chave(ev.get("url") or "") in descartadas:
            result = "descartado"
        elif ev is None:
            result = "sem dados de evento"
        else:
            result = merge(events, ev, today, descartadas, historico=args.historico)
        counts[result] = counts.get(result, 0) + 1
        if result == "novo":
            report.append(bloco_novo(ev, url))
            report.append("")
        elif result == "completado":
            report.append(f"- **completado**: [{ev['title']}]({ev.get('url') or url}) · {(ev.get('start') or 'sem data')[:16]}")
        elif result not in ("igual", "passado"):
            report.append(f"- {result}: {url}")

    events.sort(key=lambda e: e.get("start") or "9999")
    data["updated"] = today.isoformat()
    summary = " · ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "nada a importar"
    report.insert(0, f"Resumo: {summary}")

    if not args.dry_run and (counts.get("novo") or counts.get("completado")):
        EVENTS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.relatorio:
        args.relatorio.write_text(
            "\n".join(report).rstrip() + "\n\nRevise datas, preço e tags antes de aprovar.\n" + RODAPE + "\n",
            encoding="utf-8",
        )
    print("\n".join(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
