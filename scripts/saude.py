#!/usr/bin/env python3
"""Relatório semanal da agenda. Não grava data/events.json.

Conta eventos à frente, sonda cada fonte de fontes.json e lista PRs do
importador. Cria ou atualiza uma única issue aberta com a etiqueta
saude-da-agenda.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RIO = dt.timezone(dt.timedelta(hours=-3))
UA = "Mozilla/5.0 (compatible; AgendaRioTech/1.0; +https://github.com)"
LEMBRETE = "Exportar o chat do WhatsApp do grupo e rodar scripts/semanal.sh"


def contar(events: list[dict], hoje: dt.date) -> tuple[int, int]:
    """Eventos com início entre hoje e daqui a 14 dias, e entre hoje e 30 dias."""
    n14 = n30 = 0
    fim14 = hoje + dt.timedelta(days=14)
    fim30 = hoje + dt.timedelta(days=30)
    for ev in events:
        start = ev.get("start")
        if not start or len(str(start)) < 10:
            continue
        try:
            dia = dt.date.fromisoformat(str(start)[:10])
        except ValueError:
            continue
        if hoje <= dia <= fim30:
            n30 += 1
        if hoje <= dia <= fim14:
            n14 += 1
    return n14, n30


def analisar_ics(text: str) -> tuple[int, dt.date | None]:
    """Número de VEVENT e a data mais recente de DTSTART."""
    text = re.sub(r"\r?\n[ \t]", "", text)
    datas: list[dt.date] = []
    blocos = re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S)
    for bloco in blocos:
        m = re.search(r"^DTSTART[^:\n]*:(\d{8})", bloco, re.M)
        if not m:
            continue
        ymd = m.group(1)
        try:
            datas.append(dt.date(int(ymd[0:4]), int(ymd[4:6]), int(ymd[6:8])))
        except ValueError:
            continue
    return len(blocos), (max(datas) if datas else None)


def fonte_preocupa(ativo: bool, status: int | None, n: int, ultima: dt.date | None, hoje: dt.date) -> bool:
    """Fonte ativa com erro, sem VEVENT, ou sem evento novo há 60 dias ou mais."""
    if ativo is False:
        return False
    if status is None or status >= 400 or n == 0 or ultima is None:
        return True
    return ultima <= hoje - dt.timedelta(days=60)


def pr_velho(created: str, agora: dt.datetime) -> bool:
    """Aberto há mais de 7 dias."""
    instante = dt.datetime.fromisoformat(created.replace("Z", "+00:00"))
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=dt.timezone.utc)
    return instante < agora - dt.timedelta(days=7)


def linha_fonte(nome: str, ativo: bool, status: int | None, n: int, ultima: dt.date | None, preocupa: bool) -> str:
    http = str(status) if status is not None else "erro"
    quando = ultima.isoformat() if ultima else "nenhum"
    estado = "inativa" if ativo is False else "ativa"
    titulo = f"{nome} ⚠️" if preocupa else nome
    return f"| {titulo} | {estado} | {http} | {n} | {quando} |"


def montar(
    hoje: dt.date,
    n14: int,
    n30: int,
    fontes: list[str],
    prs: list[dict],
    erro_prs: str | None,
    agora: dt.datetime | None = None,
) -> str:
    linhas = [
        "## Saúde da agenda",
        "",
        f"Atualizado em {hoje.isoformat()} (horário do Rio).",
        "",
        "### Eventos à frente",
        f"- Próximos 14 dias: {n14}" + (" ⚠️" if n14 < 4 else ""),
        f"- Próximos 30 dias: {n30}",
        "",
        "### Fontes",
        "",
        "Último evento novo é o DTSTART mais recente do calendário. Fonte ativa com erro, sem VEVENT ou com o último evento há 60 dias ou mais leva ⚠️.",
        "",
        "| Fonte | Estado | HTTP | VEVENT | Último evento novo |",
        "| --- | --- | --- | --- | --- |",
        *fontes,
        "",
        "### PRs do importador",
        "",
    ]
    if erro_prs:
        linhas.append(f"⚠️ Não deu para listar os PRs com a etiqueta importacao-automatica ({erro_prs}).")
    elif not prs:
        linhas.append("Nenhum PR aberto com a etiqueta importacao-automatica.")
    else:
        agora = agora or dt.datetime.now(dt.timezone.utc)
        for pr in prs:
            quando = str(pr.get("createdAt") or "")[:10]
            marca = " ⚠️ há mais de 7 dias" if pr.get("createdAt") and pr_velho(pr["createdAt"], agora) else ""
            linhas.append(f"- #{pr.get('number')} {pr.get('title') or ''} — aberto em {quando}{marca}")
    linhas += ["", "### Lembrete", "", LEMBRETE, ""]
    return "\n".join(linhas)


def buscar_fonte(url: str) -> tuple[int | None, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/calendar,text/plain,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (URLs públicas de fontes.json)
            status = getattr(resp, "status", None) or resp.getcode()
            return status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception:  # noqa: BLE001
        return None, ""


def listar_prs() -> tuple[list[dict] | None, str | None]:
    r = subprocess.run(
        ["gh", "pr", "list", "--label", "importacao-automatica", "--state", "open",
         "--json", "number,title,createdAt,url"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "gh pr list falhou").strip().splitlines()
        return None, (msg[-1] if msg else "gh pr list falhou")[:300]
    try:
        dados = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        return None, "resposta do gh não é JSON"
    return dados, None


def publicar(corpo: str) -> str:
    lista = subprocess.run(
        ["gh", "issue", "list", "--label", "saude-da-agenda", "--state", "open",
         "--json", "number,url", "--limit", "20"],
        check=True, capture_output=True, text=True,
    )
    abertas = sorted(json.loads(lista.stdout or "[]"), key=lambda i: i["number"])
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as tmp:
        tmp.write(corpo)
        caminho = tmp.name
    try:
        if abertas:
            alvo = abertas[0]
            subprocess.run(["gh", "issue", "edit", str(alvo["number"]), "--body-file", caminho], check=True)
            return alvo.get("url") or f"#{alvo['number']}"
        criada = subprocess.run(
            ["gh", "issue", "create", "--title", "Saúde da agenda",
             "--label", "saude-da-agenda", "--body-file", caminho],
            check=True, capture_output=True, text=True,
        )
        return criada.stdout.strip()
    finally:
        Path(caminho).unlink(missing_ok=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="imprime o relatório e não cria issue")
    args = ap.parse_args(argv)

    hoje = dt.datetime.now(RIO).date()
    events = json.loads((ROOT / "data" / "events.json").read_text(encoding="utf-8"))["events"]
    n14, n30 = contar(events, hoje)
    linhas = []
    for fonte in json.loads((ROOT / "fontes.json").read_text(encoding="utf-8")).get("fontes", []):
        status, corpo = buscar_fonte(fonte["url"])
        n, ultima = analisar_ics(corpo) if corpo else (0, None)
        ativo = fonte.get("ativo", True)
        linhas.append(linha_fonte(
            fonte.get("nome") or fonte["url"], ativo is not False, status, n, ultima,
            fonte_preocupa(ativo, status, n, ultima, hoje),
        ))
    prs, erro = listar_prs()
    texto = montar(hoje, n14, n30, linhas, prs or [], erro)
    if args.dry_run:
        print(texto)
        return 0
    print(publicar(texto))
    return 0


if __name__ == "__main__":
    sys.exit(main())
