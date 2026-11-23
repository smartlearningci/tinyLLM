"""Experimental C2 evidence retrieval v2, inside one known recipe.

Python standard library at inference. Optional weakly-supervised section router
from train_section_router.py (trained using C2 TRAIN recipes only). No generated
SQL, no answer generation, no API call. Results are ALWAYS candidates, not fact
certifications. Do not use output as an SFT label without auditing.
"""
from __future__ import annotations
import argparse
import collections
import json
import math
import re
import unicodedata
from pathlib import Path

from recipe_search import RecipeSearch, tokens, _fold, _char_grams, _cosine

WORD = re.compile(r"\b\w+\b",re.UNICODE)
# Closed taxonomic hints: never treat unrecognised ingredients as certified
# non-allergens, non-sugars, or non-seasonings. Rules may be incomplete.
SEASONING_NAMES = frozenset('''paprika cumin coriander allspice rosemary pepper cayenne turmeric cinnamon nutmeg oregano thyme basil parsley dill sage chili chilli ginger garlic onion salt clove cardamom mustard fennel fenugreek tarragon mint saffron smoked five spice seasoning herb sumac'''.split())
SUGAR_NAMES = frozenset('''sugar sugars syrup molasses demerara muscovado caster icing confectioners granulated brown white honey jaggery'''.split())
CATEGORY = {'seasonings','seasoning','spices','spice','herbs','herb','temperos','especiarias','ervas'}
# Minimal bilingual lexicon for English-source recipes and Portuguese prompts.
# It is explicitly incomplete; unknown synonyms must not be invented.
PT_EN = {
 'acucar':'sugar','acucare':'sugar','ovo':'egg','farinha':'flour',
 'leite':'milk','manteiga':'butter','azeite':'oil','oleo':'oil',
 'iogurte':'yogurt','sal':'salt','pimenta':'pepper','canela':'cinnamon',
 'batata':'potato','cebola':'onion','alho':'garlic','tomate':'tomato',
 'limao':'lemon','laranja':'orange','mel':'honey','arroz':'rice',
 'frango':'chicken','carne':'meat','queijo':'cheese','agua':'water',
 'cenoura':'carrot','salsa':'parsley','coentros':'coriander',
 'paprica':'paprika','gengibre':'ginger','oregãos':'oregano',
 'adicionar':'add','adiciono':'add','adiciona':'add','acrescento':'add',
 'juntar':'add','junto':'add','misturar':'mix','misturo':'mix',
 'forno':'oven','cozer':'cook','assar':'bake','tempo':'time','momento':'when',
 'inicio':'first','fim':'last','etapa':'step','passo':'step',
}

def _lexical_tokens(question: str)->list[str]:
    original=tokens(question)
    return list(dict.fromkeys(original+[PT_EN[t] for t in original if t in PT_EN]))

EXCLUDE_RE = re.compile(r'\b(?:excluding|except|not\s+the|but\s+not|other\s+than|without|excluindo|exceto|menos|sem)\s+((?:the\s+|any\s+|os\s+|as\s+|o\s+|a\s+)?(?:sugars?|acucar(?:es)?|syrups?|mel|honey))\b',re.I)


def _router_tokens(s: str) -> list[str]:
    s=''.join(c for c in unicodedata.normalize('NFKD',s.lower()) if not unicodedata.combining(c))
    return WORD.findall(s)


def _router_probabilities(model:dict,question:str)->dict[str,float]:
    t=_router_tokens(question)
    terms=t+[a+' '+b for a,b in zip(t,t[1:])]
    counts=collections.Counter(terms)
    vocab=model['vocabulary'];idf=model['idf']
    weights={vocab[k]:(1.0+math.log(n))*idf[vocab[k]] for k,n in counts.items() if k in vocab}
    norm=math.sqrt(sum(x*x for x in weights.values()))
    if norm>0:weights={k:v/norm for k,v in weights.items()}
    logits=[b+sum(coef[k]*w for k,w in weights.items()) for coef,b in zip(model['coef'],model['intercept'])]
    m=max(logits); exps=[math.exp(v-m) for v in logits];total=sum(exps)
    return {c:round(v/total,5) for c,v in zip(model['classes'],exps)}


