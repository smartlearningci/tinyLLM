#!/usr/bin/env python3
"""Preparação reprodutível de um corpus de pré-treino PT-PT (Python >=3.10).

Fontes preservadas; os documentos preparados ficam em JSONL.gz. Só os modos
Bagaço2 e FairytaleQA precisam de ``pip install datasets``.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Iterable

ROOT = Path('dados/corpus_ptpt')
RE_TAG = re.compile(r'<[^>]*>')
RE_SPACE = re.compile(r'[ \t\r\f\v]+')
RE_WORD = re.compile(r'\w+', re.UNICODE)
RE_EXT = re.compile(r'<ext(?:\s|>)', re.I)
RE_END_EXT = re.compile(r'</ext\s*>', re.I)
VERSION = 'ptpt-corpus-1.0'


def normalizar(texto: str) -> str:
    """Ajusta espaços e caracteres invisíveis; não altera ortografia nem dialeto."""
    texto = unicodedata.normalize('NFC', str(texto)).replace('\ufeff', '')
    texto = re.sub(r'[\u200b-\u200d\u2060]', '', texto)
    texto = texto.replace('\xa0', ' ').replace('\r\n', '\n').replace('\r', '\n')
    return '\n'.join(RE_SPACE.sub(' ', linha).strip() for linha in texto.split('\n')).strip()


def aceitavel(texto: str, min_palavras: int = 35, max_chars: int = 250000) -> bool:
    if len(texto) > max_chars or len(texto) < 140:
        return False
    palavras = len(RE_WORD.findall(texto))
    if palavras < min_palavras:
        return False
    # Rejeita páginas dominadas por símbolos e texto ilegível.
    letras = sum(ch.isalpha() for ch in texto)
    return letras / max(1, len(texto)) > 0.45


def digest(texto: str) -> str:
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()


def escrever(f, reg: dict) -> None:
    f.write(json.dumps(reg, ensure_ascii=False, separators=(',', ':')) + '\n')


def abrir_saida(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f'O ficheiro já existe (não será substituído): {path}')
    return gzip.open(path, 'wt', encoding='utf-8', newline='\n')


def stats():
    return Counter(vistos=0, guardados=0, descartados=0, palavras=0)


def ingere_documentos(docs: Iterable[dict], saida: Path, fonte: str, min_palavras: int = 35,
                      limite_palavras: int = 0) -> dict:
    """Processa documentos em streaming; elimina duplicados exatos por conteúdo."""
    r = stats()
    vistos: set[str] = set()
    with abrir_saida(saida) as out:
        for doc in docs:
            r['vistos'] += 1
            texto = normalizar(doc.get('text', ''))
            if not aceitavel(texto, min_palavras) or (sha := digest(texto)) in vistos:
                r['descartados'] += 1
                continue
            vistos.add(sha)
            palavras = len(RE_WORD.findall(texto))
            escrever(out, {'id': str(doc.get('id') or fonte + ':' + sha[:20]),
                          'source': fonte, 'lang': 'pt-PT', 'text': texto,
                          'group': str(doc.get('group') or fonte + ':' + sha[:20]),
                          'words': palavras})
            r['guardados'] += 1
            r['palavras'] += palavras
            if limite_palavras > 0 and r['palavras'] >= limite_palavras:
                break
    return dict(r)


def _texto_cetem(fragmento: str) -> str:
    # O CETEMPúblico 1.7 é SGML; preservamos os limites de parágrafo.
    s = re.sub(r'</p\s*>', '\n', fragmento, flags=re.I)
    s = re.sub(r'</s\s*>', ' ', s, flags=re.I)
    s = RE_TAG.sub(' ', s)
    return normalizar(html.unescape(s))


def cetem_documentos(ficheiro: Path):
    """Itera sobre <ext>...</ext> do CETEMPúblico 1.7 sem extrair o .gz para disco.

    O ficheiro tem normalmente codificação de 8 bits; o descodificador tenta
    UTF-8 e usa Latin-1 se a linha não for UTF-8.
    """
    abrir = gzip.open if ficheiro.suffix == '.gz' else open
    dentro = False
    buffer: list[str] = []
    i = 0
    with abrir(ficheiro, 'rb') as stream:
        for linha in stream:
            try:
                s = linha.decode('utf-8')
            except UnicodeDecodeError:
                s = linha.decode('latin-1')
            # Uma linha pode, em teoria, conter início e fim da unidade.
            for segmento in re.split(r'(?=<ext(?:\s|>))|(?<=</ext>)', s, flags=re.I):
                if RE_EXT.search(segmento):
                    dentro, buffer = True, []
                if dentro:
                    buffer.append(segmento)
                if dentro and RE_END_EXT.search(segmento):
                    i += 1
                    texto = _texto_cetem(''.join(buffer))
                    yield {'id': f'cetem:{i}', 'text': texto}
                    dentro, buffer = False, []
    if dentro:
        raise ValueError('CETEMPúblico terminou dentro de um <ext> sem </ext> (ficheiro truncado?).')
    if i == 0:
        raise ValueError('Não foram encontrados extratos <ext> no CETEMPúblico.')


def bagaco_documentos(linhas: Iterable[dict], ptpt_min: float = .90, edu_min: int = 2):
    for r in linhas:
        if float(r.get('ptpt_score') or 0) < ptpt_min:
            continue
        if int(r.get('educational_score') or 0) < edu_min:
            continue
        texto = r.get('text') or ''
        if not isinstance(texto, str):
            continue
        yield {'id': 'bagaco:' + str(r.get('id') or digest(texto)[:20]), 'text': texto}


def iter_bagaco(config: str = 'all'):
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise RuntimeError('Instala a dependência: python3 -m pip install datasets') from exc
    kw = {'split': 'train', 'streaming': True}
    if config:
        kw['name'] = config
    return load_dataset('duarteocarmo/fineweb2-bagaco2', **kw)


def fairytale_dataset():
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise RuntimeError('Instala a dependência: python3 -m pip install datasets') from exc
    return load_dataset('benjleite/FairytaleQA-translated-ptPT')


def processar_fairytale(datasets: dict, pasta: Path) -> dict:
    """Guarda contextos únicos de treino e QA por split; nunca junta splits.

    story_section é um EXCERTO, não necessariamente uma história completa.
    O mesmo excerto ocorre em várias perguntas, por isso só entra uma vez.
    """
    resultados = {}
    for split in ('train', 'validation', 'test'):
        if split not in datasets:
            raise ValueError('FairytaleQA não tem o split obrigatório: ' + split)
        out_qa = pasta / f'fairytale_qa_{split}.jsonl.gz'
        out_text = pasta / f'fairytale_contextos_{split}.jsonl.gz'
        if out_qa.exists() or out_text.exists():
            raise FileExistsError('Já existem ficheiros FairytaleQA; usa uma pasta nova.')
        pares = 0
        contextos = 0
        hashes: set[str] = set()
        with abrir_saida(out_qa) as qo, abrir_saida(out_text) as tx:
            for row in datasets[split]:
                story = str(row.get('story_name') or '')
                context = normalizar(row.get('story_section') or '')
                question = normalizar(row.get('question') or '')
                answer = normalizar(row.get('answer') or '')
                if not context or not question or not answer or not story:
                    continue
                sh = digest(context)
                escrever(qo, {'source': 'fairytaleqa_ptpt', 'split': split, 'story': story,
                              'context_id': sh, 'context': context,
                              'question': question, 'answer': answer,
                              'attribute': row.get('attribute'),
                              'explicit_or_implicit': row.get('ex-or-im1', row.get('ex-or-im'))})
                pares += 1
                if sh not in hashes:
                    hashes.add(sh)
                    # Só os contextos TRAIN podem alimentar o pré-treino.
                    escrever(tx, {'id': 'fairytale:' + sh[:20], 'source': 'fairytaleqa_ptpt',
                                  'lang': 'pt-PT', 'split': split,
                                  'group': 'fairytale:' + story, 'text': context,
                                  'words': len(RE_WORD.findall(context))})
                    contextos += 1
        resultados[split] = {'perguntas': pares, 'contextos_unicos': contextos}
    return resultados


def txt_documentos(pasta: Path):
    for p in sorted(pasta.rglob('*.txt')):
        if not p.is_file():
            continue
        # Detecta BOM UTF-8; textos de fontes modernas deverão ser UTF-8.
        texto = p.read_text(encoding='utf-8-sig')
        yield {'id': 'texto:' + digest(str(p.relative_to(pasta)))[:20], 'text': texto}


def iter_jsonl_gz(ficheiro: Path):
    with gzip.open(ficheiro, 'rt', encoding='utf-8') as f:
        for linha in f:
            if linha.strip():
                yield json.loads(linha)


def merge(pasta: Path, entradas: list[Path], val_permille: int = 5) -> dict:
    """Merge global deduplicado exato com split determinístico por grupo.

    O split reservado do FairytaleQA não é incluído; apenas contextos TRAIN.
    """
    if not 1 <= val_permille <= 50:
        raise ValueError('val_permille deve estar entre 1 e 50.')
    train_path = pasta / 'train.jsonl.gz'
    val_path = pasta / 'validation.jsonl.gz'
    report_path = pasta / 'dataset_report.json'
    if any(p.exists() for p in (train_path, val_path, report_path)):
        raise FileExistsError('Já existe um resultado; usa outra pasta ou arquiva a versão anterior.')
    pasta.mkdir(parents=True, exist_ok=True)
    # Índice SQLite para não carregar milhões de hashes em memória.
    dbfile = pasta / '_seen.sqlite'
    if dbfile.exists():
        raise FileExistsError(dbfile)
    db = sqlite3.connect(dbfile)
    db.execute('CREATE TABLE seen (hash TEXT PRIMARY KEY)')
    res = {'version': VERSION, 'train': 0, 'validation': 0, 'discarded': 0,
           'sources': {}, 'words_train': 0, 'words_validation': 0,
           'note': 'Contagem de palavras; tokens apenas após treinar o tokenizer. Deduplicação exata, não semântica.'}
    try:
        with abrir_saida(train_path) as tr, abrir_saida(val_path) as va:
            for file in entradas:
                if not file.is_file():
                    raise FileNotFoundError(file)
                for row in iter_jsonl_gz(file):
                    source = str(row.get('source', ''))
                    if source == 'fairytaleqa_ptpt' and row.get('split') != 'train':
                        raise ValueError('Tentativa de misturar FairytaleQA validation/test no pré-treino: ' + str(file))
                    texto = normalizar(row.get('text', ''))
                    if not aceitavel(texto, min_palavras=20 if source == 'fairytaleqa_ptpt' else 35):
                        res['discarded'] += 1
                        continue
                    sha = digest(texto)
                    try:
                        db.execute('INSERT INTO seen VALUES (?)', (sha,))
                    except sqlite3.IntegrityError:
                        res['discarded'] += 1
                        continue
                    # Fairytale tem a sua própria divisão em histórias; só train vai a train.
                    grupo = str(row.get('group') or row.get('id') or sha)
                    h = int(hashlib.sha256(('ptpt-v1|' + grupo).encode()).hexdigest()[:8], 16)
                    split = ('train' if source == 'fairytaleqa_ptpt' else
                             ('validation' if h % 1000 < val_permille else 'train'))
                    palavras = len(RE_WORD.findall(texto))
                    reg = {'id': row['id'], 'source': source, 'lang': 'pt-PT', 'text': texto}
                    escrever(tr if split == 'train' else va, reg)
                    res[split] += 1
                    res['words_' + split] += palavras
                    res['sources'][source] = res['sources'].get(source, 0) + 1
                db.commit()
        report_path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        db.close()
        dbfile.unlink(missing_ok=True)
    return res


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='modo', required=True)
    cetem = sub.add_parser('cetem', help='Ler CETEMPublico1.7.gz localmente')
    cetem.add_argument('--input', type=Path, default=ROOT / 'raw/CETEMPublico1.7.gz')
    cetem.add_argument('--out', type=Path, default=ROOT / 'processed/cetem.jsonl.gz')
    bag = sub.add_parser('bagaco', help='Ler Bagaço2 em streaming do Hugging Face')
    bag.add_argument('--out', type=Path, default=ROOT / 'processed/bagaco.jsonl.gz')
    bag.add_argument('--config', default='all', help='Usar all para o corpus integral; sample é apenas uma amostra')
    bag.add_argument('--ptpt-min', type=float, default=.90)
    bag.add_argument('--edu-min', type=int, default=2)
    bag.add_argument('--palavras-alvo', type=int, default=120_000_000)
    fairy = sub.add_parser('fairytale', help='Transferir FairytaleQA ptPT, preservar splits')
    fairy.add_argument('--out-dir', type=Path, default=ROOT / 'processed')
    txt = sub.add_parser('textos', help='Converter documentos .txt adicionais para JSONL')
    txt.add_argument('--input-dir', type=Path, required=True)
    txt.add_argument('--source', required=True, help='Ex.: parlamint, eltec, adamastor')
    txt.add_argument('--out', type=Path, required=True)
    juntar = sub.add_parser('juntar', help='Gerar train/validation JSONL.gz e relatório')
    juntar.add_argument('--out-dir', type=Path, default=ROOT / 'release/v1')
    juntar.add_argument('--inputs', nargs='+', type=Path, required=True)
    juntar.add_argument('--val-permille', type=int, default=5)
    a = p.parse_args(argv)
    if a.modo == 'cetem':
        if not a.input.exists():
            p.error(f'Falta o ficheiro local: {a.input}')
        result = ingere_documentos(cetem_documentos(a.input), a.out, 'cetempublico')
    elif a.modo == 'bagaco':
        result = ingere_documentos(
            bagaco_documentos(iter_bagaco(a.config), a.ptpt_min, a.edu_min),
            a.out, 'bagaco2', limite_palavras=a.palavras_alvo)
    elif a.modo == 'fairytale':
        result = processar_fairytale(fairytale_dataset(), a.out_dir)
    elif a.modo == 'textos':
        result = ingere_documentos(txt_documentos(a.input_dir), a.out, a.source)
    else:
        result = merge(a.out_dir, a.inputs, a.val_permille)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()