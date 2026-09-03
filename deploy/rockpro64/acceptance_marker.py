"""Deployment acceptance marker for the ROCKPro64 staging run.

Writes one identifiable record into each persistence store, then reads them
back. Run it before a restart or reboot to plant a marker, and afterwards to
prove the data survived:

    python deploy/rockpro64/acceptance_marker.py create ROCKPRO-ACCEPTANCE-001
    python deploy/rockpro64/acceptance_marker.py verify ROCKPRO-ACCEPTANCE-001

It must run inside the runtime container, which is the only place that has
both PostgreSQL access and the Information Engine on its path:

    docker compose exec -T runtime python deploy/rockpro64/acceptance_marker.py ...

Two stores, because v0.74 persistence is hybrid:

  PostgreSQL  runtime_state row, written through runtime.db - the runtime's
              own API, not raw SQL
  SQLite      a Recommendation Runtime Outcome, produced by driving the
              Information Engine v0.73 service functions
              register_generation() / resolve_generation()

The upstream recommendation, ranking, selection and generation rows those two
functions consume are seeded here exactly the way the engine's own test
harness seeds them; in production they arrive from the full pipeline, which
has no real source data yet. No engine source is modified and no engine
schema is altered.

This is deployment tooling. It adds no Information Engine feature.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from runtime import db, engine_adapter  # noqa: E402
from runtime.config import load_settings  # noqa: E402

RUNTIME_STATE_PREFIX = "acceptance."
REMEDIATION_TYPE = "FAMILY_ARCHITECTURE_FIX"
ROOT_CAUSE = "SOURCE_LOCAL_RECURRENCE"


def _engine_connection(settings):
    """Open the Information Engine's own SQLite store through its own API."""
    root = str(settings.engine_root)
    if root not in sys.path:
        sys.path.insert(0, root)
    from src.database import init_db  # noqa: PLC0415 - engine import is lazy

    return init_db(engine_adapter.engine_db_path(settings))


def _outcome_module():
    import importlib  # noqa: PLC0415

    return importlib.import_module(
        "src.origin_threshold_recommendation_fallback_family_recommendation_outcome"
    )


