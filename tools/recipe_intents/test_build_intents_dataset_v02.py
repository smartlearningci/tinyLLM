"""Regression tests from the reviewed 180-question sample (row indices 1-based)."""
import csv
import unittest
from pathlib import Path

from build_intents_dataset_v02 import classify_v02

STANDALONE_CASES = [
    ('What else should I do before microwaving?', None),
    ('Why does the method tell me to stir the spices together before rubbing them on the pork?', None),
    ('Can you turn the pesto-making part into a short checklist, keeping the ingredient order?', ('steps','rewrite')),
    ('I avoid alcohol. Does this recipe contain alcohol, or is the olive oil spray alcohol-free?', ('constraints','check')),
    ('Can I replace the blueberries with raspberries without changing anything else?', ('constraints','substitute')),
    ('How much chicken broth does this casserole use?', ('quantity','get')),
    ('What should I do after taking the cakes out?', ('steps','next')),
]

# Only high-confidence reference judgments are included. `None` means abstain.
# These references were reviewed against full questions, not inferred from v01 labels.
GOLD = {
    1: ('constraints','check'),
    10: ('constraints','check'),
    21: ('constraints','check'),
    24: ('constraints','check'),
    42: ('constraints','substitute'),
    45: None,                          # heat cue replaces time; ambiguous operation
    50: ('steps','rewrite'),
    53: None,                          # egg substitute is an ingredient, not a request to substitute
    61: ('steps','rewrite'),
    63: ('constraints','check'),
    69: ('constraints','check'),
    70: ('constraints','check'),
    74: ('constraints','check'),
    79: ('constraints','check'),
    81: None,                          # ingredient list + preparation steps
    82: None,                          # why-question not yet in v02 schema
    90: ('steps','rewrite'),
    102: None,                         # `what else` is context-dependent, not missing ingredients
    109: None,
    119: None,
    129: None,                          # rewrite plus number of kneading repetitions
    133: ('quantity','get'),
    143: ('steps','explain'),
    149: ('steps','explain'),
    161: ('steps','next'),
    169: ('steps','next'),
}


class RegressionTests(unittest.TestCase):
    def test_standalone_regressions(self):
        for q, expected in STANDALONE_CASES:
            with self.subTest(question=q):
                target, _ = classify_v02(q)
                got = None if target is None else (target['intent'], target['operation'])
                self.assertEqual(got, expected)

    def test_sample(self):
        path = Path(__file__).parent / 'upload' / 'amostra_revisao_180.csv'
        if not path.exists():
            self.skipTest('Private audit CSV unavailable; use --review-csv in full audit.')
        with path.open(encoding='utf-8-sig',newline='') as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows),180)
        for index, target in GOLD.items():
            with self.subTest(row=index):
                result, reason = classify_v02(rows[index-1]['question'])
                observed = None if result is None else (result['intent'], result['operation'])
                self.assertEqual(observed, target, f'{reason}: {rows[index-1]["question"]}')


if __name__ == '__main__':
    unittest.main()
