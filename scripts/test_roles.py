"""Testes da agenda Rolês, sem rede. Rodar com: python -m unittest discover -s scripts"""
import datetime as dt
import unittest
from pathlib import Path

import importar
import validar

FIX = Path(__file__).parent / "fixtures"
RIO = dt.timezone(dt.timedelta(hours=-3))


class TestRoles(unittest.TestCase):
    def test_jsonld_aninhado_e_meia_noite(self):
        page = (FIX / "roles_lista.html").read_text(encoding="utf-8")
        eventos = importar.events_from_page(page, "https://exemplo.org/lista", "roles")
        self.assertEqual(len(eventos), 1)
        ev = eventos[0]
        self.assertEqual(ev["url"], "https://exemplo.org/samba")
        self.assertEqual(ev["start"], "2030-05-02T22:00:00-03:00")
        self.assertEqual(ev["end"], "2030-05-03T04:00:00-03:00")
        self.assertIn("samba-roda", ev["tags"])
        self.assertEqual(ev["categoria"], "festas")
        self.assertEqual(ev["bairro"], "Lapa")
        self.assertEqual(ev["cost"]["type"], "gratis")
        self.assertFalse(validar.termina_antes(ev))

    def test_ical_de_role(self):
        evs = importar.ics_events((FIX / "roles_calendario.ics").read_text(encoding="utf-8"), agenda="roles")
        self.assertEqual(len(evs), 1)
        # 19:00 UTC = 16:00 no Rio
        self.assertEqual(evs[0]["start"], "2030-05-06T16:00:00-03:00")
        self.assertEqual(evs[0]["end"], "2030-05-06T21:00:00-03:00")
        self.assertIn("idiomas", evs[0]["tags"])
        self.assertEqual(evs[0]["idioma"], "multi")
        self.assertEqual(evs[0]["bairro"], "Botafogo")
        self.assertEqual(evs[0]["cost"]["type"], "gratis")

    def test_dedup_prefere_pagina_oficial(self):
        lista = []
        hoje = dt.date(2030, 1, 1)
        base = {
            "title": "Mundo Lingo Rio - Botafogo",
            "start": "2030-05-06T19:00:00-03:00",
            "venue": "Bar Bukowski",
            "url": "https://www.meetup.com/mundo-lingo-rio/events/1/",
            "tags": ["idiomas"],
            "categoria": "comunidades",
            "format": "presencial",
            "city": "Rio de Janeiro",
        }
        self.assertEqual(importar.merge(lista, base, hoje, set(), agenda="roles"), "novo")
        oficial = dict(base)
        oficial["title"] = "Mundo Lingo Botafogo"
        oficial["url"] = "https://exemplo.org/oficial"
        oficial["description"] = {"pt": "Intercâmbio no Botafogo."}
        self.assertEqual(importar.merge(lista, oficial, hoje, set(), agenda="roles"), "completado")
        self.assertEqual(len(lista), 1)
        self.assertEqual(lista[0]["url"], "https://exemplo.org/oficial")
        self.assertIn("https://www.meetup.com/mundo-lingo-rio/events/1/", lista[0]["urls"])

    def test_lugar_diferente_nao_junta(self):
        a = {"title": "Roda de samba", "start": "2030-05-02T19:00:00-03:00", "venue": "Pedra do Sal"}
        b = {"title": "Roda de samba", "start": "2030-05-02T19:30:00-03:00", "venue": "Fundição Progresso"}
        self.assertFalse(importar.mesmo_role(a, b))

    def test_rrule_semanal_e_mensal(self):
        segunda = dt.date(2026, 11, 12)
        dias = importar.dias_da_regra("FREQ=WEEKLY;BYDAY=MO", segunda, segunda + dt.timedelta(days=28))
        self.assertEqual(dias, [dt.date(2026, 11, 16), dt.date(2026, 11, 23), dt.date(2026, 11, 30), dt.date(2026, 12, 7)])
        domingos = importar.dias_da_regra("FREQ=MONTHLY;BYDAY=2SU", dt.date(2026, 11, 1), dt.date(2026, 12, 1))
        self.assertEqual(domingos, [dt.date(2026, 11, 8)])
        self.assertIsNone(validar.erro_rrule("FREQ=WEEKLY;BYDAY=MO,TH"))
        self.assertIsNotNone(validar.erro_rrule("FREQ=DAILY;BYDAY=MO"))
        self.assertIsNotNone(validar.erro_rrule("FREQ=WEEKLY"))

    def test_fixo_cruza_meia_noite(self):
        fixo = {
            "id": "pedra",
            "title": "Roda",
            "rrule": "FREQ=WEEKLY;BYDAY=MO",
            "time": "19:00",
            "end_time": "00:00",
            "url": "https://exemplo.org/pedra",
            "tags": ["samba-roda"],
            "categoria": "festas",
            "format": "presencial",
            "cost": {"type": "gratis"},
            "registration": "livre",
        }
        hoje = dt.date(2026, 11, 12)
        agora = dt.datetime(2026, 11, 12, 8, 0, tzinfo=RIO)
        ocorrencias = importar.expandir_fixo(fixo, hoje, semanas=4, agora=agora)
        self.assertEqual(len(ocorrencias), 4)
        self.assertEqual(ocorrencias[0]["start"], "2026-11-16T19:00:00-03:00")
        self.assertEqual(ocorrencias[0]["end"], "2026-11-17T00:00:00-03:00")
        self.assertTrue(ocorrencias[0]["fixo"])
        self.assertFalse(validar.termina_antes(ocorrencias[0]))

    def test_fim_antes_do_inicio(self):
        self.assertTrue(validar.termina_antes({
            "start": "2030-05-02T22:00:00-03:00",
            "end": "2030-05-02T21:00:00-03:00",
        }))
        self.assertFalse(validar.termina_antes({
            "start": "2030-05-02T22:00:00-03:00",
            "end": "2030-05-03T04:00:00-03:00",
        }))

    def test_fonte_robots_tos_e_jsonld(self):
        robots = "User-agent: *\nDisallow: /privado\nAllow: /\n"
        pagina = (FIX / "roles_lista.html").read_text(encoding="utf-8")
        ok, motivo = importar.fonte_aceitavel(
            {"tipo": "jsonld", "url": "https://exemplo.org/rio"}, robots, pagina)
        self.assertTrue(ok, motivo)
        ok, motivo = importar.fonte_aceitavel(
            {"tipo": "jsonld", "url": "https://exemplo.org/privado/x"}, robots, pagina)
        self.assertFalse(ok)
        ok, motivo = importar.fonte_aceitavel(
            {"tipo": "jsonld", "url": "https://exemplo.org/rio"}, robots, "<html>sem dados</html>")
        self.assertFalse(ok)
        self.assertIn("JSON-LD", motivo)
        ok, motivo = importar.fonte_aceitavel(
            {"tipo": "url", "url": "https://exemplo.org/rio"},
            robots, pagina, termos="You may not use any robots, botnets, scrapers or spiders.")
        self.assertFalse(ok)
        self.assertIn("ToS", motivo)
        ics = (FIX / "roles_calendario.ics").read_text(encoding="utf-8")
        ok, motivo = importar.fonte_aceitavel(
            {"tipo": "ics", "url": "https://www.meetup.com/grupo/events/ical/"},
            "User-agent: *\nDisallow: /api/\n", ics,
            termos="screen scraping is forbidden")
        self.assertTrue(ok, motivo)
        ok, _motivo = importar.fonte_aceitavel(
            {"tipo": "manual", "url": "https://www.internations.org/rio", "nota": "só membros"},
            "", "")
        self.assertFalse(ok)

    def test_fixo_sem_fonte_falha(self):
        vocab, categorias = validar._vocab_roles()
        dados = {"updated": "2026-11-12", "events": [{
            "id": "x", "title": "X", "rrule": "FREQ=WEEKLY;BYDAY=MO", "time": "19:00",
            "format": "presencial", "cost": {"type": "gratis"}, "registration": "livre",
            "url": "https://exemplo.org/x", "verificado_em": "2026-11-12",
            "tags": ["samba-roda"], "categoria": "festas",
        }]}
        erros = validar.erros_fixos(dados, vocab, categorias)
        self.assertTrue(any("fonte" in e for e in erros), erros)

    def test_issue_escolhe_agenda(self):
        corpo = "### Agenda\n\nRolês\n\n### Categoria\n\nFestas\n\n### Link do evento\n\nhttps://exemplo.org/e\n"
        agenda, categoria = importar.agenda_e_categoria(corpo)
        self.assertEqual(agenda, "roles")
        self.assertEqual(categoria, "festas")
        agenda, categoria = importar.agenda_e_categoria("### Agenda\n\nTech\n")
        self.assertEqual(agenda, "tech")
        self.assertIsNone(categoria)

    def test_lista_nao_herda_a_meta_da_pagina(self):
        page = """<html><head>
        <meta property="og:description" content="Descubra os eventos mais badalados em Rio de Janeiro">
        <script type="application/ld+json">{"@context":"https://schema.org","@type":"ItemList",
         "itemListElement":[{"item":{"@type":"Event","name":"Roda de samba",
           "startDate":"2030-06-01T20:00:00-03:00","url":"https://exemplo.org/outra",
           "location":{"@type":"Place","name":"Lapa","address":"Rua da Lapa"}}}]}
        </script></head></html>"""
        ev = importar.events_from_page(page, "https://exemplo.org/lista", "roles")[0]
        self.assertEqual(ev.get("description"), {})
        self.assertIn("samba-roda", ev["tags"])

    def test_game_night_digital_nao_e_tabuleiro(self):
        tags, categoria = importar.classificar_roles(
            "Game Night: mostra de jogos e cultura digital"
        )
        self.assertIn("nerd-geek", tags)
        self.assertNotIn("jogos-tabuleiro", tags)
        self.assertEqual(categoria, "comunidades")
        tags, categoria = importar.classificar_roles("Game night de jogos de tabuleiro")
        self.assertEqual(tags, ["jogos-tabuleiro"])
        self.assertEqual(categoria, "comunidades")
        tags, categoria = importar.classificar_roles("Games, tecnologia e cultura digital. Game Night")
        self.assertEqual(tags, ["nerd-geek"])
        self.assertEqual(categoria, "comunidades")
        self.assertEqual(importar.classificar_roles("people show up to the happy hour")[0], [])


if __name__ == "__main__":
    unittest.main()
