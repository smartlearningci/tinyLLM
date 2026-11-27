import gzip
import json
import tempfile
import unittest
from pathlib import Path
from recolher_boakpe_api import recolher, registo_da_linha, PAGE_SIZE

TEXT='No jardim da escola, a Leonor encontrou uma caixa cheia de cartas e chamou os amigos. '*9

def fake_page(offset, length):
    assert length==PAGE_SIZE
    if offset==200: return {'rows': []}
    return {'rows': [{'row_idx': i,'row':{'titulo': f'Conto {i}', 'texto': TEXT+str(i)}} for i in range(offset,offset+PAGE_SIZE)]}

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_registo_formato(self):
        reg=registo_da_linha({'titulo':' O mar ', 'texto':TEXT},42)
        self.assertEqual(reg['source'],'historinhas')
        self.assertEqual(reg['lang_original'],'pt-BR')
        self.assertEqual(reg['dataset_row_id'],'42')
    def test_recolha_retomada(self):
        out=self.p/'historinhas.jsonl.gz'
        parcial=recolher(out, 150,pedir=fake_page,max_paginas=1)
        self.assertFalse(parcial['publicado']);self.assertFalse(out.exists())
        result=recolher(out,150,pedir=fake_page)
        self.assertTrue(result['publicado']);self.assertEqual(result['historias'],150)
        with gzip.open(out,'rt') as f:
            rows=[json.loads(x) for x in f]
        self.assertEqual(len(rows),150)
        self.assertEqual(len({x['sha_original'] for x in rows}),150)
        with self.assertRaises(FileExistsError):recolher(out,150,pedir=fake_page)
    def test_sem_registos_nao_publica(self):
        out=self.p/'historinhas.jsonl.gz'
        with self.assertRaisesRegex(RuntimeError,'Nenhuma história válida'):
            recolher(out, 150,pedir=lambda offset, length:{'rows':[]})
        self.assertFalse(out.exists())
    def test_rejeita_texto_curto(self):
        self.assertIsNone(registo_da_linha({'texto':'Olá'},0))
    def test_resume_com_pagina_filtrada(self):
        out=self.p/'historinhas.jsonl.gz'
        def pag(off, length):
            if off==0: return {'rows':[{'row_idx':i,'row':{'texto':'Olá'}} for i in range(100)]}
            if off==100: return {'rows':[{'row_idx':i,'row':{'texto':TEXT+str(i)}} for i in range(100,200)]}
            return {'rows':[]}
        p=recolher(out,100,pedir=pag,max_paginas=1)
        self.assertEqual(p['unicas'],0)
        r=recolher(out,100,pedir=pag)
        self.assertEqual(r['historias'],100)

if __name__=='__main__':unittest.main()