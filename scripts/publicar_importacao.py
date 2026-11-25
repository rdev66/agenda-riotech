#!/usr/bin/env python3
"""Publica a importação automática na main, ou deixa a revisão para um PR.

Fluxo: atualiza a main (git pull --rebase), importa, resume, roda
scripts/validar.py e os testes. Se está tudo verde e há mudança, o commit
é «Importação automática (<agenda>, AAAA-MM-DD)» e o push vai para a main.
Se o push falha porque a main andou, faz rebase e tenta de novo, até 3
vezes; se o rebase conflita, importa de novo. Se a validação falha, não
mexe na main.

O workflow abre o PR de revisão (peter-evans/create-pull-request) quando
este script devolve revisar=true. O relatório vai para o resumo do job e
para a issue semanal «Saúde da agenda».

No fluxo correio, a etiqueta agenda/processado só entra depois de um push
bem-sucedido na main, nos UIDs que importar_correio.py guardou. Revisão ou
falha não etiqueta: a próxima rodada lê de novo.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
RIO = ZoneInfo("America/Sao_Paulo")
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
BOT_NOME = "github-actions[bot]"
PERMITIDOS = frozenset({"data/events.json", "data/roles.json"})
TENTATIVAS = 3


def dia_rio(agora: dt.datetime | None = None) -> str:
    """Data civil em America/Sao_Paulo."""
    if agora is None:
        agora = dt.datetime.now(RIO)
    elif agora.tzinfo is None:
        raise ValueError("agora precisa de fuso")
    else:
        agora = agora.astimezone(RIO)
    return agora.date().isoformat()


def mensagem_commit(agenda: str, dia: str) -> str:
    return f"Importação automática ({agenda}, {dia})"


def montar_relatorio(blocos: list[tuple[str, str]], erro: str | None) -> str:
    """Relatório que ia no corpo do PR, mais o erro quando a main não muda."""
    partes: list[str] = []
    for titulo, texto in blocos:
        corpo = (texto or "").strip() or "_sem relatório_"
        partes.append(f"## {titulo}\n\n{corpo}")
    if erro and erro.strip():
        limpo = erro.replace("```", "'''").strip()
        if len(limpo) > 20000:
            limpo = limpo[:20000] + "\n… (cortado)"
        partes.append("## Erro\n\n```\n" + limpo + "\n```")
    return "\n\n".join(partes).rstrip() + "\n"


def slug_e_rotulo(agendas: list[str]) -> tuple[str, str]:
    if agendas == ["tech", "roles"]:
        return "tech-e-roles", "tech e rolês"
    if len(agendas) == 1:
        return agendas[0], agendas[0]
    return "-e-".join(agendas), " e ".join(agendas)


def _limpar_segredo(texto: str) -> str:
    texto = re.sub(r"x-access-token:[^@\s]+", "x-access-token:***", texto)
    texto = re.sub(r"https://[^/\s@]+:[^@\s/]+@", "https://***@", texto)
    return texto


def _recusar(paths: list[str]) -> None:
    for path in paths:
        nome = Path(path).name
        if nome == "_chat.txt" or nome.endswith(".zip") or "WhatsApp" in path or path not in PERMITIDOS:
            raise RuntimeError(f"não vou gravar {path}")


@dataclass
class Plano:
    agenda: str
    arquivos: tuple[str, ...]
    comandos: tuple[tuple[str, ...], ...]
    relatorio: str


def _py() -> str:
    return sys.executable


def planos(fluxo: str) -> list[Plano]:
    py = _py()
    if fluxo == "diario":
        return [
            Plano(
                "tech",
                ("data/events.json",),
                (
                    (py, "scripts/importar.py", "--agenda", "tech", "--fontes", "fontes.json",
                     "--relatorio", "relatorio-tech.md"),
                    (py, "scripts/resumir.py", "--agenda", "tech"),
                ),
                "relatorio-tech.md",
            ),
            Plano(
                "roles",
                ("data/roles.json",),
                (
                    (py, "scripts/importar.py", "--agenda", "roles", "--fontes", "fontes_roles.json",
                     "--relatorio", "relatorio-roles.md"),
                    (py, "scripts/resumir.py", "--agenda", "roles"),
                ),
                "relatorio-roles.md",
            ),
        ]
    if fluxo == "correio":
        return [
            Plano(
                "correio",
                ("data/events.json", "data/roles.json"),
                (
                    (py, "scripts/importar_correio.py", "--relatorio", "relatorio-correio.md"),
                    (py, "scripts/resumir.py"),
                ),
                "relatorio-correio.md",
            ),
        ]
    raise ValueError(f"fluxo desconhecido: {fluxo}")


COMANDOS_VALIDAR: tuple[tuple[str, ...], ...] = (
    (_py(), "scripts/validar.py"),
    (_py(), "-m", "unittest", "discover", "-s", "scripts"),
)


def executar(comandos: tuple[tuple[str, ...], ...] | list, relatorio_nome: str) -> tuple[int, str, str]:
    """Roda os comandos no repositório. Para no primeiro erro. Devolve código, log e relatório."""
    logs: list[str] = []
    codigo = 0
    for cmd in comandos:
        r = subprocess.run(list(cmd), cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            codigo = r.returncode
            logs.append(f"$ {' '.join(cmd[1:])}\n{r.stdout}{r.stderr}".strip())
            break
    texto = ""
    path = ROOT / relatorio_nome
    if path.is_file():
        texto = path.read_text(encoding="utf-8")
    return codigo, "\n\n".join(logs), texto


def validar_repositorio() -> tuple[bool, str]:
    erros: list[str] = []
    for cmd in COMANDOS_VALIDAR:
        r = subprocess.run(list(cmd), cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            erros.append(f"$ {' '.join(cmd[1:])}\n{r.stdout}{r.stderr}".strip())
    if erros:
        return False, "\n\n".join(erros)
    return True, ""


@dataclass
class Etapa:
    agenda: str
    arquivos: list[str]
    rodar: Callable[[], tuple[int, str, str]]


@dataclass
class Resultado:
    publicado: bool = False
    revisar: bool = False
    falha: str = ""
    relatorio: str = ""
    dia: str = ""
    agenda: str = ""
    rotulo: str = ""


class Git:
    """Operações git locais. O remoto é origin/main."""

    def __init__(self, cwd: Path):
        self.cwd = cwd

    def _run(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        r = subprocess.run(
            ["git", *args], cwd=self.cwd, capture_output=True, text=True, env=env,
        )
        if check and r.returncode != 0:
            detalhe = _limpar_segredo((r.stderr or r.stdout or "").strip())
            raise RuntimeError(f"git {' '.join(args)} falhou: {detalhe[:500]}")
        return r

    def _saida(self, r: subprocess.CompletedProcess[str]) -> str:
        return _limpar_segredo(((r.stderr or "") + (r.stdout or "")).strip())

    def garantir_identidade(self) -> None:
        self._run(["config", "user.email", BOT_EMAIL])
        self._run(["config", "user.name", BOT_NOME])
        self._run(["config", "commit.gpgsign", "false"])

    def preparar(self) -> None:
        """Deixa o branch main em cima de origin/main."""
        self._run(["fetch", "origin", "main"])
        self._run(["checkout", "-B", "main", "origin/main"])
        self.garantir_identidade()
        estado = self.pull_rebase()
        if estado != "ok":
            raise RuntimeError(f"git pull --rebase falhou ao atualizar a main ({estado})")

    def _caminho_git(self, nome: str) -> Path:
        r = self._run(["rev-parse", "--git-path", nome], check=False)
        bruto = (r.stdout or "").strip()
        path = Path(bruto)
        if not path.is_absolute():
            path = Path(self.cwd) / path
        return path

    def _rebase_em_andamento(self) -> bool:
        return self._caminho_git("rebase-merge").exists() or self._caminho_git("rebase-apply").exists()

    def pull_rebase(self) -> str:
        """'ok', 'conflito' ou 'erro:…'."""
        r = self._run(["pull", "--rebase", "origin", "main"], check=False)
        if r.returncode == 0:
            return "ok"
        texto = self._saida(r)
        if self._rebase_em_andamento() or "CONFLICT" in texto or "could not apply" in texto:
            return "conflito"
        return "erro: " + texto[:500]

    def push(self) -> tuple[bool, str]:
        """(True, '') ou (False, 'main-moved' | mensagem)."""
        r = self._run(["push", "origin", "HEAD:main"], check=False)
        if r.returncode == 0:
            return True, ""
        texto = self._saida(r)
        if re.search(r"rejected|fetch first|non-fast-forward", texto, re.I):
            return False, "main-moved"
        return False, texto[:500] or "git push falhou"

    def mudancas(self, paths: list[str]) -> list[str]:
        if not paths:
            return []
        _recusar(paths)
        r = self._run(["status", "--porcelain", "--", *paths])
        return [linha for linha in r.stdout.splitlines() if linha.strip()]

    def ahead(self) -> bool:
        r = self._run(["rev-list", "--count", "origin/main..HEAD"])
        return (r.stdout or "").strip() not in ("", "0")

    def commitar(self, etapas: list[Etapa], dia: str) -> list[str]:
        self.garantir_identidade()
        feitas: list[str] = []
        for etapa in etapas:
            if not self.mudancas(etapa.arquivos):
                continue
            _recusar(etapa.arquivos)
            self._run(["add", "--", *etapa.arquivos])
            nomes = [n for n in self._run(["diff", "--cached", "--name-only"]).stdout.splitlines() if n.strip()]
            if not nomes:
                continue
            for nome in nomes:
                if nome not in PERMITIDOS:
                    self._run(["reset", "HEAD"], check=False)
                    raise RuntimeError(f"não vou gravar {nome}")
            msg = mensagem_commit(etapa.agenda, dia)
            self._run(["commit", "-m", msg])
            feitas.append(msg)
            print(f"commit: {msg}")
        return feitas

    def recuperar_base(self) -> None:
        """Aborta um rebase e volta o branch para origin/main, sem mudanças locais."""
        if self._rebase_em_andamento():
            self._run(["rebase", "--abort"], check=False)
        self._run(["fetch", "origin", "main"])
        self._run(["reset", "--hard", "origin/main"])

    def _rev(self, ref: str) -> str:
        return self._run(["rev-parse", ref]).stdout.strip()


def _etapa_de_plano(plano: Plano) -> Etapa:
    def rodar() -> tuple[int, str, str]:
        return executar(plano.comandos, plano.relatorio)

    return Etapa(plano.agenda, list(plano.arquivos), rodar)


def _arquivos(etapas: list[Etapa]) -> list[str]:
    vistos: list[str] = []
    for etapa in etapas:
        for path in etapa.arquivos:
            if path not in vistos:
                vistos.append(path)
    return vistos


def _importar(etapas: list[Etapa], dia: str) -> tuple[list[tuple[str, str]], list[str]]:
    blocos: list[tuple[str, str]] = []
    erros: list[str] = []
    for etapa in etapas:
        codigo, log, texto = etapa.rodar()
        blocos.append((mensagem_commit(etapa.agenda, dia), texto))
        if codigo != 0:
            erros.append(log or f"{etapa.agenda} saiu com código {codigo}")
    return blocos, erros


def _juntar_validacao(erros: list[str], validar) -> list[str]:
    ok, erro_val = validar()
    if not ok:
        return [*erros, erro_val or "validação falhou"]
    return list(erros)


def etiquetar_correio() -> None:
    """Aplica agenda/processado nos UIDs salvos por importar_correio.py."""
    import importar_correio

    importar_correio.aplicar_rotulos()


def etiquetar_do_fluxo(fluxo: str) -> Callable[[], None] | None:
    """Só o correio etiqueta, e só quem chama isto depois do push na main."""
    if fluxo == "correio":
        return etiquetar_correio
    return None


def conduzir(
    git: Git,
    etapas: list[Etapa],
    validar,
    dia: str,
    tentativas: int = TENTATIVAS,
    etiquetar: Callable[[], None] | None = None,
) -> Resultado:
    """Importa, valida e tenta gravar na main. Não abre PR."""
    tentativas = max(1, tentativas)
    agendas = [e.agenda for e in etapas]
    slug, rotulo = slug_e_rotulo(agendas)
    base = Resultado(dia=dia, agenda=slug, rotulo=rotulo)
    paths = _arquivos(etapas)

    def falha(erros: list[str], blocos: list[tuple[str, str]], extra: str = "") -> Resultado:
        texto = "\n\n".join(p for p in [*erros, extra] if p)
        base.falha = texto or "falhou"
        base.relatorio = montar_relatorio(blocos, texto)
        base.publicado = False
        base.revisar = False
        return base

    def revisar(erros: list[str], blocos: list[tuple[str, str]], extra: str = "") -> Resultado:
        if not git.mudancas(paths):
            return falha(erros, blocos, extra or "sem mudanças para revisar")
        texto = "\n\n".join(p for p in [*erros, extra] if p)
        base.revisar = True
        base.publicado = False
        base.falha = ""
        base.relatorio = montar_relatorio(blocos, texto)
        print("a main não foi alterada; fica para revisão")
        return base

    def ciclo() -> tuple[list[tuple[str, str]], list[str]]:
        blocos, erros = _importar(etapas, dia)
        return blocos, _juntar_validacao(erros, validar)

    blocos, erros = ciclo()
    if erros:
        print("validação ou importação falhou")
        return revisar(erros, blocos) if git.mudancas(paths) else falha(erros, blocos)

    if not git.mudancas(paths):
        print("sem mudanças")
        base.relatorio = montar_relatorio(blocos, None)
        return base

    for tentativa in range(1, tentativas + 1):
        if git.mudancas(paths):
            git.commitar(etapas, dia)
        print(f"push na main, tentativa {tentativa}")
        ok, motivo = git.push()
        if ok:
            print("publicado na main")
            base.publicado = True
            base.relatorio = montar_relatorio(blocos, None)
            if etiquetar is not None:
                try:
                    etiquetar()
                except Exception as exc:
                    print(
                        f"aviso: não etiquetei o correio ({type(exc).__name__})",
                        file=sys.stderr,
                    )
            return base
        if motivo != "main-moved":
            return falha([], blocos, motivo)
        if tentativa == tentativas:
            break
        print("a main andou; git pull --rebase")
        estado = git.pull_rebase()
        if estado == "ok":
            continue
        if estado != "conflito":
            if git._rebase_em_andamento():
                git._run(["rebase", "--abort"], check=False)
            return falha([], blocos, estado)
        print("conflito no rebase; importando de novo")
        git.recuperar_base()
        blocos, erros = ciclo()
        if erros:
            return revisar(erros, blocos) if git.mudancas(paths) else falha(erros, blocos)
        if not git.mudancas(paths):
            print("sem mudanças depois de importar de novo")
            base.relatorio = montar_relatorio(blocos, None)
            return base

    print(f"não deu para enviar à main depois de {tentativas} tentativas")
    git.recuperar_base()
    blocos, erros = ciclo()
    aviso = f"não deu para enviar à main depois de {tentativas} tentativas"
    if erros:
        return revisar(erros, blocos, aviso) if git.mudancas(paths) else falha(erros, blocos, aviso)
    if git.mudancas(paths):
        return revisar([], blocos, aviso)
    base.relatorio = montar_relatorio(blocos, None)
    return base


def definir_saida(**pares: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for chave, valor in pares.items():
            if "\n" in valor or "\r" in valor:
                raise ValueError(chave)
            fh.write(f"{chave}={valor}\n")


def escrever_resumo(texto: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(texto if texto.endswith("\n") else texto + "\n")


def anexar_na_issue(corpo: str, run=None) -> str:
    """Acrescenta o relatório na issue aberta «Saúde da agenda».

    Se a issue existe, comenta (o relatório semanal reescreve o corpo na
    segunda e o comentário fica). Se não existe, cria a issue.
    """
    run = run or _gh

    def chamar(args: list[str]) -> subprocess.CompletedProcess[str]:
        r = run(args)
        if r.returncode != 0:
            detalhe = _limpar_segredo((r.stderr or r.stdout or "gh falhou").strip())
            raise RuntimeError(detalhe[:300])
        return r

    lista = chamar([
        "gh", "issue", "list", "--label", "saude-da-agenda", "--state", "open",
        "--json", "number,url", "--limit", "20",
    ])
    abertas = sorted(json.loads(lista.stdout or "[]"), key=lambda i: i["number"])
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as tmp:
        tmp.write(corpo)
        caminho = tmp.name
    try:
        if not abertas:
            criada = chamar([
                "gh", "issue", "create", "--title", "Saúde da agenda",
                "--label", "saude-da-agenda",
                "--body", "Os relatórios de importação ficam nos comentários.",
            ])
            alvo_ref = (criada.stdout or "").strip()
        else:
            alvo = abertas[0]
            alvo_ref = str(alvo["number"])
        chamar(["gh", "issue", "comment", alvo_ref, "--body-file", caminho])
        if abertas:
            return abertas[0].get("url") or f"#{abertas[0]['number']}"
        return alvo_ref
    finally:
        Path(caminho).unlink(missing_ok=True)


def _gh(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True)


def _resolver_dia(explicito: str | None) -> str:
    bruto = (explicito if explicito is not None else os.environ.get("DIA") or "").strip()
    if not bruto:
        return dia_rio()
    dt.date.fromisoformat(bruto)
    return bruto


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("fluxo", choices=["diario", "correio"])
    ap.add_argument("--dia", help="AAAA-MM-DD em America/Sao_Paulo; padrão: DIA ou hoje no Rio")
    ap.add_argument("--tentativas", type=int, default=TENTATIVAS)
    args = ap.parse_args(argv)
    try:
        dia = _resolver_dia(args.dia)
    except ValueError as exc:
        print(f"erro: dia inválido ({exc})", file=sys.stderr)
        definir_saida(revisar="false", publicado="false", agenda="", rotulo="", dia="")
        return 1

    git = Git(ROOT)
    try:
        git.preparar()
        etapas = [_etapa_de_plano(p) for p in planos(args.fluxo)]
        resultado = conduzir(
            git, etapas, validar_repositorio, dia, args.tentativas,
            etiquetar=etiquetar_do_fluxo(args.fluxo),
        )
    except Exception as exc:
        print(f"erro: {_limpar_segredo(str(exc))}", file=sys.stderr)
        definir_saida(revisar="false", publicado="false", agenda="", rotulo="", dia=dia)
        return 1

    (ROOT / "relatorio.md").write_text(resultado.relatorio, encoding="utf-8")
    escrever_resumo(resultado.relatorio)
    try:
        onde = anexar_na_issue(resultado.relatorio)
        print(f"relatório na issue: {onde}")
    except Exception as exc:
        print(f"aviso: não consegui acrescentar na issue Saúde da agenda ({_limpar_segredo(str(exc))})")

    definir_saida(
        revisar="true" if resultado.revisar else "false",
        publicado="true" if resultado.publicado else "false",
        agenda=resultado.agenda,
        rotulo=resultado.rotulo,
        dia=resultado.dia,
    )
    if resultado.falha:
        print(_limpar_segredo(resultado.falha), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
