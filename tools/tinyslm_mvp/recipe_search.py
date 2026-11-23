"""TinySLM C1/C2: baseline local retrieval within a *known* recipe.

Read-only SQLite, zero external services, no generative model or SQL from the
LLM. The tool retrieves evidence, not answers. The confidence gate is NOT
calibrated; refine only after independent evaluation on held-out recipes.

Usage:
  python recipe_search.py --db recipes_normalized.sqlite \
      --recipe-id 'recipe_nlg_lite:...' --query 'When do I add sugar?'
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import re
import sqlite3
import unicodedata
from pathlib import Path

_WORD = re.compile(r"[\w]+", re.UNICODE)
_STOP = frozenset("""
 a an and are as at be before by can could do does for from had has have how
 i in into is it its me my of on or our should some that the their them there
 these they this those to use used using want was were what when where which
 while who why will with would you your about after between exactly list recipe
 instructions ingredient ingredients ingredients' step steps preparation method
 amount amounts question make making need get say says stated show tell tellme
 que qual quais quanto quantos quando onde como para por uma um do da dos das
 de no na nos nas e ou esta este isto receita ingredientes preparacao preparo
""".split())


def _fold(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', s.casefold()) if not unicodedata.combining(c))


def tokens(s: str) -> list[str]:
    out=[]
    for t in _WORD.findall(_fold(s)):
        if t in _STOP or len(t)<2 or t.isdigit():
            continue
        # Deliberately conservative suffix treatment, not a lexicon/translator.
        if len(t)>5 and t.endswith('ies'):
            t=t[:-3]+'y'
        elif len(t)>4 and t.endswith('s') and not t.endswith(('ss','us')):
            t=t[:-1]
        out.append(t)
    return out


def _char_grams(words: list[str]) -> collections.Counter:
    c=collections.Counter()
    for w in words:
        if len(w)<3:
            c[w]+=1
        else:
            c.update(w[i:i+3] for i in range(len(w)-2))
    return c


def _cosine(a: collections.Counter,b: collections.Counter) -> float:
    if not a or not b: return 0.0
    norm1=math.sqrt(sum(v*v for v in a.values()))
    norm2=math.sqrt(sum(v*v for v in b.values()))
    return sum(v*b.get(k,0) for k,v in a.items())/max(1e-12,norm1*norm2)


class RecipeSearch:
    def __init__(self, db_path: str | Path, max_evidence: int=4):
        self.db_path=Path(db_path)
        if not self.db_path.is_file():
            raise FileNotFoundError(self.db_path)
        self.conn=sqlite3.connect(f'{self.db_path.resolve().as_uri()}?mode=ro',uri=True)
        self.conn.row_factory=sqlite3.Row
        self.max_evidence=max_evidence
        self._cache={}  # per-instance, bounded; do not retain closed connections globally

    def close(self):
        self.conn.close()

    def _passages(self, recipe_id: str) -> tuple[dict,...]:
        if recipe_id in self._cache:
            return self._cache[recipe_id]
        # SQL parameters only. The model never supplies SQL or table names.
        found=self.conn.execute('SELECT recipe_id FROM recipes WHERE recipe_id=?',(recipe_id,)).fetchone()
        if not found: return ()
        rows=[]
        for r in self.conn.execute('SELECT position,raw,name,parse_status FROM ingredients WHERE recipe_id=? ORDER BY position',(recipe_id,)):
            rows.append({'section':'INGREDIENTS','position':r['position'],
                         'text':r['raw'],'parse_status':r['parse_status']})
        for r in self.conn.execute('SELECT position,text,parse_status FROM preparation_segments WHERE recipe_id=? ORDER BY position',(recipe_id,)):
            rows.append({'section':'PREPARATION','position':r['position'],
                         'text':r['text'],'parse_status':r['parse_status']})
        if len(self._cache) >= 1024:
            self._cache.clear()
        self._cache[recipe_id] = tuple(rows)
        return self._cache[recipe_id]

    def search(self, recipe_id: str, query: str) -> dict:
        """Return factual source passages, NEVER a generated answer.

        `FOUND` is a first-pass lexical signal, not certified truth or answer
        correctness. The whole C2 pipeline requires independent evaluation.
        """
        if not recipe_id or not isinstance(query,str) or not query.strip():
            return {'status':'INSUFFICIENT_EVIDENCE','evidence':[], 'reason':'invalid request'}
        passages=self._passages(recipe_id)
        if not passages:
            return {'status':'INSUFFICIENT_EVIDENCE','evidence':[], 'reason':'unknown or empty recipe'}
        q=tokens(query)
        if not q:
            return {'status':'INSUFFICIENT_EVIDENCE','evidence':[], 'reason':'no searchable terms'}
        doc_tokens=[tokens(d['text']) for d in passages]
        doc_count=len(passages)
        df=collections.Counter(t for ts in doc_tokens for t in set(ts))
        avgdl=sum(len(ts) for ts in doc_tokens)/doc_count or 1
        qg=_char_grams(q)
        hits=[]
        for d,dt in zip(passages,doc_tokens):
            cnt=collections.Counter(dt)
            bm25=0.0
            for term in set(q):
                tf=cnt.get(term,0)
                if not tf:continue
                idf=math.log(1.0+(doc_count-df[term]+0.5)/(df[term]+0.5))
                bm25+=idf*(tf*2.2/(tf+1.2*(0.25+0.75*len(dt)/avgdl)))
            charsim=_cosine(qg,_char_grams(dt))
            # Exact matching dominates; fuzzy overlap breaks ties and handles
            # inflection. A low char-only score must never cause a FOUND.
            score=bm25+1.4*charsim
            hits.append((score,bm25,charsim,d))
        hits.sort(key=lambda h:(-h[0],h[3]['section'],h[3]['position']))
        matched=[(s,b,c,d) for s,b,c,d in hits if b>0.0]
        # These are candidates only: shared query words do NOT establish
        # sufficient evidence for a composite or negated question.
        if not matched:
            return {'status':'INSUFFICIENT_EVIDENCE','evidence':[],
                    'reason':'no lexical evidence (manual/semantic retrieval needed)'}
        top=matched[:self.max_evidence]
        return {'status':'EVIDENCE_CANDIDATES','evidence':[
            {'section':d['section'],'position':d['position'],
             'text':d['text'], 'parse_status':d['parse_status'],
             'source_ref':f"{d['section'].lower()}:{d['position']}"}
            for s,b,c,d in top],
            'retrieval_note':'lexical candidates; relevance and completeness not independently certified'}

    @staticmethod
    def format_for_model(result: dict) -> str:
        lines=['TOOL RESULT',f"STATUS: {result['status']}"]
        if result['status']=='EVIDENCE_CANDIDATES':
            lines.append('EVIDENCE:')
            for e in result['evidence']:
                lines.append(f"{e['section']} {e['position']}: {e['text']}")
        else:
            lines.append('No sufficient evidence found in the available recipe segments.')
        return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db',type=Path,required=True)
    p.add_argument('--recipe-id',required=True)
    p.add_argument('--query',required=True)
    p.add_argument('--json',action='store_true')
    args=p.parse_args()
    tool=RecipeSearch(args.db)
    try:
        r=tool.search(args.recipe_id,args.query)
        print(json.dumps(r,ensure_ascii=False,indent=2) if args.json else tool.format_for_model(r))
    finally:
        tool.close()

if __name__=='__main__':
    main()