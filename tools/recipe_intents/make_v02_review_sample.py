"""Create a reproducible, stratified human-label audit sheet for C2 v02."""
import argparse
import csv
import json
import random
from collections import defaultdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', type=Path, default=Path('intent_dataset_v02'))
    parser.add_argument('--per-operation', type=int, default=20)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    groups = defaultdict(list)
    for split in ('train', 'validation', 'test'):
        with (args.dataset / f'{split}.jsonl').open(encoding='utf-8') as stream:
            for line in stream:
                row = json.loads(line)
                key = (row['target']['intent'], row['target']['operation'])
                groups[key].append((split, row))
    sample = []
    for key, items in sorted(groups.items()):
        rng.shuffle(items)
        for split, row in items[:args.per_operation]:
            sample.append({
                'split': split,
                'question': row['question'],
                'recipe_id': row.get('recipe_id', ''),
                'candidate_intent': key[0],
                'candidate_operation': key[1],
                'human_intent': '',
                'human_operation': '',
                'decision_accept_correct_reject': '',
                'notes': '',
            })
    rng.shuffle(sample)
    destination = args.dataset / 'review_sample_v02.csv'
    with destination.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(sample[0]))
        writer.writeheader()
        writer.writerows(sample)
    print(f'{len(sample)} review candidates from {len(groups)} operations: {destination}')


if __name__ == '__main__':
    main()
