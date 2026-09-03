import json
from datetime import datetime, timezone, date

POLICY_VERSION="v0.49"
BASELINE_TEXT_THRESHOLD=0.86
MIN_DECISIVE_REVIEWS_FOR_THRESHOLD_CHANGE=5
MIN_THRESHOLD=0.80
MAX_THRESHOLD=0.95

def _now():
    return datetime.now(timezone.utc).isoformat()

def _decode_json(value):
    try:
        return json.loads(value) if value else []
    except Exception:
        return []

def calibration_metrics(con):
    rows=con.execute("""SELECT r.review_id,r.cluster_id,r.decision,r.reviewed_at
      FROM origin_inference_reviews r
      JOIN (
        SELECT cluster_id,MAX(review_id) review_id
        FROM origin_inference_reviews GROUP BY cluster_id
      ) latest ON latest.review_id=r.review_id
      ORDER BY r.review_id""").fetchall()
    synd=sum(r["decision"]=="CONFIRM_SYNDICATION" for r in rows)
    indep=sum(r["decision"]=="CONFIRM_INDEPENDENT" for r in rows)
    hold=sum(r["decision"]=="HOLD" for r in rows)
    decisive=synd+indep
    precision=(synd/decisive) if decisive else None
    false_positive=(indep/decisive) if decisive else None
    return {
        "reviewed_cluster_count":len(rows),
        "decisive_review_count":decisive,
        "confirmed_syndication_count":synd,
        "confirmed_independent_count":indep,
        "hold_count":hold,
        "precision":precision,
        "false_positive_rate":false_positive
    }

def shadow_threshold_recommendation(metrics,baseline=BASELINE_TEXT_THRESHOLD):
    decisive=metrics["decisive_review_count"]
    fp=metrics["false_positive_rate"]
    precision=metrics["precision"]
    target=float(baseline)
    status="INSUFFICIENT_EVIDENCE"
    reasons=[]

    if decisive < MIN_DECISIVE_REVIEWS_FOR_THRESHOLD_CHANGE:
        reasons.append(
            f"need >= {MIN_DECISIVE_REVIEWS_FOR_THRESHOLD_CHANGE} decisive human reviews; have {decisive}")
    else:
        if fp is not None and fp>=0.25:
            target=min(MAX_THRESHOLD,baseline+0.03)
            status="SHADOW_TIGHTEN"
            reasons.append(
                f"false-positive rate {fp:.3f} >= 0.25; tighten near-duplicate threshold in Shadow")
        elif fp is not None and fp<=0.10 and precision is not None and precision>=0.90:
            target=max(MIN_THRESHOLD,baseline-0.01)
            status="SHADOW_RELAX"
            reasons.append(
                f"precision {precision:.3f} and false-positive rate {fp:.3f} support a small Shadow relaxation")
        else:
            status="SHADOW_HOLD"
            reasons.append("human outcomes do not justify changing the current threshold")

    return {
        "baseline_text_threshold":float(baseline),
        "shadow_recommended_text_threshold":round(float(target),4),
        "threshold_delta":round(float(target-baseline),4),
        "recommendation_status":status,
        "reasons":reasons,
        "automatic_production_change":False
    }

