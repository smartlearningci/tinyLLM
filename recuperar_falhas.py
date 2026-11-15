#!/usr/bin/env python3
"""Audita, recupera e reencaminha falhas sem interromper trabalhadores em execucao.

Por omissao apenas consulta. --recover importa respostas arquivadas e validadas.
--retry-errors reserva erros restantes para um trabalhador economico --retry-only.
"""
import argparse
import collections
import json
import sqlite3
from pathlib import Path

import distill
import reparacao_local

ROOT = Path(__file__).resolve().parent


def archived(work, db):
    """Indexa apenas respostas com ID unico no manifesto correspondente."""
    candidates = collections.defaultdict(list)
    warnings = []
    for manifest_path in sorted((work / "raw").glob("eco-*.manifest.json")):
        path = manifest_path.with_name(manifest_path.name.replace(".manifest.json", ".response.json"))
        if not path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            raw = distill.parse_response(path.read_text(encoding="utf-8"))
            entries = raw["responses"]
            if not isinstance(entries, list):
                raise ValueError("responses nao e lista")
            ids = set(manifest["job_ids"])
            counts = collections.Counter(x.get("job_id") for x in entries if isinstance(x, dict))
            for item in entries:
                if not isinstance(item, dict):
                    continue
                jid = item.get("job_id")
                if jid in ids and counts[jid] == 1:
                    candidates[jid].append((path.name, item))
            if any(not isinstance(x, dict) or x.get("job_id") not in ids for x in entries):
                warnings.append((path.name, "IDs estranhos; ignorados"))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            warnings.append((path.name, str(exc)))
    return candidates, warnings


def scan(db, candidates, max_attempts):
    stats = collections.Counter()
    ready = []
    repairs = []
    for job in db.execute("SELECT * FROM jobs WHERE status='error' AND provider='codex-economico'"):
        request = json.loads(job["request"])
        valid = None
        edits = []
        origin = ""
        for filename, item in candidates.get(job["id"], []):
            try:
                distill.validate_response(item, request)
                valid, origin = item, filename
                break
            except (ValueError, TypeError, KeyError):
                corrected, changes = reparacao_local.repair_response(item, request)
                if corrected is not None:
                    valid, edits, origin = corrected, changes, filename
                    break
        if valid is not None:
            ready.append((job, valid, origin, edits))
            stats["recuperaveis"] += 1
        elif job["attempts"] < max_attempts:
            stats["novas_tentativas_possiveis"] += 1
        else:
            stats["limite_tentativas"] += 1
        stats["erros"] += 1
    return stats, ready


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--recover", action="store_true", help="Importar respostas arquivadas validas.")
    actions.add_argument("--retry-errors", action="store_true", help="Reservar falhas para nova geracao individual.")
    parser.add_argument("--work", type=Path, default=ROOT / "dados")
    args = parser.parse_args()
    work = args.work.resolve()
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    max_attempts = config["max_attempts"]
    with sqlite3.connect(work / "queue.sqlite", timeout=30) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        candidates, warnings = archived(work, db)
        stats, ready = scan(db, candidates, max_attempts)
        print(f"Erros economicos: {stats['erros']}")
        print(f"Recuperaveis dos arquivos: {stats['recuperaveis']}")
        print(f"Elegiveis para nova chamada: {stats['novas_tentativas_possiveis']}")
        print(f"Ja no limite de tentativas: {stats['limite_tentativas']}")
        print(f"Avisos nos arquivos: {len(warnings)}")
        if args.recover:
            imported = audit = 0
            audit_rows = []
            for job, response, origin, edits in ready:
                # Importacao so para 'error'; um trabalhador nunca recebe estes IDs.
                db.execute("BEGIN IMMEDIATE")
                try:
                    current = db.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone()
                    if current["status"] != "error":
                        db.rollback()
                        continue
                    distill.store_response(db, current, response, "codex-economico",
                                           current["teacher"] or "gpt-6-luna")
                    db.commit()
                    imported += 1
                    if edits:
                        audit += 1
                        audit_rows.append({"job_id": job["id"], "origin": origin, "changes": edits})
                except BaseException:
                    db.rollback()
                    raise
            if audit_rows:
                location = work / "respostas" / "recuperacao_economica" / "auditoria_automatica.json"
                distill.write_json(location, audit_rows)
                print(f"Auditoria: {location}")
            print(f"Importados e validados: {imported}; com reparacao literal: {audit}.")
        elif args.retry_errors:
            # Exclui arquivos recuperaveis; requer executar --recover previamente para os aproveitar.
            if ready:
                print("PARAGEM: existem respostas arquivadas recuperaveis. Executa --recover primeiro.")
                return 2
            db.execute("BEGIN IMMEDIATE")
            try:
                result = db.execute(
                    "UPDATE jobs SET status='retry_pending',updated=? "
                    "WHERE status='error' AND provider='codex-economico' AND attempts<?",
                    (distill.now(), max_attempts),
                )
                db.commit()
            except BaseException:
                db.rollback()
                raise
            print(f"Reservados para nova geracao individual: {result.rowcount}.")
            print("Executa: python economico.py --retry-only --batch-size 1 --limit 200 --max-consecutive-failures 5")
        else:
            print("Modo consulta: nenhum estado foi alterado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
