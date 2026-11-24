#!/usr/bin/env python3
"""Resume eventos futuros que ainda não têm «resumo».

O texto sai só do título e da descrição real (descricao_completa, ou
description se ela não for o aviso genérico da Luma). Não inventa. Cada
idioma fica em uma ou duas frases, com no máximo 240 caracteres.

    python3 scripts/resumir.py
    python3 scripts/resumir.py --agenda tech
    python3 scripts/resumir.py --dry-run

Usa a API da Anthropic (claude-haiku-5-5) por urllib, com tool use e
esquema estrito. Sem ANTHROPIC_API_KEY, não faz nada e termina sem erro.
O mesmo id não é pedido duas vezes na mesma rodada.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import importar
import validar

ROOT = Path(__file__).resolve().parents[1]
DESTINOS = {
    "tech": ROOT / "data" / "events.json",
    "roles": ROOT / "data" / "roles.json",
}
NOMES = {"tech": "Tech", "roles": "Rolês"}
MODELO = "claude-haiku-5-5"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2026-10-21"
MAX_FONTE = 6000
_FRASE = re.compile(r"[.!?…]+")

ESQUEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["suficiente", "pt", "en", "es"],
    "properties": {
        "suficiente": {
            "type": "boolean",
            "description": "false se o título e a descrição não bastam para dizer o que é, para quem é e o que acontece.",
        },
        "pt": {"type": "string", "description": "Uma ou duas frases em português, até 240 caracteres. Vazio se suficiente for false."},
        "en": {"type": "string", "description": "One or two sentences in English, up to 240 characters. Empty if suficiente is false."},
        "es": {"type": "string", "description": "Una o dos frases en español, hasta 240 caracteres. Vacío si suficiente es false."},
    },
}
INSTRUCAO = (
    "Você resume um evento para a agenda, em português, inglês e espanhol. "
    "Use somente o título e a descrição recebidos. Não invente público, programa, "
    "preço, data, lugar, organizador nem o que acontece. "
    "Cada idioma: uma ou duas frases, no máximo 240 caracteres. "
    "Diga o que é, para quem é e o que acontece, só quando o texto disser. "
    "Se o título e a descrição não bastarem para isso, marque suficiente como false "
    "e deixe pt, en e es vazios. "
    "Não copie o aviso genérico de calendário "
    "(Obtenha informações atualizadas, Get up-to-date information, Organizado por)."
)


class ModeloErro(Exception):
    pass


def ainda_vai_acontecer(ev: dict, hoje: dt.date) -> bool:
    fim = str(ev.get("end") or ev.get("start") or "")[:10]
    try:
        return dt.date.fromisoformat(fim) >= hoje
    except ValueError:
        return False


def tem_resumo(ev: dict) -> bool:
    resumo = ev.get("resumo")
    if not isinstance(resumo, dict):
        return False
    return all(isinstance(resumo.get(lingua), str) and resumo[lingua].strip() for lingua in validar.RESUMO_IDIOMAS)


def fonte_do_resumo(ev: dict) -> tuple[str, str] | None:
    """Título e descrição real. Sem os dois, não há o que resumir."""
    titulo = str(ev.get("title") or "").strip()
    if not titulo:
        return None
    completa = ev.get("descricao_completa")
    if isinstance(completa, str) and completa.strip() and not validar.descricao_luma_generica(completa):
        descricao = completa.strip()
    else:
        desc = ev.get("description") or {}
        partes: list[str] = []
        if isinstance(desc, dict):
            for lingua in validar.RESUMO_IDIOMAS:
                texto = desc.get(lingua)
                if isinstance(texto, str) and texto.strip() and not validar.descricao_luma_generica(texto):
                    partes.append(texto.strip())
        descricao = "\n".join(partes).strip()
    if not descricao:
        return None
    return titulo, descricao[:MAX_FONTE]


def _frases(texto: str) -> int:
    return len([p for p in _FRASE.split(texto.strip()) if p.strip()])


def interpretar(item: dict | None) -> dict | None:
    """Aceita o resumo só se os três idiomas couberem no esquema. Não corta."""
    if not isinstance(item, dict) or item.get("suficiente") is not True:
        return None
    saida: dict[str, str] = {}
    for lingua in validar.RESUMO_IDIOMAS:
        texto = re.sub(r"\s+", " ", str(item.get(lingua) or "")).strip()
        if not texto or len(texto) > validar.RESUMO_MAX:
            return None
        if _frases(texto) < 1 or _frases(texto) > 2:
            return None
        if validar.descricao_luma_generica(texto):
            return None
        saida[lingua] = texto
    return saida


def montar_pedido(titulo: str, descricao: str) -> dict:
    return {
        "model": MODELO,
        "max_tokens": 1024,
        "system": INSTRUCAO,
        "messages": [{
            "role": "user",
            "content": f"Título: {titulo}\n\nDescrição:\n{descricao}",
        }],
        "tools": [{
            "name": "registrar_resumo",
            "description": "Registra o resumo só com o que o título e a descrição dizem.",
            "strict": True,
            "input_schema": ESQUEMA,
        }],
        "tool_choice": {"type": "tool", "name": "registrar_resumo"},
    }


def _uso(corpo: dict) -> tuple[int, int]:
    uso = corpo.get("usage") or {}
    entrada = int(uso.get("input_tokens") or 0)
    entrada += int(uso.get("cache_creation_input_tokens") or 0)
    entrada += int(uso.get("cache_read_input_tokens") or 0)
    saida = int(uso.get("output_tokens") or 0)
    return entrada, saida


def ler_resposta(corpo: dict) -> tuple[dict | None, int, int]:
    entrada, saida = _uso(corpo)
    for bloco in corpo.get("content") or []:
        if not isinstance(bloco, dict) or bloco.get("type") != "tool_use":
            continue
        if bloco.get("name") != "registrar_resumo":
            continue
        dado = bloco.get("input")
        if isinstance(dado, str):
            dado = json.loads(dado)
        if isinstance(dado, dict):
            return dado, entrada, saida
    return None, entrada, saida


def chamar_modelo(titulo: str, descricao: str, abrir=None) -> tuple[dict | None, int, int]:
    pedido = montar_pedido(titulo, descricao)
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
    return ler_resposta(json.loads(bruto.decode("utf-8")))


def _gravar(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rodar(agendas: list[str], hoje: dt.date, chamar, destinos: dict[str, Path] | None = None, gravar: bool = True) -> str:
    """Preenche resumo nos eventos futuros que ainda não têm. Devolve o relatório."""
    destinos = destinos or DESTINOS
    cache: dict[str, dict | None] = {}
    entrada = saida = falhas = 0
    linhas: list[str] = []
    for agenda in agendas:
        path = destinos[agenda]
        data = json.loads(path.read_text(encoding="utf-8"))
        eventos = data.get("events") if isinstance(data, dict) else None
        if not isinstance(eventos, list):
            linhas.append(f"{NOMES.get(agenda, agenda)}: arquivo sem lista de eventos")
            continue
        novos = sem = passados = ja = fracos = 0
        mudou = False
        for ev in eventos:
            if not isinstance(ev, dict):
                continue
            if not ainda_vai_acontecer(ev, hoje):
                passados += 1
                continue
            if tem_resumo(ev):
                ja += 1
                continue
            fonte = fonte_do_resumo(ev)
            if not fonte:
                sem += 1
                continue
            ident = str(ev.get("id") or "")
            if ident and ident in cache:
                pronto = cache[ident]
            else:
                try:
                    bruto, ent, sai = chamar(*fonte)
                except (ModeloErro, urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
                    falhas += 1
                    continue
                entrada += max(0, int(ent))
                saida += max(0, int(sai))
                pronto = interpretar(bruto)
                if ident:
                    cache[ident] = pronto
            if not pronto:
                fracos += 1
                continue
            ev["resumo"] = dict(pronto)
            novos += 1
            mudou = True
        if mudou and gravar:
            data["updated"] = hoje.isoformat()
            _gravar(path, data)
        linhas.append(
            f"{NOMES.get(agenda, agenda)}: {novos} resumos · {ja} já tinham · {sem} sem descrição · {fracos} sem informação · {passados} passados"
        )
    linhas.append(f"tokens: entrada {entrada} · saída {saida}")
    if falhas:
        linhas.append(f"avisos: {falhas} chamada falhou" if falhas == 1 else f"avisos: {falhas} chamadas falharam")
    return "\n".join(linhas)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agenda", choices=["tech", "roles"], help="só uma agenda; sem isto, Tech e Rolês")
    ap.add_argument("--dry-run", action="store_true", help="não grava o JSON")
    args = ap.parse_args(argv)
    if not (os.environ.get("ANTHROPIC_API_KEY") or "").strip():
        print("ANTHROPIC_API_KEY ausente; nenhum resumo foi gerado")
        print("tokens: entrada 0 · saída 0")
        return 0
    hoje = dt.datetime.now(importar.RIO).date()
    agendas = [args.agenda] if args.agenda else ["tech", "roles"]
    print(rodar(agendas, hoje, chamar_modelo, gravar=not args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
