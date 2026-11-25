#!/usr/bin/env python3
"""Lê duas caixas do Gmail e importa eventos pelo mesmo caminho de importar.py.

Caixas (a conta é uma dica, não uma regra):
  agenda.rio.eventos@gmail.com       agenda Tech (data/events.json)
  agenda.rio.roles@gmail.com         agenda Rolês (data/roles.json)
  agenda.rio.roles+cultura@gmail.com Rolês, categoria cultura

Link de página que o importador já lê (Luma, Meetup, Sympla, Eventbrite,
Even3, Shotgun e os outros hosts de importar.EVENT_HOSTS) segue o caminho
--url. Newsletter sem esse link (IMS, Sesc, Fever, Bandsintown e semelhantes)
vai para o modelo. Não inventa data nem hora.

Filtros deste caminho: futuro, presencial ou híbrido (online fica de fora),
cidade configurada (Rio) e validar.py. Não abre link de descadastro,
preferências, perfil ou «ver no navegador», nem o List-Unsubscribe.
Não abre link de conta: confirm, confirmar, verify, verificar, activate,
ativar, reset, password, login, signin ou token= na URL.
Se a página do evento falha (HTTP, robots.txt indisponível ou 503, sem
JSON-LD), o texto do e-mail vai para o modelo, em vez de descartar.
Songkick («concerts this week in Rio»), Eventim e Resident Advisor listam
vários eventos no mesmo e-mail: entram todos, com data, local, artista e link.
A cidade sai do bloco, não do e-mail inteiro: Rio se o bloco cita Rio, RJ ou
uma casa conhecida do Rio; São Paulo, SP, BH e o mesmo tipo ficam de fora.
No Songkick «concerts this week in Rio», a lista inteira é do Rio.
Também ignora imagem, CDN, loja de aplicativo e página da Luma que não é
evento (/, /settings, /ios, /android, /home, /discover). Isso não entra
na lista de descartados. O relatório lista cada URL descartada uma vez,
com quantos e-mails ela apareceu.

A caixa Tech manda para a Rolês o evento cuja tag é só esporte ou lazer
(corrida, samba, idiomas e o mesmo tipo) e não tem tema tech.

IMAP só lê. Para não reprocessar, aplica a etiqueta agenda/processado.
Não apaga nem move. O repositório não guarda endereço, remetente nem o texto.

Segredos (nunca no repositório): GMAIL_EVENTOS_APP_PASSWORD,
GMAIL_ROLES_APP_PASSWORD e ANTHROPIC_API_KEY. Se faltar senha, sai com aviso
e código 0.

Só usa a biblioteca padrão do Python (3.10+).
"""
from __future__ import annotations

import argparse
import datetime as dt
import email
import html
import imaplib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from email import policy
from pathlib import Path

import importar
import validar

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
ROTULO = "agenda/processado"
DIAS = 14
MAX_MENSAGENS = 40
MAX_RASTREADORES = 15
MAX_TEXTO = 30_000
MAX_INPUT_TOKENS = 300_000
MODELO = "claude-haiku-5-5"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2026-10-21"
# A cidade da agenda. O correio já filtra por ela.
CIDADE = "Rio de Janeiro"

CAIXAS = (
    {
        "nome": "Tech",
        "user": "agenda.rio.eventos@gmail.com",
        "senha_env": "GMAIL_EVENTOS_APP_PASSWORD",
        "agenda": "tech",
    },
    {
        "nome": "Rolês",
        "user": "agenda.rio.roles@gmail.com",
        "senha_env": "GMAIL_ROLES_APP_PASSWORD",
        "agenda": "roles",
    },
)
ALIAS_CULTURA = "agenda.rio.roles+cultura"
# Na busca Gmail, etiqueta aninhada «agenda/processado» vira «agenda-processado».
# O STORE +X-GM-LABELS continua com ROTULO («agenda/processado»).
BUSCA = f"newer_than:{DIAS}d -label:agenda-processado"

# Hosts que importar.py já lê, mais Shotgun (está nos agregadores, não no regex).
_HOSTS_CONHECIDOS = re.compile(
    r"(?:^|\.)" + importar.EVENT_HOSTS.pattern + r"$",
    re.I,
)
RASTREADORES = (
    "bit.ly", "t.co", "tinyurl.com", "ow.ly", "buff.ly", "lnkd.in",
    "mailchi.mp", "list-manage.com", "sendgrid.net", "awstrack.me",
    "mandrillapp.com", "ctt.ec", "hubs.ly",
)
# No caminho ou na query, antes de seguir um rastreador.
_PALAVRAS_URL = (
    "unsubscribe", "unsub", "optout", "opt-out", "opt_out", "descadastr",
    "cancelar-inscricao", "preferences", "preferencias", "manage", "profile",
    "update-profile",
)
# Conta, senha e confirmação. Não são página de evento.
_PALAVRAS_CONTA = (
    "confirm", "confirmar", "verify", "verificar", "activate", "ativar",
    "reset", "password", "login", "signin", "sign-in", "sign_in",
)
# No texto do <a>, também antes de seguir.
_FRASES_ANCORA = (
    "descadastr", "cancelar inscricao", "unsubscribe", "preferencias",
    "preferences", "gerenciar", "ver no navegador", "view in browser",
)
EXTRAS_RASTREIO = {
    "mc_cid", "mc_eid", "mkt_tok", "_hsenc", "_hsmi", "igshid", "vero_id",
    "vero_conv", "_ke", "ml_subscriber", "ml_subscriber_hash", "sc_cid",
    "trk", "trkcampaign", "yclid", "msclkid", "si", "aff", "aff_id",
}
TAGS_TECH_FRACAS = {
    "palestra", "comunidade", "networking", "meetup", "conferencia",
    "workshop", "carreira", "educacao", "inovacao",
}
TAGS_ROLES_FRACAS = {"palestras"}
# Esporte e lazer. Palestra e nerd/geek ficam de fora: cruzam com a agenda Tech.
TAGS_LAZER = {
    "corrida", "trilha", "volei",
    "samba-roda", "pagode", "funk", "forro", "hiphop", "eletronica", "rock",
    "lgbtqia", "festa-popular", "shows",
    "idiomas", "jogos-tabuleiro", "leitura", "nomades", "expats",
    "exposicoes", "mostras", "cineclubes", "pre-estreias", "festivais",
    "de-graca",
}
# Nome de clube ou comunidade. Não segura o evento na Tech se a atividade é lazer.
TAGS_SOCIAIS = {
    "founders", "comunidade", "networking", "diversidade", "empreendedorismo",
}
_EXT_ASSET = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico")
_LUMA_NAO_EVENTO = {"settings", "ios", "android", "home", "discover"}
_LOJAS = ("apps.apple.com", "itunes.apple.com", "play.google.com")
OUTRA_CIDADE = re.compile(
    r"\bs[aã]o paulo\b|\bbelo horizonte\b|\bcuritiba\b|\bporto alegre\b|"
    r"\bsalvador\b|\brecife\b|\bbras[ií]lia\b|\bflorian[oó]polis\b|\bcampinas\b",
    re.I,
)
# Sigla do mesmo tipo, no bloco do evento. Não vale para o e-mail inteiro.
_SIGLA_OUTRA_CIDADE = re.compile(r"\b(?:sp|bh|poa|bsb|ssa|rec|cwb|fln)\b")
_RIO_NO_BLOCO = re.compile(r"\b(?:rio de janeiro|rio|rj)\b")
_SONGKICK_LISTA_RIO = re.compile(r"concerts this week in rio\b")
# Casas do Rio que a newsletter cita sem repetir a cidade.
_CASAS_RIO = (
    "circo voador",
    "qualistage",
    "marina da gloria",
    "teatro riachuelo",
    "club laroc",
)
_CASAS_RIO_GENERICAS = {"shows", "gratis", "fim de semana"}
EMAIL_RE = re.compile(r"(?i)[\w.+-]+@[\w.-]+\.[a-z]{2,}")
LINK_RE = re.compile(r"https?://[^\s<>()\[\]\"']+", re.I)
_ANCORA_RE = re.compile(
    r"(?is)<a\b[^>]*\bhref\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>"
)

