"""Testes offline para o pipeline Codex de historias; nao consomem quota."""
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codex_adapt_stories as pipeline

BR = ('A menina pegou o ônibus para ir até a fazenda da vovó. '
      'Ela estava muito feliz porque ia visitar seus amigos. '
      'No caminho, ouviu os pássaros cantando e viu um jardim colorido. '
      'Quando chegou, a avó lhe deu um abraço carinhoso e contou uma bela história. '
      'Todos se divertiram e aprenderam uma lição sobre amizade.')
PT = BR.replace('pegou o ônibus', 'apanhou o autocarro').replace('fazenda da vovó',
      'quinta da avó').replace('seus amigos','seus amigos')


def criar_fonte(path, source, quantity, shared=0):
    with gzip.open(path, 'wt', encoding='utf-8') as f:
        for i in range(quantity):
            texto = BR + f' A historia numero {i} tem um final feliz. '
            if source == 'historinhas' and i >= 2:
                texto += ' Esta versão inclui a visita a uma praia portuguesa. '
            # Os primeiros dois são duplicados entre ambas as fontes.
            sha = pipeline.digest_text(texto)
            row = {'id': f'{source}:{sha[:24]}', 'source': source, 'text_original': texto,
                   'sha_original': sha, 'lang_original': 'pt-BR', 'titulo_original': 'Uma história'}
            f.write(json.dumps(row, ensure_ascii=False)+'\n')


