"""Testes do importador e do validador. Rodar com:  python -m unittest discover -s scripts"""
import datetime as dt
import json
import sys
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
        errs = validar.check(data, {"ia"})
        self.assertTrue(any("ISO" in e for e in errs))
        self.assertTrue(any("https" in e for e in errs))
        self.assertTrue(any("vocabulário" in e for e in errs))


if __name__ == "__main__":
    unittest.main()
