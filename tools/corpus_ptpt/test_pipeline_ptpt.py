import csv
import gzip
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fontes_literarias import eltec_docs, parlamint_docs, adamastor_docs, textos_docs, dividir_texto, obter_eltec, git_blob_sha
from historias_ptpt import (candidatos_linhas, recolher, adaptar, auditar, gerar_amostra,
                             publicar, juntar_aprovadas, sinais_br, NearDuplicates, ler_linhas, auditar_registro)
from build_ptpt import ingere_documentos, merge
from finalizar_dataset import auditar_pretrain, preparar_qa, exportar_kaggle
from equilibrar_corpus import preparar as equilibrar, cotas_disponiveis

TEXT = ('A Leonor encontrou uma caixa antiga no jardim da escola. ' * 5 +
        'A professora pediu aos alunos que a abrissem com cuidado. ' * 4 +
        'Todos descobriram um livro de histórias e ficaram muito contentes.')
BR = ('A garotinha estava fazendo um passeio quando viu um ônibus. ' * 6 +
      'Foi até o banheiro, encontrou a vovó e comeu sorvete com os amigos. ' * 3)
PT = ('A menina estava a passear quando viu um autocarro. ' * 6 +
      'Foi à casa de banho, encontrou a avó e comeu gelado com os amigos. ' * 3)


