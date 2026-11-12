#!/usr/bin/env python3
"""Valida data/events.json, data/descartados.json e os YAML de .github.

Roda em todo PR (GitHub Actions) e localmente:

    python scripts/validar.py

Os .yml de .github são lidos por um subconjunto de YAML da biblioteca padrão
(mapas, listas, escalares e âncoras). A checagem não depende de PyYAML.
"""
from __future__ import annotations

import copy
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
IDIOMAS = {"pt", "en", "es", "multi"}
DIAS_RRULE = {"MO", "TU", "WE", "TH", "FR", "SA", "SU"}
RIO = dt.timezone(dt.timedelta(hours=-3))
REQUIRED = ["id", "title", "start", "format", "cost", "registration", "url", "tags"]
DESCARTADOS = ROOT / "data" / "descartados.json"
ROLES = ROOT / "data" / "roles.json"
FIXOS = ROOT / "data" / "roles_fixos.json"
TAGS_ROLES = ROOT / "data" / "tags_roles.json"


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


def instante(valor: str, fim_do_dia: bool = False) -> dt.datetime | None:
    """Data ISO. Dia sem hora vale o começo do dia, ou o fim se for o término."""
    if len(valor) == 10:
        hora = "23:59:59" if fim_do_dia else "00:00:00"
        return dt.datetime.fromisoformat(f"{valor}T{hora}").replace(tzinfo=RIO)
    try:
        quando = dt.datetime.fromisoformat(valor)
    except ValueError:
        return None
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=RIO)
    return quando


def termina_antes(evento: dict) -> bool:
    """True se o fim é anterior ou igual ao início.

    Um fim na madrugada do dia seguinte (cruza a meia-noite) não conta:
    o instante do fim ainda é depois do começo.
    """
    inicio, fim = evento.get("start"), evento.get("end")
    if not isinstance(inicio, str) or not isinstance(fim, str):
        return False
    a, b = instante(inicio, False), instante(fim, True)
    if a is None or b is None:
        return False
    return b <= a


def erro_rrule(rrule: str) -> str | None:
    """Aceita só FREQ=WEEKLY ou MONTHLY, com BYDAY. INTERVAL é opcional."""
    if not isinstance(rrule, str) or not rrule.strip():
        return "falta «rrule»"
    partes: dict[str, str] = {}
    for pedaco in rrule.split(";"):
        if "=" not in pedaco:
            return "rrule inválida"
        chave, valor = pedaco.split("=", 1)
        if chave in partes:
            return f"rrule com «{chave}» repetido"
        partes[chave] = valor
    sobra = set(partes) - {"FREQ", "BYDAY", "INTERVAL"}
    if sobra:
        return "rrule só pode ter FREQ, BYDAY e INTERVAL"
    if partes.get("FREQ") not in {"WEEKLY", "MONTHLY"}:
        return "FREQ precisa ser WEEKLY ou MONTHLY"
    if "BYDAY" not in partes or not partes["BYDAY"]:
        return "falta BYDAY"
    if "INTERVAL" in partes and not re.fullmatch(r"[1-9][0-9]*", partes["INTERVAL"]):
        return "INTERVAL inválido"
    for token in partes["BYDAY"].split(","):
        if partes["FREQ"] == "WEEKLY":
            if token not in DIAS_RRULE:
                return f"BYDAY inválido ({token})"
        elif not re.fullmatch(r"([+-]?[1-5])?(MO|TU|WE|TH|FR|SA|SU)", token):
            return f"BYDAY inválido ({token})"
    return None


def _vocab_roles() -> tuple[set[str], set[str]]:
    dados = json.loads(TAGS_ROLES.read_text(encoding="utf-8"))
    tags = set(dados.get("tags") or {})
    categorias = {c.get("id") for c in dados.get("categories") or [] if isinstance(c, dict)}
    return tags, categorias


