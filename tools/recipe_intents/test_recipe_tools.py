"""Run with: python -m unittest discover -s tools/recipe_intents -v"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from recipe_tools import (get_recipe_ingredients, get_ingredient_quantity,
                          get_recipe_steps, check_recipe_constraint,
                          _constraint_ingredient_from_question,
                          _quantity_ingredient_from_question,
                          parse_ingredient)


class IngredientToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "recipes.sqlite"
        with sqlite3.connect(self.db) as connection:
            connection.execute("CREATE TABLE recipes (recipe_id TEXT PRIMARY KEY, title TEXT, ingredients_raw TEXT, method_raw TEXT)")
            connection.execute("INSERT INTO recipes VALUES (?, ?, ?, ?)", (
                "recipe:1", "braised lamb shanks",
                "4.0 lamb, 1.0 tablespoon olive oil, 0.5 teaspoon paprika, 2.0 pound sweet potatoes",
                "1. heat olive oil in a skillet . brown lamb . add garlic . simmer covered for one hour.",
            ))
            connection.execute("INSERT INTO recipes VALUES (?, ?, ?, ?)", (
                "recipe:2", "butter biscuits", "2 tablespoon salted butter, 1 tablespoon unsalted butter, salt to taste",
                "mix butter . add flour . mix butter again . bake until golden.",
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

    def test_specific_quantity(self):
        result = get_ingredient_quantity(self.db, "recipe:1", "paprika")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["ingredient"]["quantity"], 0.5)
        self.assertEqual(result["ingredient"]["unit"], "teaspoon")

    def test_multiple_matches_are_ambiguous(self):
        result = get_ingredient_quantity(self.db, "recipe:2", "butter")
        self.assertEqual(result["status"], "ambiguous_ingredient")
        self.assertEqual(len(result["candidates"]), 2)

    def test_missing_ingredient_is_not_invented(self):
        result = get_ingredient_quantity(self.db, "recipe:1", "cumin")
        self.assertEqual(result["status"], "ingredient_not_found")

    def test_missing_numeric_quantity(self):
        result = get_ingredient_quantity(self.db, "recipe:2", "salt")
        self.assertEqual(result["status"], "quantity_not_specified")

    def test_question_inference_is_conservative(self):
        entries = get_recipe_ingredients(self.db, "recipe:1")["ingredients"]
        self.assertEqual(_quantity_ingredient_from_question("How much paprika should I use?", entries), ["paprika"])
        self.assertEqual(_quantity_ingredient_from_question("How much should I use?", entries), [])

    def test_steps_retain_original_source(self):
        result = get_recipe_steps(self.db, "recipe:1")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["steps"]), 4)
        self.assertTrue(result["method_raw"].startswith("1. heat olive oil"))
        self.assertEqual(result["steps"][0]["raw"], "heat olive oil in a skillet")

    def test_first_and_next_step(self):
        first = get_recipe_steps(self.db, "recipe:1", step_number=1)
        following = get_recipe_steps(self.db, "recipe:1", current_step=1)
        self.assertEqual(first["selected_step"]["position"], 1)
        self.assertEqual(following["selected_step"]["raw"], "brown lamb")

    def test_end_of_method_not_invented(self):
        result = get_recipe_steps(self.db, "recipe:1", current_step=4)
        self.assertEqual(result["status"], "no_next_step")

    def test_after_step_exact_phrase(self):
        result = get_recipe_steps(self.db, "recipe:1", after_text="brown lamb")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["selected_step"]["raw"], "add garlic")

    def test_ambiguous_action_is_not_guessed(self):
        result = get_recipe_steps(self.db, "recipe:2", after_text="mix butter")
        self.assertEqual(result["status"], "ambiguous_step")

    def test_constraint_present_is_grounded(self):
        result = check_recipe_constraint(self.db, "recipe:2", "butter")
        self.assertEqual(result["status"], "listed")
        self.assertEqual(len(result["matching_source_entries"]), 2)
        self.assertIsNone(result["safe_for_allergy"])

    def test_constraint_not_listed_is_not_certified_absent(self):
        result = check_recipe_constraint(self.db, "recipe:1", "milk")
        self.assertEqual(result["status"], "not_listed")
        self.assertEqual(result["matching_source_entries"], [])
        self.assertEqual(result["source_scope"], "explicit_ingredient_list_only")
        self.assertIsNone(result["safe_for_allergy"])

    def test_constraint_uses_whole_words(self):
        result = check_recipe_constraint(self.db, "recipe:1", "oil")
        self.assertEqual(result["status"], "listed")
        self.assertEqual(result["matching_source_entries"], ["1.0 tablespoon olive oil"])

    def test_constraint_english_question_parsing(self):
        self.assertEqual(_constraint_ingredient_from_question("Does this recipe contain milk?"), "milk")
        self.assertEqual(_constraint_ingredient_from_question("Can I make this without butter?"), "butter")
        self.assertIsNone(_constraint_ingredient_from_question("Is it allergen free?"))


if __name__ == "__main__":
    unittest.main()
