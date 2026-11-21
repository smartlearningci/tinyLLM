"""Offline tests: unique queue and reserved test/validation questions."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).with_name('make_production_questions.py')
spec = importlib.util.spec_from_file_location('make_production_questions', MODULE)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def write_rows(path, rows):
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')


class ProductionTests(unittest.TestCase):
    def test_excludes_previous_samples_and_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root / 'dataset'
            data.mkdir()
            write_rows(data/'train.jsonl', [
                {'question': 'What comes next?', 'target': {'intent': 'steps', 'operation': 'next'}},
                {'question': 'How much sugar?', 'target': {'intent': 'quantity', 'operation': 'get'}},
            ])
            write_rows(data/'validation.jsonl', [{'question': 'What comes next?'}])
            write_rows(data/'test.jsonl', [{'question': 'Reserved question?'}])
            write_rows(data/'review.jsonl', [
                {'question': 'Can I leave it out?', 'reason': 'possible_compound_request'},
                {'question': 'What else?', 'reason': 'contextual_what_else'},
                {'question': 'Reserved question?', 'reason': 'abstain'},
            ])
            exclude = root/'exclude.jsonl'
            write_rows(exclude, [{'question': 'How much sugar?'}])
            out = root/'queue.jsonl'
            report = builder.select(data, out, limit=2, exclusions=[exclude])
            rows = list(builder.read_jsonl(out))
            self.assertEqual(len(rows), 2)
            self.assertEqual(report['questions'], 2)
            self.assertEqual({x['question'] for x in rows},
                             {'Can I leave it out?', 'What else?'})
            self.assertTrue(all(x['label_status'] == 'question_only_teacher_pending'
                                for x in rows))


if __name__ == '__main__':
    unittest.main()