def erros_extras_roles(eventos: list, categorias: set[str]) -> list[str]:
    """Campos opcionais da Rolês e fim que cruza a meia-noite."""
    errs: list[str] = []
    for i, evento in enumerate(eventos):
        if not isinstance(evento, dict):
            continue
        onde = f"evento {i + 1} ({evento.get('id') or evento.get('title') or '?'})"
        if termina_antes(evento):
            errs.append(f"{onde}: termina antes de começar")
        categoria = evento.get("categoria")
        if categoria is not None and categoria not in categorias:
            errs.append(f"{onde}: categoria fora da lista ({categoria})")
        idioma = evento.get("idioma")
        if idioma is not None and idioma not in IDIOMAS:
            errs.append(f"{onde}: idioma deve ser um de {sorted(IDIOMAS)}")
        idade = evento.get("idade_minima")
        if idade is not None and (not isinstance(idade, int) or isinstance(idade, bool) or idade < 0):
            errs.append(f"{onde}: idade_minima precisa ser um número")
        bairro = evento.get("bairro")
        if bairro is not None and not str(bairro).strip():
            errs.append(f"{onde}: bairro vazio")
        urls = evento.get("urls")
        if urls is not None:
            if not isinstance(urls, list):
                errs.append(f"{onde}: urls precisa ser uma lista")
            else:
                for url in urls:
                    if not str(url).startswith("https://"):
                        errs.append(f"{onde}: url extra precisa começar com https://")
    return errs


def erros_fixos(dados: dict, vocab: set[str], categorias: set[str]) -> list[str]:
    errs: list[str] = []
    if not isinstance(dados, dict):
        return ["data/roles_fixos.json precisa ser um objeto"]
    if not isinstance(dados.get("events"), list):
        return ["data/roles_fixos.json precisa de uma lista «events»"]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(dados.get("updated", ""))):
        errs.append("data/roles_fixos.json: «updated» precisa ser AAAA-MM-DD")
    ids: set[str] = set()
    for i, evento in enumerate(dados["events"]):
        onde = f"fixo {i + 1} ({evento.get('id') or evento.get('title') or '?'})"
        if not isinstance(evento, dict):
            errs.append(f"{onde}: precisa ser um objeto")
            continue
        for campo in ("id", "title", "rrule", "time", "format", "cost", "registration", "url", "fonte", "verificado_em", "tags"):
            if evento.get(campo) in (None, "", []):
                errs.append(f"{onde}: falta «{campo}»")
        if evento.get("id") in ids:
            errs.append(f"{onde}: id repetido")
        if evento.get("id"):
            ids.add(evento["id"])
        problema = erro_rrule(str(evento.get("rrule") or ""))
        if problema and evento.get("rrule"):
            errs.append(f"{onde}: {problema}")
        elif not evento.get("rrule"):
            pass
        if not re.fullmatch(r"\d{2}:\d{2}", str(evento.get("time") or "")):
            if evento.get("time"):
                errs.append(f"{onde}: «time» precisa ser HH:MM")
        fim = evento.get("end_time")
        if fim is not None and not re.fullmatch(r"\d{2}:\d{2}", str(fim)):
            errs.append(f"{onde}: «end_time» precisa ser HH:MM")
        if not str(evento.get("fonte") or "").startswith("https://"):
            if evento.get("fonte"):
                errs.append(f"{onde}: «fonte» precisa ser uma URL https://")
        if not str(evento.get("url") or "").startswith("https://"):
            if evento.get("url"):
                errs.append(f"{onde}: a url precisa começar com https://")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(evento.get("verificado_em") or "")):
            if evento.get("verificado_em"):
                errs.append(f"{onde}: «verificado_em» precisa ser AAAA-MM-DD")
        if evento.get("format") not in FORMATS:
            errs.append(f"{onde}: format deve ser um de {sorted(FORMATS)}")
        if (evento.get("cost") or {}).get("type") not in COSTS:
            errs.append(f"{onde}: cost.type deve ser um de {sorted(COSTS)}")
        if evento.get("registration") not in REGS:
            errs.append(f"{onde}: registration deve ser um de {sorted(REGS)}")
        ruins = [t for t in evento.get("tags", []) if t not in vocab]
        if ruins:
            errs.append(f"{onde}: tags fora do vocabulário {ruins}")
        categoria = evento.get("categoria")
        if categoria not in categorias:
            errs.append(f"{onde}: categoria fora da lista ({categoria})")
        # end_time anterior ao time é a madrugada seguinte, não um erro.
        if fim and evento.get("time") and str(fim) <= str(evento.get("time")):
            pass
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


class YamlError(Exception):
    """YAML fora do subconjunto aceito, ou sintaxe inválida."""

    def __init__(self, message: str, line: int | None = None):
        self.line = line
        if line:
            super().__init__(f"linha {line}: {message}")
        else:
            super().__init__(message)


