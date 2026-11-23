"""Testes do importador e do validador. Rodar com:  python -m unittest discover -s scripts"""
import contextlib
import datetime as dt
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import importar  # noqa: E402
import validar  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
HOJE = dt.date(2030, 1, 1)


class TestImportar(unittest.TestCase):
    def test_jsonld(self):
        page = (FIX / "evento_jsonld.html").read_text(encoding="utf-8")
        ld = importar.jsonld_events(page)
        self.assertEqual(len(ld), 1)
        ev = importar.from_jsonld(ld[0], "https://exemplo.org/e", importar.meta_tags(page))
        self.assertEqual(ev["start"], "2030-03-10T19:00:00-03:00")
        self.assertEqual(ev["cost"]["type"], "gratis")
        self.assertEqual(ev["format"], "presencial")
        self.assertEqual(ev["venue"], "Espaço Exemplo")
        self.assertIn("python", ev["tags"])
        self.assertIn("ia", ev["tags"])

    def test_sympla_next_data_tem_data(self):
        page = (FIX / "evento_sympla.html").read_text(encoding="utf-8")
        ev = importar.event_from_page(
            page, "https://www.sympla.com.br/evento/2-encontro-da-rede-dr-empreendedor/3635352?utm_source=whats")
        self.assertEqual(ev["start"], "2026-11-26T08:30:00-03:00")
        self.assertEqual(ev["end"], "2026-11-27T17:30:00-03:00")
        self.assertTrue(ev["time_known"])
        self.assertEqual(ev["status"], "confirmado")
        self.assertEqual(ev["venue"], "Ibmec - Unidade Barra")
        self.assertEqual(ev["address"], "Avenida Armando Lombardi, 940")
        self.assertEqual(ev["city"], "Rio de Janeiro")
        self.assertEqual(ev["format"], "presencial")
        self.assertEqual(ev["cost"]["type"], "pago")
        self.assertEqual(ev["url"], "https://www.sympla.com.br/evento/2-encontro-da-rede-dr-empreendedor/3635352")
        self.assertIn("empreendedorismo", ev["tags"])
        self.assertIn("startups", ev["tags"])

    def test_doity_data_com_fuso_colado(self):
        self.assertEqual(importar.to_iso("2026-09-15-0300:00"), "2026-09-15T00:00:00-03:00")
        self.assertEqual(importar.to_iso("2026-12-04-0323:59"), "2026-12-04T23:59:00-03:00")
        page = (FIX / "evento_doity.html").read_text(encoding="utf-8")
        ev = importar.event_from_page(page, "https://doity.com.br/exemplo")
        self.assertEqual(ev["start"], "2026-09-15T00:00:00-03:00")
        self.assertEqual(ev["end"], "2026-12-04T23:59:00-03:00")
        self.assertEqual(ev["format"], "online")
        self.assertEqual(ev["title"], "Prêmio Exemplo")

    def test_sympla_data_com_espaco(self):
        self.assertEqual(importar.to_iso("2026-11-26 08:30:00"), "2026-11-26T08:30:00-03:00")
        page = """<script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{"hydrationData":{"eventHydration":{"event":{
  "name":"Encontro","startDate":"2026-11-26 08:30:00","endDate":"2026-11-27 17:30:00",
  "eventsAddress":{"name":"Ibmec","city":"Rio de Janeiro"}
}}}}}}
</script>"""
        ev = importar.event_from_page(page, "https://www.sympla.com.br/evento/x/1")
        self.assertEqual(ev["start"], "2026-11-26T08:30:00-03:00")
        self.assertEqual(ev["end"], "2026-11-27T17:30:00-03:00")

    def test_jsonld_nao_e_substituido_pela_data_do_sympla(self):
        page = """<html><head>
<script type="application/ld+json">
{"@type":"Event","name":"Título curado","startDate":"2030-03-10T19:00:00-03:00"}
</script>
<script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{"hydrationData":{"eventHydration":{"event":{
  "name":"Outro título","startDate":"2026-11-26 08:30:00",
  "eventsAddress":{"name":"Ibmec - Unidade Barra","city":"Rio de Janeiro"}
}}}}}}
</script></head></html>"""
        ev = importar.event_from_page(page, "https://www.sympla.com.br/evento/x/1")
        self.assertEqual(ev["title"], "Título curado")
        self.assertEqual(ev["start"], "2030-03-10T19:00:00-03:00")
        self.assertEqual(ev["venue"], "Ibmec - Unidade Barra")
        self.assertEqual(ev["city"], "Rio de Janeiro")

    def test_ics(self):
        evs = importar.ics_events((FIX / "calendario.ics").read_text(encoding="utf-8"))
        self.assertEqual(len(evs), 2)
        self.assertEqual(evs[0]["start"], "2030-04-05T09:00:00-03:00")  # 12:00 UTC = 09:00 no Rio
        self.assertEqual(evs[0]["url"], "https://exemplo.org/hackathon")
        self.assertIn("hackathon", evs[0]["tags"])
        self.assertEqual(evs[1]["start"], "2030-04-10")
        self.assertFalse(evs[1]["time_known"])
        self.assertEqual(evs[1]["format"], "online")

    def test_whatsapp_so_links_de_eventos(self):
        links = importar.whatsapp_links(FIX / "chat_exemplo.txt")
        self.assertEqual(links, ["https://luma.com/abc123", "https://www.sympla.com.br/evento/teste/123"])
        self.assertFalse(any("90000" in u for u in links))

    def test_whatsapp_desde(self):
        links = importar.whatsapp_links(FIX / "chat_exemplo.txt", since=dt.date(2030, 3, 2))
        self.assertEqual(links, ["https://www.sympla.com.br/evento/teste/123", "https://luma.com/abc123"])

    def test_merge_nao_sobrescreve(self):
        existentes = [{"id": "x", "title": "Python Rio #42", "url": "https://exemplo.org/e",
                       "start": "2030-03-10T19:00:00-03:00", "venue": "Lugar curado à mão", "image": None}]
        novo = {"title": "Outro título", "url": "https://exemplo.org/e", "start": "2030-03-10T19:00:00-03:00",
                "venue": "Lugar do importador", "image": "https://exemplo.org/capa.png", "format": "presencial"}
        self.assertEqual(importar.merge(existentes, novo, HOJE), "completado")
        self.assertEqual(existentes[0]["venue"], "Lugar curado à mão")
        self.assertEqual(existentes[0]["title"], "Python Rio #42")
        self.assertEqual(existentes[0]["image"], "https://exemplo.org/capa.png")

    def test_merge_filtra(self):
        lista = []
        passado = {"title": "Velho", "start": "2029-12-01T19:00:00-03:00", "url": "https://a.org/1"}
        sem_data = {"title": "Sem data", "start": None, "url": "https://a.org/2"}
        sp = {"title": "Em SP", "start": "2030-02-01T19:00:00-03:00", "url": "https://a.org/3",
              "format": "presencial", "venue": "Auditório", "city": "São Paulo"}
        self.assertEqual(importar.merge(lista, passado, HOJE), "passado")
        self.assertTrue(importar.merge(lista, sem_data, HOJE).startswith("sem data"))
        self.assertEqual(importar.merge(lista, sp, HOJE), "fora do Rio")
        self.assertEqual(lista, [])

    def test_historico_guarda_passado_antigo_e_outra_cidade(self):
        lista = []
        antigo = {"title": "Antigo", "start": "2024-01-15T19:00:00-03:00", "url": "https://luma.com/antigo",
                  "format": "presencial", "city": "Rio de Janeiro"}
        sp = {"title": "Em SP", "start": "2030-02-01T19:00:00-03:00", "url": "https://luma.com/sp",
              "format": "presencial", "city": "São Paulo"}
        self.assertEqual(importar.merge(lista, antigo, HOJE, historico=True), "novo")
        self.assertEqual(importar.merge(lista, sp, HOJE, historico=True), "novo")
        self.assertEqual(lista[0]["start"][:10], "2024-01-15")
        self.assertEqual(lista[1]["city"], "São Paulo")

    def test_historico_nao_sobrescreve_e_nao_duplica_chave(self):
        lista = []
        primeiro = {"title": "Um", "start": "2030-02-01T19:00:00-03:00",
                    "url": "https://luma.com/abc?locale=pt-BR", "format": "presencial", "venue": "Sala curada"}
        outro = {"title": "Outro título", "start": "2030-02-01T19:00:00-03:00",
                 "url": "https://luma.com/abc", "format": "presencial", "venue": "Sala do importador",
                 "image": "https://exemplo.org/capa.png"}
        self.assertEqual(importar.merge(lista, primeiro, HOJE, historico=True), "novo")
        self.assertEqual(importar.merge(lista, outro, HOJE, historico=True), "completado")
        self.assertEqual(len(lista), 1)
        self.assertEqual(lista[0]["title"], "Um")
        self.assertEqual(lista[0]["venue"], "Sala curada")
        self.assertEqual(lista[0]["url"], "https://luma.com/abc?locale=pt-BR")
        self.assertEqual(lista[0]["image"], "https://exemplo.org/capa.png")

    def test_historico_id_repetido_ganha_sufixo(self):
        lista = []
        a = {"title": "Meetup", "start": "2030-02-01T19:00:00-03:00", "url": "https://luma.com/aaa111", "format": "presencial"}
        b = {"title": "Meetup", "start": "2030-02-01T19:00:00-03:00", "url": "https://luma.com/bbb222", "format": "presencial"}
        self.assertEqual(importar.merge(lista, a, HOJE, historico=True), "novo")
        self.assertEqual(importar.merge(lista, b, HOJE, historico=True), "novo")
        self.assertNotEqual(lista[0]["id"], lista[1]["id"])
        self.assertEqual(len(lista), 2)

    def test_clean_url(self):
        self.assertEqual(importar.clean_url("http://lu.ma/x?tk=1&utm_source=a&id=7"), "https://luma.com/x?id=7")

    def test_luma_url_colada(self):
        limpa = importar.clean_url("https://luma.com/4cy8s78qBora?")
        self.assertEqual(limpa, "https://luma.com/4cy8s78q")
        self.assertIn(validar.url_chave(limpa), validar.chaves_descartadas())
        self.assertEqual(
            importar.clean_url("https://luma.com/founderslive-rio-de-janeiro-2026-11"),
            "https://luma.com/founderslive-rio-de-janeiro-2026-11",
        )
        self.assertEqual(importar.clean_url("https://luma.com/StellarHalftimeBR"), "https://luma.com/StellarHalftimeBR")

    def test_luma_sem_jsonld_le_start_at(self):
        page = (FIX / "evento_luma.html").read_text(encoding="utf-8")
        self.assertEqual(importar.jsonld_events(page), [])
        ev = importar.event_from_page(page, "https://luma.com/exemplo?tk=ABC")
        self.assertEqual(ev["start"], "2026-11-04T18:00:00-03:00")
        self.assertEqual(ev["end"], "2026-11-04T19:00:00-03:00")
        self.assertEqual(ev["format"], "online")
        self.assertEqual(ev["cost"]["type"], "gratis")
        self.assertEqual(ev["organizer"], "Comunidade Exemplo")
        self.assertEqual(ev["url"], "https://luma.com/exemplo")
        self.assertIn("startups", ev["tags"])

    def test_jsonld_nao_e_substituido_pela_data_do_luma(self):
        page = """<html><head>
<script type="application/ld+json">
{"@type":"Event","name":"Título curado","startDate":"2030-05-01T19:00:00-03:00",
 "location":{"@type":"Place","name":"Sala curada","address":{"addressLocality":"Rio de Janeiro"}}}
</script>
<script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{"initialData":{"data":{"event":{
  "name":"Outro","start_at":"2026-11-04T21:00:00.000Z","location_type":"meet"
}}}}}}
</script></head></html>"""
        ev = importar.event_from_page(page, "https://luma.com/exemplo")
        self.assertEqual(ev["title"], "Título curado")
        self.assertEqual(ev["start"], "2030-05-01T19:00:00-03:00")
        self.assertEqual(ev["venue"], "Sala curada")
        self.assertEqual(ev["city"], "Rio de Janeiro")

    def test_luma_presencial_preenche_cidade_vazia(self):
        page = """<script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{"initialData":{"data":{"event":{
  "name":"Meetup de Python",
  "start_at":"2026-11-10T22:00:00.000Z",
  "location_type":"offline",
  "geo_address_info":{"city":"Rio de Janeiro","address":"Casa Exemplo","short_address":"Rua 1"}
}}}}}}
</script>"""
        ev = importar.event_from_page(page, "https://luma.com/py")
        self.assertEqual(ev["start"], "2026-11-10T19:00:00-03:00")
        self.assertEqual(ev["format"], "presencial")
        self.assertEqual(ev["venue"], "Casa Exemplo")
        self.assertEqual(ev["address"], "Rua 1")
        self.assertEqual(ev["city"], "Rio de Janeiro")

    def test_empreendedor_parece_tech(self):
        ev = {
            "title": "2º Encontro da Rede Dr. Empreendedor",
            "city": "Rio de Janeiro",
            "venue": "Ibmec",
            "start": "2026-11-26T08:30:00-03:00",
            "url": "https://www.sympla.com.br/evento/x/1",
            "source": "sympla.com.br",
            "tags": ["empreendedorismo"],
            "description": {"pt": "Dois dias de conexão no Rio."},
        }
        self.assertTrue(importar.parece_tech(ev))
        self.assertNotIn("não parece tech", importar.bloco_novo(ev, ev["url"]))

    def test_descartado_nao_entra(self):
        lista = []
        novo = {"title": "Aprendizagem", "start": "2030-02-01T19:00:00-03:00",
                "url": "https://lu.ma/kcgfyftk/?tk=1", "format": "presencial", "city": "Rio de Janeiro"}
        self.assertEqual(importar.merge(lista, novo, HOJE, validar.chaves_descartadas()), "descartado")
        self.assertEqual(lista, [])

    def test_descartado_nao_completa(self):
        existentes = [{"id": "x", "title": "X", "url": "https://luma.com/kcgfyftk",
                       "start": "2030-03-10T19:00:00-03:00", "venue": None}]
        novo = {"title": "Outro", "url": "https://www.luma.com/KCGFYFTK?tk=9",
                "start": "2030-03-10T19:00:00-03:00", "venue": "Sala"}
        self.assertEqual(importar.merge(existentes, novo, HOJE), "descartado")
        self.assertIsNone(existentes[0]["venue"])
        self.assertEqual(len(existentes), 1)

    def test_relatorio_marca_revisar(self):
        ev = {
            "title": "Clube do Livro",
            "start": "2030-06-01T19:00:00-03:00",
            "venue": "Livraria",
            "address": "Rua 1",
            "city": "Salvador",
            "source": "Luma",
            "url": "https://luma.com/pve8emb2",
            "tags": ["comunidade"],
            "description": {"pt": "Vamos ler um romance."},
        }
        texto = importar.bloco_novo(ev, ev["url"])
        self.assertIn("### Clube do Livro", texto)
        self.assertIn("2030-06-01T19:00", texto)
        self.assertIn("Livraria · Rua 1 · Salvador", texto)
        self.assertIn("Fonte: Luma", texto)
        self.assertIn("https://luma.com/pve8emb2", texto)
        self.assertIn("comunidade", texto)
        self.assertIn("⚠️ revisar", texto)
        self.assertIn("não parece tech", texto)
        self.assertIn("cidade não é Rio", texto)
        self.assertIn("data/descartados.json", importar.RODAPE)

    def test_relatorio_tech_no_rio_sem_aviso(self):
        ev = {
            "title": "Meetup de Python",
            "start": "2030-06-02T19:00:00-03:00",
            "venue": "Casa",
            "city": "Rio de Janeiro",
            "url": "https://exemplo.org/py",
            "tags": ["python"],
            "description": {"pt": "Palestra de Python."},
        }
        self.assertNotIn("⚠️", importar.bloco_novo(ev, ev["url"]))

    def test_palavra_curta_nao_entra_no_meio(self):
        ev = {"title": "Oficial", "description": {"pt": "Diária da equipe"}, "city": "Rio de Janeiro"}
        self.assertFalse(importar.parece_tech(ev))

    def test_tags_toda_tecnologia_positivos(self):
        casos = [
            ("Meetup de biotech e saúde digital no Rio", "saude-biotech"),
            ("Fórum de energia solar e cleantech", "energia-clima"),
            ("Open finance e fintech no Centro", "fintech"),
            ("Arduino Day e robótica com IoT", "hardware-robotica"),
            ("Oficina de impressão 3D no fab lab", "maker"),
            ("Palestra de satélites e astronomia", "espaco"),
            ("Encontro de ciência e pesquisa quântica", "ciencia"),
            ("Govtech e governo digital na cidade inteligente", "govtech"),
            ("Edtech: educação digital na escola", "edtech"),
            ("Festival de audiovisual e creative tech", "economia-criativa"),
        ]
        for texto, tag in casos:
            with self.subTest(tag=tag):
                self.assertIn(tag, importar.auto_tags(texto, limit=10))

    def test_tags_toda_tecnologia_negativos(self):
        # «Espaço Colmeia» e «clima de festa» não podem virar tags de deep tech.
        self.assertNotIn("espaco", importar.auto_tags("Meetup no Espaço Colmeia", limit=10))
        self.assertNotIn("espaco", importar.auto_tags("Coworking space no Centro", limit=10))
        self.assertNotIn("energia-clima", importar.auto_tags("Rolê com clima de festa", limit=10))
        self.assertNotIn("energia-clima", importar.auto_tags("Bom clima para networking", limit=10))
        # Sem contexto aeroespacial, «espaço» sozinho não marca.
        self.assertNotIn("espaco", importar.auto_tags("Workshop no espaço da empresa", limit=10))
        # Data science e UX research não são «ciência» deep tech.
        self.assertNotIn("ciencia", importar.auto_tags("Meetup de data science no Rio", limit=10))
        self.assertNotIn("ciencia", importar.auto_tags("Ciência de dados com Python", limit=10))
        self.assertNotIn("ciencia", importar.auto_tags("UX research meetup e pesquisa de usuário", limit=10))

    def test_ciencia_impa_e_laboratorio(self):
        self.assertIn("ciencia", importar.auto_tags("Palestra de geometria no IMPA", limit=10))
        self.assertIn("ciencia", importar.auto_tags("Visita ao laboratório do CBPF", limit=10))

    def test_urls_de_idioma_sao_o_mesmo_evento(self):
        en = "https://rio.websummit.com/en"
        pt = "https://rio.websummit.com/pt-br"
        self.assertEqual(importar.chave_url(en), importar.chave_url(pt))
        self.assertEqual(
            importar.chave_url("https://rio.websummit.com/pt-br?lang=pt"),
            importar.chave_url("https://rio.websummit.com/es?lang=es"),
        )
        self.assertEqual(
            importar.chave_url("https://rio.websummit.com/?lang=en"),
            importar.chave_url("https://rio.websummit.com/?lang=pt-br"),
        )
        self.assertNotEqual(
            importar.chave_url("https://rio.websummit.com/en/startups"),
            importar.chave_url("https://rio.websummit.com/pt-br/investors"),
        )
        hoje = dt.date(2026, 1, 1)
        lista = []
        primeiro = {
            "title": "Web Summit Rio",
            "start": "2027-06-14T00:00:00-03:00",
            "venue": "Riocentro",
            "url": en,
            "format": "presencial",
            "city": "Rio de Janeiro",
        }
        segundo = {
            "title": "Web Summit Rio 2027",
            "start": "2027-06-14T00:00:00-03:00",
            "venue": "Riocentro",
            "url": pt,
            "format": "presencial",
            "city": "Rio de Janeiro",
            "description": {"pt": "Conferência no Riocentro."},
        }
        self.assertEqual(importar.merge(lista, primeiro, hoje, set()), "novo")
        self.assertEqual(importar.merge(lista, segundo, hoje, set()), "completado")
        self.assertEqual(len(lista), 1)
        self.assertEqual(lista[0]["url"], en)
        self.assertEqual(lista[0]["description"]["pt"], "Conferência no Riocentro.")

    def test_mesmo_dia_e_lugar_com_titulo_contido(self):
        hoje = dt.date(2026, 1, 1)
        lista = []
        base = {
            "title": "Web Summit Rio",
            "start": "2027-06-14T10:00:00-03:00",
            "venue": "Riocentro",
            "url": "https://exemplo.org/summit-a",
            "format": "presencial",
            "city": "Rio de Janeiro",
        }
        outro = {
            "title": "Web Summit Rio 2027",
            "start": "2027-06-14T00:00:00-03:00",
            "venue": "Riocentro",
            "url": "https://exemplo.org/summit-b",
            "format": "presencial",
            "city": "Rio de Janeiro",
        }
        self.assertEqual(importar.merge(lista, base, hoje, set()), "novo")
        self.assertEqual(importar.merge(lista, outro, hoje, set()), "completado")
        self.assertEqual(len(lista), 1)
        self.assertEqual(lista[0]["start"], "2027-06-14T10:00:00-03:00")
        self.assertEqual(lista[0]["historico"][0]["campo"], "start")
        self.assertEqual(lista[0]["historico"][0]["depois"], "2027-06-14T00:00:00-03:00")
        longe = dict(outro, url="https://exemplo.org/summit-c", venue="Pier Mauá")
        self.assertEqual(importar.merge(lista, longe, hoje, set()), "novo")
        self.assertEqual(len(lista), 2)

    def test_url_na_outra_agenda_nao_entra(self):
        hoje = dt.date(2026, 1, 1)
        outra = [{
            "title": "FRC Rio x Common Ground x More Hostels",
            "url": "https://luma.com/32yapcfk",
            "start": "2026-11-28T16:30:00-03:00",
        }]
        novo = {
            "title": "Meetup de Python",
            "start": "2026-11-28T16:30:00-03:00",
            "url": "https://www.luma.com/32yapcfk?utm_source=x",
            "format": "presencial",
            "city": "Rio de Janeiro",
            "venue": "Ipanema",
        }
        lista = []
        self.assertEqual(importar.merge(lista, novo, hoje, set(), outra=outra), "já na outra agenda")
        self.assertEqual(lista, [])
        outra_idioma = [{
            "title": "Web Summit Rio",
            "url": "https://rio.websummit.com/en",
            "start": "2027-06-14T00:00:00-03:00",
            "venue": "Riocentro",
        }]
        pt = {
            "title": "Web Summit Rio 2027",
            "start": "2027-06-14T00:00:00-03:00",
            "url": "https://rio.websummit.com/pt-br?lang=pt-br",
            "format": "presencial",
            "city": "Rio de Janeiro",
            "venue": "Riocentro",
        }
        self.assertEqual(importar.merge(lista, pt, hoje, set(), outra=outra_idioma), "já na outra agenda")
        self.assertEqual(lista, [])


