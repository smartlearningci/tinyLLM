"""High-precision English intent candidate builder (v02).

Uses sentence-level request patterns with explicit abstention. This is not a
semantic model or a substitute for human review. Unknown and slot supervision
must come from separately curated sources.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
import re
from pathlib import Path

OPERATIONS = {
    'ingredients': {'list', 'check'},
    'quantity': {'get'},
    'steps': {'next', 'explain', 'rewrite'},
    'constraints': {'check', 'exclude', 'substitute'},
}


def norm(text):
    return re.sub(r'\s+', ' ', text.lower().replace('’', "'").strip())


def classify_v02(question):
    q = norm(question)
    if not 12 <= len(q) <= 420:
        return None, 'length'
    # Obvious multi-part instructions should not be reduced to a single intent.
    if re.search(r'\b(?:ingredients and (?:steps|instructions|directions)|steps and ingredients|ingredients and preparation steps)\b', q):
        return None, 'multi_request'
    if re.search(r'\b(?:what else|something else)\b', q):
        return None, 'contextual_what_else'
    if re.search(r'\b(?:and (?:does|do|can|should|what|when|how)|, (?:and )?what (?:else|kind))\b', q):
        return None, 'possible_compound_request'
    hits = set()
    def match(intent, op, pattern):
        if re.search(pattern, q):
            hits.add((intent, op))

    # Check restrictions *before* ingredient presence; classify request purpose.
    dietary = re.search(r'(?:dairy.free|gluten.free|alcohol.free|peanut.free|nut.free|egg.free|vegetarian|vegan|allergic|contain no [a-z]+|avoid(?:ing)? (?:dairy|alcohol|gluten|nuts?|meat|eggs?|beef|fish)|can(?:not|\'t) eat)', q)
    unchanged = re.search(r'(?:as written|unchanged|exactly as (?:written|listed)|meet (?:my|the|that|this) (?:requirement|restriction|constraint)|suitable for|safe for)', q)
    if dietary and (unchanged or re.search(r'\b(?:does|can|is|are|will)\b', q)):
        hits.add(('constraints','check'))
    match('constraints','check',r'(?:can i|could i|is it possible to|does the recipe allow).{0,85}(?:without (?:butter|eggs?|milk|cheese|nuts?|garlic|onion|flour|sugar|salt|oil|cream|meat|fish)|leave out (?:the )?(?:butter|eggs?|milk|cheese|nuts?|garlic|onion|flour|sugar|salt|oil|cream|meat|fish))')
    match('constraints','substitute',r'(?:what (?:can|could|should) i use instead of|can i (?:replace|substitute) .{1,50} with|(?:does|do) (?:the )?recipe (?:give|offer|suggest|specify|recommend) (?:a |any )?substitut)')
    # Explicit exclusion requests are generally mixed with recipe compliance;
    # abstain rather than emit an inaccurate `exclude` operation.

    # Ingredient list and membership must be the dominant request.
    match('ingredients','list',r'^(?:(?:please )?(?:list|give me|show me|tell me|name)|what|which|could you list|can you list).{0,95}\b(?:ingredients|spices|herbs)\b')
    match('ingredients','list',r'\b(?:which|what) (?:listed )?ingredients (?:go|belong|should i|are used|do i need|are required)\b')
    match('ingredients','check',r'\b(?:does|do|is|are) (?:this |the )?(?:recipe|ingredient list|dish|sauce|it) .{0,35}(?:contain|include|list)\b')

    # Measured ingredients, yields and servings, not cooking duration or calories.
    match('quantity','get',r'\b(?:how much|what (?:amount|quantity|weight|measurement)) .{0,95}\b(?:use|need|required|calls? for|add|measure|pour|goes? (?:in|into)|does? (?:the )?recipe (?:specify|list|use))\b')
    match('quantity','get',r'\bhow many (?!minutes|hours|seconds|days)(?:\w+ ?){0,10}(?:do i need|should i use|does? (?:this|the) recipe (?:need|make|serve)|are required|does? it make)\b')
    match('quantity','get',r'\bhow many (?:servings|people|portions|cups|tablespoons|teaspoons|potatoes|eggs|onions|cloves)\b')
    match('quantity','get',r'\bhow many .{0,70}(?:does|do) (?:the|this) recipe (?:call for|need|specify)\b')

    # Method and procedural timing.
    match('steps','next',r'\b(?:what (?:should|do) i do (?:immediately )?(?:next|after)|what comes (?:immediately )?(?:next|after)|what (?:is|comes) the next step)\b')
    match('steps','explain',r'\b(?:how (?:do|should|can) i (?:prepare|cook|chop|cut|mix|bake|roast|slice|heat|assemble)|when (?:should|do) i (?:add|remove|take|mix|stir)|which (?:pan|utensil|equipment) (?:should|do)|what (?:heat|texture|cue|oven temperature))\b')
    match('steps','explain',r'\b(?:how (?:long|many minutes|many hours) (?:should|do|does)|what (?:cooking|baking|freezing|roasting) time|what temperature (?:should|does|is))\b')
    match('steps','rewrite',r'\b(?:rewrite|turn|convert|reformat) .{0,100}\b(?:method|instructions|directions|steps|checklist|sequence)\b')

    if not hits:
        return None, 'abstain'
    # Skip diet+ingredient overlap rather than pretending to resolve anaphora.
    if dietary and ('constraints','check') in hits:
        hits = {h for h in hits if h[0] == 'constraints'}
    if len(hits) != 1:
        return None, 'multi_or_conflicting_request'
    intent, operation = next(iter(hits))
    return {'intent': intent, 'operation': operation}, 'high_precision_candidate'


def split_for_single_recipe(recipe_id):
    value = int.from_bytes(hashlib.sha256(recipe_id.encode()).digest()[:8], 'big') % 100
    return 'train' if value < 80 else 'validation' if value < 90 else 'test'


def build(source, destination, limit=30000, seed=42):
    destination.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    buckets = {x: [] for x in ('train','validation','test')}
    limits = {'train': int(limit*.8), 'validation': int(limit*.1)}
    limits['test'] = limit - sum(limits.values())
    seen = collections.Counter()
    counts = collections.Counter()
    with source.open(encoding='utf-8') as stream, (destination/'review.jsonl').open('w',encoding='utf-8') as review:
        for line in stream:
            src = json.loads(line)
            q = src.get('question', '')
            ids = sorted(set(src.get('recipe_ids', [])))
            label, reason = classify_v02(q)
            if label is None or len(ids) != 1:
                obj = {'question': q, 'reason': reason if label is None else 'multiple_or_no_recipe',
                       'candidate':label, 'recipe_count':len(ids)}
                review.write(json.dumps(obj,ensure_ascii=False)+'\n')
                counts['review'] += 1
                continue
            split = split_for_single_recipe(ids[0])
            row = {'question':q,'target':label,'recipe_id':ids[0],
                   'capabilities':src.get('capabilities',[]),
                   'label_status':'high_precision_weak_candidate', 'source':'audited_c1_c7_questions'}
            counts['eligible'] += 1
            seen[split] += 1
            reservoir = buckets[split]
            if len(reservoir) < limits[split]:
                reservoir.append(row)
            else:
                idx = rng.randrange(seen[split])
                if idx < limits[split]: reservoir[idx] = row
    for split, rows in buckets.items():
        # Keep frequent templated forms from drowning out rare operations.
        by_operation = collections.defaultdict(list)
        for row in rows:
            by_operation[row['target']['intent']+'/'+row['target']['operation']].append(row)
        max_per_operation = 3000 if split == 'train' else 400
        balanced = []
        for group in sorted(by_operation):
            group_rows = by_operation[group]
            rng.shuffle(group_rows)
            balanced.extend(group_rows[:max_per_operation])
        rng.shuffle(balanced)
        rows = balanced
        buckets[split] = rows
        with (destination/f'{split}.jsonl').open('w',encoding='utf-8') as f:
            for row in rows:
                f.write(json.dumps(row,ensure_ascii=False)+'\n')
        counts[split] = len(rows)
    report = {'status':'HIGH_PRECISION_WEAK_CANDIDATES_NOT_YET_HUMAN_VERIFIED',
              'counts':dict(counts),'requested_limit':limit,
              'distribution':{split:dict(collections.Counter(r['target']['intent']+'/'+r['target']['operation'] for r in rows))
                              for split,rows in buckets.items()},
              'warnings':['Do not train until representative labels are manually validated.',
                          'No unknown examples, no ingredient slots, and no multi-intent labels yet.',
                          'Recipe-disjoint splits do not guarantee paraphrase-disjoint evaluation.']}
    (destination/'build_report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    return report


if __name__ == '__main__':
    cli = argparse.ArgumentParser()
    cli.add_argument('--source',required=True,type=Path)
    cli.add_argument('--output',required=True,type=Path)
    cli.add_argument('--max-candidates',type=int,default=30000)
    args=cli.parse_args()
    print(json.dumps(build(args.source,args.output,args.max_candidates),indent=2))
