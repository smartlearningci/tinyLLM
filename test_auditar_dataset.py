"""Testes offline do relatorio de auditoria."""
import tempfile
import unittest
from pathlib import Path

import auditar_dataset as audit


class DatasetAuditTests(unittest.TestCase):
    def sample(self, persona, cap, i):
        request = {
            "recipe": {"source_id": "r", "text": "Ingredients: onion, salt. Method: cook onions."},
            "knowledge": []
        }
        example = {
            "supported": True, "capability": cap, "evidence_type": "E0" if cap == "C7" else "E1",
            "messages": [{"role": "user", "content": "What is in this recipe?"},
                         {"role": "assistant", "content": "It has onion and salt."}],
            "evidence": [{"source_id": "r", "quote": "onion, salt"}],
            "evidence_note": "From source"
        }
        if cap == "C6":
            example["messages"] += [
                {"role": "user", "content": "What is the first ingredient?"},
                {"role": "assistant", "content": "The first is onion."}
            ]
        return {"id": str(i), "job_id": str(i), "recipe_id": "r",
                "persona": persona, "capability": cap, "status": "auto_valid",
                "recipe_title": "Onion", "example": example,
                "request": request, "flags": audit.audit_example(example, request)}

    def test_stratified_sample_covers_all_35_cells(self):
        rows = [self.sample(p, c, i * 2 + j)
                for i, (p, c) in enumerate((p, c) for p in audit.PERSONAS for c in audit.CAPS)
                for j in range(3)]
        selected = audit.choose_sample(rows, 2, 42)
        self.assertEqual(len(selected), 70)
        from collections import Counter
        self.assertTrue(all(n == 2 for n in Counter(
            (row["persona"], row["capability"]) for row in selected).values()))
        self.assertEqual(selected, audit.choose_sample(rows, 2, 42))

    def test_quote_and_role_issues_flagged(self):
        row = self.sample("P1", "C1", 1)
        ex = row["example"]
        ex["evidence"][0]["quote"] = "invented passage"
        ex["messages"].append({"role": "assistant", "content": "Unexpected turn"})
        flags = audit.audit_example(ex, row["request"])
        self.assertIn("quote_not_literal", flags)
        self.assertIn("roles_or_turns", flags)

    def test_report_writes_three_files(self):
        row = self.sample("P1", "C1", 1)
        with tempfile.TemporaryDirectory() as d:
            result = audit.make_report([row], [row], Path(d))
            self.assertEqual(result["total_examples"], 1)
            self.assertTrue((Path(d) / "resumo.json").exists())
            self.assertTrue((Path(d) / "amostra.jsonl").exists())
            self.assertTrue((Path(d) / "amostra_para_revisao.md").exists())


if __name__ == "__main__":
    unittest.main()