_CAMPOS_EVENTO = {
    "title": {"type": "string", "description": "Nome como no texto."},
    "start": {"type": "string", "description": "Início ISO 8601 com -03:00. Vazio se faltar data ou hora."},
    "end": {"type": "string", "description": "Término ISO 8601 com -03:00, ou vazio."},
    "venue": {"type": "string", "description": "Local, ou vazio."},
    "address": {"type": "string", "description": "Endereço, ou vazio."},
    "city": {"type": "string", "description": "Cidade como no texto, ou vazio. Não assuma."},
    "url": {"type": "string", "description": "Link público https do evento, ou vazio."},
    "cost": {"type": "string", "description": "gratis, pago, desconhecido, ou o preço escrito."},
    "format": {"type": "string", "enum": ["presencial", "online", "hibrido"]},
    "language": {"type": "string", "enum": ["pt", "en", "es", "multi", "desconhecido"]},
    "description_pt": {"type": "string", "description": "Resumo seu em português, até 280 caracteres."},
}
ESQUEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["eventos"],
    "properties": {
        "eventos": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": list(_CAMPOS_EVENTO),
                "properties": _CAMPOS_EVENTO,
            },
        },
    },
}
INSTRUCAO = (
    "Extraia eventos de uma newsletter. Não invente dado nenhum. "
    "Se a data ou a hora não estiver no texto, o evento não entra. "
    "Não inclua e-mail, telefone nem nome de pessoa. "
    "description_pt é um resumo seu, em português, com no máximo 280 caracteres. "
    "start e end em ISO 8601 com fuso -03:00. end vazio se o texto não disser o fim. "
    "url só se houver um link público https do evento; se não houver, url vazio. "
    "format é presencial, online ou hibrido, como o texto disser. "
    "cost é gratis, pago, desconhecido, ou o preço exatamente como escrito. "
    "language é pt, en, es, multi ou desconhecido. "
    "city é a cidade escrita no texto; se não estiver, city vazio. "
    "Se não houver evento, a lista fica vazia."
)


class FalhaEntrada(Exception):
    """A senha foi recusada. A mensagem original fica de fora: pode ecoar a senha."""


class ModeloErro(Exception):
    pass


class ModeloIncompleto(Exception):
    def __init__(self, entrada: int = 0, saida: int = 0):
        super().__init__("resposta cortada")
        self.entrada = entrada
        self.saida = saida


class ContaTokens:
    def __init__(self, teto: int = MAX_INPUT_TOKENS):
        self.entrada = 0
        self.saida = 0
        self.teto = teto
        self.parou = False

    def pode(self) -> bool:
        if self.entrada >= self.teto:
            self.parou = True
            return False
        return True

    def somar(self, entrada: int, saida: int) -> None:
        self.entrada += max(0, int(entrada))
        self.saida += max(0, int(saida))
        if self.entrada >= self.teto:
            self.parou = True


class ResumoCaixa:
    def __init__(self, nome: str, user: str):
        self.nome = nome
        self.user = user
        self.lidos = 0
        self.encontrados = 0
        self.novos: list[str] = []
        self.completados: list[str] = []
        self.reclassificados: list[str] = []
        self.adiados: list[str] = []
        self.avisos: list[str] = []
        self.entrada = 0
        self.saida = 0
        self.mail_id = 0
        self._mail_seq = 0
        self._descartes: dict[str, dict] = {}
        self._ordem: list[str] = []

    def novo_mail(self) -> None:
        self._mail_seq += 1
        self.mail_id = self._mail_seq

    def descartar(self, texto: str, url: str | None = None) -> None:
        """Uma linha por URL. O número é de e-mails, não de repetições no mesmo."""
        chave = importar.chave_url(url or "") or texto
        item = self._descartes.get(chave)
        if item is None:
            item = {"texto": texto, "mails": set()}
            self._descartes[chave] = item
            self._ordem.append(chave)
        item["mails"].add(self.mail_id)

    def linhas_descartados(self) -> list[str]:
        linhas = []
        for chave in self._ordem:
            item = self._descartes[chave]
            n = len(item["mails"])
            rotulo = "e-mail" if n == 1 else "e-mails"
            linhas.append(f"{item['texto']} · {n} {rotulo}")
        return linhas


class CaixaTrabalho:
    def __init__(self, nome: str, user: str, agenda: str, mensagens: list[tuple[str, bytes]],
                 etiquetar: Callable[[str], None] | None = None, truncou: bool = False):
        self.nome = nome
        self.user = user
        self.agenda = agenda
        self.mensagens = mensagens
        self.etiquetar = etiquetar
        self.truncou = truncou


def caminhos() -> dict[str, Path]:
    return {
        "tech": importar.EVENTS,
        "roles": importar.ROOT / "data" / "roles.json",
    }


def limpar_privacidade(texto: str) -> str:
    return EMAIL_RE.sub(" ", texto or "")


def sem_rastreio(url: str) -> str:
    url = importar.clean_url(url)
    partes = urllib.parse.urlsplit(url)
    query = [
        (chave, valor)
        for chave, valor in urllib.parse.parse_qsl(partes.query)
        if chave.lower() not in EXTRAS_RASTREIO and not chave.lower().startswith("utm_")
    ]
    return urllib.parse.urlunsplit((
        partes.scheme, partes.netloc, partes.path, urllib.parse.urlencode(query), "",
    ))


def _primeiro(qs: dict, *chaves: str) -> str | None:
    for chave in chaves:
        valores = qs.get(chave)
        if not valores:
            continue
        valor = html_unescape(valores[0]).strip()
        if valor.lower().startswith("http"):
            return valor
    return None


def html_unescape(texto: str) -> str:
    return html.unescape(texto)


def desembrulhar(url: str) -> str:
    atual = (url or "").strip()
    for _ in range(5):
        prox = _um_salto(atual)
        if not prox or prox == atual:
            break
        atual = prox
    return atual


def _um_salto(url: str) -> str | None:
    url = html_unescape(url.strip())
    baixo = url.lower()
    if "urldefense" in baixo or "proofpoint" in baixo:
        achou = re.search(r"__(https?://.+?)__", url)
        if achou:
            return achou.group(1)
    partes = urllib.parse.urlsplit(url)
    host = partes.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return None
    qs = urllib.parse.parse_qs(partes.query)
    if host in {"google.com", "google.com.br"} and (partes.path or "").startswith("/url"):
        return _primeiro(qs, "q", "url")
    if host.endswith("safelinks.protection.outlook.com"):
        return _primeiro(qs, "url")
    if host in {"l.facebook.com", "lm.facebook.com", "l.instagram.com"}:
        return _primeiro(qs, "u")
    if "urldefense" in host or host.endswith("protection.proofpoint.com"):
        return _primeiro(qs, "u")
    return None


def e_rastreador(url: str) -> bool:
    host = importar._host(url)
    return any(host == item or host.endswith("." + item) for item in RASTREADORES)


def _chave_url(url: str) -> str:
    return html_unescape((url or "").strip()).rstrip(".,;:!?)*]>\"'")


def _host_link(url: str) -> str:
    try:
        host = urllib.parse.urlsplit(_chave_url(url)).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    if host == "lu.ma":
        host = "luma.com"
    return host


def url_irrelevante(url: str) -> bool:
    """Imagem, CDN, loja de aplicativo ou página da Luma que não é um evento.

    Não entra na lista de descartados: o link é ignorado.
    """
    bruto = _chave_url(url)
    if not bruto:
        return False
    try:
        partes = urllib.parse.urlsplit(bruto if "://" in bruto else "https://" + bruto)
    except Exception:
        return False
    host = _host_link(bruto if "://" in bruto else "https://" + bruto)
    if host.startswith("cdn."):
        return True
    if any(host == loja or host.endswith("." + loja) for loja in _LOJAS):
        return True
    path = urllib.parse.unquote(partes.path or "").lower()
    if "/email/" in f"/{path.strip('/')}/" or "/app-store" in path or "/store/apps" in path:
        return True
    if any(path.rstrip("/").endswith(ext) for ext in _EXT_ASSET):
        return True
    if host == "luma.com":
        miolo = path.strip("/")
        if not miolo or miolo.split("/")[0] in _LUMA_NAO_EVENTO:
            return True
    return False


def _alvo_url(url: str) -> str:
    try:
        partes = urllib.parse.urlsplit(_chave_url(url))
    except Exception:
        return ""
    return (
        urllib.parse.unquote(partes.path or "")
        + "?"
        + urllib.parse.unquote_plus(partes.query or "")
    ).lower()


def url_de_conta(url: str) -> bool:
    """Confirmação, senha, login ou token. Não abre."""
    alvo = _alvo_url(url)
    if not alvo:
        return False
    if "token=" in alvo:
        return True
    return any(palavra in alvo for palavra in _PALAVRAS_CONTA)


