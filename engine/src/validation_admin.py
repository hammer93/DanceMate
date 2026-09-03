import csv
import json
from pathlib import Path
from datetime import datetime, timezone
from .gate1_validation import run_validation

GT_FIELDS = [
    "gt_id","event_date","event_name","venue","start_time","end_time","fee",
    "actual_status","evidence_url","notes"
]

DM_FIELDS = [
    "gt_id","event_date","dm_event_id","dm_status","dm_date","dm_start_time",
    "dm_fee","dm_venue","human_touch","hallucinated_core_field",
    "critical_cancellation_miss","notes"
]

def ensure_csv(path: Path, fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        with path.open("w",encoding="utf-8-sig",newline="") as f:
            w=csv.DictWriter(f,fieldnames=fields)
            w.writeheader()
    return path

def append_row(path: Path, fields, row):
    ensure_csv(path,fields)
    with path.open("a",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writerow({k:row.get(k,"") for k in fields})

def next_gt_id(gt_path: Path, event_date: str):
    ensure_csv(gt_path,GT_FIELDS)
    with gt_path.open("r",encoding="utf-8-sig",newline="") as f:
        rows=[r for r in csv.DictReader(f) if r.get("event_date")==event_date]
    return f"GT-{event_date.replace('-','')}-{len(rows)+1:02d}"

def add_ground_truth(gt_path: Path, *, event_date, event_name, venue, start_time, end_time,
                     fee, actual_status="HELD", evidence_url="", notes=""):
    gt_id=next_gt_id(gt_path,event_date)
    row={
        "gt_id":gt_id,"event_date":event_date,"event_name":event_name,"venue":venue,
        "start_time":start_time,"end_time":end_time,"fee":fee,
        "actual_status":actual_status,"evidence_url":evidence_url,"notes":notes
    }
    append_row(gt_path,GT_FIELDS,row)
    return row

def update_ground_truth_status(gt_path: Path, gt_id: str, actual_status: str, notes_append=""):
    ensure_csv(gt_path,GT_FIELDS)
    with gt_path.open("r",encoding="utf-8-sig",newline="") as f:
        rows=list(csv.DictReader(f))
    found=False
    for r in rows:
        if r["gt_id"]==gt_id:
            r["actual_status"]=actual_status
            if notes_append:
                existing=(r.get("notes") or "").strip()
                r["notes"]=(existing+" | "+notes_append).strip(" |")
            found=True
            break
    if not found:
        raise KeyError(f"Ground Truth not found: {gt_id}")
    with gt_path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=GT_FIELDS); w.writeheader(); w.writerows(rows)
    return next(r for r in rows if r["gt_id"]==gt_id)

def export_dancemate_results(con, out_path: Path, *, event_date=None):
    out_path.parent.mkdir(parents=True,exist_ok=True)
    sql="""SELECT
      ei.event_instance_id, ei.event_date, ei.status AS dm_status, ei.normalized_venue,
      ec.start_time, ec.fee, ec.name, rp.source_id
      FROM event_instances ei
      LEFT JOIN event_instance_candidates eic ON eic.event_instance_id=ei.event_instance_id
      LEFT JOIN event_candidates ec ON ec.candidate_id=eic.candidate_id
      LEFT JOIN raw_posts rp ON rp.post_id=ec.post_id
      WHERE 1=1"""
    args=[]
    if event_date:
        sql+=" AND ei.event_date=?"
        args.append(event_date)
    sql+=" ORDER BY ei.event_date,ei.event_instance_id,ec.candidate_id"
    rows=con.execute(sql,args).fetchall()

    # One output row per EventInstance, choosing a deterministic representative candidate.
    by={}
    for r in rows:
        eid=r["event_instance_id"]
        if eid not in by:
            by[eid]=r
    with out_path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=DM_FIELDS); w.writeheader()
        for eid,r in by.items():
            w.writerow({
                "gt_id":"",
                "event_date":r["event_date"] or "",
                "dm_event_id":f"DM-{eid:06d}",
                "dm_status":r["dm_status"] or "",
                "dm_date":r["event_date"] or "",
                "dm_start_time":r["start_time"] or "",
                "dm_fee":"" if r["fee"] is None else r["fee"],
                "dm_venue":r["normalized_venue"] or "",
                "human_touch":"0",
                "hallucinated_core_field":"0",
                "critical_cancellation_miss":"0",
                "notes":"exported_from_runtime_db"
            })
    return {"path":str(out_path),"event_instances":len(by)}

