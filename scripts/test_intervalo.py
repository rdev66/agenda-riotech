"""O dia grande da agenda é só o início. O fim do intervalo não pode ser cortado."""
import datetime as dt
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"


def fim_do_intervalo(inicio: dt.date, fim: dt.date | None) -> str:
    """Mesmo contrato de fimDoIntervalo em index.html.

    «–27» no mesmo mês. «–4/12» se o mês muda. Nunca «15–04/12».
    """
    if fim is None or fim == inicio:
        return ""
    dia = str(fim.day)
    mesmo_mes = fim.month == inicio.month and fim.year == inicio.year
    return "–" + dia + ("" if mesmo_mes else f"/{fim.month:02d}")


class TestIntervalo(unittest.TestCase):
    def test_premio_nao_vira_15_04_1(self):
        texto = fim_do_intervalo(dt.date(2026, 9, 15), dt.date(2026, 12, 4))
        self.assertEqual(texto, "–4/12")
        self.assertNotIn("15", texto)
        self.assertNotEqual(texto, "15-04/1")
        self.assertNotIn("15–04", "15" + texto)

    def test_mesmo_mes_e_mesmo_dia(self):
        self.assertEqual(fim_do_intervalo(dt.date(2026, 11, 26), dt.date(2026, 11, 27)), "–27")
        self.assertEqual(fim_do_intervalo(dt.date(2026, 6, 30), dt.date(2026, 7, 1)), "–1/07")
        self.assertEqual(fim_do_intervalo(dt.date(2026, 9, 15), dt.date(2026, 9, 15)), "")
        self.assertEqual(fim_do_intervalo(dt.date(2026, 9, 15), None), "")

    def test_fim_cabe_na_coluna(self):
        # «–31/12» são 6 caracteres. A 12px na coluna de 52px isso não corta o último dígito.
        for dia in range(1, 32):
            texto = fim_do_intervalo(dt.date(2026, 9, 15), dt.date(2026, 12, dia))
            self.assertLessEqual(len(texto), 6)
            self.assertTrue(texto.startswith("–"))
            self.assertNotIn("15–", texto)

    def test_pagina_separa_o_fim_do_dia_grande(self):
        html = INDEX.read_text(encoding="utf-8")
        self.assertIn("function fimDoIntervalo", html)
        self.assertIn('class: "until"', html)
        self.assertIn(".when .until", html)
        self.assertIn(".when .until { display: block;", html)
        self.assertIn("white-space: nowrap", html[html.index(".when .until"):html.index(".when .until") + 220])
        self.assertNotIn('dayTxt = d1 + "–"', html)
        self.assertNotIn("day range", html)
