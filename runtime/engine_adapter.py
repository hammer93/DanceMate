"""Adapter between the DanceMate runtime and the Information Engine v0.73.

The engine is a self-contained package rooted at ``engine/`` that keeps its own
SQLite persistence. This adapter never modifies engine source or engine schema;
it only answers "is the engine importable, and is its persistence reachable?"

Engine facts this adapter relies on (verified against the imported v0.73 tree):
  * package root        engine/            (``src`` is the importable package)
  * CLI entry point     ``python -m src.main <command>``
  * SQLite location     ``<engine root>/data/dancemate_ie_poc_v0.73.sqlite3``
                        (hardcoded in ``src/main.py:db_path()``)

Because the engine's DB path is derived from its own package root, persistence
is provided by mounting a volume over ``<engine root>/data`` rather than by
patching the engine. ``ENGINE_DATA_DIR`` names the host side of that mount.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import Settings

ENGINE_PACKAGE = "src"
ENGINE_DB_FILENAME = "dancemate_ie_poc_v0.73.sqlite3"
REQUIRED_MODULES = ("src.database", "src.main")
SMOKE_COMMAND = [sys.executable, "-m", "src.main", "snapshot-list"]


def engine_db_path(settings: Settings) -> Path:
    return settings.engine_data_dir / ENGINE_DB_FILENAME


def _importable(engine_root: Path) -> tuple[bool, str]:
    root = str(engine_root)
    inserted = root not in sys.path
    if inserted:
        sys.path.insert(0, root)
    try:
        for name in REQUIRED_MODULES:
            module = importlib.import_module(name)
            if name == "src.database" and not hasattr(module, "init_db"):
                return False, "src.database has no init_db()"
        return True, "engine package importable"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        if inserted and root in sys.path:
            sys.path.remove(root)


def inspect(settings: Settings) -> dict[str, Any]:
    """Report engine availability without mutating engine state.

    Returns a dict with ``status`` of PASS / WARN / FAIL and the checks that
    produced it. Never raises.
    """
    root = settings.engine_root
    checks: dict[str, Any] = {}

    checks["engine_root"] = str(root)
    checks["engine_root_exists"] = root.is_dir()
    checks["package_present"] = (root / ENGINE_PACKAGE / "main.py").is_file()
    checks["config_present"] = (root / "config" / "sources.json").is_file()

    data_dir = settings.engine_data_dir
    checks["data_dir"] = str(data_dir)
    checks["data_dir_exists"] = data_dir.is_dir()
    checks["data_dir_writable"] = os.access(data_dir, os.W_OK) if data_dir.is_dir() else False

    db = engine_db_path(settings)
    checks["sqlite_path"] = str(db)
    checks["sqlite_present"] = db.is_file()
    checks["sqlite_bytes"] = db.stat().st_size if db.is_file() else 0

    if checks["engine_root_exists"] and checks["package_present"]:
        ok, detail = _importable(root)
    else:
        ok, detail = False, "engine package not found on disk"
    checks["importable"] = ok
    checks["import_detail"] = detail

    if not (checks["engine_root_exists"] and checks["package_present"] and ok):
        status = "FAIL"
    elif not (checks["data_dir_exists"] and checks["data_dir_writable"]):
        status = "FAIL"
    elif not checks["sqlite_present"]:
        # A fresh deployment has no engine DB until the first engine run.
        status = "WARN"
    else:
        status = "PASS"

    return {"status": status, "version": settings.engine_version, "checks": checks}


def smoke(settings: Settings, timeout: int = 60) -> dict[str, Any]:
    """Run one read-only engine CLI command as an end-to-end availability probe.

    ``snapshot-list`` only opens the engine DB and lists rows; it performs no
    network access and writes no engine data beyond schema creation.
    """
    root = settings.engine_root
    if not (root / ENGINE_PACKAGE / "main.py").is_file():
        return {"status": "FAIL", "detail": f"engine package missing under {root}"}
    try:
        completed = subprocess.run(
            SMOKE_COMMAND,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "FAIL", "detail": f"engine smoke timed out after {timeout}s"}
    except OSError as exc:
        return {"status": "FAIL", "detail": f"engine smoke could not start: {exc}"}

    tail = (completed.stdout or completed.stderr or "").strip().splitlines()
    return {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "command": " ".join(SMOKE_COMMAND[1:]),
        "returncode": completed.returncode,
        "output_tail": tail[-3:],
    }
