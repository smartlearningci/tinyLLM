import gzip
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_ptpt import (cetem_documentos, ingere_documentos, bagaco_documentos,
                        processar_fairytale, merge, iter_jsonl_gz)

TEXT = ('No jardim da escola, a Leonor encontrou uma pequena caixa de madeira. '
        'A professora pediu-lhe que chamasse os colegas. Todos se reuniram junto '
        'ao banco e conversaram sobre a melhor maneira de abrir a caixa. '
        'No final, descobriram um bilhete de agradecimento escrito pela turma.')


class TestCorpus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cetem_stream_utf8_e_8bits(self):
        f = self.p / 'c.gz'
        with gzip.open(f, 'wb') as out:
            out.write(('<ext n=1>\n<p><s>' + TEXT + '</s></p>\n</ext>\n').encode('utf-8'))
            out.write(('<ext n=2>\n<p><s>' + TEXT.replace('Leonor', 'Tiago') +
                       '</s></p>\n</ext>\n').encode('latin-1'))
        d = list(cetem_documentos(f))
        self.assertEqual(len(d), 2)
        self.assertIn('Leonor', d[0]['text'])
        self.assertIn('Tiago', d[1]['text'])
        self.assertNotIn('<ext', d[0]['text'])

    def test_bagaco_filtrado(self):
        d = [{'id': 1, 'text': TEXT, 'ptpt_score': .95, 'educational_score': 2},
             {'id': 2, 'text': TEXT, 'ptpt_score': .7, 'educational_score': 3},
             {'id': 3, 'text': TEXT, 'ptpt_score': .99, 'educational_score': 0}]
        self.assertEqual(len(list(bagaco_documentos(d))), 1)

    def test_qa_split_e_contextos_unicos(self):
        data = {split: [{'story_name': split + ' story', 'story_section': TEXT,
                         'question': 'Quem encontrou a caixa?', 'answer': 'A Leonor.'},
                        {'story_name': split + ' story', 'story_section': TEXT,
                         'question': 'Onde?', 'answer': 'No jardim.'}]
                for split in ('train', 'validation', 'test')}
        result = processar_fairytale(data, self.p)
        self.assertEqual(result['train']['perguntas'], 2)
        self.assertEqual(result['train']['contextos_unicos'], 1)
        self.assertEqual(len(list(iter_jsonl_gz(self.p / 'fairytale_contextos_test.jsonl.gz'))), 1)
        with self.assertRaises(FileExistsError):
            processar_fairytale(data, self.p)
        good = self.p / 'processed.jsonl.gz'
        ingere_documentos([{'text': TEXT}], good, 'cetempublico')
        merged = merge(self.p / 'release', [good, self.p / 'fairytale_contextos_train.jsonl.gz'])
        self.assertEqual(merged['train'] + merged['validation'], 1)  # duplicate by identical text
        with self.assertRaises(ValueError):
            merge(self.p / 'bad_release', [self.p / 'fairytale_contextos_test.jsonl.gz'])

    def test_deduplicacao_e_versoes_imutaveis(self):
        out = self.p / 'a.jsonl.gz'
        s = ingere_documentos([{'text': TEXT}, {'text': TEXT}, {'text': TEXT+' Outra nota.'}], out, 'extra')
        self.assertEqual(s['guardados'], 2)
        self.assertEqual(s['descartados'], 1)
        with self.assertRaises(FileExistsError):
            ingere_documentos([], out, 'extra')
        r = merge(self.p / 'out', [out])
        self.assertEqual(r['train'] + r['validation'], 2)
        with self.assertRaises(FileExistsError):
            merge(self.p / 'out', [out])


if __name__ == '__main__':
    unittest.main()