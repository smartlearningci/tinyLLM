#!/usr/bin/env python3
"""Auditoria offline do TinyLLM: apenas leitura, sem Codex e sem alterar SQLite."""
import argparse
from collections import Counter, defaultdict
import datetime as dt
import json
from pathlib import Path
import random
import sqlite3

ROOT = Path(__file__).resolve().parent
PERSONAS = ["P1", "P2", "P3", "P4", "P5"]
CAPS = ["C1", "C2", "C3", "C4", "C5", "C6", "C7"]


def normal(s):
    return " ".join(str(s).casefold().split())


def audit_example(example, request):
    flags = []
    if not example.get("supported"):
        return ["unsupported"]
    messages = example.get("messages", [])
    roles = [m.get("role") for m in messages]
    minimum = 4 if example.get("capability") == "C6" else 2
    if len(roles) < minimum or len(roles) > 8 or roles != ["user", "assistant"] * (len(roles) // 2):
        flags.append("roles_or_turns")
    evidence = example.get("evidence", [])
    if not 1 <= len(evidence) <= 3:
        flags.append("evidence_count")
    sources = {x["source_id"]: x["text"] for x in [request["recipe"], *(request.get("knowledge") or [])]}
    for ev in evidence:
        source = sources.get(ev.get("source_id"))
        quote = ev.get("quote", "")
        if not source or not quote or normal(quote) not in normal(source):
            flags.append("quote_not_literal")
            break
    answers = [m.get("content", "") for m in messages if m.get("role") == "assistant"]
    if any(len(a.split()) < 5 for a in answers):
        flags.append("short_answer")
    if any(len(a.split()) > 210 for a in answers):
        flags.append("long_answer")
    if example.get("capability") == "C7" and example.get("evidence_type") != "E0":
        flags.append("c7_not_e0")
    return flags


def choose_sample(rows, per_cell, seed):
    rng = random.Random(seed)
    groups = defaultdict(list)
    for row in rows:
        groups[(row["persona"], row["capability"])].append(row)
    selection = []
    for p in PERSONAS:
        for cap in CAPS:
            options = groups[(p, cap)]
            selection.extend(rng.sample(options, min(per_cell, len(options))))
    return selection


def make_report(rows, selected, out):
    statuses = Counter(r["status"] for r in rows)
    personas = Counter(r["persona"] for r in rows)
    caps = Counter(r["capability"] for r in rows)
    flags = Counter(flag for r in rows for flag in r["flags"])
    answers = Counter(normal(m.get("content", "")) for r in rows
                      for m in r["example"].get("messages", [])
                      if m.get("role") == "assistant" and normal(m.get("content", "")))
    recurring = sum(n for n in answers.values() if n > 1)
    report = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "total_examples": len(rows),
        "distinct_jobs": len({r["job_id"] for r in rows}),
        "distinct_recipes": len({r["recipe_id"] for r in rows}),
        "statuses": dict(statuses), "personas": dict(personas),
        "capabilities": dict(caps), "mechanical_flags": dict(flags),
        "repeated_assistant_messages_occurrences": recurring,
        "sample_size": len(selected),
        "limitation": "A validacao automatica nao comprova a exatidao semantica nem a qualidade do modelo treinado."
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "resumo.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out / "amostra.jsonl").open("w", encoding="utf-8") as f:
        for row in selected:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    md = ["# TinyLLM — auditoria humana de conversas", "",
          "Nota: auto_valid verifica estrutura/citacoes; nao comprova qualidade factual.", "",
          "## Resumo", "",
          "Exemplos: " + str(len(rows)),
          "Receitas distintas representadas: " + str(report["distinct_recipes"]),
          "Amostra estratificada: " + str(len(selected)),
          "Mensagens do assistente repetidas literalmente: " + str(recurring), "",
          "Alertas mecanicos: " + json.dumps(dict(flags), ensure_ascii=False), "",
          "## Como rever cada conversa", "",
          "Pontuar de 0 a 2: fidelidade a receita, utilidade, naturalidade, adequacao a persona, comportamento.",
          "Rejeitar exemplos com informacao inventada ou quantidades, tempos e ingredientes errados.",
          "Separar qualidade dos dados de qualidade do modelo depois do treino.", ""]
    for index, row in enumerate(selected, 1):
        e = row["example"]
        md.extend(["## " + str(index) + ". " + row["persona"] + " / " + row["capability"]
                   + " — " + row["recipe_title"], "",
                   "ID: " + row["id"] + " | Estado: " + row["status"],
                   "Alertas: " + (", ".join(row["flags"]) if row["flags"] else "nenhum"), "",
                   "### Fonte original", "", "~~~", row["request"]["recipe"]["text"], "~~~", "",
                   "### Conversa", ""])
        for m in e.get("messages", []):
            md.extend([m.get("role", "?").upper() + ": " + m.get("content", ""), ""])
        md.extend(["### Evidencias", ""])
        for ev in e.get("evidence", []):
            md.append("- " + ev.get("source_id", "") + ": " + ev.get("quote", ""))
        md.extend(["", "Nota: " + e.get("evidence_note", ""), "",
                   "Fidelidade __/2 | Utilidade __/2 | Naturalidade __/2 | Persona __/2 | Comportamento __/2",
                   "Decisao: aceitar / rever / rejeitar", "", "---", ""])
    (out / "amostra_para_revisao.md").write_text("\n".join(md), encoding="utf-8")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--work", default=str(ROOT / "dados"))
    p.add_argument("--out", default=str(ROOT / "dados" / "auditoria"))
    p.add_argument("--per-cell", type=int, default=2)
    p.add_argument("--seed", type=int, default=42)
    a = p.parse_args()
    if not 1 <= a.per_cell <= 10:
        p.error("--per-cell entre 1 e 10.")
    path = Path(a.work).expanduser().resolve() / "queue.sqlite"
    if not path.is_file():
        p.error("Base nao encontrada: " + str(path))
    rows = []
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        sql = ("SELECT e.id,e.job_id,e.recipe_id,e.persona,e.capability,e.status,"
               "e.data,j.request,j.teacher,r.title FROM examples e "
               "JOIN jobs j ON e.job_id=j.id JOIN recipes r ON e.recipe_id=r.id "
               "WHERE e.status IN ('auto_valid','accepted','needs_review') ORDER BY e.id")
        for record in db.execute(sql):
            e = json.loads(record["data"])
            req = json.loads(record["request"])
            rows.append({"id": record["id"], "job_id": record["job_id"],
                         "recipe_id": record["recipe_id"], "persona": record["persona"],
                         "capability": record["capability"], "status": record["status"],
                         "recipe_title": record["title"], "teacher": record["teacher"],
                         "example": e, "request": req,
                         "flags": audit_example(e, req)})
    sample = choose_sample(rows, a.per_cell, a.seed)
    report = make_report(rows, sample, Path(a.out))
    print("Conversas:", report["total_examples"], "| Receitas:", report["distinct_recipes"],
          "| Amostra:", report["sample_size"])
    print("Alertas:", report["mechanical_flags"])
    print("Mensagens repetidas:", report["repeated_assistant_messages_occurrences"])
    print("Relatorios em:", Path(a.out))


if __name__ == "__main__":
    main()
