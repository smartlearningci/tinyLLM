"""Fast offline checks for the 20k-teacher-to-Kaggle pipeline."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from tools.recipe_intents import build_teacher_sft_dataset as builder


class TeacherSftDatasetTest(unittest.TestCase):
    def sample_rows(self):
        rows = []
        for index in range(40):
            question = f"What do I do after step {index} in this recipe?"
            identity = hashlib.sha256(question.encode()).hexdigest()[:20]
            operation = "get" if index == 0 else "next"
            rows.append({"id": identity, "question": question,
                         "recipe_id": f"recipe-{index // 2}" if index < 32 else None,
                         "origin": "v02_train_weak_candidate",
                         "candidate": {"intent": "steps", "operation": "next"},
                         "teacher": {"id": identity, "intent": "steps",
                                     "operation": operation, "taxonomy_warning": index == 0}})
        return rows

    def write_input(self, source: Path, rows):
        content = "".join(json.dumps(row) + "\n" for row in rows)
        with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("teacher_intents_unverified.jsonl", content)

    def test_build_and_preserve_original_teacher_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, output, review = root / "teacher.zip", root / "sft.zip", root / "review.csv"
            self.write_input(source, self.sample_rows())
            with mock.patch.object(builder, "REQUIRED_COUNT", 40):
                report = builder.build(source, output, review)
            self.assertEqual(report["excluded_taxonomy_warnings"], 1)
            self.assertEqual(report["unique_teacher_question_count"], 40)
            self.assertEqual(report["unique_final_question_count"], 90)
            self.assertEqual(sum(report["splits"].values()), 89)
            self.assertEqual(report["offdomain_assistant_curated_train"], 35)
            self.assertEqual(report["offdomain_assistant_curated_test"], 15)
            self.assertTrue(review.is_file())
            with zipfile.ZipFile(output) as archive:
                parts = {part: [json.loads(line) for line in archive.read(part + ".jsonl").splitlines()]
                         for part in ("train", "validation", "test")}
                self.assertEqual(len(archive.read("review_warnings.jsonl").splitlines()), 1)
                self.assertEqual(json.loads(archive.read("sft_report.json"))["splits"], report["splits"])
            for part in ("validation", "test"):
                self.assertTrue(all(row["recipe_id"] is not None or
                                    row["source"] == "assistant_curated_offdomain"
                                    for row in parts[part]))
            grouped = {}
            for part, rows in parts.items():
                for row in rows:
                    if row["recipe_id"]:
                        self.assertEqual(grouped.setdefault(row["recipe_id"], part), part)

    def test_reject_id_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            rows = self.sample_rows()
            rows[5]["teacher"]["id"] = "bad-id"
            self.write_input(root / "teacher.zip", rows)
            with mock.patch.object(builder, "REQUIRED_COUNT", 40):
                with self.assertRaisesRegex(ValueError, "ID/pergunta"):
                    builder.build(root / "teacher.zip", root / "out.zip", root / "review.csv")

    def test_notebook_generator_outputs_valid_python_cells(self):
        from tools.recipe_intents import create_v09_refinement_notebook as notebook
        notebook.main()
        payload = json.loads(notebook.DEST.read_text(encoding="utf-8"))
        self.assertEqual(payload["nbformat"], 4)
        self.assertGreaterEqual(len(payload["cells"]), 12)
        for index, cell in enumerate(payload["cells"]):
            if cell["cell_type"] == "code":
                compile(cell["source"], f"cell_{index}", "exec")


if __name__ == "__main__":
    unittest.main()
