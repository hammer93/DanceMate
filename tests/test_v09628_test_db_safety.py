"""Test-database safety hardening (v0.96.28).

The suite needs a real PostgreSQL, and for most of this project's life it was
pointed at the shared one on the reassurance that "every test runs in a
transaction that is rolled back". That promise was false and it cost two
releases: v0.96.14 stamped ``extracted_engine_version = 0.75`` on 1,852 of 2,468
Production ``source_item_content`` rows, and v0.96.27 did it again on 50, from an
invocation that looked right -

    POSTGRES_DB=ct_9627 scripts/run-container-tests.sh

- because that script hardcoded ``--env-file .env``, took no database argument at
all, and therefore never forwarded the host-side variable. The rollback cannot
contain it: the ``pg`` fixture owns one connection, while nine test call sites
and most of the runtime open their own ``db.connect(settings, autocommit=True)``.

Three things are held here: that the decision logic refuses what it must, that
``scripts/run-container-tests.sh`` now builds an invocation which cannot target
the deployment's database, and that the marker really is unreachable from the
schema - a database declares itself disposable with a comment, and no migration
can write one.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from runtime import scratch_db_guard

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
COMMON = SCRIPTS / "_common.sh"
RUNNER = SCRIPTS / "run-container-tests.sh"
CONFTEST = REPO_ROOT / "tests" / "conftest.py"
MIGRATIONS = REPO_ROOT / "migrations" / "runtime"


def _bash() -> str:
    found = shutil.which("bash")
    if not found:
        pytest.skip("no bash available to exercise the shell helpers")
    return found


def _stub_repo(tmp_path: Path, *, deployment_db: str | None = "dancemate") -> Path:
    """A throwaway tree with the real helpers and a fake .env."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(COMMON, tmp_path / "scripts" / "_common.sh")
    shutil.copy(RUNNER, tmp_path / "scripts" / "run-container-tests.sh")
    (tmp_path / "VERSION").write_text("0.0.0\n", encoding="utf-8")
    lines = ["POSTGRES_USER=dancemate", "DANCEMATE_POSTGRES_CONTAINER=pg"]
    if deployment_db is not None:
        lines.append(f"POSTGRES_DB={deployment_db}")
    (tmp_path / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


# --- the decision, as a pure function ---------------------------------------

def test_a_database_with_no_comment_is_never_disposable():
    """Every production and freshly-installed database looks exactly like this."""
    report = scratch_db_guard.disposable_report(None, "dancemate")
    assert report["status"] == "FAIL"
    assert "not declared disposable" in report["detail"]
    assert "scripts/run-container-tests.sh" in report["detail"], \
        "a refusal must name the supported way to get a database that passes"


def test_the_marker_must_match_exactly():
    """A comment that merely mentions testing is not a declaration."""
    for comment in ("a test database", "disposable", "dancemate",
                    "dancemate-disposable-test-db-ish", ""):
        assert scratch_db_guard.disposable_report(comment, "x")["status"] == "FAIL", comment


def test_the_marker_is_accepted_with_surrounding_whitespace():
    marker = f"  {scratch_db_guard.DISPOSABLE_MARKER}\n"
    assert scratch_db_guard.disposable_report(marker, "ct_x")["status"] == "PASS"


def test_the_deployment_database_is_refused_by_name():
    """v0.96.27's exact shape: the override never arrived, so the target is
    still whatever .env says."""
    report = scratch_db_guard.deployment_collision_report("dancemate", "dancemate")
    assert report["status"] == "FAIL"
    assert "did not arrive" in report["detail"]


def test_another_database_is_not_a_collision():
    assert scratch_db_guard.deployment_collision_report(
        "dm_test_1", "dancemate")["status"] == "PASS"


def test_a_checkout_with_no_env_has_no_database_to_collide_with():
    assert scratch_db_guard.deployment_collision_report("x", None)["status"] == "PASS"


def test_preflight_names_every_failing_check():
    report = scratch_db_guard.preflight_report(None, "dancemate", "dancemate")
    assert report["status"] == "FAIL"
    assert set(report["failed"]) == {"deployment_collision", "disposable"}
    report = scratch_db_guard.preflight_report(
        scratch_db_guard.DISPOSABLE_MARKER, "dm_test_1", "dancemate")
    assert report["status"] == "PASS" and report["failed"] == []


def test_the_marker_statement_refuses_a_name_it_cannot_quote():
    """The database name cannot be a bind parameter in COMMENT ON DATABASE, so a
    name that could break out of the identifier is refused rather than escaped."""
    for bad in ("ct; DROP DATABASE dancemate", "ct'x", "ct-x", "", "9ct"):
        with pytest.raises(ValueError):
            scratch_db_guard.marker_set_sql(bad)
    assert scratch_db_guard.marker_set_sql("dm_test_1") == (
        "COMMENT ON DATABASE dm_test_1 IS 'dancemate-disposable-test-db'")


# --- the marker is unreachable from the schema -------------------------------

def test_no_migration_can_declare_a_database_disposable():
    """The whole point of a database comment rather than a table: running the
    migrations on production must never make it look testable."""
    for sql in sorted(MIGRATIONS.glob("*.sql")):
        text = sql.read_text(encoding="utf-8")
        assert scratch_db_guard.DISPOSABLE_MARKER not in text, sql.name
        assert "COMMENT ON DATABASE" not in text.upper(), sql.name


def test_the_shell_and_python_markers_are_the_same_string():
    text = COMMON.read_text(encoding="utf-8")
    assert f'DISPOSABLE_DB_MARKER="{scratch_db_guard.DISPOSABLE_MARKER}"' in text


# --- the shell guard, through real bash --------------------------------------

def test_guard_refuses_the_deployment_database(tmp_path):
    bash = _bash()
    repo = _stub_repo(tmp_path)
    result = subprocess.run(
        [bash, "-c", "source scripts/_common.sh; guard_not_deployment_database dancemate"],
        cwd=repo, capture_output=True, text=True)
    assert result.returncode != 0
    assert "deployment's own database" in result.stderr


def test_guard_accepts_a_scratch_name(tmp_path):
    bash = _bash()
    repo = _stub_repo(tmp_path)
    result = subprocess.run(
        [bash, "-c", "source scripts/_common.sh; "
                     "guard_not_deployment_database dm_test_1 && echo GUARD_OK"],
        cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "GUARD_OK" in result.stdout


@pytest.mark.parametrize("name", ["ct-x", "ct;x", "ct x", "ct'x", ""])
def test_guard_refuses_a_name_it_cannot_safely_interpolate(tmp_path, name):
    bash = _bash()
    repo = _stub_repo(tmp_path)
    result = subprocess.run(
        [bash, "-c", f"source scripts/_common.sh; guard_not_deployment_database '{name}'"],
        cwd=repo, capture_output=True, text=True)
    assert result.returncode != 0, f"{name!r} should be refused"


def test_generated_scratch_names_are_safe_and_unique(tmp_path):
    bash = _bash()
    repo = _stub_repo(tmp_path)
    result = subprocess.run(
        [bash, "-c", "source scripts/_common.sh; scratch_db_name; echo; scratch_db_name"],
        cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    for name in result.stdout.split():
        assert scratch_db_guard._is_plain_identifier(name), name
        assert name != "dancemate"


def test_drop_refuses_a_database_that_is_not_declared_disposable(tmp_path):
    """If a name ever collided with something real, losing the run beats losing
    the data. A stub psql reports an empty comment."""
    bash = _bash()
    repo = _stub_repo(tmp_path)
    (repo / "bin").mkdir()
    (repo / "bin" / "docker").write_text(
        '#!/usr/bin/env bash\n'
        '# `docker exec -i <c> psql ... -tAc <sql>` - answer the marker query with\n'
        '# a comment that is not the marker, and record any DROP that is attempted.\n'
        'for a in "$@"; do case "$a" in *"DROP DATABASE"*) echo "$a" >> dropped.txt ;; esac; done\n'
        'for a in "$@"; do case "$a" in *shobj_description*) echo "someone-elses-db"; exit 0 ;; esac; done\n'
        'exit 0\n',
        encoding="utf-8")
    (repo / "bin" / "docker").chmod(0o755)
    result = subprocess.run(
        [bash, "-c", 'export PATH="$PWD/bin:$PATH"; source scripts/_common.sh; '
                     'drop_scratch_db dm_test_1 dancemate'],
        cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "not dropping" in result.stderr
    assert not (repo / "dropped.txt").exists(), \
        "a database without the marker must never be dropped"


# --- the runner's shape ------------------------------------------------------

def test_the_runner_overrides_the_database_after_the_env_file():
    """The v0.96.27 defect, as a text assertion: --env-file sets POSTGRES_DB to
    the deployment's own, so the override has to come later to win."""
    # Comment lines quote the old broken invocation on purpose, so judge the
    # code alone.
    code = "\n".join(line for line in RUNNER.read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith("#"))
    chunks = [c for c in code.split("container_run_as_repo_owner")[1:]
              if "--env-file" in c]
    assert len(chunks) >= 2, "the migrate step and the test step both pass the env file"
    for chunk in chunks:
        env_file = chunk.index("--env-file")
        override = chunk.index('-e "POSTGRES_DB=$SCRATCH_DB"')
        assert override > env_file, \
            "-e POSTGRES_DB must follow --env-file, or the env file wins"


def test_the_runner_creates_migrates_and_drops_its_own_database():
    text = RUNNER.read_text(encoding="utf-8")
    assert "create_scratch_db" in text
    assert "runtime.migrate" in text
    assert "drop_scratch_db" in text
    assert "trap cleanup_scratch_db EXIT" in text, \
        "an interrupted or failing run must still drop its scratch database"


def test_the_runner_guards_before_it_creates_anything():
    text = RUNNER.read_text(encoding="utf-8")
    assert text.index("guard_not_deployment_database") < text.index("create_scratch_db")


def test_the_runner_announces_the_database_it_will_use():
    assert "TEST DB TARGET" in RUNNER.read_text(encoding="utf-8")


def test_the_runner_accepts_a_database_argument_at_all():
    """There was no way to say it before, which is why the wrong thing happened."""
    text = RUNNER.read_text(encoding="utf-8")
    assert "--db" in text and "--keep-db" in text


# --- the suite refuses to start ----------------------------------------------

def test_conftest_refuses_a_session_against_a_database_that_is_not_disposable():
    text = CONFTEST.read_text(encoding="utf-8")
    assert "def pytest_sessionstart" in text
    assert "scratch_db_guard" in text
    assert "pytest.exit" in text, "a refusal must stop the session, not skip a test"
    assert "TEST DB TARGET" in text


def test_conftest_no_longer_promises_that_a_rollback_makes_a_shared_database_safe():
    text = CONFTEST.read_text(encoding="utf-8")
    before, _, after = text.partition("v0.96.28")
    assert after, "the correction itself must be recorded, not merely applied"
    for claim in ("a shared staging database is never polluted",
                  "docker compose exec -T runtime python -m pytest"):
        assert claim not in before, (
            f"{claim!r} must not stand as current guidance; two releases disproved it")
        assert claim in after, (
            f"{claim!r} should survive as the quoted thing the correction is about")