class TestFontes(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.p = Path(self.t.name)
    def tearDown(self):
        self.t.cleanup()

    def test_eltec_obra_longa_mantem_grupo_e_split(self):
        folder = self.p / 'eltec'; folder.mkdir()
        texto = ('\n\n'.join([TEXT]*60))
        (folder / 'obra.xml').write_text('<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader>Introdução não usada</teiHeader><text><body><div><p>'+texto.replace('\n\n','</p><p>')+'</p></div></body></text></TEI>', encoding='utf-8')
        docs = list(eltec_docs(folder, max_chars=3000))
        self.assertGreater(len(docs), 10)
        self.assertEqual(len(set(x['group'] for x in docs)),1)
        source = self.p / 'raw.jsonl.gz'
        counts = ingere_documentos(docs, source, 'eltec_por')
        self.assertGreater(counts['guardados'], 0)
        result = merge(self.p/'release', [source], val_permille=50)
        self.assertEqual(result['train'] + result['validation'], counts['guardados'])
        self.assertTrue(result['train'] == 0 or result['validation'] == 0)

    def test_parlamint_fala_sem_cabecalhos(self):
        folder = self.p / 'parlamint'; folder.mkdir()
        (folder/'sessao.xml').write_text('<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader>SECRET</teiHeader><text><body><div><u who="p1"><seg>'+TEXT+'</seg></u><u who="p2"><seg>'+TEXT.replace('Leonor','Maria')+'</seg></u></div></body></text></TEI>',encoding='utf-8')
        docs = list(parlamint_docs(folder))
        self.assertEqual(len(docs), 2)
        self.assertNotIn('SECRET', docs[0]['text'])
        self.assertEqual(docs[0]['group'], docs[1]['group'])

    def test_epub_respeita_spine(self):
        folder = self.p / 'adam'; folder.mkdir()
        f = folder / 'obra.epub'
        with zipfile.ZipFile(f, 'w') as z:
            z.writestr('META-INF/container.xml','<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
            z.writestr('OEBPS/content.opf','<package><manifest><item id="b" href="b.xhtml"/><item id="a" href="a.xhtml"/></manifest><spine><itemref idref="a"/><itemref idref="b"/></spine></package>')
            z.writestr('OEBPS/a.xhtml','<html><body><p>'+TEXT+'</p></body></html>')
            z.writestr('OEBPS/b.xhtml','<html><body><p>'+TEXT.replace('Leonor','Joana')+'</p></body></html>')
        docs = list(adamastor_docs(folder))
        self.assertEqual(len(docs), 1)
        self.assertLess(docs[0]['text'].index('Leonor'),docs[0]['text'].index('Joana'))

    def test_download_eltec_sha_e_reutilizacao(self):
        blob=b'<TEI><text><body><p>Exemplo</p></body></text></TEI>'
        listing=[{'type':'file','name':'obra.xml','sha':git_blob_sha(blob),
                  'download_url':'https://raw.githubusercontent.com/mock/obra.xml'}]
        f=lambda _: blob
        a=obter_eltec(self.p/'level1',listing=listing,transfer=f)
        self.assertEqual(a['novos'],1)
        b=obter_eltec(self.p/'level1',listing=listing,transfer=lambda _: self.fail('Redownload'))
        self.assertEqual(b['ja_existiam'],1)
        (self.p/'level1/obra.xml').write_text('alterado')
        with self.assertRaises(ValueError):
            obter_eltec(self.p/'level1',listing=listing,transfer=f)

    def test_texto_tamanho(self):
        blocks = list(dividir_texto((TEXT+'\n')*30, max_chars=1000))
        self.assertGreater(len(blocks), 2)
        self.assertTrue(all(len(x)<=1000 for x in blocks))


class TestHistorias(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(); self.p=Path(self.t.name)
    def tearDown(self): self.t.cleanup()

    def test_esquemas_e_recolha(self):
        a=list(candidatos_linhas([{'texto':BR,'titulo':'A Vida'}], 'historinhas'))
        b=list(candidatos_linhas([{'text':BR}], 'tinystories'))
        self.assertEqual(len(a),1); self.assertEqual(len(b),1)
        self.assertEqual(a[0]['lang_original'],'pt-BR')
        out=self.p/'raw.jsonl.gz'
        r=recolher('historinhas',out,rows=[{'texto':BR},{'texto':BR}])
        self.assertEqual(r['duplicados'],1)
        self.assertEqual(len(list(ler_linhas(out))),1)

    def test_reescrita_auditoria_review_e_publicacao(self):
        raw=self.p/'raw.gz'
        self.assertEqual(recolher('historinhas',raw,rows=[{'texto':BR}])['recolhidos'],1)
        converted=self.p/'adapted.gz'
        r=adaptar(raw,converted,'http://127.0.0.1:11434/v1/chat/completions','test-model',client=lambda _: PT)
        self.assertEqual(r['processadas_agora'],1)
        r=adaptar(raw,converted,'http://127.0.0.1:11434/v1/chat/completions','test-model',client=lambda _: 'error')
        self.assertEqual(r['processadas_agora'],0)
        audit=self.p/'audit.gz'
        qa=auditar(converted,audit)
        self.assertEqual(qa['pre_aprovados'],1)
        self.assertEqual(sinais_br(PT),[])
        review=self.p/'review.csv'
        rep=gerar_amostra(audit,review,por_lote=2)
        self.assertEqual(rep['amostras'],1)
        with review.open(encoding='utf-8-sig',newline='') as f:
            rows=list(csv.DictReader(f)); fields=list(rows[0])
        rows[0]['aprovada']='sim'
        with review.open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
        r=publicar(audit,review,self.p/'release')
        self.assertEqual(r['train']+r['validation'],1)
        with self.assertRaises(FileExistsError): publicar(audit,review,self.p/'release')

    def test_filtro_brasileirismos_e_revisao_pendente(self):
        self.assertIn('ônibus',sinais_br('O ônibus parou.'))
        row={'status':'pending_audit','text_original':BR,'text_ptpt':BR}
        self.assertFalse(auditar_registro(row)['auto_ok'])
        raw=self.p/'raw.gz'; recolher('historinhas',raw,rows=[{'texto':BR}])
        converted=self.p/'converted.gz'
        adaptar(raw,converted,'http://127.0.0.1:11434/v1/chat/completions','test-model',client=lambda _: PT)
        audit=self.p/'audit.gz'; auditar(converted,audit)
        review=self.p/'review.csv';gerar_amostra(audit,review)
        report=publicar(audit,review,self.p/'pending')
        self.assertEqual(report['train']+report['validation'],0)
        self.assertEqual(report['lote_sem_aprovacao'],1)

    def test_juntar_dedupe_de_duas_fontes(self):
        folders=[self.p/'a',self.p/'b']
        for folder,src,texto in zip(folders,['tinystories_ptbr_adaptado_ptpt',
                                            'historinhas_ptbr_adaptado_ptpt'],
                                    [TEXT,TEXT.replace('Leonor','Joana')]):
            folder.mkdir()
            (folder/'historias_report.json').write_text('{"train":1}',encoding='utf-8')
            with gzip.open(folder/'historias_train.jsonl.gz','wt',encoding='utf-8') as f:
                f.write(json.dumps({'id':src,'source':src,'group':'story:'+src,
                                    'lang':'pt-PT','text':texto},ensure_ascii=False)+'\n')
            with gzip.open(folder/'historias_validation.jsonl.gz','wt',encoding='utf-8') as f:
                pass
        r=juntar_aprovadas(folders,self.p/'combined',meta_historias=2)
        self.assertEqual(r['total_aceites'],1)
        self.assertEqual(r['duplicados_aproximados'],1)
        self.assertFalse(r['meta_atingida'])

    def test_neardup(self):
        db=NearDuplicates()
        self.assertTrue(db.add(TEXT))
        self.assertFalse(db.add(TEXT.replace('Leonor','Joana')))
        db.close()


class TestFinal(unittest.TestCase):
    def setUp(self): self.t=tempfile.TemporaryDirectory();self.p=Path(self.t.name)
    def tearDown(self):self.t.cleanup()

    def test_equilibrio_token_real_sem_fabricacao(self):
        class FakeEncoding:
            def __init__(self,t): self.ids=t.split()
        class FakeTokenizer:
            def encode(self,text,add_special_tokens=False): return FakeEncoding(text)
        inputs={}
        for name in ('train','validation'):
            path=self.p/(name+'.jsonl.gz')
            with gzip.open(path,'wt',encoding='utf-8') as f:
                for source in ('cetempublico','bagaco2','parlamint_pt','eltec_por'):
                    row={'id':f'{name}:{source}','group':source+name,
                         'lang':'pt-PT','source':source,'text':TEXT}
                    f.write(json.dumps(row,ensure_ascii=False)+'\n')
            inputs[name]=path
        quota={'bagaco2':500,'cetempublico':20,'parlamint_pt':20,'narrativa':20}
        result=equilibrar(inputs['train'],inputs['validation'],FakeTokenizer(),
                          self.p/'balanced',quotas=quota)
        self.assertLessEqual(result['total_tokens'],sum(quota.values()))
        self.assertEqual(result['contagem_disponivel_tokens']['bagaco2'],2*(len(TEXT.split())+1))
        self.assertFalse(result['meta_atingida'])
        self.assertTrue((self.p/'balanced/quota_report.json').exists())
        self.assertEqual(cotas_disponiveis({'bagaco2':400,'cetempublico':0,'parlamint_pt':0,'narrativa':0},quota)['bagaco2'],400)

    def test_qa_e_bloqueio_dados(self):
        src=self.p/'qa';src.mkdir()
        for split in ('train','validation','test'):
            with gzip.open(src/f'fairytale_qa_{split}.jsonl.gz','wt',encoding='utf-8') as f:
                f.write(json.dumps({'story': split,'context':TEXT,'question':'Onde?','answer':'Na escola.'},ensure_ascii=False)+'\n')
        result=preparar_qa(src,self.p/'sft')
        self.assertEqual(result['test']['count'],1)
        with gzip.open(self.p/'sft/qa_train.jsonl.gz','rt',encoding='utf-8') as f:
            row=json.loads(f.readline())
        self.assertEqual(row['messages'][2]['role'],'assistant')
        self.assertEqual(row['split'],'train')
        with self.assertRaises(ValueError):
            exportar_kaggle(self.p/'release',self.p/'kaggle.zip')

    def test_auditoria_deteta_fuga_de_grupo(self):
        for split in ('train','validation'):
            with gzip.open(self.p/f'{split}.jsonl.gz','wt',encoding='utf-8') as f:
                row={'id':split,'group':'livro:1','source':'eltec_por','lang':'pt-PT','text':TEXT.replace('Leonor','Joana' if split=='train' else 'Laura')}
                f.write(json.dumps(row,ensure_ascii=False)+'\n')
        result=auditar_pretrain(self.p/'train.jsonl.gz',self.p/'validation.jsonl.gz',self.p/'report.json')
        self.assertEqual(result['status'],'bloqueado')
        self.assertEqual(result['bloqueios']['fuga_grupo_train_validation'],1)


if __name__=='__main__': unittest.main()