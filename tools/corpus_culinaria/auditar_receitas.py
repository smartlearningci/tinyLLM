"""Auditoria conservadora de receitas. Não altera a base original."""
import argparse
import csv
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

def audit(db, out):
    out.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True)
    rows = conn.execute("SELECT url, normalized FROM pages WHERE kind='recipe' AND status='accepted' ORDER BY url").fetchall()
    conn.close()
    counts = Counter()
    titles = Counter()
    recipes = []
    issues = []
    def flag(url, field, code, original):
        counts[code] += 1
        issues.append(dict(url=url, field=field, issue=code, original=original, correction="", decision=""))
    for url, raw in rows:
        r = json.loads(raw)
        titles[r["title"].strip().casefold()] += 1
        recipes.append((url, r))
    with (out / "receitas_normalizadas.jsonl").open("w", encoding="utf-8") as f:
        for url, r in recipes:
            cleaned = dict(r)
            cleaned["ingredients"] = []
            for i, original in enumerate(r["ingredients"]):
                s = " ".join(original.split())
                s = re.sub(r"^1\s+q\.b\.\s+(.+)$", r"\1 q.b.", s, flags=re.I)
                s = re.sub(r"\bc\. de sopa\b", "colher de sopa", s)
                s = re.sub(r"\bc\. de chá\b", "colher de chá", s)
                if not re.match(r"^(?:\d|[¼½¾⅓⅔])", s) and not re.search(r"q\.b\.|a gosto", s, re.I):
                    flag(url, f"ingredients[{i}]", "quantity_uncertain", original)
                cleaned["ingredients"].append(s)
            operations = []
            for i, step in enumerate(r["steps"]):
                durations = re.findall(r"\b\d+(?:\s*(?:a|–|-)\s*\d+)?\s*(?:minutos?|horas?)\b", step, re.I)
                temperatures = re.findall(r"\b\d+\s*[°º]\s*C\b", step, re.I)
                if durations or temperatures:
                    operations.append(dict(step=i+1, durations=durations, temperatures=temperatures, evidence=step))
            cleaned["time_evidence"] = operations
            for field in ("servings", "prep_minutes", "cook_minutes", "total_minutes"):
                if r.get(field) in (None, "", 0):
                    flag(url, field, "missing_"+field, "")
            p,c,t = (r.get(k) for k in ("prep_minutes","cook_minutes","total_minutes"))
            if all(isinstance(v,(int,float)) and v>0 for v in (p,c,t)) and p+c!=t:
                flag(url,"times","time_inconsistent",json.dumps([p,c,t]))
            if titles[r["title"].strip().casefold()] > 1:
                flag(url,"title","duplicate_title",r["title"])
            f.write(json.dumps(dict(url=url, original=r, normalized=cleaned), ensure_ascii=False)+"\n")
    with (out / "revisao.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer=csv.DictWriter(f, fieldnames=["url","field","issue","original","correction","decision"])
        writer.writeheader()
        writer.writerows(issues)
    report=dict(recipes=len(rows), issues=dict(counts), recipes_with_issues=len({i["url"] for i in issues}))
    (out/"relatorio.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db",default="dados/culinaria/pingodoce.sqlite")
    p.add_argument("--out",default="dados/culinaria/auditoria")
    a=p.parse_args()
    audit(a.db,Path(a.out))
