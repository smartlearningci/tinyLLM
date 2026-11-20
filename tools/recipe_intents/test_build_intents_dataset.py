import tempfile
import json
import unittest
from pathlib import Path

from build_intents_dataset import build, classify


class IntentBuilderTests(unittest.TestCase):
    def test_abstains_instead_of_unknown(self):
        target, reason = classify('Who won the football match yesterday?')
        self.assertIsNone(target)
        self.assertEqual(reason, 'unmatched_not_unknown')

    def test_clear_questions(self):
        self.assertEqual(classify('How much paprika should I use?')[0],
                         {'intent':'quantity', 'operation':'get'})
        self.assertEqual(classify('What should I do next after boiling?')[0],
                         {'intent':'steps', 'operation':'next'})
        self.assertEqual(classify('Can I make it without butter?')[0],
                         {'intent':'constraints', 'operation':'exclude'})

    def test_multi_intent_review(self):
        self.assertIsNone(classify('Which ingredients and steps should I include?')[0])

    def test_group_disjoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source.jsonl'
            with source.open('w') as f:
                for i in range(100):
                    f.write(json.dumps({'question': f'How much paprika should I use for dish {i}?',
                                        'recipe_ids':[f'recipe:{i}']})+'\n')
            out = Path(tmp) / 'out'
            build(source, out, 60, 42)
            recipes = {}
            for split in ['train', 'validation', 'test']:
                with (out / f'{split}.jsonl').open() as stream:
                    for line in stream:
                        recipe = json.loads(line)['recipe_id']
                        self.assertNotIn(recipe, recipes)
                        recipes[recipe] = split


if __name__ == '__main__':
    unittest.main()
