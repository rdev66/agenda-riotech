#!/usr/bin/env python3
"""Preenche fonte, via e vistos a partir de «source». Roda uma vez.

luma.com (e os outros domínios soltos) sem calendário conhecido fica com via
«whatsapp» quando «added» cai num dia em que o git registra importação do
WhatsApp. Nos outros dias, via «desconhecida». Calendário listado em
fontes.json ou fontes_roles.json fica com via «feed».

Não apaga «source». Não mexe num evento que já tem fonte, via e vistos.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import validar

ROOT = Path(__file__).resolve().parents[1]
_DATA = re.compile(r"\d{4}-\d{2}-\d{2}")


def extrair_datas_whatsapp(assuntos: str, ramos: str) -> set[str]:
    """Datas citadas num assunto ou ramo que fala de WhatsApp."""
    datas: set[str] = set()
    for linha in (assuntos or "").splitlines():
        if re.search(r"whatsapp", linha, re.I):
            datas.update(_DATA.findall(linha))
    for linha in (ramos or "").splitlines():
        if "whatsapp" in linha.lower():
            datas.update(_DATA.findall(linha))
    return datas


def datas_whatsapp(repo: Path | None = None) -> set[str]:
    """Lê o git do repositório. Não abre exportação de chat."""
    raiz = repo or ROOT

    def saida(*args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(raiz), *args],
            capture_output=True, text=True,
        )
        return proc.stdout if proc.returncode == 0 else ""

    return extrair_datas_whatsapp(
        saida("log", "--all", "--format=%s"),
        saida("branch", "-a"),
    )


def _ja_tem_origem(ev: dict) -> bool:
    return bool(
        ev.get("fonte") and ev.get("via")
        and isinstance(ev.get("vistos"), list) and ev["vistos"]
    )


def migrar_evento(ev: dict, tabela: validar.TabelaFontes, datas: set[str]) -> bool:
    """Preenche fonte, via e vistos. Devolve False se já estava preenchido."""
    if _ja_tem_origem(ev):
        return False
    fonte, conhecido = validar.resolver(ev.get("source"), ev.get("url"), tabela)
    added = str(ev.get("added") or "")
    if not _DATA.fullmatch(added):
        added = "1970-01-01"
    via = validar.via_migrada(fonte, conhecido, added, datas)
    ev["fonte"] = fonte
    ev["via"] = via
    ev["vistos"] = [{"fonte": fonte, "via": via, "data": added}]
    return True


def migrar_descarte(item: dict, tabela: validar.TabelaFontes, datas: set[str]) -> bool:
    """Fonte e via de um descarte novo, a partir da URL."""
    if item.get("fonte") and item.get("via"):
        return False
    fonte, conhecido = validar.resolver(None, item.get("url"), tabela)
    dia = str(item.get("data") or "")
    item["fonte"] = fonte
    item["via"] = validar.via_migrada(fonte, conhecido, dia, datas)
    return True


def _gravar(path: Path, dados: dict) -> None:
    path.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def migrar_arquivos(root: Path | None = None, datas: set[str] | None = None) -> dict[str, int]:
    """Atualiza events.json, roles.json e descartados.json. Devolve quantos mudaram."""
    base = root or ROOT
    tabela = validar.tabela_fontes(base)
    dias = datas if datas is not None else datas_whatsapp(base)
    contagem: dict[str, int] = {}
    for nome in ("events.json", "roles.json"):
        path = base / "data" / nome
        dados = json.loads(path.read_text(encoding="utf-8"))
        n = 0
        for ev in dados.get("events") or []:
            if isinstance(ev, dict) and migrar_evento(ev, tabela, dias):
                n += 1
        if n:
            _gravar(path, dados)
        contagem[nome] = n
    path = base / "data" / "descartados.json"
    dados = json.loads(path.read_text(encoding="utf-8"))
    n = 0
    for item in dados.get("urls") or []:
        if isinstance(item, dict) and migrar_descarte(item, tabela, dias):
            n += 1
    if n:
        _gravar(path, dados)
    contagem["descartados.json"] = n
    return contagem


def main(argv=None) -> int:
    contagem = migrar_arquivos()
    for nome, n in contagem.items():
        print(f"{nome}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