class TestValidar(unittest.TestCase):
    def test_dados_do_repositorio(self):
        root = Path(__file__).resolve().parents[1]
        data = json.loads((root / "data" / "events.json").read_text(encoding="utf-8"))
        vocab = set(json.loads((root / "data" / "tags.json").read_text(encoding="utf-8"))["tags"])
        self.assertEqual(validar.check(data, vocab), [])
        summit = [e for e in data["events"] if e.get("title") == "Web Summit Rio"]
        self.assertEqual(len(summit), 1)
        self.assertEqual(summit[0]["url"], "https://rio.websummit.com/pt-br")
        self.assertEqual(summit[0]["start"][:10], "2027-06-14")
        self.assertEqual(summit[0]["venue"], "Riocentro")
        self.assertFalse(any("FRC Rio x Common Ground" in (e.get("title") or "") for e in data["events"]))
        roles = json.loads((root / "data" / "roles.json").read_text(encoding="utf-8"))["events"]
        self.assertTrue(any(e.get("title") == "FRC Rio x Common Ground x More Hostels" for e in roles))

    def test_detecta_erros(self):
        data = {"updated": "2030-01-01", "events": [
            {"id": "a", "title": "A", "start": "2030-01-02 19h", "format": "presencial",
             "cost": {"type": "gratis"}, "registration": "inscricao", "url": "http://a.org", "tags": ["inventada"]}]}
        errs = validar.check(data, {"ia"}, set())
        self.assertTrue(any("ISO" in e for e in errs))
        self.assertTrue(any("https" in e for e in errs))
        self.assertTrue(any("vocabulário" in e for e in errs))

    def test_url_chave_ignora_query_barra_e_caixa(self):
        self.assertEqual(validar.url_chave("HTTPS://LU.MA/AbC/?tk=1"), validar.url_chave("https://luma.com/abc"))
        self.assertEqual(validar.url_chave("luma.com/abc/"), "luma.com/abc")
        self.assertNotIn("?", validar.url_chave("https://luma.com/x?id=7"))
        self.assertEqual(validar.url_chave("https://www.luma.com/x"), "luma.com/x")

    def test_descartados_tem_os_seis(self):
        root = Path(__file__).resolve().parents[1]
        data = json.loads((root / "data" / "descartados.json").read_text(encoding="utf-8"))
        self.assertEqual(validar.erros_descartados(data), [])
        chaves = {validar.url_chave(i["url"]) for i in data["urls"]}
        for slug in ("kcgfyftk", "y1z3ue5c", "pve8emb2", "m6gfhf1y", "fmp2ldvv", "4cy8s78q"):
            self.assertIn(validar.url_chave("luma.com/" + slug), chaves)
        self.assertTrue(all(i["motivo"] == "fora do tema tech / não é no Rio" for i in data["urls"]))
        self.assertTrue(all(i["data"] == "2026-10-31" for i in data["urls"]))

    def test_url_em_ambos_os_arquivos(self):
        data = {"updated": "2030-01-01", "events": [{
            "id": "a", "title": "A", "start": "2030-02-01T19:00:00-03:00",
            "format": "presencial", "cost": {"type": "gratis"}, "registration": "livre",
            "url": "https://www.luma.com/4cy8s78q/?utm_source=x", "tags": ["ia"],
        }]}
        errs = validar.check(data, {"ia"})
        self.assertTrue(any("descartados" in e for e in errs))

    def test_id_de_campo_unico(self):
        doc = {"name": "N", "description": "D", "body": [
            {"type": "input", "id": "link"},
            {"type": "input", "id": "link"},
        ]}
        errs = validar.check_issue_form(doc, "t.yml")
        self.assertTrue(any("repetido" in e for e in errs))

    def test_yaml_do_repositorio(self):
        self.assertEqual(validar.check_github_yaml(), [])

    def test_descricao_sem_aspas_com_dois_pontos(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pasta = root / ".github" / "ISSUE_TEMPLATE"
            pasta.mkdir(parents=True)
            (pasta / "novo-evento.yml").write_text(
                "name: Sugerir\n"
                "description: Ex.: devs Python, iniciantes…\n"
                "body:\n"
                "  - type: input\n"
                "    id: link\n",
                encoding="utf-8",
            )
            errs = validar.check_github_yaml(root)
            self.assertTrue(errs, errs)
            self.assertTrue(any("description" in e or "YAML" in e for e in errs), errs)

    def test_checagem_yml_sem_pyyaml(self):
        """Os .yml são validados mesmo quando o import de PyYAML falha."""
        anterior = sys.modules.pop("yaml", None)
        sys.modules["yaml"] = None
        try:
            with self.assertRaises(ModuleNotFoundError):
                import importlib

                importlib.import_module("yaml")
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                wf = root / ".github" / "workflows"
                wf.mkdir(parents=True)
                (wf / "ok.yml").write_text(
                    "name: CI\n"
                    "on:\n"
                    "  push:\n"
                    "    branches: [main]\n"
                    "base: &runner ubuntu-latest\n"
                    "jobs:\n"
                    "  validar:\n"
                    "    runs-on: *runner\n"
                    "    steps:\n"
                    "      - run: echo ok\n",
                    encoding="utf-8",
                )
                (wf / "ruim.yml").write_text("name: Ruim\non: [push\n", encoding="utf-8")
                errs = validar.check_github_yaml(root)
            self.assertTrue(any("ruim.yml" in e and "YAML" in e for e in errs), errs)
            self.assertFalse(any("ok.yml" in e for e in errs), errs)
            self.assertFalse(any("pulada" in e or "PyYAML" in e for e in errs))
        finally:
            sys.modules.pop("yaml", None)
            if anterior is not None:
                sys.modules["yaml"] = anterior

    def test_ancora_e_merge(self):
        doc = validar.load_yaml(
            "base: &b\n"
            "  runs-on: ubuntu-latest\n"
            "job:\n"
            "  <<: *b\n"
            "  name: x\n"
        )
        self.assertEqual(doc["job"], {"runs-on": "ubuntu-latest", "name": "x"})
        with self.assertRaises(validar.YamlError):
            validar.load_yaml("job:\n  uses: *nao_tem\n")


def _pagina(titulo: str, formato: str, cidade: str = "Rio de Janeiro") -> str:
    modo = {
        "online": "https://schema.org/OnlineEventAttendanceMode",
        "hibrido": "https://schema.org/MixedEventAttendanceMode",
    }[formato]
    if formato == "online":
        local = '{"@type":"VirtualLocation","url":"https://meet.example/x"}'
    else:
        local = (
            '{"@type":"Place","name":"Casa","address":{"addressLocality":"' + cidade + '"}}'
        )
    return (
        '<script type="application/ld+json">'
        '{"@type":"Event","name":"' + titulo + '","startDate":"2030-11-20T19:00:00-03:00",'
        '"eventAttendanceMode":"' + modo + '","location":' + local + "}"
        "</script>"
    )


class TestSoPresencial(unittest.TestCase):
    """Online não entra. Híbrido entra. Um caso por caminho do importador."""

    def setUp(self):
        self._fetch = importar.fetch

    def tearDown(self):
        importar.fetch = self._fetch

    def _rodar(self, argv, paginas):
        def fake(url, timeout=20):
            if str(url).endswith("/robots.txt"):
                return "User-agent: *\nAllow: /\n"
            if url not in paginas:
                raise AssertionError(url)
            return paginas[url]
        importar.fetch = fake
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = importar.main(argv)
        self.assertEqual(code, 0, buf.getvalue())
        return buf.getvalue()

    def _confere(self, texto, titulo_hibrido, titulo_online):
        self.assertIn("online: 1", texto)
        self.assertIn("novo: 1", texto)
        self.assertIn("### " + titulo_hibrido, texto)
        self.assertNotIn("### " + titulo_online, texto)

    def test_merge_online_fora_e_hibrido_entra(self):
        for agenda in ("tech", "roles"):
            lista = []
            online = {
                "title": "Live", "start": "2030-11-20T19:00:00-03:00",
                "url": "https://luma.com/merge-on-" + agenda,
                "format": "online", "city": "São Paulo",
            }
            hibrido = {
                "title": "Casa", "start": "2030-11-21T19:00:00-03:00",
                "url": "https://luma.com/merge-hib-" + agenda,
                "format": "hibrido", "city": "Rio de Janeiro", "tags": ["python"],
            }
            self.assertEqual(
                importar.merge(lista, online, HOJE, set(), historico=True, agenda=agenda),
                "online",
            )
            self.assertEqual(lista, [])
            self.assertEqual(importar.merge(lista, hibrido, HOJE, set(), agenda=agenda), "novo")
            self.assertEqual(lista[0]["format"], "hibrido")

    def test_cidade_so_no_config(self):
        self.assertEqual(importar.NOME_CIDADE, validar.CIDADE["nome"])
        self.assertEqual(validar.FUSO.key, validar.CIDADE["fuso"])
        self.assertTrue(importar.cidade_rio("Niterói"))
        self.assertTrue(importar.cidade_rio("Petrópolis"))
        self.assertTrue(importar.cidade_rio("RJ"))
        self.assertFalse(importar.cidade_rio("São Paulo"))

    def test_url_tech(self):
        on, hib = "https://luma.com/so-on-url", "https://luma.com/so-hib-url"
        tit_on, tit_hib = "Live online de Python", "Meetup híbrido de Python"
        paginas = {on: _pagina(tit_on, "online", "São Paulo"), hib: _pagina(tit_hib, "hibrido")}
        texto = self._rodar(["--agenda", "tech", "--dry-run", "--url", on, "--url", hib], paginas)
        self._confere(texto, tit_hib, tit_on)

    def test_fontes_tech(self):
        on, hib = "https://luma.com/so-on-fontes", "https://luma.com/so-hib-fontes"
        tit_on, tit_hib = "Live online de Python", "Meetup híbrido de Python"
        paginas = {on: _pagina(tit_on, "online", "São Paulo"), hib: _pagina(tit_hib, "hibrido")}
        with tempfile.TemporaryDirectory() as tmp:
            fontes = Path(tmp) / "fontes.json"
            fontes.write_text(json.dumps({"fontes": [
                {"nome": "Fonte online", "tipo": "url", "url": on},
                {"nome": "Fonte híbrida", "tipo": "url", "url": hib},
            ]}), encoding="utf-8")
            texto = self._rodar(
                ["--agenda", "tech", "--dry-run", "--fontes", str(fontes)], paginas)
        self._confere(texto, tit_hib, tit_on)

    def test_whatsapp_tech(self):
        on, hib = "https://luma.com/so-on-zap", "https://luma.com/so-hib-zap"
        tit_on, tit_hib = "Live online de Python", "Meetup híbrido de Python"
        paginas = {on: _pagina(tit_on, "online", "São Paulo"), hib: _pagina(tit_hib, "hibrido")}
        with tempfile.TemporaryDirectory() as tmp:
            chat = Path(tmp) / "_chat.txt"
            chat.write_text(
                "[20.11.30, 10:00:00] ~ Fulano: " + on + "\n"
                "[20.11.30, 10:01:00] ~ Fulano: " + hib + "\n",
                encoding="utf-8",
            )
            texto = self._rodar(
                ["--agenda", "tech", "--dry-run", "--whatsapp", str(chat)], paginas)
        self._confere(texto, tit_hib, tit_on)

    def test_url_roles(self):
        on, hib = "https://luma.com/so-on-roles", "https://luma.com/so-hib-roles"
        tit_on, tit_hib = "Roda de samba online", "Roda de samba híbrida"
        paginas = {on: _pagina(tit_on, "online", "São Paulo"), hib: _pagina(tit_hib, "hibrido")}
        texto = self._rodar(["--agenda", "roles", "--dry-run", "--url", on, "--url", hib], paginas)
        self._confere(texto, tit_hib, tit_on)

    def test_fontes_roles(self):
        url = "https://exemplo.org/lista-roles"
        tit_on, tit_hib = "Roda de samba online", "Roda de samba híbrida"
        pagina = _pagina(tit_on, "online", "São Paulo") + _pagina(tit_hib, "hibrido")
        with tempfile.TemporaryDirectory() as tmp:
            fontes = Path(tmp) / "fontes.json"
            fontes.write_text(json.dumps({"fontes": [
                {"nome": "Lista", "tipo": "jsonld", "url": url},
            ]}), encoding="utf-8")
            texto = self._rodar(
                ["--agenda", "roles", "--dry-run", "--fontes", str(fontes)],
                {url: pagina},
            )
        self._confere(texto, tit_hib, tit_on)

    def test_ics_virtual_sem_lugar_nao_entra(self):
        texto = (
            "BEGIN:VCALENDAR\nBEGIN:VEVENT\n"
            "SUMMARY:PyData Global\n"
            "DTSTART:20301209T110000Z\n"
            "DESCRIPTION:A 2-day virtual event for the community.\n"
            "URL:https://exemplo.org/pydata-global\n"
            "END:VEVENT\nEND:VCALENDAR\n"
        )
        ev = importar.ics_events(texto)[0]
        self.assertEqual(ev["format"], "online")
        lista = []
        self.assertEqual(importar.merge(lista, ev, HOJE), "online")
        self.assertEqual(lista, [])
        presencial = importar.ics_events(
            "BEGIN:VCALENDAR\nBEGIN:VEVENT\n"
            "SUMMARY:Meetup\nDTSTART:20301209T110000Z\n"
            "LOCATION:Casa\nURL:https://exemplo.org/meetup\n"
            "END:VEVENT\nEND:VCALENDAR\n"
        )[0]
        self.assertEqual(presencial["format"], "presencial")

    def test_ics_telegram_online_e_virtual_no_titulo(self):
        """Meetup Rolês: Telegram / Online / encontro virtual sem LOCATION."""
        casos = [
            ("Conversação em espanhol no Telegram", "Encontro do grupo.", "online"),
            ("Sunday Free Online Guided Meditation", "Meditate together.", "online"),
            ("Encontro virtual Literatura e Criatividade", "Vamos ler.", "online"),
            ("Corrida no Maracanã", "Treino leve.", "presencial"),
            # Zoom citado na descrição não torna presencial na praia em online.
            (
                "Fale INGLÊS na PRAIA do LEME",
                "Membros podem conectar por zoom ou whatsapp com alunos na California.",
                "presencial",
            ),
        ]
        for titulo, desc, esperado in casos:
            ics = (
                "BEGIN:VCALENDAR\nBEGIN:VEVENT\n"
                f"SUMMARY:{titulo}\n"
                "DTSTART:20301209T110000Z\n"
                f"DESCRIPTION:{desc}\n"
                "URL:https://www.meetup.com/exemplo/events/1/\n"
                "END:VEVENT\nEND:VCALENDAR\n"
            )
            with self.subTest(titulo=titulo):
                ev = importar.ics_events(ics, agenda="roles")[0]
                self.assertEqual(ev["format"], esperado)
                if esperado == "online":
                    self.assertEqual(importar.merge([], ev, HOJE, agenda="roles"), "online")

    def test_rejeita_formato_online(self):
        base = {
            "id": "a", "title": "A", "start": "2030-02-01T19:00:00-03:00",
            "cost": {"type": "gratis"}, "registration": "livre",
            "url": "https://exemplo.org/so-online", "tags": ["ia"],
            "fonte": "manual", "via": "manual",
            "vistos": [{"fonte": "manual", "via": "manual", "data": "2030-01-01"}],
        }
        online = {"updated": "2030-01-01", "events": [{**base, "format": "online"}]}
        errs = validar.check(online, {"ia"}, set())
        self.assertTrue(any("format" in e for e in errs), errs)
        hibrido = {"updated": "2030-01-01", "events": [{**base, "id": "b", "format": "hibrido", "url": "https://exemplo.org/so-hib"}]}
        self.assertEqual(validar.check(hibrido, {"ia"}, set()), [])


if __name__ == "__main__":
    unittest.main()
