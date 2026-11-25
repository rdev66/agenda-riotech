"""A importação entra na main, ou fica para revisão. Sem rede e sem API."""
import datetime as dt
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import publicar_importacao as pub  # noqa: E402
import validar  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _git(cwd, *args, check=True):
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"git {args}: {r.stderr or r.stdout}")
    return r


def _identidade(cwd):
    _git(cwd, "config", "user.email", "teste@example.com")
    _git(cwd, "config", "user.name", "Teste")
    _git(cwd, "config", "commit.gpgsign", "false")


def _repos(tmp: Path):
    origin = tmp / "origin.git"
    subprocess.check_call(["git", "init", "--bare", "-b", "main", str(origin)])
    seed = tmp / "seed"
    subprocess.check_call(["git", "init", "-b", "main", str(seed)])
    _identidade(seed)
    dados = seed / "data"
    dados.mkdir()
    (dados / "events.json").write_text('{"events":[]}\n', encoding="utf-8")
    (dados / "roles.json").write_text('{"events":[]}\n', encoding="utf-8")
    (seed / "README").write_text("base\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "inicio")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "-u", "origin", "main")
    work = tmp / "work"
    other = tmp / "other"
    subprocess.check_call(["git", "clone", str(origin), str(work)])
    subprocess.check_call(["git", "clone", str(origin), str(other)])
    _identidade(work)
    _identidade(other)
    return work, other


def _log(cwd) -> list[str]:
    return _git(cwd, "log", "--format=%s").stdout.splitlines()


def _ler(cwd, nome) -> str:
    return (cwd / nome).read_text(encoding="utf-8")


class TestRelatorio(unittest.TestCase):
    def test_dia_vira_no_rio(self):
        antes = dt.datetime(2026, 11, 25, 2, 30, tzinfo=dt.timezone.utc)
        self.assertEqual(pub.dia_rio(antes), "2026-11-24")
        depois = dt.datetime(2026, 11, 25, 3, 0, tzinfo=dt.timezone.utc)
        self.assertEqual(pub.dia_rio(depois), "2026-11-25")

    def test_mensagem(self):
        self.assertEqual(
            pub.mensagem_commit("tech", "2026-11-24"),
            "Importação automática (tech, 2026-11-24)",
        )

    def test_relatorio_com_erro(self):
        texto = pub.montar_relatorio([("Importação automática (correio, 2026-11-24)", "novo: 1")], "quebra")
        self.assertIn("## Importação automática (correio, 2026-11-24)", texto)
        self.assertIn("novo: 1", texto)
        self.assertIn("## Erro", texto)
        self.assertIn("quebra", texto)

    def test_relatorio_sem_erro_nao_tem_secao(self):
        texto = pub.montar_relatorio([("T", "ok")], None)
        self.assertNotIn("## Erro", texto)

    def test_slug(self):
        self.assertEqual(pub.slug_e_rotulo(["tech", "roles"]), ("tech-e-roles", "tech e rolês"))
        self.assertEqual(pub.slug_e_rotulo(["correio"]), ("correio", "correio"))

    def test_limpa_token(self):
        bruto = "failed https://x-access-token:ghp_secret@github.com/o/r"
        limpo = pub._limpar_segredo(bruto)
        self.assertNotIn("ghp_secret", limpo)
        self.assertIn("github.com/o/r", limpo)

    def test_comandos_em_serie(self):
        diario = pub.planos("diario")
        self.assertEqual([p.agenda for p in diario], ["tech", "roles"])
        self.assertEqual(diario[0].arquivos, ("data/events.json",))
        self.assertEqual(diario[1].arquivos, ("data/roles.json",))
        self.assertEqual(
            diario[0].comandos[0][1:],
            ("scripts/importar.py", "--agenda", "tech", "--fontes", "fontes.json", "--relatorio", "relatorio-tech.md"),
        )
        self.assertEqual(diario[0].comandos[1][1:], ("scripts/resumir.py", "--agenda", "tech"))
        self.assertEqual(
            diario[1].comandos[0][1:],
            ("scripts/importar.py", "--agenda", "roles", "--fontes", "fontes_roles.json",
             "--relatorio", "relatorio-roles.md"),
        )
        self.assertEqual(diario[1].comandos[1][1:], ("scripts/resumir.py", "--agenda", "roles"))
        correio = pub.planos("correio")
        self.assertEqual(len(correio), 1)
        self.assertEqual(correio[0].arquivos, ("data/events.json", "data/roles.json"))
        self.assertEqual(
            correio[0].comandos[0][1:],
            ("scripts/importar_correio.py", "--relatorio", "relatorio-correio.md"),
        )
        self.assertEqual(correio[0].comandos[1][1:], ("scripts/resumir.py",))
        self.assertEqual(pub.COMANDOS_VALIDAR[0][1:], ("scripts/validar.py",))
        self.assertEqual(pub.COMANDOS_VALIDAR[1][1:], ("-m", "unittest", "discover", "-s", "scripts"))

    def test_recusa_whatsapp(self):
        with tempfile.TemporaryDirectory() as tmp:
            work, _other = _repos(Path(tmp))
            git = pub.Git(work)
            with self.assertRaises(RuntimeError):
                git.mudancas(["_chat.txt"])
            with self.assertRaises(RuntimeError):
                git.mudancas(["WhatsApp/chat.zip"])


class TestPublicar(unittest.TestCase):
    def _etapa(self, agenda, arquivo, gravar):
        def rodar():
            gravar()
            return 0, "", f"relatório {agenda}"

        return pub.Etapa(agenda, [arquivo], rodar)

    def test_grava_na_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            work, _other = _repos(Path(tmp))

            def gravar():
                (work / "data" / "events.json").write_text('{"events":[{"id":"a"}]}\n', encoding="utf-8")

            git = pub.Git(work)
            resultado = pub.conduzir(
                git, [self._etapa("tech", "data/events.json", gravar)], lambda: (True, ""), "2026-11-24",
            )
            self.assertTrue(resultado.publicado)
            self.assertFalse(resultado.revisar)
            self.assertEqual(_ler(work, "data/events.json"), '{"events":[{"id":"a"}]}\n')
            self.assertIn("Importação automática (tech, 2026-11-24)", _log(work))
            self.assertEqual(
                _git(work, "rev-parse", "HEAD").stdout,
                _git(work, "rev-parse", "origin/main").stdout,
            )
            self.assertNotIn("## Erro", resultado.relatorio)

    def test_dois_commits_num_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            work, _other = _repos(Path(tmp))

            def tech():
                (work / "data" / "events.json").write_text('{"events":[{"id":"t"}]}\n', encoding="utf-8")

            def roles():
                (work / "data" / "roles.json").write_text('{"events":[{"id":"r"}]}\n', encoding="utf-8")

            git = pub.Git(work)
            resultado = pub.conduzir(
                git,
                [
                    self._etapa("tech", "data/events.json", tech),
                    self._etapa("roles", "data/roles.json", roles),
                ],
                lambda: (True, ""),
                "2026-11-24",
            )
            self.assertTrue(resultado.publicado)
            self.assertEqual(resultado.agenda, "tech-e-roles")
            self.assertEqual(resultado.rotulo, "tech e rolês")
            mensagens = _log(work)
            self.assertEqual(mensagens[0], "Importação automática (roles, 2026-11-24)")
            self.assertEqual(mensagens[1], "Importação automática (tech, 2026-11-24)")

    def test_importacao_falha_sem_diff_nao_abre_revisao(self):
        with tempfile.TemporaryDirectory() as tmp:
            work, _other = _repos(Path(tmp))
            antes = _log(work)

            def rodar():
                return 1, "caixa indisponível", "aviso"

            git = pub.Git(work)
            resultado = pub.conduzir(
                git, [pub.Etapa("correio", ["data/events.json"], rodar)], lambda: (True, ""), "2026-11-24",
            )
            self.assertFalse(resultado.revisar)
            self.assertFalse(resultado.publicado)
            self.assertIn("caixa indisponível", resultado.falha)
            self.assertEqual(_log(work), antes)

    def test_importacao_falha_com_diff_pede_revisao(self):
        with tempfile.TemporaryDirectory() as tmp:
            work, _other = _repos(Path(tmp))

            def rodar():
                (work / "data" / "events.json").write_text("parcial\n", encoding="utf-8")
                return 1, "não gravei tudo", "parcial"

            git = pub.Git(work)
            resultado = pub.conduzir(
                git, [pub.Etapa("correio", ["data/events.json"], rodar)], lambda: (True, ""), "2026-11-24",
            )
            self.assertTrue(resultado.revisar)
            self.assertFalse(resultado.publicado)
            self.assertIn("não gravei tudo", resultado.relatorio)
            self.assertEqual(_log(work), ["inicio"])

    def test_sem_mudancas(self):
        with tempfile.TemporaryDirectory() as tmp:
            work, _other = _repos(Path(tmp))
            antes = _log(work)
            git = pub.Git(work)
            resultado = pub.conduzir(
                git,
                [self._etapa("correio", "data/events.json", lambda: None)],
                lambda: (True, ""),
                "2026-11-24",
            )
            self.assertFalse(resultado.publicado)
            self.assertFalse(resultado.revisar)
            self.assertEqual(_log(work), antes)
            self.assertNotIn("## Erro", resultado.relatorio)

    def test_validacao_nao_toca_a_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            work, _other = _repos(Path(tmp))
            antes = _log(work)

            def gravar():
                (work / "data" / "events.json").write_text("ruim\n", encoding="utf-8")

            git = pub.Git(work)
            resultado = pub.conduzir(
                git,
                [self._etapa("correio", "data/events.json", gravar)],
                lambda: (False, "validar.py falhou"),
                "2026-11-24",
            )
            self.assertFalse(resultado.publicado)
            self.assertTrue(resultado.revisar)
            self.assertEqual(resultado.agenda, "correio")
            self.assertEqual(_log(work), antes)
            self.assertEqual(_git(work, "status", "--porcelain").stdout.strip(), "M data/events.json")
            self.assertIn("validar.py falhou", resultado.relatorio)
            self.assertIn("relatório correio", resultado.relatorio)
            self.assertIn("## Erro", resultado.relatorio)

    def test_main_andou_sem_conflito(self):
        with tempfile.TemporaryDirectory() as tmp:
            work, other = _repos(Path(tmp))
            feito = {"n": 0}

            def antes(_n):
                if feito["n"]:
                    return
                feito["n"] = 1
                (other / "data" / "roles.json").write_text('{"events":[{"id":"deles"}]}\n', encoding="utf-8")
                _git(other, "add", "data/roles.json")
                _git(other, "commit", "-m", "lado")
                _git(other, "push", "origin", "HEAD:main")

            class Empurra(pub.Git):
                def push(self):
                    antes(0)
                    return super().push()

            def gravar():
                (work / "data" / "events.json").write_text('{"events":[{"id":"nosso"}]}\n', encoding="utf-8")

            resultado = pub.conduzir(
                Empurra(work),
                [self._etapa("tech", "data/events.json", gravar)],
                lambda: (True, ""),
                "2026-11-24",
            )
            self.assertTrue(resultado.publicado, resultado.falha)
            self.assertFalse(resultado.revisar)
            self.assertEqual(_ler(work, "data/events.json"), '{"events":[{"id":"nosso"}]}\n')
            self.assertEqual(_ler(work, "data/roles.json"), '{"events":[{"id":"deles"}]}\n')
            self.assertIn("Importação automática (tech, 2026-11-24)", _log(work))
            self.assertIn("lado", _log(work))

    def test_conflito_reimporta(self):
        with tempfile.TemporaryDirectory() as tmp:
            work, other = _repos(Path(tmp))
            chamadas = {"n": 0}
            lado = {"n": 0}

            def gravar():
                chamadas["n"] += 1
                texto = "mesclado\n" if chamadas["n"] > 1 else "nosso\n"
                (work / "data" / "events.json").write_text(texto, encoding="utf-8")

            def antes(_n):
                if lado["n"]:
                    return
                lado["n"] = 1
                (other / "data" / "events.json").write_text("deles\n", encoding="utf-8")
                _git(other, "add", "data/events.json")
                _git(other, "commit", "-m", "lado")
                _git(other, "push", "origin", "HEAD:main")

            class Empurra(pub.Git):
                def push(self):
                    antes(0)
                    return super().push()

            resultado = pub.conduzir(
                Empurra(work),
                [self._etapa("tech", "data/events.json", gravar)],
                lambda: (True, ""),
                "2026-11-24",
            )
            self.assertTrue(resultado.publicado, resultado.falha)
            self.assertGreaterEqual(chamadas["n"], 2)
            self.assertEqual(_ler(work, "data/events.json"), "mesclado\n")
            self.assertIn("Importação automática (tech, 2026-11-24)", _log(work))
            self.assertFalse((work / ".git" / "rebase-merge").exists())

    def test_tres_tentativas_abrem_revisao(self):
        with tempfile.TemporaryDirectory() as tmp:
            work, other = _repos(Path(tmp))
            n = {"push": 0}

            def gravar():
                (work / "data" / "events.json").write_text("nosso\n", encoding="utf-8")

            def antes(vez):
                (other / "README").write_text(f"lado {vez}\n", encoding="utf-8")
                _git(other, "add", "README")
                _git(other, "commit", "-m", f"lado {vez}")
                _git(other, "push", "origin", "HEAD:main")

            class Empurra(pub.Git):
                def push(self):
                    n["push"] += 1
                    antes(n["push"])
                    return super().push()

            resultado = pub.conduzir(
                Empurra(work),
                [self._etapa("tech", "data/events.json", gravar)],
                lambda: (True, ""),
                "2026-11-24",
                tentativas=3,
            )
            self.assertEqual(n["push"], 3)
            self.assertTrue(resultado.revisar)
            self.assertFalse(resultado.publicado)
            self.assertIn("3 tentativas", resultado.relatorio)
            self.assertEqual(_git(work, "rev-list", "--count", "origin/main..HEAD").stdout.strip(), "0")
            self.assertIn("nosso", _ler(work, "data/events.json"))
            self.assertNotIn("Importação automática", "\n".join(_log(work)))
            self.assertFalse((work / ".git" / "rebase-merge").exists())

    def test_push_que_nao_e_a_main_nao_abre_revisao(self):
        with tempfile.TemporaryDirectory() as tmp:
            work, _other = _repos(Path(tmp))

            def gravar():
                (work / "data" / "events.json").write_text("x\n", encoding="utf-8")

            class Recusa(pub.Git):
                def push(self):
                    return False, "sem permissão"

            antes = _log(work)
            resultado = pub.conduzir(
                Recusa(work),
                [self._etapa("tech", "data/events.json", gravar)],
                lambda: (True, ""),
                "2026-11-24",
            )
            self.assertFalse(resultado.revisar)
            self.assertFalse(resultado.publicado)
            self.assertIn("sem permissão", resultado.falha)
            # O commit local existe, mas a main do remoto não andou.
            self.assertEqual(_log(work)[1:], antes)


class TestIssue(unittest.TestCase):
    def test_comenta_a_issue_aberta(self):
        chamadas = []

        def run(args):
            chamadas.append(args)
            if args[1:3] == ["issue", "list"]:
                return subprocess.CompletedProcess(args, 0, stdout='[{"number": 9}, {"number": 4}]', stderr="")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        onde = pub.anexar_na_issue("relatório\n", run=run)
        self.assertEqual(onde, "#4")
        self.assertEqual(chamadas[1][:4], ["gh", "issue", "comment", "4"])
        self.assertIn("--body-file", chamadas[1])

    def test_cria_se_nao_ha_issue(self):
        chamadas = []

        def run(args):
            chamadas.append(args)
            if args[1:3] == ["issue", "list"]:
                return subprocess.CompletedProcess(args, 0, stdout="[]", stderr="")
            return subprocess.CompletedProcess(args, 0, stdout="https://example/issue/1\n", stderr="")

        onde = pub.anexar_na_issue("relatório\n", run=run)
        self.assertEqual(onde, "https://example/issue/1")
        self.assertEqual(chamadas[1][1:4], ["issue", "create", "--title"])
        self.assertIn("Saúde da agenda", chamadas[1])
        self.assertIn("saude-da-agenda", chamadas[1])
        self.assertEqual(chamadas[2][:4], ["gh", "issue", "comment", "https://example/issue/1"])


class TestWorkflows(unittest.TestCase):
    def _doc(self, nome):
        texto = (ROOT / ".github" / "workflows" / nome).read_text(encoding="utf-8")
        return texto, validar.load_yaml(texto)

    def test_importar_e_correio_em_serie(self):
        for nome, fluxo in (("importar.yml", "diario"), ("importar-correio.yml", "correio")):
            texto, doc = self._doc(nome)
            self.assertEqual(doc["concurrency"]["group"], "dados-agenda", nome)
            self.assertIs(doc["concurrency"]["cancel-in-progress"], False, nome)
            for chave in ("contents", "pull-requests", "actions", "issues"):
                self.assertEqual(doc["permissions"][chave], "write", nome)
            self.assertEqual(len(doc["jobs"]), 1, nome)
            self.assertIn("git pull --rebase origin main", texto, nome)
            self.assertIn(f"python scripts/publicar_importacao.py {fluxo}", texto, nome)
            self.assertIn("gh workflow run pages.yml --ref main", texto, nome)
            self.assertIn("TZ=America/Sao_Paulo date +%F", texto, nome)
            self.assertIn("fetch-depth: 0", texto, nome)
            pr = next(
                p for p in next(iter(doc["jobs"].values()))["steps"]
                if str(p.get("uses", "")).startswith("peter-evans/create-pull-request@")
            )
            self.assertEqual(pr["uses"], "peter-evans/create-pull-request@v8")
            self.assertEqual(
                pr["with"]["branch"],
                "importador/revisar-${{ steps.publicar.outputs.agenda }}-${{ steps.publicar.outputs.dia }}",
            )
            self.assertIs(pr["with"]["delete-branch"], False)
            self.assertEqual(pr["with"]["body-path"], "relatorio.md")
            self.assertIn("data/events.json", texto)
            self.assertIn("data/roles.json", texto)
        diario, _doc = self._doc("importar.yml")
        correio, doc_correio = self._doc("importar-correio.yml")
        self.assertIn('cron: "17 11 * * *"', diario)
        self.assertIn('cron: "47 11 * * *"', correio)
        self.assertIn("workflow_dispatch:", diario)
        self.assertIn("workflow_dispatch:", correio)
        self.assertNotIn("importar-roles", diario)
        self.assertIn("GMAIL_EVENTOS_APP_PASSWORD", correio)
        self.assertIn("GMAIL_ROLES_APP_PASSWORD", correio)
        self.assertIn("ANTHROPIC_API_KEY", diario)
        self.assertIn("ANTHROPIC_API_KEY", correio)
        self.assertIn("importar-correio", doc_correio["jobs"])
        pages = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
        self.assertIn("branches: [main]", pages)
        self.assertIn("workflow_dispatch:", pages)

    def test_readme_explica_o_fluxo(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        contribuindo = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        for texto in (readme, contribuindo):
            self.assertIn("dados-agenda", texto)
            self.assertIn("importador/revisar-", texto)
            self.assertIn("Saúde da agenda", texto)
        self.assertIn("issue-para-pr", readme)
        self.assertIn("PR feito à mão", contribuindo)
        self.assertIn("gh workflow run pages.yml --ref main", readme)
        self.assertIn("Importação automática (tech, AAAA-MM-DD)", readme)
        self.assertIn("Importação automática (correio, AAAA-MM-DD)", readme)


if __name__ == "__main__":
    unittest.main()
