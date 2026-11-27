import argparse, json, sqlite3, time, re, hashlib
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.robotparser import RobotFileParser
from urllib.error import HTTPError
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

BASE='https://www.pingodoce.pt/'
UA='TinySLM-research/0.1'
class HTML(HTMLParser):
    def __init__(self):
        super().__init__(); self.active=False; self.blocks=[]; self.buf=[]
    def handle_starttag(self,tag,attrs):
        if tag=='script' and dict(attrs).get('type')=='application/ld+json': self.active=True; self.buf=[]
    def handle_data(self,data):
        if self.active: self.buf.append(data)
    def handle_endtag(self,tag):
        if tag=='script' and self.active:
            self.active=False
            try: self.blocks.append(json.loads(''.join(self.buf)))
            except ValueError: pass
class Plain(HTMLParser):
    def __init__(self): super().__init__(); self.parts=[]
    def handle_data(self,d): self.parts.append(d)
def clean(s):
    p=Plain(); p.feed(str(s or '')); return ' '.join(''.join(p.parts).split())
def nodes(x):
    if isinstance(x,list):
        for v in x: yield from nodes(v)
    elif isinstance(x,dict):
        yield x
        if '@graph' in x: yield from nodes(x['@graph'])
def typed(x,t):
    tipos = x.get('@type') or []
    return t in ([tipos] if isinstance(tipos, str) else tipos if isinstance(tipos, list) else [])
def steps(x):
    if isinstance(x,str): return [clean(x)] if clean(x) else []
    if isinstance(x,list): return [s for item in x for s in steps(item)]
    if isinstance(x,dict): return steps(x.get('itemListElement') or x.get('text') or '')
    return []
def minutes(x):
    m=re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?',str(x)); return (int(m[1] or 0)*60+int(m[2] or 0) or None) if m else None
def parse(html,kind):
    p=HTML(); p.feed(html); ns=list(nodes(p.blocks)); target='Recipe' if kind=='recipe' else 'HowTo'
    r=next((x for x in ns if typed(x,target)),None)
    if r is None: return None,p.blocks
    ingredients=[clean(x) for x in r.get('recipeIngredient',[]) if isinstance(x,str) and clean(x)]
    prep=steps(r.get('recipeInstructions') if kind=='recipe' else r.get('step'))
    title=clean(r.get('name'))
    if not title or not prep or (kind=='recipe' and not ingredients): return None,p.blocks
    record=dict(title=title,ingredients=ingredients,steps=prep,servings=r.get('recipeYield'),category=r.get('recipeCategory'),prep_minutes=minutes(r.get('prepTime')),cook_minutes=minutes(r.get('cookTime')),total_minutes=minutes(r.get('totalTime')))
    return record,p.blocks

def main():
    a=argparse.ArgumentParser(); a.add_argument('--db',default='dados/culinaria/pingodoce.sqlite'); a.add_argument('--collect',action='store_true'); a.add_argument('--permission-confirmed',action='store_true'); a.add_argument('--delay',type=float,default=2); a.add_argument('--limit',type=int); args=a.parse_args()
    if args.collect and not args.permission_confirmed: a.error('Confirm permitted collection and use before running --collect.')
    path=Path(args.db); path.parent.mkdir(parents=True,exist_ok=True); db=sqlite3.connect(path)
    db.execute('CREATE TABLE IF NOT EXISTS pages(url TEXT PRIMARY KEY, kind TEXT, status TEXT, raw TEXT, normalized TEXT, error TEXT)')
    db.commit()
    if not args.collect:
        print(db.execute('SELECT kind,status,count(*) FROM pages GROUP BY kind,status').fetchall()); return
    def fetch(url):
        if urlparse(url).hostname!='www.pingodoce.pt': raise ValueError('Unexpected host')
        time.sleep(max(2,args.delay))
        with urlopen(Request(url,headers={'User-Agent':UA}),timeout=30) as r: return r.read()
    robots=RobotFileParser(); robots.parse(fetch(BASE+'robots.txt').decode().splitlines())
    ns={'s':'http://www.sitemaps.org/schemas/sitemap/0.9'}
    def get(url):
        if not robots.can_fetch(UA,url): raise ValueError('Disallowed by robots.txt')
        return fetch(url)
    index=ET.fromstring(get(BASE+'sitemap.xml'))
    for loc in index.findall('s:sitemap/s:loc',ns):
        name=loc.text.rsplit('/',1)[-1]
        if not re.fullmatch(r'recipe-sitemap\d*\.xml|cooking_techniques-sitemap\d*\.xml',name): continue
        kind='recipe' if name.startswith('recipe') else 'technique'
        root=ET.fromstring(get(loc.text))
        db.executemany('INSERT OR IGNORE INTO pages(url,kind,status) VALUES(?,?,\'pending\')',[(x.text,kind) for x in root.findall('s:url/s:loc',ns)])
        db.commit()
    rows=db.execute("SELECT url,kind FROM pages WHERE status IN ('pending','error') ORDER BY kind,url").fetchall()
    for url,kind in rows[:args.limit]:
        try:
            data,raw=parse(get(url).decode('utf-8'),kind)
            status='accepted' if data else 'review'
            db.execute('UPDATE pages SET status=?,raw=?,normalized=?,error=NULL WHERE url=?',(status,json.dumps(raw,ensure_ascii=False),json.dumps(data,ensure_ascii=False) if data else None,url))
        except HTTPError as e:
            db.execute('UPDATE pages SET status=\'error\',error=? WHERE url=?',(str(e),url)); db.commit()
            if e.code in (403,429,503): print('Stopped:',e); break
        except Exception as e: db.execute('UPDATE pages SET status=\'error\',error=? WHERE url=?',(str(e),url))
        db.commit(); print(kind,url,flush=True)
    print(db.execute('SELECT kind,status,count(*) FROM pages GROUP BY kind,status').fetchall())
    out=path.with_suffix('.jsonl')
    with out.open('w',encoding='utf-8') as f:
        for url,kind,raw in db.execute("SELECT url,kind,normalized FROM pages WHERE status='accepted' ORDER BY url"):
            r=json.loads(raw); context='Receita: ' if kind=='recipe' else 'Técnica: '; context+=r['title']+'\n'
            if r['servings']: context+='Doses: '+str(r['servings'])+'\n'
            if r['ingredients']: context+='Ingredientes:\n'+'\n'.join(r['ingredients'])+'\n'
            context+='Preparação:\n'+'\n'.join(f'{i}. {s}' for i,s in enumerate(r['steps'],1))
            f.write(json.dumps(dict(url=url,kind=kind,context=context),ensure_ascii=False)+'\n')
if __name__=='__main__': main()