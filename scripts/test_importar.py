"""Testes do importador e do validador. Rodar com:  python -m unittest discover -s scripts"""
import datetime as dt
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


class TestValidar(unittest.TestCase):
    def test_dados_do_repositorio(self):
        root = Path(__file__).resolve().parents[1]
        data = json.loads((root / "data" / "events.json").read_text(encoding="utf-8"))
        vocab = set(json.loads((root / "data" / "tags.json").read_text(encoding="utf-8"))["tags"])
        self.assertEqual(validar.check(data, vocab), [])

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
            "format": "online", "cost": {"type": "gratis"}, "registration": "livre",
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
        errs, aviso = validar.check_github_yaml()
        if aviso:
            print("⚠️", aviso)
            return
        self.assertEqual(errs, [])

    def test_descricao_sem_aspas_com_dois_pontos(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("sem PyYAML")
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
            errs, aviso = validar.check_github_yaml(root)
            self.assertIsNone(aviso)
            self.assertTrue(errs, errs)
            self.assertTrue(any("description" in e or "YAML" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
