"""Testes locais e sem internet com receitas inventadas apenas para testar o codigo."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from criar_bd_pt import criar
from consultar_bd_pt import listar_receitas, obter_receita, procurar, resumo_bd
from exportar_bd_pt import exportar
from ver_bd_pt import detalhe, inicio, apoio


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
        self.assertIn("possível duplicado", inicio(self.db, {"q": ["Bolo de açúcar"]}))
        self.assertIn("class='warning'", apoio(self.db))

    def test_normalizacao_real_almondengas_e_alerta(self):
        """Exemplo extraído da fonte Afrodite: números duplicados, frases e carvão."""
        fonte = self.dir / "carvao.json"
        fonte.write_text(json.dumps([{
            "_id": {"$oid": "exemplo-carvao"}, "nome": "Almôndegas defumadas",
            "secao": [
                {"nome": " Ingredientes", "conteudo": ["500g de carne moída", "50g de queijo provolone ralado"]},
                {"nome": " Modo de Preparo", "conteudo": [
                    "1 - Coloque na chama do fogão um pedaço de carvão e deixe esquentando até ficar em brasa.",
                    "2 - Numa tigela, coloque 500 g de carne moída e misture. Faça bolinhas. Reserve.",
                    "3 - Numa frigideira doure as bolinhas (+/- 5 minutos).",
                    "4 - Retire o carvão em brasa. Tampe a frigideira. Desligue o fogo e sirva."
                ]}
            ]
        }], ensure_ascii=False), encoding="utf-8")
        saida = self.dir / "normalizada.sqlite"
        rel = criar(saida, {"afrodite": fonte}, Path(__file__).with_name("apoio.json"))
        self.assertEqual(rel["total"], 1)
        reg = obter_receita(saida, "afro:exemplo-carvao")
        self.assertEqual(len(reg["preparacao"]), 8)
        self.assertEqual(reg["ingredientes"][0]["texto"], "500 g de carne moída")
        self.assertEqual(reg["preparacao"][0]["texto"],
                         "Coloque na chama do fogão um pedaço de carvão e deixe esquentando até ficar em brasa.")
        self.assertTrue(any("aproximadamente 5 minutos" in x["texto"] for x in reg["preparacao"]))
        self.assertEqual(reg["alertas"][0]["codigo"], "REVER_CARVAO_EM_BRASA")
        self.assertIn("1 - Coloque", sqlite3.connect(saida).execute(
            "SELECT original_json FROM receitas WHERE id='afro:exemplo-carvao'"
        ).fetchone()[0])
        self.assertNotIn("<li>1 - Coloque", detalhe(saida, reg["id"]))
        self.assertIn("Ver texto original da fonte", detalhe(saida, reg["id"]))
        self.assertIn("rever", inicio(saida, {"q": ["Almôndegas"]}))
        destino = self.dir / "sem_alertas.jsonl"
        self.assertEqual(exportar(saida, destino, excluir_alertas=True), 0)

    def test_normalizacao_nao_altera_quantidades(self):
        from normalizar_receitas import normalizar_passo, normalizar_ingrediente, dividir_preparacao
        self.assertEqual(normalizar_ingrediente("• 1/2kg de farinha"), "1/2 kg de farinha")
        self.assertEqual(normalizar_passo("1 - Juntar 250g de açúcar."), "Juntar 250 g de açúcar.")
        self.assertEqual(normalizar_passo("2) Ferver 10 minutos."), "Ferver 10 minutos.")
        self.assertEqual(normalizar_passo("500 g de açúcar"), "500 g de açúcar")
        self.assertEqual(normalizar_passo("Maionese2 - Refogue a cebola."), "Refogue a cebola.")
        self.assertEqual(normalizar_passo("1-Misture a farinha."), "Misture a farinha.")
        self.assertEqual(normalizar_passo("1.5 kg de batatas"), "1.5 kg de batatas")
        self.assertEqual(dividir_preparacao(["1 - Misture o preparado. Reserve."]),
                         ["Misture o preparado.", "Reserve."])


    def test_receita_real_hamburdog_com_seccoes_coladas_aos_numeros(self):
        """Regressão com as secções e passos originais da receita Afrodite."""
        fonte = self.dir / "hamburdog.json"
        fonte.write_text(json.dumps([{
            "_id": {"$oid": "5744eff20ca7832b5c745abf"},
            "nome": '"Hamburdog" do Ogro Jimmy',
            "secao": [
                {"nome": " Ingredientes", "conteudo": [
                    "Berinjela- 1 fio de azeite- 2 cebolas roxas fatiadas- 1 berinjela cortada em cubos- Suco de ½ limão siciliano- 1 colher (chá) gengibre ralado- 1 colher (sopa) de manjericão picado",
                    "Maionese- 1 fio de azeite- 1 pimentão vermelho- 1 copo (tipo americano) de leite- Sal e pimenta-do-reino a gosto- 450 ml de óleo",
                    "Kafta- 1 kg de carne moída temperada com sal e pimenta-do-reino a gosto (peito ou acém)- 1 fio de azeite- 8 pães de cachorro quente",
                ]},
                {"nome": " Modo de Preparo", "conteudo": [
                    "Berinjela1 - Em uma panela com 1 fio de azeite refogue 2 cebolas roxas fatiadas. Adicione 1 berinjela cortada em cubos, suco de ½ limão siciliano, 1 colher (chá) gengibre ralado, 1 colher (sopa) de manjericão picado, misture e deixe cozinhar por 10 minutos ou até a berinjela amolecer. Retire do fogo e reserve.",
                    "Maionese2 - Coloque em uma outra panela 1 fio de azeite e refogue 1 pimentão vermelho. Retire do fogo e deixe esfriar.",
                    "3 - Transfira o pimentão refogado para um liquidificador, adicione 1 copo (tipo americano) de leite, sal e pimenta-do-reino a gosto e bata bem até ficar homogêneo. Com o liquidificador ainda ligado, adicione em fio 450 ml de óleo. Desligue o liquidificador e leve para gelar.",
                    "Kafta4 - Separe 8 porções de carne moída temperada com sal e pimenta-do-reino a gosto e modele no formato de kafta. Em seguida, em uma frigideira com 1 fio de azeite coloque as kaftas e frite até dourar. Retire da frigideira e reserve.",
                    "Montagem5 - Corte os pães de cachorro-quente ao meio, passe uma camada de maionese, coloque 1 kafta e cubra com o refogado de berinjela. Sirva em seguida.",
                ]},
                {"nome": " Outras informações", "conteudo": ["Rende 8 porções"]},
            ]
        }], ensure_ascii=False), encoding="utf-8")
        saida = self.dir / "hamburdog.sqlite"
        resumo = criar(saida, {"afrodite": fonte}, Path(__file__).with_name("apoio.json"))
        self.assertEqual(resumo["normalizacao"], "1.2")
        reg = obter_receita(saida, "afro:5744eff20ca7832b5c745abf")
        self.assertEqual(reg["estado"], "completa")
        self.assertEqual(len(reg["ingredientes"]), 14)
        self.assertEqual(len(reg["preparacao"]), 13)
        self.assertEqual(reg["ingredientes"][0], {"secao": "Berinjela", "texto": "1 fio de azeite"})
        self.assertEqual(reg["ingredientes"][6], {"secao": "Maionese", "texto": "1 fio de azeite"})
        self.assertEqual(reg["ingredientes"][11], {"secao": "Kafta", "texto": "1 kg de carne moída temperada com sal e pimenta-do-reino a gosto (peito ou acém)"})
        self.assertEqual(reg["preparacao"][0]["secao"], "Berinjela")
        self.assertEqual(reg["preparacao"][3]["secao"], "Maionese")
        self.assertEqual(reg["preparacao"][5]["secao"], "Maionese")
        self.assertEqual(reg["preparacao"][8]["secao"], "Kafta")
        self.assertEqual(reg["preparacao"][11]["secao"], "Montagem")
        self.assertTrue(all(not p["texto"].startswith(("Berinjela1", "Maionese2", "3 -", "Kafta4", "Montagem5")) for p in reg["preparacao"]))
        pagina = detalhe(saida, reg["id"])
        self.assertIn("<h3>Berinjela</h3>", pagina)
        self.assertIn("<h3>Maionese</h3>", pagina)
        self.assertIn("<ol start='4'>", pagina)
        self.assertIn("<ol start='9'>", pagina)
        self.assertIn("<ol start='12'>", pagina)
        self.assertNotIn("Berinjela1 -", pagina.split("Ver texto original da fonte")[0])
        exportado = self.dir / "hamburdog.jsonl"
        self.assertEqual(exportar(saida, exportado), 1)
        linha = json.loads(exportado.read_text(encoding="utf-8").strip())
        self.assertEqual(len(linha["preparacao"]), 13)
        self.assertIn({"tipo": "preparacao", "inicio": 4, "titulo": "Maionese"}, linha["grupos"])
        self.assertIn({"tipo": "ingredientes", "inicio": 12, "titulo": "Kafta"}, linha["grupos"])
        with sqlite3.connect(saida) as con:
            original = con.execute("SELECT original_json FROM receitas WHERE id=?", (reg['id'],)).fetchone()[0]
        self.assertIn("Berinjela1 -", original)

if __name__ == "__main__":
    unittest.main()