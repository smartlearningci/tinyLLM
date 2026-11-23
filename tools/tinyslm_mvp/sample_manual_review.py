"""Prepare a deterministic, unlabelled human-audit set for the known C2 test split.

Generated outputs are held outside the Git repo (private recipe/dialogue data).
Do not treat source quotes or teacher answers as adjudicated correctness.
"""
from __future__ import annotations
import argparse,collections,gzip,json,hashlib
from pathlib import Path
from recipe_search import RecipeSearch
from recipe_search_v2 import RecipeSearchV2
from evaluate_retrieval_baseline import quote_recall


def run(db:Path,candidates:Path,output:Path,per_category:int=20):
    categories=collections.defaultdict(list)
    old=RecipeSearch(db)
    with RecipeSearchV2(db) as new:
        with gzip.open(candidates,'rt',encoding='utf8') as f:
            for line in f:
                case=json.loads(line)
                if case['split']!='test':continue
                a=old.search(case['recipe_id'],case['question'])
                b=new.search(case['recipe_id'],case['question'])
                r1=quote_recall(a['evidence'],case['source_quotes'])
                r2=quote_recall(b['evidence'],case['source_quotes'])
                if b['status']=='INSUFFICIENT_EVIDENCE':category='no_candidate'
                elif b.get('truncated'):category='truncated'
                elif r2>r1+.35:category='improved_lexical_overlap'
                elif r1>r2+.35:category='regressed_lexical_overlap'
                else:category='other'
                entry={
                    'case_id':case['id'],'recipe_id':case['recipe_id'],
                    'recipe_title':case['recipe_title'],'question':case['question'],
                    'historical_quotes_weak_reference':case['source_quotes'],
                    'baseline_evidence':a['evidence'], 'v2_evidence':b['evidence'],
                    'v2_status':b['status'],'v2_truncated':b.get('truncated',False),
                    'weak_quote_recall_baseline':round(r1,3),
                    'weak_quote_recall_v2':round(r2,3),
                    'human_evidence_correct':None,'human_evidence_complete':None,
                    'human_contradiction_or_exclusion':None,'human_notes':None,
                }
                categories[category].append(entry)
    old.close()
    selected=[]
    for category,rows in sorted(categories.items()):
        # Deterministic selection without biasing toward alphabetical questions.
        rows.sort(key=lambda x:hashlib.sha256(x['case_id'].encode()).hexdigest())
        for r in rows[:per_category]:
            selected.append({'review_category':category,**r})
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('w',encoding='utf8') as f:
        for r in selected:f.write(json.dumps(r,ensure_ascii=False)+'\n')
    return {'per_category_target':per_category,'available_by_category':{k:len(v) for k,v in categories.items()},
            'selected_by_category':dict(collections.Counter(r['review_category'] for r in selected)),
            'selected_total':len(selected),'human_reviewed':0,'note':'Selection is not human grading; no factual accuracy metric yet.'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',required=True,type=Path);p.add_argument('--candidates',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path);p.add_argument('--per-category',type=int,default=20)
    a=p.parse_args();print(json.dumps(run(a.db,a.candidates,a.out,a.per_category),indent=2))