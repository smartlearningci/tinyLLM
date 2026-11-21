"""Prepare 20k unique C2 questions for Codex teacher annotation (NOT final train set).

Sources: only v02 train candidates and unassigned review questions; v02 validation
and test questions are excluded. This output is a teacher queue, NOT a label set.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import random


REVIEW_QUOTAS = {
    'possible_compound_request': 2600,
    'multi_request': 1150,
    'abstain': 1100,
    'contextual_what_else': 400,
    'multi_or_conflicting_request': 200,
}


def read_jsonl(path):
    with path.open(encoding='utf-8-sig') as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def normalized(question):
    return ' '.join(question.casefold().split())


def select(dataset, output, limit=20000, seed=42, exclusions=()):
    rng = random.Random(seed)
    # Exclude previous teacher trial prompts, and exact validation/test questions.
    forbidden = set()
    for split in ('validation.jsonl', 'test.jsonl'):
        forbidden.update(normalized(x['question']) for x in read_jsonl(dataset / split))
    for source in exclusions:
        if source.exists():
            forbidden.update(normalized(x['question']) for x in read_jsonl(source))

    seen = set(forbidden)
    chosen = []

    def insert(row, origin):
        question = row['question'].strip()
        key = normalized(question)
        if not key or key in seen:
            return False
        seen.add(key)
        chosen.append({'question': question,
                       'target': row.get('target'),
                       'recipe_id': row.get('recipe_id'),
                       'origin': origin,
                       'review_reason': row.get('reason'),
                       'label_status': 'question_only_teacher_pending'})
        return True

    candidates = list(read_jsonl(dataset / 'train.jsonl'))
    rng.shuffle(candidates)
    for row in candidates:
        insert(row, 'v02_train_weak_candidate')

    # Review questions are not known negatives; sample them for the teacher to
    # resolve rather than asserting unknown or recycling a keyword-based label.
    review = defaultdict(list)
    for row in read_jsonl(dataset / 'review.jsonl'):
        if row.get('reason') == 'multiple_or_no_recipe':
            continue
        review[row.get('reason')].append(row)
    for group in review.values():
        rng.shuffle(group)
    quota_counts = Counter()
    for reason, count in REVIEW_QUOTAS.items():
        for row in review.get(reason, []):
            if len(chosen) >= limit or quota_counts[reason] >= count:
                break
            if insert(row, f'v02_review_{reason}'):
                quota_counts[reason] += 1
    if len(chosen) < limit:
        pool = [row for group in review.values() for row in group]
        rng.shuffle(pool)
        for row in pool:
            if len(chosen) >= limit:
                break
            insert(row, f'v02_review_{row.get("reason")}')
    if len(chosen) < limit:
        raise RuntimeError(f'Only {len(chosen)} unique questions available; requested {limit}')
    # Shuffle final order to distribute operation types across partial runs.
    rng.shuffle(chosen)
    chosen = chosen[:limit]
    output.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with output.open('w', encoding='utf-8') as stream:
        for row in chosen:
            line = json.dumps(row, ensure_ascii=False) + '\n'
            stream.write(line)
            digest.update(line.encode('utf-8'))
    counts = dict(sorted(Counter(row['origin'] for row in chosen).items()))
    report = {'status': 'teacher_questions_only_unverified', 'questions': len(chosen),
              'excluded_questions': len(forbidden), 'sha256': digest.hexdigest(),
              'source_counts': counts, 'seed': seed,
              'warnings': ['Do not treat this as a human-labelled train split.',
                           'V02 recipe-disjoint validation/test are reserved, but '
                           'question-only review rows may share recipe content.',
                           'Create a new audited split after teacher labels are reviewed.']}
    (output.parent / (output.stem + '_report.json')).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', type=Path, default=Path('intent_dataset_v02'))
    parser.add_argument('--output', type=Path,
                        default=Path('dados/intents_teacher/production_20000_questions.jsonl'))
    parser.add_argument('--limit', type=int, default=20000)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--exclude', type=Path, action='append', default=[])
    args = parser.parse_args()
    if args.limit < 1:
        parser.error('limit must be positive')
    report = select(args.dataset, args.output, args.limit, args.seed, args.exclude)
    print('Prepared', report['questions'], 'questions:', args.output)
    print('SHA256:', report['sha256'])
    print('Sources:', json.dumps(report['source_counts'], ensure_ascii=False))


if __name__ == '__main__':
    main()
