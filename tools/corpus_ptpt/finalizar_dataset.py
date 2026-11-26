#!/usr/bin/env python3
"""QA, inventário, detetor de contaminação e empacotamento do TinySLM PT-PT.

Não mascara metas não atingidas. Não carrega corpus completo em RAM.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
import zipfile
from collections import Counter
from pathlib import Path

from build_ptpt import iter_jsonl_gz, digest


def sha256_file(path: Path, block=1024*1024):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(block), b''):
            h.update(b)
    return h.hexdigest()


def auditar_pretrain(train: Path, validation: Path, report: Path, *, meta_tokens=400_000_000,
                     pack_report: Path | None = None):
    if report.exists():
        raise FileExistsError(report)
    if not train.is_file() or not validation.is_file():
        raise FileNotFoundError('É obrigatório ter train e validation')
    report.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(report.parent / '_audit.sqlite')
    db.execute('CREATE TABLE hashes (h TEXT PRIMARY KEY, split TEXT)')
    db.execute('CREATE TABLE groups_seen (group_id TEXT PRIMARY KEY, split TEXT)')
    counts = Counter()
    sources = Counter()
    try:
        for split, src in (('train', train), ('validation', validation)):
            for r in iter_jsonl_gz(src):
                counts[split] += 1
                source = str(r.get('source',''))
                sources[source] += 1
                if r.get('lang') != 'pt-PT':
                    counts['lang_incorrecta'] += 1
                if 'ptbr' in source.lower() and 'adaptado_ptpt' not in source.lower():
                    counts['ptbr_cru'] += 1
                if source == 'fairytaleqa_ptpt':
                    counts['fairytale_no_pretreino'] += 1
                content = str(r.get('text') or '')
                if not content:
                    counts['vazios'] += 1
                h = digest(content)
                try:
                    db.execute('INSERT INTO hashes VALUES(?,?)', (h, split))
                except sqlite3.IntegrityError:
                    counts['documento_duplicado'] += 1
                group = str(r.get('group') or r.get('id') or h)
                found = db.execute('SELECT split FROM groups_seen WHERE group_id=?', (group,)).fetchone()
                if found and found[0] != split:
                    counts['fuga_grupo_train_validation'] += 1
                if not found:
                    db.execute('INSERT INTO groups_seen VALUES (?,?)', (group, split))
            db.commit()
    finally:
        db.close()
        (report.parent / '_audit.sqlite').unlink(missing_ok=True)
    actual_tokens = None
    if pack_report:
        j = json.loads(pack_report.read_text(encoding='utf-8'))
        actual_tokens = int(j['train']['tokens']) + int(j['validation']['tokens'])
    blockers = {k: counts[k] for k in ('lang_incorrecta', 'ptbr_cru', 'fairytale_no_pretreino',
                'vazios', 'documento_duplicado', 'fuga_grupo_train_validation') if counts[k]}
    data = {'status': 'bloqueado' if blockers else 'passou_verificacoes_estruturais',
            'bloqueios': blockers, 'documentos': {k: counts[k] for k in ('train','validation')},
            'fontes': dict(sources), 'sha256': {'train': sha256_file(train),
            'validation': sha256_file(validation)}, 'meta_tokens': meta_tokens,
            'tokens_reais': actual_tokens,
            'quota_atingida': None if actual_tokens is None else actual_tokens >= meta_tokens,
            'notas': [
              'Esta auditoria deteta duplicados exatos e fugas por grupo; não deteta paráfrases.',
              'Uma etiqueta pt-PT não prova que a variante esteja correta.',
              'A licença e a qualidade linguística de amostras precisam de verificação humana.'
            ]}
    report.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return data


def preparar_qa(pasta: Path, out: Path):
    """Três splits supervisionados separados, sem converter test em treino."""
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(out)
    out.mkdir(parents=True, exist_ok=True)
    result = {}
    for split in ('train', 'validation', 'test'):
        src = pasta / f'fairytale_qa_{split}.jsonl.gz'
        if not src.is_file():
            raise FileNotFoundError(src)
        n = 0
        f = out / f'qa_{split}.jsonl.gz'
        with gzip.open(f, 'xt', encoding='utf-8') as dst:
            for r in iter_jsonl_gz(src):
                ctx = r['context'].strip()
                que = r['question'].strip()
                answer = r['answer'].strip()
                if not (ctx and que and answer):
                    continue
                row = {'source': 'fairytaleqa_ptpt', 'split': split,
                       'story': r['story'], 'messages': [
                           {'role': 'system', 'content': 'Responde em português de Portugal apenas com base no excerto. Se a informação não existir, diz que não é possível determinar.'},
                           {'role': 'user', 'content': f'Excerto:\n{ctx}\n\nPergunta: {que}'},
                           {'role': 'assistant', 'content': answer}]}
                dst.write(json.dumps(row, ensure_ascii=False, separators=(',',':'))+'\n')
                n += 1
        result[split] = {'count': n, 'sha256': sha256_file(f), 'file': str(f)}
    (out / 'qa_report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def exportar_kaggle(release: Path, output: Path, *, include_qa=False, private_ack=False):
    """Exporta só BIN/tokenizer/metadata; nunca inclui textos originais."""
    if not private_ack:
        raise ValueError('Confirma que o destino é privado e que validaste licenças com --destino-privado-confirmado')
    if output.exists():
        raise FileExistsError(output)
    rels = ['bin/train.bin','bin/validation.bin','bin/pack_report.json',
            'tokenizer/tokenizer.json','tokenizer/tokenizer_config_ptpt.json']
    if include_qa:
        rels += ['qa/qa_train.jsonl.gz','qa/qa_validation.jsonl.gz','qa/qa_report.json']
    for rel in rels:
        if not (release / rel).is_file():
            raise FileNotFoundError('Em falta para Kaggle: ' + str(release / rel))
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'private_dataset': True, 'included': {rel:sha256_file(release/rel) for rel in rels},
              'instruction': 'Carregar como dataset PRIVADO no Kaggle. Licenças devem ser validadas pelo responsável.'}
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_STORED, allowZip64=True) as z:
        for rel in rels:
            z.write(release/rel, rel)
        z.writestr('MANIFEST.json', json.dumps(report, ensure_ascii=False, indent=2))
    return dict(report, zip=str(output), bytes=output.stat().st_size)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    s = p.add_subparsers(dest='cmd', required=True)
    a = s.add_parser('auditar')
    a.add_argument('--train', type=Path, required=True)
    a.add_argument('--validation', type=Path, required=True)
    a.add_argument('--report', type=Path, required=True)
    a.add_argument('--pack-report', type=Path)
    a.add_argument('--meta-tokens', type=int, default=400_000_000)
    a = s.add_parser('qa')
    a.add_argument('--fairytale-dir', type=Path, required=True)
    a.add_argument('--out', type=Path, required=True)
    a = s.add_parser('kaggle')
    a.add_argument('--release', type=Path, required=True)
    a.add_argument('--out', type=Path, required=True)
    a.add_argument('--include-qa', action='store_true')
    a.add_argument('--destino-privado-confirmado', action='store_true')
    q = p.parse_args(argv)
    if q.cmd == 'auditar':
        result = auditar_pretrain(q.train, q.validation, q.report,
                   meta_tokens=q.meta_tokens, pack_report=q.pack_report)
    elif q.cmd == 'qa':
        result = preparar_qa(q.fairytale_dir, q.out)
    else:
        result = exportar_kaggle(q.release, q.out, include_qa=q.include_qa,
                       private_ack=q.destino_privado_confirmado)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()