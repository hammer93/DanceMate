"""Container entry point: apply runtime migrations, then serve the API."""

from __future__ import annotations

import logging
import sys

from .config import load_settings, validate
from .db import DatabaseUnavailable

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, stream=sys.stdout)
    log = logging.getLogger("dancemate.runtime")

    settings = load_settings()
    problems = validate(settings)
    if problems:
        for problem in problems:
            log.error("configuration problem: %s", problem)
        return 2

    from . import migrate

    try:
        result = migrate.run(settings)
    except DatabaseUnavailable as exc:
        log.error("cannot reach PostgreSQL for migrations: %s", exc)
        return 3
    log.info("migrations applied=%s discovered=%s", result["applied"], result["discovered"])
    if result["checksum_drift"]:
        log.error("migration checksum drift: %s", result["checksum_drift"])
        return 4

    import uvicorn

    log.info(
        "serving DanceMate runtime v%s on %s:%s (env=%s)",
        settings.version,
        settings.bind_address,
        settings.port,
        settings.env,
    )
    uvicorn.run(
        "runtime.app:app",
        host=settings.bind_address,
        port=settings.port,
        log_level="info",
        access_log=False,  # microSD write minimization
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
