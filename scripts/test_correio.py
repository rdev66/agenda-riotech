"""Testes do importador de correio. Sem rede: IMAP e o modelo são falsos."""
import datetime as dt
import email.message
import imaplib
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import importar  # noqa: E402
import importar_correio as correio  # noqa: E402
import validar  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1]
HOJE = dt.date(2026, 11, 15)


class FakeIMAP:
    def __init__(self, mensagens=None):
        self.mensagens = dict(mensagens or {})
        self.user = None
        self.password = None
        self.selecionada = None
        self.readonly = None
        self.comandos = []

    def login(self, user, password):
        self.user = user
        self.password = password
        self.comandos.append(("LOGIN", user))
        return "OK", [b"ok"]

    def list(self):
        self.comandos.append(("LIST",))
        return "OK", [b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"']

    def select(self, mailbox="INBOX", readonly=False):
        self.comandos.append(("SELECT", mailbox, readonly))
        # imaplib da stdlib não entreaspas nomes com espaço; Gmail responde BAD.
        if " " in mailbox and not (mailbox.startswith('"') and mailbox.endswith('"')):
            raise imaplib.IMAP4.error(b"BAD Could not parse command")
        self.selecionada = mailbox
        self.readonly = readonly
        return "OK", [b"1"]

    def uid(self, cmd, *args):
        self.comandos.append(("UID", cmd, *args))
        comando = cmd.upper()
        if comando == "SEARCH":
            return "OK", [" ".join(self.mensagens).encode()]
        if comando == "FETCH":
            uid = str(args[0])
            raw = self.mensagens[uid]
            meta = f"1 (X-GM-LABELS (\\Inbox) RFC822 {{{len(raw)}}})".encode()
            return "OK", [(meta, raw), b")"]
        if comando == "STORE":
            return "OK", [None]
        raise AssertionError(cmd)

    def logout(self):
        self.comandos.append(("LOGOUT",))
        return "OK", [b"bye"]


class FakeIMAPAllFalha(FakeIMAP):
    """\\All existe no LIST, mas SELECT desse buzón falha → cai em INBOX."""

    def select(self, mailbox="INBOX", readonly=False):
        self.comandos.append(("SELECT", mailbox, readonly))
        if mailbox != '"INBOX"':
            raise imaplib.IMAP4.error(b"[NONEXISTENT] Unknown Mailbox: [Gmail]/All Mail")
        self.selecionada = mailbox
        self.readonly = readonly
        return "OK", [b"1"]


class Resposta:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def destinos(tmp: Path) -> dict:
    vazio = json.dumps({"updated": "2026-11-01", "events": []}) + "\n"
    saida = {}
    for agenda in ("tech", "roles"):
        path = tmp / f"{agenda}.json"
        path.write_text(vazio, encoding="utf-8")
        saida[agenda] = path
    return saida


def evento_base(url, **mudancas):
    ev = {
        "title": "Python no Rio",
        "start": "2026-12-18T19:00:00-03:00",
        "end": "2026-12-18T21:00:00-03:00",
        "time_known": True,
        "venue": "Botafogo",
        "address": None,
        "city": "Rio de Janeiro",
        "format": "presencial",
        "cost": {"type": "gratis", "text": "Grátis"},
        "registration": "inscricao",
        "url": url,
        "description": {"pt": "Encontro de Python no Rio."},
        "tags": ["python", "meetup"],
        "status": "confirmado",
    }
    ev.update(mudancas)
    return ev


def falso_url(url, agenda):
    if "online99" in url:
        return [evento_base(url, title="Meetup remoto", format="online", tags=["meetup"])], None
    if "sp-tech" in url:
        return [evento_base(url, title="Encontro em Sao Paulo", city="São Paulo")], None
    if "velho" in url:
        return [evento_base(
            url, title="Evento velho",
            start="2026-10-01T19:00:00-03:00", end="2026-10-01T21:00:00-03:00",
        )], None
    if "pyrio42" in url or "pagina" in url:
        return [evento_base(url, title="Python no Rio" if "pyrio" in url else "Titulo da pagina")], None
    return [], "sem dados de evento"


class TestCorreio(unittest.TestCase):
    def test_constantes_e_whatsapp_continua(self):
        self.assertEqual(correio.CIDADE, "Rio de Janeiro")
        self.assertEqual(correio.MODELO, "claude-haiku-5-5")
        self.assertEqual(correio.MAX_TEXTO, 30_000)
        self.assertEqual(correio.MAX_INPUT_TOKENS, 300_000)
        self.assertEqual(correio.MAX_MENSAGENS, 40)
        self.assertIn("newer_than:14d", correio.BUSCA)
        self.assertIn("-label:agenda-processado", correio.BUSCA)
        self.assertNotIn("agenda/processado", correio.BUSCA)
        self.assertEqual(correio.ROTULO, "agenda/processado")
        self.assertTrue(callable(importar.whatsapp_links))

    def test_selecionar_entrecomilla_all_mail(self):
        fake = FakeIMAP()
        self.assertEqual(correio.selecionar(fake), "[Gmail]/All Mail")
        self.assertEqual(fake.selecionada, '"[Gmail]/All Mail"')
        selects = [c for c in fake.comandos if c[0] == "SELECT"]
        self.assertEqual(selects[0][1], '"[Gmail]/All Mail"')

    def test_selecionar_all_falha_cai_em_inbox(self):
        fake = FakeIMAPAllFalha()
        self.assertEqual(correio.selecionar(fake), "INBOX")
        self.assertEqual(fake.selecionada, '"INBOX"')
        selects = [c for c in fake.comandos if c[0] == "SELECT"]
        self.assertEqual(selects[0][1], '"[Gmail]/All Mail"')
        self.assertEqual(selects[1][1], '"INBOX"')

    def test_busca_usa_agenda_processado_com_hifen(self):
        self.assertEqual(correio.BUSCA, "newer_than:14d -label:agenda-processado")
        fake = FakeIMAP({"1": b"x"})
        correio.uids_pendentes(fake)
        busca = [c for c in fake.comandos if c[0] == "UID" and c[1] == "SEARCH"]
        self.assertIn("agenda-processado", busca[0][3])
        self.assertNotIn("agenda/processado", busca[0][3])

    def test_hosts_conhecidos(self):
        self.assertTrue(correio.host_conhecido("https://luma.com/abc"))
        self.assertTrue(correio.host_conhecido("https://www.meetup.com/x/events/1"))
        self.assertTrue(correio.host_conhecido("https://www.sympla.com.br/evento/x/1"))
        self.assertTrue(correio.host_conhecido("https://www.eventbrite.com.br/e/1"))
        self.assertTrue(correio.host_conhecido("https://even3.com.br/x"))
        self.assertTrue(correio.host_conhecido("https://shotgun.live/events/x"))
        self.assertTrue(correio.host_conhecido("https://doity.com.br/x"))
        self.assertFalse(correio.host_conhecido("https://ims.com.br/programacao"))
        self.assertFalse(correio.host_conhecido("https://www.sescrio.org.br/programacao/"))
        self.assertFalse(correio.host_conhecido("https://feverup.com/m/1"))
        self.assertFalse(correio.host_conhecido("https://www.bandsintown.com/e/1"))
        self.assertFalse(correio.host_conhecido("https://notluma.com/abc"))

    def test_limpa_rastreio_sem_rede(self):
        def abrir(url):
            raise AssertionError(url)

        google = "https://www.google.com/url?q=https%3A%2F%2Fluma.com%2Fabc%3Futm_source%3Dnl%26tk%3D1"
        self.assertEqual(correio.resolver_link(google, abrir), "https://luma.com/abc")
        safe = (
            "https://nam12.safelinks.protection.outlook.com/?url="
            "https%3A%2F%2Fwww.sympla.com.br%2Fevento%2Fteste%2F123%3Futm_medium%3Demail"
        )
        self.assertEqual(correio.resolver_link(safe, abrir), "https://www.sympla.com.br/evento/teste/123")

        def seguir(url):
            self.assertEqual(url, "https://bit.ly/abc")
            return "https://www.eventbrite.com/e/festa-tickets-999?utm_source=x"

        self.assertEqual(
            correio.resolver_link("https://bit.ly/abc", seguir),
            "https://www.eventbrite.com/e/festa-tickets-999",
        )
        links = correio.links_uteis(
            "Veja https://shotgun.live/events/festa?utm_source=ig e https://feverup.com/m/1?utm_source=email",
            abrir,
        )
        self.assertEqual(links, ["https://shotgun.live/events/festa"])

    def test_html_e_link_so_no_href(self):
        texto = correio.html_para_texto(
            '<p>Olá</p><a href="https://luma.com/abc?utm_source=x">encontro</a>'
        )
        self.assertIn("encontro", texto)
        self.assertNotIn("<a", texto)
        self.assertEqual(
            correio.links_uteis(texto, lambda url: (_ for _ in ()).throw(AssertionError(url))),
            ["https://luma.com/abc"],
        )
        raw = (
            "From: a@example.com\r\n"
            "To: agenda.rio.eventos@gmail.com\r\n"
            "Subject: x\r\n"
            "MIME-Version: 1.0\r\n"
            "Content-Type: multipart/alternative; boundary=xyz\r\n"
            "\r\n"
            "--xyz\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "\r\n"
            "Veja o encontro.\r\n"
            "--xyz\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            "\r\n"
            '<a href="https://luma.com/so-no-href">o encontro</a>\r\n'
            "--xyz--\r\n"
        ).encode()
        _msg, texto, fonte = correio.ler_mensagem(raw)
        self.assertNotIn("@", texto)
        self.assertNotIn("luma.com", texto)
        self.assertEqual(correio.links_uteis(fonte, lambda url: None), ["https://luma.com/so-no-href"])

    def test_formato_cidade_e_reclassificacao(self):
        self.assertIsNone(correio.motivo_formato_cidade(
            {"format": "hibrido", "city": "Rio de Janeiro", "title": "Feira"}))
        self.assertIsNone(correio.motivo_formato_cidade(
            {"format": "presencial", "city": "Niterói", "title": "Feira"}))
        self.assertEqual(
            correio.motivo_formato_cidade({"format": "online", "city": "Rio de Janeiro", "title": "Live"}),
            "formato online",
        )
        self.assertEqual(
            correio.motivo_formato_cidade({"format": "presencial", "city": "São Paulo", "title": "SP"}),
            "fora do Rio",
        )
        samba = {"title": "Roda de samba na Pedra do Sal", "description": {"pt": "Samba ao vivo."}}
        agenda, mudou = correio.escolher_agenda(samba, "tech")
        self.assertEqual((agenda, mudou), ("roles", True))
        python = {"title": "Meetup de Python e IA", "description": {"pt": "Encontro de python."}}
        agenda, mudou = correio.escolher_agenda(python, "roles")
        self.assertEqual((agenda, mudou), ("tech", True))
        mostra = {"title": "Exposição de fotografia", "description": {"pt": "Mostra no centro."}}
        self.assertEqual(correio.escolher_agenda(mostra, "roles"), ("roles", False))
        ambos = {"title": "Exposição de IA", "description": {"pt": "Exposição sobre inteligencia artificial."}}
        self.assertEqual(correio.escolher_agenda(ambos, "tech"), ("tech", False))
        self.assertEqual(correio.escolher_agenda(ambos, "roles"), ("roles", False))
        fraco = {"title": "Palestra sobre pintura", "description": {"pt": "Uma conversa no museu."}}
        self.assertEqual(correio.escolher_agenda(fraco, "tech"), ("tech", False))

    def test_fixtures_e_importacao(self):
        luma = (FIX / "correio_luma.eml").read_bytes()
        sem = (FIX / "correio_sem_link.eml").read_bytes()
        spam = (FIX / "correio_spam.eml").read_bytes()
        self.assertNotIn(b"http", sem.lower())
        self.assertIn(b"bit.ly/pyrio", luma)
        self.assertIn(b"tenis", spam)

        vistos = []

        def urls(url, agenda):
            vistos.append(url)
            return falso_url(url, agenda)

        def abrir(url):
            self.assertIn("bit.ly", url)
            return "https://luma.com/pyrio42?utm_source=newsletter&tk=1"

        def modelo(texto):
            self.assertNotIn("@", texto)
            self.assertLessEqual(len(texto), 30_000)
            self.assertNotIn("nao pode vazar", texto)
            if "Exposicao de fotografia" in texto:
                return ([
                    {
                        "title": "Exposicao de fotografia no IMS",
                        "start": "2026-12-18T19:00:00-03:00",
                        "end": "2026-12-18T21:00:00-03:00",
                        "venue": "IMS Botafogo",
                        "address": "Rua Marques de Abrantes, 123",
                        "city": "Rio de Janeiro",
                        "url": "https://ims.com.br/eventos/mostra-rio",
                        "cost": "gratis",
                        "format": "presencial",
                        "language": "pt",
                        "description_pt": "Exposicao de fotografia no IMS, em Botafogo, com entrada gratuita.",
                    },
                    {
                        "title": "Sem hora marcada",
                        "start": "2026-12-20",
                        "end": "",
                        "venue": "IMS",
                        "address": "",
                        "city": "Rio de Janeiro",
                        "url": "https://ims.com.br/sem-hora",
                        "cost": "gratis",
                        "format": "presencial",
                        "language": "pt",
                        "description_pt": "O texto nao diz a hora.",
                    },
                    {
                        "title": "Live do IMS",
                        "start": "2026-12-19T19:00:00-03:00",
                        "end": "",
                        "venue": "",
                        "address": "",
                        "city": "Rio de Janeiro",
                        "url": "https://ims.com.br/live",
                        "cost": "gratis",
                        "format": "online",
                        "language": "pt",
                        "description_pt": "Transmissao online.",
                    },
                ], 500, 80)
            if "tenis" in texto or "loja.example.com" in texto:
                return [], 100, 20
            raise AssertionError(texto[:180])

        marcados = []
        with tempfile.TemporaryDirectory() as tmp:
            paths = destinos(Path(tmp))
            with patch("urllib.request.urlopen", side_effect=AssertionError("rede")):
                relatorio, codigo = correio.rodar(
                    [
                        correio.CaixaTrabalho(
                            "Tech", "agenda.rio.eventos@gmail.com", "tech",
                            [("luma", luma), ("spam", spam)],
                            etiquetar=marcados.append,
                        ),
                        correio.CaixaTrabalho(
                            "Rolês", "agenda.rio.roles@gmail.com", "roles",
                            [("ims", sem)],
                            etiquetar=marcados.append,
                        ),
                    ],
                    hoje=HOJE,
                    destinos=paths,
                    abrir_redirect=abrir,
                    eventos_da_url=urls,
                    modelo=modelo,
                )
            tech = json.loads(paths["tech"].read_text(encoding="utf-8"))
            roles = json.loads(paths["roles"].read_text(encoding="utf-8"))
        self.assertEqual(codigo, 0, relatorio)
        self.assertEqual(marcados, ["luma", "spam", "ims"])
        self.assertIn("https://luma.com/pyrio42", vistos)
        self.assertNotIn("utm_", " ".join(vistos))
        self.assertEqual([e["title"] for e in tech["events"]], ["Python no Rio"])
        self.assertEqual(tech["events"][0]["url"], "https://luma.com/pyrio42")
        self.assertEqual(tech["events"][0]["format"], "presencial")
        self.assertEqual([e["title"] for e in roles["events"]], ["Exposicao de fotografia no IMS"])
        self.assertEqual(roles["events"][0]["categoria"], "cultura")
        self.assertEqual(roles["events"][0]["city"], "Rio de Janeiro")
        self.assertEqual(roles["events"][0]["bairro"], "Botafogo")
        self.assertTrue(str(roles["events"][0]["url"]).startswith("https://ims.com.br/"))
        vocab_roles, categorias = validar._vocab_roles()
        self.assertEqual(validar.check(tech, set(json.loads((ROOT / "data" / "tags.json").read_text())["tags"])), [])
        self.assertEqual(validar.check(roles, vocab_roles), [])
        self.assertEqual(validar.erros_extras_roles(roles["events"], categorias), [])
        bruto = json.dumps(tech) + json.dumps(roles)
        for proibido in (
            "@", "joao.silva", "lista@example.com", "programacao@example.com",
            "promo@example.com", "Joao da Silva", "nao pode vazar", "50%", "tenis",
        ):
            self.assertNotIn(proibido, bruto)
        for trecho in ("formato online", "fora do Rio", "passado", "sem hora", "entrada 100", "entrada 500", "entrada: 600"):
            self.assertIn(trecho, relatorio)
        self.assertNotIn("joao.silva@gmail.com", relatorio)
        self.assertNotIn("programacao@example.com", relatorio)
        online = {
            "title": "Meetup remoto", "start": "2026-12-18T19:00:00-03:00",
            "url": "https://luma.com/online99", "format": "online", "city": "Rio de Janeiro",
        }
        self.assertEqual(importar.merge([], online, HOJE), "online")
        self.assertNotIn("online99", bruto)

    def test_reclassifica_e_grava_na_outra_agenda(self):
        def cru(to, corpo):
            return (
                f"From: Lista <lista@example.com>\r\nTo: {to}\r\nSubject: x\r\n"
                "Content-Type: text/plain; charset=utf-8\r\n\r\n" + corpo
            ).encode()

        def modelo(texto):
            if "samba" in texto:
                return ([{
                    "title": "Roda de samba na Pedra do Sal",
                    "start": "2026-12-19T22:00:00-03:00",
                    "end": "",
                    "venue": "Pedra do Sal",
                    "address": "",
                    "city": "Rio de Janeiro",
                    "url": "https://example.com/samba",
                    "cost": "gratis",
                    "format": "presencial",
                    "language": "pt",
                    "description_pt": "Roda de samba ao vivo na Pedra do Sal.",
                }], 10, 4)
            if "Python" in texto:
                return ([{
                    "title": "Meetup de Python e IA",
                    "start": "2026-12-19T19:00:00-03:00",
                    "end": "",
                    "venue": "Botafogo",
                    "address": "",
                    "city": "Rio de Janeiro",
                    "url": "https://example.com/python-rio",
                    "cost": "gratis",
                    "format": "presencial",
                    "language": "pt",
                    "description_pt": "Encontro de python e IA para quem programa.",
                }], 10, 4)
            raise AssertionError(texto)

        with tempfile.TemporaryDirectory() as tmp:
            paths = destinos(Path(tmp))
            relatorio, codigo = correio.rodar(
                [
                    correio.CaixaTrabalho(
                        "Tech", "agenda.rio.eventos@gmail.com", "tech",
                        [("s", cru("agenda.rio.eventos@gmail.com", "Hoje tem roda de samba."))],
                    ),
                    correio.CaixaTrabalho(
                        "Rolês", "agenda.rio.roles@gmail.com", "roles",
                        [("p", cru("agenda.rio.roles@gmail.com", "Meetup de Python e IA no Rio."))],
                    ),
                ],
                hoje=HOJE, destinos=paths, abrir_redirect=lambda url: None,
                eventos_da_url=lambda url, agenda: ([], "sem dados"),
                modelo=modelo,
            )
            tech = json.loads(paths["tech"].read_text(encoding="utf-8"))
            roles = json.loads(paths["roles"].read_text(encoding="utf-8"))
        self.assertEqual(codigo, 0, relatorio)
        self.assertEqual([e["title"] for e in roles["events"]], ["Roda de samba na Pedra do Sal"])
        self.assertEqual(roles["events"][0]["categoria"], "festas")
        self.assertEqual([e["title"] for e in tech["events"]], ["Meetup de Python e IA"])
        self.assertNotIn("categoria", tech["events"][0])
        self.assertIn("foi para a agenda Rolês; a caixa era Tech", relatorio)
        self.assertIn("foi para a agenda Tech; a caixa era Rolês", relatorio)
        self.assertNotIn("lista@example.com", json.dumps(tech) + json.dumps(roles) + relatorio)

    def test_link_do_modelo_passa_pelo_url(self):
        chamadas = []

        def urls(url, agenda):
            chamadas.append(url)
            return [evento_base(url, title="Titulo da pagina")], None

        def modelo(texto):
            return ([{
                "title": "Titulo inventado",
                "start": "2026-12-18T19:00:00-03:00",
                "end": "",
                "venue": "Botafogo",
                "address": "",
                "city": "Rio de Janeiro",
                "url": "https://luma.com/pagina?utm_source=x",
                "cost": "gratis",
                "format": "presencial",
                "language": "pt",
                "description_pt": "Nao usar este texto.",
            }], 8, 3)

        raw = (
            "From: a@example.com\r\nTo: agenda.rio.eventos@gmail.com\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n\r\nSem link no texto.\r\n"
        ).encode()
        with tempfile.TemporaryDirectory() as tmp:
            paths = destinos(Path(tmp))
            _relatorio, codigo = correio.rodar(
                [correio.CaixaTrabalho("Tech", "agenda.rio.eventos@gmail.com", "tech", [("1", raw)])],
                hoje=HOJE, destinos=paths, abrir_redirect=lambda url: None,
                eventos_da_url=urls, modelo=modelo,
            )
            tech = json.loads(paths["tech"].read_text(encoding="utf-8"))
        self.assertEqual(codigo, 0)
        self.assertEqual(chamadas, ["https://luma.com/pagina"])
        self.assertEqual(tech["events"][0]["title"], "Titulo da pagina")

    def test_teto_de_tokens_nao_etiqueta_o_resto(self):
        chamadas = []

        def modelo(texto):
            chamadas.append(texto)
            return [], 300_000, 1

        def cru(corpo):
            return (
                "From: a@example.com\r\nTo: agenda.rio.roles@gmail.com\r\n"
                "Content-Type: text/plain; charset=utf-8\r\n\r\n" + corpo
            ).encode()

        marcados = []
        with tempfile.TemporaryDirectory() as tmp:
            paths = destinos(Path(tmp))
            relatorio, codigo = correio.rodar(
                [correio.CaixaTrabalho(
                    "Rolês", "agenda.rio.roles@gmail.com", "roles",
                    [("1", cru("primeira newsletter")), ("2", cru("segunda newsletter"))],
                    etiquetar=marcados.append,
                )],
                hoje=HOJE, destinos=paths, abrir_redirect=lambda url: None,
                eventos_da_url=lambda url, agenda: ([], None),
                modelo=modelo,
            )
        self.assertEqual(codigo, 0, relatorio)
        self.assertEqual(len(chamadas), 1)
        self.assertEqual(marcados, ["1"])
        self.assertIn("300000", relatorio)
        self.assertIn("não foi etiquetado", relatorio)

    def test_sem_chave_do_modelo_adia_newsletter_e_segue_link(self):
        marcados = []
        raw_link = (FIX / "correio_luma.eml").read_bytes()
        raw_sem = (FIX / "correio_sem_link.eml").read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            paths = destinos(Path(tmp))
            relatorio, codigo = correio.rodar(
                [correio.CaixaTrabalho(
                    "Tech", "agenda.rio.eventos@gmail.com", "tech",
                    [("luma", raw_link), ("ims", raw_sem)],
                    etiquetar=marcados.append,
                )],
                hoje=HOJE, destinos=paths,
                abrir_redirect=lambda url: "https://luma.com/pyrio42" if "bit.ly" in url else None,
                eventos_da_url=lambda url, agenda: ([evento_base(url)], None) if "pyrio42" in url else ([], "sem dados"),
                modelo=None,
            )
        self.assertEqual(codigo, 0, relatorio)
        self.assertEqual(marcados, ["luma"])
        self.assertIn("ANTHROPIC_API_KEY ausente", relatorio)

    def test_pedido_anthropic_sem_rede(self):
        visto = {}

        def abrir(req, timeout=0):
            visto["url"] = req.full_url
            visto["body"] = json.loads(req.data.decode())
            return Resposta({
                "stop_reason": "end_turn",
                "content": [{
                    "type": "tool_use",
                    "name": "registrar_eventos",
                    "input": {"eventos": []},
                }],
                "usage": {"input_tokens": 12, "output_tokens": 3},
            })

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "chave-de-teste"}):
            with patch("urllib.request.urlopen", side_effect=AssertionError("rede")):
                eventos, entrada, saida = correio.chamar_modelo("joao@example.com " + "a" * 40000, abrir=abrir)
        self.assertEqual(eventos, [])
        self.assertEqual((entrada, saida), (12, 3))
        self.assertEqual(visto["url"], correio.ANTHROPIC_URL)
        corpo = visto["body"]
        self.assertEqual(corpo["model"], "claude-haiku-5-5")
        self.assertNotIn("chave-de-teste", json.dumps(corpo))
        self.assertIn("Não invente", corpo["system"])
        self.assertIn("hora", corpo["system"])
        self.assertLessEqual(len(corpo["messages"][0]["content"]), 30_000)
        self.assertNotIn("joao@example.com", corpo["messages"][0]["content"])
        ferramenta = corpo["tools"][0]
        self.assertTrue(ferramenta["strict"])
        self.assertEqual(corpo["tool_choice"], {"type": "tool", "name": "registrar_eventos"})
        item = ferramenta["input_schema"]["properties"]["eventos"]["items"]
        self.assertFalse(item["additionalProperties"])
        self.assertEqual(
            set(item["properties"]),
            {"title", "start", "end", "venue", "address", "city", "url", "cost", "format", "language", "description_pt"},
        )
        self.assertEqual(set(item["required"]), set(item["properties"]))

    def test_limite_de_40_e_imap_so_le_e_etiqueta(self):
        muitos = FakeIMAP({str(i): b"x" for i in range(41)})
        uids, truncou = correio.uids_pendentes(muitos)
        self.assertEqual(len(uids), 40)
        self.assertTrue(truncou)

        fake = FakeIMAP({"7": (FIX / "correio_spam.eml").read_bytes()})
        relatorio_path = None
        with tempfile.TemporaryDirectory() as tmp:
            paths = destinos(Path(tmp))
            relatorio_path = Path(tmp) / "relatorio.md"
            saida, erro = io.StringIO(), io.StringIO()
            with patch.dict(os.environ, {
                "GMAIL_EVENTOS_APP_PASSWORD": "segredo-eventos",
                "GMAIL_ROLES_APP_PASSWORD": "",
                "ANTHROPIC_API_KEY": "chave-de-teste",
            }):
                with patch.object(correio.imaplib, "IMAP4_SSL", return_value=fake), \
                     patch.object(correio, "chamar_modelo", return_value=([], 7, 1)), \
                     patch.object(correio, "seguir", side_effect=AssertionError("rede")), \
                     patch.object(correio, "caminhos", return_value=paths), \
                     patch("urllib.request.urlopen", side_effect=AssertionError("rede")):
                    with redirect_stdout(saida), redirect_stderr(erro):
                        codigo = correio.main(["--relatorio", str(relatorio_path)])
            relatorio = relatorio_path.read_text(encoding="utf-8")
            tech = json.loads(paths["tech"].read_text(encoding="utf-8"))
        self.assertEqual(codigo, 0, relatorio + erro.getvalue())
        self.assertEqual(fake.user, "agenda.rio.eventos@gmail.com")
        self.assertEqual(fake.password, "segredo-eventos")
        self.assertEqual(fake.selecionada, '"[Gmail]/All Mail"')
        self.assertFalse(fake.readonly)
        busca = [c for c in fake.comandos if len(c) > 2 and c[1] == "SEARCH"]
        self.assertIn("newer_than:14d", busca[0][3])
        self.assertIn("-label:agenda-processado", busca[0][3])
        stores = [c for c in fake.comandos if len(c) > 1 and c[1] == "STORE"]
        self.assertEqual(len(stores), 1)
        self.assertIn("+X-GM-LABELS", stores[0])
        self.assertIn("agenda/processado", " ".join(str(p) for p in stores[0]))
        tudo = " ".join(str(p) for c in fake.comandos for p in c).upper()
        self.assertNotIn("\\DELETED", tudo)
        self.assertNotIn("EXPUNGE", tudo)
        self.assertNotIn("MOVE", tudo)
        self.assertEqual(tech["events"], [])
        self.assertIn("entrada 7", relatorio)
        self.assertIn("GMAIL_ROLES_APP_PASSWORD ausente", erro.getvalue())
        self.assertNotIn("segredo-eventos", relatorio + saida.getvalue() + erro.getvalue())
        self.assertNotIn("promo@example.com", relatorio)

    def test_senhas_ausentes_saem_zero(self):
        erro = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / "relatorio.md"
            with patch.dict(os.environ, {
                "GMAIL_EVENTOS_APP_PASSWORD": "",
                "GMAIL_ROLES_APP_PASSWORD": "",
            }):
                with patch.object(correio.imaplib, "IMAP4_SSL") as imap:
                    with redirect_stderr(erro):
                        codigo = correio.main(["--relatorio", str(destino)])
            texto = destino.read_text(encoding="utf-8")
        self.assertEqual(codigo, 0)
        imap.assert_not_called()
        self.assertIn("ausentes", erro.getvalue())
        self.assertIn("GMAIL_EVENTOS_APP_PASSWORD", texto)
        self.assertIn("GMAIL_ROLES_APP_PASSWORD", texto)

    def test_mailchimp_nao_abre_descadastro(self):
        direto = "https://example.us1.list-manage.com/unsubscribe?u=aaa&id=bbb"
        embrulhado = "https://example.us1.list-manage.com/track/click?u=aaa&id=bbb&e=zzz"
        preferencias = "https://mailchi.mp/abc/preferences"
        navegador = "https://example.us1.list-manage.com/track/click?u=aaa&id=bbb&e=nav"
        cabecalho = "https://example.us1.list-manage.com/track/click?u=soheader&id=bbb&e=hdr"
        bom = "https://bit.ly/showrio"
        self.assertTrue(correio.url_recusada(direto))
        self.assertTrue(correio.url_recusada(preferencias))
        self.assertFalse(correio.url_recusada(embrulhado))
        self.assertFalse(correio.url_recusada(cabecalho))
        self.assertTrue(correio.ancora_recusada("cancelar inscrição"))
        raw = (
            "From: Lista <lista@example.com>\r\n"
            "To: agenda.rio.roles@gmail.com\r\n"
            "Subject: boletim\r\n"
            f"List-Unsubscribe: <{cabecalho}>, <mailto:unsub@example.com>\r\n"
            "MIME-Version: 1.0\r\n"
            "Content-Type: multipart/alternative; boundary=xyz\r\n"
            "\r\n"
            "--xyz\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "\r\n"
            f"Samba na Pedra\r\n{bom}\r\n{direto}\r\n{preferencias}\r\n"
            "--xyz\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            "\r\n"
            "<html><body>"
            f'<a href="{bom}">Samba na Pedra</a>'
            f'<a href="{direto}">descadastrar</a>'
            f'<a href="{embrulhado}">cancelar inscrição</a>'
            f'<a href="{preferencias}">preferências</a>'
            f'<a href="{navegador}">ver no navegador</a>'
            f'<a href="{cabecalho}">o boletim</a>'
            '<a href="https://example.com/view-in-browser">View in browser</a>'
            "</body></html>\r\n"
            "--xyz--\r\n"
        ).encode()
        abertos = []
        vistos = []

        def urlopen(req, timeout=None):
            url = getattr(req, "full_url", str(req))
            abertos.append(url)
            if "bit.ly/showrio" not in url:
                raise OSError(url)

            class Destino:
                def geturl(self):
                    return "https://luma.com/showrio"

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            return Destino()

        def eventos_url(url, agenda):
            vistos.append(url)
            return [], "sem dados de evento"

        with tempfile.TemporaryDirectory() as tmp:
            paths = destinos(Path(tmp))
            with patch("urllib.request.urlopen", urlopen):
                relatorio, codigo = correio.rodar(
                    [correio.CaixaTrabalho(
                        "Rolês", "agenda.rio.roles@gmail.com", "roles", [("mc", raw)],
                    )],
                    hoje=HOJE,
                    destinos=paths,
                    abrir_redirect=correio.seguir,
                    eventos_da_url=eventos_url,
                    modelo=lambda texto: (_ for _ in ()).throw(AssertionError(texto[:120])),
                )
        self.assertEqual(codigo, 0, relatorio)
        self.assertEqual(abertos, [bom])
        self.assertEqual(vistos, ["https://luma.com/showrio"])
        junto = " ".join(abertos + vistos)
        for trecho in ("unsubscribe", "list-manage.com", "mailchi.mp", "preferences", "view-in-browser"):
            self.assertNotIn(trecho, junto)

    def test_no_maximo_quinze_rastreadores(self):
        urls = [f"https://bit.ly/n{i}" for i in range(16)]
        abertos = []

        def abrir(url):
            abertos.append(url)
            return f"https://luma.com/{url.rsplit('/', 1)[-1]}"

        uteis = correio.links_uteis("\n".join(urls), abrir)
        self.assertEqual(correio.MAX_RASTREADORES, 15)
        self.assertEqual(abertos, urls[:15])
        self.assertEqual(uteis, [f"https://luma.com/n{i}" for i in range(15)])

    def test_frc_da_caixa_eventos_vai_para_roles(self):
        descricao = (
            "Join Founders Running Club, Common Ground and More Hostel for a special "
            "Saturday gathering in Ipanema, bringing together founders, creatives, "
            "travelers and entrepreneurs."
        )
        frc = evento_base(
            "https://luma.com/frcnovo",
            title="FRC Rio x Common Ground x More Hostels",
            start="2026-11-28T16:30:00-03:00",
            end="2026-11-28T22:00:00-03:00",
            venue="More Ipanema Hostel",
            description={"pt": descricao},
            tags=["founders"],
        )
        self.assertEqual(correio.escolher_agenda(frc, "tech"), ("roles", True))
        corrida_tech = {
            "title": "Web Summit Run",
            "description": {"pt": "Running club during the Web Summit with founders."},
            "city": "Rio de Janeiro",
        }
        self.assertEqual(correio.escolher_agenda(corrida_tech, "tech")[0], "tech")
        idiomas = {
            "title": "Mundo Lingo",
            "description": {"pt": "Language exchange for founders in Botafogo."},
        }
        self.assertEqual(correio.escolher_agenda(idiomas, "tech"), ("roles", True))
        samba = {
            "title": "Roda de samba",
            "description": {"pt": "Samba dos founders na Pedra do Sal."},
        }
        self.assertEqual(correio.escolher_agenda(samba, "tech"), ("roles", True))

        def cru(url):
            return (
                "From: a@example.com\r\nTo: agenda.rio.eventos@gmail.com\r\n"
                "Content-Type: text/plain; charset=utf-8\r\n\r\n"
                f"FRC Rio x Common Ground x More Hostels\r\n{url}\r\n"
            ).encode()

        with tempfile.TemporaryDirectory() as tmp:
            paths = destinos(Path(tmp))
            relatorio, codigo = correio.rodar(
                [correio.CaixaTrabalho(
                    "Tech", "agenda.rio.eventos@gmail.com", "tech",
                    [("novo", cru("https://luma.com/frcnovo"))],
                )],
                hoje=HOJE,
                destinos=paths,
                abrir_redirect=lambda url: None,
                eventos_da_url=lambda url, agenda: ([dict(frc, url=url)], None),
                modelo=lambda texto: (_ for _ in ()).throw(AssertionError(texto[:80])),
            )
            tech = json.loads(paths["tech"].read_text(encoding="utf-8"))
            gravados = json.loads(paths["roles"].read_text(encoding="utf-8"))
        self.assertEqual(codigo, 0, relatorio)
        self.assertEqual(tech["events"], [])
        self.assertEqual(len(gravados["events"]), 1)
        novo = gravados["events"][0]
        self.assertEqual(novo["url"], "https://luma.com/frcnovo")
        self.assertIn("corrida", novo["tags"])
        self.assertNotIn("founders", novo["tags"])
        self.assertEqual(novo["categoria"], "ao-ar-livre")
        self.assertIn("foi para a agenda Rolês; a caixa era Tech", relatorio)

    def test_ignora_asset_loja_e_luma_que_nao_e_evento(self):
        recusados = [
            "https://luma.com/capa.png",
            "https://luma.com/foto.jpg",
            "https://luma.com/foto.jpeg",
            "https://luma.com/foto.gif",
            "https://luma.com/foto.svg",
            "https://luma.com/foto.webp",
            "https://luma.com/favicon.ico",
            "https://cdn.exemplo.com/a.jpg",
            "https://luma.com/email/open",
            "https://apps.apple.com/br/app/luma/id1",
            "https://itunes.apple.com/app/id1",
            "https://play.google.com/store/apps/details?id=com.luma",
            "https://luma.com/",
            "https://luma.com/settings",
            "https://luma.com/ios",
            "https://luma.com/android",
            "https://luma.com/home",
            "https://luma.com/discover",
            "https://lu.ma/discover?utm_source=x",
        ]
        for url in recusados:
            self.assertTrue(correio.url_irrelevante(url), url)
            self.assertTrue(correio.url_recusada(url), url)
        self.assertFalse(correio.url_irrelevante("https://luma.com/evento123"))
        self.assertFalse(correio.url_irrelevante("https://luma.com/homecoming"))
        texto = "\n".join(["https://luma.com/evento123", *recusados])
        self.assertEqual(
            correio.links_uteis(texto, lambda url: (_ for _ in ()).throw(AssertionError(url))),
            ["https://luma.com/evento123"],
        )
        self.assertEqual(
            correio.links_uteis(
                "https://luma.com/en/evento-rio\nhttps://luma.com/pt-br/evento-rio?lang=pt",
                lambda url: None,
            ),
            ["https://luma.com/en/evento-rio"],
        )
        bruto = (
            "From: a@example.com\r\nTo: agenda.rio.eventos@gmail.com\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n\r\n"
            + texto + "\n"
        ).encode()
        with tempfile.TemporaryDirectory() as tmp:
            paths = destinos(Path(tmp))
            relatorio, codigo = correio.rodar(
                [correio.CaixaTrabalho(
                    "Tech", "agenda.rio.eventos@gmail.com", "tech", [("1", bruto)],
                )],
                hoje=HOJE, destinos=paths, abrir_redirect=lambda url: None,
                eventos_da_url=lambda url, agenda: ([], "sem dados de evento"),
                modelo=lambda texto: (_ for _ in ()).throw(AssertionError("modelo")),
            )
        self.assertEqual(codigo, 0, relatorio)
        self.assertIn("https://luma.com/evento123", relatorio)
        self.assertEqual(relatorio.count("https://luma.com/evento123"), 1)
        for trecho in (
            "capa.png", "foto.jpg", "foto.jpeg", "foto.gif", "foto.svg", "foto.webp",
            "favicon.ico", "cdn.exemplo.com", "/email/", "apps.apple.com",
            "itunes.apple.com", "play.google.com", "luma.com/settings", "luma.com/ios",
            "luma.com/android", "luma.com/home", "luma.com/discover",
        ):
            self.assertNotIn(trecho, relatorio, trecho)

    def test_descartados_unicos_por_url(self):
        def cru(url):
            return (
                "From: a@example.com\r\nTo: agenda.rio.eventos@gmail.com\r\n"
                "Content-Type: text/plain; charset=utf-8\r\n\r\n"
                f"Veja {url}\n{url}\n"
            ).encode()

        with tempfile.TemporaryDirectory() as tmp:
            paths = destinos(Path(tmp))
            relatorio, codigo = correio.rodar(
                [correio.CaixaTrabalho(
                    "Tech", "agenda.rio.eventos@gmail.com", "tech",
                    [
                        ("a", cru("https://luma.com/online99")),
                        ("b", cru("https://luma.com/online99?utm_source=nl")),
                        ("c", cru("https://luma.com/velho")),
                    ],
                )],
                hoje=HOJE, destinos=paths, abrir_redirect=lambda url: None,
                eventos_da_url=falso_url,
                modelo=lambda texto: (_ for _ in ()).throw(AssertionError("modelo")),
            )
        self.assertEqual(codigo, 0, relatorio)
        self.assertEqual(relatorio.count("https://luma.com/online99"), 1)
        self.assertIn("2 e-mails", relatorio)
        self.assertIn("formato online", relatorio)
        self.assertIn("1 e-mail", relatorio)
        self.assertIn("passado", relatorio)

    def test_readme_e_workflow(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for trecho in (
            "GMAIL_EVENTOS_APP_PASSWORD",
            "GMAIL_ROLES_APP_PASSWORD",
            "ANTHROPIC_API_KEY",
            "agenda.rio.eventos@gmail.com",
            "agenda.rio.roles+cultura@gmail.com",
            "agenda/processado",
            "importar_correio.py",
        ):
            self.assertIn(trecho, readme)
        texto = (ROOT / ".github" / "workflows" / "importar-correio.yml").read_text(encoding="utf-8")
        doc = validar.load_yaml(texto)
        self.assertIn('cron: "47 11 * * *"', texto)
        self.assertIn("workflow_dispatch:", texto)
        self.assertEqual(doc["concurrency"]["group"], "dados-agenda")
        self.assertIs(doc["concurrency"]["cancel-in-progress"], False)
        passo = next(
            p["with"] for p in doc["jobs"]["importar-correio"]["steps"]
            if str(p.get("uses", "")).startswith("peter-evans/create-pull-request@")
        )
        self.assertEqual(
            passo["branch"],
            "importador/revisar-${{ steps.publicar.outputs.agenda }}-${{ steps.publicar.outputs.dia }}",
        )
        self.assertEqual(
            passo["title"],
            "Revisar importação automática (${{ steps.publicar.outputs.rotulo }}, ${{ steps.publicar.outputs.dia }})",
        )
        self.assertIs(passo["delete-branch"], False)
        self.assertIn("TZ=America/Sao_Paulo date +%F", texto)
        self.assertIn("git pull --rebase origin main", texto)
        self.assertIn("python scripts/publicar_importacao.py correio", texto)
        self.assertIn("gh workflow run pages.yml --ref main", texto)
        self.assertNotIn("delete-branch: true", texto)
        self.assertNotIn("importador/correio-${{ steps.data.outputs.dia }}", texto)
        self.assertIn("data/events.json", texto)
        self.assertIn("data/roles.json", texto)
        for nome in ("GMAIL_EVENTOS_APP_PASSWORD", "GMAIL_ROLES_APP_PASSWORD", "ANTHROPIC_API_KEY"):
            self.assertIn(nome, texto)

    def test_ims_sympla_503_cai_no_texto(self):
        raw = (FIX / "correio_ims_sympla.eml").read_bytes()
        pedidos = []

        class RespostaHttp:
            def __init__(self, corpo: bytes):
                self._corpo = corpo
                self.headers = email.message.EmailMessage()

            def read(self):
                return self._corpo

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def urlopen(req, timeout=None):
            url = getattr(req, "full_url", str(req))
            pedidos.append(url)
            if url.endswith("/robots.txt"):
                return RespostaHttp(b"User-agent: *\nAllow: /\n")
            if "sympla.com.br/evento/" in url:
                raise urllib.error.HTTPError(
                    url, 503, "Service Unavailable", email.message.EmailMessage(), None,
                )
            raise AssertionError(url)

        def modelo(texto):
            self.assertIn("Exposicao de fotografia", texto)
            self.assertIn("sympla.com.br", texto)
            self.assertNotIn("@", texto)
            return ([{
                "title": "Exposicao de fotografia no IMS",
                "start": "2026-12-18T19:00:00-03:00",
                "end": "2026-12-18T21:00:00-03:00",
                "venue": "IMS Botafogo",
                "address": "Rua Marques de Abrantes, 123",
                "city": "Rio de Janeiro",
                "url": "https://www.sympla.com.br/evento/mostra-ims/321",
                "cost": "gratis",
                "format": "presencial",
                "language": "pt",
                "description_pt": "Exposicao de fotografia no IMS, em Botafogo, com entrada gratuita.",
            }], 40, 12)

        with tempfile.TemporaryDirectory() as tmp:
            paths = destinos(Path(tmp))
            with patch("urllib.request.urlopen", urlopen):
                relatorio, codigo = correio.rodar(
                    [correio.CaixaTrabalho(
                        "Rolês", "agenda.rio.roles@gmail.com", "roles", [("ims", raw)],
                    )],
                    hoje=HOJE, destinos=paths, abrir_redirect=lambda url: None,
                    eventos_da_url=correio.eventos_da_url, modelo=modelo,
                )
            roles = json.loads(paths["roles"].read_text(encoding="utf-8"))
        self.assertEqual(codigo, 0, relatorio)
        self.assertTrue(any("sympla.com.br/evento/" in url for url in pedidos), pedidos)
        self.assertTrue(any(url.endswith("/robots.txt") for url in pedidos), pedidos)
        self.assertEqual([e["title"] for e in roles["events"]], ["Exposicao de fotografia no IMS"])
        self.assertEqual(
            roles["events"][0]["url"],
            "https://www.sympla.com.br/evento/mostra-ims/321",
        )
        self.assertEqual(roles["events"][0]["categoria"], "cultura")
        self.assertNotIn("erro ao abrir", relatorio)
        self.assertNotIn("JSON-LD", relatorio)
        self.assertNotIn("@", json.dumps(roles))

    def test_robots_e_jsonld_caem_no_texto(self):
        self.assertTrue(correio.falha_pede_texto("erro ao abrir: HTTPError"))
        self.assertTrue(correio.falha_pede_texto("robots.txt respondeu 503"))
        self.assertTrue(correio.falha_pede_texto("robots.txt falhou: URLError"))
        self.assertTrue(correio.falha_pede_texto("sem iCal nem schema.org/Event em JSON-LD"))
        self.assertFalse(correio.falha_pede_texto("robots.txt não permite a leitura"))
        self.assertFalse(correio.falha_pede_texto("sem dados de evento"))

        def cru(url, corpo):
            return (
                "From: a@example.com\r\nTo: agenda.rio.roles@gmail.com\r\n"
                "Content-Type: text/plain; charset=utf-8\r\n\r\n"
                f"{corpo}\n{url}\n"
            ).encode()

        class RespostaHttp:
            def __init__(self, corpo: bytes):
                self._corpo = corpo
                self.headers = email.message.EmailMessage()

            def read(self):
                return self._corpo

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def urlopen(req, timeout=None):
            url = getattr(req, "full_url", str(req))
            if "luma.com" in url and url.endswith("/robots.txt"):
                raise urllib.error.HTTPError(
                    url, 503, "Service Unavailable", email.message.EmailMessage(), None,
                )
            if "doity.com.br" in url and url.endswith("/robots.txt"):
                return RespostaHttp(b"User-agent: *\nAllow: /\n")
            if "doity.com.br" in url:
                return RespostaHttp(b"<html><body>sem evento</body></html>")
            raise AssertionError(url)

        def modelo(texto):
            if "gravura" in texto:
                return ([{
                    "title": "Exposicao de gravura",
                    "start": "2026-12-19T18:00:00-03:00",
                    "end": "",
                    "venue": "IMS Paulista",
                    "address": "",
                    "city": "Rio de Janeiro",
                    "url": "https://luma.com/gravura-ims",
                    "cost": "gratis",
                    "format": "presencial",
                    "language": "pt",
                    "description_pt": "Exposicao de gravura no IMS.",
                }], 10, 4)
            if "serigrafia" in texto:
                return ([{
                    "title": "Exposicao de serigrafia",
                    "start": "2026-12-20T15:00:00-03:00",
                    "end": "",
                    "venue": "Centro",
                    "address": "",
                    "city": "Rio de Janeiro",
                    "url": "https://doity.com.br/serigrafia-rio",
                    "cost": "gratis",
                    "format": "presencial",
                    "language": "pt",
                    "description_pt": "Exposicao de serigrafia no centro.",
                }], 10, 4)
            raise AssertionError(texto[:160])

        with tempfile.TemporaryDirectory() as tmp:
            paths = destinos(Path(tmp))
            with patch("urllib.request.urlopen", urlopen):
                relatorio, codigo = correio.rodar(
                    [correio.CaixaTrabalho(
                        "Rolês", "agenda.rio.roles@gmail.com", "roles", [
                            ("robots", cru(
                                "https://luma.com/gravura-ims",
                                "Exposicao de gravura no IMS, dia 19 de dezembro de 2026, as 18h.",
                            )),
                            ("jsonld", cru(
                                "https://doity.com.br/serigrafia-rio",
                                "Exposicao de serigrafia no centro, dia 20 de dezembro de 2026, as 15h.",
                            )),
                        ],
                    )],
                    hoje=HOJE, destinos=paths, abrir_redirect=lambda url: None,
                    eventos_da_url=correio.eventos_da_url, modelo=modelo,
                )
            roles = json.loads(paths["roles"].read_text(encoding="utf-8"))
        self.assertEqual(codigo, 0, relatorio)
        self.assertEqual(
            [e["title"] for e in roles["events"]],
            ["Exposicao de gravura", "Exposicao de serigrafia"],
        )
        self.assertNotIn("robots.txt", relatorio)
        self.assertNotIn("JSON-LD", relatorio)

    def test_shotgun_confirmacao_nao_abre_conta(self):
        raw = (FIX / "correio_shotgun_confirmacao.eml").read_bytes()
        contas = [
            "https://shotgun.live/confirm?token=teste",
            "https://shotgun.live/users/confirmar",
            "https://shotgun.live/verify-email",
            "https://shotgun.live/verificar",
            "https://shotgun.live/activate",
            "https://shotgun.live/ativar",
            "https://shotgun.live/password/reset",
            "https://shotgun.live/login",
            "https://shotgun.live/signin",
            "https://shotgun.live/users/sign-in",
            "https://shotgun.live/events/festa-rio?token=teste",
        ]
        for url in contas:
            self.assertTrue(correio.url_de_conta(url), url)
            self.assertTrue(correio.url_recusada(url), url)
        evento = "https://shotgun.live/events/festa-rio"
        self.assertFalse(correio.url_de_conta(evento))
        abertos = []

        def abrir(url):
            abertos.append(url)
            raise AssertionError(url)

        def eventos_url(url, agenda):
            abertos.append(url)
            return [], "sem dados de evento"

        with tempfile.TemporaryDirectory() as tmp:
            paths = destinos(Path(tmp))
            with patch("urllib.request.urlopen", side_effect=AssertionError("rede")):
                relatorio, codigo = correio.rodar(
                    [correio.CaixaTrabalho(
                        "Rolês", "agenda.rio.roles@gmail.com", "roles", [("sg", raw)],
                    )],
                    hoje=HOJE, destinos=paths, abrir_redirect=abrir,
                    eventos_da_url=eventos_url,
                    modelo=lambda texto: (_ for _ in ()).throw(AssertionError("modelo")),
                )
            gravado = paths["roles"].read_text(encoding="utf-8")
        self.assertEqual(codigo, 0, relatorio)
        self.assertEqual(abertos, [evento])
        junto = relatorio + gravado + " ".join(abertos)
        for url in contas:
            self.assertNotIn(url, junto)
        self.assertNotIn("token=", junto)
        self.assertNotIn("@", gravado)

    def test_listas_songkick_eventim_e_ra(self):
        def proibe(url, agenda=None):
            raise AssertionError(url)

        casos = [
            ("correio_songkick.eml", [
                ("Gilberto Gil", "Circo Voador", "2026-12-18T21:00:00-03:00",
                 "https://www.songkick.com/concerts/111-gilberto-gil", False),
                ("Djavan", "Qualistage", "2026-12-19T20:00:00-03:00",
                 "https://www.songkick.com/concerts/222-djavan", False),
                ("Martinho da Vila", "Praia de Copacabana", "2026-12-20T16:00:00-03:00",
                 "https://www.songkick.com/concerts/333-martinho", True),
            ]),
            ("correio_eventim.eml", [
                ("Ana Carolina", "Teatro Riachuelo", "2026-12-18T21:00:00-03:00",
                 "https://www.eventim.com.br/event/ana-carolina-rio-111", False),
                ("Jorge Ben Jor", "Qualistage", "2026-12-19T20:00:00-03:00",
                 "https://www.eventim.com.br/event/jorge-ben-jor-222", False),
            ]),
            ("correio_ra.eml", [
                ("Vera", "D-Edge Rio", "2026-12-18T23:00:00-03:00",
                 "https://ra.co/events/190001", False),
                ("Carlita", "Club Laroc", "2026-12-19T22:00:00-03:00",
                 "https://ra.co/events/190002", False),
            ]),
        ]
        for nome, esperados in casos:
            with self.subTest(nome=nome):
                raw = (FIX / nome).read_bytes()
                self.assertGreater(len(esperados), 1)
                with tempfile.TemporaryDirectory() as tmp:
                    paths = destinos(Path(tmp))
                    with patch("urllib.request.urlopen", side_effect=AssertionError("rede")):
                        relatorio, codigo = correio.rodar(
                            [correio.CaixaTrabalho(
                                "Rolês", "agenda.rio.roles@gmail.com", "roles", [("1", raw)],
                            )],
                            hoje=HOJE, destinos=paths, abrir_redirect=proibe,
                            eventos_da_url=proibe,
                            modelo=lambda texto: (_ for _ in ()).throw(AssertionError("modelo")),
                        )
                    roles = json.loads(paths["roles"].read_text(encoding="utf-8"))
                self.assertEqual(codigo, 0, relatorio)
                self.assertEqual(len(roles["events"]), len(esperados), relatorio)
                por_titulo = {e["title"]: e for e in roles["events"]}
                self.assertEqual(set(por_titulo), {item[0] for item in esperados})
                for titulo, local, inicio, url, de_graca in esperados:
                    ev = por_titulo[titulo]
                    self.assertEqual(ev["venue"], local, titulo)
                    self.assertEqual(ev["start"], inicio, titulo)
                    self.assertEqual(ev["url"], url, titulo)
                    self.assertEqual(ev["categoria"], "shows", titulo)
                    self.assertIn("shows", ev["tags"], titulo)
                    if de_graca:
                        self.assertIn("de-graca", ev["tags"], titulo)
                        self.assertEqual(ev["cost"]["type"], "gratis", titulo)
                    else:
                        self.assertNotIn("de-graca", ev["tags"], titulo)
                bruto = json.dumps(roles)
                self.assertNotIn("@", bruto)
                self.assertNotIn("lista@example.com", bruto + relatorio)


if __name__ == "__main__":
    unittest.main()
