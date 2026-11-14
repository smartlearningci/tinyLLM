#!/usr/bin/env python3
"""Recupera respostas validas de lotes economicos arquivados; sem chamar Codex."""
import json
import sqlite3
from pathlib import Path
import distill

ROOT = Path(__file__).resolve().parent

def main():
    raw = ROOT / "dados" / "raw"
    out = ROOT / "dados" / "respostas" / "recuperacao_economica"
    out.mkdir(parents=True, exist_ok=True)
    recovered = []
    problems = []
    with sqlite3.connect(ROOT / "dados" / "queue.sqlite") as db:
        db.row_factory = sqlite3.Row
        for manifest_path in sorted(raw.glob("eco-*.manifest.json")):
            response_path = raw / manifest_path.name.replace(".manifest.json", ".response.json")
            if not response_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                response = json.loads(response_path.read_text(encoding="utf-8"))
                items = response["responses"]
                if not isinstance(items, list):
                    raise ValueError("responses nao e lista")
                ids = set(manifest["job_ids"])
                seen = set()
                for item in items:
                    jid = item.get("job_id") if isinstance(item, dict) else None
                    if jid not in ids or jid in seen:
                        raise ValueError("ID desconhecido ou repetido")
                    seen.add(jid)
                for item in items:
                    jid = item["job_id"]
                    job = db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
                    if job is None or job["status"] != "error" or job["provider"] != "codex-economico":
                        continue
                    try:
                        distill.validate_response(item, json.loads(job["request"]))
                    except ValueError as exc:
                        problems.append((jid, str(exc)))
                        continue
                    recovered.append(item)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                problems.append((manifest_path.name, str(exc)))
    # Evita IDs duplicados se o mesmo pedido estiver arquivado em varios lotes.
    recovered = list({item["job_id"]: item for item in recovered}.values())
    path = out / "respostas_validas.json"
    if recovered:
        distill.write_json(path, recovered)
        print(f"{len(recovered)} pedidos validos recuperaveis, {len(problems)} avisos.")
        print("Ficheiro:", path)
        print("Importar com: python distill.py import dados/respostas/recuperacao_economica/respostas_validas.json --provider codex-economico --teacher gpt-6-luna")
    else:
        print("Nenhuma resposta valida pendente de importacao.")
    for jid, reason in problems[:20]:
        print("REVER:", jid, reason)

if __name__ == "__main__":
    main()
