"""Testes da origem (vistos, historico) e da migração. Não acessa a rede."""
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import importar  # noqa: E402
import migrar_fontes  # noqa: E402
import relatorio_fontes  # noqa: E402
import saude  # noqa: E402
import validar  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HOJE = dt.date(2030, 1, 15)


def _evento(**mudancas):
    ev = {
        "title": "Python Rio",
        "start": "2030-03-10T19:00:00-03:00",
        "end": "2030-03-10T21:00:00-03:00",
        "url": "https://luma.com/abc123",
        "format": "presencial",
        "city": "Rio de Janeiro",
        "venue": "Sala A",
        "status": "confirmado",
        "source": "luma.com",
        "fonte": "luma",
        "via": "whatsapp",
    }
    ev.update(mudancas)
    return ev


def _tabela():
    return validar.TabelaFontes(
        {
            "Maravalley (Luma)": "luma:maravalley",
            "Meetup · Mundo Lingo Rio": "meetup:mundo-lingo-rio",
        },
        {"luma:maravalley", "meetup:mundo-lingo-rio"},
    )


class TestMergeOrigem(unittest.TestCase):
    def test_vistos_anexa_sem_repetir_fonte_via(self):
        lista = []
        self.assertEqual(importar.merge(lista, _evento(), HOJE, set()), "novo")
        self.assertEqual(lista[0]["vistos"], [{
            "fonte": "luma", "via": "whatsapp", "data": "2030-01-15",
        }])
        self.assertEqual(lista[0]["source"], "luma.com")
        de_novo = _evento(image="https://exemplo.org/capa.png")
        self.assertEqual(importar.merge(lista, de_novo, HOJE, set()), "completado")
        self.assertEqual(len(lista[0]["vistos"]), 1)
        self.assertEqual(lista[0]["image"], "https://exemplo.org/capa.png")
        outra = _evento(
            fonte="luma:maravalley", via="feed", source="Maravalley (Luma)",
            venue="Sala do importador",
        )
        self.assertEqual(importar.merge(lista, outra, HOJE, set()), "completado")
        pares = [(v["fonte"], v["via"]) for v in lista[0]["vistos"]]
        self.assertEqual(pares, [("luma", "whatsapp"), ("luma:maravalley", "feed")])
        self.assertEqual(lista[0]["venue"], "Sala A")
        self.assertEqual(lista[0]["fonte"], "luma")

    def test_historico_registra_e_nao_sobrescreve(self):
        lista = []
        self.assertEqual(importar.merge(lista, _evento(), HOJE, set()), "novo")
        novo = _evento(
            fonte="luma:maravalley", via="feed",
            start="2030-03-11T19:00:00-03:00",
            end="2030-03-11T22:00:00-03:00",
            venue="Sala do importador",
            status="cancelado",
        )
        self.assertEqual(importar.merge(lista, novo, HOJE, set()), "completado")
        gravado = lista[0]
        self.assertEqual(gravado["venue"], "Sala A")
        self.assertEqual(gravado["start"], "2030-03-10T19:00:00-03:00")
        self.assertEqual(gravado["end"], "2030-03-10T21:00:00-03:00")
        self.assertEqual(gravado["status"], "confirmado")
        por_campo = {h["campo"]: h for h in gravado["historico"]}
        self.assertEqual(set(por_campo), {"start", "end", "venue", "status"})
        self.assertEqual(por_campo["venue"]["antes"], "Sala A")
        self.assertEqual(por_campo["venue"]["depois"], "Sala do importador")
        self.assertEqual(por_campo["status"]["depois"], "cancelado")
        self.assertEqual(por_campo["start"]["fonte"], "luma:maravalley")
        self.assertEqual(por_campo["start"]["data"], "2030-01-15")
        self.assertEqual(importar.merge(lista, novo, HOJE, set()), "igual")
        self.assertEqual(len(gravado["historico"]), 4)
        self.assertEqual(len(gravado["vistos"]), 2)


