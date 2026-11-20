"""Prepare a deterministic 200-question teacher trial across operations and unknowns."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import random


OFF_DOMAIN = [
    'Who won the football match yesterday?', 'How do I reset my router?',
    'What is the capital of Peru?', 'Can you translate this contract into German?',
    'How do I create a Git branch?', 'What is the weather forecast tomorrow?',
    'How can I cancel a hotel reservation?', 'Write a poem about the ocean.',
    'What are the symptoms of influenza?', 'How do I configure a firewall?',
    'What is the exchange rate for euros?', 'Solve the equation x squared minus nine equals zero.',
    'Who wrote Hamlet?', 'How do I get to the airport?',
    'Explain the difference between TCP and UDP.', 'Can you book a taxi?',
    'When did the Roman Empire fall?', 'How much RAM does my laptop have?',
    'What is the population of Tokyo?', 'Can you recommend a horror film?',
]


def read(path):
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def create(dataset, output, seed):
    rng = random.Random(seed)
    groups = defaultdict(list)
    for row in read(dataset / 'train.jsonl'):
        key = (row['target']['intent'], row['target']['operation'])
        groups[key].append(row)
    assert len(groups) == 8, f'Expected 8 operations; found {sorted(groups)}'
    selected = []
    seen = set()

    def include(row, group):
        question = row['question'].strip()
        key = question.casefold()
        if key in seen:
            return False
        seen.add(key)
        selected.append({'question': question, 'target': row.get('target'),
                         'recipe_id': row.get('recipe_id'), 'pilot_group': group,
                         'candidate_status': 'weak_heuristic_not_verified'})
        return True

    for (intent, operation), rows in sorted(groups.items()):
        rng.shuffle(rows)
        count = 0
        for row in rows:
            if include(row, f'{intent}/{operation}'):
                count += 1
            if count == 20:
                break
        if count != 20:
            raise ValueError(f'Not enough unique examples for {intent}/{operation}')

    for question in OFF_DOMAIN:
        include({'question': question, 'target': {'intent': 'unknown', 'operation': 'unknown'}},
                'unknown/off_domain')

    candidates = [row for row in read(dataset / 'review.jsonl')
                  if row.get('reason') in {'possible_compound_request', 'multi_request',
                                           'multi_or_conflicting_request'}]
    rng.shuffle(candidates)
    count = 0
    for row in candidates:
        # These are UNCERTAIN cases, not validated unknown labels.
        if include({'question': row['question'], 'recipe_id': None,
                    'target': {'intent': 'unknown', 'operation': 'unknown'}},
                   'unknown/ambiguous_candidate'):
            count += 1
        if count == 20:
            break
    assert len(selected) == 200, len(selected)
    rng.shuffle(selected)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('w', encoding='utf-8') as stream:
        for row in selected:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    print('Saved', len(selected), 'questions to', output)
    print('8 operations x 20 + 20 off-domain + 20 ambiguous candidates')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', type=Path, default=Path('intent_dataset_v02'))
    parser.add_argument('--output', type=Path,
                        default=Path('dados/intents_teacher/pilot_200_questions.jsonl'))
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    create(args.dataset, args.output, args.seed)


if __name__ == '__main__':
    main()