def _seed_generation(con, marker: str, moment: str) -> tuple[int, int]:
    """Seed the upstream rows a Recommendation Outcome is derived from.

    Mirrors engine/tests/test_origin_threshold_recommendation_fallback_family_
    recommendation_outcome.py, which is the engine's own way of standing this
    state up without running the whole pipeline.
    """
    family = f"{marker}=>{marker}"
    # family_recovery_case_id is UNIQUE in the generation-outcomes table, so a
    # second marker must not reuse the first one's case id.
    case_id = con.execute(
        "SELECT COALESCE(MAX(family_recovery_case_id), 0) + 1 AS next "
        "FROM origin_threshold_recommendation_fallback_family_generation_outcomes"
    ).fetchone()["next"]

    con.execute(
        """INSERT INTO origin_threshold_recommendation_fallback_family_remediation_recommendations(
          family_recovery_case_id,family_signature,source,status,recommended_remediation_type,
          recommended_remediation_ref,recommended_score,score_margin,human_selection_required,
          reasons_json,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (case_id, family, "EFFECTIVENESS_MEMORY_SHADOW", "SHADOW_PREFERRED",
         REMEDIATION_TYPE, marker, 0.8, 0.2, 1, "[]", moment),
    )
    rec_id = con.execute("SELECT last_insert_rowid() id").fetchone()["id"]

    con.execute(
        """INSERT INTO origin_threshold_recommendation_fallback_family_remediation_rankings(
          family_recovery_case_id,family_signature,historical_family_signature,
          remediation_type,remediation_ref,context_similarity,attempt_count,decisive_count,
          sustained_success_count,recurrence_failure_count,wilson_lower_bound,survival_score,
          evidence_score,recurrence_penalty,conservative_score,confidence_band,
          effectiveness_band,rank_state,rank_position,reasons_json,ranked_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (case_id, family, family, REMEDIATION_TYPE, marker, 1, 5, 5, 5, 0, 0.56, 1, 1, 0,
         0.8, "ESTABLISHED", "PREFERRED", "PREFERRED", 1, "[]", moment),
    )
    rank_id = con.execute("SELECT last_insert_rowid() id").fetchone()["id"]

    con.execute(
        """INSERT INTO origin_threshold_recommendation_fallback_family_remediation_selection_reviews(
          family_recovery_case_id,family_remediation_recommendation_id,
          family_remediation_ranking_id,decision,selected_remediation_type,
          selected_remediation_ref,reviewer,reason,reviewed_at)
          VALUES(?,?,?,?,?,?,?,?,?)""",
        (case_id, rec_id, rank_id, "SELECT", REMEDIATION_TYPE, marker,
         "rockpro64-acceptance", "deployment acceptance marker", moment),
    )

    con.execute(
        """INSERT INTO origin_threshold_recommendation_fallback_family_generation_outcomes(
          family_recovery_case_id,fallback_family_profile_id,root_cause_type,family_signature,
          candidate_algorithm_version_id,remediation_type,remediation_ref,status,stabilized_at)
          VALUES(?,?,?,?,?,?,?,?,?)""",
        (case_id, 1, ROOT_CAUSE, family, 10, REMEDIATION_TYPE, marker, "ACTIVE", moment),
    )
    generation_id = con.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    con.commit()
    return generation_id, case_id


def create(marker: str) -> dict:
    settings = load_settings()
    moment = datetime.now(timezone.utc).isoformat()
    result: dict[str, object] = {"marker": marker, "created_at": moment}

    # --- PostgreSQL: runtime state, through the runtime's own API ---------
    db.set_runtime_state(
        settings,
        RUNTIME_STATE_PREFIX + marker,
        json.dumps({"marker": marker, "created_at": moment, "phase": "pre"}),
    )
    result["postgres"] = {
        "state_key": RUNTIME_STATE_PREFIX + marker,
        "written": True,
    }

    # --- SQLite: a real Recommendation Runtime Outcome --------------------
    con = _engine_connection(settings)
    outcome_module = _outcome_module()
    family = f"{marker}=>{marker}"
    existing = outcome_module.outcomes(con, family_signature=family)
    if existing:
        result["engine"] = {
            "family_signature": family,
            "generation_id": existing[0]["family_generation_outcome_id"],
            "outcome_class": existing[0]["outcome_class"],
            "note": "already present, left untouched",
        }
        con.close()
        return result

    generation_id, case_id = _seed_generation(con, marker, moment)
    registered = outcome_module.register_generation(con, generation_id)
    resolved = outcome_module.resolve_generation(con, generation_id, "SUSTAINED_SUCCESS")
    con.commit()
    result["engine"] = {
        "family_signature": family,
        "family_recovery_case_id": case_id,
        "generation_id": generation_id,
        "registered_class": registered["outcome_class"],
        "outcome_class": resolved["outcome_class"],
        "recommendation_accepted": resolved["recommendation_accepted"],
        "sqlite_path": str(engine_adapter.engine_db_path(settings)),
    }
    con.close()
    return result


def verify(marker: str) -> dict:
    settings = load_settings()
    family = f"{marker}=>{marker}"
    report: dict[str, object] = {"marker": marker}

    raw = db.get_runtime_state(settings, RUNTIME_STATE_PREFIX + marker)
    report["postgres"] = {
        "found": raw is not None,
        "value": json.loads(raw) if raw else None,
    }

    con = _engine_connection(settings)
    outcome_module = _outcome_module()
    rows = outcome_module.outcomes(con, family_signature=family)
    profiles = [
        p for p in outcome_module.effectiveness_profiles(con)
        if p["family_signature"] == family
    ]
    report["engine"] = {
        "found": bool(rows),
        "count": len(rows),
        "outcome_class": rows[0]["outcome_class"] if rows else None,
        "recommendation_accepted": rows[0]["recommendation_accepted"] if rows else None,
        "effectiveness_profiles": len(profiles),
        "sqlite_path": str(engine_adapter.engine_db_path(settings)),
        "sqlite_bytes": engine_adapter.engine_db_path(settings).stat().st_size
        if engine_adapter.engine_db_path(settings).is_file() else 0,
    }
    con.close()

    report["ok"] = bool(report["postgres"]["found"] and report["engine"]["found"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["create", "verify"])
    parser.add_argument("marker", help="e.g. ROCKPRO-ACCEPTANCE-001")
    args = parser.parse_args()

    if os.environ.get("ENGINE_ROOT") is None:
        print("note: ENGINE_ROOT is unset; falling back to the repository default",
              file=sys.stderr)

    result = create(args.marker) if args.action == "create" else verify(args.marker)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.action == "verify" and not result.get("ok"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
