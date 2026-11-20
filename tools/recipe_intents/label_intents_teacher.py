"""Small, resumable teacher-label pilot for C2 intent candidates.

Uses the OpenAI Responses API; never automatically approves teacher labels.
"""
import argparse
import concurrent.futures
import csv
import json
import os
import random
import time
from pathlib import Path

INTENTS = {'ingredients', 'quantity', 'steps', 'constraints', 'unknown'}
OPERATIONS = {'list', 'check', 'get', 'next', 'explain', 'rewrite', 'substitute', 'unknown'}
INSTRUCTIONS = '''Classify the user's intent in a cooking recipe assistant.
You receive ONLY the user question, not the recipe. Do not answer the question.
Choose intent: ingredients, quantity, steps, constraints, unknown.
Choose operation: list, check, get, next, explain, rewrite, substitute, unknown.
If ambiguous, mixed, or outside the domain, use unknown for both or explain uncertainty.
Examples: "How much paprika?" -> quantity/get; "What do I add next?" -> steps/next;
"Is it dairy-free?" -> constraints/check; "Who won?" -> unknown/unknown.
Return a JSON object with exactly intent, operation, confidence (0 to 1), rationale (brief).'''


def read_questions(path, limit, seed):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        if path.suffix.lower() == '.csv':
            rows = list(csv.DictReader(handle))
        else:
            rows = [json.loads(line) for line in handle if line.strip()]
    rows = [row for row in rows if row.get('question')]
    random.Random(seed).shuffle(rows)
    return rows[:limit]


def teacher_label(question, model):
    from openai import OpenAI
    client = OpenAI(timeout=45, max_retries=2)
    response = client.responses.create(
        model=model,
        instructions=INSTRUCTIONS,
        input=question,
        text={'format': {'type': 'json_object'}},
        max_output_tokens=180,
    )
    data = json.loads(response.output_text)
    intent = data.get('intent')
    operation = data.get('operation')
    if intent not in INTENTS or operation not in OPERATIONS:
        raise ValueError(f'Invalid intent/operation: {intent}/{operation}')
    confidence = float(data.get('confidence', 0))
    if not 0 <= confidence <= 1:
        raise ValueError('Confidence must be between 0 and 1')
    return {'intent': intent, 'operation': operation, 'confidence': confidence,
            'rationale': str(data.get('rationale', ''))[:500]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('pilot_teacher_labels.jsonl'))
    parser.add_argument('--limit', type=int, default=12)
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--model', default='gpt-4.1-mini')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 100 or not 1 <= args.workers <= 5:
        parser.error('Pilot guardrails: 1 <= limit <= 100, 1 <= workers <= 5')
    if not args.dry_run and not os.getenv('OPENAI_API_KEY'):
        parser.error('Missing OPENAI_API_KEY (configure Kaggle Secrets; never paste in notebook)')
    questions = read_questions(args.input, args.limit, args.seed)
    if args.dry_run:
        for row in questions:
            print(json.dumps({'question': row['question'], 'candidate': row.get('target') or
                              {'intent': row.get('candidate_intent'), 'operation': row.get('candidate_operation')}},
                             ensure_ascii=False))
        print(f'DRY RUN: {len(questions)} questions, 0 API calls')
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    completed = {}
    if args.output.exists():
        with args.output.open(encoding='utf-8') as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                    if record.get('status') == 'ok':
                        completed[record['question']] = record
                except (ValueError, KeyError):
                    continue

    def work(row):
        question = row['question']
        item = {'question': question, 'candidate': row.get('target') or
                {'intent': row.get('candidate_intent'), 'operation': row.get('candidate_operation')},
                'model': args.model, 'timestamp': int(time.time()),
                'status': 'ok', 'human_verified': False}
        try:
            item['teacher'] = teacher_label(question, args.model)
            item['agrees_with_candidate'] = all(item['teacher'][k] == item['candidate'].get(k)
                                                 for k in ('intent', 'operation'))
        except Exception as exc:
            item['status'] = 'error'
            item['error'] = f'{type(exc).__name__}: {str(exc)[:300]}'
        return item

    pending = [row for row in questions if row['question'] not in completed]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(work, row) for row in pending]
        with args.output.open('a', encoding='utf-8') as stream:
            for future in concurrent.futures.as_completed(futures):
                record = future.result()
                stream.write(json.dumps(record, ensure_ascii=False) + '\n')
                stream.flush()
                print(record['status'], record['question'][:65],
                      record.get('teacher', {}).get('intent', ''))
    print('Saved:', args.output, '| new:', len(pending), '| skipped completed:', len(questions) - len(pending))


if __name__ == '__main__':
    main()
