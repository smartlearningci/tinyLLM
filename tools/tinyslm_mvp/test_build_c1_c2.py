import gzip
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from build_c1_c2 import build, split_for_recipe

class DatasetTests(unittest.TestCase):
    def test_same_recipe_same_split(self):
        self.assertEqual(split_for_recipe('r1'), split_for_recipe('r1'))
        self.assertIn(split_for_recipe('r1'), ('train','validation','test'))

    def test_build_and_reject_wrong_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); db=root/'recipes.sqlite'; inp=root/'data.jsonl'; out=root/'out'
            con=sqlite3.connect(db)
            con.execute('CREATE TABLE recipes (recipe_id TEXT PRIMARY KEY,title TEXT,canonical_text TEXT,original_text TEXT,warnings_json TEXT)')
            con.execute('INSERT INTO recipes VALUES (?,?,?,?,?)',('r1','Cake','RECIPE\nTITLE: Cake\nINGREDIENTS:\n- 2 cups flour','2 cups flour','[]'))
            con.commit();con.close()
            def item(i,cap,quote):
                return {'id':i,'capability':cap,'recipe_id':'r1','conversation':[{'role':'user','content':'How much flour?'},{'role':'assistant','content':'2 cups flour.'}], 'evidence':[{'source_id':'r1','quote':quote}]}
            inp.write_text('\n'.join(json.dumps(x) for x in [item('a','C1','2 cups flour'),item('b','C2','2 cups flour'),item('c','C2','7 cups flour')])+'\n')
            r=build(inp,db,out)
            self.assertEqual(r['candidate_counts'],{'C1':1,'C2':1})
            self.assertEqual(r['review_counts']['C2/evidence_not_exact_in_source'],1)
            with gzip.open(out/'c2_candidates.jsonl.gz','rt') as f: row=json.loads(next(f))
            self.assertIn('DETAILS: Not present',row['candidate_decision_context'])
            self.assertNotIn('2 cups flour',row['candidate_decision_context'])
            self.assertEqual(row['tool_result_status'],'PENDING_REAL_TOOL_EVALUATION')
            self.assertFalse(row['training_approved'])
            with self.assertRaises(FileExistsError):build(inp,db,out)

if __name__=='__main__': unittest.main()