"""Test-database safety guard (v0.96.28, "Test DB Safety Hardening").

The runtime test suite needs a real PostgreSQL - the master-data, source and
intake modules are SQL, and a mock would only prove the mock works. For most of
this project's life the answer was "run it against the shared database; every
test rolls its transaction back". That promise is false, and it has now cost two
releases:

* v0.96.14: one run stamped ``extracted_engine_version = 0.75`` on 1,852 of
  2,468 Production ``source_item_content`` rows.
* v0.96.27: the same thing on 50 rows, from an invocation that *looked* right -
  ``POSTGRES_DB=ct_9627 scripts/run-container-tests.sh`` - because that script
  hardcoded ``--env-file .env`` and had no way to accept a database at all, so
  the host-side variable was never forwarded and the run silently targeted
  ``dancemate``.

The rollback cannot contain it. ``tests/conftest.py``'s ``pg`` fixture owns one
connection; nine test-side call sites and most of the runtime open their own
``db.connect(settings, autocommit=True)`` - ``engine_ingest.reprocess_acquired()``
stamps the re-extract cursor and commits through one of them. Any guard that
lives in the fixture is a guard around the wrong thing.

So the decision is made once, before a single test runs, about the *database*
rather than about any connection to it: a database is expendable only if it says
so itself. ``COMMENT ON DATABASE`` is the marker, and it is deliberately not a
table:

* migrations can never create it, so no amount of schema work makes a
  production database look disposable;
* it survives repeated runs, so a scratch database is reusable and the guard
  needs no "how many rows is too many" threshold - the kind of number
  ``guard_db_identity``'s ``sources > 0`` test shows the weakness of;
* it is one statement to set by hand, which keeps an ad-hoc scratch database a
  supported thing rather than a reason to reach for the live one.

What lives here is the pure decision - given the marker a database carries, and
the name of the database this deployment actually runs on, what is the verdict -
so it is unit-testable with no database at all. Enforcement lives where those
things are real: ``tests/conftest.py`` refuses to start a session, and
``scripts/_common.sh``/``scripts/run-container-tests.sh`` refuse to start a
container. Mirrors ``runtime/deploy_guard.py``'s own report-dict pattern.
"""

from __future__ import annotations

from typing import Any

#: What a database must say about itself before the suite will write to it.
#: Matched exactly, after stripping surrounding whitespace - a database whose
#: comment merely mentions testing is not a declaration.
DISPOSABLE_MARKER = "dancemate-disposable-test-db"

#: Read the marker from inside the database being tested. `shobj_description`
#: rather than `obj_description`: a database comment is a *shared* catalog
#: object, so it is reachable from any database but only names the current one
#: when filtered this way.
MARKER_READ_SQL = (
    "SELECT shobj_description(oid, 'pg_database') FROM pg_database "
    "WHERE datname = current_database()"
)


def marker_set_sql(database: str) -> str:
    """The statement that declares ``database`` disposable.

    A database name cannot be a bind parameter in ``COMMENT ON DATABASE``, so it
    is quoted here rather than interpolated at each call site, and a name that
    could break out of the identifier is refused outright instead of escaped -
    every caller of this generates its own name or takes one from an operator on
    the same machine, and none of them has a reason to use a name like that.
    """
    if not _is_plain_identifier(database):
        raise ValueError(
            f"refusing to build a COMMENT statement for {database!r}: a scratch "
            "database name may contain only letters, digits and underscores"
        )
    return f"COMMENT ON DATABASE {database} IS '{DISPOSABLE_MARKER}'"


def _is_plain_identifier(name: str) -> bool:
    return bool(name) and all(c.isalnum() or c == "_" for c in name) \
        and not name[0].isdigit()


def disposable_report(marker: str | None, database: str) -> dict[str, Any]:
    """Has ``database`` declared itself expendable?

    ``marker`` is whatever ``MARKER_READ_SQL`` returned - ``None`` for a
    database with no comment at all, which is what every production and
    freshly-installed database looks like.
    """
    found = (marker or "").strip()
    if found == DISPOSABLE_MARKER:
        return {
            "status": "PASS",
            "database": database,
            "detail": f"database '{database}' is declared disposable",
        }
    saw = "no comment" if not found else f"comment {found!r}"
    return {
        "status": "FAIL",
        "database": database,
        "detail": (
            f"database '{database}' is not declared disposable ({saw}). The test "
            "suite commits through connections no fixture can roll back, so it "
            "will not run here. Use scripts/run-container-tests.sh, which creates "
            "and drops its own scratch database, or declare one by hand:\n"
            f"    {marker_set_sql('your_scratch_db')}"
        ),
    }


def deployment_collision_report(target: str, deployment: str | None) -> dict[str, Any]:
    """Is the database about to be tested the one this deployment runs on?

    The second, independent signal, and the one that catches v0.96.27's exact
    shape before a container even starts: an override that never arrived leaves
    the target equal to ``.env``'s own ``POSTGRES_DB``. Checked by name because
    at that point there is nothing else to check - no connection has been made
    yet - and a deployment whose ``.env`` is absent (a developer checkout with no
    ``.env`` at all) has no database to collide with.
    """
    if deployment and target == deployment:
        return {
            "status": "FAIL",
            "database": target,
            "detail": (
                f"refusing to run tests against '{target}': that is this "
                "deployment's own database, named in .env as POSTGRES_DB. If an "
                "override was meant to apply, it did not arrive."
            ),
        }
    return {
        "status": "PASS",
        "database": target,
        "detail": f"'{target}' is not this deployment's own database",
    }


def preflight_report(marker: str | None, target: str,
                     deployment: str | None = None) -> dict[str, Any]:
    """Both checks, as one verdict. FAILs name every failing check."""
    checks = {
        "deployment_collision": deployment_collision_report(target, deployment),
        "disposable": disposable_report(marker, target),
    }
    failed = [name for name, r in checks.items() if r["status"] != "PASS"]
    return {
        "status": "FAIL" if failed else "PASS",
        "database": target,
        "failed": failed,
        "checks": checks,
        "detail": "\n".join(checks[name]["detail"] for name in failed)
        or f"database '{target}' is safe to test against",
    }
