"""Testes locais e sem internet com receitas inventadas apenas para testar o codigo."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from criar_bd_pt import criar
from consultar_bd_pt import listar_receitas, obter_receita, procurar, resumo_bd
from exportar_bd_pt import exportar
from ver_bd_pt import detalhe, inicio


class TestBasePortugues(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        wiki = self.dir / "wiki.jsonl"
        reg = {"titulo": "Bolo de açúcar", "categoria": "Doces",
               "ingredientes": ["2 ovos", "200 g de açúcar"],
               "preparo": ["Misturar os ovos com o açúcar."],
               "fonte_url": "https://exemplo.invalid/bolo"}
        ataque = {"titulo": "<script>alert(1)</script>", "categoria": "Testes",
                  "ingredientes": ["1 tomate", "1 cebola"], "preparo": ["Refogar os legumes."]}
        wiki.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [reg, reg, ataque]) + "\n", encoding="utf-8")
        afro = self.dir / "afro.json"
        afro.write_text(json.dumps([
            {"_id": {"$oid": "id01"}, "nome": "Arroz branco",
             "secao": [{"nome": " Ingredientes", "conteudo": ["1 xícara de arroz", "2 xícaras de água"]},
                       {"nome": " Modo de Preparo", "conteudo": ["Junte a água e cozinhe."]}]},
            {"_id": {"$oid": "id02"}, "nome": "Sopa parcial",
             "secao": [{"nome": " Ingredientes", "conteudo": []},
                       {"nome": " Modo de Preparo", "conteudo": ["Leve ao lume."]},
                       {"nome": "Outras informações", "conteudo": ["Serve duas pessoas."]}]},
            {"_id": {"$oid": "id03"}, "nome": "Sem informação", "secao": []},
        ], ensure_ascii=False), encoding="utf-8")
        self.db = self.dir / "receitas.sqlite"
        self.rel = criar(self.db, {"wikilivros": wiki, "afrodite": afro}, Path(__file__).with_name("apoio.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_preserva_todos_e_classifica(self):
        self.assertEqual(self.rel["total"], 6)
        self.assertEqual(self.rel["estados"], {"completa": 4, "parcial": 1, "incompleta": 1})
        self.assertEqual(self.rel["duplicados_exatos"], 1)
        self.assertEqual(resumo_bd(self.db)["total"], 6)
        self.assertEqual(len(listar_receitas(self.db, origem="afrodite")), 3)
        self.assertEqual(len(listar_receitas(self.db, estado="parcial")), 1)
        self.assertEqual(len(listar_receitas(self.db, termo="açúcar")), 2)
        reg = obter_receita(self.db, "afro:id02")
        self.assertEqual(reg["estado"], "parcial")
        self.assertEqual(reg["extras"][0]["texto"], "Serve duas pessoas.")
        self.assertEqual(reg["ingredientes"], [])
        with sqlite3.connect(self.db) as con:
            raw = con.execute("SELECT original_json FROM receitas WHERE id='afro:id02'").fetchone()[0]
            self.assertIn("Modo de Preparo", raw)

    def test_consulta_factual_e_nao_inventa(self):
        w = listar_receitas(self.db, termo="bolo")[0]["id"]
        self.assertIn("200 g de açúcar", procurar(self.db, w, "ingrediente", "açúcar")["dados"])
        self.assertEqual(procurar(self.db, w, "ingrediente", "sacarina")["estado"], "SEM_DADOS")
        self.assertEqual(procurar(self.db, w, "alternativa", "açúcar", "sacarina")["estado"],
                         "SEM_ALTERNATIVA_REGISTADA")
        self.assertEqual(procurar(self.db, w, "alternativa", "açúcar", "mel")["estado"],
                         "SUGESTAO_GERAL_CONDICIONAL")
        self.assertEqual(procurar(self.db, w, "tecnica", "refogar")["estado"], "ENCONTRADO")
        self.assertEqual(procurar(self.db, w, "preparo", "grelhar")["estado"], "SEM_DADOS")
        self.assertEqual(procurar(self.db, "id_inexistente", "ingrediente", "sal")["estado"],
                         "RECEITA_DESCONHECIDA")

    def test_exportacao_e_sem_sobrescrita(self):
        destino = self.dir / "receitas.jsonl"
        n = exportar(self.db, destino)
        self.assertEqual(n, 3)
        data = [json.loads(x) for x in destino.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(all(x["estado"] == "completa" for x in data))
        self.assertTrue(all(x["duplicado_de"] is None for x in data))
        with self.assertRaises(FileExistsError):
            exportar(self.db, destino)
        with self.assertRaises(FileExistsError):
            criar(self.db, {}, Path(__file__).with_name("apoio.json"))
        self.assertEqual(resumo_bd(self.db)["total"], 6)

    def test_interface_html_sem_codigo_injetado(self):
        rendered = inicio(self.db, {"q": ["<script>"]})
        self.assertNotIn("value='<script>'", rendered)
        reg = listar_receitas(self.db, termo="script")[0]["id"]
        page = detalhe(self.db, reg)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<script>alert(1)</script>", page)


if __name__ == "__main__":
    unittest.main()