class TestMigracao(unittest.TestCase):
    def test_luma_sem_calendario_segue_o_dia_do_whatsapp(self):
        tab = _tabela()
        datas = {"2026-11-03", "2026-11-11"}
        no_zap = {"source": "luma.com", "added": "2026-11-03", "url": "https://luma.com/abc"}
        self.assertTrue(migrar_fontes.migrar_evento(no_zap, tab, datas))
        self.assertEqual(no_zap["fonte"], "luma")
        self.assertEqual(no_zap["via"], "whatsapp")
        self.assertEqual(no_zap["vistos"], [{
            "fonte": "luma", "via": "whatsapp", "data": "2026-11-03",
        }])
        self.assertEqual(no_zap["source"], "luma.com")
        fora = {"source": "luma.com", "added": "2026-10-31", "url": "https://luma.com/xyz"}
        migrar_fontes.migrar_evento(fora, tab, datas)
        self.assertEqual(fora["fonte"], "luma")
        self.assertEqual(fora["via"], "desconhecida")
        curto = {"source": "luma", "added": "2026-10-31", "url": "https://luma.com/curto"}
        migrar_fontes.migrar_evento(curto, tab, datas)
        self.assertEqual(curto["fonte"], "luma")
        self.assertEqual(curto["via"], "desconhecida")

    def test_calendario_conhecido_e_idempotente(self):
        tab = _tabela()
        datas = {"2026-11-03"}
        mara = {"source": "Maravalley (Luma)", "added": "2026-11-03", "url": "https://luma.com/m"}
        migrar_fontes.migrar_evento(mara, tab, datas)
        self.assertEqual(mara["fonte"], "luma:maravalley")
        self.assertEqual(mara["via"], "feed")
        lingo = {"source": "Meetup · Mundo Lingo Rio", "added": "2026-11-12", "url": "https://meetup.com/e/1"}
        migrar_fontes.migrar_evento(lingo, tab, datas)
        self.assertEqual(lingo["fonte"], "meetup:mundo-lingo-rio")
        self.assertEqual(lingo["via"], "feed")
        self.assertFalse(migrar_fontes.migrar_evento(mara, tab, datas))
        self.assertEqual(len(mara["vistos"]), 1)

    def test_atalhos_e_correio(self):
        tab = _tabela()
        zap = {"source": "whatsapp-riotech", "added": "2026-10-31", "url": "https://sebraeriosummit.com.br"}
        migrar_fontes.migrar_evento(zap, tab, set())
        self.assertEqual(zap["fonte"], "whatsapp:riotech")
        self.assertEqual(zap["via"], "whatsapp")
        oficial = {"source": "site-oficial", "added": "2026-10-31", "url": "https://exemplo.org/x"}
        migrar_fontes.migrar_evento(oficial, tab, set())
        self.assertEqual(oficial["fonte"], "manual")
        self.assertEqual(oficial["via"], "manual")
        sympla = {"source": "sympla.com.br", "added": "2026-11-03", "url": "https://www.sympla.com.br/evento/x/1"}
        migrar_fontes.migrar_evento(sympla, tab, {"2026-11-03"})
        self.assertEqual(sympla["fonte"], "sympla")
        self.assertEqual(sympla["via"], "whatsapp")
        ev = {"source": "sympla.com.br", "url": "https://www.sympla.com.br/evento/x/1"}
        validar.preencher_origem(ev, "correio", "2026-11-23", tab)
        self.assertEqual(ev["fonte"], "correio:sympla")
        self.assertEqual(ev["via"], "correio")
        validar.preencher_origem(ev, "correio", "2026-11-24", tab)
        self.assertEqual(len(ev["vistos"]), 1)

    def test_datas_saem_do_assunto_e_do_ramo(self):
        datas = migrar_fontes.extrair_datas_whatsapp(
            "Importa eventos do WhatsApp (2026-11-03).\n"
            "Prepara o link para o WhatsApp\n"
            "Importa o histórico do WhatsApp, com passados e qualquer cidade.\n",
            "importador/whatsapp-2026-11-11\nmain\n",
        )
        self.assertEqual(datas, {"2026-11-03", "2026-11-11"})

    def test_descarte_ganha_fonte_e_via(self):
        item = {
            "url": "https://luma.com/kcgfyftk",
            "motivo": "fora do tema",
            "data": "2026-10-31",
        }
        self.assertTrue(migrar_fontes.migrar_descarte(item, _tabela(), {"2026-11-03"}))
        self.assertEqual(item["fonte"], "luma")
        self.assertEqual(item["via"], "desconhecida")
        self.assertFalse(migrar_fontes.migrar_descarte(item, _tabela(), {"2026-11-03"}))


