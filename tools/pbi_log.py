"""
pbi_log.py  Lee transcript_events de OpenClaw SQLite y escribe logs JSONL
incrementales para la sesion PBI bot. Disenado para ejecutarse cada minuto.

Uso: python tools/pbi_log.py
"""

import json
import sqlite3
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

LOCAL_TZ = ZoneInfo("America/La_Paz")

# Tarifas USD por millon de tokens. Solo modelos con precio verificado en la
# referencia oficial de la API de Claude. Cache read = 0.1x input,
# cache write = 1.25x input (TTL 5 min, el default).
PRICING = {
    "claude-sonnet-5": {
        "input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50
    },
}

# Rutas que no devuelven telemetria utilizable.
# cli      -> Claude Code CLI: input/output son un stub del envoltorio.
# codex    -> Codex App Server: el costo queda en el backend de ChatGPT.
STUB_TOKEN_ROUTES = {"cli"}
NO_COST_ROUTES    = {"cli", "openai-responses"}
NO_THINKING_ROUTES = {"cli", "openai-responses"}


def estimate_cost(model: str, tok: dict) -> float | None:
    """Estima costo desde tarifas de catalogo. None si no hay precio verificado."""
    rates = PRICING.get(model)
    if not rates:
        return None
    return round(
        tok["input"]       / 1e6 * rates["input"]
        + tok["output"]      / 1e6 * rates["output"]
        + tok["cache_read"]  / 1e6 * rates["cache_read"]
        + tok["cache_write"] / 1e6 * rates["cache_write"],
        6,
    )


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


def load_trajectory_usage() -> dict:
    """Lee model.completed de trajectory_runtime_events indexados por turnId."""
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT event_json FROM trajectory_runtime_events WHERE session_id = ?",
        (SESSION_ID,)
    ).fetchall()
    con.close()

    by_turn = {}
    for (ej,) in rows:
        try:
            ev = json.loads(ej)
        except Exception:
            continue
        if ev.get("type") != "model.completed":
            continue
        data = ev.get("data", {})
        turn_id = data.get("turnId")
        usage = data.get("usage") or {}
        if turn_id and usage.get("total", 0) > 0:
            by_turn[turn_id] = usage
    return by_turn


def load_events(trajectory_usage: dict) -> list[dict]:
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
                ev["_api"]   = msg.get("api", "")
                msg_model = msg.get("model", "")
                if msg_model and msg_model != "delivery-mirror":
                    current_model = msg_model
                ev["_model"] = current_model

                # Extraer turnId desde mirrorIdentity para Codex runs
                oc = msg.get("__openclaw", {}) or ev.get("__openclaw", {})
                mirror_id = oc.get("mirrorIdentity", "")
                turn_id = mirror_id.split(":")[0] if mirror_id else None
                ev["_turn_id"] = turn_id
                ev["_traj_usage"] = trajectory_usage.get(turn_id) if turn_id else None

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
            ts = datetime.fromtimestamp(ts_ms / 1000, tz=LOCAL_TZ).isoformat()
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

        # Sumar tokens: primero desde message.usage, luego desde trajectory si hay 0
        tok = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
               "reasoning": 0, "total": 0}
        total_cost = 0.0
        traj_used = set()

        for ae in asst_events:
            u = ae.get("message", {}).get("usage") or {}
            tok["input"]       += u.get("input", 0)
            tok["output"]      += u.get("output", 0)
            tok["cache_read"]  += u.get("cacheRead", 0)
            tok["cache_write"] += u.get("cacheWrite", 0)
            tok["reasoning"]   += u.get("reasoningTokens", 0)
            tok["total"]       += u.get("totalTokens", 0)
            total_cost        += (u.get("cost") or {}).get("total", 0.0)

            # Acumular turnIds para fallback via trajectory
            turn_id = ae.get("_turn_id")
            traj_u  = ae.get("_traj_usage")
            if turn_id and traj_u and turn_id not in traj_used:
                traj_used.add(turn_id)

        # Si message.usage no dio datos, usar trajectory
        if tok["total"] == 0 and traj_used:
            # Recargar usage directamente del evento de trajectory ya cargado
            for ae in asst_events:
                turn_id = ae.get("_turn_id")
                traj_u  = ae.get("_traj_usage")
                if turn_id and traj_u and turn_id in traj_used:
                    tok["input"]       += traj_u.get("input", 0)
                    tok["output"]      += traj_u.get("output", 0)
                    tok["cache_read"]  += traj_u.get("cacheRead", 0)
                    tok["cache_write"] += traj_u.get("cacheWrite", 0)
                    tok["reasoning"]   += traj_u.get("reasoningTokens", 0)
                    tok["total"]       += traj_u.get("total", 0)
                    total_cost        += (traj_u.get("cost") or {}).get("total", 0.0)
                    traj_used.discard(turn_id)

        # Ruta real: el api del ultimo evento con modelo propio, ignorando
        # los delivery-mirror que solo reflejan el texto final.
        route = ""
        for ae in reversed(asst_events):
            api = ae.get("_api", "")
            if api and api not in ("openclaw-transcript",):
                route = api
                break

        model = final_asst.get("_model") or "unknown"
        cost  = round(total_cost, 6)

        # Honestidad: distinguir "cero" de "no disponible".
        if cost > 0:
            cost_usd, cost_est, cost_note = cost, None, "real reportado por el proveedor"
        else:
            cost_est = estimate_cost(model, tok)
            cost_usd = None
            if cost_est is None:
                cost_note = f"no disponible (ruta {route}) y sin tarifa verificada para {model}"
            elif route in STUB_TOKEN_ROUTES:
                cost_note = (f"ESTIMADO desde catalogo; piso minimo, la ruta {route} "
                             f"reporta input/output como stub")
            else:
                cost_note = "ESTIMADO desde tarifas de catalogo"

        tokens_note = (
            f"parcial: la ruta {route} reporta input/output como stub del envoltorio; "
            "solo cache_read y cache_write son reales"
            if route in STUB_TOKEN_ROUTES else "reales"
        )
        thinking_note = (
            f"no disponible: la ruta {route} no emite bloques de thinking al transcript"
            if not thinking and route in NO_THINKING_ROUTES else
            ("sin bloques de thinking en esta respuesta" if not thinking else "capturado")
        )

        exchanges.append({
            "asst_seq": final_asst["_seq"],
            "ts":       ts,
            "model":    model,
            "route":    route or "desconocida",
            "question": question,
            "answer":   answer,
            "thinking": thinking,
            "thinking_note": thinking_note,
            "tokens":   tok,
            "tokens_note": tokens_note,
            "cost_usd": cost_usd,
            "cost_estimated_usd": cost_est,
            "cost_note": cost_note,
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

    last_seq        = last_logged_seq()
    traj_usage      = load_trajectory_usage()
    events          = load_events(traj_usage)
    exchanges       = build_exchanges(events)

    new_exchanges = [e for e in exchanges if e["asst_seq"] > last_seq]
    if not new_exchanges:
        print("Sin exchanges nuevos.")
        return

    for ex in new_exchanges:
        try:
            ts_date = date.fromisoformat(ex["ts"][:10])
        except Exception:
            ts_date = date.today()

        record = dict(ex)
        log_file = log_file_for_date(ts_date)
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"Logged seq={ex['asst_seq']}: {ex['question'][:60]}")

    max_seq = max(e["asst_seq"] for e in new_exchanges)
    STATE_FILE.write_text(str(max_seq), encoding="utf-8")
    print(f"Guardado last_seq={max_seq}")


if __name__ == "__main__":
    main()
