import json
from datetime import datetime, timezone

def _ratio(n,d):
    return round(n/d,4) if d else None

def _parse_json(v):
    if not v:
        return None
    try:
        return json.loads(v)
    except Exception:
        return None

def calculate_human_review_metrics(con):
    rows=con.execute("""SELECT * FROM human_review_actions
                        ORDER BY action_id""").fetchall()

    total=len(rows)
    by_action={"APPROVE":0,"MODIFY":0,"REJECT":0,"HOLD":0}
    by_type={"EVENT":0,"FIELD":0,"RECOVERY":0}
    corrections=0
    disagreements=0
    verified_overrides=0
    resolved_actions=0

    for r in rows:
        by_action[r["action"]]=by_action.get(r["action"],0)+1
        by_type[r["review_type"]]=by_type.get(r["review_type"],0)+1

        old=_parse_json(r["old_value_json"])
        new=_parse_json(r["new_value_json"])

        if r["action"] in ("APPROVE","MODIFY","REJECT"):
            resolved_actions += 1

        if r["action"]=="MODIFY":
            corrections += 1
            if old != new:
                disagreements += 1

        if r["action"]=="REJECT":
            disagreements += 1

        if r["review_type"]=="FIELD" and new:
            if new.get("confidence")=="VERIFIED" and new.get("source_scope")=="HUMAN_REVIEW":
                verified_overrides += 1

    # Review turnaround time:
    # Since older queue rows do not retain explicit enqueue timestamp,
    # use target object's created_at/updated_at as best available durable start.
    turnaround_seconds=[]
    for r in rows:
        created=None
        if r["review_type"]=="EVENT" and r["event_instance_id"]:
            obj=con.execute("SELECT created_at FROM event_instances WHERE event_instance_id=?",
                            (r["event_instance_id"],)).fetchone()
            created=obj["created_at"] if obj else None
        elif r["review_type"]=="RECOVERY" and r["recovery_id"]:
            obj=con.execute("SELECT created_at FROM recovery_queue WHERE recovery_id=?",
                            (r["recovery_id"],)).fetchone()
            created=obj["created_at"] if obj else None
        elif r["review_type"]=="FIELD" and r["event_instance_id"]:
            obj=con.execute("SELECT created_at FROM event_instances WHERE event_instance_id=?",
                            (r["event_instance_id"],)).fetchone()
            created=obj["created_at"] if obj else None
        if created:
            try:
                start=datetime.fromisoformat(created.replace("Z","+00:00"))
                end=datetime.fromisoformat(r["created_at"].replace("Z","+00:00"))
                turnaround_seconds.append(max(0,(end-start).total_seconds()))
            except Exception:
                pass

    avg_turnaround=(round(sum(turnaround_seconds)/len(turnaround_seconds),2)
                    if turnaround_seconds else None)

    # Reviewer reliability proxy.
    # There is not yet a second reviewer / external adjudication ground truth.
    # So we expose an operational proxy rather than pretending it is true reliability:
    # resolved non-HOLD actions with evidence / resolved actions.
    evidenced_resolved=con.execute("""SELECT COUNT(*) n
        FROM human_review_actions
        WHERE action IN ('APPROVE','MODIFY','REJECT')
          AND evidence_json IS NOT NULL
          AND evidence_json NOT IN ('{}','null')""").fetchone()["n"]

    reviewer_rows=con.execute("""SELECT actor,
        COUNT(*) total,
        SUM(CASE WHEN action='APPROVE' THEN 1 ELSE 0 END) approved,
        SUM(CASE WHEN action='MODIFY' THEN 1 ELSE 0 END) modified,
        SUM(CASE WHEN action='REJECT' THEN 1 ELSE 0 END) rejected,
        SUM(CASE WHEN action='HOLD' THEN 1 ELSE 0 END) held,
        SUM(CASE WHEN action IN ('APPROVE','MODIFY','REJECT')
                  AND evidence_json IS NOT NULL
                  AND evidence_json NOT IN ('{}','null')
                 THEN 1 ELSE 0 END) evidenced_resolved
        FROM human_review_actions
        GROUP BY actor ORDER BY actor""").fetchall()

    reviewers=[]
    for rr in reviewer_rows:
        resolved=(rr["approved"] or 0)+(rr["modified"] or 0)+(rr["rejected"] or 0)
        reviewers.append({
            "actor":rr["actor"],
            "total_reviews":rr["total"],
            "approved":rr["approved"] or 0,
            "modified":rr["modified"] or 0,
            "rejected":rr["rejected"] or 0,
            "held":rr["held"] or 0,
            "evidence_backed_resolution_rate":_ratio(rr["evidenced_resolved"] or 0,resolved),
        })

    return {
        "review_count":total,
        "action_distribution":by_action,
        "type_distribution":by_type,
        "manual_correction_rate":_ratio(corrections,total),
        "machine_human_disagreement_rate":_ratio(disagreements,total),
        "manual_verified_override_rate":_ratio(verified_overrides,total),
        "approval_rate":_ratio(by_action["APPROVE"],total),
        "rejection_rate":_ratio(by_action["REJECT"],total),
        "hold_rate":_ratio(by_action["HOLD"],total),
        "average_review_turnaround_seconds":avg_turnaround,
        "evidence_backed_resolution_rate":_ratio(evidenced_resolved,resolved_actions),
        "reviewer_reliability_status":"PROXY_ONLY",
        "reviewer_reliability_note":"True reviewer reliability requires later adjudication or independent ground truth; current metric is evidence-backed resolution rate only.",
        "reviewers":reviewers,
    }