class TestDadosMigrados(unittest.TestCase):
    def test_amostra_do_repositorio(self):
        events = json.loads((ROOT / "data" / "events.json").read_text(encoding="utf-8"))["events"]
        roles = json.loads((ROOT / "data" / "roles.json").read_text(encoding="utf-8"))["events"]
        por_id = {e["id"]: e for e in events}
        por_role = {e["id"]: e for e in roles}
        zap = por_id["2026-04-02-iii-ciclo-do-programa-sandbox-rio"]
        self.assertEqual(zap["source"], "luma.com")
        self.assertEqual(zap["fonte"], "luma")
        self.assertEqual(zap["via"], "whatsapp")
        self.assertEqual(zap["vistos"][0]["data"], "2026-11-03")
        solto = por_id["2026-11-17-jornada-tecnica-nokia-para-mulheres"]
        self.assertEqual(solto["fonte"], "luma")
        self.assertEqual(solto["via"], "desconhecida")
        mara = por_id["2026-11-24-sankhya-day-2026"]
        self.assertEqual(mara["fonte"], "luma:maravalley")
        self.assertEqual(mara["via"], "feed")
        grupo = por_id["2026-11-10-sebrae-rio-summit-2026"]
        self.assertEqual(grupo["fonte"], "whatsapp:riotech")
        self.assertEqual(grupo["via"], "whatsapp")
        manual = por_id["2026-12-09-inova-ia-2026"]
        self.assertEqual(manual["fonte"], "manual")
        self.assertEqual(manual["via"], "manual")
        lingo = por_role["2026-11-12-mundo-lingo-rio-botafogo"]
        self.assertEqual(lingo["fonte"], "meetup:mundo-lingo-rio")
        self.assertEqual(lingo["via"], "feed")
        tab = validar.tabela_fontes()
        self.assertEqual(tab.por_nome["Maravalley (Luma)"], "luma:maravalley")
        self.assertEqual(tab.por_nome["Meetup · Mundo Lingo Rio"], "meetup:mundo-lingo-rio")
        self.assertTrue(all(e.get("fonte") and e.get("via") and e.get("vistos") for e in events))
        self.assertTrue(all(e.get("fonte") and e.get("via") and e.get("vistos") for e in roles))


class TestRelatorio(unittest.TestCase):
    def test_contagens_de_30_dias(self):
        hoje = dt.date(2026, 11, 23)
        eventos = [
            {
                "fonte": "luma", "status": "confirmado",
                "vistos": [{"fonte": "luma", "via": "whatsapp", "data": "2026-11-20"}],
                "historico": [{
                    "campo": "venue", "antes": "A", "depois": "B",
                    "fonte": "luma:maravalley", "data": "2026-11-21",
                }],
            },
            {
                "fonte": "luma", "status": "cancelado",
                "vistos": [
                    {"fonte": "luma", "via": "whatsapp", "data": "2026-11-01"},
                    {"fonte": "luma:maravalley", "via": "feed", "data": "2026-11-02"},
                ],
            },
            {
                "fonte": "sympla", "status": "confirmado",
                "vistos": [{"fonte": "sympla", "via": "feed", "data": "2026-08-01"}],
            },
        ]
        descartes = [{
            "fonte": "luma", "via": "desconhecida", "motivo": "fora do tema",
            "data": "2026-11-10", "url": "https://luma.com/x",
        }]
        texto = relatorio_fontes.relatorio(eventos, descartes, hoje)
        bloco = texto.split("#### Últimos 90 dias")[0]
        self.assertIn("| luma | 2 | 1 | 2 | 50% | 50% | fora do tema (1) |", bloco)
        self.assertIn("| luma:maravalley | 1 | 0 | 0 | 0% | 100% | 0 |", bloco)
        self.assertNotIn("sympla", bloco)
        self.assertNotIn("| sympla |", texto)

    def test_saude_anexa_o_relatorio(self):
        corpo = saude.montar(dt.date(2026, 11, 23), 4, 8, [], [], None)
        extra = relatorio_fontes.relatorio([], [], dt.date(2026, 11, 23))
        junto = saude.anexar_fontes(corpo, extra)
        self.assertIn("## Saúde da agenda", junto)
        self.assertIn("### Fontes: contribuição e confiança", junto)
        self.assertIn("#### Últimos 30 dias", junto)
        self.assertIn(saude.LEMBRETE, junto)


if __name__ == "__main__":
    unittest.main()
