"""
readiness.py — Progressive readiness tracker for Princeps subsystems.

Tracks individual subsystem startup states so the frontend can display
granular progress while background ingestion tasks complete (60-120s).

Thread-safe: all mutations go through a threading.Lock.
"""

import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Subsystem states: pending -> loading -> ready | failed
# ---------------------------------------------------------------------------
VALID_STATES = {"pending", "loading", "ready", "failed"}

# Core subsystems (must be ready for the app to serve requests)
CORE_SUBSYSTEMS = {"database", "core_api"}

# All tracked subsystems
ALL_SUBSYSTEMS = {
    "database", "core_api", "grid_data", "demand_data",
    "neo4j", "geeflow", "dc_infrastructure",
}

_lock = threading.Lock()
_start_time = time.time()
_subsystems: dict[str, dict] = {
    name: {"status": "pending", "loaded_at": None, "progress": None, "error": None}
    for name in ALL_SUBSYSTEMS
}


def mark_ready(subsystem: str, *, status: str = "ready") -> None:
    """Mark a subsystem as ready (or failed)."""
    if status not in VALID_STATES:
        raise ValueError(f"Invalid state: {status}")
    with _lock:
        if subsystem not in _subsystems:
            _subsystems[subsystem] = {
                "status": "pending", "loaded_at": None,
                "progress": None, "error": None,
            }
        _subsystems[subsystem]["status"] = status
        if status == "ready":
            _subsystems[subsystem]["loaded_at"] = time.time()
            _subsystems[subsystem]["error"] = None


def mark_loading(subsystem: str, progress: Optional[str] = None) -> None:
    """Mark a subsystem as currently loading, with optional progress text."""
    with _lock:
        if subsystem not in _subsystems:
            _subsystems[subsystem] = {
                "status": "pending", "loaded_at": None,
                "progress": None, "error": None,
            }
        _subsystems[subsystem]["status"] = "loading"
        _subsystems[subsystem]["progress"] = progress


def mark_failed(subsystem: str, error: str = "") -> None:
    """Mark a subsystem as failed."""
    with _lock:
        if subsystem not in _subsystems:
            _subsystems[subsystem] = {
                "status": "pending", "loaded_at": None,
                "progress": None, "error": None,
            }
        _subsystems[subsystem]["status"] = "failed"
        _subsystems[subsystem]["error"] = error


def update_progress(subsystem: str, progress: str) -> None:
    """Update progress text for a loading subsystem."""
    with _lock:
        if subsystem in _subsystems:
            _subsystems[subsystem]["progress"] = progress


def is_ready(subsystem: str) -> bool:
    """Check if a specific subsystem is ready."""
    with _lock:
        entry = _subsystems.get(subsystem)
        return entry is not None and entry["status"] == "ready"


def core_ready() -> bool:
    """True when all CORE_SUBSYSTEMS are ready — enough to serve requests."""
    with _lock:
        return all(
            _subsystems.get(s, {}).get("status") == "ready"
            for s in CORE_SUBSYSTEMS
        )


def get_status() -> dict:
    """Return full readiness snapshot for the /api/readiness endpoint."""
    with _lock:
        subsystems = {}
        for name, entry in _subsystems.items():
            info: dict = {"status": entry["status"]}
            if entry["loaded_at"]:
                info["loaded_at"] = entry["loaded_at"]
            if entry["progress"]:
                info["progress"] = entry["progress"]
            if entry["error"]:
                info["error"] = entry["error"]
            subsystems[name] = info

        c_ready = all(
            _subsystems.get(s, {}).get("status") == "ready"
            for s in CORE_SUBSYSTEMS
        )

        statuses = {e["status"] for e in _subsystems.values()}
        if all(s == "ready" for s in statuses):
            overall = "ready"
        elif "failed" in statuses and c_ready:
            overall = "degraded"
        else:
            overall = "starting"

    return {
        "overall": overall,
        "core_ready": c_ready,
        "subsystems": subsystems,
        "uptime_s": round(time.time() - _start_time, 1),
    }


def reset_start_time() -> None:
    """Reset the start time (call during lifespan init)."""
    global _start_time
    _start_time = time.time()
