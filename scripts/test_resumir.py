"""Testes do resumo. Sem rede e sem a API: o modelo é falso."""
import datetime as dt
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import resumir  # noqa: E402

HOJE = dt.date(2030, 1, 1)
CHEIA = (
    "Encontro da comunidade Python na Lapa para quem programa no Rio e quer ver agentes de IA. "
    "A noite tem uma palestra curta e uma demonstração ao vivo, e termina com tempo para conversar."
)
RESUMO = {
    "suficiente": True,
    "pt": "Encontro de Python na Lapa para quem programa, com palestra e demonstração.",
    "en": "A Python meetup in Lapa for people who code, with a talk and a live demo.",
    "es": "Encuentro de Python en Lapa para quien programa, con charla y demostración.",
}


def evento(**extra):
    base = {
        "id": "2030-06-01-python-na-lapa",
        "title": "Python na Lapa",
        "start": "2030-06-01T19:00:00-03:00",
        "end": "2030-06-01T21:00:00-03:00",
        "description": {"pt": "Encontro de Python para quem programa."},
        "descricao_completa": CHEIA,
    }
    base.update(extra)
    return base


def arquivo(pasta, nome, eventos):
    path = Path(pasta) / nome
    path.write_text(
        json.dumps({"updated": "2030-01-01", "events": eventos}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


class FalsoModelo:
    def __init__(self, item=None, entrada=11, saida=7, erro=None):
        self.item = RESUMO if item is None else item
        self.entrada = entrada
        self.saida = saida
        self.erro = erro
        self.chamadas = []

    def __call__(self, titulo, descricao):
        self.chamadas.append((titulo, descricao))
        if self.erro:
            raise self.erro
        return self.item, self.entrada, self.saida


class TestResumir(unittest.TestCase):
    def test_sem_chave_nao_erra_e_nao_abre_a_rede(self):
        def rede(*_a, **_k):
            raise AssertionError("rede")

        ambiente = os.environ.copy()
        ambiente.pop("ANTHROPIC_API_KEY", None)
        buf = io.StringIO()
        with patch.dict(os.environ, ambiente, clear=True), patch("urllib.request.urlopen", rede):
            with redirect_stdout(buf):
                codigo = resumir.main([])
        self.assertEqual(codigo, 0)
        texto = buf.getvalue()
        self.assertIn("ANTHROPIC_API_KEY ausente", texto)
        self.assertIn("tokens: entrada 0 · saída 0", texto)

    def test_so_futuro_sem_resumo_e_com_descricao_real(self):
        modelo = FalsoModelo()
        with tempfile.TemporaryDirectory() as tmp:
            tech = arquivo(tmp, "events.json", [
                evento(),
                evento(id="2020-01-01-velho", title="Velho", start="2020-01-01T19:00:00-03:00", end="2020-01-01T21:00:00-03:00"),
                evento(id="2030-07-01-ja", resumo={"pt": "Já tinha.", "en": "Already had.", "es": "Ya tenía."}),
                evento(id="2030-08-01-vazio", title="Sem texto", description={}, descricao_completa=""),
                evento(
                    id="2030-09-01-aviso",
                    title="Aviso",
                    description={"pt": "Obtenha informações atualizadas em: https://luma.com/x"},
                    descricao_completa="Get up-to-date information at: https://luma.com/x",
                ),
            ])
            roles = arquivo(tmp, "roles.json", [])
            texto = resumir.rodar(
                ["tech", "roles"], HOJE, modelo,
                {"tech": tech, "roles": roles}, gravar=True,
            )
            gravado = json.loads(tech.read_text(encoding="utf-8"))
        self.assertEqual(len(modelo.chamadas), 1)
        self.assertEqual(modelo.chamadas[0][0], "Python na Lapa")
        self.assertIn("demonstração ao vivo", modelo.chamadas[0][1])
        self.assertNotIn("Encontro de Python para quem programa.", modelo.chamadas[0][1])
        self.assertEqual(gravado["events"][0]["resumo"]["pt"], RESUMO["pt"])
        self.assertNotIn("resumo", gravado["events"][1])
        self.assertEqual(gravado["events"][2]["resumo"]["en"], "Already had.")
        self.assertNotIn("resumo", gravado["events"][3])
        self.assertNotIn("resumo", gravado["events"][4])
        self.assertIn("tokens: entrada 11 · saída 7", texto)
        self.assertIn("Tech: 1 resumos", texto)
        self.assertEqual(gravado["updated"], "2030-01-01")

    def test_cache_por_id_nao_repete(self):
        modelo = FalsoModelo()
        with tempfile.TemporaryDirectory() as tmp:
            tech = arquivo(tmp, "events.json", [evento(), evento()])
            resumir.rodar(["tech"], HOJE, modelo, {"tech": tech}, gravar=False)
            cru = json.loads(tech.read_text(encoding="utf-8"))
        self.assertEqual(len(modelo.chamadas), 1)
        self.assertNotIn("resumo", cru["events"][0])

    def test_sem_informacao_nao_grava(self):
        modelo = FalsoModelo({"suficiente": False, "pt": "", "en": "", "es": ""})
        with tempfile.TemporaryDirectory() as tmp:
            tech = arquivo(tmp, "events.json", [evento()])
            texto = resumir.rodar(["tech"], HOJE, modelo, {"tech": tech}, gravar=True)
            gravado = json.loads(tech.read_text(encoding="utf-8"))
        self.assertNotIn("resumo", gravado["events"][0])
        self.assertIn("1 sem informação", texto)

    def test_texto_longo_ou_inventado_demais_nao_entra(self):
        longo = {**RESUMO, "en": "x" * 241}
        demais = {**RESUMO, "es": "Uno. Dos. Tres."}
        for item in (longo, demais, {**RESUMO, "pt": "Organizado por Instituto 12"}):
            with self.subTest(item=item["pt"][:24]):
                self.assertIsNone(resumir.interpretar(item))

    def test_chamada_usa_urllib_tool_use_e_esquema_estrito(self):
        pedidos = []

        class Resposta:
            def read(self):
                return json.dumps({
                    "usage": {"input_tokens": 20, "output_tokens": 9},
                    "content": [{"type": "tool_use", "name": "registrar_resumo", "input": RESPOSTA_TOOL}],
                }).encode()

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        def abrir(req, timeout=60):
            pedidos.append((json.loads(req.data.decode()), dict(req.header_items())))
            return Resposta()

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            bruto, entrada, saida = resumir.chamar_modelo("Python na Lapa", CHEIA, abrir)
        self.assertEqual((entrada, saida), (20, 9))
        self.assertEqual(bruto["pt"], RESPOSTA_TOOL["pt"])
        pedido, cabecalhos = pedidos[0]
        self.assertEqual(pedido["model"], "claude-haiku-5-5")
        ferramenta = pedido["tools"][0]
        self.assertTrue(ferramenta["strict"])
        self.assertEqual(pedido["tool_choice"], {"type": "tool", "name": "registrar_resumo"})
        self.assertFalse(ferramenta["input_schema"]["additionalProperties"])
        self.assertEqual(
            ferramenta["input_schema"]["required"],
            ["suficiente", "pt", "en", "es"],
        )
        self.assertIn(CHEIA, pedido["messages"][0]["content"])
        self.assertNotIn("Casa da Lapa", pedido["messages"][0]["content"])
        self.assertEqual(cabecalhos["X-api-key"], "test-key")
        self.assertEqual(len(pedidos), 1)

    def test_falha_da_api_nao_interrompe(self):
        modelo = FalsoModelo(erro=resumir.ModeloErro("500"))
        with tempfile.TemporaryDirectory() as tmp:
            tech = arquivo(tmp, "events.json", [evento(id="a"), evento(id="b")])
            texto = resumir.rodar(["tech"], HOJE, modelo, {"tech": tech}, gravar=True)
        self.assertIn("avisos: 2 chamadas falharam", texto)
        self.assertIn("tokens: entrada 0 · saída 0", texto)


RESPOSTA_TOOL = {
    "suficiente": True,
    "pt": "Encontro de Python na Lapa para quem programa, com palestra e demonstração.",
    "en": "A Python meetup in Lapa for people who code, with a talk and a live demo.",
    "es": "Encuentro de Python en Lapa para quien programa, con charla y demostración.",
}
