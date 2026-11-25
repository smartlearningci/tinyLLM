#!/usr/bin/env python3
"""Treina tokenizer PT-PT e codifica JSONL.gz em ficheiros binários para Kaggle.

Requer: pip install tokenizers  (a preparação do corpus anterior não requer).
Não inicia o treino de pesos; cria os inputs reproduzíveis.
"""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
import sys
from pathlib import Path

from build_ptpt import iter_jsonl_gz

ESPECIAIS = ['<pad>', '<eos>', '<unk>', '<bos>']


def tokenizer_novo(train: Path, pasta: Path, vocab_size: int = 8192):
    try:
        from tokenizers import Tokenizer, models, pre_tokenizers, decoders, trainers
    except ImportError as exc:
        raise RuntimeError('Instala: python3 -m pip install tokenizers') from exc
    if pasta.exists() and any(pasta.iterdir()):
        raise FileExistsError('Já existe tokenizer nesta pasta: ' + str(pasta))
    pasta.mkdir(parents=True, exist_ok=True)
    t = Tokenizer(models.BPE(unk_token='<unk>'))
    t.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    t.decoder = decoders.ByteLevel()
    treino = trainers.BpeTrainer(vocab_size=vocab_size, min_frequency=3, special_tokens=ESPECIAIS,
                                initial_alphabet=pre_tokenizers.ByteLevel.alphabet())
    t.train_from_iterator((r['text'] for r in iter_jsonl_gz(train)), trainer=treino)
    arquivo = pasta / 'tokenizer.json'
    t.save(str(arquivo))
    meta = {'vocab_size': t.get_vocab_size(), 'eos_id': t.token_to_id('<eos>'),
            'pad_id': t.token_to_id('<pad>'), 'unk_id': t.token_to_id('<unk>'),
            'source': str(train), 'type': 'byte_level_bpe'}
    (pasta / 'tokenizer_config_ptpt.json').write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    return meta


def codificar(dados: Path, tokenizer: Path, saida: Path):
    try:
        from tokenizers import Tokenizer
    except ImportError as exc:
        raise RuntimeError('Instala: python3 -m pip install tokenizers') from exc
    if saida.exists():
        raise FileExistsError('Não substituo fich. já existente: ' + str(saida))
    t = Tokenizer.from_file(str(tokenizer))
    if t.get_vocab_size() > 65535:
        raise ValueError('O vocabulário não cabe em uint16.')
    eos = t.token_to_id('<eos>')
    if eos is None:
        raise ValueError('Token EOS em falta.')
    saida.parent.mkdir(parents=True, exist_ok=True)
    n_docs = 0
    n_tokens = 0
    h = hashlib.sha256()
    with saida.open('xb') as f:
        for reg in iter_jsonl_gz(dados):
            ids = t.encode(reg['text'], add_special_tokens=False).ids + [eos]
            a = array('H', ids)
            if sys.byteorder != 'little':
                a.byteswap()
            b = a.tobytes()
            f.write(b)
            h.update(b)
            n_tokens += len(ids)
            n_docs += 1
    return {'documents': n_docs, 'tokens': n_tokens, 'dtype': 'uint16-le',
            'sha256': h.hexdigest(), 'binary': str(saida), 'tokenizer': str(tokenizer)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='op', required=True)
    tk = sub.add_parser('tokenizer')
    tk.add_argument('--train', type=Path, default=Path('dados/corpus_ptpt/release/v1/train.jsonl.gz'))
    tk.add_argument('--out', type=Path, default=Path('dados/corpus_ptpt/release/v1/tokenizer'))
    tk.add_argument('--vocab-size', type=int, default=8192)
    pack = sub.add_parser('pack')
    pack.add_argument('--tokenizer', type=Path, default=Path('dados/corpus_ptpt/release/v1/tokenizer/tokenizer.json'))
    pack.add_argument('--train', type=Path, default=Path('dados/corpus_ptpt/release/v1/train.jsonl.gz'))
    pack.add_argument('--validation', type=Path, default=Path('dados/corpus_ptpt/release/v1/validation.jsonl.gz'))
    pack.add_argument('--out-dir', type=Path, default=Path('dados/corpus_ptpt/release/v1/bin'))
    a = p.parse_args()
    if a.op == 'tokenizer':
        result = tokenizer_novo(a.train, a.out, a.vocab_size)
    else:
        if a.out_dir.exists() and any(a.out_dir.iterdir()):
            raise FileExistsError('A pasta dos binários já contém dados; usa nova versão.')
        result = {}
        for label, path in (('train', a.train), ('validation', a.validation)):
            result[label] = codificar(path, a.tokenizer, a.out_dir / (label + '.bin'))
        (a.out_dir / 'pack_report.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()