"""Testes da agenda Rolês, sem rede. Rodar com: python -m unittest discover -s scripts"""
import datetime as dt
import unittest
from pathlib import Path

import importar
import validar

FIX = Path(__file__).parent / "fixtures"
RIO = validar.FUSO


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


class TestShows(__import__("unittest").TestCase):
    def test_shows_e_festivais(self):
        import importar
        self.assertEqual(importar.classificar_roles("Show do Seal no Qualistage"), (["shows"], "shows"))
        self.assertEqual(importar.classificar_roles("Rio Blues Festival")[1], "shows")
        self.assertIn("festival-musica", importar.classificar_roles("Rio Blues Festival")[0])
        self.assertEqual(importar.classificar_roles("Festival de cinema do Rio")[1], "cinema")
        self.assertNotIn("shows", importar.classificar_roles("city tour pelo centro")[0])


class TestAgendaCultural(__import__("unittest").TestCase):
    def test_preco_zero_e_titulo(self):
        import importar
        ld = {"@type": "Event", "name": "Tom Ribeira lança o EP %26#8220;Vovóvovô’’", "startDate": "2026-12-11T18:00:00-03:00",
              "url": "https://agendaculturalriodejaneiro.com/events/tom-ribeira/", "offers": {"price": "0"},
              "location": {"name": "Galpão Ladeira das Artes"}}
        ev = importar.from_jsonld(ld, "https://agendaculturalriodejaneiro.com/shows-rio-de-janeiro-musica-concertos/", {}, agenda="roles")
        self.assertEqual(ev["title"], "Tom Ribeira lança o EP “Vovóvovô’’")
        self.assertNotEqual(ev["cost"]["type"], "gratis")
        ld["description"] = "Entrada gratuita, sem reserva."
        ev = importar.from_jsonld(ld, "https://agendaculturalriodejaneiro.com/x/", {}, agenda="roles")
        self.assertEqual(ev["cost"]["type"], "gratis")

    def test_completar_nao_poe_fim_antes_do_inicio(self):
        import importar
        base = {"start": "2026-11-29T17:00:00-03:00"}
        importar._completar_campos(base, {"end": "2026-11-29T17:00:00-03:00"})
        self.assertNotIn("end", base)
        importar._completar_campos(base, {"end": "2026-11-29T23:00:00-03:00"})
        self.assertEqual(base["end"], "2026-11-29T23:00:00-03:00")


