#!/usr/bin/env python3
"""Rebalanceia corpus geral usando contagens REAIS de tokens e quotas de fonte.

Lê train/validation imutáveis já divididos por obra. Não acrescenta nem duplica
textos, não misturando FairytaleQA ou histórias adaptadas no geral.
"""
from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from pathlib import Path

from build_ptpt import iter_jsonl_gz, escrever

QUOTAS = {
    'bagaco2': 200_000_000,
    'cetempublico': 150_000_000,
    'parlamint_pt': 20_000_000,
    'narrativa': 30_000_000,
}


def grupo_source(source: str):
    return 'narrativa' if source in ('eltec_por','adamastor') else source


def contabilizar(arquivos, tokenizer):
    available = Counter()
    by_split = {s: Counter() for s in ('train','validation')}
    counts = Counter()
    for split, path in arquivos.items():
        for row in iter_jsonl_gz(path):
            if row.get('lang') != 'pt-PT':
                raise ValueError('Não é PT-PT: '+str(row.get('id')))
            group = grupo_source(row['source'])
            if group not in QUOTAS:
                raise ValueError('Fonte fora do corpus geral: '+row['source'])
            n = len(tokenizer.encode(row['text'], add_special_tokens=False).ids)+1
            by_split[split][group] += n
            available[group] += n
            counts[group] += 1
    return available, by_split, counts


def cotas_disponiveis(available: Counter, quotas=None):
    quotas = quotas or QUOTAS
    target = sum(quotas.values())
    allocation = {k:min(v,available[k]) for k,v in quotas.items()}
    deficit = target - sum(allocation.values())
    if deficit and available['bagaco2'] > allocation['bagaco2']:
        allocation['bagaco2'] += min(deficit, available['bagaco2']-allocation['bagaco2'])
    return allocation


def preparar(train: Path, validation: Path, tokenizer, out_dir: Path, quotas=None):
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError('A pasta equilibrada já existe: '+str(out_dir))
    if not train.is_file() or not validation.is_file():
        raise FileNotFoundError('Faltam train/validation brutos')
    quotas = quotas or QUOTAS
    available, per_split, docs = contabilizar({'train':train,'validation':validation},tokenizer)
    alloc = cotas_disponiveis(available, quotas)
    # Reservar parte de cada quota à validação, conforme fração real existente.
    caps = {'train':{},'validation':{}}
    for source, quota in alloc.items():
        total = available[source]
        n_val = round(quota * per_split['validation'][source]/total) if total else 0
        caps['validation'][source] = min(n_val,per_split['validation'][source])
        caps['train'][source] = quota - caps['validation'][source]
    out_dir.mkdir(parents=True,exist_ok=True)
    result = {'contagem_disponivel_tokens':dict(available), 'limites_tokens':dict(alloc),
              'diferenca_meta':sum(quotas.values())-sum(alloc.values()),
              'metas_originais':dict(quotas), 'documentos_disponiveis':dict(docs),
              'por_split':{}}
    for split, src in (('train',train),('validation',validation)):
        count, accepted, omitted = Counter(), Counter(), Counter()
        with gzip.open(out_dir/(split+'.jsonl.gz'),'xt',encoding='utf-8') as dst:
            for row in iter_jsonl_gz(src):
                group = grupo_source(row['source'])
                n = len(tokenizer.encode(row['text'], add_special_tokens=False).ids)+1
                if count[group]+n <= caps[split][group]:
                    escrever(dst,row)
                    count[group]+=n
                    accepted[group]+=1
                else:
                    omitted[group]+=1
        result['por_split'][split]={'tokens_por_fonte':dict(count),
                                   'documentos_por_fonte':dict(accepted),
                                   'descartados_por_quota':dict(omitted)}
    tokens_final = sum(sum(v['tokens_por_fonte'].values()) for v in result['por_split'].values())
    result['total_tokens'] = tokens_final
    result['meta_tokens'] = sum(quotas.values())
    result['meta_atingida'] = tokens_final >= sum(quotas.values())
    result['nota']='Sem repetição para cumprir quota. Por documento inteiro pode haver pequena diferença para o teto.'
    (out_dir/'quota_report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--train', type=Path, required=True)
    p.add_argument('--validation', type=Path, required=True)
    p.add_argument('--tokenizer', type=Path, required=True)
    p.add_argument('--out-dir',type=Path,required=True)
    a=p.parse_args(argv)
    try:
        from tokenizers import Tokenizer
    except ImportError as e:
        raise RuntimeError('Instala: pip install tokenizers') from e
    t=Tokenizer.from_file(str(a.tokenizer))
    print(json.dumps(preparar(a.train,a.validation,t,a.out_dir),ensure_ascii=False,indent=2))

if __name__=='__main__':main()