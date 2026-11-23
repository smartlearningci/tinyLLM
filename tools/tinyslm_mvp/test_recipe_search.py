import sqlite3
import tempfile
import unittest
from pathlib import Path
from recipe_search import RecipeSearch

class RecipeSearchTests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory()
        db=Path(self.dir.name)/'db.sqlite'
        with sqlite3.connect(db) as c:
            c.execute('CREATE TABLE recipes(recipe_id TEXT PRIMARY KEY)')
            c.execute('CREATE TABLE ingredients(recipe_id TEXT,position INTEGER,raw TEXT,name TEXT,parse_status TEXT)')
            c.execute('CREATE TABLE preparation_segments(recipe_id TEXT,position INTEGER,text TEXT,parse_status TEXT)')
            c.execute('INSERT INTO recipes VALUES (\'r1\')')
            c.executemany('INSERT INTO ingredients VALUES (?,?,?,?,?)',[
                ('r1',1,'3 eggs','eggs','heuristic'),('r1',2,'200 g sugar','sugar','heuristic')])
            c.executemany('INSERT INTO preparation_segments VALUES (?,?,?,?)',[
                ('r1',1,'Beat the eggs with sugar.','heuristic_segment'),
                ('r1',2,'Bake for 35 minutes.','heuristic_segment')])
        self.tool=RecipeSearch(db)
    def tearDown(self):
        self.tool.close()
        self.dir.cleanup()
    def test_sugar_found_with_source(self):
        x=self.tool.search('r1','When do I add sugar?')
        self.assertEqual(x['status'],'EVIDENCE_CANDIDATES')
        self.assertTrue(any('sugar' in e['text'].lower() for e in x['evidence']))
    def test_time_found(self):
        x=self.tool.search('r1','How many minutes do I bake?')
        self.assertTrue(any('35 minutes' in e['text'] for e in x['evidence']))
    def test_unknown_recipe_cannot_escape(self):
        x=self.tool.search("r1' OR 1=1 --",'sugar')
        self.assertEqual(x['status'],'INSUFFICIENT_EVIDENCE')
    def test_absent_evidence_not_invented(self):
        x=self.tool.search('r1','Is saffron in the recipe?')
        self.assertEqual(x['status'],'INSUFFICIENT_EVIDENCE')
        self.assertFalse(x['evidence'])
    def test_output_contract(self):
        x=self.tool.search('r1','sugar')
        s=self.tool.format_for_model(x)
        self.assertTrue(s.startswith('TOOL RESULT\nSTATUS: EVIDENCE_CANDIDATES\nEVIDENCE:'))
        self.assertNotIn('{',s)

if __name__=='__main__':unittest.main()