from datetime import datetime, timezone
from .database import persist_metrics_snapshot

def _ratio(num, den):
    return round(num/den,4) if den else None

def calculate_source_metrics(con, window_label="runtime"):
    sources=con.execute("SELECT source_id,platform FROM sources ORDER BY source_id").fetchall()
    out=[]
    now=datetime.now(timezone.utc).isoformat()
    for s in sources:
        sid=s["source_id"]; platform=s["platform"]
        # Discovery derived from collector runs where available
        cr=con.execute("""SELECT
            COALESCE(SUM(discovered_count),0) discovered,
            COALESCE(SUM(new_count),0) newc,
            COALESCE(SUM(duplicate_count),0) dup
            FROM collector_runs WHERE source_id=?""",(sid,)).fetchone()
        # Fallback for sources persisted by recovery/provider but without collector_runs
        discovered=cr["discovered"]
        newc=cr["newc"]
        dup=cr["dup"]
        if discovered==0:
            discovered=con.execute("SELECT COUNT(*) n FROM raw_posts WHERE source_id=?",(sid,)).fetchone()["n"]
            newc=discovered

        aq=con.execute("""SELECT
          COUNT(*) attempts,
          SUM(CASE WHEN status='FULL' THEN 1 ELSE 0 END) fullc,
          SUM(CASE WHEN status='BODY_ONLY' THEN 1 ELSE 0 END) bodyc,
          SUM(CASE WHEN status='PARTIAL' THEN 1 ELSE 0 END) partialc,
          SUM(CASE WHEN status='FAILED' THEN 1 ELSE 0 END) failedc,
          SUM(CASE WHEN poster_candidate_count>0 THEN 1 ELSE 0 END) posters
          FROM acquisition_runs WHERE source_id=?""",(sid,)).fetchone()

        rec=con.execute("""SELECT
          COUNT(DISTINCT rq.recovery_id) attempts,
          SUM(CASE WHEN rq.state='RESOLVED' THEN 1 ELSE 0 END) resolved,
          SUM(CASE WHEN rq.state='PENDING' THEN 1 ELSE 0 END) pending
          FROM recovery_queue rq WHERE rq.source_id=?""",(sid,)).fetchone()

        # Human review proxies: unresolved recovery + CONFLICT event candidates + ambiguous identity not auto-merged.
        conflicts=con.execute("""SELECT COUNT(*) n FROM event_candidates ec
          JOIN raw_posts rp ON rp.post_id=ec.post_id
          WHERE rp.source_id=? AND ec.status='CONFLICT'""",(sid,)).fetchone()["n"]
        human=(rec["pending"] or 0)+conflicts

        rev=con.execute("""SELECT COUNT(*) revision_count,
          SUM(CASE WHEN er.revision_role='CANCELLATION' THEN 1 ELSE 0 END) cancellation_count
          FROM event_revisions er
          JOIN event_instance_candidates eic ON eic.event_instance_id=er.event_instance_id
          WHERE eic.source_id=?""",(sid,)).fetchone()
        fresh=con.execute("""SELECT COUNT(*) checks,
          SUM(CASE WHEN change_detected=1 THEN 1 ELSE 0 END) changes,
          SUM(CASE WHEN critical_miss=1 THEN 1 ELSE 0 END) misses
          FROM event_refresh_checks WHERE source_id=?""",(sid,)).fetchone()

        row={
          "source_id":sid,"platform":platform,"window_label":window_label,
          "discovered_count":discovered,"new_count":newc,"duplicate_count":dup,
          "acquisition_attempts":aq["attempts"] or 0,
          "acquisition_full":aq["fullc"] or 0,
          "acquisition_body_only":aq["bodyc"] or 0,
          "acquisition_partial":aq["partialc"] or 0,
          "acquisition_failed":aq["failedc"] or 0,
          "poster_success":aq["posters"] or 0,
          "recovery_attempts":rec["attempts"] or 0,
          "recovery_resolved":rec["resolved"] or 0,
          "recovery_pending":rec["pending"] or 0,
          "human_review_count":human,
          "revision_count":rev["revision_count"] or 0,
          "cancellation_count":rev["cancellation_count"] or 0,
          "critical_cancellation_miss":fresh["misses"] or 0,
          "freshness_checks":fresh["checks"] or 0,
          "freshness_change_detected":fresh["changes"] or 0,
          "generated_at":now,
        }
        row["discovery_success_rate"]=_ratio(row["new_count"],row["discovered_count"])
        row["full_body_rate"]=_ratio(row["acquisition_full"]+row["acquisition_body_only"],row["acquisition_attempts"])
        row["poster_rate"]=_ratio(row["poster_success"],row["acquisition_attempts"])
        row["recovery_success_rate"]=_ratio(row["recovery_resolved"],row["recovery_attempts"])
        row["human_review_rate"]=_ratio(row["human_review_count"], max(row["discovered_count"],1))
        row["freshness_change_rate"]=_ratio(row["freshness_change_detected"],row["freshness_checks"])
        row["critical_cancellation_miss_rate"]=_ratio(row["critical_cancellation_miss"],row["freshness_checks"])
        persist_metrics_snapshot(con,row)
        out.append(row)
    return out

def aggregate_metrics(rows):
    def s(k): return sum(r[k] for r in rows)
    d=s("discovered_count"); a=s("acquisition_attempts"); rr=s("recovery_attempts")
    return {
      "discovered_count":d,
      "new_count":s("new_count"),
      "acquisition_attempts":a,
      "full_body_rate":_ratio(s("acquisition_full")+s("acquisition_body_only"),a),
      "poster_rate":_ratio(s("poster_success"),a),
      "recovery_success_rate":_ratio(s("recovery_resolved"),rr),
      "human_review_rate":_ratio(s("human_review_count"),max(d,1)),
      "revision_count":s("revision_count"),
      "cancellation_count":s("cancellation_count"),
      "freshness_checks":s("freshness_checks"),
      "freshness_change_rate":_ratio(s("freshness_change_detected"),s("freshness_checks")),
      "critical_cancellation_miss":s("critical_cancellation_miss"),
      "critical_cancellation_miss_rate":_ratio(s("critical_cancellation_miss"),s("freshness_checks")),
    }