def url_recusada(url: str) -> bool:
    """Caminho ou query de descadastro, preferência, perfil, conta ou link que não é evento."""
    if url_irrelevante(url) or url_de_conta(url):
        return True
    return any(palavra in _alvo_url(url) for palavra in _PALAVRAS_URL)


def ancora_recusada(texto: str) -> bool:
    low = re.sub(r"\s+", " ", importar._sem_acento(texto or "")).strip()
    return any(frase in low for frase in _FRASES_ANCORA)


class FiltroLinks:
    """O que uma mensagem não abre, e quantos rastreadores ela já seguiu."""

    def __init__(self, limite: int = MAX_RASTREADORES):
        self.limite = limite
        self.usados = 0
        self._bloqueados: set[str] = set()

    def bloquear(self, url: str) -> None:
        chave = _chave_url(url)
        if chave:
            self._bloqueados.add(chave)

    def bloqueado(self, url: str) -> bool:
        chave = _chave_url(url)
        return bool(chave and chave in self._bloqueados)

    def pode_seguir(self) -> bool:
        if self.usados >= self.limite:
            return False
        self.usados += 1
        return True


def resolver_link(url: str, abrir: Callable[[str], str | None],
                  filtro: FiltroLinks | None = None, *, seguir_rede: bool = True) -> str | None:
    filtro = filtro or FiltroLinks()
    if not url or filtro.bloqueado(url) or url_recusada(url):
        return None
    atual = desembrulhar(url)
    if not atual.lower().startswith("http"):
        return None
    try:
        atual = sem_rastreio(atual)
    except Exception:
        return None
    if filtro.bloqueado(atual) or url_recusada(atual):
        return None
    if not e_rastreador(atual):
        return atual
    # Descadastro e preferência não chegam aqui. O teto é por mensagem.
    if seguir_rede and not filtro.pode_seguir():
        return None
    try:
        final = abrir(atual)
    except Exception:
        final = None
    if not final:
        return atual
    # O destino do rastreador pode ser outro invólucro. Não segue de novo pela rede.
    return resolver_link(final, lambda _url: None, filtro, seguir_rede=False)


def host_conhecido(url: str) -> bool:
    host = importar._host(url)
    if host == "shotgun.live" or host.endswith(".shotgun.live"):
        return True
    return bool(_HOSTS_CONHECIDOS.search(host))


def extrair_links(texto: str) -> list[str]:
    saida: list[str] = []
    vistos: set[str] = set()
    for bruto in LINK_RE.findall(texto or ""):
        url = bruto.rstrip(".,;:!?)*]>")
        if url not in vistos:
            vistos.add(url)
            saida.append(url)
    return saida


def links_uteis(texto: str, abrir: Callable[[str], str | None],
                filtro: FiltroLinks | None = None) -> list[str]:
    filtro = filtro or FiltroLinks()
    saida: list[str] = []
    vistos: set[str] = set()
    for bruto in extrair_links(texto):
        url = resolver_link(bruto, abrir, filtro)
        if not url or not host_conhecido(url):
            continue
        chave = importar.chave_url(url)
        if not chave or chave in vistos:
            continue
        vistos.add(chave)
        saida.append(url)
    return saida


def html_para_texto(origem: str) -> str:
    sem = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", " ", origem or "")

    def ancora(achou: re.Match) -> str:
        href = html_unescape(achou.group(1))
        miolo = re.sub(r"(?is)<[^>]+>", " ", achou.group(2))
        return f" {miolo} {href} "

    sem = _ANCORA_RE.sub(ancora, sem)
    sem = re.sub(r"(?i)<\s*br\s*/?>|</\s*p\s*>|</\s*div\s*>|</\s*li\s*>|</\s*tr\s*>|</\s*h[1-6]\s*>", "\n", sem)
    sem = re.sub(r"(?is)<[^>]+>", " ", sem)
    sem = html_unescape(sem).replace("\xa0", " ")
    sem = re.sub(r"[ \t]+\n", "\n", sem)
    sem = re.sub(r"[ \t]{2,}", " ", sem)
    sem = re.sub(r"\n{3,}", "\n\n", sem)
    return sem.strip()


def hrefs_html(origem: str) -> list[str]:
    return [html_unescape(item) for item in re.findall(r"(?is)\bhref\s*=\s*[\"']([^\"']+)[\"']", origem or "")]


def ancoras_html(origem: str) -> list[tuple[str, str]]:
    pares: list[tuple[str, str]] = []
    for href, miolo in _ANCORA_RE.findall(origem or ""):
        texto = re.sub(r"(?is)<[^>]+>", " ", miolo)
        texto = re.sub(r"\s+", " ", html_unescape(texto)).strip()
        pares.append((html_unescape(href).strip(), texto))
    return pares


def urls_list_unsubscribe(msg) -> list[str]:
    saida: list[str] = []
    vistos: set[str] = set()
    for valor in msg.get_all("List-Unsubscribe") or []:
        texto = str(valor)
        candidatos = [html_unescape(item.strip()) for item in re.findall(r"<([^>]+)>", texto)]
        candidatos.extend(extrair_links(texto))
        for bruto in candidatos:
            url = _chave_url(bruto)
            if not url.lower().startswith("http") or url in vistos:
                continue
            vistos.add(url)
            saida.append(url)
    return saida


def _partes(msg) -> tuple[str | None, str | None]:
    plain = html_src = None
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.is_attachment():
            continue
        tipo = part.get_content_type()
        try:
            conteudo = part.get_content()
        except Exception:
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            conteudo = payload.decode(charset, errors="replace")
        if not isinstance(conteudo, str):
            continue
        if tipo == "text/plain" and plain is None:
            plain = conteudo
        elif tipo == "text/html" and html_src is None:
            html_src = conteudo
    return plain, html_src


def ler_mensagem(raw: bytes) -> tuple[object, str, str]:
    """Devolve (mensagem, texto do modelo, texto de onde saem os links)."""
    msg = email.message_from_bytes(raw, policy=policy.default)
    plain, html_src = _partes(msg)
    href = "\n".join(hrefs_html(html_src)) if html_src else ""
    if plain and plain.strip():
        return msg, plain, plain + "\n" + href
    if html_src:
        visivel = html_para_texto(html_src)
        return msg, visivel, visivel + "\n" + href
    return msg, "", href


def filtro_da_mensagem(msg) -> FiltroLinks:
    """Marca descadastro, preferências e o cabeçalho List-Unsubscribe."""
    filtro = FiltroLinks()
    for url in urls_list_unsubscribe(msg):
        filtro.bloquear(url)
    _plain, html_src = _partes(msg)
    for href, ancora in ancoras_html(html_src or ""):
        if ancora_recusada(ancora) or url_recusada(href):
            filtro.bloquear(href)
    return filtro


def e_cultura(msg) -> bool:
    pedacos: list[str] = []
    for nome in ("to", "cc", "bcc", "delivered-to", "x-original-to", "envelope-to", "x-envelope-to"):
        for valor in msg.get_all(nome) or []:
            pedacos.append(str(valor))
    return ALIAS_CULTURA in " ".join(pedacos).lower()


def texto_evento(ev: dict) -> str:
    partes = [ev.get("title") or "", ev.get("venue") or "", ev.get("address") or "", ev.get("city") or ""]
    desc = ev.get("description") or {}
    if isinstance(desc, dict):
        partes.extend(str(valor) for valor in desc.values() if valor)
    elif isinstance(desc, str):
        partes.append(desc)
    return " ".join(str(p) for p in partes if p)


def tech_forte(texto: str) -> bool:
    low = (texto or "").lower()
    for pat, tag in importar.KEYWORDS:
        if tag in TAGS_TECH_FRACAS:
            continue
        if re.search(pat, low):
            return True
    return False


def roles_forte(texto: str) -> str | None:
    low = importar._sem_acento(texto or "")
    for pat, tag, cat in importar.ROLES_KEYWORDS:
        if tag in TAGS_ROLES_FRACAS:
            continue
        if re.search(pat, low):
            return cat
    return None


def _tags_tech(texto: str) -> list[str]:
    low = (texto or "").lower()
    achados: list[str] = []
    for pat, tag in importar.KEYWORDS:
        if tag in achados or tag in TAGS_SOCIAIS:
            continue
        if re.search(pat, low):
            achados.append(tag)
    return achados


def so_lazer(ev: dict) -> bool:
    """Tag só de esporte ou lazer (corrida, samba, idiomas e o mesmo tipo), sem tema tech.

    «Founders» no nome do clube não conta como tema tech.
    """
    texto = texto_evento(ev)
    tags, _categoria = importar.classificar_roles(texto)
    if not tags or any(tag not in TAGS_LAZER for tag in tags):
        return False
    return not _tags_tech(texto)