class TestCodexStories(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.p = Path(self.temp.name)
        self.tiny = self.p/'tiny.gz'
        self.hist = self.p/'hist.gz'
        self.queue = self.p/'fila_v1.jsonl'
        criar_fonte(self.tiny, 'tinystories', 75)
        criar_fonte(self.hist, 'historinhas', 45)

    def test_preparar_50_misto_reutiliza_fila_e_ignora_duplicados(self):
        meta = pipeline.preparar(self.tiny, self.hist, self.queue)
        self.assertEqual(meta['count'], 75 + 43)
        self.assertEqual(meta['counts']['duplicadas_entre_ou_dentro_fontes'], 2)
        self.assertEqual(pipeline.load_manifest(self.queue)['count'], 118)
        with self.queue.open(encoding='utf-8') as f:
            first = [json.loads(next(f)) for _ in range(50)]
        self.assertEqual([x['source'] for x in first].count('tinystories'), 30)
        self.assertEqual([x['source'] for x in first].count('historinhas'), 20)
        self.assertEqual(len({x['sha_original'] for x in first}), 50)
        with self.assertRaises(FileExistsError):
            pipeline.preparar(self.tiny, self.hist, self.queue)

    def test_schema_prompt_and_ids(self):
        samples = [{'id':'h:0','sha_original':'abc', 'text_original':BR},
                   {'id':'h:1','sha_original':'def', 'text_original':BR}]
        message = pipeline.prompt(samples)
        self.assertIn('português de Portugal', message)
        self.assertIn('Não resumas nem inventes', message)
        self.assertNotIn('recipe_id', message)
        correct = {'responses':[{'id':'h:0','text_ptpt':PT},{'id':'h:1','text_ptpt':PT}]}
        self.assertEqual(len(pipeline.validate_response(correct, samples)), 2)
        with self.assertRaises(ValueError):
            pipeline.validate_response({'responses':[{'id':'h:0','text_ptpt':PT}]},samples)
        with self.assertRaises(ValueError):
            pipeline.validate_response({'responses':[{'id':'h:0','text_ptpt':PT},
                    {'id':'h:0','text_ptpt':PT}]},samples)
        schema = json.loads(pipeline.SCHEMA.read_text(encoding='utf-8'))
        self.assertEqual(schema['properties']['responses']['items']['required'], ['id','text_ptpt'])

    def test_recupera_prefixo_trocado_sem_perder_hash(self):
        hashes = [pipeline.digest_text(f'origem-{i}') for i in range(10)]
        batch = [{'id': ('tinystories:' if i % 2 else 'historinhas:') + h[:24],
                  'sha_original': h, 'text_original': BR}
                 for i,h in enumerate(hashes)]
        responses = []
        for i,row in enumerate(batch):
            source,suffix = row['id'].split(':')
            trocado = ('historinhas' if source == 'tinystories' else 'tinystories')
            responses.append({'id': trocado+':'+suffix, 'text_ptpt': PT+str(i)})
        result = pipeline.validate_response({'responses':responses}, batch)
        self.assertEqual(list(result), [x['id'] for x in batch])
        self.assertEqual(result[batch[5]['id']], PT+'5')

    def test_rejeita_hash_alterado_ou_duplicado_apos_normalizacao(self):
        sha1 = pipeline.digest_text('original-um')
        sha2 = pipeline.digest_text('original-dois')
        batch = [{'id': 'tinystories:'+sha1[:24], 'sha_original': sha1},
                 {'id': 'historinhas:'+sha2[:24], 'sha_original': sha2}]
        valid = [{'id':'historinhas:'+sha1[:24], 'text_ptpt':PT},
                 {'id':'historinhas:'+sha2[:24], 'text_ptpt':PT}]
        self.assertEqual(len(pipeline.validate_response({'responses':valid}, batch)),2)
        duplicate = [valid[0], {'id':batch[0]['id'], 'text_ptpt':PT}]
        with self.assertRaisesRegex(ValueError,'ID incorreto'):
            pipeline.validate_response({'responses':duplicate}, batch)
        wrong = [dict(valid[0], id='historinhas:'+('0'*24)), valid[1]]
        with self.assertRaisesRegex(ValueError,'ID incorreto'):
            pipeline.validate_response({'responses':wrong}, batch)

    def test_recupera_evento_com_prefixo_trocado_sem_chamada(self):
        hashes = [pipeline.digest_text(f'evento-{i}') for i in range(10)]
        batch = [{'id':'tinystories:'+sha[:24], 'sha_original':sha,
                  'text_original':BR} for sha in hashes]
        f = self.p/'queue_event.jsonl'
        f.write_text(chr(10).join(json.dumps(x) for x in batch)+chr(10),
                     encoding='utf-8')
        run = self.p/'recover_prefix'; (run/'batches').mkdir(parents=True)
        replies = {'responses':[{'id':'historinhas:'+sha[:24],
                                 'text_ptpt':PT+str(i)} for i,sha in enumerate(hashes)]}
        events = {'type':'item.completed', 'item':{'type':'agent_message',
                                                   'text':json.dumps(replies)}}
        (run/'batches/batch_000000.events.jsonl').write_text(json.dumps(events)+chr(10))
        cfg={'model':'test','batch_size':10}
        args=SimpleNamespace(out=run,batch_size=10,model='test')
        self.assertEqual(pipeline.recover_events(args,f,10,cfg),1)
        saved=json.loads((run/'batches/batch_000000.json').read_text())
        self.assertEqual([x['id'] for x in saved['responses']], [x['id'] for x in batch])
        self.assertEqual(saved['quality_status'],'codex_unverified_recovered')
        self.assertEqual(pipeline.recover_events(args,f,10,cfg),0)

    def test_particoes_de_50_e_total_estavel(self):
        batch = [{'id':f'x:{i}','sha_original':str(i)} for i in range(120)]
        f = self.p/'queue.jsonl'
        f.write_text(''.join(json.dumps(x)+'\n' for x in batch), encoding='utf-8')
        self.assertEqual([x for x,_ in pipeline.batches(f,50,10)],list(range(5)))
        self.assertEqual([x for x,_ in pipeline.batches(f,120,10)][:5],list(range(5)))

    def test_recover_sem_gastar_plafond(self):
        batch=[{'id':f'h:{i}','sha_original':str(i),'text_original':BR} for i in range(10)]
        f = self.p/'queue.jsonl'; f.write_text(''.join(json.dumps(x)+'\n' for x in batch))
        run = self.p/'run'; (run/'batches').mkdir(parents=True)
        responses={'responses':[{'id':x['id'],'text_ptpt':PT} for x in batch]}
        evt={'type':'item.completed','item':{'type':'agent_message','text':json.dumps(responses)}}
        (run/'batches/batch_000000.events.jsonl').write_text(json.dumps(evt)+'\n')
        cfg={'model':'test','batch_size':10}
        args=SimpleNamespace(out=run,batch_size=10,model='test')
        self.assertEqual(pipeline.recover_events(args,f,10,cfg),1)
        self.assertEqual(pipeline.recover_events(args,f,10,cfg),0)
        saved=json.loads((run/'batches/batch_000000.json').read_text())
        self.assertEqual(len(saved['responses']),10)
        self.assertEqual(saved['config'],cfg)

    def test_exportar_nao_permita_falta_de_lote(self):
        # Manifesto de 50 registos e configuracao compatível; sem conversões.
        rows = [{'id':f'tinystories:{i}', 'source':'tinystories',
                 'text_original':BR+str(i), 'sha_original':pipeline.digest_text(BR+str(i)),
                 'lang_original':'pt-BR'} for i in range(50)]
        self.queue.write_text(''.join(json.dumps(x)+'\n' for x in rows))
        manifest={'count':50,'queue_sha256':pipeline.digest_bytes(self.queue)}
        self.queue.with_suffix('.manifest.json').write_text(json.dumps(manifest))
        run=self.p/'run';run.mkdir()
        cfg={'queue_sha256':manifest['queue_sha256'],'batch_size':10,'model':'test'}
        pipeline.save_json_atomic(run/'run_config.json',cfg)
        args=SimpleNamespace(queue=self.queue,run=run,limit=50,out=self.p/'converted.gz')
        with self.assertRaisesRegex(RuntimeError,'Lote ainda nao concluido'):
            pipeline.export(args)
        self.assertFalse(args.out.exists())
        (run/'batches').mkdir()
        for idx,batch in pipeline.batches(self.queue,50,10):
            js={'digest':pipeline.batch_digest(batch),'config':cfg,
                'responses':[{'id':x['id'],'text_ptpt':PT+str(idx)} for x in batch]}
            (run/'batches'/f'batch_{idx:06d}.json').write_text(json.dumps(js))
        result=pipeline.export(args)
        self.assertEqual(result['convertidas'],50)
        self.assertEqual(result['estado'],'pending_audit')
        with gzip.open(args.out,'rt',encoding='utf-8') as f:
            items=[json.loads(line) for line in f]
        self.assertEqual(len(items),50)
        self.assertEqual(items[0]['batch_id'],items[-1]['batch_id'])
        self.assertTrue(all(x['status']=='pending_audit' for x in items))
        self.assertTrue(all(x['source']=='tinystories' for x in items))

    def test_piloto_e_continuacao_sem_repetir_codex(self):
        pipeline.preparar(self.tiny, self.hist, self.queue)
        run = self.p/'production'
        kwargs = {'queue':self.queue, 'out':run, 'batch_size':10, 'workers':2,
                  'model':'gpt-6-luna', 'reasoning':'low', 'codex':'codex',
                  'timeout':60, 'retry_errors':False, 'max_new_batches':0,
                  'dry_run':False, 'recover_events':False}
        counter = {'calls':0}
        def fake_process(command,**options):
            if command[-2:] == ['login','status']:
                return SimpleNamespace(returncode=0,stdout='Logged in with ChatGPT',stderr='')
            counter['calls'] += 1
            import re
            found = json.loads(options['input'].split('HISTÓRIAS:\n',1)[1])
            output = {'responses':[{'id':x['id'],'text_ptpt':PT+str(counter['calls'])} for x in found]}
            Path(command[command.index('-o')+1]).write_text(json.dumps(output))
            return SimpleNamespace(returncode=0, stderr='',stdout=json.dumps({
                'type':'turn.completed','usage':{'input_tokens':100,'output_tokens':200}}))
        with patch.object(pipeline.subprocess,'run',side_effect=fake_process), \
             patch.object(pipeline.shutil,'which',return_value='/usr/bin/codex'):
            a = SimpleNamespace(limit=50,**kwargs)
            report = pipeline.generate(a)
            self.assertEqual(report['historias_convertidas'], 50)
            self.assertEqual(counter['calls'],5)
            a.limit=0
            report = pipeline.generate(a)
            self.assertEqual(report['historias_convertidas'],118)
            self.assertEqual(counter['calls'],12)  # 5 primeiros sao reutilizados
            self.assertEqual(report['output_tokens'],12*200)
        report = pipeline.export(SimpleNamespace(queue=self.queue,run=run,
                  limit=50,out=self.p/'pilot.gz'))
        self.assertEqual(report['convertidas'],50)
        self.assertEqual(report['origens']['tinystories'],30)
        self.assertEqual(report['origens']['historinhas'],20)

    def test_codex_cli_mesmo_metodo_do_professor_sem_api(self):
        args=SimpleNamespace(out=self.p/'run', model='gpt-6-luna',reasoning='low',
                             codex='codex',timeout=10,retry_errors=False)
        cfg={'model':'gpt-6-luna'}
        batch=[{'id':'a','sha_original':'abc','text_original':BR}]
        def fake_process(command,**kwargs):
            self.assertIn('--output-schema',command)
            self.assertIn('read-only',command)
            self.assertIn('gpt-6-luna',command)
            self.assertIn('português de Portugal',kwargs['input'])
            Path(command[command.index('-o')+1]).write_text(json.dumps({'responses':[{'id':'a','text_ptpt':PT}]}))
            return SimpleNamespace(returncode=0,stderr='',stdout=json.dumps({'type':'turn.completed','usage':{'input_tokens':100,'output_tokens':200}}))
        with patch.object(pipeline.subprocess,'run',side_effect=fake_process):
            r=pipeline.codex_call(0,batch,args,cfg,pipeline.Event())
        self.assertEqual(r[0],'ok')
        saved=json.loads((args.out/'batches/batch_000000.json').read_text())
        self.assertEqual(saved['usage']['output_tokens'],200)
        self.assertEqual(saved['quality_status'],'codex_unverified')
        self.assertEqual(pipeline.codex_call(0,batch,args,cfg,pipeline.Event())[0],'skipped')


if __name__=='__main__':
    unittest.main()