def _kind(question:str,probs:dict[str,float]) -> str:
    t=_fold(question)
    wants_ingredients=bool(re.search(r'\b(ingredients?|ingredientes?|quantities|quantidades|how much|quanto|dose|how many\s+(?:cups?|tablespoons?|teaspoons?|grams?|g\b)|amount|measure)\b',t))
    wants_preparation=bool(re.search(r'\b(steps?|instructions?|preparation|method|how to|when|next|before|after|during|cook|bake|roast|minutes?|hours?|time|momento|altura|adicionar|adiciono|juntar|acrescentar|quando|passos?|preparacao|durante|antes|depois|forno|minutos?|horas?|mix(?:ture|ing)?|combine|assemble|assembly|dressing|marinade|filling|layer|topping|stage|finish|near|add|put)\b|\bgo(?:es)?\s+(?:in|into|over)\b',t))
    if wants_ingredients and wants_preparation:return 'MIXED'
    if wants_ingredients:return 'INGREDIENTS'
    if wants_preparation:return 'PREPARATION'
    if probs:
        choice=max(probs,key=probs.get)
        if probs[choice]>=0.62:return choice
    return 'MIXED'


def _is_sugar(name:str)->bool:
    return bool(set(tokens(name)) & SUGAR_NAMES)


def _is_seasoning(name:str)->bool:
    return bool(set(tokens(name)) & SEASONING_NAMES)


def _stripped_name(name:str)->list[str]:
    # Ingredient `name` is already quantity-free. Ignore packaging/adjectives.
    return [w for w in tokens(name) if w not in {'fresh','ground','powder','powdered','dried','dry','crushed','chopped','minced','finely','large','small','extra','virgin','organic','unsalted','optional','medium','whole','white','red','green','brown','slice','cup','clove','tablespoon','teaspoon'}]


def _mentions(question:str,passages:tuple[dict,...]):
    qwords=set(_lexical_tokens(question))
    candidates=[]
    for d in passages:
        if d['section']!='INGREDIENTS':continue
        name=d.get('name') or d['text']
        keys=_stripped_name(name)
        if not keys:continue
        present=[x for x in keys if x in qwords]
        if present and (len(keys)==1 or len(present)/len(keys) >= 0.5 or len(present)>=2):
            candidates.append((d,tuple(present)))
    # Drop spurious overlaps with stop-/category-like ingredient words.
    result=[]
    for d,keys in candidates:
        if not any(k in {'ingredient','food','item','spice','herb','seasoning','recipe','step','other'} for k in keys):
            result.append((d,keys))
    return result


def _bm25_ranking(passages:list[dict],terms:list[str]):
    if not terms:return []
    dt=[tokens(d['text']) for d in passages]
    N=len(dt);df=collections.Counter(t for seq in dt for t in set(seq));avg=sum(len(x) for x in dt)/max(1,N) or 1
    grams=_char_grams(terms)
    scores=[]
    for d,seq in zip(passages,dt):
        cnt=collections.Counter(seq); bm=0.0
        for term in set(terms):
            tf=cnt[term]
            if tf:
                idf=math.log(1+(N-df[term]+0.5)/(df[term]+0.5))
                bm+=idf*(tf*2.2/(tf+1.2*(0.25+0.75*len(seq)/avg)))
        fuzzy=_cosine(grams,_char_grams(seq))
        scores.append((bm+1.4*fuzzy,bm,d))
    return sorted(scores,key=lambda x:(-x[0],x[2]['position']))


