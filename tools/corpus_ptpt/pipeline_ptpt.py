#!/usr/bin/env python3
"""Controlador portátil (Windows/macOS/Linux) do dataset TinySLM-PTPT.

'rascunho' descreve ausências; 'finalizar-geral' executa merge/tokenizer/pack
apenas depois de os ficheiros de fontes estarem preparados.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_ptpt import ROOT, merge
from preparar_treino import tokenizer_novo, codificar
from finalizar_dataset import auditar_pretrain, preparar_qa
from equilibrar_corpus import preparar as equilibrar

SOURCES = {
    'cetempublico': ROOT / 'processed/cetem.jsonl.gz',
    'bagaco2': ROOT / 'processed/bagaco.jsonl.gz',
    'parlamint_pt': ROOT / 'processed/parlamint.jsonl.gz',
    'eltec_por': ROOT / 'processed/eltec.jsonl.gz',
    'adamastor': ROOT / 'processed/adamastor.jsonl.gz',
}
RAW = {
    'CETEMPúblico': ROOT / 'raw/CETEMPublico1.7.gz',
    'ELTeC-por': ROOT / 'raw/eltec_level1',
    'ParlaMint-PT': ROOT / 'raw/parlamint_xml',
    'Adamastor': ROOT / 'raw/adamastor_epub',
}
STORIES = ['historias/raw/historinhas.jsonl.gz', 'historias/raw/tinystories.jsonl.gz',
           'historias/adaptados/historinhas.jsonl.gz', 'historias/adaptados/tinystories.jsonl.gz',
           'historias/auditoria/historinhas.jsonl.gz',
           'historias/auditoria/tinystories.jsonl.gz',
           'historias/revisao/historinhas.csv', 'historias/revisao/tinystories.csv',
           'historias/aprovadas/historinhas/historias_train.jsonl.gz',
           'historias/aprovadas/tinystories/historias_train.jsonl.gz']


def plano(release=ROOT / 'release/v1'):
    return {
        'meta_geral_tokens': 400000000,
        'meta_historias_aprovadas': 100000,
        'fontes_raw': {k: {'path':str(p), 'presente':p.exists()} for k,p in RAW.items()},
        'fontes_processadas': {k:{'path':str(p),'presente':p.is_file()} for k,p in SOURCES.items()},
        'fairytale': {k:(ROOT/f'processed/fairytale_qa_{k}.jsonl.gz').is_file()
                      for k in ('train','validation','test')},
        'historias': {s: (ROOT/s).is_file() for s in STORIES},
        'release_geral': {f: (release/f).is_file() for f in ('train.jsonl.gz',
                           'validation.jsonl.gz', 'dataset_report.json',
                           'tokenizer/tokenizer.json','bin/train.bin',
                           'bin/validation.bin','bin/pack_report.json',
                           'auditoria_report.json')},
        'nota': 'Presença de ficheiros não significa aprovação da qualidade; verificar relatório, hashes, quotas e licenças.'
    }


def finalizar_geral(release: Path, permitir_parcial=False, vocab_size=8192):
    inputs = [p for p in SOURCES.values() if p.is_file()]
    missing = [k for k,p in SOURCES.items() if not p.is_file()]
    if missing and not permitir_parcial:
        raise RuntimeError('Faltam fontes obrigatórias no release completo: '+', '.join(missing)
                           + '. Executa os extratores ou usa --permitir-parcial para um ensaio.')
    if not inputs:
        raise RuntimeError('Não existe nenhuma fonte processada')
    if (release/'train.jsonl.gz').exists():
        raise FileExistsError('Release já construída; não sobrescrever: '+str(release))
    result = {'missing_sources':missing, 'partial':bool(missing), 'release':str(release)}
    result['merge'] = merge(release, inputs)
    result['tokenizer'] = tokenizer_novo(release/'train.jsonl.gz',
                                       release/'tokenizer', vocab_size)
    try:
        from tokenizers import Tokenizer
    except ImportError as exc:
        raise RuntimeError('Instala tokenizers: pip install tokenizers') from exc
    real_tokenizer = Tokenizer.from_file(str(release/'tokenizer/tokenizer.json'))
    result['equilibrio'] = equilibrar(release/'train.jsonl.gz',
        release/'validation.jsonl.gz',real_tokenizer,release/'equilibrado')
    bins = {}
    for split in ('train','validation'):
        bins[split] = codificar(release / 'equilibrado' / (split+'.jsonl.gz'),
            release/'tokenizer/tokenizer.json',release/'bin'/(split+'.bin'))
    (release/'bin/pack_report.json').write_text(json.dumps(bins,ensure_ascii=False,indent=2), encoding='utf-8')
    result['pack'] = {s:{'tokens':bins[s]['tokens'],'documents':bins[s]['documents']}
                      for s in ('train','validation')}
    result['auditoria'] = auditar_pretrain(release/'equilibrado/train.jsonl.gz',
                         release/'equilibrado/validation.jsonl.gz',release/'auditoria_report.json',
                         pack_report=release/'bin/pack_report.json')
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='cmd',required=True)
    s=sub.add_parser('estado'); s.add_argument('--release',type=Path,default=ROOT/'release/v1')
    s=sub.add_parser('finalizar-geral');s.add_argument('--release',type=Path,default=ROOT/'release/v1')
    s.add_argument('--permitir-parcial',action='store_true');s.add_argument('--vocab-size',type=int,default=8192)
    s=sub.add_parser('preparar-qa');s.add_argument('--out',type=Path,default=ROOT/'release/v1/qa')
    a=p.parse_args(argv)
    if a.cmd=='estado': result=plano(a.release)
    elif a.cmd=='preparar-qa': result=preparar_qa(ROOT/'processed',a.out)
    else: result=finalizar_geral(a.release,a.permitir_parcial,a.vocab_size)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__': main()