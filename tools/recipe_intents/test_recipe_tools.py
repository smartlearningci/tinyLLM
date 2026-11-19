"""Run with: python -m unittest discover -s tools/recipe_intents -v"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from recipe_tools import get_recipe_ingredients, parse_ingredient


class IngredientToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "recipes.sqlite"
        with sqlite3.connect(self.db) as connection:
            connection.execute("CREATE TABLE recipes (recipe_id TEXT PRIMARY KEY, title TEXT, ingredients_raw TEXT)")
            connection.execute("INSERT INTO recipes VALUES (?, ?, ?)", (
                "recipe:1", "braised lamb shanks",
                "4.0 lamb, 1.0 tablespoon olive oil, 0.5 teaspoon paprika, 2.0 pound sweet potatoes",
            ))

    def test_source_preserved_and_quantities_parsed(self):
        result = get_recipe_ingredients(self.db, "recipe:1")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["ingredients"]), 4)
        self.assertEqual(result["ingredients"][0]["name"], "lamb")
        self.assertEqual(result["ingredients"][0]["quantity"], 4)
        self.assertIsNone(result["ingredients"][0]["unit"])
        self.assertEqual(result["ingredients"][1]["unit"], "tablespoon")
        self.assertEqual(result["ingredients"][2]["quantity"], 0.5)
        self.assertIn("4.0 lamb", result["ingredients_raw"])

    def test_unknown_recipe_fails_closed(self):
        result = get_recipe_ingredients(self.db, "missing")
        self.assertEqual(result["status"], "recipe_not_found")

    def test_missing_database_does_not_create_file(self):
        missing = Path(self.tmp.name) / "absent.sqlite"
        result = get_recipe_ingredients(missing, "recipe:1")
        self.assertEqual(result["status"], "database_not_found")
        self.assertFalse(missing.exists())

    def test_source_ambiguity_retained(self):
        self.assertIsNone(parse_ingredient("4.0 lamb")["unit"])
        self.assertEqual(parse_ingredient("a little salt")["raw"], "a little salt")
        self.assertEqual(parse_ingredient("1/2 teaspoon salt")["quantity"], 0.5)


if __name__ == "__main__":
    unittest.main()
