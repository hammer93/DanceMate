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
