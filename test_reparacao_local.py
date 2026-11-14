"""Testes offline das reparacoes conservadoras, sem chamadas ao modelo."""
import copy
import unittest
from unittest.mock import patch

import reparacao_local as r


class RepairTests(unittest.TestCase):
    def test_punctuation_only_unique_literal(self):
        source = "Ingredientes: tomate, água e sal. Preparação: cozer lentamente."
        self.assertEqual(r.repair_quote("Ingredientes tomate água e sal", source),
                         "Ingredientes: tomate, água e sal")

    def test_paraphrase_cannot_be_repaired(self):
        source = "Ingredientes: tomate, água e sal."
        self.assertIsNone(r.repair_quote("Ingredientes vários vegetais e sal", source))

    def test_ambiguous_phrase_cannot_be_repaired(self):
        source = "Misturar água e sal. Voltar a misturar água e sal."
        self.assertIsNone(r.repair_quote("misturar água e sal", source))

    def test_full_validation_required_for_repair(self):
        request = {"recipe": {"source_id": "r1",
                              "text": "Ingredientes: tomate, água e sal."},
                   "knowledge": []}
        raw = {"examples": [{"slot": 0, "evidence": [
            {"source_id": "r1", "quote": "Ingredientes tomate água e sal"}]}]}
        with patch.object(r.distill, "validate_response", return_value=True):
            fixed, edits = r.repair_response(raw, request)
        self.assertEqual(fixed["examples"][0]["evidence"][0]["quote"],
                         "Ingredientes: tomate, água e sal")
        self.assertEqual(len(edits), 1)
        self.assertEqual(raw["examples"][0]["evidence"][0]["quote"],
                         "Ingredientes tomate água e sal")
        with patch.object(r.distill, "validate_response",
                          side_effect=ValueError("Outra falha")):
            self.assertEqual(r.repair_response(raw, request), (None, []))

if __name__ == "__main__":
    unittest.main()
