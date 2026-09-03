"""Container entry point for the DanceMate scheduler worker."""

from __future__ import annotations

import logging
import sys

from runtime.config import load_settings, validate

from .worker import run_forever

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, stream=sys.stdout)
    log = logging.getLogger("dancemate.scheduler")

    settings = load_settings()
    problems = validate(settings)
    if problems:
        for problem in problems:
            log.error("configuration problem: %s", problem)
        return 2
    return run_forever(settings)


if __name__ == "__main__":
    raise SystemExit(main())
