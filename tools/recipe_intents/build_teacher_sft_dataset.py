"""Audit Codex teacher labels and build an experimental Kaggle SFT package.

Teacher output is NOT automatically promoted to human-verified ground truth.
Question-only intent training uses no recipe contents. Rows without a recipe_id
are train-only, so they cannot leak into held-out recipe-grouped evaluation.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path
import random
import re
import zipfile


ALLOWED = {
    "ingredients": {"list", "check"},
    "quantity": {"get"},
    "steps": {"next", "explain", "rewrite"},
    "constraints": {"check", "substitute"},
    "unknown": {"unknown"},
}
REQUIRED_COUNT = 20_000

# Small, independently written negatives. Keep train and test wording distinct.
# These are assistant-curated, not human-verified reference labels.
OFFDOMAIN_TRAIN = [
    "Who won the football league last season?",
    "What will the weather be like in Paris tomorrow?",
    "Explain how to fix a broken bicycle chain.",
    "Can you help me write a Python sorting algorithm?",
    "How much tax do I owe on my salary?",
    "Which stock should I invest in this week?",
    "When does the next train leave for Lisbon?",
    "Who is the current prime minister of Canada?",
    "What is the capital of Mongolia?",
    "Summarize the plot of a science fiction novel.",
    "What are the symptoms of influenza?",
    "How do I improve my chess opening?",
    "Why is my Wi-Fi connection so slow?",
    "How can I open a new bank account?",
    "How do CSS flexbox and grid differ?",
    "Which video game console has better graphics?",
    "How far is the moon from Earth?",
    "Can you book a hotel room for Friday?",
    "What tools does a plumber need to repair a tap?",
    "Is there a traffic jam on the motorway?",
    "When will that new movie be released?",
    "What caused the fall of the Roman Empire?",
    "How do I train a puppy to sit?",
    "What is Newton's second law of motion?",
    "Please translate this legal contract into Spanish.",
    "How should I tune an acoustic guitar?",
    "What are the dimensions of a basketball court?",
    "Can you explain the rules of cricket?",
    "How do I send an encrypted email?",
    "What is the population of Tokyo?",
    "Who painted the ceiling of the Sistine Chapel?",
    "Can you calculate my mortgage interest payments?",
    "How do I clean the cache in my browser?",
    "Why does my car engine make a rattling sound?",
    "How do I buy a ticket to the opera?",
]
OFFDOMAIN_TEST = [
    "Who scored the winning goal in the match yesterday?",
    "What is the forecast for heavy rain this weekend?",
    "Why does my laptop battery drain so quickly?",
    "Can you explain how blockchain consensus works?",
    "What is the process for renewing a passport?",
    "Which planet has the most moons?",
    "How can I learn to play the violin?",
    "Is my flight to Tokyo delayed?",
    "When does the local library close today?",
    "How do I change my car's brake pads?",
    "Who wrote the play Hamlet?",
    "How do I configure a Linux firewall?",
    "What exercises improve my running endurance?",
    "How does a solar eclipse occur?",
    "How can I improve my portrait photography?",
]


def normalise(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip().casefold())


def jsonl(items: list[dict]) -> bytes:
    return ("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
                    for item in items)).encode("utf-8")


def read_zip_jsonl(source: Path, filename: str) -> list[dict]:
    with zipfile.ZipFile(source) as archive:
        if archive.testzip() is not None:
            raise ValueError("O ZIP do professor está danificado")
        with archive.open(filename) as stream:
            return [json.loads(line) for line in stream if line.strip()]


def split_for_recipe(recipe_id: str | None) -> str:
    if not recipe_id:
        return "train"  # not enough provenance to certify a held-out recipe
    score = int(hashlib.sha256(("intents-v09:" + str(recipe_id)).encode()).hexdigest()[:8], 16) % 10_000
    return "test" if score < 750 else "validation" if score < 1_500 else "train"


def build(source: Path, destination: Path, review_csv: Path) -> dict:
    rows = read_zip_jsonl(source, "teacher_intents_unverified.jsonl")
    if len(rows) != REQUIRED_COUNT:
        raise ValueError(f"Esperados {REQUIRED_COUNT} exemplos; recebidos {len(rows)}")

    ids: set[str] = set()
    questions: set[str] = set()
    split_rows: dict[str, list[dict]] = {x: [] for x in ("train", "validation", "test")}
    warnings: list[dict] = []
    origins = Counter()
    labels = Counter()
    agreement = Counter()
    provenance = Counter()

    for index, row in enumerate(rows):
        question = row.get("question", "").strip()
        teacher = row.get("teacher") or {}
        intent, operation = teacher.get("intent"), teacher.get("operation")
        identifier = hashlib.sha256(question.encode("utf-8")).hexdigest()[:20]
        if not question or row.get("id") != identifier or teacher.get("id") != identifier:
            raise ValueError(f"ID/pergunta inválida na linha {index + 1}")
        key = normalise(question)
        if identifier in ids or key in questions:
            raise ValueError(f"Pergunta repetida na linha {index + 1}")
        ids.add(identifier)
        questions.add(key)
        if intent not in ALLOWED:
            raise ValueError(f"Intenção desconhecida na linha {index + 1}: {intent}")

        origins[row.get("origin", "unspecified")] += 1
        labels[f"{intent}/{operation}"] += 1
        if row.get("candidate"):
            agreement["candidate_total"] += 1
            if (row["candidate"].get("intent"), row["candidate"].get("operation")) == (intent, operation):
                agreement["candidate_equal"] += 1

        entry = {
            "id": identifier,
            "question": question,
            "intent": intent,
            "operation": operation,
            "recipe_id": row.get("recipe_id"),
            "source": row.get("origin", "unspecified"),
            "label_status": "teacher_unverified",
        }
        if operation not in ALLOWED[intent] or teacher.get("taxonomy_warning"):
            entry["review_reason"] = "invalid_intent_operation_combination"
            warnings.append(entry)
            continue

        part = split_for_recipe(entry["recipe_id"])
        provenance["no_recipe_id_train_only"] += not bool(entry["recipe_id"])
        split_rows[part].append(entry)

    for part, prompts in (("train", OFFDOMAIN_TRAIN), ("test", OFFDOMAIN_TEST)):
        for question in prompts:
            key = normalise(question)
            if key in questions:
                raise ValueError(f"Exemplo fora do domínio repetido: {question}")
            identifier = hashlib.sha256(question.encode("utf-8")).hexdigest()[:20]
            questions.add(key)
            ids.add(identifier)
            split_rows[part].append({
                "id": identifier, "question": question,
                "intent": "unknown", "operation": "unknown",
                "recipe_id": None, "source": "assistant_curated_offdomain",
                "label_status": "assistant_curated_unverified",
            })

    if not all(split_rows.values()):
        raise ValueError("Divisão vazia; verificar os identificadores das receitas")

    rng = random.Random(42)
    review = []
    by_intent: dict[str, list[dict]] = {i: [] for i in ALLOWED}
    for entries in split_rows.values():
        for row in entries:
            by_intent[row["intent"]].append(row)
    for intent, subset in by_intent.items():
        review.extend(rng.sample(subset, min(30, len(subset))))
    review.extend(warnings[:50])
    rng.shuffle(review)

    out_counts = {part: len(entries) for part, entries in split_rows.items()}
    report = {
        "input_count": len(rows),
        "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "unique_teacher_question_count": len(rows),
        "unique_final_question_count": len(questions),
        "excluded_taxonomy_warnings": len(warnings),
        "offdomain_assistant_curated_train": len(OFFDOMAIN_TRAIN),
        "offdomain_assistant_curated_test": len(OFFDOMAIN_TEST),
        "splits": out_counts,
        "split_policy": "sha256(recipe_id), null recipe_id train only, 85/7.5/7.5 over recipe groups",
        "label_status": "teacher_unverified; experimental SFT, not human-certified",
        "teacher_labels": dict(sorted(labels.items())),
        "origins": dict(sorted(origins.items())),
        "agreement_with_weak_candidates": dict(agreement),
        "provenance": dict(provenance),
        "caveats": [
            "Validation and test contain teacher-labelled examples, not independently certified gold labels.",
            "Review unknown, mixed requests, quantity/get and rejected taxonomy combinations.",
            "Near-duplicate paraphrases across different recipes may remain; never publish model accuracy as human-grounded.",
            "Unknown is dominated by culinary compound questions; add audited off-domain negatives before deployment.",
            "Small additional off-domain negatives are assistant-curated, not independently human-verified.",
        ],
    }

    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for part, entries in split_rows.items():
            content = jsonl(entries)
            archive.writestr(part + ".jsonl", content)
            report[part + "_sha256"] = hashlib.sha256(content).hexdigest()
        archive.writestr("review_warnings.jsonl", jsonl(warnings))
        archive.writestr("sft_report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    review_csv.parent.mkdir(parents=True, exist_ok=True)
    with review_csv.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, lineterminator="\n",
                                fieldnames=["id", "question", "intent", "operation", "source",
                                            "recipe_id", "label_status", "review_reason"])
        writer.writeheader()
        for row in review:
            writer.writerow(row)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Criados: {destination}, {review_csv}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    args = parser.parse_args()
    build(args.input, args.output, args.review)


if __name__ == "__main__":
    main()
