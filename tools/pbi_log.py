"""
pbi_log.py  Lee transcript_events de OpenClaw SQLite y escribe logs JSONL
incrementales para la sesion PBI bot. Disenado para ejecutarse cada minuto.

Uso: python tools/pbi_log.py
"""

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

try:
    import zstandard as zstd
    DCTX = zstd.ZstdDecompressor()
except ImportError:
    DCTX = None

DB_PATH    = Path(r"C:\Users\rmib2\.openclaw\agents\main\agent\openclaw-agent.sqlite")
SESSION_ID = "d35a55a6-e05d-4189-9c12-9600dd60db03"
SCRIPT_DIR = Path(__file__).parent
LOGS_DIR   = SCRIPT_DIR.parent / "logs"
STATE_FILE = LOGS_DIR / ".last_logged_asst_seq"


def log_file_for_date(d: date) -> Path:
    return LOGS_DIR / f"conversations_{d.isoformat()}.jsonl"


def decompress(data: bytes) -> str:
    if DCTX is None:
        raise RuntimeError("zstandard no instalado: pip install zstandard")
    return DCTX.decompress(data).decode("utf-8")


def load_events() -> list[dict]:
    """Lee todos los eventos de la sesion PBI desde SQLite."""
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT seq, event_json, event_zstd FROM transcript_events "
        "WHERE session_id = ? ORDER BY seq",
        (SESSION_ID,)
    ).fetchall()
    con.close()

    events = []
    current_model = None
    for seq, ej, ez in rows:
        try:
            raw = ej if ej else decompress(ez)
            ev = json.loads(raw)
        except Exception:
            continue

        t = ev.get("type", "")
        if t == "custom" and ev.get("customType") == "model-snapshot":
            current_model = ev.get("data", {}).get("modelId")

        msg = ev.get("message")
        if isinstance(msg, dict):
            role = msg.get("role", "")
            if role in ("user", "assistant"):
                ev["_seq"]   = seq
                ev["_role"]  = role
                ev["_model"] = current_model
                events.append(ev)

    return events


def extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def extract_thinking(content) -> list[str]:
    if not isinstance(content, list):
        return []
    return [
        b["thinking"]
        for b in content
        if isinstance(b, dict) and b.get("type") == "thinking" and b.get("thinking")
    ]


def build_exchanges(events: list[dict]) -> list[dict]:
    """Agrupa eventos en exchanges (pregunta => respuesta final)."""
    exchanges = []
    i = 0
    while i < len(events):
        ev = events[i]
        if ev["_role"] != "user":
            i += 1
            continue

        msg = ev.get("message", {})
        question = extract_text(msg.get("content", ""))
        ts_ms = msg.get("timestamp") or 0
        if ts_ms:
            ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
        else:
            ts = ev.get("timestamp", "")

        # Todos los assistant messages hasta el proximo user
        j = i + 1
        while j < len(events) and events[j]["_role"] == "assistant":
            j += 1
        asst_events = events[i + 1:j]

        if not asst_events:
            i = j
            continue

        # Ultimo assistant con texto real
        final_asst = None
        for ae in reversed(asst_events):
            content = ae.get("message", {}).get("content", [])
            has_text = any(
                isinstance(b, dict) and b.get("type") == "text" and b.get("text")
                for b in (content if isinstance(content, list) else [])
            )
            if has_text:
                final_asst = ae
                break
        if final_asst is None:
            final_asst = asst_events[-1]

        answer = extract_text(final_asst.get("message", {}).get("content", []))

        # Thinking de todos los turns del exchange
        thinking = []
        for ae in asst_events:
            thinking.extend(extract_thinking(ae.get("message", {}).get("content", [])))

        # Sumar tokens y costo de todos los turns del exchange
        tok = {"input": 0, "output": 0, "cache_read": 0, "reasoning": 0, "total": 0}
        total_cost = 0.0
        for ae in asst_events:
            u = ae.get("message", {}).get("usage") or {}
            tok["input"]      += u.get("input", 0)
            tok["output"]     += u.get("output", 0)
            tok["cache_read"] += u.get("cacheRead", 0)
            tok["reasoning"]  += u.get("reasoningTokens", 0)
            tok["total"]      += u.get("totalTokens", 0)
            total_cost        += (u.get("cost") or {}).get("total", 0.0)

        exchanges.append({
            "asst_seq": final_asst["_seq"],
            "ts":       ts,
            "model":    final_asst.get("_model") or "unknown",
            "question": question,
            "answer":   answer,
            "thinking": thinking,
            "tokens":   tok,
            "cost_usd": round(total_cost, 6),
        })
        i = j

    return exchanges


def last_logged_seq() -> int:
    if STATE_FILE.exists():
        try:
            return int(STATE_FILE.read_text(encoding="utf-8").strip())
        except ValueError:
            pass
    return -1


def main() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    last_seq  = last_logged_seq()
    events    = load_events()
    exchanges = build_exchanges(events)

    new_exchanges = [e for e in exchanges if e["asst_seq"] > last_seq]
    if not new_exchanges:
        print("Sin exchanges nuevos.")
        return

    for ex in new_exchanges:
        try:
            ts_date = date.fromisoformat(ex["ts"][:10])
        except Exception:
            ts_date = date.today()

        record = {
            "asst_seq": ex["asst_seq"],
            "ts":       ex["ts"],
            "model":    ex["model"],
            "question": ex["question"],
            "answer":   ex["answer"],
            "thinking": ex["thinking"],
            "tokens":   ex["tokens"],
            "cost_usd": ex["cost_usd"],
        }
        log_file = log_file_for_date(ts_date)
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"Logged seq={ex['asst_seq']}: {ex['question'][:60]}")

    max_seq = max(e["asst_seq"] for e in new_exchanges)
    STATE_FILE.write_text(str(max_seq), encoding="utf-8")
    print(f"Guardado last_seq={max_seq}")


if __name__ == "__main__":
    main()
