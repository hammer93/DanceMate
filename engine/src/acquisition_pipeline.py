from datetime import datetime, timezone
from .acquirers.daum_post import DaumPostAcquirer
from .database import (
    persist_acquisition_result, update_raw_post_acquisition, enqueue_recovery, pending_metadata_posts,
    update_source_access, media_rows_for_post, classify_media_record,
    start_observation, finish_observation, latest_lineage_for_post
)
from .collectors.base import RawPostRecord
from .live_pipeline import process_discovered_post
from .database import persist_events
from .source_state import derive_source_state
from .media_classifier import classify_media

def _row_value(row, key):
    """A column if the caller's query selected it, else None.

    acquire_posts takes rows from several different queries, and sqlite3.Row
    raises rather than returning None for a column that is not there.
    """
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


def acquire_pending_daum(con, *, mode="live", acquirer=None, limit=None, lineage_map=None):
    acquirer = acquirer or DaumPostAcquirer()
    rows = list(pending_metadata_posts(con))
    if limit:
        rows = rows[:limit]
    summary = []
    for row in rows:
        started = datetime.now(timezone.utc).isoformat()
        link=None
        if lineage_map and row["post_id"] in lineage_map:
            link=lineage_map[row["post_id"]]
        else:
            link=latest_lineage_for_post(con,row["post_id"])
        obs_id=start_observation(
            con,run_type="ACQUISITION",source_id=row["source_id"],target_url=row["source_url"],
            metadata={"mode":mode,"post_id":row["post_id"]},
            lineage_id=(link.get("lineage_id") if link else None),
            parent_observation_id=(link.get("observation_id") if link else None),
            stage="ACQUISITION"
        )
        result = acquirer.acquire(post_id=row["post_id"], source_id=row["source_id"], url=row["source_url"])
        persist_acquisition_result(con, result, mode=mode, started_at=started)

        srcrow=con.execute("SELECT source_role FROM sources WHERE source_id=?",(row["source_id"],)).fetchone()
        source_role=srcrow["source_role"] if srcrow else "UNKNOWN"
        authority,access=derive_source_state(
            source_role=source_role,
            acquisition_status=result.status,
            http_status=result.http_status,
            body_available=bool(result.body_text)
        )
        update_source_access(con,row["source_id"],authority_level=authority,access_state=access)

        for mr in media_rows_for_post(con,row["post_id"]):
            dec=classify_media(url=mr["media_url"],surrounding_text=result.body_text or "")
            classify_media_record(con,mr["media_id"],dec.media_class,dec.reason)

        upgraded = False
        reprocessed = []
        if result.status in {"FULL","BODY_ONLY"} and result.body_text:
            update_raw_post_acquisition(con, row["post_id"], body=result.body_text, acquisition_quality=result.status)
            # Carry the post's own date. Re-extraction reads the dates out of
            # the body again, and a bare "8/22" cannot be placed in a year
            # without it -- dropping it here silently un-dated every post whose
            # body we successfully fetched.
            post = RawPostRecord(
                source_id=row["source_id"], platform="DAUM_CAFE", source_url=row["source_url"],
                title=row["title"], body=result.body_text,
                published_at=_row_value(row, "published_at"), acquisition_quality=result.status
            )
            source_role_row = con.execute("SELECT source_role FROM sources WHERE source_id=?", (row["source_id"],)).fetchone()
            source_role = source_role_row["source_role"] if source_role_row else "SECONDARY"
            processed = process_discovered_post(con, post, source_role)
            # Avoid duplicating an already-created METADATA event candidate from discovery.
            con.execute("DELETE FROM evidences WHERE candidate_id IN (SELECT candidate_id FROM event_candidates WHERE post_id=?)", (row["post_id"],))
            con.execute("DELETE FROM event_candidates WHERE post_id=?", (row["post_id"],))
            if processed["events"]:
                persist_events(con, row["post_id"], processed["events"])
                con.commit()
            upgraded = True
            reprocessed = [e.to_dict() for e in processed["events"]]
        else:
            reason = result.error_code or ("POSTER_UNAVAILABLE" if not result.images else "FULL_BODY_UNAVAILABLE")
            enqueue_recovery(con, row["post_id"], row["source_id"], row["title"], reason)

        # FULL body without usable images is still recoverable for poster evidence if core fields remain incomplete.
        if result.status == "BODY_ONLY":
            enqueue_recovery(con, row["post_id"], row["source_id"], row["title"], "POSTER_UNAVAILABLE")

        finish_observation(
            con,obs_id,
            result_status="PASS" if result.status in {"FULL","BODY_ONLY"} else ("PARTIAL" if result.status=="PARTIAL" else "FAILED"),
            acquisition_attempt_count=1,
            acquisition_success_count=1 if result.status in {"FULL","BODY_ONLY"} else 0,
            acquisition_failure_count=1 if result.status not in {"FULL","BODY_ONLY"} else 0,
            error_code=result.error_code,error_message=result.error
        )
        obsrow=con.execute("SELECT lineage_id FROM observation_runs WHERE observation_id=?",(obs_id,)).fetchone()
        summary.append({
            "post_id":row["post_id"], "url":row["source_url"], "status":result.status,
            "http_status":result.http_status, "body_chars":result.body_chars,
            "images":len(result.images), "poster_candidates":len(result.poster_candidates),
            "error_code":result.error_code, "upgraded":upgraded, "events":reprocessed,
            "lineage_id":obsrow["lineage_id"],"observation_id":obs_id
        })
    return summary
