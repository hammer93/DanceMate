"""Real-source E2E in an explicitly isolated local PostgreSQL test DB only.

No fixture Event is inserted. Source registration uses the same service as
Admin CRUD; every post is fetched from the configured official public board.
Production use is deliberately refused to prevent a manual run racing the
single scheduler's SQLite engine transaction.
"""

from __future__ import annotations

import json
from pathlib import Path

from runtime import db, duplicates, engine_ingest, master_data, normalization, sources
from runtime.config import load_settings
from scheduler import acquisition_job, intake_job

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "docs" / "SALSA_BOARD_SOURCES.json"
TEST_DBS = {"dancemate_v092_board_fresh", "dancemate_v092_board_finalfresh"}
TARGET_ARTICLES = {
    "SRC-D-026": "944", "SRC-D-022": "1114", "SRC-D-027": "787",
    "SRC-D-028": "132", "SRC-D-029": "271",
}


def main() -> None:
    settings = load_settings()
    if settings.postgres_db not in TEST_DBS or settings.env == "production":
        raise RuntimeError(f"refusing non-isolated DB: {settings.safe_dsn}")
    specs = json.loads(SPECS.read_text(encoding="utf-8"))
    with db.connect(settings, autocommit=True) as con:
        genres = {g["code"]: g["genre_id"] for g in master_data.list_genres(con)}
        regions = {r["code"]: r["region_id"] for r in master_data.list_regions(con)}
        for spec in specs:
            config = {
                "parser": "daum_cafe_board", "cafe_url": spec["url"],
                "community_id": spec["community_id"],
                "board_name": spec["board_name"], "board_type": spec["board_type"],
                "board_urls": [spec["board_url"]], "genre_code": "SALSA",
                "lookback_days": 60,
            }
            source = sources.create_source(
                con, source_key=spec["source_key"], name=spec["name"],
                platform="DAUM_CAFE", source_role="COMMUNITY",
                authority_level="PRIMARY_ORGANIZER", url=spec["board_url"],
                genre_id=genres["SALSA"], region_id=regions[spec["region_code"]],
                config=config, enabled=True, collection_interval_minutes=180,
            )
            result = intake_job.collect_source(settings, con, source)
            print(f"{spec['source_key']}: {result['status']} "
                  f"fetched={result.get('discovered')} new={result.get('NEW')}")
            if result["status"] != "PASS":
                raise RuntimeError(f"{spec['source_key']} did not collect live")
        with con.cursor() as cur:
            ids = []
            for key, article in TARGET_ARTICLES.items():
                cur.execute(
                    "SELECT i.source_item_id FROM source_items i JOIN sources s "
                    "ON s.source_id=i.source_id WHERE s.source_key=%s "
                    "AND i.url LIKE %s",
                    (key, f"%/{article}"),
                )
                row = cur.fetchone()
                if not row:
                    raise RuntimeError(f"{key} article {article} not in real intake")
                ids.append(row[0])
    acquired = acquisition_job.reacquire(settings, ids)
    print("acquired", [(r["source_item_id"], r["status"])
                       for r in acquired["results"]])
    ingested = engine_ingest.ingest_pending(settings, limit=100)
    print("ingest", {k: ingested[k] for k in ("pending", "ingested", "failed", "candidates")})
    if ingested["failed"]:
        raise RuntimeError(f"ingest failures: {ingested['failures']}")
    normalized = normalization.normalize_all(settings)
    print("normalize", normalized)
    with db.connect(settings, autocommit=True) as con:
        print("dedupe", duplicates.scan(con))
        with con.cursor() as cur:
            cur.execute(
                "SELECT s.source_key,e.event_id,e.event_date,e.event_name,"
                "r.code,e.listing_state,e.source_url "
                "FROM events e JOIN source_items i ON i.source_item_id=e.source_item_id "
                "JOIN sources s ON s.source_id=i.source_id "
                "LEFT JOIN regions r ON r.region_id=e.region_id "
                "WHERE s.source_key=ANY(%s) AND e.event_date>=current_date "
                "ORDER BY e.event_date,e.event_id",
                (list(TARGET_ARTICLES),),
            )
            rows = cur.fetchall()
    for key, event_id, day, title, region, state, url in rows:
        print(f"event {key} {event_id} {day} {region} {state} {url} {title}")
    if len(rows) < 3:
        raise RuntimeError("real board pipeline did not create enough upcoming Events")


if __name__ == "__main__":
    main()
