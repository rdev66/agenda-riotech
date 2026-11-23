#!/usr/bin/env python3
"""Relatório de contribuição e confiança por fonte. Não grava a agenda.

Para cada fonte, nos últimos 30 e 90 dias (pela data em que ela viu o
evento, ou pela data do descarte):

  - eventos que ela contribuiu
  - únicos (só essa fonte viu)
  - primeira a anunciar (a data dela é a mais cedo; empate no dia conta)
  - percentagem com mudança posterior de data, fim, local ou status
  - percentagem cancelada
  - descartes, por motivo

Entra na issue semanal «Saúde da agenda».
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DATA = re.compile(r"\d{4}-\d{2}-\d{2}")
JANELAS = (30, 90)


def _dia(valor: str | None) -> dt.date | None:
    if not isinstance(valor, str) or not _DATA.fullmatch(valor):
        return None
    try:
        return dt.date.fromisoformat(valor)
    except ValueError:
        return None


def na_janela(valor: str | None, hoje: dt.date, dias: int) -> bool:
    dia = _dia(valor)
    if dia is None:
        return False
    return hoje - dt.timedelta(days=dias) <= dia <= hoje


def _datas_por_fonte(ev: dict) -> dict[str, str]:
    """Fonte → data mais cedo em que ela viu o evento."""
    datas: dict[str, str] = {}
    for item in ev.get("vistos") or []:
        if not isinstance(item, dict):
            continue
        fonte = item.get("fonte")
        data = item.get("data")
        if not isinstance(fonte, str) or _dia(data) is None:
            continue
        if fonte not in datas or data < datas[fonte]:
            datas[fonte] = data
    return datas


def _mudou(ev: dict) -> bool:
    hist = ev.get("historico")
    return isinstance(hist, list) and any(isinstance(item, dict) for item in hist)


def _cancelado(ev: dict) -> bool:
    if ev.get("status") == "cancelado":
        return True
    for item in ev.get("historico") or []:
        if not isinstance(item, dict) or item.get("campo") != "status":
            continue
        depois = str(item.get("depois") or "").strip().lower()
        if depois in {"cancelado", "cancelled", "canceled"}:
            return True
    return False


def _pct(parte: int, total: int) -> str:
    if total <= 0:
        return "—"
    return f"{round(100 * parte / total)}%"


def _celula(texto: str) -> str:
    return str(texto).replace("|", "/").replace("\n", " ")


def _linha_descartes(motivos: Counter) -> str:
    if not motivos:
        return "0"
    partes = [f"{_celula(motivo)} ({n})" for motivo, n in sorted(motivos.items(), key=lambda par: (-par[1], par[0]))]
    return "; ".join(partes)


def relatorio(eventos: list[dict], descartes: list[dict], hoje: dt.date) -> str:
    """Markdown com uma tabela por janela. eventos inclui Tech e Rolês."""
    por_fonte_datas = [_datas_por_fonte(ev) for ev in eventos]
    linhas = [
        "### Fontes: contribuição e confiança",
        "",
        "A data é o dia em que a fonte viu o evento (`vistos.data`) ou, no descarte, o dia do registro. "
        "«Únicos» é evento que só essa fonte viu. «Primeira» é quem anunciou no dia mais cedo "
        "(empate no mesmo dia conta para as duas). «Mudou» teve alteração posterior de data, fim, local ou status. "
        "«Cancelado» está com status cancelado ou o histórico marca cancelamento. "
        "A mesma URL da plataforma aplica data, fim, local e status. Correio, WhatsApp "
        "e outra plataforma só entram no histórico e na lista «a revisar».",
        "",
    ]
    for dias in JANELAS:
        contrib: dict[str, list[int]] = defaultdict(list)
        for i, datas in enumerate(por_fonte_datas):
            for fonte, data in datas.items():
                if na_janela(data, hoje, dias):
                    contrib[fonte].append(i)
        motivos: dict[str, Counter] = defaultdict(Counter)
        for item in descartes:
            if not isinstance(item, dict):
                continue
            fonte = item.get("fonte")
            if not isinstance(fonte, str) or not na_janela(item.get("data"), hoje, dias):
                continue
            motivos[fonte][str(item.get("motivo") or "sem motivo")] += 1
        fontes = sorted(set(contrib) | set(motivos), key=lambda f: (-len(contrib.get(f, [])), f))
        linhas.append(f"#### Últimos {dias} dias")
        linhas.append("")
        if not fontes:
            linhas.append("Nenhuma fonte neste período.")
            linhas.append("")
            continue
        linhas.append("| Fonte | Eventos | Únicos | Primeira | Mudou | Cancelado | Descartes |")
        linhas.append("| --- | ---: | ---: | ---: | ---: | ---: | --- |")
        for fonte in fontes:
            idxs = contrib.get(fonte, [])
            unicos = primeira = mudou = cancelado = 0
            for i in idxs:
                datas = por_fonte_datas[i]
                if set(datas) == {fonte}:
                    unicos += 1
                if datas and datas[fonte] == min(datas.values()):
                    primeira += 1
                ev = eventos[i]
                if _mudou(ev):
                    mudou += 1
                if _cancelado(ev):
                    cancelado += 1
            n = len(idxs)
            linhas.append(
                f"| {_celula(fonte)} | {n} | {unicos} | {primeira} | {_pct(mudou, n)} | "
                f"{_pct(cancelado, n)} | {_linha_descartes(motivos.get(fonte, Counter()))} |"
            )
        linhas.append("")
    return "\n".join(linhas).rstrip() + "\n"


def a_revisar(eventos: list[dict]) -> str:
    """Mudança que outra fonte viu e a agenda ainda não aplicou."""
    itens = []
    for ev in eventos:
        if not isinstance(ev, dict):
            continue
        titulo = _celula(ev.get("title") or ev.get("id") or "evento")
        for item in ev.get("historico") or []:
            if not isinstance(item, dict) or item.get("aplicado") is not False:
                continue
            campo = item.get("campo")
            publicado = ev.get(campo)
            if publicado != item.get("antes") or publicado == item.get("depois"):
                continue
            itens.append(
                f"- **{titulo}** — {campo}: «{_celula(item.get('antes') or '')}» → "
                f"«{_celula(item.get('depois') or '')}» ({_celula(item.get('fonte') or '')}, {item.get('data') or ''})"
            )
    linhas = ["### A revisar", ""]
    if not itens:
        linhas.append("Nada a revisar.")
    else:
        linhas.append(
            "Correio, WhatsApp ou outra plataforma viu data, fim, local ou status diferente. "
            "O valor publicado não mudou."
        )
        linhas.append("")
        linhas.extend(itens)
    return "\n".join(linhas).rstrip() + "\n"


def main(argv=None) -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hoje", help="AAAA-MM-DD; padrão é hoje no fuso da agenda")
    args = ap.parse_args(argv)
    import validar
    hoje = dt.date.fromisoformat(args.hoje) if args.hoje else dt.datetime.now(validar.FUSO).date()
    eventos: list[dict] = []
    for nome in ("events.json", "roles.json"):
        dados = json.loads((ROOT / "data" / nome).read_text(encoding="utf-8"))
        eventos.extend(ev for ev in dados.get("events") or [] if isinstance(ev, dict))
    bruto = validar.ler_descartados(ROOT / "data" / "descartados.json")
    descartes = bruto.get("urls") if isinstance(bruto, dict) else []
    sys.stdout.write(relatorio(eventos, descartes or [], hoje))
    return 0


if __name__ == "__main__":
    sys.exit(main())
