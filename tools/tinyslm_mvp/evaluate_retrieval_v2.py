"""Compare baseline and enhanced RECIPE_SEARCH on a recipe-disjoint split.

Quote-token recall is a weak automatic proxy. Even perfect quote-token recall
would not establish factual accuracy, coverage or safety. Manual evaluation
remains mandatory before SFT.
"""
from __future__ import annotations
import argparse,collections,gzip,json,sys
from pathlib import Path
from recipe_search import RecipeSearch
from recipe_search_v2 import RecipeSearchV2
from evaluate_retrieval_baseline import quote_recall


def run(db:Path,candidates:Path,split='validation',router=None,limit=0):
    rows=[]
    with gzip.open(candidates,'rt',encoding='utf8') as f:
        for line in f:
            row=json.loads(line)
            if row['split']==split:
                rows.append(row)
                if limit and len(rows)>=limit:break
    tools={'baseline':RecipeSearch(db),'v2_no_router':RecipeSearchV2(db),'v2_router':RecipeSearchV2(db,router_path=router)} if router else {'baseline':RecipeSearch(db),'v2_no_router':RecipeSearchV2(db)}
    measures={key:{'recalls':[],'status':collections.Counter(),'n_passages':[],'truncated':0} for key in tools}
    samples=[]
    for o in rows:
        answers={key:tool.search(o['recipe_id'],o['question']) for key,tool in tools.items()}
        for key,a in answers.items():
            measures[key]['recalls'].append(quote_recall(a['evidence'],o['source_quotes']))
            measures[key]['status'][a['status']]+=1
            measures[key]['n_passages'].append(len(a['evidence']))
            measures[key]['truncated']+=bool(a.get('truncated'))
        r1=measures['baseline']['recalls'][-1]
        r2=measures['v2_router' if router else 'v2_no_router']['recalls'][-1]
        if len(samples)<12 and (r2-r1>=0.6 or r1-r2>=0.6):
            samples.append({'id':o['id'],'question':o['question'],'baseline_quote_overlap':round(r1,3),'v2_quote_overlap':round(r2,3),'quote':o['source_quotes'][:1], 'v2_texts':[e['text'] for e in answers['v2_router' if router else 'v2_no_router']['evidence'][:3]]})
    for t in tools.values():t.close()
    result={'split':split,'n':len(rows),'baselines':{}}
    for key,m in measures.items():
        v=m['recalls'];n=len(v)
        result['baselines'][key]={'status':dict(m['status']),
          'quote_recall_ge_0_50':round(sum(x>=.5 for x in v)/n,4),
          'quote_recall_ge_0_80':round(sum(x>=.8 for x in v)/n,4),
          'quote_recall_mean':round(sum(v)/n,4),
          'avg_passages':round(sum(m['n_passages'])/n,2),
          'truncated_count':m['truncated']}
    result['comparison_samples']=samples
    result['limitations']=['Historical source quotes are weak lexical references, not ground truth.','Multiple passages may be required; increased recall can result from returning more text.','No answer correctness or tool decision metric, no human review yet.','Split by recipe for this dataset only; previous training exposure may not be fully excluded.']
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--candidates',type=Path,required=True)
    p.add_argument('--split',choices=['train','validation','test'],default='validation');p.add_argument('--router',type=Path)
    p.add_argument('--limit',type=int,default=0);p.add_argument('--out',type=Path)
    a=p.parse_args();res=run(a.db,a.candidates,a.split,a.router,a.limit)
    if a.out:a.out.write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in res.items() if k!='comparison_samples'},ensure_ascii=False,indent=2))