def evaluate_calibration(con,baseline=BASELINE_TEXT_THRESHOLD,persist=True):
    metrics=calibration_metrics(con)
    rec=shadow_threshold_recommendation(metrics,baseline)
    result={"policy_version":POLICY_VERSION,**metrics,**rec}
    if persist:
        cur=con.execute("""INSERT INTO origin_inference_calibrations(
          policy_version,reviewed_cluster_count,confirmed_syndication_count,
          confirmed_independent_count,hold_count,precision,false_positive_rate,
          baseline_text_threshold,shadow_recommended_text_threshold,threshold_delta,
          recommendation_status,reasons_json,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (POLICY_VERSION,metrics["reviewed_cluster_count"],
           metrics["confirmed_syndication_count"],
           metrics["confirmed_independent_count"],metrics["hold_count"],
           metrics["precision"],metrics["false_positive_rate"],
           rec["baseline_text_threshold"],rec["shadow_recommended_text_threshold"],
           rec["threshold_delta"],rec["recommendation_status"],
           json.dumps(rec["reasons"],ensure_ascii=False),_now()))
        cid=cur.lastrowid
        con.execute("""INSERT INTO origin_calibration_events(
          calibration_id,event_type,actor,detail_json,created_at)
          VALUES(?,?,?,?,?)""",
          (cid,"SHADOW_THRESHOLD_EVALUATED","origin-calibration",
           json.dumps({
               "recommendation_status":rec["recommendation_status"],
               "automatic_production_change":False,
               "decisive_review_count":metrics["decisive_review_count"]
           },ensure_ascii=False),_now()))
        con.commit()
        result["calibration_id"]=cid
    return result

def calibration_history(con):
    rows=con.execute("""SELECT * FROM origin_inference_calibrations
                       ORDER BY calibration_id""").fetchall()
    out=[]
    for r in rows:
        x=dict(r); x["reasons"]=_decode_json(x.pop("reasons_json"))
        out.append(x)
    return out

def _cluster_priority(con,row):
    cid=row["cluster_id"]
    members=con.execute("""SELECT * FROM cross_post_cluster_members
                           WHERE cluster_id=? ORDER BY member_id""",(cid,)).fetchall()
    max_sim=max([float(m["text_similarity"] or 0) for m in members] or [0.0])
    poster_count=sum(bool(m["same_poster"]) for m in members)
    link_count=sum(bool(m["same_link_origin"]) for m in members)

    ev=con.execute("""SELECT status,event_date FROM event_instances
                      WHERE event_instance_id=?""",(row["event_instance_id"],)).fetchone()
    event_status=ev["status"] if ev else None
    event_date=ev["event_date"] if ev else None

    # Count alternative-route decisions whose source-independence outcome could
    # be affected by this event's cluster.
    route_impact=con.execute("""SELECT COUNT(*) n FROM alternative_route_evaluations
      WHERE event_instance_id=? AND route_status IN ('ROUTED_VERIFIED','ROUTED_POSSIBLE')""",
      (row["event_instance_id"],)).fetchone()["n"]

    score=0.0; reasons=[]
    # High similarity means a stronger machine assertion; wrong blocking here
    # is more consequential and should be reviewed sooner.
    score += max_sim*35.0
    if max_sim>=0.95: reasons.append("very high near-duplicate similarity")
    elif max_sim>=0.86: reasons.append("near-duplicate threshold exceeded")

    score += min(int(row["member_count"]),5)*5.0
    if int(row["member_count"])>=3:
        reasons.append(f"{row['member_count']} sources are clustered")

    if poster_count:
        score += min(poster_count,3)*3.0
        reasons.append("shared poster signal present")
    if link_count:
        score += min(link_count,3)*4.0
        reasons.append("shared link-origin signal present")

    if event_status=="VERIFIED":
        score += 20.0
        reasons.append("cluster touches a VERIFIED event")
    elif event_status in {"POSSIBLE","EXPECTED","CONFLICT"}:
        score += 8.0

    if route_impact:
        score += min(route_impact,3)*8.0
        reasons.append(f"{route_impact} alternative-route decision(s) may depend on independence")

    # Upcoming event = higher operational urgency. Past/unknown dates get no boost.
    if event_date:
        try:
            days=(date.fromisoformat(event_date)-date.today()).days
            if 0<=days<=2:
                score+=20.0; reasons.append("event is within 2 days")
            elif 3<=days<=7:
                score+=10.0; reasons.append("event is within 7 days")
        except Exception:
            pass

    confidence=(row["confidence"] or "MEDIUM").upper()
    if confidence=="HIGH":
        score+=8.0
    elif confidence=="LOW":
        score-=5.0

    score=max(0.0,min(100.0,score))
    band="P1" if score>=70 else ("P2" if score>=45 else "P3")
    if not reasons:
        reasons.append("routine automated-origin review")
    return {
        "cluster_id":cid,
        "status":row["status"],
        "priority_score":round(score,2),
        "priority_band":band,
        "event_status":event_status,
        "member_count":int(row["member_count"]),
        "max_text_similarity":round(max_sim,4),
        "same_poster_count":poster_count,
        "same_link_origin_count":link_count,
        "route_impact_count":int(route_impact),
        "likely_origin_source_id":row["likely_origin_source_id"],
        "reasons":reasons
    }

def build_review_queue(con,persist=True):
    rows=con.execute("""SELECT * FROM cross_post_clusters
      WHERE status='AUTO_SUSPECTED_SYNDICATION'
      ORDER BY cluster_id""").fetchall()
    items=[_cluster_priority(con,r) for r in rows]
    items.sort(key=lambda x:(-x["priority_score"],x["cluster_id"]))
    if persist:
        now=_now()
        for x in items:
            con.execute("""INSERT INTO origin_review_priorities(
              cluster_id,status,priority_score,priority_band,event_status,
              member_count,max_text_similarity,same_poster_count,
              same_link_origin_count,route_impact_count,likely_origin_source_id,
              reasons_json,calculated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (x["cluster_id"],x["status"],x["priority_score"],x["priority_band"],
               x["event_status"],x["member_count"],x["max_text_similarity"],
               x["same_poster_count"],x["same_link_origin_count"],
               x["route_impact_count"],x["likely_origin_source_id"],
               json.dumps(x["reasons"],ensure_ascii=False),now))
        con.commit()
    return {
        "policy_version":POLICY_VERSION,
        "pending_cluster_count":len(items),
        "p1_count":sum(x["priority_band"]=="P1" for x in items),
        "p2_count":sum(x["priority_band"]=="P2" for x in items),
        "p3_count":sum(x["priority_band"]=="P3" for x in items),
        "items":items
    }

def priority_history(con,cluster_id=None):
    if cluster_id is None:
        rows=con.execute("""SELECT * FROM origin_review_priorities
                            ORDER BY priority_id""").fetchall()
    else:
        rows=con.execute("""SELECT * FROM origin_review_priorities
          WHERE cluster_id=? ORDER BY priority_id""",(cluster_id,)).fetchall()
    out=[]
    for r in rows:
        x=dict(r); x["reasons"]=_decode_json(x.pop("reasons_json"))
        out.append(x)
    return out

def daily_origin_quality(con):
    cal=evaluate_calibration(con,persist=True)
    queue=build_review_queue(con,persist=True)
    return {
        "policy_version":POLICY_VERSION,
        "calibration":cal,
        "review_queue":{
            "pending_cluster_count":queue["pending_cluster_count"],
            "p1_count":queue["p1_count"],
            "p2_count":queue["p2_count"],
            "p3_count":queue["p3_count"]
        }
    }
