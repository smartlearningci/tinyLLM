"""Build auditable C1/C2 candidates from historic dialogs and normalized recipes.

No teacher labels are assumed ground truth. The tool response is deliberately
NOT synthesized here: RECIPE_SEARCH must be evaluated independently first.

python build_c1_c2.py --dialogues train.jsonl --recipes recipes_normalized.sqlite --out out
"""
from __future__ import annotations
import argparse
import collections
import gzip
import hashlib
import json
import sqlite3
from pathlib import Path


CAPS = {"C1", "C2"}


def split_for_recipe(recipe_id: str) -> str:
    # Fixed by recipe, not by question: protects within-dataset evaluation.
    bucket = int(hashlib.sha256(recipe_id.encode()).hexdigest()[:12], 16) % 100
    return "train" if bucket < 80 else "validation" if bucket < 90 else "test"


def build(dialogues: Path, recipes: Path, out: Path) -> dict:
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"output folder is not empty: {out}")
    out.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(f"{recipes.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    source = {x["recipe_id"]: dict(x) for x in conn.execute(
        "SELECT recipe_id, title, canonical_text, original_text, warnings_json FROM recipes")}
    conn.close()
    counts = collections.Counter()
    by_split = collections.Counter()
    review = collections.Counter()
    warnings = collections.Counter()
    seen_ids = set()
    seen_recipe_splits = {}
    examples = []
    paths = {cap: out / f"{cap.lower()}_candidates.jsonl.gz" for cap in CAPS}
    handles = {cap: gzip.open(path, "wt", encoding="utf-8") for cap, path in paths.items()}
    reject_file = out / "review_queue.jsonl.gz"
    total_read = 0
    try:
        with gzip.open(reject_file, "wt", encoding="utf-8") as rejected, \
             dialogues.open(encoding="utf-8") as stream:
            for line in stream:
                total_read += 1
                item = json.loads(line)
                cap = item.get("capability")
                if cap not in CAPS:
                    continue
                counts[f"seen_{cap}"] += 1
                rid = item.get("recipe_id")
                recipe = source.get(rid)
                conversation = item.get("conversation") or []
                user_turns = [t.get("content") for t in conversation if t.get("role") == "user"]
                assistant_turns = [t.get("content") for t in conversation if t.get("role") == "assistant"]
                q = user_turns[-1].strip() if user_turns and isinstance(user_turns[-1], str) else ""
                answer = assistant_turns[-1].strip() if assistant_turns and isinstance(assistant_turns[-1], str) else ""
                evidences = item.get("evidence") or []
                reason = None
                if not recipe:
                    reason = "recipe_not_in_normalized_source"
                elif not q or not answer:
                    reason = "missing_question_or_answer"
                elif not evidences or not isinstance(evidences, list):
                    reason = "missing_evidence"
                elif any(not isinstance(e, dict) or not e.get("quote") or
                         e.get("source_id", rid) != rid or
                         e["quote"] not in recipe["original_text"] for e in evidences):
                    reason = "evidence_not_exact_in_source"
                if reason:
                    review[(cap, reason)] += 1
                    rejected.write(json.dumps({"id": item.get("id"), "capability": cap,
                        "recipe_id": rid, "reason": reason, "question": q,
                        "answer_teacher_unverified": answer, "evidence": evidences}, ensure_ascii=False)+"\n")
                    continue
                eid = item.get("id") or hashlib.sha256((rid+q).encode()).hexdigest()
                if eid in seen_ids:
                    review[(cap, "duplicate_example_id")] += 1
                    rejected.write(json.dumps({"id":eid,"capability":cap,
                        "recipe_id":rid,"reason":"duplicate_example_id"},ensure_ascii=False)+"\n")
                    continue
                seen_ids.add(eid)
                split = split_for_recipe(rid)
                if rid in seen_recipe_splits and seen_recipe_splits[rid] != split:
                    raise AssertionError("split conflict")
                seen_recipe_splits[rid] = split
                flags = json.loads(recipe["warnings_json"])
                for flag in flags:
                    warnings[(cap, flag)] += 1
                record = {
                    "id": eid, "capability": cap, "recipe_id": rid, "split": split,
                    "recipe_title": recipe["title"],
                    "normalized_recipe_reference": recipe["canonical_text"],
                    # This is a CANDIDATE context only, NOT a confirmed decision label.
                    # Never show the full reference in a C2 pre-tool prompt while
                    # simultaneously training CALL TOOL: it already contains the answer.
                    "candidate_decision_context": (
                        "RECIPE\nTITLE: " + recipe["title"] + "\nEVIDENCE FROM RECIPE:\n" +
                        "\n".join("- " + e["quote"] for e in evidences) if cap == "C1"
                        else "RECIPE\nTITLE: " + recipe["title"] +
                        "\nDETAILS: Not present in the supplied context."),
                    "question": q,
                    "conversation": conversation,
                    "historical_answer_teacher_unverified": answer,
                    "source_quotes": [e["quote"] for e in evidences],
                    "source_citations_exact": True,
                    "normalization_warnings": flags,
                    "training_approved": False,
                    "approval_reason": "teacher_answer_and_context_not_audited",
                    "tool_call_target": (
                        "CALL TOOL\nNAME: RECIPE_SEARCH\nQUERY: " + q
                        if cap == "C2" else None),
                    "tool_result_status": (
                        "PENDING_REAL_TOOL_EVALUATION" if cap == "C2" else "NOT_REQUIRED"),
                    "provenance": {"original_id": item.get("id"),
                        "original_split": item.get("provenance",{}).get("source",{}).get("original_split")},
                }
                handles[cap].write(json.dumps(record, ensure_ascii=False)+"\n")
                counts[f"candidate_{cap}"] += 1
                by_split[(cap,split)] += 1
                if flags: counts[f"candidate_{cap}_review_flags"] += 1
                if len(examples) < 4 and (not examples or cap != examples[-1]["capability"]):
                    examples.append({"id":eid,"capability":cap,"title":recipe["title"],
                        "question":q,"source_quote":evidences[0]["quote"],
                        "tool_call_target":record["tool_call_target"]})
    finally:
        for f in handles.values(): f.close()
    report = {
        "source_dialogue_rows": total_read,
        "source_recipes": len(source),
        "historical_counts": {cap:counts[f"seen_{cap}"] for cap in ("C1","C2")},
        "candidate_counts": {cap:counts[f"candidate_{cap}"] for cap in ("C1","C2")},
        "review_counts": {f"{cap}/{reason}":n for (cap,reason),n in sorted(review.items())},
        "candidate_with_normalization_warnings": {
            cap:counts[f"candidate_{cap}_review_flags"] for cap in ("C1","C2")},
        "by_split": {cap:{s:by_split[(cap,s)] for s in ("train","validation","test")}
                     for cap in ("C1","C2")},
        "unique_recipes_in_candidates":len(seen_recipe_splits),
        "checks": {"unique_example_ids": len(seen_ids) == sum(counts[f"candidate_{x}"] for x in CAPS),
                   "recipe_splits_disjoint":True,
                   "all_source_quotes_exact":True},
        "warnings": [
            "Teacher answers are NOT certified for training by quote presence alone.",
            "C2 tool call targets are candidate targets, not executed tool calls.",
            "C2 tool answers are absent pending separate RECIPE_SEARCH retrieval evaluation.",
            "Recipe tokenizer length and maximum context of 512 tokens not yet validated.",
            "Historical prior training may include these recipes; splits are only disjoint within this newly prepared dataset.",
            "Normalization warnings must be reviewed before any affected recipe is promoted to training.",
        ],
        "examples":examples,
    }
    (out / "stage3_report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dialogues",required=True,type=Path)
    p.add_argument("--recipes",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    a=p.parse_args()
    print(json.dumps(build(a.dialogues,a.recipes,a.out),indent=2,ensure_ascii=False))


if __name__ == "__main__": main()