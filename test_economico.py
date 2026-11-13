"""Testes sem chamadas de rede nem consumo de quota."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import economico

class EconomicTests(unittest.TestCase):
    def job(self, jid, template="Instructions"):
        req = {"job_id": jid, "recipe": {"source_id":"r", "text":"recipe"}, "tasks":[]}
        return {"id":jid,"request":json.dumps(req),"prompt":template+"\nREQUEST\n"+json.dumps(req)}

    def test_batch_prompt_reuses_template(self):
        text = economico.batch_prompt([self.job("one"),self.job("two")])
        self.assertEqual(text.count("Instructions"),1)
        self.assertIn('"job_id":"one"',text)
        self.assertIn('"job_id":"two"',text)

    def test_mixed_template_rejected(self):
        with self.assertRaises(ValueError):
            economico.batch_prompt([self.job("a"),self.job("b","Other")])

    def test_missing_job_rejected(self):
        with self.assertRaises(ValueError):
            economico.validate_batch([{"job_id":"a"}],[self.job("a"),self.job("b")])

    def test_usage_last_event(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"events"
            p.write_text('{"type":"turn.completed","usage":{"input_tokens":10}}\n'
                         '{"type":"turn.completed","usage":{"input_tokens":15}}\n')
            self.assertEqual(economico.usage_from_events(p)["input_tokens"],15)

    def test_recovery_does_not_retry(self):
        with tempfile.TemporaryDirectory() as d, sqlite3.connect(":memory:") as db:
            db.row_factory=sqlite3.Row
            db.execute("CREATE TABLE jobs(id TEXT,status TEXT,attempts INTEGER,error TEXT,updated TEXT,created TEXT)")
            db.execute("INSERT INTO jobs VALUES('a','running',1,NULL,NULL,'today')")
            economico.recover(db,Path(d))
            self.assertEqual(db.execute("SELECT status FROM jobs").fetchone()[0],"error")

    def test_only_pending_selected(self):
        with sqlite3.connect(":memory:") as db:
            db.row_factory=sqlite3.Row
            db.execute("CREATE TABLE jobs(id TEXT,recipe_id TEXT,prompt TEXT,status TEXT,attempts INTEGER,created TEXT)")
            for jid,status in [("a","pending"),("b","manual"),("c","done")]:
                db.execute("INSERT INTO jobs VALUES(?,?,?,?,0,'today')",
                           (jid,"r","Instruction\nREQUEST\n{}",status))
            self.assertEqual([r["id"] for r in economico.selected_jobs(db,20,4,3)],["a"])

if __name__=="__main__":
    unittest.main()