_BOOL_TRUE = {"true", "True", "TRUE", "yes", "Yes", "YES", "on", "On", "ON"}
_BOOL_FALSE = {"false", "False", "FALSE", "no", "No", "NO", "off", "Off", "OFF"}
_NULL = {"null", "Null", "NULL", "~"}


def _coerce_scalar(text: str):
    """Escalares simples no mesmo sentido do YAML 1.1 que o PyYAML lia."""
    if text in _BOOL_TRUE:
        return True
    if text in _BOOL_FALSE:
        return False
    if text in _NULL:
        return None
    if re.fullmatch(r"-?(0|[1-9][0-9]*)", text):
        return int(text)
    if re.fullmatch(r"-?(0|[1-9][0-9]*)\.[0-9]+", text):
        return float(text)
    return text


def _strip_plain_comment(text: str) -> str:
    for i, ch in enumerate(text):
        if ch == "#" and (i == 0 or text[i - 1].isspace()):
            return text[:i]
    return text


class _YamlParser:
    """Lê o subconjunto de YAML usado nos workflows e nas plantilhas.

    Mapas e listas em bloco, sequências e mapas flow, escalares entre aspas,
    blocos `|` e `>`, âncoras (`&`/`*`) e merge (`<<`). O que ficar de fora
    é erro: a checagem não segue em silêncio.
    """

    def __init__(self, text: str):
        self.lines = text.splitlines()
        self.n = len(self.lines)
        self.i = 0
        self.anchors: dict[str, object] = {}
        self.ended = False

    def parse(self):
        self._skip_blanks(allow_doc_start=True)
        if self.i >= self.n or self.ended:
            return None
        node = self._parse_block_node(self._indent_of(self.i))
        self._skip_blanks(allow_doc_start=False)
        if self.i < self.n and not self.ended:
            raise self._err("conteúdo extra depois do documento")
        return node

    def _err(self, message: str) -> YamlError:
        line = self.i + 1 if self.i < self.n else self.n
        return YamlError(message, line)

    def _indent_of(self, idx: int) -> int:
        line = self.lines[idx]
        n = 0
        for ch in line:
            if ch == " ":
                n += 1
            elif ch == "\t":
                raise YamlError("tabulação na indentação", idx + 1)
            else:
                break
        return n

    def _skip_blanks(self, allow_doc_start: bool) -> None:
        while self.i < self.n:
            stripped = self.lines[self.i].strip()
            if stripped == "" or stripped.startswith("#"):
                self.i += 1
                continue
            if stripped == "---":
                if not allow_doc_start:
                    raise self._err("documento YAML extra")
                self.i += 1
                allow_doc_start = False
                continue
            if stripped == "...":
                self.i += 1
                self.ended = True
                return
            if stripped.startswith("%"):
                raise self._err("diretiva YAML não é aceita")
            return

    def _parse_block_node(self, indent: int):
        if self.i >= self.n:
            raise self._err("valor ausente")
        ind = self._indent_of(self.i)
        if ind < indent:
            raise self._err("indentação menor que o esperado")
        content = self.lines[self.i][ind:]
        if content.startswith("- ") or content == "-":
            return self._parse_sequence(ind)
        if content.startswith("!"):
            raise self._err("tags YAML não são aceitas")
        if content.startswith("*"):
            if not self._is_alias(content):
                raise self._err("alias inválido")
            node = self._resolve_alias(content)
            self.i += 1
            return node
        if self._is_key_line(content):
            return self._parse_mapping(ind)
        if content.startswith('"') or content.startswith("'"):
            node, end = self._parse_quoted(content, 0)
            if _strip_plain_comment(content[end:]).strip():
                raise self._err("sobra depois do escalar")
            self.i += 1
            return node
        if content.startswith("[") or content.startswith("{"):
            return self._parse_flow_value(content)
        node = self._parse_plain(content)
        self.i += 1
        return node

    def _parse_mapping(self, indent: int, first: str | None = None) -> dict:
        result: dict = {}
        merges: list = []
        pending = first
        while True:
            if pending is None:
                self._skip_blanks(allow_doc_start=False)
                if self.i >= self.n or self.ended:
                    break
                ind = self._indent_of(self.i)
                if ind < indent:
                    break
                if ind > indent:
                    raise self._err("indentação inesperada num mapa")
                content = self.lines[self.i][ind:]
                if content.startswith("- ") or content == "-":
                    if first is not None:
                        break
                    raise self._err("lista no meio de um mapa")
                pending = content
            key, rest = self._split_key(pending)
            pending = None
            value = self._parse_value_after_key(rest, indent)
            if key == "<<":
                merges.append(value)
            else:
                result[key] = value
        if merges:
            return self._apply_merge(merges, result)
        return result

    def _parse_sequence(self, indent: int) -> list:
        items: list = []
        while self.i < self.n and not self.ended:
            self._skip_blanks(allow_doc_start=False)
            if self.i >= self.n or self.ended:
                break
            ind = self._indent_of(self.i)
            if ind < indent:
                break
            if ind > indent:
                raise self._err("indentação inesperada numa lista")
            content = self.lines[self.i][ind:]
            if content == "-":
                rest = ""
            elif content.startswith("- "):
                rest = content[2:]
            else:
                break
            items.append(self._parse_seq_item(rest, indent))
        return items

    def _parse_seq_item(self, rest: str, dash_indent: int):
        col = dash_indent + 2
        idx = 0
        while idx < len(rest) and rest[idx] == " ":
            idx += 1
            col += 1
        anchor = None
        if idx < len(rest) and rest.startswith("&", idx):
            anchor, after = self._take_anchor(rest[idx:])
            idx = len(rest) - len(after)
            col = dash_indent + 2 + idx
            while idx < len(rest) and rest[idx] == " ":
                idx += 1
                col += 1
        node = self._parse_node_from_text(rest[idx:], col, dash_indent)
        if anchor is not None:
            self.anchors[anchor] = node
        return node

    def _parse_node_from_text(self, s: str, value_col: int, dash_indent: int):
        if s.startswith("*"):
            if not self._is_alias(s):
                raise self._err("alias inválido")
            node = self._resolve_alias(s)
            self.i += 1
            return node
        if s.startswith("!"):
            raise self._err("tags YAML não são aceitas")
        if s == "" or s.startswith("#"):
            self.i += 1
            self._skip_blanks(allow_doc_start=False)
            if not self.ended and self.i < self.n and self._indent_of(self.i) > dash_indent:
                return self._parse_block_node(self._indent_of(self.i))
            return None
        if self._starts_block_header(s):
            return self._parse_block_scalar(s, dash_indent)
        if s.startswith("[") or s.startswith("{"):
            return self._parse_flow_value(s)
        if self._is_key_line(s):
            return self._parse_mapping(value_col, first=s)
        if s.startswith('"') or s.startswith("'"):
            node, end = self._parse_quoted(s, 0)
            if _strip_plain_comment(s[end:]).strip():
                raise self._err("sobra depois do escalar")
            self.i += 1
            return node
        node = self._parse_plain(s)
        self.i += 1
        return node

    def _parse_value_after_key(self, rest: str, parent_indent: int):
        s = rest.lstrip(" ")
        anchor = None
        if s.startswith("&"):
            anchor, after = self._take_anchor(s)
            s = after.lstrip(" ")
        if s.startswith("!"):
            raise self._err("tags YAML não são aceitas")
        if s.startswith("*"):
            if not self._is_alias(s):
                raise self._err("alias inválido")
            node = self._resolve_alias(s)
            self.i += 1
        elif self._starts_block_header(s):
            node = self._parse_block_scalar(s, parent_indent)
        elif s.startswith("[") or s.startswith("{"):
            node = self._parse_flow_value(s)
        elif s.startswith('"') or s.startswith("'"):
            node, end = self._parse_quoted(s, 0)
            if _strip_plain_comment(s[end:]).strip():
                raise self._err("sobra depois do escalar")
            self.i += 1
        elif s == "" or s.startswith("#"):
            self.i += 1
            self._skip_blanks(allow_doc_start=False)
            if not self.ended and self.i < self.n and self._indent_of(self.i) > parent_indent:
                node = self._parse_block_node(self._indent_of(self.i))
            else:
                node = None
        else:
            node = self._parse_plain(s)
            self.i += 1
        if anchor is not None:
            self.anchors[anchor] = node
        return node

    def _parse_block_scalar(self, header: str, parent_indent: int) -> str:
        hdr = _strip_plain_comment(header).strip()
        m = re.fullmatch(r"([|>])([-+]?)([1-9])?", hdr)
        if not m:
            raise self._err(f"cabeçalho de bloco inválido: {header!r}")
        style, chomp, explicit = m.group(1), m.group(2) or "", m.group(3)
        self.i += 1
        lines: list[str] = []
        content_indent = parent_indent + int(explicit) if explicit else None
        while self.i < self.n:
            line = self.lines[self.i]
            if line.strip() == "":
                lines.append("")
                self.i += 1
                continue
            ind = self._indent_of(self.i)
            if ind <= parent_indent:
                break
            if content_indent is None:
                content_indent = ind
            if ind < content_indent:
                raise self._err("linha do bloco menos indentada que o conteúdo")
            lines.append(line[content_indent:])
            self.i += 1
        if content_indent is None:
            return ""
        if style == "|":
            text = "\n".join(lines) + "\n"
        else:
            text = self._fold(lines)
        if chomp == "-":
            return text.rstrip("\n")
        if chomp == "+":
            return text if text.endswith("\n") or text == "" else text + "\n"
        return text.rstrip("\n") + "\n"

    def _fold(self, lines: list[str]) -> str:
        """Dobra quebras simples em espaço; linha em branco vira quebra de parágrafo."""
        pieces: list[str] = []
        buf: list[str] = []
        blanks = 0
        prev_literal = False

        def emit(chunk: str, literal: bool) -> None:
            nonlocal blanks, prev_literal
            if pieces:
                if prev_literal:
                    n = blanks
                else:
                    n = blanks if blanks else 1
                if n:
                    pieces.append("\n" * n)
            elif blanks:
                pieces.append("\n" * blanks)
            blanks = 0
            pieces.append(chunk)
            if literal:
                pieces.append("\n")
            prev_literal = literal

        def flush_folded() -> None:
            if buf:
                emit(" ".join(buf), False)
                buf.clear()

        for line in lines:
            if line == "":
                flush_folded()
                blanks += 1
            elif line[0].isspace():
                flush_folded()
                emit(line, True)
            else:
                if blanks and buf:
                    flush_folded()
                buf.append(line)
        flush_folded()
        if blanks:
            pieces.append("\n" * blanks)
        text = "".join(pieces)
        if text and not text.endswith("\n"):
            text += "\n"
        return text

    def _parse_flow_value(self, first: str):
        text = first
        while not self._flow_balanced(text):
            self.i += 1
            if self.i >= self.n:
                raise self._err("coleção não fechada")
            text += "\n" + self.lines[self.i]
        node, end = self._parse_flow_at(text, 0)
        if _strip_plain_comment(text[end:]).strip():
            raise self._err("sobra depois da coleção")
        self.i += 1
        return node

    def _flow_balanced(self, text: str) -> bool:
        depth_sq = depth_cu = 0
        in_s = in_d = False
        i = 0
        while i < len(text):
            ch = text[i]
            if in_d:
                if ch == "\\":
                    i += 2
                    continue
                if ch == '"':
                    in_d = False
                i += 1
                continue
            if in_s:
                if ch == "'":
                    if i + 1 < len(text) and text[i + 1] == "'":
                        i += 2
                        continue
                    in_s = False
                i += 1
                continue
            if ch == '"':
                in_d = True
            elif ch == "'":
                in_s = True
            elif ch == "#":
                nl = text.find("\n", i)
                if nl == -1:
                    break
                i = nl
                continue
            elif ch == "[":
                depth_sq += 1
            elif ch == "]":
                depth_sq -= 1
                if depth_sq < 0:
                    raise self._err("] sem [")
            elif ch == "{":
                depth_cu += 1
            elif ch == "}":
                depth_cu -= 1
                if depth_cu < 0:
                    raise self._err("} sem {")
            i += 1
        return depth_sq == 0 and depth_cu == 0 and not in_s and not in_d

    def _parse_flow_at(self, text: str, i: int):
        i = self._skip_flow_ws(text, i)
        if i >= len(text):
            raise self._err("coleção flow incompleta")
        ch = text[i]
        if ch == "[":
            return self._parse_flow_seq(text, i)
        if ch == "{":
            return self._parse_flow_map(text, i)
        if ch in "\"'":
            return self._parse_quoted(text, i)
        if ch == "*":
            m = re.match(r"\*([A-Za-z0-9_]+)", text[i:])
            if not m or m.group(1) not in self.anchors:
                raise self._err("âncora indefinida" if m else "alias inválido")
            return copy.deepcopy(self.anchors[m.group(1)]), i + m.end()
        if ch in "!&":
            raise self._err("tag ou âncora flow não aceita nesse ponto")
        return self._parse_flow_plain(text, i)

    def _parse_flow_seq(self, text: str, i: int):
        i += 1
        items: list = []
        while True:
            i = self._skip_flow_ws(text, i)
            if i < len(text) and text[i] == "]":
                return items, i + 1
            if i >= len(text):
                raise self._err("lista flow não fechada")
            node, i = self._parse_flow_at(text, i)
            items.append(node)
            i = self._skip_flow_ws(text, i)
            if i < len(text) and text[i] == ",":
                i += 1
                continue
            if i < len(text) and text[i] == "]":
                return items, i + 1
            raise self._err("faltou vírgula ou ] na lista")

    def _parse_flow_map(self, text: str, i: int):
        i += 1
        result: dict = {}
        while True:
            i = self._skip_flow_ws(text, i)
            if i < len(text) and text[i] == "}":
                return result, i + 1
            if i >= len(text):
                raise self._err("mapa flow não fechado")
            if text[i] in "\"'":
                key, i = self._parse_quoted(text, i)
            else:
                key, i = self._parse_flow_plain(text, i)
            i = self._skip_flow_ws(text, i)
            if i >= len(text) or text[i] != ":":
                raise self._err("faltou : no mapa flow")
            i += 1
            val, i = self._parse_flow_at(text, i)
            result[key] = val
            i = self._skip_flow_ws(text, i)
            if i < len(text) and text[i] == ",":
                i += 1
                continue
            if i < len(text) and text[i] == "}":
                return result, i + 1
            raise self._err("faltou vírgula ou } no mapa")

    def _parse_flow_plain(self, text: str, i: int):
        start = i
        while i < len(text):
            ch = text[i]
            if ch in ",[]{}":
                break
            if ch == "#" and (i == start or text[i - 1].isspace()):
                break
            if ch == ":" and i + 1 < len(text) and text[i + 1].isspace():
                break
            i += 1
        raw = text[start:i].strip()
        if raw == "":
            raise self._err("escalar vazio")
        return _coerce_scalar(raw), i

    def _skip_flow_ws(self, text: str, i: int) -> int:
        while i < len(text):
            if text[i] in " \t\n\r":
                i += 1
                continue
            if text[i] == "#":
                while i < len(text) and text[i] != "\n":
                    i += 1
                continue
            break
        return i

    def _parse_quoted(self, text: str, i: int) -> tuple[str, int]:
        quote = text[i]
        i += 1
        out: list[str] = []
        if quote == '"':
            while i < len(text):
                ch = text[i]
                if ch == "\\":
                    if i + 1 >= len(text):
                        raise self._err("escape incompleto")
                    nxt = text[i + 1]
                    mapping = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "/": "/"}
                    if nxt not in mapping:
                        raise self._err(f"escape desconhecido: \\{nxt}")
                    out.append(mapping[nxt])
                    i += 2
                    continue
                if ch == '"':
                    return "".join(out), i + 1
                out.append(ch)
                i += 1
            raise self._err("aspas duplas não fechadas")
        while i < len(text):
            ch = text[i]
            if ch == "'":
                if i + 1 < len(text) and text[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                return "".join(out), i + 1
            out.append(ch)
            i += 1
        raise self._err("aspas simples não fechadas")

    def _parse_plain(self, text: str):
        raw = _strip_plain_comment(text).strip()
        if raw == "":
            return None
        if re.search(r":[ \t]", raw):
            raise self._err("escalar sem aspas não pode conter «: »")
        if "\t" in raw:
            raise self._err("tabulação em escalar sem aspas")
        if raw.startswith(("!", "&", "*")):
            raise self._err("indicador YAML no escalar")
        return _coerce_scalar(raw)

    def _is_alias(self, text: str) -> bool:
        return re.fullmatch(r"\*[A-Za-z0-9_]+", _strip_plain_comment(text).strip()) is not None

    def _resolve_alias(self, text: str):
        name = _strip_plain_comment(text).strip()[1:]
        if name not in self.anchors:
            raise self._err(f"âncora indefinida «{name}»")
        return copy.deepcopy(self.anchors[name])

    def _take_anchor(self, text: str) -> tuple[str, str]:
        m = re.match(r"&([A-Za-z0-9_]+)(\s.*)?$", text)
        if not m:
            raise self._err(f"âncora inválida: {text!r}")
        return m.group(1), m.group(2) or ""

    def _starts_block_header(self, s: str) -> bool:
        hdr = _strip_plain_comment(s).strip()
        return re.fullmatch(r"[|>][-+]?[1-9]?", hdr) is not None

    def _is_key_line(self, content: str) -> bool:
        s = content.lstrip()
        if not s or s[0] in "[{|>*!%#&":
            return False
        if s[0] in "\"'":
            try:
                _, end = self._parse_quoted(s, 0)
            except YamlError:
                return False
            rest = s[end:]
            return rest.startswith(":") and (len(rest) == 1 or rest[1].isspace())
        for i, ch in enumerate(s):
            if ch == ":" and (i + 1 == len(s) or s[i + 1].isspace()):
                return i > 0
        return False

    def _split_key(self, content: str):
        if content.startswith(("\"", "'")):
            key, end = self._parse_quoted(content, 0)
            if end >= len(content) or content[end] != ":":
                raise self._err("falta ':' depois da chave")
            nxt = content[end + 1:end + 2]
            if nxt not in ("", " ", "\t"):
                raise self._err("falta espaço depois de ':'")
            return key, content[end + 1:]
        for i, ch in enumerate(content):
            if ch == ":" and (i + 1 == len(content) or content[i + 1].isspace()):
                raw = content[:i].rstrip()
                if not raw:
                    raise self._err("chave vazia")
                return _coerce_scalar(raw), content[i + 1:]
        raise self._err("não é uma entrada de mapa")

    def _apply_merge(self, merges: list, explicit: dict) -> dict:
        merged: dict = {}
        for val in merges:
            dicts = val if isinstance(val, list) else [val]
            for item in dicts:
                if not isinstance(item, dict):
                    raise self._err("«<<» precisa ser um mapa")
                for k, v in item.items():
                    if k not in merged and k not in explicit:
                        merged[k] = copy.deepcopy(v)
        merged.update(explicit)
        return merged


def load_yaml(text: str):
    """Interpreta um documento YAML (subconjunto) e devolve a estrutura Python."""
    return _YamlParser(text).parse()


def check_github_yaml(root: Path | None = None) -> list[str]:
    """Valida os .yml de .github. Sempre roda; não depende de PyYAML."""
    base_root = root or ROOT
    base = base_root / ".github"
    errs: list[str] = []
    arquivos = sorted(base.rglob("*.yml")) + sorted(base.rglob("*.yaml"))
    if not arquivos:
        errs.append(f"{base}: nenhum .yml encontrado")
    for path in arquivos:
        rel = path.relative_to(base_root).as_posix()
        try:
            doc = load_yaml(path.read_text(encoding="utf-8"))
        except YamlError as exc:
            errs.append(f"{rel}: YAML inválido ({exc})")
            continue
        except UnicodeDecodeError as exc:
            errs.append(f"{rel}: YAML inválido ({exc})")
            continue
        if doc is None:
            errs.append(f"{rel}: YAML vazio")
            continue
        if "ISSUE_TEMPLATE" in path.parts and path.name != "config.yml":
            errs.extend(check_issue_form(doc, rel))
    return errs


def main() -> int:
    data = json.loads((ROOT / "data" / "events.json").read_text(encoding="utf-8"))
    vocab = set(json.loads((ROOT / "data" / "tags.json").read_text(encoding="utf-8"))["tags"])
    errs = check(data, vocab)
    bruto = ler_descartados()
    if isinstance(bruto, str):
        errs.append(bruto)
    else:
        errs.extend(erros_descartados(bruto))
    roles = json.loads(ROLES.read_text(encoding="utf-8"))
    vocab_roles, categorias = _vocab_roles()
    errs.extend(f"roles.json: {e}" if not e.startswith("roles") else e for e in check(roles, vocab_roles))
    if isinstance(roles.get("events"), list):
        errs.extend(f"roles.json: {e}" for e in erros_extras_roles(roles["events"], categorias))
    fixos = json.loads(FIXOS.read_text(encoding="utf-8"))
    errs.extend(erros_fixos(fixos, vocab_roles, categorias))
    errs.extend(check_github_yaml())
    if errs:
        print("❌ a agenda tem problemas:")
        print("\n".join(f"  - {e}" for e in errs))
        return 1
    n_fixos = len(fixos.get("events") or [])
    print(f"✅ {len(data['events'])} eventos de tech, {len(roles['events'])} rolês e {n_fixos} fixos válidos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
