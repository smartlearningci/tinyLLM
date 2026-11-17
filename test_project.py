"""Verificações offline: leitura web, revisão, origem e exclusão de validação."""
import contextlib
import fcntl
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
import monitor
import preparar
import distill
import test_distill


class ProjectTest(unittest.TestCase):
    def test_training_export_while_worker_holds_shared_lock(self):
        fixture=test_distill.PipelineTest();fixture.setUp()
        try:
            distill.store_response(fixture.db,fixture.job,fixture.response(),'test','fixture')
            root=fixture.work/'project';data=root/'dados';data.mkdir(parents=True)
            with sqlite3.connect(data/'queue.sqlite') as target:
                fixture.db.backup(target)
            validation=data/'validation_v01.jsonl'
            validation.write_text(json.dumps({'recipe_id':'reserved','context':{'chunks':[{'text':'Different validation recipe'}]}})+'\n')
            with (data/'queue.lock').open('a') as worker_lock:
                fcntl.flock(worker_lock,fcntl.LOCK_SH)
                with patch.object(preparar,'ROOT',root),contextlib.redirect_stdout(io.StringIO()):
                    preparar.treino(validation,'culinario_v04')
            report=json.loads((data/'exports'/'culinario_v04'/'dataset_report.json').read_text())
            self.assertEqual(report['train_examples'],6)
            self.assertEqual(report['validation_examples'],1)
        finally: fixture.tearDown()

    def test_monitor_read_review_and_origin(self):
        fixture=test_distill.PipelineTest();fixture.setUp()
        try:
            distill.store_response(fixture.db,fixture.job,fixture.response(),'chatgpt','fixture')
            eid=fixture.db.execute('SELECT id FROM examples LIMIT 1').fetchone()[0]
            server=ThreadingHTTPServer(('127.0.0.1',0),monitor.handler_for(monitor.ROOT,fixture.work))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                for route in ('/','/api/config','/api/guides','/api/models','/api/overview','/api/recipes','/api/outputs'):
                    with urlopen(base+route) as r: self.assertEqual(r.status,200)
                payload=json.dumps({'id':eid,'decision':'accepted','note':'Revisão de teste'}).encode()
                req=Request(base+'/api/review',data=payload,headers={'Content-Type':'application/json','Origin':base})
                with urlopen(req) as r: self.assertEqual(r.status,200)
                self.assertEqual(fixture.db.execute('SELECT status FROM examples WHERE id=?',(eid,)).fetchone()[0],'accepted')
                req=Request(base+'/api/review',data=payload,headers={'Content-Type':'application/json','Origin':'https://external.invalid'})
                with self.assertRaises(HTTPError) as e:urlopen(req)
                self.assertEqual(e.exception.code,403)
            finally: server.shutdown();server.server_close();thread.join()
        finally: fixture.tearDown()

    def test_group_text_protection(self):
        a={'recipe_id':'a','context':{'chunks':[{'text':'One Recipe'}]}}
        b={'recipe_id':'b','context':{'chunks':[{'text':'one   recipe'}]}}
        self.assertTrue(preparar.grupo(a)&preparar.grupo(b))

    def test_migration_is_independent_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=root/'old';(old/'work').mkdir(parents=True)
            db=distill.open_db(old/'work');db.close()
            new=root/'new';new.mkdir()
            with patch.object(preparar,'ROOT',new),contextlib.redirect_stdout(io.StringIO()):
                preparar.migrar(old)
                self.assertTrue((new/'dados'/'queue.sqlite').is_file())
                with self.assertRaises(ValueError):preparar.migrar(old)
