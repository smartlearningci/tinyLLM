"""Testes offline, não contactam o Pingo Doce."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

MODULE_PATH = Path(__file__).with_name('pingodoce.py')
spec = importlib.util.spec_from_file_location('pingodoce', MODULE_PATH)
pingodoce = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pingodoce)


def html_jsonld(record):
    return '<html><head><script type="application/ld+json">' + json.dumps(record, ensure_ascii=False) + '</script></head></html>'


class TestPingoDoce(unittest.TestCase):
    def test_receita_jsonld(self):
        page = html_jsonld({
            '@context': 'https://schema.org', '@type': 'Recipe',
            'name': ' Queijadas de laranja ', 'recipeIngredient': [' 2 ovos ', '200 g de açúcar'],
            'recipeInstructions': [{'@type': 'HowToStep', 'text': 'Bater os ovos.'},
                                   {'@type': 'HowToStep', 'text': 'Levar ao forno.'}],
            'prepTime': 'PT20M', 'cookTime': 'PT1H10M', 'recipeYield': '6 doses'})
        row, blocks = pingodoce.parse(page, 'recipe')
        self.assertEqual(len(blocks), 1)
        self.assertEqual(row['title'], 'Queijadas de laranja')
        self.assertEqual(row['ingredients'], ['2 ovos', '200 g de açúcar'])
        self.assertEqual(row['steps'], ['Bater os ovos.', 'Levar ao forno.'])
        self.assertEqual(row['prep_minutes'], 20)
        self.assertEqual(row['cook_minutes'], 70)

    def test_tecnica_jsonld(self):
        page = html_jsonld({'@type': 'HowTo', 'name': 'Escaldar legumes',
                            'step': [{'@type': 'HowToStep', 'text': 'Aquecer água.'}]})
        row, _ = pingodoce.parse(page, 'technique')
        self.assertEqual(row['steps'], ['Aquecer água.'])

    def test_grafo_e_tipo_ausente(self):
        page = html_jsonld({'@graph': [{'name': 'Documento sem tipo'},
                                            {'@type': ['Thing', 'Recipe'],
                                             'name': 'Bolo', 'recipeIngredient': ['2 ovos'],
                                             'recipeInstructions': 'Misturar.'}]})
        row, _ = pingodoce.parse(page, 'recipe')
        self.assertEqual(row['title'], 'Bolo')

    def test_incompleto_nao_aceite(self):
        page = html_jsonld({'@type': 'Recipe', 'name': 'Incompleta',
                            'recipeIngredient': ['1 ovo'], 'recipeInstructions': []})
        row, blocks = pingodoce.parse(page, 'recipe')
        self.assertIsNone(row)
        self.assertEqual(len(blocks), 1)

    def test_inicializacao_sem_rede(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / 'dados.sqlite'
            p = subprocess.run([sys.executable, str(MODULE_PATH), '--db', str(db)],
                               check=True, capture_output=True, text=True)
            self.assertTrue(db.exists())
            self.assertEqual(p.stdout.strip(), '[]')

    def test_recolha_requer_permissao_confirmada(self):
        with tempfile.TemporaryDirectory() as d:
            p = subprocess.run([sys.executable, str(MODULE_PATH), '--db', str(Path(d) / 'dados.sqlite'), '--collect'],
                               capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('Confirm permitted collection and use', p.stderr)

if __name__ == '__main__':
    unittest.main()