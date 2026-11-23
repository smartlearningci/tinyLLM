"""Train OPTIONAL C2 section router on weak quote-derived labels (train split only).

scikit-learn is needed only to train, NOT to run the resulting JSON model.
Only quotes falling entirely within an ingredient or preparation section become
pseudo-labels; ambiguity/non-matches are excluded and audited.
"""
from __future__ import annotations
import argparse, collections, gzip, json, sqlite3
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression


def category_for_quote(row,recipe):
    if recipe is None:return None
    ingr,prep=recipe
    labels=set()
    for q in row.get('source_quotes',[]):
        s=q.strip().casefold()
        if not s:continue
        a=s in ingr;b=s in prep
        if a:labels.add('INGREDIENTS')
        if b:labels.add('PREPARATION')
        if not a and not b:return None
    return next(iter(labels)) if len(labels)==1 else ('MIXED' if labels=={'INGREDIENTS','PREPARATION'} else None)


def iter_rows(path):
    with gzip.open(path,'rt',encoding='utf-8') as f:
        for ln in f:yield json.loads(ln)


def run(candidates:Path,db_path:Path,model_out:Path,report_out:Path):
    with sqlite3.connect(db_path) as con:
        recipes={r[0]:(r[1].casefold(),r[2].casefold()) for r in con.execute('SELECT recipe_id,ingredients_raw,method_raw FROM recipes')}
    train=[],[]; validation=[],[]
    stats=collections.Counter()
    for r in iter_rows(candidates):
        lab=category_for_quote(r,recipes.get(r['recipe_id']))
        stats[(r['split'],lab or 'EXCLUDED')]+=1
        if lab and r['split']=='train':
            train[0].append(r['question']);train[1].append(lab)
        if lab and r['split']=='validation':
            validation[0].append(r['question']);validation[1].append(lab)
    if not train[0] or not validation[0]:raise ValueError('No supervised train/validation cases')
    vec=TfidfVectorizer(max_features=2500,min_df=4,ngram_range=(1,2),sublinear_tf=True,strip_accents='unicode',token_pattern=r'(?u)\b\w+\b')
    x=vec.fit_transform(train[0]);xv=vec.transform(validation[0]);
    clf=LogisticRegression(max_iter=350,class_weight='balanced',random_state=42)
    clf.fit(x,train[1]); y=clf.predict(xv)
    # Multiclass linear model; inference uses exported coefficients (no sklearn).
    model={
      'schema':'tinyslm-section-router-1','classes':list(clf.classes_),
      'vocabulary':{k:int(v) for k,v in vec.vocabulary_.items()},
      'idf':vec.idf_.round(8).tolist(),
      'coef':clf.coef_.round(8).tolist(),
      'intercept':clf.intercept_.round(8).tolist(),
      'text_processing':'scikit-learn TfidfVectorizer(strip_accents=unicode,lowercase=True,token_pattern=one-or-more-word-chars,ngram_range=1,2,sublinear_tf=True,norm=l2)'
    }
    model_out.parent.mkdir(parents=True,exist_ok=True)
    model_out.write_text(json.dumps(model,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf8')
    acc=sum(a==b for a,b in zip(y,validation[1]))/len(y)
    bylab={}
    for label in clf.classes_:
        subset=[i for i,e in enumerate(validation[1]) if e==label]
        bylab[label]={'n':len(subset),'recall':round(sum(y[i]==label for i in subset)/max(1,len(subset)),4)}
    report={'training_count':len(train[0]),'validation_count':len(validation[0]),
      'weak_label_validation_accuracy':round(acc,4),
      'weak_label_validation_by_section':bylab,
      'vocabulary_size':len(vec.vocabulary_),
      'labels_by_split':{f'{sp}/{l}':n for (sp,l),n in sorted(stats.items())},
      'warning':'Weak labels are quote positions, not verified question intent, human answer correctness, or evidence completeness. Model optional and not used to override hard query constraints.'}
    report_out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--candidates',type=Path,required=True);p.add_argument('--db',type=Path,required=True);p.add_argument('--model-out',type=Path,required=True);p.add_argument('--report-out',type=Path,required=True);args=p.parse_args()
    print(json.dumps(run(args.candidates,args.db,args.model_out,args.report_out),indent=2))