def load_rows(path):
    with open(path,encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))

def reconcile(gt_path: Path, dm_path: Path, *, date_filter=None):
    gt=load_rows(gt_path)
    dm=load_rows(dm_path)
    if date_filter:
        gt=[r for r in gt if r["event_date"]==date_filter]
        dm=[r for r in dm if r["event_date"]==date_filter]

    gt_ids={r["gt_id"] for r in gt}
    linked={r["gt_id"] for r in dm if r.get("gt_id")}
    unmatched_gt=[r for r in gt if r["gt_id"] not in linked]
    unmatched_dm=[r for r in dm if not r.get("gt_id") or r.get("gt_id") not in gt_ids]
    duplicate_links={}
    for r in dm:
        g=r.get("gt_id")
        if g:
            duplicate_links[g]=duplicate_links.get(g,0)+1
    duplicate_links={k:v for k,v in duplicate_links.items() if v>1}

    return {
        "ground_truth_count":len(gt),
        "dancemate_count":len(dm),
        "unmatched_ground_truth":unmatched_gt,
        "unmatched_dancemate":unmatched_dm,
        "duplicate_links":duplicate_links
    }

def generate_daily_report(gt_path: Path, dm_path: Path, report_dir: Path, event_date: str):
    result=run_validation(gt_path,dm_path)
    day=next((x for x in result["daily"] if x["date"]==event_date),None)
    if day is None:
        raise ValueError(f"No Ground Truth for date {event_date}")
    rec=reconcile(gt_path,dm_path,date_filter=event_date)
    payload={
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "date":event_date,
        "metrics":day,
        "reconcile":rec
    }
    report_dir.mkdir(parents=True,exist_ok=True)
    jp=report_dir/f"gate1-daily-{event_date}.json"
    mp=report_dir/f"gate1-daily-{event_date}.md"
    jp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    md=[
        f"# DanceMate Gate 1 Daily — {event_date}","",
        f"- Ground Truth: {day['ground_truth_events']}",
        f"- Detected: {day['detected_events']}",
        f"- Recall: {day['event_recall']}",
        f"- VERIFIED Precision: {day['verified_precision']}",
        f"- Human Touch Rate: {day['human_touch_rate']}",
        f"- False VERIFIED: {day['false_verified']}",
        f"- Critical Cancellation Miss: {day['critical_cancellation_miss']}",
        f"- Unmatched Ground Truth: {len(rec['unmatched_ground_truth'])}",
        f"- Unmatched DanceMate: {len(rec['unmatched_dancemate'])}",
        f"- Duplicate Links: {len(rec['duplicate_links'])}",
    ]
    mp.write_text("\n".join(md),encoding="utf-8")
    return {"json":str(jp),"markdown":str(mp),"payload":payload}

def generate_rolling_report(gt_path: Path, dm_path: Path, report_dir: Path, label="rolling"):
    result=run_validation(gt_path,dm_path)
    report_dir.mkdir(parents=True,exist_ok=True)
    jp=report_dir/f"gate1-{label}-report-v0.9.json"
    mp=report_dir/f"gate1-{label}-report-v0.9.md"
    jp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    a=result["aggregate"]
    md=[
        f"# DanceMate Gate 1 — {label}","",
        f"- Gate: **{result['gate']}**",
        f"- Days: {a['days']}",
        f"- Ground Truth Events: {a['ground_truth_events']}",
        f"- Detected Events: {a['detected_events']}",
        f"- Event Recall: {a['event_recall']}",
        f"- VERIFIED Precision: {a['verified_precision']}",
        f"- Core Accuracy: Date {a['date_accuracy']} / Time {a['time_accuracy']} / Fee {a['fee_accuracy']} / Venue {a['venue_accuracy']}",
        f"- Human Touch Rate: {a['human_touch_rate']}",
        f"- False VERIFIED: {a['false_verified']}",
        f"- Hallucinated Core Fields: {a['hallucinated_core_fields']}",
        f"- Critical Cancellation Miss: {a['critical_cancellation_miss']}",
    ]
    mp.write_text("\n".join(md),encoding="utf-8")
    return {"json":str(jp),"markdown":str(mp),"gate":result["gate"],"aggregate":a}
