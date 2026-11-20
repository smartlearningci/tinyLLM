"""Offline contract checks; no Codex calls."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

FILE = Path(__file__).with_name('codex_generate_intents.py')
spec = importlib.util.spec_from_file_location('codex_generate_intents', FILE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ContractTests(unittest.TestCase):
    def test_distinct_questions_and_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'questions.jsonl'
            source.write_text('\n'.join(json.dumps({'question': x}) for x in
                                        ['How much sugar?', 'How much sugar?', 'What next?']),
                              encoding='utf-8')
            rows = module.samples(source, 10)
            self.assertEqual(len(rows), 2)
            self.assertNotEqual(rows[0]['id'], rows[1]['id'])

    def test_rejects_wrong_ids_and_operation(self):
        batch = [{'id': 'a', 'question': 'How much sugar?'}]
        good = {'responses': [{'id': 'a', 'intent': 'quantity', 'operation': 'get',
                               'confidence': .8, 'reason': 'amount'}]}
        self.assertEqual(module.validate(good, batch)['a']['intent'], 'quantity')
        for modified in ({'id': 'wrong'}, {'operation': 'list'}, {'confidence': 2}):
            bad = json.loads(json.dumps(good))
            bad['responses'][0].update(modified)
            with self.assertRaises(ValueError):
                module.validate(bad, batch)


if __name__ == '__main__':
    unittest.main()
