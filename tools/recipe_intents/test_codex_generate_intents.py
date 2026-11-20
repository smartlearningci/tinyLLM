"""Offline contract checks; no Codex calls."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

FILE = Path(__file__).with_name('codex_generate_intents.py')
spec = importlib.util.spec_from_file_location('codex_generate_intents', FILE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ContractTests(unittest.TestCase):
    def test_compact_prompt_only_sends_questions(self):
        batch = [{'id': 'abc', 'question': 'How much salt?',
                  'recipe_id': 'private_recipe_123', 'candidate': {'intent': 'steps'}}]
        text = module.prompt(batch)
        self.assertIn('How much salt?', text)
        self.assertNotIn('private_recipe_123', text)
        self.assertNotIn('"candidate"', text)
        self.assertNotIn('"reason":"..."', text)

    def test_schema_matches_compact_labels(self):
        schema = json.loads(Path(__file__).with_name('codex_intents.schema.json').read_text())
        required = schema['properties']['responses']['items']['required']
        self.assertEqual(required, ['id', 'intent', 'operation'])

    def test_usage_from_events(self):
        events = '\n'.join(json.dumps(x) for x in [
            {'type': 'turn.completed', 'usage': {'input_tokens': 120, 'output_tokens': 5}},
            {'type': 'turn.completed', 'usage': {'input_tokens': 130, 'output_tokens': 8}},
        ])
        self.assertEqual(module.tokens_from_events(events),
                         {'input_tokens': 130, 'output_tokens': 8})

    def test_recovers_saved_agent_response(self):
        batch = [{'id': 'abc', 'question': 'What heat?'}]
        output = {'responses': [{'id': 'abc', 'intent': 'steps', 'operation': 'get',
                                 'confidence': .9, 'reason': 'heat'}]}
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / 'batches'
            directory.mkdir()
            event = {'type': 'item.completed', 'item': {'type': 'agent_message',
                     'text': json.dumps(output)}}
            (directory / 'batch_000000.events.jsonl').write_text(json.dumps(event) + '\n')
            recovered = module.recover_events(SimpleNamespace(out=Path(folder), model='test'), [batch])
            self.assertEqual(recovered, 1)
            saved = json.loads((directory / 'batch_000000.json').read_text())
            self.assertTrue(saved['items'][0]['teacher']['taxonomy_warning'])

    def test_distinct_questions_and_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'questions.jsonl'
            source.write_text('\n'.join(json.dumps({'question': x}) for x in
                                        ['How much sugar?', 'How much sugar?', 'What next?']),
                              encoding='utf-8')
            rows = module.samples(source, 10)
            self.assertEqual(len(rows), 2)
            self.assertNotEqual(rows[0]['id'], rows[1]['id'])

    def test_rejects_wrong_ids_and_confidence_but_preserves_new_operations(self):
        batch = [{'id': 'a', 'question': 'How much sugar?'}]
        good = {'responses': [{'id': 'a', 'intent': 'quantity', 'operation': 'get',
                               'confidence': .8, 'reason': 'amount'}]}
        self.assertEqual(module.validate(good, batch)['a']['intent'], 'quantity')
        changed = json.loads(json.dumps(good))
        changed['responses'][0]['operation'] = 'list'
        annotated = module.validate(changed, batch)
        self.assertTrue(annotated['a']['taxonomy_warning'])
        for modified in ({'id': 'wrong'}, {'confidence': 2}):
            bad = json.loads(json.dumps(good))
            bad['responses'][0].update(modified)
            with self.assertRaises(ValueError):
                module.validate(bad, batch)


if __name__ == '__main__':
    unittest.main()
