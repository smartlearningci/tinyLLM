"""Unit tests for deterministic recipe section retrieval."""
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

# Running with: python -m unittest discover -s tools/tinyslm_mvp -p 'test_*.py' -v
from tools.tinyslm_mvp.recipe_context import get_recipe_context, split_chunks


class RecipeContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "recipes.sqlite"
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                CREATE TABLE recipes (recipe_id TEXT PRIMARY KEY, title TEXT,
                  description TEXT, ingredients_raw TEXT, warnings_json TEXT);
                CREATE TABLE ingredients (recipe_id TEXT, position INTEGER, raw TEXT);
                CREATE TABLE preparation_segments (recipe_id TEXT, position INTEGER, text TEXT);
                INSERT INTO recipes VALUES ('r1', 'Bolo de iogurte',
                  'Bolo simples.', '3 ovos, 200 g açúcar, 250 g farinha', '[]');
                INSERT INTO ingredients VALUES ('r1', 1, '3 ovos');
                INSERT INTO ingredients VALUES ('r1', 2, '200 g açúcar');
                INSERT INTO ingredients VALUES ('r1', 3, '250 g farinha');
                INSERT INTO preparation_segments VALUES ('r1', 1, 'Bater os ovos com o açúcar.');
                INSERT INTO preparation_segments VALUES ('r1', 2, 'Adicionar o iogurte.');
                INSERT INTO recipes VALUES ('r2', 'Mistura', '',
                  '1 cup flour, , 2 cups milk', '["ingredient_delimiters_not_roundtrippable"]');
                INSERT INTO recipes VALUES ('r3', 'Vazia', '', '', '[]');
            """)

    def tearDown(self):
        self.temp.cleanup()

    def ctx(self, rid="r1", section="INGREDIENTS", chunk=1, max_chars=900):
        return get_recipe_context(self.path, rid, section, chunk, max_chars)

    def test_ingredient_list_is_literal_and_in_order(self):
        c=self.ctx()
        self.assertEqual(c.status,"FOUND")
        self.assertIn("2. 200 g açúcar", c.content)
        self.assertLess(c.content.index("1. 3 ovos"), c.content.index("3. 250 g farinha"))

    def test_preparation_does_not_interpret_question(self):
        c=self.ctx(section="PREPARATION")
        self.assertEqual(c.content,"SEGMENT 1: Bater os ovos com o açúcar.\nSEGMENT 2: Adicionar o iogurte.")

    def test_description_is_available(self):
        self.assertEqual(self.ctx(section="DESCRIPTION").content,"Bolo simples.")

    def test_full_includes_all_sections(self):
        c=self.ctx(section="FULL")
        for key in ("DESCRIPTION:","INGREDIENTS:","PREPARATION:","200 g açúcar"):
            self.assertIn(key,c.content)

    def test_paging_is_lossless_and_stable(self):
        full=self.ctx(section="FULL",max_chars=128)
        chunks=[self.ctx(section="FULL",chunk=i,max_chars=128).content
                for i in range(1,full.total_chunks+1)]
        self.assertGreater(full.total_chunks,1)
        self.assertEqual("".join(chunks),self.ctx(section="FULL").content)
        self.assertEqual(self.ctx(section="FULL",chunk=2,max_chars=128).content,chunks[1])

    def test_unknown_recipe_returns_not_found(self):
        self.assertEqual(self.ctx("not-a-recipe").status,"NOT_FOUND")

    def test_sql_injection_does_not_escape_recipe(self):
        self.assertEqual(self.ctx("r1' OR 1=1 --").status,"NOT_FOUND")

    def test_invalid_input_rejected(self):
        with self.assertRaises(ValueError): self.ctx(section="ALL")
        with self.assertRaises(ValueError): self.ctx(chunk=0)
        with self.assertRaises(ValueError): self.ctx(max_chars=4)

    def test_preserve_original_if_malformed_delimiters(self):
        c=self.ctx("r2")
        self.assertEqual(c.content,"1 cup flour, , 2 cups milk")
        self.assertIn("ingredient_delimiters_not_roundtrippable",c.as_text())

    def test_empty_and_out_of_range(self):
        self.assertEqual(self.ctx("r3","DESCRIPTION").status,"EMPTY")
        self.assertEqual(self.ctx(chunk=90).status,"CHUNK_NOT_FOUND")

    def test_chunker_exact_reconstruction_without_newlines(self):
        x="x"*1100+"\né"
        self.assertEqual("".join(split_chunks(x,128)),x)


if __name__ == "__main__":
    unittest.main()