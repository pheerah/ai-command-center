"""Read-only scheduler liveness shared by CLI, connector and dashboard."""
from __future__ import annotations

import json
import math
import time

from center_store import pid_alive


def service_status(center):
    with center.store.connection() as con:
        row = con.execute("SELECT value FROM center_meta WHERE key='service'").fetchone()
    if not row:
        return {"running": False, "mode": "unknown", "heartbeat_age_seconds": None, "reason": "not_started"}
    try:
        record = json.loads(row[0])
        if not isinstance(record, dict) or type(record.get("pid")) is not int:
            raise ValueError("Invalid scheduler record")
        heartbeat = record.get("heartbeat")
        if type(heartbeat) not in (int, float) or not math.isfinite(heartbeat):
            raise ValueError("Invalid scheduler heartbeat")
        age = max(0.0, time.time() - heartbeat)
        alive = pid_alive(record["pid"])
        record["heartbeat_age_seconds"] = round(age, 3)
        record["running"] = alive and age < 20
        record["reason"] = "running" if record["running"] else "heartbeat_stale" if alive else "process_not_running"
        return record
    except (ValueError, TypeError, KeyError):
        return {"running": False, "mode": "unknown", "heartbeat_age_seconds": None, "reason": "invalid_service_record"}
