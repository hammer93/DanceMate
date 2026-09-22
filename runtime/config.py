"""Environment-driven configuration for the DanceMate runtime and scheduler.

Every value has a safe default so the module imports (and the unit tests run)
without any environment set up. Nothing here reads a secret from disk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Product runtime version. Deliberately distinct from the Information Engine
# version: the Information Engine is versioned by its own extraction
# behaviour. v0.74 is the first version DanceMate modified (time, venue and
# fee reading); the untouched import is tagged engine-v0.73-baseline.
PRODUCT_VERSION = "0.96.8"
# v0.82 bumped this for parse_time_range()'s fallback-ordering fix (prefer an
# EVIDENCE_EXPLICIT reading over an ambiguous one - see extraction_rules.py) -
# a real change to what the engine reads, not just new Source rows.
# v0.84.1 bumped it again for extract_fee(): Korean 만원 notation, free
# admission, and a package/session-tier exclusion guard - see
# extraction_rules.py.
# v0.84.3 bumped it again: extract_with_image_fallback() gained venue as a
# fourth fallback field alongside date/time/fee, and extract_fee()'s
# _NOT_A_FEE narrowed "주차" so "무료주차" no longer disqualifies a real,
# nearby, clearly-labelled fee.
# v0.84.4 bumped it again: classify_with_image_evidence() (classifier.py)
# and process_discovered_post()'s call to it (live_pipeline.py) - an
# image-only post can now be classified from a trusted poster reading, not
# just title+body, closing the gap that made v0.84.3's own OCR fallback
# unreachable for a genuinely empty-body post.
# v0.91.0 bumped it again: extractor.DATE_PATTERNS gained a year-plus-range
# reading (extract_single() now also emits MULTI_DAY_EVENT/genre_hint
# evidence), extraction_rules.extract_venue() gained the truncated-label
# guard, and classifier.py gained party_evidence_bundle() and
# detect_genre_hints() - all real changes to what the engine reads, not
# just new Source rows.
# v0.96.0 bumped this to 0.89: classifier.py gained the recap/administrative
# non-event gate and the notice evidence bundle, extractor.py monthly and
# nth-weekday dates plus schedule-post expansion, extraction_rules.py the
# single start clock and unlabelled venue forms - what the engine reads changed.
# v0.96.2 bumped this to 0.90: extraction_rules.extract_venue() refuses a
# person/account/room "@" (grammar rules, no name list), extractor segments a
# multi-program post at structural anchors instead of the character midpoint
# (a clock is never cut in half) and picks the reviewed segment of an
# ambiguous post by the classifier's own vocabulary; parse_time_range()'s
# other-programme window stops at a bracket heading / line break. What the
# engine reads changed, so by the same rule every earlier bump followed.
# v0.96.3 deliberately does NOT bump this: it adds the operational path for
# re-reading stored bodies with whatever engine version is running
# (`extracted_engine_version`, migration 042), and changes nothing about what
# the engine reads. Bumping it would have made every row stale for no reason
# and, worse, thrown away the 0.91 baseline the re-extract is measured
# against.
# v0.96.2 (release-blocker fix, product version unchanged) bumped this to
# 0.91: extract_venue() now reads an honorific with an attached particle
# ("선배님은", "선배님께서") as a person and a multi-word "@" value with a
# finite predicate on any word as prose - Production item 2020's second
# mention had slipped through 0.90's detached-particle / last-token rules.
# v0.96.4 bumps this to 0.92: extractor.DATE_PATTERNS reads a month that
# names two of its own days ("9월 19,20일" - four Production items, all one
# weekly social series, previously dateless), flagging the span with the same
# MULTI_DAY_EVENT evidence the existing "9.18-20" range uses; and
# extraction_rules._near_window() stops the window a word may *qualify* a
# clock through at a structural break, exactly as the window that
# disqualifies one already did, so a section heading can no longer claim a
# neighbouring programme's clock. What the engine reads changed, so the
# version does. v0.96.3's incremental re-extract needs nothing else: every
# stored body is stale against 0.92 by definition and the scheduler works
# through them 25 at a time.
# v0.96.5 bumps this to 0.93: classifier.classify() reads a night announced
# in a post's own title through a body that also teaches - the rule
# social_evidence() has given the other scenes since v0.79, which the milonga
# family never had, and which cannot simply be copied because a lesson
# advert names the milonga it teaches you to dance at. Twelve Production
# items stop being CLASS-with-no-candidate; sweeping all 2,267 collected
# items changes those twelve and nothing else in either direction. What
# the engine reads out of a stored body changed, so the version does, and
# v0.96.3's incremental pass re-reads every row against 0.93 with no
# migration and no cursor hack.
# v0.96.7 bumps this to 0.94: classifier.classify() reads a post whose own
# title sells a lesson in the education vocabulary `class_words` never
# carried (수업, 특강, 클래스, 클라스, 강좌, 레슨) as a class rather than as
# the night it teaches you to dance at. Sweeping all 2,298 collected items
# changes 61: 18 stop being events (every one a lesson advert, a course
# syllabus, a recap or a guitar-school post - 0 genuine nights, 0 upcoming
# nights), 6 become SOCIAL_WITH_CLASS instead of SOCIAL (still events, now
# naming the lesson they carry) and 37 become CLASS instead of OTHER. What
# the engine reads out of a stored body changed, so the version does, and
# v0.96.3's incremental pass re-reads every row against 0.94 with no
# migration and no cursor hack.
# v0.96.8 bumps this to 0.95: classifier.classify() asks its recap/
# administrative guard before the collector's own `known_event_type`, so a
# post whose title says it is a club's archive of a night already danced
# ("정기모임 영상 #01", "금요정모 사진") or a notice that the night is off
# ("금요정모 휴강" - the one word the guard gained) is read as OTHER even on
# a dedicated event board. Sweeping all 2,327 collected items changes 154
# classifications; 126 stop being events, every one an archive post or a
# cancellation, one of them still upcoming (item 3635). 0 genuine nights and
# 0 genuine upcoming nights are lost, and nothing becomes an event that was
# not one. What the engine reads out of a stored title changed, so the
# version does, and v0.96.3's incremental pass re-reads every row against
# 0.95 with no migration and no cursor hack.
DEFAULT_ENGINE_VERSION = "0.95"

REPO_ROOT = Path(__file__).resolve().parents[1]


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# DANCEMATE_HOST and DANCEMATE_BIND_ADDRESS are NOT the same thing:
#
#   DANCEMATE_HOST          the address the server listens on INSIDE the
#                           container. Almost always 0.0.0.0 - a container has
#                           no LAN address of its own, so binding the host's
#                           LAN IP here fails with "could not bind on any
#                           address".
#   DANCEMATE_BIND_ADDRESS  the HOST interface Docker publishes the port on.
#                           Compose and the health scripts read it; the
#                           application never does.


@dataclass(frozen=True)
class Settings:
    env: str
    version: str
    engine_version: str

    listen_address: str
    port: int

    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str

    engine_root: Path
    engine_data_dir: Path
    data_dir: Path
    log_dir: Path
    backup_dir: Path

    scheduler_heartbeat_seconds: int
    scheduler_job_interval_seconds: int

    storage_warn_percent: int
    storage_critical_percent: int
    backup_retention: int
    backup_max_age_hours: int

    @property
    def dsn(self) -> str:
        return (
            f"host={self.postgres_host} port={self.postgres_port} "
            f"dbname={self.postgres_db} user={self.postgres_user} "
            f"password={self.postgres_password}"
        )

    @property
    def safe_dsn(self) -> str:
        """DSN with the password removed - safe to log or return over HTTP."""
        return (
            f"host={self.postgres_host} port={self.postgres_port} "
            f"dbname={self.postgres_db} user={self.postgres_user}"
        )


def load_settings() -> Settings:
    engine_root = Path(_env("ENGINE_ROOT", str(REPO_ROOT / "engine")))
    return Settings(
        env=_env("DANCEMATE_ENV", "staging"),
        version=_env("DANCEMATE_VERSION", PRODUCT_VERSION),
        engine_version=_env("ENGINE_VERSION", DEFAULT_ENGINE_VERSION),
        listen_address=_env("DANCEMATE_HOST", "0.0.0.0"),
        port=_env_int("DANCEMATE_PORT", 8080),
        postgres_host=_env("POSTGRES_HOST", "postgres"),
        postgres_port=_env_int("POSTGRES_PORT", 5432),
        postgres_db=_env("POSTGRES_DB", "dancemate"),
        postgres_user=_env("POSTGRES_USER", "dancemate"),
        postgres_password=_env("POSTGRES_PASSWORD", ""),
        engine_root=engine_root,
        engine_data_dir=Path(_env("ENGINE_DATA_DIR", str(engine_root / "data"))),
        data_dir=Path(_env("DANCEMATE_DATA_DIR", str(REPO_ROOT / "data"))),
        log_dir=Path(_env("DANCEMATE_LOG_DIR", str(REPO_ROOT / "logs"))),
        backup_dir=Path(_env("DANCEMATE_BACKUP_DIR", str(REPO_ROOT / "backup"))),
        scheduler_heartbeat_seconds=_env_int("SCHEDULER_HEARTBEAT_SECONDS", 60),
        scheduler_job_interval_seconds=_env_int("SCHEDULER_JOB_INTERVAL_SECONDS", 300),
        storage_warn_percent=_env_int("STORAGE_WARN_PERCENT", 75),
        storage_critical_percent=_env_int("STORAGE_CRITICAL_PERCENT", 95),
        backup_retention=_env_int("BACKUP_RETENTION", 7),
        backup_max_age_hours=_env_int("BACKUP_MAX_AGE_HOURS", 48),
    )


def validate(settings: Settings) -> list[str]:
    """Return a list of configuration problems. Empty list means valid."""
    problems: list[str] = []
    if not settings.postgres_password:
        problems.append("POSTGRES_PASSWORD is empty")
    if settings.postgres_password == "CHANGE_ME":
        problems.append("POSTGRES_PASSWORD is still the .env.example placeholder")
    if not 1 <= settings.port <= 65535:
        problems.append(f"DANCEMATE_PORT out of range: {settings.port}")
    if settings.scheduler_heartbeat_seconds < 30:
        problems.append(
            "SCHEDULER_HEARTBEAT_SECONDS below 30 - too much SD card write pressure"
        )
    if not 1 <= settings.storage_warn_percent < settings.storage_critical_percent <= 100:
        problems.append("STORAGE_WARN_PERCENT/STORAGE_CRITICAL_PERCENT are inconsistent")
    if settings.backup_retention < 1:
        problems.append("BACKUP_RETENTION must be at least 1")
    return problems
