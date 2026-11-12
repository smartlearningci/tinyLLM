"""Offline integration checks. Fake teacher responses are NEVER production data."""
import argparse
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import distill as d


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.work=Path(self.tmp.name)
        self.db=d.open_db(self.work)
        self.config=json.loads((d.ROOT/'config.json').read_text())
        self.source=self.work/'recipes.jsonl'
        records=[{'id':'r1','text':'Title: Tomato soup\nIngredients: tomatoes, water, salt.\nMethod: Simmer the tomatoes in water. Blend until smooth.',
                  'metadata':{'source':'recipe_nlg_lite','split':'train','title':'Tomato soup'}},
                 {'id':'r2','text':'Reserved recipe must never enter training.','metadata':{'source':'recipe_nlg_lite','split':'validation'}}]
        self.source.write_text('\n'.join(json.dumps(x) for x in records))
        with contextlib.redirect_stdout(io.StringIO()):
            d.ingest(self.db,argparse.Namespace(file=str(self.source),source='recipe_nlg_lite',assume_train=False))
            d.plan(self.db,argparse.Namespace(limit=1,knowledge=None),self.config)
        self.job=self.db.execute('SELECT * FROM jobs ORDER BY created,id LIMIT 1').fetchone()
        self.request=json.loads(self.job['request'])

    def tearDown(self):
        self.db.close();self.tmp.cleanup()

    def test_status_preserves_running_job(self):
        self.db.execute("UPDATE jobs SET status='running' WHERE id=?", (self.job['id'],))
        self.db.commit()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            d.main(['--work', str(self.work), 'status'])
        self.assertIn('running: 1', output.getvalue())
        self.assertEqual(self.db.execute('SELECT status FROM jobs WHERE id=?', (self.job['id'],)).fetchone()[0], 'running')

    def response(self):
        examples=[]
        for task in self.request['tasks']:
            cap=task['capability'];slot=task['slot']
            messages=[{'role':'user','content':f'Fixture question {slot}: Which ingredients are listed?'},
                      {'role':'assistant','content':'The listed ingredients are tomatoes, water and salt.'}]
            if cap=='C6':messages += [{'role':'user','content':'Which of those is the liquid?'},{'role':'assistant','content':'Water is the liquid listed.'}]
            examples.append({'slot':slot,'capability':cap,'supported':True,'evidence_type':'E0' if cap=='C7' else 'E1',
              'difficulty':'easy','messages':messages,'evidence':[{'source_id':'r1','quote':'Ingredients: tomatoes, water, salt.'}],
              'evidence_note':'Test fixture only: not a real pedagogical validation.'})
        return {'job_id':self.job['id'],'examples':examples}

    def test_holdout_idempotence_and_plan(self):
        self.assertEqual(self.db.execute('SELECT count(*) FROM recipes').fetchone()[0],1)
        with contextlib.redirect_stdout(io.StringIO()):
            d.plan(self.db,argparse.Namespace(limit=1,knowledge=None),self.config)
        self.assertEqual(self.db.execute('SELECT count(*) FROM jobs').fetchone()[0],5)

    def test_missing_slot_and_fabricated_quote_rejected(self):
        data=self.response();data['examples'].pop()
        with self.assertRaises(ValueError):d.validate_response(data,self.request)
        data=self.response();data['examples'][0]['evidence'][0]['quote']='Bake at 400 degrees for 90 minutes.'
        with self.assertRaises(ValueError):d.validate_response(data,self.request)
        self.assertEqual(self.db.execute('SELECT count(*) FROM examples').fetchone()[0],0)

    def test_idempotent_output_and_full_context_export(self):
        data=self.response();d.store_response(self.db,self.job,data,'test','fake')
        again=d.store_response(self.db,self.job,data,'test','fake')
        self.assertEqual(again['added'],0)
        out=self.work/'export'
        with contextlib.redirect_stdout(io.StringIO()):d.export_data(self.db,argparse.Namespace(out=str(out),reviewed_only=False))
        rows=list(d.read_jsonl(out/'sft_train.jsonl'))
        self.assertEqual(len(rows),6)
        self.assertIn(self.request['recipe']['text'],rows[0]['messages'][1]['content'])
        with contextlib.redirect_stdout(io.StringIO()):d.export_data(self.db,argparse.Namespace(out=str(out),reviewed_only=True))
        self.assertEqual(list(d.read_jsonl(out/'sft_train.jsonl')),[])

    def test_reserved_manual_jobs_are_not_pending(self):
        with contextlib.redirect_stdout(io.StringIO()):
            d.export_prompts(self.db,argparse.Namespace(out=str(self.work/'prompts'),limit=2))
        self.assertEqual(self.db.execute("SELECT count(*) FROM jobs WHERE status='manual'").fetchone()[0],2)
        self.assertEqual(self.db.execute("SELECT count(*) FROM jobs WHERE status='pending'").fetchone()[0],3)

    def test_e4_needs_review(self):
        request=copy.deepcopy(self.request)
        request['knowledge']=[{'source_id':'note1','text':'A supplied technical note with an explanation.','source_url':'https://example.org/note'}]
        self.db.execute('UPDATE jobs SET request=? WHERE id=?',(d.dumps(request),self.job['id']));self.db.commit()
        job=self.db.execute('SELECT * FROM jobs WHERE id=?',(self.job['id'],)).fetchone()
        data=self.response()
        item=next(e for e in data['examples'] if e['capability']!='C7')
        item['evidence_type']='E4';item['evidence'].append({'source_id':'note1','quote':'A supplied technical note with an explanation.'})
        d.store_response(self.db,job,data,'test','fake')
        self.assertEqual(self.db.execute("SELECT count(*) FROM examples WHERE status='needs_review'").fetchone()[0],1)

    def test_code_execution_adapter_offline_and_quota_stop(self):
        calls=[]
        def fake_run(cmd,**kwargs):
            calls.append(cmd)
            if cmd[1:]==['login','status']:return argparse.Namespace(returncode=0,stdout='',stderr='Logged in using ChatGPT')
            if cmd[1:]==['exec','--help']:return argparse.Namespace(returncode=0,stdout='--output-schema --ephemeral',stderr='')
            Path(cmd[cmd.index('-o')+1]).write_text(json.dumps(self.response()))
            kwargs['stdout'].write(json.dumps({'type':'turn.completed','usage':{'input_tokens':100,'output_tokens':200}})+'\n')
            return argparse.Namespace(returncode=0)
        args=argparse.Namespace(codex_bin='codex',model=None,limit=1)
        with patch.dict('os.environ',{},clear=True),patch('shutil.which',return_value='/test/codex'),patch('subprocess.run',side_effect=fake_run),contextlib.redirect_stdout(io.StringIO()):
            d.run_codex(self.db,args,self.config,self.work)
        self.assertEqual(self.db.execute("SELECT count(*) FROM jobs WHERE status='done'").fetchone()[0],1)
        self.assertIn('read-only',calls[-1]);self.assertEqual(calls[-1][-1],'-')
        def failed_run(cmd,**kwargs):
            if 'exec' in cmd and '--help' not in cmd:return argparse.Namespace(returncode=1)
            return fake_run(cmd,**kwargs)
        with patch.dict('os.environ',{},clear=True),patch('shutil.which',return_value='/test/codex'),patch('subprocess.run',side_effect=failed_run):
            with self.assertRaises(ValueError):d.run_codex(self.db,args,self.config,self.work)
        self.assertEqual(self.db.execute("SELECT count(*) FROM jobs WHERE status='error'").fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM jobs WHERE status='pending'").fetchone()[0],3)

    def test_complete_conversation_and_export(self):
        data=self.response()
        item=next(e for e in data['examples'] if e['capability']=='C7')
        item['messages'] += [{'role':'user','content':'I cannot find that information.'},{'role':'assistant','content':'The source cannot establish that missing detail.'}]
        d.validate_response(data,self.request)
        item['messages'].pop()
        with self.assertRaises(ValueError):d.validate_response(data,self.request)

    def test_batch_filters_partial_import_and_retry(self):
        out=self.work/'batch'
        args=argparse.Namespace(out=str(out),limit=2,batch_size=2,status='pending',persona=None,recipe='r1',job=None)
        with contextlib.redirect_stdout(io.StringIO()):d.export_prompts(self.db,args)
        files=list(out.glob('*.txt'));self.assertEqual(len(files),1)
        self.assertEqual(len(json.loads(files[0].read_text().split('\nREQUESTS\n')[1])),2)
        path=self.work/'answers.json'
        path.write_text(json.dumps([self.response(),{'job_id':'unknown'}]))
        args=argparse.Namespace(path=str(path),provider='copilot',teacher='test')
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(ValueError):d.import_responses(self.db,args,self.work)
            path.write_text(json.dumps([self.response()]))
            d.import_responses(self.db,args,self.work)
        self.assertEqual(self.db.execute('SELECT count(*) FROM examples').fetchone()[0],6)

    def test_upgrade_preserves_manual_done_and_ids(self):
        d.store_response(self.db,self.job,self.response(),'test','fake')
        self.db.execute("UPDATE jobs SET status='manual' WHERE persona='P2'")
        for job in self.db.execute('SELECT * FROM jobs').fetchall():
            req=json.loads(job['request']);req.pop('conversation_policy',None)
            self.db.execute('UPDATE jobs SET request=?,prompt=? WHERE id=?',(d.dumps(req),'old prompt',job['id']))
        self.db.commit()
        before=[tuple(r) for r in self.db.execute("SELECT * FROM jobs WHERE status IN ('done','manual') ORDER BY id")]
        with contextlib.redirect_stdout(io.StringIO()):d.upgrade_prompts(self.db,None,self.work)
        after=[tuple(r) for r in self.db.execute("SELECT * FROM jobs WHERE status IN ('done','manual') ORDER BY id")]
        self.assertEqual(before,after)
        self.assertEqual(len(list(self.work.glob('queue-before-v3-*.sqlite'))),1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM jobs WHERE prompt='old prompt'").fetchone()[0],2)
        with contextlib.redirect_stdout(io.StringIO()):d.plan(self.db,argparse.Namespace(limit=1,knowledge=None),self.config)
        self.assertEqual(self.db.execute('SELECT count(*) FROM jobs').fetchone()[0],5)

    def test_short_quotes_and_nonliteral_quotes(self):
        data=self.response();data['examples'][0]['evidence'][0]['quote']='salt'
        d.validate_response(data,self.request)
        data['examples'][0]['evidence'][0]['quote']='tomatoes [...] salt'
        with self.assertRaises(ValueError):d.validate_response(data,self.request)

    def test_provider_reservations_and_manual_upgrade(self):
        args=argparse.Namespace(out=str(self.work/'gemini'),limit=2,batch_size=2,status='pending',provider='gemini')
        with contextlib.redirect_stdout(io.StringIO()):d.export_prompts(self.db,args)
        self.assertEqual(self.db.execute("SELECT count(*) FROM jobs WHERE provider='gemini' AND status='manual'").fetchone()[0],2)
        self.db.execute("UPDATE jobs SET prompt='old',request=replace(request,'complete-v3','complete-v2') WHERE status='manual'");self.db.commit()
        with contextlib.redirect_stdout(io.StringIO()):d.upgrade_prompts(self.db,argparse.Namespace(include_manual=True),self.work)
        args.status='manual';args.out=str(self.work/'reexport')
        with contextlib.redirect_stdout(io.StringIO()):d.export_prompts(self.db,args)
        text=next(Path(args.out).glob('*.txt')).read_text()
        self.assertIn('complete-v3',text)
        self.assertEqual(self.db.execute("SELECT count(*) FROM jobs WHERE status='pending'").fetchone()[0],3)


if __name__=='__main__':unittest.main()