def escolher_agenda(ev: dict, dica: str) -> tuple[str, bool]:
    """A caixa é a dica. Só muda quando o texto é claramente da outra agenda.

    Na caixa Tech, esporte ou lazer sem tema tech vai para a Rolês.
    """
    if dica == "tech" and so_lazer(ev):
        return "roles", True
    texto = texto_evento(ev)
    tech = tech_forte(texto)
    roles = roles_forte(texto) is not None
    if tech and roles:
        return dica, False
    if dica == "tech" and roles and not tech:
        return "roles", True
    if dica == "roles" and tech and not roles:
        return "tech", True
    return dica, False


def normalizar_formato(valor: str) -> str:
    texto = importar._sem_acento(valor or "").strip()
    if texto in {"presencial", "online", "hibrido"}:
        return texto
    if texto in {"hybrid", "mixed"}:
        return "hibrido"
    return ""


def interpretar_custo(valor: str) -> dict:
    bruto = (valor or "").strip()
    baixo = importar._sem_acento(bruto)
    if not baixo or baixo in {"desconhecido", "unknown", "n/d", "nd"}:
        return {"type": "desconhecido", "text": None}
    if re.search(r"\b(gratis|gratuit[oa]|free|entrada franca)\b", baixo):
        return {"type": "gratis", "text": "Grátis"}
    if re.search(r"\d", bruto):
        return {"type": "pago", "text": bruto[:40]}
    if baixo in {"pago", "paid"}:
        return {"type": "pago", "text": None}
    return {"type": "desconhecido", "text": None}


def cidade_ok(city: str | None) -> bool:
    if not city or not str(city).strip():
        return False
    if importar.cidade_rio(city):
        return True
    return importar._sem_acento(CIDADE) in importar._sem_acento(city)


def motivo_formato_cidade(ev: dict) -> str | None:
    formato = normalizar_formato(str(ev.get("format") or ""))
    if formato == "online":
        return "formato online"
    if formato not in {"presencial", "hibrido"}:
        return "sem formato"
    city = str(ev.get("city") or "").strip()
    if city and not cidade_ok(city):
        return "fora do Rio"
    if not city and OUTRA_CIDADE.search(texto_evento(ev)) and not importar.cidade_rio(texto_evento(ev)):
        return "fora do Rio"
    return None


def copiar_evento(ev: dict) -> dict:
    novo = dict(ev)
    for chave in ("description", "cost"):
        if isinstance(novo.get(chave), dict):
            novo[chave] = dict(novo[chave])
    if isinstance(novo.get("tags"), list):
        novo["tags"] = list(novo["tags"])
    return novo


def limpar_campos(ev: dict) -> None:
    ev["title"] = limpar_privacidade(str(ev.get("title") or "")).strip()
    for campo in ("venue", "address", "city", "organizer", "source"):
        if not ev.get(campo):
            continue
        limpo = limpar_privacidade(str(ev[campo])).strip()
        ev[campo] = limpo or None
    if ev.get("organizer") and "@" in str(ev["organizer"]):
        ev["organizer"] = None
    if ev.get("source") and "@" in str(ev["source"]):
        ev["source"] = None
    desc = ev.get("description")
    if isinstance(desc, dict):
        limpo = {}
        for chave, valor in desc.items():
            if not valor:
                continue
            texto = importar.short(limpar_privacidade(str(valor)), 280)
            if texto:
                limpo[chave] = texto
        ev["description"] = limpo


def garantir_minimo(ev: dict) -> None:
    ev["start"] = importar.to_iso(ev.get("start"))
    ev["end"] = importar.to_iso(ev.get("end")) if ev.get("end") else None
    if ev.get("start"):
        ev["time_known"] = len(str(ev["start"])) > 10
    if ev.get("end") and ev.get("start") and validar.termina_antes(ev):
        ev["end"] = None
    formato = normalizar_formato(str(ev.get("format") or ""))
    if formato:
        ev["format"] = formato
    custo = ev.get("cost")
    if not isinstance(custo, dict) or custo.get("type") not in validar.COSTS:
        ev["cost"] = {"type": "desconhecido", "text": None}
    if ev.get("registration") not in validar.REGS:
        tipo = ev["cost"]["type"]
        ev["registration"] = "livre" if tipo == "gratis" else "ingresso" if tipo == "pago" else "inscricao"
    if not ev.get("status"):
        ev["status"] = "confirmado" if ev.get("start") else "a-confirmar"
    if not ev.get("source") or "@" in str(ev.get("source") or ""):
        ev["source"] = importar._host(str(ev.get("url") or "")) or "correio"


def vocab_tech() -> set[str]:
    return set(json.loads(importar.TAGS.read_text(encoding="utf-8"))["tags"])


def completar_tech(ev: dict, substituir: bool) -> str | None:
    for campo in ("categoria", "idioma", "bairro", "idade_minima", "urls"):
        ev.pop(campo, None)
    vocab = vocab_tech()
    if substituir or not ev.get("tags"):
        ev["tags"] = importar.auto_tags(texto_evento(ev), agenda="tech")
    else:
        ev["tags"] = [t for t in ev["tags"] if t in vocab][:6] or importar.auto_tags(texto_evento(ev), agenda="tech")
    return None


def completar_roles(ev: dict, categoria_dica: str | None, substituir: bool) -> str | None:
    blob = texto_evento(ev)
    tags, categoria = importar.classificar_roles(blob)
    vocab, categorias = validar._vocab_roles()
    if substituir or not ev.get("tags"):
        escolhidas = tags
    else:
        escolhidas = [t for t in ev.get("tags") or [] if t in vocab] or tags
    if importar.marca_de_graca(blob, gratis=(ev.get("cost") or {}).get("type") == "gratis"):
        if "de-graca" not in escolhidas:
            escolhidas.append("de-graca")
    ev["tags"] = escolhidas[:6]
    if categoria_dica == "cultura":
        ev["categoria"] = "cultura"
    elif substituir or not ev.get("categoria"):
        ev["categoria"] = categoria or categoria_dica
    if ev.get("categoria") not in categorias:
        ev.pop("categoria", None)
    if not ev.get("tags"):
        importar.aplicar_padrao(ev, None, ev.get("categoria"))
    if not ev.get("tags"):
        return "fora das categorias"
    if ev.get("idioma") not in validar.IDIOMAS:
        ev.pop("idioma", None)
    if ev.get("cost", {}).get("type") == "gratis" and ev.get("registration") in (None, "", "inscricao"):
        ev["registration"] = "livre"
    bairro = importar.inferir_bairro(blob)
    if bairro and not ev.get("bairro"):
        ev["bairro"] = bairro
    return None


def motivo_antes(ev: dict, exigir_hora: bool) -> str | None:
    if not str(ev.get("title") or "").strip():
        return "sem título"
    if not str(ev.get("url") or "").startswith("https://"):
        return "sem página https"
    if not ev.get("start"):
        return "sem data"
    if exigir_hora and len(str(ev["start"])) <= 10:
        return "sem hora"
    return motivo_formato_cidade(ev)


def problemas(ev: dict, agenda: str) -> list[str]:
    copia = copiar_evento(ev)
    copia["id"] = "2030-01-01-" + (importar.slug(str(ev.get("title") or "evento")) or "evento")
    dados = {"updated": "2026-11-15", "events": [copia]}
    if agenda == "roles":
        vocab, categorias = validar._vocab_roles()
        erros = validar.check(dados, vocab, descartadas=set())
        return erros + validar.erros_extras_roles([copia], categorias)
    return validar.check(dados, vocab_tech(), descartadas=set())


def arquivo_ok(data: dict, agenda: str) -> list[str]:
    if agenda == "roles":
        vocab, categorias = validar._vocab_roles()
        erros = validar.check(data, vocab)
        if isinstance(data.get("events"), list):
            erros += validar.erros_extras_roles(data["events"], categorias)
        return erros
    return validar.check(data, vocab_tech())


def linha(ev: dict, url: str | None = None) -> str:
    titulo = limpar_privacidade(str(ev.get("title") or "Sem título")).strip() or "Sem título"
    link = url or ev.get("url") or ""
    texto = f"{titulo} — {link}".strip(" —") if link else titulo
    return limpar_privacidade(texto).strip()


def nome_agenda(agenda: str) -> str:
    return "Rolês" if agenda == "roles" else "Tech"


