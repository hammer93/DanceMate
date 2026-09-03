from pathlib import Path
from src.validation_admin import add_ground_truth,update_ground_truth_status,reconcile,generate_daily_report,GT_FIELDS,DM_FIELDS
import csv

def test_gt_add_and_status(tmp_path):
    p=tmp_path/"gt.csv"
    r=add_ground_truth(p,event_date="2026-08-27",event_name="A 밀롱가",venue="PISTA",
        start_time="20:00",end_time="24:00",fee="13000",actual_status="HELD")
    assert r["gt_id"]=="GT-20260827-01"
    r2=update_ground_truth_status(p,r["gt_id"],"CANCELLED","취소공지")
    assert r2["actual_status"]=="CANCELLED"
    assert "취소공지" in r2["notes"]

def test_reconcile_unmatched(tmp_path):
    gt=tmp_path/"gt.csv"; dm=tmp_path/"dm.csv"
    with gt.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=GT_FIELDS);w.writeheader()
        w.writerow({"gt_id":"GT-1","event_date":"2026-08-27","event_name":"A","venue":"V",
                    "start_time":"20:00","end_time":"","fee":"10000","actual_status":"HELD","evidence_url":"","notes":""})
    with dm.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=DM_FIELDS);w.writeheader()
        w.writerow({"gt_id":"","event_date":"2026-08-27","dm_event_id":"DM-1","dm_status":"VERIFIED",
                    "dm_date":"2026-08-27","dm_start_time":"20:00","dm_fee":"10000","dm_venue":"V",
                    "human_touch":"0","hallucinated_core_field":"0","critical_cancellation_miss":"0","notes":""})
    r=reconcile(gt,dm,date_filter="2026-08-27")
    assert len(r["unmatched_ground_truth"])==1
    assert len(r["unmatched_dancemate"])==1
