import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.tinyslm_mvp.normalize_audit_recipes import (
    canonical_text, normalize, parse_ingredients, parse_preparation, run,
)


class NormalizationTests(unittest.TestCase):
    def test_exact_ingredient_source_roundtrip(self):
        source = "1.0 cup sauce, hot style, 2.0 cups flour, pepperoncini"
        items, warnings = parse_ingredients(source)
        self.assertEqual(", ".join(item["raw"] for item in items), source)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["parse_status"], "needs_review")
        self.assertIn("uncertain_ingredient_comma", warnings)

    def test_preparation_keeps_original(self):
        source = "1. mix flour . stir carefully . bake until golden."
        segments, warnings = parse_preparation(source)
        self.assertEqual(" . ".join(segment["raw"] for segment in segments), source)
        self.assertEqual(len(segments), 3)
        self.assertEqual(warnings, set())

    def test_bad_source_delimiters_are_flagged_and_preserved(self):
        source = "1 teaspoon salt, , 2 cups flour"
        ingredients, warnings = parse_ingredients(source)
        self.assertIn("ingredient_delimiters_not_roundtrippable", warnings)
        self.assertNotEqual(", ".join(x["raw"] for x in ingredients), source)

    def test_canonical_format_is_short_and_source_faithful(self):
        ingredients, _ = parse_ingredients("2 cup flour, 3 eggs")
        segments, _ = parse_preparation("1. whisk . bake")
        text = canonical_text("Cake", "Simple cake", ingredients, segments)
        self.assertTrue(text.startswith("RECIPE\nTITLE: Cake\nDESCRIPTION:"))
        self.assertIn("INGREDIENTS:\n- 2 cup flour\n- 3 eggs", text)
        self.assertIn("PREPARATION:\n1. whisk\n2. bake", text)
        self.assertNotIn("{", text)

    def test_end_to_end_does_not_change_source(self):
        with tempfile.TemporaryDirectory() as temp:
            src = Path(temp) / "src.sqlite"
            out = Path(temp) / "output"
            with sqlite3.connect(src) as conn:
                conn.execute("CREATE TABLE recipes (recipe_id TEXT PRIMARY KEY, "
                             "source_id TEXT, title TEXT, original_text TEXT, "
                             "ingredients_raw TEXT, method_raw TEXT)")
                conn.execute("INSERT INTO recipes VALUES (?,?,?,?,?,?)", (
                    "r1", "s1", "Cake", "Title: Cake\n\nDescription: Example\n\nIngredients:\n",
                    "2 cup flour, 3 eggs", "1. whisk . bake"))
            report = run(src, out, historical_count=1)
            self.assertEqual(report["counts"]["recipes"], 1)
            self.assertTrue(report["all_original_fields_exact"])
            self.assertTrue((out / "recipes_normalized.jsonl.gz").exists())
            with self.assertRaises(FileExistsError):
                run(src, out, historical_count=1)


if __name__ == "__main__":
    unittest.main()