def montar_pedido(texto: str) -> dict:
    return {
        "model": MODELO,
        "max_tokens": 8192,
        "system": INSTRUCAO,
        "messages": [{"role": "user", "content": (texto or "")[:MAX_TEXTO]}],
        "tools": [{
            "name": "registrar_eventos",
            "description": "Registra só os eventos que o texto descreve, com data e hora.",
            "strict": True,
            "input_schema": ESQUEMA,
        }],
        "tool_choice": {"type": "tool", "name": "registrar_eventos"},
    }


def ler_resposta(corpo: dict) -> tuple[list[dict], int, int]:
    uso = corpo.get("usage") or {}
    entrada = int(uso.get("input_tokens") or 0)
    entrada += int(uso.get("cache_creation_input_tokens") or 0)
    entrada += int(uso.get("cache_read_input_tokens") or 0)
    saida = int(uso.get("output_tokens") or 0)
    eventos: list[dict] = []
    for bloco in corpo.get("content") or []:
        if not isinstance(bloco, dict) or bloco.get("type") != "tool_use":
            continue
        if bloco.get("name") != "registrar_eventos":
            continue
        entrada_tool = bloco.get("input")
        if isinstance(entrada_tool, str):
            entrada_tool = json.loads(entrada_tool)
        if isinstance(entrada_tool, dict) and isinstance(entrada_tool.get("eventos"), list):
            eventos.extend(item for item in entrada_tool["eventos"] if isinstance(item, dict))
    return eventos, entrada, saida


