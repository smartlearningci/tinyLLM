"""Testes sem chamadas de rede nem consumo de quota."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
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

    def test_batch_prompt_overrides_singular_output_format(self):
        template = ("Return only the requested JSON object.\n"
                    "Exact response format (no Markdown wrapper):\n{}")
        result = economico.batch_prompt([self.job("one", template), self.job("two", template)])
        self.assertIn("Return only the requested JSON batch object.", result)
        self.assertIn("Format of EACH item inside responses", result)
        self.assertIn("exactly as many items as REQUESTS", result)

    def test_mixed_template_rejected(self):
        with self.assertRaises(ValueError):
            economico.batch_prompt([self.job("a"),self.job("b","Other")])

    def test_missing_job_rejected(self):
        with self.assertRaises(ValueError):
            economico.validate_batch([{"job_id":"a"}],[self.job("a"),self.job("b")])

    def test_partial_batch_preserves_three_valid_jobs(self):
        jobs = [self.job(jid) for jid in ("good1", "good2", "good3", "bad")]
        items = [{"job_id": jid} for jid in ("good1", "good2", "good3", "bad")]
        with sqlite3.connect(":memory:") as db:
            db.row_factory = sqlite3.Row
            db.execute("CREATE TABLE jobs(id TEXT,status TEXT,error TEXT,updated TEXT)")
            for job in jobs:
                db.execute("INSERT INTO jobs VALUES(?,'running',NULL,NULL)", (job["id"],))

            def validate(item, request):
                if item["job_id"] == "bad":
                    raise ValueError("Ordem de mensagens inválida.")

            def store(database, job, item, provider, model, usage):
                database.execute("UPDATE jobs SET status='done' WHERE id=?", (job["id"],))
                database.commit()
                return {"added": 6, "duplicate": 0, "unsupported": 0}

            with patch.object(economico.distill, "validate_response", side_effect=validate):
                with patch.object(economico.distill, "store_response", side_effect=store):
                    counts = economico.save_batch(db, jobs, items, "gpt-6-luna",
                                                  {"input_tokens": 25000}, 15.0)
            self.assertEqual(counts["added"], 18)
            self.assertEqual(counts["completed_jobs"], 3)
            self.assertEqual([x["job_id"] for x in counts["failed_jobs"]], ["bad"])
            states = dict(db.execute("SELECT id,status FROM jobs"))
            self.assertEqual(states["good1"], "done")
            self.assertEqual(states["good2"], "done")
            self.assertEqual(states["good3"], "done")
            self.assertEqual(states["bad"], "error")

    def test_missing_response_preserves_other_jobs(self):
        jobs = [self.job(jid) for jid in ("one", "two", "three", "four")]
        items = [{"job_id": "one"}, {"job_id": "two"}]
        with sqlite3.connect(":memory:") as db:
            db.row_factory = sqlite3.Row
            db.execute("CREATE TABLE jobs(id TEXT,status TEXT,error TEXT,updated TEXT)")
            for job in jobs:
                db.execute("INSERT INTO jobs VALUES(?,'running',NULL,NULL)", (job["id"],))
            def store(database, job, item, provider, model, usage):
                database.execute("UPDATE jobs SET status='done' WHERE id=?", (job["id"],))
                database.commit()
                return {"added": 6, "duplicate": 0, "unsupported": 0}
            with patch.object(economico.distill, "validate_response"):
                with patch.object(economico.distill, "store_response", side_effect=store):
                    result = economico.save_batch(db, jobs, items, "gpt-6-luna",
                                                  {"input_tokens": 12000}, 10.0)
            self.assertEqual(result["completed_jobs"], 2)
            self.assertEqual(result["added"], 12)
            self.assertEqual(len(result["failed_jobs"]), 2)
            self.assertEqual(dict(db.execute("SELECT id,status FROM jobs")),
                             {"one": "done", "two": "done", "three": "error", "four": "error"})

    def test_production_run_continues_and_stops_at_three_bad_batches(self):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            db = economico.distill.open_db(work)
            try:
                for i in range(12):
                    jid = f"job{i:02d}"
                    req = {"job_id": jid, "recipe": {"source_id": "r", "text": "recipe"},
                           "tasks": [], "knowledge": []}
                    db.execute(
                        "INSERT INTO jobs(id,recipe_id,prompt,request,status,attempts,created) "
                        "VALUES(?,?,?,?,?,0,?)",
                        (jid, "r", "Instruction\\nREQUEST\\n" + json.dumps(req),
                         json.dumps(req), "pending", jid),
                    )
                db.commit()
                calls = []

                def fake_subprocess(cmd, **kwargs):
                    if cmd[1:3] == ["login", "status"]:
                        return argparse.Namespace(returncode=0, stdout="Logged in using ChatGPT", stderr="")
                    if cmd[1:3] == ["exec", "--help"]:
                        return argparse.Namespace(returncode=0, stdout="--output-schema --ephemeral", stderr="")
                    calls.append(len(calls) + 1)
                    requests = json.loads(kwargs["input"].split("\\nREQUESTS\\n")[-1])
                    items = ([{"job_id": req["job_id"]} for req in requests]
                             if len(calls) == 2 else [])
                    Path(cmd[cmd.index("-o") + 1]).write_text(
                        json.dumps({"responses": items}), encoding="utf-8")
                    kwargs["stdout"].write(
                        '{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":50}}\\n')
                    return argparse.Namespace(returncode=0)

                def fake_store(database, job, item, provider, model, usage=None):
                    database.execute("UPDATE jobs SET status='done' WHERE id=?", (job["id"],))
                    database.commit()
                    return {"added": 6, "duplicate": 0, "unsupported": 0}

                args = argparse.Namespace(codex_bin="codex", model="gpt-6-luna",
                                          reasoning_effort="low", limit=12,
                                          batch_size=2, timeout=10,
                                          max_consecutive_failures=3)
                patches = [
                    patch.dict("os.environ", {}, clear=True),
                    patch.object(economico.shutil, "which", return_value="/test/codex"),
                    patch.object(economico.subprocess, "run", side_effect=fake_subprocess),
                    patch.object(economico.distill, "validate_response"),
                    patch.object(economico.distill, "store_response", side_effect=fake_store),
                ]
                with contextlib.ExitStack() as stack:
                    for mocker in patches:
                        stack.enter_context(mocker)
                    output = io.StringIO()
                    stack.enter_context(contextlib.redirect_stdout(output))
                    economico.run(args, {"max_attempts": 3, "timeout_seconds": 60}, db, work)
                self.assertEqual(len(calls), 5)
                self.assertEqual(dict(db.execute(
                    "SELECT status,COUNT(*) FROM jobs GROUP BY status")),
                    {"done": 2, "error": 8, "pending": 2})
                self.assertIn("limite de falhas consecutivas", output.getvalue())
                self.assertIn("12 conversas novas", output.getvalue())
            finally:
                db.close()

    def test_failure_streak_stops_only_after_three_consecutive_bad_batches(self):
        streak = 0
        for failures in ([{"job_id": "a"}], [], [{"job_id": "b"}],
                         [{"job_id": "c"}], [{"job_id": "d"}]):
            streak = economico.update_failure_streak(streak, failures)
        self.assertEqual(streak, 3)
        self.assertEqual(economico.update_failure_streak(streak, []), 0)

    def test_run_summary_tracks_failed_jobs_and_conversations(self):
        summary = economico.format_run_summary(
            attempted=14, completed=12, failed=2, calls=7,
            conversations=72, tokens=131535,
            stop_reason="limite de falhas consecutivas",
        )
        self.assertIn("12/14 pedidos concluidos", summary)
        self.assertIn("2 pedidos falhados", summary)
        self.assertIn("72 conversas novas", summary)
        self.assertIn("131535 tokens", summary)

    def test_codex_command_uses_low_before_exec(self):
        cmd = economico.codex_command(
            "codex", "gpt-6-luna", "low", Path("/tmp/response.json"), ephemeral=True)
        self.assertEqual(cmd[0:2], ["codex", "--ask-for-approval"])
        self.assertEqual(cmd[cmd.index("-c") + 1], "model_reasoning_effort=low")
        self.assertLess(cmd.index("-c"), cmd.index("exec"))
        self.assertEqual(cmd[cmd.index("--model") + 1], "gpt-6-luna")
        self.assertIn("--ephemeral", cmd)
        self.assertEqual(cmd[-1], "-")

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
