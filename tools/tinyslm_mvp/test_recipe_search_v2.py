"""Auditable v2 regression tests. These are NOT model evaluation metrics."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from recipe_search_v2 import RecipeSearchV2,_router_probabilities

class RecipeSearchV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=Path(self.temp.name)/'recipes.sqlite'
        with sqlite3.connect(self.db) as c:
            c.execute('CREATE TABLE recipes(recipe_id TEXT PRIMARY KEY)')
            c.execute('CREATE TABLE ingredients(recipe_id TEXT, position INTEGER, raw TEXT, name TEXT, parse_status TEXT)')
            c.execute('CREATE TABLE preparation_segments(recipe_id TEXT, position INTEGER, text TEXT, parse_status TEXT)')
            c.execute("INSERT INTO recipes VALUES ('cake')")
            ing=[('cake',1,'3 eggs','eggs','heuristic'),('cake',2,'200 g sugar','sugar','heuristic'),
                 ('cake',3,'250 g flour','flour','heuristic'),('cake',4,'1 tsp cinnamon','cinnamon','heuristic')]
            st=[('cake',1,'Beat the eggs with sugar.','heuristic_segment'),
                ('cake',2,'Stir in flour and cinnamon.','heuristic_segment'),
                ('cake',3,'Bake for 35 minutes.','heuristic_segment')]
            c.executemany('INSERT INTO ingredients VALUES (?,?,?,?,?)',ing)
            c.executemany('INSERT INTO preparation_segments VALUES (?,?,?,?)',st)
        self.tool=RecipeSearchV2(self.db)
    def tearDown(self):self.tool.close();self.temp.cleanup()
    def test_when_sugar_returns_step(self):
        o=self.tool.search('cake','Em que momento adiciono o açúcar?')
        self.assertTrue(any(x['section']=='PREPARATION' and x['position']==1 for x in o['evidence']))
        e=self.tool.search('cake','When do I add sugar?')
        self.assertEqual(e['status'],'EVIDENCE_CANDIDATES')
        self.assertTrue(any(x['section']=='PREPARATION' and x['position']==1 for x in e['evidence']))
        self.assertEqual(o['status'],'EVIDENCE_CANDIDATES')
    def test_quantity_returns_original_value(self):
        r=self.tool.search('cake','How much sugar does the recipe use?')
        self.assertIn('200 g sugar',[x['text'] for x in r['evidence']])
    def test_sql_injection_cannot_escape_known_recipe(self):
        self.assertEqual(self.tool.search("cake' OR 1=1--",'sugar')['status'],'INSUFFICIENT_EVIDENCE')
    def test_unknown_entity_has_no_hallucinated_match(self):
        r=self.tool.search('cake','Is saffron included?')
        self.assertEqual(r['status'],'INSUFFICIENT_EVIDENCE')
        self.assertEqual(r['evidence'],[])
    def test_model_format_no_json(self):
        txt=self.tool.format_for_model(self.tool.search('cake','How much sugar?'))
        self.assertTrue(txt.startswith('TOOL RESULT\nSTATUS: EVIDENCE_CANDIDATES\nEVIDENCE:'))
        self.assertNotIn('{',txt)
    def test_all_ingredients_is_explicit_about_truncation(self):
        small=RecipeSearchV2(self.db,max_evidence=2)
        try:
            r=small.search('cake','List all ingredients')
            self.assertTrue(r['truncated'])
            self.assertIn('INCOMPLETE_RESULTS',small.format_for_model(r))
        finally:small.close()
    def test_real_smokehouse_excludes_sugars(self):
        # Local fixture is derived from the actual normalized recipe in the
        # 5,025-recipe source; no external LLM facts are used.
        with sqlite3.connect(self.db) as c:
            c.execute("INSERT INTO recipes VALUES ('smoke')")
            c.executemany('INSERT INTO ingredients VALUES (?,?,?,?,?)',[
                ('smoke',i,t,n,'heuristic') for i,(t,n) in enumerate([
                    ('0.2 cup paprika','paprika'),('0.5 cup brown sugar','brown sugar'),
                    ('0.5 cup white sugar','white sugar'),('1.0 tablespoon onion powder','onion powder'),
                    ('1.0 tablespoon ground rosemary','ground rosemary'),('1.0 tablespoon garlic powder','garlic powder'),
                    ('1.0 tablespoon coarse ground black pepper','coarse ground black pepper'),
                    ('1.0 tablespoon ginger powder','ginger powder'),('1.0 teaspoon cayenne pepper','cayenne pepper')],1)])
            c.execute("INSERT INTO preparation_segments VALUES ('smoke',1,'Combine all ingredients','heuristic_segment')")
        r=self.tool.search('smoke','I’m gathering only the dry seasonings, not the sugars. Which listed ingredients should I set out?')
        texts=' '.join(e['text'] for e in r['evidence']).lower()
        self.assertIn('paprika',texts)
        self.assertIn('cayenne',texts)
        self.assertNotIn('sugar',texts)
        self.assertEqual(len(r['evidence']),7)
        self.assertEqual(r['exclusions_applied'],['sugar'])
    def test_soft_router_probability_output(self):
        # Minimal portable model and deterministic multinomial softmax.
        fake={'classes':['INGREDIENTS','PREPARATION'], 'vocabulary':{'sugar':0},
              'idf':[1.0], 'coef':[[1.0],[-1.0]],'intercept':[0.0,0.0]}
        p=_router_probabilities(fake,'sugar')
        self.assertGreater(p['INGREDIENTS'],p['PREPARATION'])
        self.assertAlmostEqual(sum(p.values()),1.0,places=4)

if __name__=='__main__':unittest.main()