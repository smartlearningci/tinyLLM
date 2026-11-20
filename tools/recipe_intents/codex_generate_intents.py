"""Build a resumable intent-labelled dataset via local authenticated Codex CLI.

Run from a PC with `codex login`; no OpenAI API key is required.
Never silently promote teacher-generated labels to human-verified labels.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    return ('''You are an expert annotation teacher for a culinary-domain assistant.
Task: classify each USER QUESTION independently without recipe context, NOT answer it.
Intent labels: ingredients (list/membership), quantity (amount/count),
steps (next/explain/rewrite), constraints (diet/replacement check), unknown.
Operations: list, check, get, next, explain, rewrite, substitute, unknown.
Use unknown/unknown for unrelated, ambiguous or multi-intent requests where one label
cannot safely capture the user's need. Judge meaning, not keyword frequency.
"How many grams of sugar?" -> quantity/get, NOT ingredients/check.
"What should I do next?" -> steps/next; "Is this dairy free?" -> constraints/check.
Be conservative. Confidence is your qualitative estimate, NOT calibrated probability.
Return a JSON object with responses, exactly one item for EACH provided id; preserve ids.
No recipe facts or invented answers. Short reason per item.
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
        if item['operation'] not in ALLOWED[item['intent']]:
            raise ValueError('Incompatible intent / operation')
        if not 0 <= item['confidence'] <= 1:
            raise ValueError('Confidence out of range')
    return {x['id']: x for x in items}


def codex_run(batch, args, batch_index):
    directory = args.out / 'batches'
    directory.mkdir(parents=True, exist_ok=True)
    name = f'batch_{batch_index:06d}'
    good = directory / (name + '.json')
    if good.exists():
        return 'skipped', name
    with tempfile.TemporaryDirectory(prefix='tiny-intents-') as temp:
        temp_path = Path(temp)
        output = temp_path / 'result.json'
        command = [args.codex, '--ask-for-approval', 'never', '-c',
                   f'model_reasoning_effort={args.reasoning}',
                   'exec', '--sandbox', 'read-only', '--skip-git-repo-check',
                   '--output-schema', str(SCHEMA.resolve()), '--json', '-o', str(output),
                   '--model', args.model, '-']
        try:
            process = subprocess.run(command, input=prompt(batch), text=True,
                                     capture_output=True, timeout=args.timeout, cwd=temp)
            (directory / (name + '.events.jsonl')).write_text(process.stdout, encoding='utf-8')
            if process.returncode or not output.is_file():
                raise RuntimeError(f'Codex exit={process.returncode}; {process.stderr[-500:]}')
            text = output.read_text(encoding='utf-8')
            labelled = validate(json.loads(text), batch)
            result = {'batch': name, 'model': args.model, 'label_status': 'teacher_unverified',
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


def export(args):
    directory = args.out / 'batches'
    results = []
    for path in sorted(directory.glob('batch_*.json')):
        batch = json.loads(path.read_text(encoding='utf-8'))
        results.extend(batch['items'])
    output = args.out / 'teacher_intents_unverified.jsonl'
    with output.open('w', encoding='utf-8') as stream:
        for item in results:
            stream.write(json.dumps(item, ensure_ascii=False) + '\n')
    print('Exported', len(results), 'teacher-labelled questions to', output)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--out', type=Path, default=Path('dados/intents_teacher'))
    p.add_argument('--limit', type=int, default=12)
    p.add_argument('--batch-size', type=int, default=3)
    p.add_argument('--workers', type=int, default=2)
    p.add_argument('--model', default='gpt-6-luna')
    p.add_argument('--reasoning', choices=['low', 'medium', 'high'], default='low')
    p.add_argument('--timeout', type=int, default=180)
    p.add_argument('--codex', default='codex')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--export-only', action='store_true')
    args = p.parse_args()
    if not (1 <= args.limit <= 100000 and 1 <= args.batch_size <= 10 and
            1 <= args.workers <= 8):
        p.error('Check limit / batch-size / workers ranges')
    args.out.mkdir(parents=True, exist_ok=True)
    if args.export_only:
        export(args)
        return
    rows = samples(args.input, args.limit)
    batches = [rows[i:i + args.batch_size] for i in range(0, len(rows), args.batch_size)]
    print(f'{len(rows)} questions; {len(batches)} batches; {args.workers} workers')
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
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(codex_run, group, args, i) for i, group in enumerate(batches)]
        errors = 0
        for task in as_completed(futures):
            status, name = task.result()
            print(status, name, flush=True)
            errors += (status == 'error')
    export(args)
    if errors:
        raise SystemExit(f'{errors} failed batches; review .error.txt files before retrying')


if __name__ == '__main__':
    main()
