"""Testes do relatório de saúde. Não acessa a rede."""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import saude  # noqa: E402


class TestSaude(unittest.TestCase):
    def test_contar(self):
        hoje = dt.date(2026, 10, 31)
        events = [
            {"start": "2026-11-01T10:00:00-03:00"},
            {"start": "2026-11-20T10:00:00-03:00"},
            {"start": "2026-10-01T10:00:00-03:00"},
        ]
        self.assertEqual(saude.contar(events, hoje), (1, 2))

    def test_ics_conta_e_data(self):
        texto = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART:20261104T220000Z
SUMMARY:A
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20260801
SUMMARY:B
END:VEVENT
END:VCALENDAR
"""
        n, ultima = saude.analisar_ics(texto)
        self.assertEqual(n, 2)
        self.assertEqual(ultima, dt.date(2026, 11, 4))

    def test_fonte_parada(self):
        hoje = dt.date(2026, 10, 31)
        self.assertTrue(saude.fonte_preocupa(True, 200, 0, None, hoje))
        self.assertFalse(saude.fonte_preocupa(False, 500, 0, None, hoje))
        self.assertTrue(saude.fonte_preocupa(True, None, 0, None, hoje))
        self.assertTrue(saude.fonte_preocupa(True, 200, 3, dt.date(2026, 8, 1), hoje))
        self.assertFalse(saude.fonte_preocupa(True, 200, 3, dt.date(2026, 10, 1), hoje))

    def test_pr_velho(self):
        agora = dt.datetime(2026, 10, 31, tzinfo=dt.timezone.utc)
        self.assertTrue(saude.pr_velho("2026-10-01T00:00:00Z", agora))
        self.assertFalse(saude.pr_velho("2026-10-30T00:00:00Z", agora))
        self.assertFalse(saude.pr_velho("2026-10-24T00:00:00Z", agora))

    def test_lembrete_e_aviso_de_14_dias(self):
        texto = saude.montar(dt.date(2026, 10, 31), 1, 5, [], [], None)
        self.assertIn("Próximos 14 dias: 1 ⚠️", texto)
        self.assertIn(saude.LEMBRETE, texto)


if __name__ == "__main__":
    unittest.main()
