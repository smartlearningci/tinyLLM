"""Build a resumable intent-labelled dataset via local authenticated Codex CLI.

Run from a PC with `codex login`; no OpenAI API key is required.
Never silently promote teacher-generated labels to human-verified labels.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

SCHEMA = Path(__file__).with_name('codex_intents.schema.json')
ALLOWED = {'ingredients': {'list', 'check'}, 'quantity': {'get'},
           'steps': {'next', 'explain', 'rewrite'},
           'constraints': {'check', 'substitute'}, 'unknown': {'unknown'}}
QUOTA_ERRORS = ('usage limit', 'usage cap', 'quota exceeded', 'rate limit exceeded',
                'rate_limit_exceeded', 'too many requests', 'usage_limit_reached')


def samples(path, limit):
    with path.open(encoding='utf-8-sig') as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    result = []
    seen = set()
    for row in rows:
        question = row.get('question', '').strip()
        if not question or question.casefold() in seen:
            continue
        seen.add(question.casefold())
        result.append({'id': hashlib.sha256(question.encode('utf-8')).hexdigest()[:20],
                       'question': question, 'candidate': row.get('target'),
                       'recipe_id': row.get('recipe_id')})
        if len(result) >= limit:
            break
    return result


def prompt(batch):
    return ('''Classify culinary questions by meaning, without recipe context. Do NOT answer.
Return ONLY JSON {"responses":[{"id":"...","intent":"...","operation":"..."}]}.
Intents: ingredients (list/check); quantity (get: amounts, time, temperatures);
steps (next/explain/rewrite); constraints (check/substitute); unknown (unknown).
Use unknown/unknown for off-topic or inseparable mixed requests.
Keep every id, exactly once; no explanations, no recipe facts.
QUESTIONS:\n''' + json.dumps([{'id': item['id'], 'question': item['question']}
                                for item in batch], ensure_ascii=False))


def validate(data, batch):
    items = data.get('responses')
    expected = {x['id'] for x in batch}
    if not isinstance(items, list) or len(items) != len(batch):
        raise ValueError('Wrong number of responses')
    ids = [x.get('id') for x in items]
    if set(ids) != expected or len(set(ids)) != len(ids):
        raise ValueError('Missing, duplicate or unexpected ids')
    for item in items:
        # A structured teacher response may reveal a missing operation in our
        # preliminary ontology (e.g. steps/get for cooking heat or timing).
        # Preserve the teacher answer for auditing instead of losing the batch.
        item['taxonomy_warning'] = item['operation'] not in ALLOWED[item['intent']]
        if 'confidence' in item and not 0 <= item['confidence'] <= 1:
            raise ValueError('Confidence out of range')
    return {x['id']: x for x in items}


def tokens_from_events(text):
    usage = {}
    for line in text.splitlines():
        try:
            event = json.loads(line)
            if event.get('type') == 'turn.completed':
                usage = event.get('usage') or {}
        except ValueError:
            continue
    return {'input_tokens': usage.get('input_tokens', 0),
            'output_tokens': usage.get('output_tokens', 0)}


def codex_run(batch, args, batch_index, stop=None):
    directory = args.out / 'batches'
    directory.mkdir(parents=True, exist_ok=True)
    name = f'batch_{batch_index:06d}'
    good = directory / (name + '.json')
    if good.exists():
        saved = json.loads(good.read_text(encoding='utf-8'))
        if [x['id'] for x in saved['items']] != [x['id'] for x in batch]:
            raise ValueError(f'{name}: existing result belongs to different questions; choose new --out')
        return 'skipped', name
    if stop is not None and stop.is_set():
        return 'paused', name
    events = directory / (name + '.events.jsonl')
    if events.exists() and not args.retry_errors:
        return 'needs_review', name
    with tempfile.TemporaryDirectory(prefix='tiny-intents-') as temp:
        output = Path(temp) / 'result.json'
        command = [args.codex, '--ask-for-approval', 'never', '-c',
                   f'model_reasoning_effort={args.reasoning}',
                   'exec', '--sandbox', 'read-only', '--skip-git-repo-check',
                   '--output-schema', str(SCHEMA.resolve()), '--json', '-o', str(output),
                   '--model', args.model, '-']
        try:
            started = time.monotonic()
            process = subprocess.run(command, input=prompt(batch), text=True,
                                     capture_output=True, timeout=args.timeout, cwd=temp)
            events.write_text(process.stdout, encoding='utf-8')
            usage = tokens_from_events(process.stdout)
            elapsed = round(time.monotonic() - started, 2)
            if any(pattern in (process.stderr + process.stdout).casefold() for pattern in QUOTA_ERRORS):
                if stop is not None:
                    stop.set()
                raise RuntimeError('Quota/usage limit detected; pause all new batches')
            if process.returncode or not output.is_file():
                raise RuntimeError(f'Codex exit={process.returncode}; {process.stderr[-500:]}')
            text = output.read_text(encoding='utf-8')
            labelled = validate(json.loads(text), batch)
            result = {'batch': name, 'model': args.model, 'label_status': 'teacher_unverified',
                      'usage': usage, 'duration_seconds': elapsed,
                      'items': [{**original, 'teacher': labelled[original['id']]}
                                for original in batch]}
            # Atomic success file, so restart skips only complete, validated batches.
            staging = directory / (name + '.tmp')
            staging.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            staging.replace(good)
            return 'ok', name
        except Exception as exc:
            (directory / (name + '.error.txt')).write_text(str(exc), encoding='utf-8')
            return 'error', name


def recover_events(args, batches):
    """Recover complete Codex answers from saved events without another call."""
    directory = args.out / 'batches'
    recovered = 0
    for index, original in enumerate(batches):
        name = f'batch_{index:06d}'
        target = directory / (name + '.json')
        events = directory / (name + '.events.jsonl')
        if target.exists() or not events.exists():
            continue
        candidates = []
        for line in events.read_text(encoding='utf-8').splitlines():
            try:
                event = json.loads(line)
                item = event.get('item', {})
                if event.get('type') == 'item.completed' and item.get('type') == 'agent_message':
                    candidates.append(json.loads(item['text']))
            except (ValueError, KeyError, TypeError):
                continue
        for candidate in reversed(candidates):
            try:
                labelled = validate(candidate, original)
                result = {'batch': name, 'model': args.model,
                          'label_status': 'teacher_unverified_recovered_from_events',
                          'items': [{**row, 'teacher': labelled[row['id']]}
                                    for row in original]}
                staging = directory / (name + '.tmp')
                staging.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                   encoding='utf-8')
                staging.replace(target)
                recovered += 1
                print('recovered', name)
                break
            except (ValueError, KeyError):
                continue
    return recovered


def export(args):
    directory = args.out / 'batches'
    results = []
    total_in = total_out = elapsed_sum = calls_with_metrics = 0
    for path in sorted(directory.glob('batch_*.json')):
        batch = json.loads(path.read_text(encoding='utf-8'))
        results.extend(batch['items'])
        if batch.get('usage'):
            total_in += batch['usage'].get('input_tokens', 0)
            total_out += batch['usage'].get('output_tokens', 0)
            elapsed_sum += batch.get('duration_seconds', 0)
            calls_with_metrics += 1
    output = args.out / 'teacher_intents_unverified.jsonl'
    with output.open('w', encoding='utf-8') as stream:
        for item in results:
            stream.write(json.dumps(item, ensure_ascii=False) + '\n')
    print('Exported', len(results), 'teacher-labelled questions to', output)
    if calls_with_metrics:
        print(f'Metrics: {calls_with_metrics} measured calls; {total_in} input / '
              f'{total_out} output tokens; {elapsed_sum:.1f}s aggregate worker time')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--out', type=Path, default=Path('dados/intents_teacher'))
    p.add_argument('--limit', type=int, default=12)
    p.add_argument('--batch-size', type=int, default=8)
    p.add_argument('--workers', type=int, default=8)
    p.add_argument('--model', default='gpt-6-luna')
    p.add_argument('--reasoning', choices=['low', 'medium', 'high'], default='low')
    p.add_argument('--timeout', type=int, default=180)
    p.add_argument('--codex', default='codex')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--export-only', action='store_true')
    p.add_argument('--recover-events', action='store_true',
                   help='Recover complete saved Codex responses; no new requests')
    p.add_argument('--retry-errors', action='store_true',
                   help='Explicitly repeat failed calls after inspecting saved events')
    args = p.parse_args()
    if not (1 <= args.limit <= 100000 and 1 <= args.batch_size <= 10 and
            1 <= args.workers <= 12):
        p.error('Check limit / batch-size / workers ranges')
    args.out.mkdir(parents=True, exist_ok=True)
    if args.export_only:
        export(args)
        return
    rows = samples(args.input, args.limit)
    batches = [rows[i:i + args.batch_size] for i in range(0, len(rows), args.batch_size)]
    print(f'{len(rows)} questions; {len(batches)} batches; {args.workers} workers')
    if args.recover_events:
        print('Recovered batches:', recover_events(args, batches))
        export(args)
        return
    if args.dry_run:
        print(prompt(batches[0]) if batches else 'No questions')
        print('DRY RUN: no Codex calls')
        return
    if os.getenv('OPENAI_API_KEY') or os.getenv('CODEX_API_KEY'):
        p.error('Remove API keys: use the authenticated Codex ChatGPT login')
    if not shutil.which(args.codex):
        p.error('Codex CLI not installed or unavailable on PATH')
    login = subprocess.run([args.codex, 'login', 'status'], capture_output=True,
                           text=True, timeout=30)
    if login.returncode or 'chatgpt' not in (login.stdout + login.stderr).casefold():
        p.error('Run codex login with your ChatGPT account first')
    stop = Event()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(codex_run, group, args, i, stop) for i, group in enumerate(batches)]
        errors = 0
        needs_review = 0
        for task in as_completed(futures):
            status, name = task.result()
            print(status, name, flush=True)
            errors += (status == 'error')
            needs_review += (status == 'needs_review')
    export(args)
    if errors or needs_review or stop.is_set():
        raise SystemExit(f'{errors} failed batches, {needs_review} saved event batches need review. '
                         'Use --recover-events before choosing --retry-errors.')


if __name__ == '__main__':
    main()
