#!/usr/bin/env python3
"""Execucao economica do TinyLLM: lotes, medicao e retoma conservadora.

Por omissao: ate 20 pedidos, em lotes de 4, modelo gpt-6-luna e raciocinio low.
Nunca reenvia automaticamente um pedido 'running' ou 'error'.
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import distill

ROOT = Path(__file__).resolve().parent
BATCH_SCHEMA = ROOT / "response.batch.schema.json"


def batch_prompt(jobs):
    """Uma instrucao comum, mantendo os requests originais e os seus IDs."""
    templates = [j["prompt"].split("\nREQUEST\n", 1)[0] for j in jobs]
    if len(set(templates)) != 1:
        raise ValueError("O lote mistura versoes de prompt; processa cada versao separadamente.")
    requests = [json.loads(j["request"]) for j in jobs]
    return (
        templates[0]
        + "\nBATCH OVERRIDE: Return exactly one response object per requested job_id, "
        "including every task slot. Do not merge jobs, omit jobs "
        "or change identifiers. All supported messages must alternate user, assistant, "
        "starting with user and ending with assistant; C6 requires 2 to 4 such exchanges. "
        "Keep citations verbatim and evidence source_ids exact."
        "\nReturn an object with exactly one key: responses (an array of the individual response objects).\nREQUESTS\n" + distill.dumps(requests) + "\n"
    )


def usage_from_events(path):
    """A ultima medicao turn.completed e o total da chamada, nao somar eventos."""
    usage = {}
    if not path.is_file():
        return usage
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = event["usage"]
    return usage


def index_batch(items, jobs):
    """Confere IDs do lote sem descartar respostas validas por erro de outro pedido."""
    if not isinstance(items, list):
        raise ValueError("O lote de respostas tem de ser uma lista.")
    expected = {j["id"]: j for j in jobs}
    seen = set()
    for item in items:
        if not isinstance(item, dict) or item.get("job_id") not in expected:
            raise ValueError("job_id desconhecido ou resposta mal formada.")
        jid = item["job_id"]
        if jid in seen:
            raise ValueError("job_id repetido no lote.")
        seen.add(jid)
    return {item["job_id"]: item for item in items}


def validate_batch(items, jobs):
    """Valida todos os pedidos; usado na verificacao estrita."""
    mapped = index_batch(items, jobs)
    for job in jobs:
        if job["id"] not in mapped:
            raise ValueError("Resposta em falta para pedido " + job["id"])
        distill.validate_response(mapped[job["id"]], json.loads(job["request"]))
    return mapped


def mark_failed(db, jobs, message):
    """Nao repetir execucoes possivelmente cobradas sem uma decisao explicita."""
    with db:
        for j in jobs:
            db.execute(
                "UPDATE jobs SET status='error',error=?,updated=? "
                "WHERE id=? AND status='running'",
                (message[:1000], distill.now(), j["id"]),
            )


def save_batch(db, jobs, items, model, usage, seconds):
    """Guarda pedidos validos individualmente, isolando os invalidos sem nova chamada."""
    mapped = index_batch(items, jobs)
    counts = {"added": 0, "duplicate": 0, "unsupported": 0,
              "completed_jobs": 0, "failed_jobs": []}
    usage_written = False
    for job in jobs:
        jid = job["id"]
        try:
            if jid not in mapped:
                raise ValueError("Resposta em falta no lote.")
            distill.validate_response(mapped[jid], json.loads(job["request"]))
        except ValueError as exc:
            mark_failed(db, [job], str(exc))
            counts["failed_jobs"].append({"job_id": jid, "error": str(exc)})
            continue
        # A utilizacao pertence a chamada inteira: registar numa unica linha.
        record_usage = (dict(usage, elapsed_seconds=round(seconds, 2),
                             batch_size=len(jobs)) if not usage_written else None)
        result = distill.store_response(
            db, job, mapped[jid], "codex-economico", model, record_usage
        )
        usage_written = True
        counts["completed_jobs"] += 1
        for key in ("added", "duplicate", "unsupported"):
            counts[key] += result[key]
    return counts


def recover(db, raw_dir):
    """Se houver JSON completo validado, importar. Caso contrario, marcar erro.

    Mesmo com crash durante a gravacao, nao reenvia o mesmo lote ao modelo.
    """
    rows = db.execute("SELECT * FROM jobs WHERE status='running' ORDER BY created,id").fetchall()
    if not rows:
        return
    pending = {row["id"]: row for row in rows}
    for manifest in sorted(raw_dir.glob("eco-*.manifest.json")):
        try:
            meta = json.loads(manifest.read_text(encoding="utf-8"))
            ids = meta["job_ids"]
            expected_attempts = meta["attempts"]
        except (ValueError, KeyError, TypeError):
            continue
        matched = [pending[jid] for jid in ids if jid in pending and pending[jid]["attempts"] == expected_attempts[jid]]
        if not matched:
            continue
        response = raw_dir / (manifest.name.replace(".manifest.json", ".response.json"))
        if response.is_file():
            try:
                items = distill.parse_response(response.read_text(encoding="utf-8"))["responses"]
                all_jobs = [db.execute(
                    "SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
                    for jid in ids]
                mapped = index_batch(items, all_jobs)
                for job in matched:
                    try:
                        if job["id"] not in mapped:
                            raise ValueError("Resposta em falta no lote.")
                        distill.validate_response(
                            mapped[job["id"]], json.loads(job["request"]))
                    except ValueError as exc:
                        mark_failed(db, [job], str(exc))
                        print("Resposta invalida arquivada:", job["id"], exc,
                              file=sys.stderr)
                    else:
                        distill.store_response(db, job, mapped[job["id"]],
                                               "codex-economico", meta["model"])
                    pending.pop(job["id"], None)
                print("Recuperado lote:", manifest.name, flush=True)
                continue
            except (ValueError, KeyError, TypeError) as exc:
                print("Lote a rever:", manifest.name, str(exc), file=sys.stderr)
        mark_failed(db, matched, "Execucao anterior interrompida; analisar ficheiros raw antes de retry")
        for j in matched:
            pending.pop(j["id"], None)
    if pending:
        mark_failed(db, list(pending.values()), "Execucao interrompida sem resposta arquivada; verificar antes de retry")
    print("Recuperacao concluida; nenhum pedido foi reenviado automaticamente.", flush=True)


def selected_jobs(db, limit, batch_size, max_attempts):
    """Escolhe pendentes; prioriza receitas comuns para reduzir repeticoes."""
    rows = db.execute(
        "SELECT * FROM jobs WHERE status='pending' AND attempts<? "
        "ORDER BY recipe_id,created,id LIMIT ?",
        (max_attempts, limit),
    ).fetchall()
    if not rows:
        return []
    first = rows[0]
    template = first["prompt"].split("\nREQUEST\n", 1)[0]
    group = [r for r in rows if r["prompt"].split("\nREQUEST\n", 1)[0] == template]
    return group[:batch_size]


def codex_command(executable, model, reasoning_effort, output, ephemeral=False):
    """Configura raciocinio no nivel global do Codex, antes de exec."""
    cmd = [
        executable, "--ask-for-approval", "never",
        "-c", f"model_reasoning_effort={reasoning_effort}",
        "exec", "--sandbox", "read-only", "--skip-git-repo-check",
        "--output-schema", str(BATCH_SCHEMA), "--json", "-o", str(output),
    ]
    if ephemeral:
        cmd.append("--ephemeral")
    cmd.extend(["--model", model, "-"])
    return cmd


def run(args, config, db, work):
    executable = shutil.which(args.codex_bin)
    if not executable:
        raise ValueError("Codex CLI nao encontrado.")
    if os.getenv("CODEX_API_KEY") or os.getenv("OPENAI_API_KEY"):
        raise ValueError("API key detetada. Usa a sessao autenticada ChatGPT, sem estas variaveis.")
    auth = subprocess.run([executable, "login", "status"], capture_output=True,
                          text=True, timeout=30)
    if auth.returncode or "chatgpt" not in (auth.stdout + auth.stderr).casefold():
        raise ValueError("Autenticacao ChatGPT nao confirmada (codex login status).")
    help_result = subprocess.run([executable, "exec", "--help"], capture_output=True,
                                 text=True, timeout=30)
    if help_result.returncode or "--output-schema" not in help_result.stdout:
        raise ValueError("Atualiza o Codex CLI: falta --output-schema.")
    raw_dir = work / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    recover(db, raw_dir)

    attempted = completed = calls = 0
    token_total = 0
    while attempted < args.limit:
        group = selected_jobs(db, args.limit - attempted, args.batch_size,
                              config["max_attempts"])
        if not group:
            break
        prompt = batch_prompt(group)
        ids = [j["id"] for j in group]
        stem = "eco-" + hashlib.sha256((distill.dumps(ids) + str(time.time_ns())).encode()).hexdigest()[:20]
        prefix = raw_dir / stem
        # Manifesto antes de cobrar qualquer chamada: permite recuperacao apos crash.
        manifest = {"job_ids": ids, "attempts": {j["id"]: j["attempts"] + 1 for j in group}, "model": args.model,
                    "created": distill.now(), "reasoning_effort": args.reasoning_effort}
        distill.write_json(str(prefix) + ".manifest.json", manifest)
        with db:
            for job in group:
                db.execute(
                    "UPDATE jobs SET status='running',attempts=attempts+1,"
                    "provider='codex-economico',updated=? WHERE id=?",
                    (distill.now(), job["id"]),
                )
        attempted += len(group)
        started = time.monotonic()
        try:
            with tempfile.TemporaryDirectory(prefix="tinyslm-eco-") as folder:
                output = Path(folder) / "response.json"
                cmd = codex_command(
                    executable, args.model, args.reasoning_effort, output,
                    ephemeral="--ephemeral" in help_result.stdout,
                )
                with (Path(str(prefix) + ".events.jsonl")).open("w", encoding="utf-8") as log, (
                    Path(str(prefix) + ".stderr.txt")
                ).open("w", encoding="utf-8") as err:
                    result = subprocess.run(
                        cmd, input=prompt, text=True, stdout=log, stderr=err,
                        cwd=folder, timeout=args.timeout or config["timeout_seconds"],
                    )
                if result.returncode:
                    raise ValueError(f"Codex saiu com codigo {result.returncode}")
                # Guardar ANTES de validar ou atualizar a fila.
                text = output.read_text(encoding="utf-8")
                Path(str(prefix) + ".response.json").write_text(text, encoding="utf-8")
            items = distill.parse_response(text)["responses"]
            metrics = usage_from_events(Path(str(prefix) + ".events.jsonl"))
            elapsed = time.monotonic() - started
            counts = save_batch(db, group, items, args.model, metrics, elapsed)
            calls += 1
            completed += counts["completed_jobs"]
            tokens = metrics.get("input_tokens", 0) + metrics.get("output_tokens", 0)
            token_total += tokens
            summary = dict(manifest, elapsed_seconds=round(elapsed, 2),
                           usage=metrics, results=counts,
                           status="partial" if counts["failed_jobs"] else "done")
            distill.write_json(str(prefix) + ".summary.json", summary)
            print(f"Lote: {counts['completed_jobs']}/{len(group)} pedidos validos, "
                  f"{counts['added']} conversas novas, {tokens} tokens reportados.",
                  flush=True)
            if counts["failed_jobs"]:
                print("Lote parcialmente invalido; respostas validas preservadas. "
                      "Geracao parada para revisao sem repetir a chamada:",
                      counts["failed_jobs"], flush=True)
                break
        except (Exception, KeyboardInterrupt) as exc:
            # Nao relancar reservas nem repetir lote possivelmente cobrado.
            mark_failed(db, group, str(exc))
            print(f"Lote parado ({stem}): {exc}. "
                  "Inspeciona dados/raw; usa retry apenas depois de verificar.",
                  file=sys.stderr, flush=True)
            raise
    print(f"RESUMO: {completed}/{attempted} pedidos concluidos, {calls} chamadas, "
          f"{token_total} tokens reportados. Consulta dados/raw/eco-*.summary.json.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", default=str(ROOT / "dados"))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high", "xhigh"), default="low",
                        help="Nivel de raciocinio Codex; por omissao low.")
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--timeout", type=int)
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 20:
        parser.error("--limit deve estar entre 1 e 20 (protecao inicial).")
    if not 1 <= args.batch_size <= 4:
        parser.error("--batch-size deve estar entre 1 e 4.")
    work = Path(args.work).expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    with (work / "queue.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Outra operacao usa a fila. Nao iniciar em paralelo.")
        with contextlib.closing(distill.open_db(work)) as db:
            run(args, config, db, work)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print("ERRO:", exc, file=sys.stderr)
        sys.exit(1)
