import csv
import json
from dataclasses import dataclass
from pathlib import Path
from collections import defaultdict

P0_ERRORS = {
    "FALSE_VERIFIED",
    "HALLUCINATED_CORE_FIELD",
    "CRITICAL_CANCELLATION_MISS",
}

def _bool(v):
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"1","true","yes","y"}

def _norm(v):
    if v is None:
        return None
    s=str(v).strip()
    return s if s else None

def _ratio(n,d):
    return round(n/d,4) if d else None

def load_csv(path):
    with open(path,encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))

def compare_day(gt_rows, dm_rows, day):
    gt=[r for r in gt_rows if r["event_date"]==day]
    dm=[r for r in dm_rows if r["event_date"]==day]

    gt_by={r["gt_id"]:r for r in gt}
    dm_by_gt=defaultdict(list)
    for r in dm:
        if r.get("gt_id"):
            dm_by_gt[r["gt_id"]].append(r)

    detected=0
    verified_total=0
    correct_verified=0
    false_verified=0
    date_ok=time_ok=fee_ok=venue_ok=0
    verified_compared=0
    human_touch=0
    hallucinated=0
    cancellation_miss=0
    errors=[]

    for gtid,g in gt_by.items():
        matches=dm_by_gt.get(gtid,[])
        if matches:
            detected += 1
        # Duplicate rows for same GT are allowed in raw comparison but flagged.
        if len(matches)>1:
            errors.append({"code":"DUPLICATE_EVENT","gt_id":gtid,"count":len(matches)})

        for r in matches:
            human_touch += int(_bool(r.get("human_touch")))
            if _bool(r.get("hallucinated_core_field")):
                hallucinated += 1
                errors.append({"code":"HALLUCINATED_CORE_FIELD","gt_id":gtid})
            if _bool(r.get("critical_cancellation_miss")):
                cancellation_miss += 1
                errors.append({"code":"CRITICAL_CANCELLATION_MISS","gt_id":gtid})

            if r.get("dm_status")=="VERIFIED":
                verified_total += 1
                gt_active = g.get("actual_status")=="HELD"
                core_match = (
                    _norm(r.get("dm_date")) == _norm(g.get("event_date")) and
                    _norm(r.get("dm_start_time")) == _norm(g.get("start_time")) and
                    _norm(r.get("dm_fee")) == _norm(g.get("fee")) and
                    _norm(r.get("dm_venue")) == _norm(g.get("venue"))
                )
                if gt_active and core_match:
                    correct_verified += 1
                else:
                    false_verified += 1
                    errors.append({"code":"FALSE_VERIFIED","gt_id":gtid})

                verified_compared += 1
                date_ok += int(_norm(r.get("dm_date")) == _norm(g.get("event_date")))
                time_ok += int(_norm(r.get("dm_start_time")) == _norm(g.get("start_time")))
                fee_ok += int(_norm(r.get("dm_fee")) == _norm(g.get("fee")))
                venue_ok += int(_norm(r.get("dm_venue")) == _norm(g.get("venue")))

        # Ground truth cancellation that DM does not mark cancelled => critical miss.
        if g.get("actual_status")=="CANCELLED":
            if not any(r.get("dm_status")=="CANCELLED" for r in matches):
                cancellation_miss += 1
                errors.append({"code":"CRITICAL_CANCELLATION_MISS","gt_id":gtid})

    return {
        "date":day,
        "ground_truth_events":len(gt),
        "detected_events":detected,
        "event_recall":_ratio(detected,len(gt)),
        "verified_events":verified_total,
        "correct_verified":correct_verified,
        "false_verified":false_verified,
        "verified_precision":_ratio(correct_verified,verified_total),
        "date_accuracy":_ratio(date_ok,verified_compared),
        "time_accuracy":_ratio(time_ok,verified_compared),
        "fee_accuracy":_ratio(fee_ok,verified_compared),
        "venue_accuracy":_ratio(venue_ok,verified_compared),
        "human_touch_count":human_touch,
        "human_touch_rate":_ratio(human_touch,max(len(dm),1)),
        "hallucinated_core_fields":hallucinated,
        "critical_cancellation_miss":cancellation_miss,
        "errors":errors,
    }

def aggregate(days):
    def s(k): return sum((d.get(k) or 0) for d in days)
    gt=s("ground_truth_events")
    detected=s("detected_events")
    verified=s("verified_events")
    correct=s("correct_verified")
    compared=verified
    # Weighted field accuracy from daily counts is reconstructed conservatively from ratios.
    def weighted_ratio(metric):
        num=0
        den=0
        for d in days:
            r=d.get(metric)
            if r is not None and d.get("verified_events",0):
                num += r*d["verified_events"]
                den += d["verified_events"]
        return round(num/den,4) if den else None
    human=s("human_touch_count")
    dm_total=sum(max(d["detected_events"],0) for d in days)
    return {
        "days":len(days),
        "ground_truth_events":gt,
        "detected_events":detected,
        "event_recall":_ratio(detected,gt),
        "verified_events":verified,
        "correct_verified":correct,
        "false_verified":s("false_verified"),
        "verified_precision":_ratio(correct,verified),
        "date_accuracy":weighted_ratio("date_accuracy"),
        "time_accuracy":weighted_ratio("time_accuracy"),
        "fee_accuracy":weighted_ratio("fee_accuracy"),
        "venue_accuracy":weighted_ratio("venue_accuracy"),
        "human_touch_count":human,
        "human_touch_rate":_ratio(human,max(dm_total,1)),
        "hallucinated_core_fields":s("hallucinated_core_fields"),
        "critical_cancellation_miss":s("critical_cancellation_miss"),
    }

def gate_result(agg):
    p0_fail = (
        agg["false_verified"] > 0 or
        agg["hallucinated_core_fields"] > 0 or
        agg["critical_cancellation_miss"] > 0
    )
    if p0_fail:
        return "FAIL"

    core_accs=[agg["date_accuracy"],agg["time_accuracy"],agg["fee_accuracy"],agg["venue_accuracy"]]
    core_min=min([x for x in core_accs if x is not None], default=1.0)
    pass_perf = (
        (agg["event_recall"] or 0) >= 0.85 and
        (agg["verified_precision"] or 0) >= 0.99 and
        core_min >= 0.98 and
        (agg["human_touch_rate"] or 0) <= 0.20
    )
    if pass_perf:
        return "PASS"

    # Conditional pass is allowed only when P0 is clean and the miss is moderate.
    recall=agg["event_recall"] or 0
    precision=agg["verified_precision"] or 0
    human=agg["human_touch_rate"] or 0
    if recall >= 0.80 and precision >= 0.99 and core_min >= 0.98 and human <= 0.25:
        return "CONDITIONAL_PASS"
    return "FAIL"

def run_validation(gt_path, dm_path):
    gt=load_csv(gt_path)
    dm=load_csv(dm_path)
    days=sorted({r["event_date"] for r in gt})
    daily=[compare_day(gt,dm,d) for d in days]
    agg=aggregate(daily)
    return {"daily":daily,"aggregate":agg,"gate":gate_result(agg)}