class TestAgendaCulturalRegras(unittest.TestCase):
    """Preço, duplicata e exposição só na fonte agendacultural:*."""

    @classmethod
    def setUpClass(cls):
        page = (FIX / "agendacultural_lista.html").read_text(encoding="utf-8")
        cls.por_nome = {
            ev["title"]: ev
            for ev in importar.events_from_page(
                page, "https://agendaculturalriodejaneiro.com/shows-rio-de-janeiro-musica-concertos/", "roles"
            )
        }

    def test_preco_no_fixture(self):
        pago = self.por_nome["Seal no Qualistage"]
        self.assertEqual(pago["cost"], {"type": "pago", "text": "A partir de R$ 297,50"})
        self.assertEqual(pago["registration"], "ingresso")
        porta = self.por_nome["Noite na porta"]
        self.assertEqual(porta["cost"], {"type": "pago", "text": "R$ 80"})
        self.assertEqual(porta["registration"], "ingresso")
        faixa = self.por_nome["Turnê com meia-entrada"]
        self.assertEqual(faixa["cost"]["type"], "pago")
        self.assertEqual(
            faixa["cost"]["text"],
            "Meia-entrada entre R$ 100 e R$ 180; inteira entre R$ 200 e R$ 360",
        )
        self.assertEqual(self.por_nome["Roda na praça"]["cost"], {"type": "gratis", "text": "Grátis"})
        self.assertEqual(self.por_nome["Roda na praça"]["registration"], "livre")
        franca = self.por_nome["Abolicionistas no museu"]
        self.assertEqual(franca["cost"]["type"], "gratis")
        queen = self.por_nome["Queen e Beatles"]
        self.assertEqual(queen["cost"], {"type": "pago", "text": "A partir de R$ 51,50"})
        self.assertNotEqual(queen["cost"]["type"], "gratis")
        sem = self.por_nome["Break Free sem preço"]
        self.assertEqual(sem["cost"], {"type": "desconhecido", "text": None})

    def test_exposicao_sai_de_cinema_mostra_de_cinema_fica(self):
        franca = self.por_nome["Abolicionistas no museu"]
        self.assertEqual(franca["categoria"], "cultura")
        self.assertIn("exposicoes", franca["tags"])
        self.assertNotIn("mostras", franca["tags"])
        galeria = self.por_nome["Mostra na galeria"]
        self.assertEqual(galeria["categoria"], "cultura")
        self.assertEqual(galeria["tags"], ["exposicoes"])
        cinema = self.por_nome["Mostra de cinema no museu"]
        self.assertEqual(cinema["categoria"], "cinema")
        self.assertIn("festivais", cinema["tags"])

    def test_outra_fonte_nao_pega_preco_nem_categoria(self):
        page = """<script type="application/ld+json">{"@type":"Event","name":"Mostra no museu",
            "startDate":"2030-06-01T18:00:00-03:00","url":"https://exemplo.org/mostra",
            "description":"Mostra no museu. Ingressos: A partir de R$ 40. Entrada franca não, é pago."}
            </script>"""
        ev = importar.events_from_page(page, "https://exemplo.org/mostra", "roles")[0]
        self.assertEqual(ev["categoria"], "cinema")
        self.assertNotEqual(ev["cost"]["type"], "pago")
        ev["fonte"] = "meetup:rio"
        self.assertFalse(importar.aplicar_agendacultural(ev))
        self.assertEqual(ev["categoria"], "cinema")
        self.assertNotEqual(ev["cost"]["type"], "pago")
        ev["fonte"] = "agendacultural:gratuitos"
        self.assertTrue(importar.aplicar_agendacultural(ev))
        self.assertEqual(ev["categoria"], "cultura")
        self.assertEqual(ev["cost"], {"type": "pago", "text": "A partir de R$ 40"})
        self.assertIn("exposicoes", ev["tags"])
        self.assertNotIn("mostras", ev["tags"])

    def test_jazz_room_e_baile_viram_um(self):
        jazz_a = {
            "title": "The Jazz Room celebra Frank Sinatra e Louis Armstrong em noite intimista no Teatro Rival",
            "start": "2026-12-04",
            "venue": "Teatro Rival Petrobras",
            "url": "https://agendaculturalriodejaneiro.com/events/jazz-a",
            "format": "presencial", "fonte": "agendacultural:shows",
            "cost": {"type": "desconhecido", "text": None}, "registration": "inscricao",
            "tags": ["shows"], "categoria": "shows",
        }
        jazz_b = {
            "title": "The Jazz Room: Um Tributo a Frank Sinatra e Louis Armstrong no TEATRO RIVAL PETROBRAS",
            "start": "2026-12-04T19:30:00-03:00", "time_known": True,
            "venue": "Teatro Rival Petrobras",
            "url": "https://agendaculturalriodejaneiro.com/events/jazz-b",
            "format": "presencial", "fonte": "agendacultural:shows",
            "resumo": {"pt": "Tributo."},
            "cost": {"type": "desconhecido", "text": None}, "registration": "inscricao",
            "tags": ["shows"], "categoria": "shows",
        }
        baile_a = {
            "title": "Baile do 2A aposta em funk e pagode em locação secreta no Rio",
            "start": "2026-12-05T22:00:00-03:00", "time_known": True,
            "venue": "Locação secreta em Rio de Janeiro",
            "url": "https://agendaculturalriodejaneiro.com/events/baile-a",
            "format": "presencial", "fonte": "agendacultural:shows",
            "cost": {"type": "desconhecido", "text": None}, "registration": "inscricao",
            "tags": ["funk"], "categoria": "festas",
        }
        baile_b = {
            "title": "Baile do 2A mistura funk e pagode em festa secreta no Rio",
            "start": "2026-12-05T22:00:00-03:00", "time_known": True,
            "venue": "Locação secreta em Rio de Janeiro - RJ, Brasil",
            "url": "https://agendaculturalriodejaneiro.com/events/baile-b",
            "format": "presencial", "fonte": "agendacultural:fim-de-semana",
            "resumo": {"pt": "Festa secreta."},
            "cost": {"type": "desconhecido", "text": None}, "registration": "inscricao",
            "tags": ["funk"], "categoria": "festas",
        }
        self.assertTrue(importar.mesmo_agendacultural(jazz_a, jazz_b))
        self.assertTrue(importar.mesmo_agendacultural(baile_a, baile_b))
        juntos = importar.colapsar_agendacultural([jazz_a, jazz_b, baile_a, baile_b])
        self.assertEqual(len(juntos), 2)
        self.assertEqual(juntos[0]["url"], jazz_b["url"])
        self.assertIn(jazz_a["url"], juntos[0]["urls"])
        self.assertEqual(juntos[1]["url"], baile_b["url"])
        self.assertIn(baile_a["url"], juntos[1]["urls"])
        hoje = dt.date(2026, 11, 1)
        lista = []
        self.assertEqual(importar.merge(lista, dict(jazz_a), hoje, set(), agenda="roles"), "novo")
        self.assertEqual(importar.merge(lista, dict(jazz_b), hoje, set(), agenda="roles"), "completado")
        self.assertEqual(len(lista), 1)
        self.assertIn(jazz_b["url"], lista[0].get("urls") or [])

    def test_duplicata_exige_dia_lugar_e_tres_palavras(self):
        base = {
            "title": "Jazz Room Sinatra no Rival",
            "start": "2030-12-04T19:00:00-03:00",
            "venue": "Teatro Rival",
            "url": "https://agendaculturalriodejaneiro.com/events/um",
            "fonte": "agendacultural:shows", "format": "presencial",
        }
        pouco = dict(base, title="Jazz Room especial", url="https://agendaculturalriodejaneiro.com/events/dois")
        self.assertFalse(importar.mesmo_agendacultural(base, pouco))
        outro_dia = dict(base, start="2030-12-05T19:00:00-03:00", url="https://agendaculturalriodejaneiro.com/events/tres")
        self.assertFalse(importar.mesmo_agendacultural(base, outro_dia))
        outro_lugar = dict(base, venue="Circo Voador", url="https://agendaculturalriodejaneiro.com/events/quatro")
        self.assertFalse(importar.mesmo_agendacultural(base, outro_lugar))
        sem_lugar = dict(base, venue="", url="https://agendaculturalriodejaneiro.com/events/cinco")
        self.assertTrue(importar.mesmo_agendacultural(base, sem_lugar))
        meetup = dict(base, fonte="meetup:rio", url="https://www.meetup.com/events/1")
        copia = dict(base, url="https://www.meetup.com/events/2")
        self.assertFalse(importar.mesmo_agendacultural(meetup, copia))
        self.assertEqual(len(importar.colapsar_agendacultural([meetup, copia])), 2)

    def test_nao_descarta_presencial_nem_passado(self):
        passado = {
            "title": "Exposição antiga no museu da cidade",
            "start": "2024-12-19T10:00:00-03:00",
            "venue": "Cidade das Artes",
            "url": "https://agendaculturalriodejaneiro.com/events/antiga",
            "format": "presencial", "fonte": "agendacultural:gratuitos",
            "cost": {"type": "desconhecido", "text": None}, "registration": "inscricao",
            "tags": ["exposicoes"], "categoria": "cultura", "city": "Rio de Janeiro",
        }
        futuro = {
            "title": "Outro rolê bem diferente na lapa",
            "start": "2030-12-01T20:00:00-03:00",
            "venue": "Lapa 40 Graus",
            "url": "https://agendaculturalriodejaneiro.com/events/outro",
            "format": "presencial", "fonte": "agendacultural:shows",
            "cost": {"type": "desconhecido", "text": None}, "registration": "inscricao",
            "tags": ["shows"], "categoria": "shows", "city": "Rio de Janeiro",
        }
        self.assertEqual(len(importar.colapsar_agendacultural([dict(passado), dict(futuro)])), 2)
        hoje = dt.date(2026, 11, 25)
        self.assertEqual(importar.merge([], dict(passado), hoje, set(), agenda="roles"), "passado")
        guardados = []
        self.assertEqual(
            importar.merge(guardados, dict(passado), hoje, set(), historico=True, agenda="roles"),
            "novo",
        )
        self.assertEqual(len(guardados), 1)
        self.assertEqual(guardados[0]["format"], "presencial")
        online = dict(futuro, format="online", url="https://agendaculturalriodejaneiro.com/events/online")
        self.assertEqual(importar.merge([], online, hoje, set(), agenda="roles"), "online")
