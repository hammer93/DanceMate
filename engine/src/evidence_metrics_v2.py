from datetime import datetime, timezone
from .database import persist_evidence_metrics_v2

def _ratio(n,d): return round(n/d,4) if d else None

def calculate_metrics_v2(con, window_label="runtime"):
    now=datetime.now(timezone.utc).isoformat()
    fields=con.execute("SELECT * FROM event_field_states WHERE field_name IN ('date','start_time','venue','fee')").fetchall()
    counts={"VERIFIED":0,"EXPECTED":0,"INFERRED":0,"CONFLICT":0,"UNKNOWN":0}
    for r in fields: counts[r["confidence"]]=counts.get(r["confidence"],0)+1
    expected=[r for r in fields if r["expected_value"] is not None]
    promo=sum(1 for r in expected if r["confidence"]=="VERIFIED" and r["verified_value"] is not None)
    events=con.execute("SELECT COUNT(*) n FROM event_instances").fetchone()["n"]
    yield_events=con.execute("SELECT COUNT(*) n FROM event_candidates WHERE event_type='MILONGA'").fetchone()["n"]
    yield_posts=con.execute("SELECT COUNT(*) n FROM raw_posts").fetchone()["n"]
    access_attempts=con.execute("SELECT COUNT(*) n FROM acquisition_runs").fetchone()["n"]
    access_failures=con.execute("SELECT COUNT(*) n FROM acquisition_runs WHERE status IN ('PARTIAL','FAILED')").fetchone()["n"]
    pri_attempts=con.execute("""SELECT COUNT(*) n FROM recovery_queue rq JOIN sources s ON s.source_id=rq.source_id
                               WHERE s.authority_level IN ('PRIMARY_ORGANIZER','PRIMARY_VENUE')""").fetchone()["n"]
    pri_success=con.execute("""SELECT COUNT(*) n FROM recovery_queue rq JOIN sources s ON s.source_id=rq.source_id
                              WHERE s.authority_level IN ('PRIMARY_ORGANIZER','PRIMARY_VENUE') AND rq.state='RESOLVED'""").fetchone()["n"]
    row={"window_label":window_label,"metric_scope":"OVERALL","source_id":None,"event_count":events,
         "field_total":len(fields),"field_verified":counts["VERIFIED"],"field_expected":counts["EXPECTED"],
         "field_inferred":counts["INFERRED"],"field_conflict":counts["CONFLICT"],"field_unknown":counts["UNKNOWN"],
         "expected_to_verified_promotions":promo,"expected_to_verified_opportunities":len(expected),
         "source_yield_events":yield_events,"source_yield_posts":yield_posts,
         "access_attempts":access_attempts,"access_failures":access_failures,
         "primary_recovery_attempts":pri_attempts,"primary_recovery_success":pri_success,"generated_at":now}
    row["field_coverage_rate"]=_ratio(row["field_verified"],row["field_total"])
    row["known_field_rate"]=_ratio(row["field_verified"]+row["field_expected"]+row["field_inferred"],row["field_total"])
    row["expected_to_verified_promotion_rate"]=_ratio(promo,len(expected))
    row["source_yield_rate"]=_ratio(yield_events,yield_posts)
    row["access_failure_rate"]=_ratio(access_failures,access_attempts)
    row["primary_recovery_success_rate"]=_ratio(pri_success,pri_attempts)
    persist_evidence_metrics_v2(con,row)
    return [row]
