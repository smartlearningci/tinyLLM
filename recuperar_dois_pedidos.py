#!/usr/bin/env python3
"""Recuperacao pontual auditavel de dois pedidos; SEM IA e SEM alterar SQLite."""
import copy
import json
import sqlite3
from pathlib import Path

import distill

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "dados" / "raw"
OUT = ROOT / "dados" / "respostas" / "recuperacao_pontual"
CASES = {
    "0e0b34a774b7b470fc1cc66a": "quote",
    "85095e84f1c0e36c9f0607fc": "roles",
}
OLD_QUOTE = "1.0 tablespoon chili powder, 1.0 tablespoon red pepper flakes, 0.5 teaspoon cayenne"
NEW_QUOTE = "1.0 tablespoon chili powder, 1.0 tablespoon red pepper flakes, 0.5 teaspoon cumin, 0.5 teaspoon cayenne"


def fix(raw, request, case):
    result = copy.deepcopy(raw)
    changes = []
    if case == "quote":
        source_id = request["recipe"]["source_id"]
        source = request["recipe"]["text"]
        if NEW_QUOTE not in source:
            raise ValueError("Passagem original nao encontrada; nao corrigir.")
        found = []
        for example in result["examples"]:
            for ev in example["evidence"]:
                if ev["source_id"] == source_id and ev["quote"] == OLD_QUOTE:
                    found.append((example, ev))
        if len(found) != 1:
            raise ValueError("Citacao a corrigir nao e unica.")
        example, ev = found[0]
        ev["quote"] = NEW_QUOTE
        changes.append({"slot": example["slot"], "before": OLD_QUOTE, "after": NEW_QUOTE})
    elif case == "roles":
        source = request["recipe"]["text"]
        if "chopped chives for garnish" not in source.casefold():
            raise ValueError("A fonte nao confirma o cebolinho.")
        target = [e for e in result["examples"] if e["slot"] == 2 and e["capability"] == "C1"]
        if len(target) != 1:
            raise ValueError("Slot 2/C1 nao encontrado.")
        e = target[0]
        msgs = e["messages"]
        if [m["role"] for m in msgs] != ["user", "assistant", "assistant"]:
            raise ValueError("A sequencia esperada mudou.")
        if "chives" not in msgs[2]["content"].casefold():
            raise ValueError("Resposta final nao menciona chives.")
        if "mint" in msgs[2]["content"].casefold():
            raise ValueError("Resposta final contem mint.")
        if "ham" not in msgs[0]["content"].casefold() or "garnish" not in msgs[0]["content"].casefold():
            raise ValueError("Pergunta inesperada.")
        e["messages"] = [msgs[0], msgs[2]]
        changes.append({"slot": 2, "removed": msgs[1], "kept": msgs[2]})
    else:
        raise ValueError("Caso desconhecido.")
    distill.validate_response(result, request)
    return result, changes


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    output = []
    audit = []
    with sqlite3.connect(ROOT / "dados" / "queue.sqlite") as db:
        db.row_factory = sqlite3.Row
        for jid, case in CASES.items():
            try:
                row = db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
                if row is None or row["status"] != "error":
                    raise ValueError("Pedido inexistente ou ja concluido.")
                request = json.loads(row["request"])
                originals = []
                for file in RAW.glob("eco-*.response.json"):
                    responses = json.loads(file.read_text(encoding="utf-8"))["responses"]
                    originals.extend((file, x) for x in responses if x.get("job_id") == jid)
                if len(originals) != 1:
                    raise ValueError("Resposta original ausente ou duplicada.")
                file, raw = originals[0]
                repaired, changes = fix(raw, request, case)
                output.append(repaired)
                audit.append({"job_id": jid, "origin": file.name, "changes": changes,
                              "full_validation": "passed"})
                print("VALIDADO:", jid)
            except (ValueError, TypeError, KeyError, OSError) as exc:
                print("NAO RECUPERADO:", jid, exc)
    path = OUT / "respostas_validadas.json"
    report = OUT / "auditoria.json"
    if output:
        distill.write_json(path, output)
        distill.write_json(report, audit)
        print("Reparacoes:", len(output), "| Auditar:", report)
        print("Ficheiro para importacao:", path)
    else:
        if path.exists():
            path.unlink()
        if report.exists():
            report.unlink()
        print("Nao existem respostas para importar.")


if __name__ == "__main__":
    main()