class RecipeSearchV2(RecipeSearch):
    def __init__(self,db_path:str|Path,router_path:Path|None=None,max_evidence:int=8,max_chars:int=1800):
        super().__init__(db_path,max_evidence=max_evidence)
        self.max_chars=max_chars
        self.router=None
        if router_path is not None:
            data=json.loads(Path(router_path).read_text(encoding='utf8'))
            if data.get('schema')!='tinyslm-section-router-1':raise ValueError('Unsupported router model')
            self.router=data

    def __enter__(self):
        return self

    def __exit__(self,exc_type,exc,tb):
        self.close()

    def _passages(self,recipe_id:str):
        # Keep the same parameterised SQL as baseline, adding normalized name
        # for conservative ingredient matching. Both original and parsed fields
        # are preserved; ambiguity warnings remain visible.
        key='v2:'+recipe_id
        if key in self._cache:return self._cache[key]
        if not self.conn.execute('SELECT 1 FROM recipes WHERE recipe_id=?',(recipe_id,)).fetchone():return ()
        rows=[]
        for r in self.conn.execute('SELECT position,raw,name,parse_status FROM ingredients WHERE recipe_id=? ORDER BY position',(recipe_id,)):
            rows.append({'section':'INGREDIENTS','position':r['position'],'text':r['raw'],'name':r['name'],'parse_status':r['parse_status']})
        for r in self.conn.execute('SELECT position,text,parse_status FROM preparation_segments WHERE recipe_id=? ORDER BY position',(recipe_id,)):
            rows.append({'section':'PREPARATION','position':r['position'],'text':r['text'],'parse_status':r['parse_status']})
        if len(self._cache)>=1024:self._cache.clear()
        self._cache[key]=tuple(rows)
        return self._cache[key]

    def search(self,recipe_id:str,query:str)->dict:
        if not isinstance(query,str) or not query.strip() or not recipe_id:
            return {'status':'INSUFFICIENT_EVIDENCE','reason':'invalid request','evidence':[]}
        passages=self._passages(recipe_id)
        if not passages:return {'status':'INSUFFICIENT_EVIDENCE','reason':'unknown or empty recipe','evidence':[]}
        qnorm=_fold(query);q=_lexical_tokens(query)
        if not q:return {'status':'INSUFFICIENT_EVIDENCE','reason':'no query terms','evidence':[]}
        probs=_router_probabilities(self.router,query) if self.router else {}
        section=_kind(query,probs)
        excl=EXCLUDE_RE.search(qnorm)
        exclusions={'sugar'} if excl else set()
        terms=[x for x in q if x not in (SUGAR_NAMES if exclusions else set()) and x not in CATEGORY]
        group_seasoning=bool(set(_router_tokens(query)) & CATEGORY)
        group_sugar=bool(re.search(r'\b(?:sugars?|acucar(?:es)?)\b',qnorm)) and not excl
        is_list=bool(re.search(r'\b(which|list|all|what|quais|lista|todos|gather|set out)\b',qnorm))
        all_ingredients=bool(re.search(r'\b(?:all|every|todos|todas)\b.*\b(?:ingredients?|ingredientes?)\b',qnorm))
        quantity=bool(re.search(r'\b(?:how much|how many|amount|quantity|quantidade|quanto|quanta|quantos)\b',qnorm)) and not bool(re.search(r'\b(?:minutes?|hours?|minutos?|horas?|time|tempo|long|demora)\b',qnorm))
        mentioned=_mentions(query,passages)
        mentioned_keys={w for _,keys in mentioned for w in keys}
        ingredient_section=[p for p in passages if p['section']=='INGREDIENTS']
        step_section=[p for p in passages if p['section']=='PREPARATION']
        chosen=[];strategy='ranked_passages'
        if group_seasoning and is_list and section != 'MIXED':
            chosen=[x for x in ingredient_section if _is_seasoning(x['name']) and not (_is_sugar(x['name']) and exclusions)]
            strategy='conservative_seasoning_taxonomy'
        elif group_sugar and is_list and section != 'MIXED':
            chosen=[x for x in ingredient_section if _is_sugar(x['name'])]
            strategy='sugar_taxonomy'
        elif all_ingredients and section!='PREPARATION':
            chosen=ingredient_section;strategy='full_ingredient_list'
        elif quantity and mentioned:
            chosen=[d for d,keys in mentioned if not (_is_sugar(d['name']) and exclusions)]
            strategy='quantity_by_ingredient'
        elif section=='INGREDIENTS' and mentioned and not bool(re.search(r'\b(?:mix(?:ture|ing)?|combine|marinade|dressing|layer|filling|topping|assemble|near|before|after|when|stage|put|add)\b|\bgo(?:es)?\s+(?:in|into|over)\b',qnorm)):
            chosen=[d for d,keys in mentioned if not (_is_sugar(d['name']) and exclusions)]
            strategy='ingredient_by_name'
        if not chosen:
            pool=passages
            ranks=_bm25_ranking(list(pool),terms)
            # Section routing is soft, not a hard filter. Mixed intent may need both.
            def boost(item):
                score,bm,d=item
                s=score
                if section==d['section']:s+=1.2
                elif section!='MIXED':s-=0.25
                if d['section']=='PREPARATION' and mentioned_keys and (set(tokens(d['text']))&mentioned_keys):s+=1.5
                if d['section']=='INGREDIENTS' and mentioned and d in [p for p,_ in mentioned]:s+=1.2
                if d['section']=='INGREDIENTS' and exclusions and _is_sugar(d['name']):s-=15
                return (s,bm,d)
            ranks.sort(key=lambda x:(-boost(x)[0],-x[1],x[2]['position']))
            chosen=[d for _,bm,d in ranks if bm>0]
            if exclusions:chosen=[d for d in chosen if not (d['section']=='INGREDIENTS' and _is_sugar(d['name']))]
            if not chosen:return {'status':'INSUFFICIENT_EVIDENCE','evidence':[],
                                  'reason':'no matching evidence in known recipe',
                                  'section_hint':section,'router_probabilities':probs}
            # Preserve at least one passage for each matched ingredient in mixed/
            # multi-target queries instead of selecting only a lexical winner.
            if mentioned and section in ('PREPARATION','MIXED'):
                seen=set();mandatory=[]
                for d,keys in mentioned:
                    for w in keys:
                        found=[p for p in step_section if w in tokens(p['text'])]
                        if found:
                            p=found[0]
                            k=(p['section'],p['position'])
                            if k not in seen:seen.add(k);mandatory.append(p)
                chosen=mandatory+[d for d in chosen if (d['section'],d['position']) not in seen]
        # Conservative adjacency: when sequencing is requested, also show the
        # immediately preceding operation to establish 'when' and 'after'.
        if chosen and bool(re.search(r'\b(?:when|before|after|next|order|step|quando|antes|depois|passo)\b',qnorm)):
            extra=[];already={(p['section'],p['position']) for p in chosen[:self.max_evidence]}
            for p in chosen[:2]:
                if p['section']=='PREPARATION' and p['position']>1:
                    candidate=next((x for x in step_section if x['position']==p['position']-1),None)
                    if candidate and (candidate['section'],candidate['position']) not in already:
                        extra.append(candidate);already.add((candidate['section'],candidate['position']))
            chosen=chosen[:3]+extra+chosen[3:]
        # If a list would exceed context budget we return a PARTIAL candidate
        # and explicitly say it is incomplete; never claim an exhaustive list.
        evidence=[];used=0
        for p in chosen:
            if len(evidence)>=self.max_evidence:break
            if used+len(p['text'])>self.max_chars:
                continue
            evidence.append({'section':p['section'],'position':p['position'],
                             'text':p['text'],'parse_status':p['parse_status'],
                             'source_ref':f"{p['section'].lower()}:{p['position']}"})
            used+=len(p['text'])
        if not evidence:return {'status':'INSUFFICIENT_EVIDENCE','reason':'candidate evidence exceeds context budget','evidence':[]}
        total_candidate=len(chosen)
        result={'status':'EVIDENCE_CANDIDATES','evidence':evidence,
                'section_hint':section,'strategy':strategy,
                'retrieval_note':'Unverified source excerpts, not a validated answer',
                'candidate_count':total_candidate,'truncated':len(evidence)<total_candidate,
                'router_probabilities':probs}
        if exclusions:result['exclusions_applied']=list(sorted(exclusions))
        if result['truncated']:result['warning']='Results incomplete; cannot claim exhaustive coverage'
        if group_seasoning:result['warning']='Taxonomy is incomplete: do not claim an exhaustive or allergy-safe ingredient list'
        return result

    @staticmethod
    def format_for_model(result:dict)->str:
        lines=['TOOL RESULT',f"STATUS: {result['status']}"]
        if result['status']=='EVIDENCE_CANDIDATES':
            lines.append('EVIDENCE:')
            for e in result['evidence']:
                lines.append(f"{e['section']} {e['position']}: {e['text']}")
            if result.get('truncated'):lines.append('WARNING: INCOMPLETE_RESULTS')
            if result.get('warning') and not result.get('truncated'):lines.append('WARNING: REVIEW_REQUIRED')
        else:lines.append('No sufficient evidence was found in the known recipe.')
        return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True);p.add_argument('--recipe-id',required=True)
    p.add_argument('--query',required=True);p.add_argument('--router',type=Path)
    p.add_argument('--json',action='store_true');a=p.parse_args()
    with RecipeSearchV2(a.db,router_path=a.router) as r:
        result=r.search(a.recipe_id,a.query)
        print(json.dumps(result,ensure_ascii=False,indent=2) if a.json else r.format_for_model(result))

if __name__=='__main__':main()