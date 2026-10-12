"""DanceMate Runtime HTTP API.

LAN-only staging. Two surfaces on one app: the operator console under /admin,
and from v0.77 the alpha user surface at / and /api/events. Neither is
authenticated and neither is public -- the deployment policy requires the host
to stay behind the LAN firewall with no WAN port forwarding.

Framework choice - FastAPI + uvicorn:
  * ASGI, single process, ~40MB RSS on the 4GB ROCKPro64 target
  * pure-Python except pydantic-core, which ships manylinux aarch64 wheels,
    so the ARM64 image needs no compiler
  * JSON responses and OpenAPI come for free, which is all this admin surface
    needs - no template engine, no ORM, no task queue
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse

from . import admin, admin_pages, events_admin, health, master_admin, public
from . import directory_admin  # v0.88.0: Communities and Notices
from . import discovery_admin  # v0.89.0: Community Discovery
from .config import PRODUCT_VERSION, Settings, load_settings

app = FastAPI(
    title="DanceMate Runtime",
    version=PRODUCT_VERSION,
    description=(
        "LAN-only staging runtime for the ROCKPro64 deployment target. "
        "The operator console lives at /admin."
    ),
)

_settings: Settings | None = None


def settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


# The admin console shares one Settings instance with the API.
admin.bind(lambda: settings())
app.include_router(admin.router)
app.include_router(admin.api)
app.include_router(admin_pages.router)
app.include_router(admin_pages.api)
app.include_router(events_admin.router)
app.include_router(events_admin.api)
app.include_router(master_admin.router)
app.include_router(master_admin.api)
app.include_router(directory_admin.router)
app.include_router(discovery_admin.router)

# The alpha user surface: / , /events , /events/{id} and /api/events. Mounted
# last so it can never shadow an operator route.
public.bind(lambda: settings())
app.include_router(public.api)
app.include_router(public.router)


@app.get("/health")
def get_health() -> dict[str, Any]:
    """Liveness only - deliberately cheap so Docker can poll it often."""
    return {
        "status": "ok",
        "version": settings().version,
    }


@app.get("/health/sources")
def get_source_health() -> dict[str, Any]:
    """Which sources are collecting, and which regions still have a future.

    v0.96.31, and deliberately a second endpoint rather than a field on
    `/health`: that one is Docker's liveness probe and must stay a cheap
    constant, and `health.collect()`'s six components are the contract
    `scripts/check-server.sh` prints. Neither should start reporting a
    third-party site's outage as this runtime being unwell - a failing
    source is not a failing server. But it must be *askable*, because an
    operator reading `{"status":"ok"}` concluded for three weeks that
    everything upstream was fine.

    Read-only, one connection, no writes.
    """
    from . import db, source_freshness                     # noqa: PLC0415

    current = settings()
    with db.connect(current) as con:
        rows = source_freshness.report(con)
        failing = source_freshness.failing(rows)
        supply = source_freshness.regional_supply(con)
        zero = source_freshness.zero_supply_reasons(con)
    return {
        "status": "ok" if not failing else "SOURCES_DEGRADED",
        "version": current.version,
        "sources": {
            "total": len(rows),
            "enabled": sum(1 for r in rows
                           if r["state"] != source_freshness.DISABLED),
            "failing": len(failing),
            "by_state": {
                state: sum(1 for r in rows if r["state"] == state)
                for state in sorted({r["state"] for r in rows})
            },
            "not_collecting": [
                {
                    "source_key": r["source_key"],
                    "name": r["name"],
                    "state": r["state"],
                    "consecutive_failures": r["consecutive_failures"],
                    "last_success_at": (None if r["last_success_at"] is None
                                        else str(r["last_success_at"])),
                    "days_since_success": r["days_since_success"],
                    "error": r["last_error_message"] or r["last_error_kind"],
                }
                for r in failing
            ],
        },
        "regional_supply": [
            {
                "region": r["region_code"],
                "today": r["today"], "d7": r["d7"], "d14": r["d14"],
                "d30": r["d30"], "future_events": r["future_events"],
                "latest_future_date": (None if r["latest_future_date"] is None
                                       else str(r["latest_future_date"])),
                "days_of_runway": r["days_of_runway"],
            }
            for r in supply
        ],
        "zero_supply": zero,
    }


@app.get("/version")
def get_version() -> dict[str, Any]:
    current = settings()
    return {
        "product_runtime": current.version,
        "information_engine": current.engine_version,
        "environment": current.env,
    }


@app.get("/status")
def get_status() -> JSONResponse:
    """Full component status. 200 when healthy, 503 when any component FAILs."""
    payload = health.collect(settings())
    verdict = health.overall(payload)
    body = {
        "status": verdict,
        "version": settings().version,
        "information_engine": settings().engine_version,
        **payload,
    }
    return JSONResponse(body, status_code=200 if verdict != "FAIL" else 503)


@app.get("/status/summary", response_class=PlainTextResponse)
def get_status_summary() -> PlainTextResponse:
    """The dotted operator report, so check-server.sh needs no JSON parser."""
    payload = health.collect(settings())
    verdict = health.overall(payload)
    text = "\n".join(health.summary_lines(payload)) + "\n"
    return PlainTextResponse(text, status_code=200 if verdict != "FAIL" else 503)


@app.get("/resources")
def get_resources() -> dict[str, Any]:
    from . import resources

    return resources.snapshot(settings())
