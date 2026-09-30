#!/usr/bin/env python3
"""
pbi_log.py  Export PBI bot conversations to JSONL incrementally.

Cada linea del archivo de salida representa una sesion completa de
pregunta-respuesta con sus tokens, thinking y costo.

Uso: python tools/pbi_log.py
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

SESSION_KEY = "agent:main:telegram:pbi:direct:1353028892"
SCRIPT_DIR  = Path(__file__).parent
BOT_DIR     = SCRIPT_DIR.parent
LOGS_DIR    = BOT_DIR / "logs"
STATE_FILE  = LOGS_DIR / ".logged_run_ids"


def log_file_for_today() -> Path:
    from datetime import date
    return LOGS_DIR / f"conversations_{date.today().isoformat()}.jsonl"


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_session() -> Path | None:
    """Ejecuta openclaw export-trajectory y devuelve el directorio generado."""
    result = subprocess.run(
        ["powershell", "-Command",
         f"openclaw sessions export-trajectory --session-key '{SESSION_KEY}' --json"],
        capture_output=True, text=True, shell=False
    )
    # stdout puede tener warnings ANSI en stderr; stdout contiene solo el JSON
    stdout = result.stdout.strip()
    if result.returncode != 0 or not stdout:
        print(f"[pbi_log] Export fallido: {result.stderr.strip()}", file=sys.stderr)
        return None
    # Buscar el bloque JSON (puede haber ruido ANSI antes)
    idx = stdout.find("{")
    if idx == -1:
        print(f"[pbi_log] Sin JSON en la salida: {stdout[:200]}", file=sys.stderr)
        return None
    data = json.loads(stdout[idx:])
    return Path(data["outputDir"])


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def load_events(export_dir: Path) -> list[dict]:
    events = []
    with open(export_dir / "events.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def group_by_run(events: list[dict]) -> dict[str, list[dict]]:
    runs: dict[str, list[dict]] = {}
    for ev in events:
        run_id = ev.get("runId")
        if run_id:
            runs.setdefault(run_id, []).append(ev)
    return runs


def extract_record(run_id: str, events: list[dict]) -> dict | None:
    """Construye un registro de log a partir de los eventos de un run."""
    events_sorted = sorted(events, key=lambda e: e.get("seq", 0))

    model_completed = None

    for ev in events_sorted:
        if ev["type"] == "model.completed":
            model_completed = ev  # nos quedamos con el ultimo (resumen total)

    if not model_completed:
        return None

    data    = model_completed.get("data", {})
    usage   = data.get("usage", {})
    cost    = usage.get("cost", {})

    # La pregunta del usuario viene en finalPromptText (resumen del contexto de entrada)
    user_message = data.get("finalPromptText", "")

    # Thinking: extraer resúmenes de todos los pasos del messagesSnapshot
    thinking_summaries: list[str] = []
    for msg in data.get("messagesSnapshot", []):
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        for block in (msg.get("content") or []):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "thinking":
                t_text = block.get("thinking", "").strip()
                if t_text:
                    thinking_summaries.append(t_text)

    # Respuesta final al usuario
    answer = " ".join(data.get("assistantTexts") or [])

    return {
        "run_id":    run_id,
        "session_id": model_completed.get("sessionId"),
        "ts":        model_completed.get("ts"),
        "model":     model_completed.get("modelId"),
        "question": user_message,
        "answer":    answer,
        "thinking":  thinking_summaries,
        "tokens": {
            "input":     usage.get("input", 0),
            "output":    usage.get("output", 0),
            "cache_read": usage.get("cacheRead", 0),
            "reasoning": usage.get("reasoningTokens", 0),
            "total":     usage.get("total", 0),
        },
        "cost_usd": cost.get("total", 0),
    }


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def load_logged_ids() -> set[str]:
    if STATE_FILE.exists():
        return set(STATE_FILE.read_text(encoding="utf-8").strip().splitlines())
    return set()


def save_logged_ids(ids: set[str]) -> None:
    STATE_FILE.write_text("\n".join(sorted(ids)), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    export_dir = export_session()
    if not export_dir:
        sys.exit(1)

    try:
        events      = load_events(export_dir)
        logged_ids  = load_logged_ids()
        runs        = group_by_run(events)
        new_records = []

        for run_id, run_events in runs.items():
            if run_id in logged_ids:
                continue
            # Solo loguear runs que completaron
            if not any(e["type"] == "model.completed" for e in run_events):
                continue
            record = extract_record(run_id, run_events)
            if record:
                new_records.append(record)
                logged_ids.add(run_id)

        if new_records:
            log_file = log_file_for_today()
            with open(log_file, "a", encoding="utf-8") as f:
                for rec in new_records:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            save_logged_ids(logged_ids)
            print(f"[pbi_log] +{len(new_records)} conversacion(es) => {log_file}")
        else:
            print("[pbi_log] Sin conversaciones nuevas.")
    finally:
        shutil.rmtree(export_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
