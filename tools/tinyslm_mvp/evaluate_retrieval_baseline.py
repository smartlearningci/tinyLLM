"""Non-authoritative diagnostic of retrieval on held-out C2 scenarios.

Historical teacher source_quotes are weak reference only. Do not interpret
quote-token overlap as correctness of retrieval, response or tool decision.
"""
from __future__ import annotations
import argparse
import collections
import gzip
import json
from pathlib import Path
from recipe_search import RecipeSearch, tokens


def quote_recall(evidence: list[dict], source_quotes: list[str]) -> float:
    if not evidence or not source_quotes: return 0.0
    retrieved=set(tokens(' '.join(e['text'] for e in evidence)))
    scores=[]
    for quote in source_quotes:
        target=set(tokens(quote))
        if target: scores.append(len(target & retrieved)/len(target))
    return max(scores,default=0.0)


def run(db:Path,candidates:Path,split:str='test',max_examples:int=0) -> dict:
    tool=RecipeSearch(db)
    rows=[]
    with gzip.open(candidates,'rt',encoding='utf8') as f:
        for line in f:
            o=json.loads(line)
            if o['split'] != split:continue
            rows.append(o)
            if max_examples and len(rows)>=max_examples:break
    status=collections.Counter()
    recall=[]
    worst=[]
    for o in rows:
        ans=tool.search(o['recipe_id'],o['question'])
        status[ans['status']]+=1
        r=quote_recall(ans['evidence'],o['source_quotes'])
        recall.append(r)
        if r<0.25 and len(worst)<12:
            worst.append({'id':o['id'],'title':o['recipe_title'],
                          'question':o['question'],'quotes':o['source_quotes'][:2],
                          'retrieved':[e['text'] for e in ans['evidence'][:4]],
                          'quote_overlap_recall':round(r,3)})
    tool.close()
    return {'split':split,'n':len(rows),'status':dict(status),
            'weak_quote_recall_at_least_0_5':round(sum(r>=.5 for r in recall)/max(1,len(rows)),4),
            'weak_quote_recall_at_least_0_8':round(sum(r>=.8 for r in recall)/max(1,len(rows)),4),
            'weak_quote_recall_mean':round(sum(recall)/max(1,len(rows)),4),
            'weak_quote_warning':'Not ground truth. Quote length/segmentation can distort scores. Human review required.',
            'examples_of_failure':worst}

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--db',type=Path,required=True)
    p.add_argument('--candidates',type=Path,required=True)
    p.add_argument('--split',choices=('train','validation','test'),default='test')
    p.add_argument('--limit',type=int,default=0)
    p.add_argument('--out',type=Path)
    args=p.parse_args()
    result=run(args.db,args.candidates,args.split,args.limit)
    data=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.out:
        args.out.write_text(data,encoding='utf8')
    print(data[:1600])