def chamar_modelo(texto: str, abrir: Callable | None = None) -> tuple[list[dict], int, int]:
    pedido = montar_pedido(limpar_privacidade(texto)[:MAX_TEXTO])
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=json.dumps(pedido).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": os.environ.get("ANTHROPIC_API_KEY") or "",
            "anthropic-version": ANTHROPIC_VERSION,
        },
        method="POST",
    )
    abrir = abrir or urllib.request.urlopen
    try:
        with abrir(req, timeout=60) as resp:
            bruto = resp.read()
    except urllib.error.HTTPError as exc:
        raise ModeloErro(str(exc.code)) from None
    corpo = json.loads(bruto.decode("utf-8"))
    eventos, entrada, saida = ler_resposta(corpo)
    if entrada <= 0:
        entrada = max(1, len(pedido["messages"][0]["content"]) // 4)
    if corpo.get("stop_reason") == "max_tokens":
        raise ModeloIncompleto(entrada, saida)
    return eventos, entrada, saida


def seguir(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": importar.UA})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:  # noqa: S310
            return resp.geturl()
    except Exception:
        return None


def eventos_da_url(url: str, agenda: str) -> tuple[list[dict], str | None]:
    """O mesmo caminho de --url em importar.py."""
    url = importar.clean_url(url)
    try:
        if agenda == "roles":
            corpo, motivo = importar.ler_permitido(url)
            if motivo:
                return [], motivo
            lista = importar.events_from_page(corpo or "", url, "roles")
            if not lista:
                return [], "sem iCal nem schema.org/Event em JSON-LD"
            return lista, None
        ev = importar.event_from_url(url, "tech")
        if not ev:
            return [], "sem dados de evento"
        return [ev], None
    except Exception as exc:  # noqa: BLE001
        return [], f"erro ao abrir: {type(exc).__name__}"


def limpar_url_evento(url: str, abrir: Callable[[str], str | None],
                      filtro: FiltroLinks | None = None) -> str | None:
    url = (url or "").strip()
    if not url.lower().startswith("http"):
        return None
    return resolver_link(url, abrir, filtro)


def evento_do_modelo(item: dict, abrir: Callable[[str], str | None],
                     filtro: FiltroLinks | None = None) -> dict:
    desc = str(item.get("description_pt") or "").strip()
    idioma = str(item.get("language") or "").strip().lower()
    ev = {
        "title": str(item.get("title") or "").strip(),
        "start": str(item.get("start") or "").strip() or None,
        "end": str(item.get("end") or "").strip() or None,
        "venue": str(item.get("venue") or "").strip() or None,
        "address": str(item.get("address") or "").strip() or None,
        "city": str(item.get("city") or "").strip() or None,
        "format": str(item.get("format") or "").strip(),
        "cost": interpretar_custo(str(item.get("cost") or "")),
        "registration": None,
        "url": limpar_url_evento(str(item.get("url") or ""), abrir, filtro),
        "description": {"pt": desc} if desc else {},
        "tags": [],
        "status": "confirmado",
    }
    if idioma in validar.IDIOMAS and idioma != "pt":
        ev["idioma"] = idioma
    return ev


def incorporar(ev: dict, dica: str, categoria_dica: str | None, exigir_hora: bool, substituir: bool,
               hoje, listas: dict, descartadas: set[str], resumo: ResumoCaixa) -> None:
    link = str(ev.get("url") or "")
    if link and url_irrelevante(link):
        return
    resumo.encontrados += 1
    ev = copiar_evento(ev)
    limpar_campos(ev)
    garantir_minimo(ev)
    quando = hoje.isoformat() if hasattr(hoje, "isoformat") else str(hoje)[:10]
    validar.preencher_origem(ev, "correio", quando)
    motivo = motivo_antes(ev, exigir_hora)
    if motivo:
        resumo.descartar(f"{motivo}: {linha(ev)}", ev.get("url"))
        return
    agenda, mudou = escolher_agenda(ev, dica)
    if agenda == "roles":
        erro = completar_roles(ev, categoria_dica, substituir or mudou)
    else:
        erro = completar_tech(ev, substituir or mudou)
    if erro:
        resumo.descartar(f"{erro}: {linha(ev)}", ev.get("url"))
        return
    if not str(ev.get("city") or "").strip():
        ev["city"] = CIDADE
    erros = problemas(ev, agenda)
    if erros:
        resumo.descartar("validação: " + "; ".join(erros), ev.get("url"))
        return
    outra = "roles" if agenda == "tech" else "tech"
    resultado = importar.merge(
        listas[agenda], ev, hoje, descartadas, agenda=agenda, outra=listas.get(outra),
    )
    if resultado == "novo":
        gravado = listas[agenda][-1]
        resumo.novos.append(importar.bloco_novo(gravado, gravado.get("url") or "", agenda))
        if mudou:
            resumo.reclassificados.append(
                f"«{gravado.get('title') or 'Sem título'}» foi para a agenda {nome_agenda(agenda)}; "
                f"a caixa era {nome_agenda(dica)}. {gravado.get('url') or ''}".rstrip()
            )
    elif resultado == "completado":
        resumo.completados.append(linha(ev))
    elif resultado != "igual":
        resumo.descartar(f"{resultado}: {linha(ev)}", ev.get("url"))


def falha_pede_texto(erro: str | None) -> bool:
    """A página não deu o evento: HTTP, robots indisponível ou 503, ou sem JSON-LD.

    Robots que proíbe a leitura não entra: o texto do e-mail não contorna isso.
    """
    if not erro:
        return False
    texto = str(erro).lower()
    if "httperror" in texto or texto.startswith("erro ao abrir"):
        return True
    if "robots.txt falhou" in texto or "robots.txt respondeu" in texto:
        return True
    return "json-ld" in texto


_MESES_LISTA = {
    "january": 1, "jan": 1, "janeiro": 1,
    "february": 2, "feb": 2, "fevereiro": 2,
    "march": 3, "mar": 3, "marco": 3,
    "april": 4, "apr": 4, "abril": 4,
    "may": 5, "maio": 5,
    "june": 6, "jun": 6, "junho": 6,
    "july": 7, "jul": 7, "julho": 7,
    "august": 8, "aug": 8, "agosto": 8,
    "september": 9, "sep": 9, "sept": 9, "setembro": 9,
    "october": 10, "oct": 10, "outubro": 10,
    "november": 11, "nov": 11, "novembro": 11,
    "december": 12, "dec": 12, "dezembro": 12,
}
_MES_ALT = "|".join(sorted(_MESES_LISTA, key=len, reverse=True))
_RE_DATA_NUM = re.compile(
    r"\b(\d{1,2})/(\d{1,2})/(\d{4})(?:[^\d]{0,16}(\d{1,2})[:h](\d{2})(?:\s*(am|pm))?)?"
)
_RE_DATA_MDY = re.compile(
    rf"\b({_MES_ALT})\s+(\d{{1,2}}),?\s+(\d{{4}})"
    rf"(?:[^\d]{{0,16}}(\d{{1,2}})[:h](\d{{2}})(?:\s*(am|pm))?)?",
    re.I,
)
_RE_DATA_DMY = re.compile(
    rf"\b(\d{{1,2}})\s+(?:de\s+)?({_MES_ALT})(?:\s+de)?\s+(\d{{4}})"
    rf"(?:[^\d]{{0,16}}(\d{{1,2}})[:h](\d{{2}})(?:\s*(am|pm))?)?",
    re.I,
)
_RE_URL_LISTA = re.compile(r"https?://[^\s<>()\[\]\"']+", re.I)
_CABECALHO_LISTA = re.compile(
    r"^(concerts this week|this week in|proximos shows|proximos eventos|"
    r"resident advisor|songkick|eventim)\b",
    re.I,
)


def _hora_lista(hora: str | None, minuto: str | None, ampm: str | None) -> tuple[int, int] | None:
    if not hora:
        return None
    h = int(hora)
    m = int(minuto or 0)
    if ampm:
        turno = ampm.lower()
        if turno == "pm" and h < 12:
            h += 12
        elif turno == "am" and h == 12:
            h = 0
    if h > 23 or m > 59:
        return None
    return h, m


def _iso_lista(ano: int, mes: int, dia: int, hora: tuple[int, int] | None) -> str | None:
    try:
        if hora is None:
            return dt.date(ano, mes, dia).isoformat()
        quando = dt.datetime(ano, mes, dia, hora[0], hora[1], tzinfo=importar.RIO)
        return quando.replace(microsecond=0).isoformat()
    except ValueError:
        return None


def parse_data_lista(texto: str) -> str | None:
    """Data de um item de lista (Songkick, Eventim, Resident Advisor)."""
    low = importar._sem_acento(re.sub(r"https?://\S+", " ", texto or ""))
    num = _RE_DATA_NUM.search(low)
    if num:
        return _iso_lista(
            int(num.group(3)), int(num.group(2)), int(num.group(1)),
            _hora_lista(num.group(4), num.group(5), num.group(6)),
        )
    mdy = _RE_DATA_MDY.search(low)
    if mdy:
        return _iso_lista(
            int(mdy.group(3)), _MESES_LISTA[mdy.group(1).lower()], int(mdy.group(2)),
            _hora_lista(mdy.group(4), mdy.group(5), mdy.group(6)),
        )
    dmy = _RE_DATA_DMY.search(low)
    if dmy:
        return _iso_lista(
            int(dmy.group(3)), _MESES_LISTA[dmy.group(2).lower()], int(dmy.group(1)),
            _hora_lista(dmy.group(4), dmy.group(5), dmy.group(6)),
        )
    return None


def _tipo_lista(url: str) -> str | None:
    if url_recusada(url):
        return None
    host = _host_link(url)
    try:
        path = urllib.parse.urlsplit(_chave_url(url)).path.lower()
    except Exception:
        return None
    if host == "songkick.com" or host.endswith(".songkick.com"):
        if "/concerts/" in path or "/festivals/" in path:
            return "songkick"
    if host == "ra.co" or host.endswith(".ra.co"):
        if "/events/" in path:
            return "ra"
    if host == "eventim.com.br" or host.endswith(".eventim.com.br") or host == "eventim.com":
        if "/event" in path:
            return "eventim"
    return None


def _spans_lista(texto: str) -> list[tuple[int, int, str]]:
    spans = []
    for achou in _RE_URL_LISTA.finditer(texto or ""):
        url = achou.group(0).rstrip(".,;:!?)*]>\"'")
        if not _tipo_lista(url):
            continue
        spans.append((achou.start(), achou.end(), url))
    return spans


def _linhas_evento(bloco: str) -> list[str]:
    linhas = []
    for bruto in (bloco or "").splitlines():
        linha = re.sub(r"https?://\S+", " ", bruto)
        linha = re.sub(r"\s+", " ", linha).strip(" -*|•\t")
        if not linha or EMAIL_RE.search(linha):
            continue
        if _CABECALHO_LISTA.search(importar._sem_acento(linha)):
            continue
        linhas.append(linha)
    return linhas


def _linha_preco(linha: str) -> bool:
    low = importar._sem_acento(linha).strip()
    return bool(re.fullmatch(
        r"(gratis|gratuito|gratuita|free|entrada franca|entrada livre|de graca|pago|paid)",
        low,
    ))


def _linha_so_cidade(linha: str) -> bool:
    low = importar._sem_acento(linha).strip()
    if low in {"rio de janeiro", "rio", "rj"}:
        return True
    return bool(OUTRA_CIDADE.fullmatch(low) or _SIGLA_OUTRA_CIDADE.fullmatch(low))


def _casas_rio() -> list[str]:
    """Nome de casa do Rio: a lista fixa e as casas da Agenda Cultural RJ."""
    nomes = {importar._sem_acento(nome) for nome in _CASAS_RIO}
    caminho = importar.ROOT / "fontes_roles.json"
    if caminho.exists():
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            dados = {}
        prefixo = "agenda cultural rj — "
        for fonte in dados.get("fontes") or []:
            nome = importar._sem_acento(str(fonte.get("nome") or ""))
            if not nome.startswith(prefixo):
                continue
            casa = nome[len(prefixo):].strip()
            if casa and casa not in _CASAS_RIO_GENERICAS:
                nomes.add(casa)
    return sorted(nomes, key=len, reverse=True)


def _casa_do_rio(texto: str) -> bool:
    low = importar._sem_acento(texto or "")
    for nome in _casas_rio():
        if re.search(r"(?<!\w)" + re.escape(nome) + r"(?!\w)", low):
            return True
    return importar.inferir_bairro(texto or "") is not None


def _outra_cidade_no_bloco(low: str) -> bool:
    return bool(OUTRA_CIDADE.search(low) or _SIGLA_OUTRA_CIDADE.search(low))


def _songkick_lista_rio(url: str, texto_mail: str) -> bool:
    """«Concerts this week in Rio»: a lista inteira é do Rio, não cada bloco."""
    if _tipo_lista(url) != "songkick":
        return False
    return bool(_SONGKICK_LISTA_RIO.search(importar._sem_acento(texto_mail or "")))


def _cidade_do_bloco(bloco: str, url: str, texto_mail: str) -> tuple[str | None, bool]:
    """Cidade pelo bloco. Devolve (cidade, descartar).

    Rio se o bloco cita Rio, RJ ou uma casa conhecida. Outra cidade (São Paulo,
    SP, BH e o mesmo tipo) descarta o evento. O restante do e-mail não decide,
    salvo o Songkick «concerts this week in Rio».
    """
    low = importar._sem_acento(bloco or "")
    menciona_rio = bool(_RIO_NO_BLOCO.search(low))
    if _outra_cidade_no_bloco(low) and not menciona_rio:
        return None, True
    if menciona_rio or _casa_do_rio(bloco) or _songkick_lista_rio(url, texto_mail):
        return CIDADE, False
    return None, False


def _evento_do_bloco(bloco: str, url: str, texto_mail: str) -> dict | None:
    linhas = _linhas_evento(bloco)
    inicio = None
    indice = None
    for i, linha in enumerate(linhas):
        achou = parse_data_lista(linha)
        if achou:
            inicio = achou
            indice = i
            break
    if not inicio:
        inicio = parse_data_lista(" ".join(linhas))
    if not inicio:
        return None
    outras = []
    for i, linha in enumerate(linhas):
        if i == indice or _linha_preco(linha) or _linha_so_cidade(linha):
            continue
        if parse_data_lista(linha):
            continue
        outras.append(linha)
    if len(outras) < 2:
        return None
    artista = outras[0].strip()
    local = outras[1].strip()
    if not artista:
        return None
    blob = " ".join(linhas)
    gratis = bool(re.search(
        r"\b(gratis|gratuit[oa]|free|entrada franca|de graca)\b",
        importar._sem_acento(blob),
    ))
    descricao = f"Show de {artista} em {local}"
    if gratis:
        descricao += ", com entrada gratuita"
    descricao += "."
    try:
        link = sem_rastreio(url)
    except Exception:
        link = url
    cidade, descartar = _cidade_do_bloco(bloco, url, texto_mail)
    if descartar:
        return None
    return {
        "title": artista,
        "start": inicio,
        "end": None,
        "venue": local,
        "address": None,
        "city": cidade,
        "format": "presencial",
        "cost": {"type": "gratis", "text": "Grátis"} if gratis else {"type": "desconhecido", "text": None},
        "registration": None,
        "url": link,
        "description": {"pt": descricao},
        "tags": ["shows"],
        "categoria": "shows",
        "status": "confirmado",
    }


def _fatias_lista(texto: str) -> list[str]:
    """Um parágrafo por evento. Vários links no mesmo parágrafo: um por link."""
    fatias = []
    for cartao in re.split(r"\n\s*\n", texto or ""):
        cartao = cartao.strip()
        if not cartao:
            continue
        spans = _spans_lista(cartao)
        if not spans:
            continue
        if len(spans) == 1:
            fatias.append(cartao)
            continue
        for i, (ini, fim, _url) in enumerate(spans):
            anterior = spans[i - 1][1] if i else 0
            fatias.append(cartao[anterior:fim])
    return fatias


def eventos_da_lista(texto: str) -> list[dict]:
    """Songkick, Eventim e Resident Advisor: cada item da lista, não só o primeiro."""
    saida = []
    vistos: set[str] = set()
    for fatia in _fatias_lista(texto or ""):
        spans = _spans_lista(fatia)
        if not spans:
            continue
        url = spans[-1][2]
        chave = importar.chave_url(url)
        if not chave or chave in vistos:
            continue
        ev = _evento_do_bloco(fatia, url, texto or "")
        if not ev:
            continue
        vistos.add(chave)
        saida.append(ev)
    return saida


def _somar_tokens(resumo: ResumoCaixa, conta: ContaTokens, entrada: int, saida: int) -> None:
    conta.somar(entrada, saida)
    resumo.entrada += max(0, int(entrada))
    resumo.saida += max(0, int(saida))


def _pelo_modelo(texto: str, dica: str, categoria: str | None, filtro: FiltroLinks, abrir, eventos_url,
                 modelo, conta: ContaTokens, resumo: ResumoCaixa, hoje, listas, descartadas) -> bool:
    if modelo is None:
        resumo.adiados.append("ANTHROPIC_API_KEY ausente")
        return False
    if not conta.pode():
        resumo.adiados.append(f"teto de {MAX_INPUT_TOKENS} tokens de entrada")
        return False
    texto_modelo = limpar_privacidade(texto)[:MAX_TEXTO]
    try:
        extraidos, entrada, saida = modelo(texto_modelo)
    except ModeloIncompleto as exc:
        _somar_tokens(resumo, conta, exc.entrada, exc.saida)
        resumo.adiados.append("modelo devolveu a resposta cortada")
        return False
    except (ModeloErro, urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        resumo.adiados.append("modelo falhou")
        return False
    _somar_tokens(resumo, conta, entrada, saida)
    for item in extraidos or []:
        if not isinstance(item, dict):
            continue
        url = limpar_url_evento(str(item.get("url") or ""), abrir, filtro)
        if url and url_irrelevante(url):
            continue
        if url and host_conhecido(url):
            eventos, erro = eventos_url(url, dica)
            if eventos:
                for ev in eventos:
                    ev = copiar_evento(ev)
                    ev["url"] = limpar_url_evento(str(ev.get("url") or url), abrir, filtro) or url
                    incorporar(ev, dica, categoria, False, False, hoje, listas, descartadas, resumo)
                continue
            if erro and not falha_pede_texto(erro):
                resumo.descartar(f"{erro}: {url}", url)
                continue
        incorporar(evento_do_modelo(item, abrir, filtro), dica, categoria, True, True, hoje, listas, descartadas, resumo)
    return True


def processar_mensagem(raw: bytes, dica: str, *, hoje, listas, descartadas, abrir, eventos_url, modelo,
                       conta: ContaTokens, resumo: ResumoCaixa) -> bool:
    """Processa uma mensagem. Devolve True se ela pode ganhar a etiqueta."""
    resumo.novo_mail()
    try:
        msg, texto, texto_links = ler_mensagem(raw)
    except Exception:
        resumo.descartar("mensagem ilegível")
        return True
    filtro = filtro_da_mensagem(msg)
    categoria = "cultura" if e_cultura(msg) else None
    links = links_uteis(texto_links, abrir, filtro)
    if links:
        falhas_rede = 0
        algum = False
        pedir_texto = False
        for url in links:
            if url_irrelevante(url):
                continue
            eventos, erro = eventos_url(url, dica)
            if erro:
                if falha_pede_texto(erro):
                    pedir_texto = True
                    if str(erro).startswith("erro ao abrir") or "robots.txt" in str(erro).lower():
                        falhas_rede += 1
                    continue
                resumo.descartar(f"{erro}: {url}", url)
                if str(erro).startswith("erro ao abrir"):
                    falhas_rede += 1
                continue
            algum = True
            for ev in eventos:
                if isinstance(ev, dict):
                    ev = copiar_evento(ev)
                    ev["url"] = limpar_url_evento(str(ev.get("url") or url), abrir, filtro) or url
                    incorporar(ev, dica, categoria, False, False, hoje, listas, descartadas, resumo)
        if pedir_texto and not algum:
            return _pelo_modelo(
                texto, dica, categoria, filtro, abrir, eventos_url, modelo, conta, resumo,
                hoje, listas, descartadas,
            )
        if falhas_rede and not algum:
            return False
        return True

    lista = eventos_da_lista(texto)
    if lista:
        for ev in lista:
            incorporar(ev, dica, categoria, False, True, hoje, listas, descartadas, resumo)
        return True
    return _pelo_modelo(
        texto, dica, categoria, filtro, abrir, eventos_url, modelo, conta, resumo,
        hoje, listas, descartadas,
    )


def carregar(path: Path, hoje) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"updated": hoje.isoformat(), "events": []}


def montar_relatorio(resumos: list[ResumoCaixa], conta: ContaTokens, avisos: list[str]) -> str:
    linhas: list[str] = []
    for aviso in avisos:
        linhas.append(f"⚠️ {aviso}")
    if avisos:
        linhas.append("")
    for res in resumos:
        linhas.append(f"## {res.nome} ({res.user})")
        linhas.append("")
        linhas.append(f"- E-mails lidos: {res.lidos}")
        linhas.append(f"- Eventos encontrados: {res.encontrados}")
        linhas.append(f"- Novos: {len(res.novos)}")
        if res.completados:
            linhas.append(f"- Completados: {len(res.completados)}")
        if res.adiados:
            linhas.append(f"- Adiados: {len(res.adiados)}")
            for item in res.adiados:
                linhas.append(f"  - {item}")
        descartes = res.linhas_descartados()
        if descartes:
            linhas.append("- Descartados:")
            for item in descartes:
                linhas.append(f"  - {item}")
        else:
            linhas.append("- Descartados: nenhum")
        if res.reclassificados:
            linhas.append("- Reclassificados:")
            for item in res.reclassificados:
                linhas.append(f"  - {item}")
        for aviso in res.avisos:
            linhas.append(f"- {aviso}")
        linhas.append(f"- Tokens: entrada {res.entrada} · saída {res.saida}")
        if res.novos:
            linhas.append("")
            linhas.append("\n\n".join(res.novos))
        linhas.append("")
    linhas.append("## Total")
    linhas.append("")
    linhas.append(f"- Tokens de entrada: {conta.entrada}")
    linhas.append(f"- Tokens de saída: {conta.saida}")
    if conta.parou:
        linhas.append(
            f"- A rodada parou ao passar de {MAX_INPUT_TOKENS} tokens de entrada. "
            "O restante não foi etiquetado."
        )
    linhas.append("")
    linhas.append("Revise datas, preço e tags antes de aprovar.")
    linhas.append(importar.RODAPE)
    return "\n".join(linhas).rstrip() + "\n"


def rodar(caixas: list[CaixaTrabalho], *, hoje, destinos: dict[str, Path], abrir_redirect, eventos_da_url,
          modelo, dry_run: bool = False, avisos: list[str] | None = None) -> tuple[str, int]:
    avisos = list(avisos or [])
    conta = ContaTokens()
    listas = {}
    mudou = {"tech": False, "roles": False}
    for agenda, path in destinos.items():
        dados = carregar(path, hoje)
        listas[agenda] = dados.setdefault("events", [])
        dados["updated"] = hoje.isoformat()
        listas[agenda + ":doc"] = dados
    descartadas = validar.chaves_descartadas()
    resumos: list[ResumoCaixa] = []
    etiquetas: list[tuple[Callable[[str], None], str]] = []
    for caixa in caixas:
        resumo = ResumoCaixa(caixa.nome, caixa.user)
        if caixa.truncou:
            resumo.avisos.append(
                f"havia mais de {MAX_MENSAGENS} mensagens; as outras ficam para a próxima rodada"
            )
        for uid, raw in caixa.mensagens:
            pode = processar_mensagem(
                raw, caixa.agenda, hoje=hoje, listas=listas, descartadas=descartadas,
                abrir=abrir_redirect, eventos_url=eventos_da_url, modelo=modelo,
                conta=conta, resumo=resumo,
            )
            if pode:
                resumo.lidos += 1
                if caixa.etiquetar and not dry_run:
                    etiquetas.append((caixa.etiquetar, uid))
        resumos.append(resumo)
    for agenda in ("tech", "roles"):
        doc = listas[agenda + ":doc"]
        antes = carregar(destinos[agenda], hoje).get("events") or []
        if len(listas[agenda]) != len(antes) or listas[agenda] != antes:
            mudou[agenda] = True
            doc["events"] = listas[agenda]
            doc["events"].sort(key=lambda e: e.get("start") or "9999")
            doc["updated"] = hoje.isoformat()
    codigo = 0
    falhas: list[str] = []
    for agenda in ("tech", "roles"):
        if not mudou[agenda]:
            continue
        for erro in arquivo_ok(listas[agenda + ":doc"], agenda):
            falhas.append(f"{nome_agenda(agenda)}: {erro}")
    if falhas:
        codigo = 1
        avisos.append("não gravei os JSON: " + " | ".join(falhas))
        mudou = {"tech": False, "roles": False}
    elif not dry_run:
        for agenda in ("tech", "roles"):
            if not mudou[agenda]:
                continue
            destinos[agenda].write_text(
                json.dumps(listas[agenda + ":doc"], ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        for fn, uid in etiquetas:
            try:
                fn(uid)
            except Exception as exc:  # noqa: BLE001
                avisos.append(f"não etiquetei uma mensagem ({type(exc).__name__})")
    return montar_relatorio(resumos, conta, avisos), codigo


def _fechar(conn) -> None:
    try:
        conn.logout()
    except Exception:
        pass


def _caixa_imap(nome: str) -> str:
    """Nome do buzón entre aspas IMAP (espaços em «[Gmail]/All Mail»)."""
    return '"' + nome.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _detalhe_imap(data) -> str:
    if not data:
        return ""
    parte = data[0] if isinstance(data, (list, tuple)) else data
    if isinstance(parte, bytes):
        return parte.decode("utf-8", "replace")
    if parte is None:
        return ""
    return str(parte)


def selecionar(conn) -> str:
    nome = "INBOX"
    try:
        typ, data = conn.list()
    except Exception:
        typ, data = "NO", None
    if typ == "OK":
        for item in data or []:
            if not item:
                continue
            # LIST pode trazer UTF-7 modificado: não decodificar, só texto do fio.
            if isinstance(item, bytes):
                linha_lista = item.decode("ascii", "surrogateescape")
            else:
                linha_lista = str(item)
            flags = linha_lista.split(")", 1)[0]
            if "\\All" not in flags:
                continue
            aspas = re.findall(r'"([^"]*)"', linha_lista)
            if aspas:
                nome = aspas[-1]
                break

    def abrir(caixa: str):
        try:
            return conn.select(_caixa_imap(caixa))
        except imaplib.IMAP4.error as exc:
            detalhe = exc.args[0] if exc.args else str(exc)
            return "NO", [detalhe]

    typ, data = abrir(nome)
    if typ != "OK" and nome != "INBOX":
        typ, data = abrir("INBOX")
        nome = "INBOX"
    if typ != "OK":
        raise RuntimeError(_detalhe_imap(data) or "não foi possível abrir a caixa")
    return nome


def uids_pendentes(conn) -> tuple[list[str], bool]:
    typ, data = conn.uid("SEARCH", "X-GM-RAW", '"' + BUSCA + '"')
    if typ != "OK" or not data or data[0] in (None, b"", ""):
        return [], False
    bruto = data[0]
    if isinstance(bruto, bytes):
        bruto = bruto.decode("utf-8", "replace")
    uids = str(bruto).split()
    return uids[:MAX_MENSAGENS], len(uids) > MAX_MENSAGENS


def ler_uid(conn, uid: str) -> tuple[bytes | None, bool]:
    typ, data = conn.uid("FETCH", uid, "(X-GM-LABELS RFC822)")
    if typ != "OK" or not data:
        return None, False
    raw = None
    labels: list[str] = []
    for item in data:
        if isinstance(item, tuple):
            meta = item[0] if item else b""
            body = item[1] if len(item) > 1 else b""
            if isinstance(meta, bytes):
                labels.append(meta.decode("utf-8", "replace"))
            if isinstance(body, bytes):
                raw = body
        elif isinstance(item, bytes):
            labels.append(item.decode("utf-8", "replace"))
    return raw, ROTULO in " ".join(labels)


def marcar(conn, uid: str) -> None:
    typ, _ = conn.uid("STORE", uid, "+X-GM-LABELS", f'("{ROTULO}")')
    if typ != "OK":
        raise OSError("não foi possível etiquetar")


class Conexao:
    def __init__(self, conn):
        self.conn = conn

    def pendentes(self) -> tuple[list[tuple[str, bytes]], bool]:
        uids, truncou = uids_pendentes(self.conn)
        saida = []
        for uid in uids:
            raw, ja = ler_uid(self.conn, uid)
            if raw and not ja:
                saida.append((uid, raw))
        return saida, truncou

    def etiquetar(self, uid: str) -> None:
        marcar(self.conn, uid)

    def fechar(self) -> None:
        _fechar(self.conn)


def abrir_conexao(user: str, senha: str) -> Conexao:
    conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    try:
        conn.login(user, senha)
    except imaplib.IMAP4.error:
        _fechar(conn)
        raise FalhaEntrada() from None
    try:
        selecionar(conn)
    except Exception:
        _fechar(conn)
        raise
    return Conexao(conn)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="não grava o JSON nem etiqueta as mensagens")
    ap.add_argument("--relatorio", type=Path, help="grava o resumo em Markdown (corpo do PR)")
    args = ap.parse_args(argv)

    hoje = dt.datetime.now(importar.RIO).date()
    avisos: list[str] = []
    presentes = [c for c in CAIXAS if os.environ.get(c["senha_env"]) or ""]
    if not presentes:
        texto = "aviso: " + " e ".join(c["senha_env"] for c in CAIXAS) + " ausentes; nada foi lido"
        print(texto, file=sys.stderr)
        if args.relatorio:
            args.relatorio.write_text(texto + "\n", encoding="utf-8")
        return 0
    for spec in CAIXAS:
        if spec not in presentes:
            msg = f"{spec['senha_env']} ausente; a caixa {spec['nome']} não foi lida"
            avisos.append(msg)
            print("aviso: " + msg, file=sys.stderr)
    if os.environ.get("ANTHROPIC_API_KEY"):
        modelo = chamar_modelo
    else:
        modelo = None
        msg = "ANTHROPIC_API_KEY ausente; newsletters sem link conhecido ficam para a próxima rodada"
        avisos.append(msg)
        print("aviso: " + msg, file=sys.stderr)

    caixas: list[CaixaTrabalho] = []
    conexoes: list[Conexao] = []
    codigo = 0
    try:
        for spec in presentes:
            senha = os.environ.get(spec["senha_env"]) or ""
            try:
                conexao = abrir_conexao(spec["user"], senha)
            except FalhaEntrada:
                msg = f"não foi possível entrar na caixa {spec['nome']}"
                avisos.append(msg)
                print("aviso: " + msg, file=sys.stderr)
                continue
            except OSError as exc:
                msg = f"sem conexão com a caixa {spec['nome']} ({type(exc).__name__})"
                avisos.append(msg)
                print("aviso: " + msg, file=sys.stderr)
                continue
            conexoes.append(conexao)
            mensagens, truncou = conexao.pendentes()
            caixas.append(CaixaTrabalho(
                nome=spec["nome"],
                user=spec["user"],
                agenda=spec["agenda"],
                mensagens=mensagens,
                etiquetar=None if args.dry_run else conexao.etiquetar,
                truncou=truncou,
            ))
        relatorio, codigo = rodar(
            caixas,
            hoje=hoje,
            destinos=caminhos(),
            abrir_redirect=seguir,
            eventos_da_url=eventos_da_url,
            modelo=modelo,
            dry_run=args.dry_run,
            avisos=avisos,
        )
    finally:
        for conexao in conexoes:
            conexao.fechar()
    if args.relatorio:
        args.relatorio.write_text(relatorio, encoding="utf-8")
    print(relatorio, end="" if relatorio.endswith("\n") else "\n")
    return codigo


if __name__ == "__main__":
    sys.exit(main())
