"""Live NAVER API HUB reachability check, through DanceMate's own collector.

Read-only: makes one small search per endpoint (blog / cafearticle / webkr)
and prints only the HTTP outcome and how many records came back. Credentials
are read from the environment by the collector itself, exactly the way the
runtime reads them, and are never touched or printed here. See
docs/NAVER_API_HUB.md for the endpoints and header scheme this exercises.

Usage:
    python scripts/check-naver-live.py [query]

Requires NAVER_CLIENT_ID / NAVER_CLIENT_SECRET to already be set (.env or
environment) - the same variables the runtime uses.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime import collectors  # noqa: E402
from runtime.config import load_settings  # noqa: E402

QUERY = sys.argv[1] if len(sys.argv) > 1 else "밀롱가"


def main() -> int:
    settings = load_settings()
    collectors._engine_on_path(settings)

    from src.collectors.naver import (  # noqa: E402  (engine package, path added above)
        API_HUB_BASE, ENDPOINTS, MissingNaverCredentials, NaverSearchCollector,
    )

    print(f"base: {API_HUB_BASE}")
    print(f"endpoints: {ENDPOINTS}")
    print()

    collector = NaverSearchCollector(timeout_seconds=20)
    ok = True
    for kind in ("blog", "cafe", "web"):
        try:
            rows = collector.search(QUERY, kind=kind, display=3, sort="date")
        except MissingNaverCredentials as exc:
            print(f"{kind:<5} SKIPPED  {exc}")
            ok = False
            continue
        except Exception as exc:  # noqa: BLE001 - report the gateway's own message, never a traceback with headers
            print(f"{kind:<5} FAILED   {type(exc).__name__}: {exc}")
            ok = False
            continue
        print(f"{kind:<5} 200      {len(rows)} record(s)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
