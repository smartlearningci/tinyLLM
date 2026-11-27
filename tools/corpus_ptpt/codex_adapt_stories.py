#!/usr/bin/env python3
"""Adapta historias infantis PT-BR para PT-PT com Codex CLI (login ChatGPT).

Reutiliza a mesma arquitectura de tools/recipe_intents/codex_generate_intents.py:
JSON schema, prompts curtos, lotes, trabalhadores, eventos, metricas, retoma,
recuperacao de eventos e deteccao de plafond. Nunca usa uma API key.

Nao substitui revisao humana: o resultado tem status=pending_audit e deve
passar por historias_ptpt.py auditar/amostrar/publicar antes de entrar no treino.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from threading import Event
import time

SCHEMA = Path(__file__).with_name('codex_stories.schema.json')
DEFAULT_TINY = Path('dados/corpus_ptpt/historias/raw/tinystories.jsonl.gz')
DEFAULT_BOAKPE = Path('dados/corpus_ptpt/historias/raw/historinhas.jsonl.gz')
DEFAULT_QUEUE = Path('dados/corpus_ptpt/historias/codex/fila_v1.jsonl')
DEFAULT_RUN = Path('dados/corpus_ptpt/historias/codex/producao_v1')
PROMPT_VERSION = 'codex-ptpt-stories-simple-v1'
QUOTA_ERRORS = ('usage limit', 'usage cap', 'quota exceeded', 'rate limit exceeded',
                'rate_limit_exceeded', 'too many requests', 'usage_limit_reached',
                'weekly usage', 'limit reached')


def digest_bytes(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def digest_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def save_json_atomic(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.partial')
    if tmp.exists():
        raise FileExistsError('Existe ficheiro parcial antigo: ' + str(tmp))
    try:
        with tmp.open('x', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def ler_gzip(path: Path):
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        for n, line in enumerate(f, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except ValueError as exc:
                    raise ValueError(f'JSON invalido em {path}, linha {n}') from exc


def preparar(tiny: Path, boakpe: Path, queue: Path, pilot: int = 50):
    """Cria uma fila imutavel com amostra piloto diversa e restantes historias.

    SQLite evita carregar ~180 mil narrativas em RAM. Primeiras 50 historias
    foram selecionadas deterministicamente de todo o universo (30/20).
    """
    if pilot != 50:
        raise ValueError('O piloto PT-PT foi definido como 50 historias (30 Tiny + 20 Boakpe).')
    if queue.exists() or queue.with_suffix('.manifest.json').exists():
        raise FileExistsError('Fila ou manifesto ja existe; nao vou substituir uma fila em producao.')
    for path in (tiny, boakpe):
        if not path.is_file():
            raise FileNotFoundError(path)
    queue.parent.mkdir(parents=True, exist_ok=True)
    staging = queue.with_name(queue.name + '.staging.sqlite')
    parcial = queue.with_name(queue.name + '.partial')
    if staging.exists() or parcial.exists():
        raise FileExistsError('Restos de preparacao anterior: verificar ficheiros .staging.sqlite/.partial.')
    counter = Counter()
    db = sqlite3.connect(staging)
    try:
        db.execute('CREATE TABLE docs (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE, '
                   'sha TEXT UNIQUE, source TEXT NOT NULL, score INTEGER, record TEXT NOT NULL)')
        for source, path in (('tinystories', tiny), ('historinhas', boakpe)):
            for row in ler_gzip(path):
                counter['lidas_' + source] += 1
                if row.get('source') != source or row.get('lang_original') != 'pt-BR':
                    raise ValueError(f'Origem/lingua inesperadas em {path}: {row.get("source")}, {row.get("lang_original")}')
                texto = row.get('text_original', '')
                if not isinstance(texto, str) or not texto.strip():
                    counter['vazias'] += 1
                    continue
                sha = digest_text(texto)
                if sha != row.get('sha_original'):
                    raise ValueError('Hash de historia original divergente: ' + str(row.get('id')))
                rid = row['id']
                score = int.from_bytes(hashlib.sha256((PROMPT_VERSION + '|' + rid).encode()).digest()[:7], 'big')
                try:
                    db.execute('INSERT INTO docs(id,sha,source,score,record) VALUES(?,?,?,?,?)',
                               (rid, sha, source, score, json.dumps(row, ensure_ascii=False)))
                    counter['unicas_' + source] += 1
                except sqlite3.IntegrityError:
                    counter['duplicadas_entre_ou_dentro_fontes'] += 1
                if counter['lidas_' + source] % 1000 == 0:
                    db.commit()
            db.commit()
        db.execute('CREATE INDEX by_source_score ON docs(source,score)')
        selected = {}
        for source, n in (('tinystories', 30), ('historinhas', 20)):
            cur = db.execute('SELECT id,record FROM docs WHERE source=? ORDER BY score LIMIT ?', (source,n))
            selected[source] = [(rid, json.loads(txt)) for rid, txt in cur]
            if len(selected[source]) != n:
                raise RuntimeError(f'Fonte {source}: so {len(selected[source])} historias para o piloto.')
        seen_pilot = {rid for values in selected.values() for rid, _ in values}
        hashes = hashlib.sha256()
        total = 0
        def put(f, row):
            nonlocal total
            line = (json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')
            f.write(line)
            hashes.update(line.encode('utf-8'))
            total += 1
        with parcial.open('x', encoding='utf-8') as out:
            # Primeiro 50, em rondas de 3 Tiny + 2 Boakpe.
            for i in range(10):
                for _, item in selected['tinystories'][i*3:i*3+3]:
                    put(out, item)
                for _, item in selected['historinhas'][i*2:i*2+2]:
                    put(out, item)
            # Depois alternar fontes 2:1, sempre mantendo a ordem estavel.
            it_t = iter(db.execute('SELECT id,record FROM docs WHERE source=? ORDER BY seq', ('tinystories',)))
            it_b = iter(db.execute('SELECT id,record FROM docs WHERE source=? ORDER BY seq', ('historinhas',)))
            exhausted = {'tinystories': False, 'historinhas': False}
            while not all(exhausted.values()):
                for source, it, number in (('tinystories', it_t, 2), ('historinhas', it_b, 1)):
                    for _ in range(number):
                        try:
                            rid, txt = next(it)
                        except StopIteration:
                            exhausted[source] = True
                            break
                        if rid not in seen_pilot:
                            put(out, json.loads(txt))
        manifest = {
            'version': PROMPT_VERSION, 'count': total, 'pilot': 50,
            'pilot_by_source': {'tinystories': 30, 'historinhas': 20},
            'queue_sha256': hashes.hexdigest(),
            'sources': {str(p): digest_bytes(p) for p in (tiny, boakpe)},
            'counts': dict(counter),
            'note': 'Fila imutavel; 50 primeiras aleatorias deterministicas. PT-BR apenas staging.'
        }
        save_json_atomic(queue.with_suffix('.manifest.json'), manifest)
        os.replace(parcial, queue)
        return manifest
    finally:
        db.close()
        staging.unlink(missing_ok=True)


def load_manifest(queue: Path):
    if not queue.is_file():
        raise FileNotFoundError('Fila em falta: ' + str(queue))
    manifest_path = queue.with_suffix('.manifest.json')
    meta = json.loads(manifest_path.read_text(encoding='utf-8'))
    if digest_bytes(queue) != meta['queue_sha256']:
        raise ValueError('Fila alterada depois de preparada! Restaurar a original ou criar outra versao.')
    return meta


def batches(queue: Path, total: int, batch_size: int):
    """Lotes de tamanho fixo: o piloto 50 e divisivel por 10 para retoma."""
    with queue.open(encoding='utf-8') as f:
        batch, i = [], 0
        for line in f:
            if i >= total:
                break
            row = json.loads(line)
            batch.append(row)
            i += 1
            if len(batch) == batch_size:
                yield (i // batch_size - 1), batch
                batch = []
        if i != total:
            raise ValueError('Fila mais curta que contagem no manifesto')
        if batch:
            yield total // batch_size, batch


def batch_digest(batch):
    return digest_text(json.dumps([(r['id'], r['sha_original']) for r in batch],
                                  ensure_ascii=False, separators=(',', ':')))


def prompt(batch):
    """Prompt intencionalmente simples, sem acrescentar factos."""
    return ("Reescreve cada história infantil em português de Portugal (PT-PT). "
            "Mantém o enredo, as personagens, a simplicidade e aproximadamente o tamanho. "
            "Corrige vocabulário e construções brasileiras. Não resumas nem inventes. "
            "Devolve apenas JSON com responses (id, text_ptpt), mesmos IDs.\n"
            "HISTÓRIAS:\n" +
            json.dumps([{'id': x['id'], 'texto': x['text_original']} for x in batch],
                       ensure_ascii=False, separators=(',', ':')))


def validate_response(data, batch):
    if not isinstance(data, dict) or set(data) != {'responses'}:
        raise ValueError('JSON de resposta precisa de uma unica chave responses.')
    items = data['responses']
    if not isinstance(items, list) or len(items) != len(batch):
        raise ValueError('Quantidade de historias convertidas nao coincide com o lote.')
    expected = {x['id'] for x in batch}
    received = set()
    out = {}
    for item in items:
        if not isinstance(item, dict) or set(item) != {'id', 'text_ptpt'}:
            raise ValueError('Cada resposta exige so id e text_ptpt.')
        rid, txt = item['id'], item['text_ptpt']
        if not isinstance(rid, str) or rid not in expected or rid in received:
            raise ValueError('ID incorreto ou repetido na resposta.')
        if not isinstance(txt, str) or not txt.strip():
            raise ValueError('Historia convertida vazia.')
        received.add(rid)
        out[rid] = txt.strip()
    if received != expected:
        raise ValueError('Faltam historias do lote.')
    return out


def tokens_from_events(text):
    usage = {}
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'turn.completed':
            usage = event.get('usage') or {}
    return {'input_tokens': int(usage.get('input_tokens') or 0),
            'output_tokens': int(usage.get('output_tokens') or 0)}


def config_path(out: Path):
    return out / 'run_config.json'


def run_config(queue: Path, out: Path, meta: dict, args):
    cfg = {'queue_sha256': meta['queue_sha256'], 'batch_size': args.batch_size,
           'model': args.model, 'reasoning': args.reasoning,
           'prompt_version': PROMPT_VERSION}
    cp = config_path(out)
    if cp.exists():
        existing = json.loads(cp.read_text(encoding='utf-8'))
        if existing != cfg:
            raise ValueError('Fila/modelo/lotes mudaram! Usa nova pasta --out para outra experiencia.')
    else:
        save_json_atomic(cp, cfg)
    return cfg


def codex_call(index: int, batch: list[dict], args, cfg: dict, stop: Event):
    folder = args.out / 'batches'
    folder.mkdir(parents=True, exist_ok=True)
    prefix = f'batch_{index:06d}'
    final = folder / (prefix + '.json')
    events = folder / (prefix + '.events.jsonl')
    error = folder / (prefix + '.error.txt')
    if final.exists():
        existing = json.loads(final.read_text(encoding='utf-8'))
        if existing.get('digest') != batch_digest(batch) or existing.get('config') != cfg:
            raise ValueError(f'{prefix}: ficheiro de lote pertence a outra experiencia!')
        validate_response({'responses': existing['responses']}, batch)
        return 'skipped', prefix
    if stop.is_set():
        return 'paused', prefix
    if events.exists() or error.exists():
        if not args.retry_errors:
            return 'needs_review', prefix
        # Preservar historico antes de tentar outra vez.
        for old in (events, error):
            if old.exists():
                number = 1
                while old.with_name(prefix + f'.attempt_{number:03d}.' + old.name.split(prefix+'.', 1)[-1]).exists():
                    number += 1
                old.rename(old.with_name(prefix + f'.attempt_{number:03d}.' + old.name.split(prefix+'.', 1)[-1]))
    with tempfile.TemporaryDirectory(prefix='tiny-codex-ptpt-') as tmpdir:
        outfile = Path(tmpdir) / 'response.json'
        command = [args.codex, '--ask-for-approval', 'never', '-c',
                   f'model_reasoning_effort={args.reasoning}', 'exec',
                   '--sandbox', 'read-only', '--skip-git-repo-check',
                   '--output-schema', str(SCHEMA.resolve()),
                   '--json', '-o', str(outfile), '--model', args.model, '-']
        try:
            start = time.monotonic()
            result = subprocess.run(command, input=prompt(batch), capture_output=True,
                                    text=True, timeout=args.timeout, cwd=tmpdir)
            events.write_text(result.stdout, encoding='utf-8')
            usage = tokens_from_events(result.stdout)
            errors_text = (result.stdout + result.stderr).casefold()
            if any(k in errors_text for k in QUOTA_ERRORS):
                stop.set()
                raise RuntimeError('Limite de utilizacao Codex: suspender novos lotes.')
            if result.returncode or not outfile.is_file():
                raise RuntimeError(f'Codex exit={result.returncode}: {result.stderr[-300:]}')
            output = json.loads(outfile.read_text(encoding='utf-8'))
            adapted = validate_response(output, batch)
            record = {'batch': index, 'digest': batch_digest(batch), 'config': cfg,
                      'usage': usage, 'elapsed_seconds': round(time.monotonic()-start, 2),
                      'quality_status': 'codex_unverified',
                      'responses': [{'id': row['id'], 'text_ptpt': adapted[row['id']]}
                                    for row in batch]}
            save_json_atomic(final, record)
            if error.exists():
                error.unlink()
            return 'ok', prefix
        except Exception as exc:
            error.write_text(str(exc)[:1000], encoding='utf-8')
            return 'error', prefix


def recover_events(args, queue: Path, total: int, cfg: dict):
    folder = args.out / 'batches'
    recovered = 0
    for idx, batch in batches(queue, total, args.batch_size):
        dest = folder / f'batch_{idx:06d}.json'
        events = folder / f'batch_{idx:06d}.events.jsonl'
        if dest.exists() or not events.exists():
            continue
        last_response = None
        usage = tokens_from_events(events.read_text(encoding='utf-8'))
        for line in events.read_text(encoding='utf-8').splitlines():
            try:
                e = json.loads(line)
                item = e.get('item') or {}
                if e.get('type') == 'item.completed' and item.get('type') == 'agent_message':
                    candidate = json.loads(item.get('text', ''))
                    last_response = validate_response(candidate, batch)
            except (ValueError, KeyError, TypeError):
                continue
        if last_response is not None:
            record = {'batch': idx, 'digest': batch_digest(batch), 'config': cfg,
                      'quality_status': 'codex_unverified_recovered',
                      'usage': usage, 'elapsed_seconds': 0,
                      'responses': [{'id': row['id'], 'text_ptpt': last_response[row['id']]}
                                    for row in batch]}
            save_json_atomic(dest, record)
            recovered += 1
    return recovered


def summarize(out: Path, expected: int | None = None):
    path = out / 'batches'
    vals = Counter()
    for f in path.glob('batch_*.json'):
        j = json.loads(f.read_text(encoding='utf-8'))
        vals['lotes_validos'] += 1
        vals['historias_convertidas'] += len(j['responses'])
        vals['input_tokens'] += j.get('usage', {}).get('input_tokens', 0)
        vals['output_tokens'] += j.get('usage', {}).get('output_tokens', 0)
        vals['tempo_somado_segundos'] += j.get('elapsed_seconds', 0)
    vals['erros_sinalizados'] = len(list(path.glob('batch_*.error.txt')))
    if expected is not None:
        vals['lotes_previstos'] = expected
        vals['lotes_em_falta'] = max(0, expected - vals['lotes_validos'])
    return dict(vals)


def generate(args):
    meta = load_manifest(args.queue)
    if not (1 <= args.batch_size <= 10 and 1 <= args.workers <= 12):
        raise ValueError('batch-size 1..10 e workers 1..12')
    if args.limit < 0 or args.max_new_batches < 0:
        raise ValueError('limit e max-new-batches nao podem ser negativos')
    n = min(args.limit or meta['count'], meta['count'])
    if n < meta['count'] and n % args.batch_size:
        raise ValueError('Para continuar na mesma pasta, o piloto deve terminar em limite multiplo de batch-size')
    todo = math.ceil(n / args.batch_size)
    print(f'Fila={meta["count"]} historias; selecionadas={n}; lotes={todo}; workers={args.workers}.', flush=True)
    if args.dry_run:
        first = next(iter(batches(args.queue, n, args.batch_size)), None)
        print(prompt(first[1])[:4500] if first else 'Fila vazia')
        print('DRY RUN — nenhuma chamada Codex, nenhuma quota consumida.')
        return {}
    cfg = run_config(args.queue, args.out, meta, args)
    if args.recover_events:
        num = recover_events(args, args.queue, n, cfg)
        print('Lotes recuperados sem chamada Codex:', num)
        return summarize(args.out, todo)
    if os.getenv('OPENAI_API_KEY') or os.getenv('CODEX_API_KEY'):
        raise RuntimeError('Retira OPENAI_API_KEY/CODEX_API_KEY deste terminal: usar apenas codex login da conta ChatGPT.')
    if not shutil.which(args.codex):
        raise RuntimeError('Codex CLI nao encontrado no PATH.')
    login = subprocess.run([args.codex, 'login', 'status'], capture_output=True,
                           text=True, timeout=30)
    if login.returncode or 'chatgpt' not in (login.stdout+login.stderr).casefold():
        raise RuntimeError('Executa codex login com a tua conta ChatGPT e repete.')
    stop = Event()
    statistics = Counter()
    futures = set()
    novos = 0
    folder = args.out / 'batches'
    folder.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        def collect_one():
            ready, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in ready:
                futures.remove(future)
                status, name = future.result()
                statistics[status] += 1
                print(status, name, flush=True)
        for idx, batch in batches(args.queue, n, args.batch_size):
            if stop.is_set():
                break
            # Validar resultados antigos e nao repetir a despesa.
            dest = folder / f'batch_{idx:06d}.json'
            if dest.exists():
                saved = json.loads(dest.read_text(encoding='utf-8'))
                if saved.get('digest') != batch_digest(batch) or saved.get('config') != cfg:
                    raise ValueError('Lote existente incompativel: ' + str(dest))
                validate_response({'responses': saved['responses']}, batch)
                statistics['skipped'] += 1
                continue
            if (folder / f'batch_{idx:06d}.events.jsonl').exists() or (folder / f'batch_{idx:06d}.error.txt').exists():
                if not args.retry_errors:
                    statistics['needs_review'] += 1
                    continue
            if args.max_new_batches and novos >= args.max_new_batches:
                statistics['limite_de_lotes_novos'] += 1
                break
            while len(futures) >= args.workers:
                collect_one()
            if stop.is_set():
                break
            futures.add(pool.submit(codex_call, idx, batch, args, cfg, stop))
            novos += 1
        while futures:
            collect_one()
    report = summarize(args.out, todo)
    report['estatisticas_desta_execucao'] = dict(statistics)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if stop.is_set() or statistics.get('error') or statistics.get('needs_review'):
        raise RuntimeError('Execucao com lotes por rever/limite de utilizacao. Primeiro --recover-events; depois --retry-errors quando autorizado.')
    return report


def export(args):
    meta = load_manifest(args.queue)
    cfg = json.loads(config_path(args.run).read_text(encoding='utf-8'))
    if cfg['queue_sha256'] != meta['queue_sha256']:
        raise ValueError('Fila diferente da utilizada pelo Codex.')
    n = min(args.limit or meta['count'], meta['count'])
    size = int(cfg['batch_size'])
    if n < meta['count'] and n % size:
        raise ValueError('Exportar um limite multiplo de batch-size.')
    if args.out.exists():
        raise FileExistsError('Exportacao ja existe: ' + str(args.out))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    stage = args.out.with_name(args.out.name + '.partial')
    if stage.exists():
        raise FileExistsError(stage)
    selected = 0
    srcs = Counter()
    try:
        with gzip.open(stage, 'xt', encoding='utf-8') as out:
            for idx, batch in batches(args.queue, n, size):
                good = args.run / 'batches' / f'batch_{idx:06d}.json'
                if not good.is_file():
                    raise RuntimeError(f'Lote ainda nao concluido: {good}. Exportacao incompleta nao publicada.')
                js = json.loads(good.read_text(encoding='utf-8'))
                if js['digest'] != batch_digest(batch) or js['config'] != cfg:
                    raise ValueError(f'Lote {idx}: dados diferentes da fila original.')
                translated = validate_response({'responses': js['responses']}, batch)
                for row in batch:
                    t = translated[row['id']]
                    record = dict(row)
                    record.update({'text_ptpt': t, 'sha_ptpt': digest_text(t),
                                   'batch_id': f'codex:review:{selected // 1000:06d}',
                                   'model': cfg['model'],
                                   'prompt_version': PROMPT_VERSION,
                                   'status': 'pending_audit', 'error': '',
                                   'teacher_status': 'codex_unverified'})
                    out.write(json.dumps(record, ensure_ascii=False)+'\n')
                    selected += 1
                    srcs[row['source']] += 1
        os.replace(stage, args.out)
    finally:
        stage.unlink(missing_ok=True)
    return {'ficheiro': str(args.out), 'convertidas': selected,
            'origens': dict(srcs), 'estado': 'pending_audit',
            'nota': 'Nao e treino aprovado: executar auditar, amostrar e revisar.'}


def cli(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='comando', required=True)
    s = sub.add_parser('preparar', help='Fila imutavel a partir de TinyStories e Boakpe')
    s.add_argument('--tinystories', type=Path, default=DEFAULT_TINY)
    s.add_argument('--historinhas', type=Path, default=DEFAULT_BOAKPE)
    s.add_argument('--queue', type=Path, default=DEFAULT_QUEUE)
    g = sub.add_parser('gerar', help='Executar Codex por lotes, com retoma e plafond')
    g.add_argument('--queue', type=Path, default=DEFAULT_QUEUE)
    g.add_argument('--out', type=Path, default=DEFAULT_RUN)
    g.add_argument('--limit', type=int, default=50, help='50 = piloto; 0 = TODAS (mesma pasta)')
    g.add_argument('--batch-size', type=int, default=10)
    g.add_argument('--workers', type=int, default=8)
    g.add_argument('--model', default='gpt-6-luna', help='Modelo usado anteriormente no Codex CLI; alterar se indisponivel')
    g.add_argument('--reasoning', choices=['low', 'medium', 'high'], default='low')
    g.add_argument('--timeout', type=int, default=600)
    g.add_argument('--codex', default='codex')
    g.add_argument('--max-new-batches', type=int, default=1000,
                   help='Maximo de chamadas novas nesta execucao; 0 = sem teto local')
    g.add_argument('--dry-run', action='store_true')
    g.add_argument('--recover-events', action='store_true')
    g.add_argument('--retry-errors', action='store_true')
    e = sub.add_parser('exportar', help='Traduzidos para o formato de auditoria existente')
    e.add_argument('--queue', type=Path, default=DEFAULT_QUEUE)
    e.add_argument('--run', type=Path, default=DEFAULT_RUN)
    e.add_argument('--limit', type=int, default=50)
    e.add_argument('--out', type=Path, required=True)
    c = sub.add_parser('estado', help='Contar lotes e tokens ja registados')
    c.add_argument('--run', type=Path, default=DEFAULT_RUN)
    c.add_argument('--queue', type=Path, default=DEFAULT_QUEUE)
    args = p.parse_args(argv)
    if args.comando == 'preparar':
        result = preparar(args.tinystories, args.historinhas, args.queue)
    elif args.comando == 'gerar':
        result = generate(args)
    elif args.comando == 'exportar':
        result = export(args)
    else:
        result = summarize(args.run)
        if args.queue.exists() and result.get('historias_convertidas', 0):
            meta = load_manifest(args.queue)
            n = result['historias_convertidas']
            full = meta['count']
            cfg = json.loads(config_path(args.run).read_text(encoding='utf-8'))
            result['projecao_linear_apenas_indicativa'] = {
                'historias_na_fila': full,
                'chamadas_previstas': math.ceil(full / cfg['batch_size']),
                'input_tokens_estimados': round(result['input_tokens'] * full / n),
                'output_tokens_estimados': round(result['output_tokens'] * full / n),
                'aviso': 'A quota Codex da subscricao nao equivale diretamente a tokens; '
                         'resultados e duracoes podem variar por tamanho das historias.'
            }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result

if __name__ == '__main__':
    cli()