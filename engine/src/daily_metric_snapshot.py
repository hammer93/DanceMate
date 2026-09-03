import json,hashlib
from .database import persist_daily_metric_snapshot,daily_metric_snapshot
from .daily_operations_summary import build_daily_operations_summary

def canonical_payload_hash(payload):
    raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def capture_daily_metric_snapshot(con,*,daily_run_id,run_date):
    existing=daily_metric_snapshot(con,daily_run_id)
    if existing:
        return {"snapshot_id":existing["snapshot_id"],"daily_run_id":daily_run_id,
                "run_date":existing["run_date"],"immutable_hash":existing["immutable_hash"],
                "already_exists":True}
    payload=build_daily_operations_summary(con)
    h=canonical_payload_hash(payload)
    persist_daily_metric_snapshot(con,daily_run_id=daily_run_id,run_date=run_date,payload=payload,immutable_hash=h)
    row=daily_metric_snapshot(con,daily_run_id)
    return {"snapshot_id":row["snapshot_id"],"daily_run_id":daily_run_id,
            "run_date":run_date,"immutable_hash":h,"already_exists":False,"payload":payload}

def load_snapshot_payload(con,daily_run_id):
    row=daily_metric_snapshot(con,daily_run_id)
    if not row: return None
    return {"snapshot_id":row["snapshot_id"],"daily_run_id":row["daily_run_id"],
            "run_date":row["run_date"],"captured_at":row["captured_at"],
            "immutable_hash":row["immutable_hash"],"payload":json.loads(row["payload_json"])}

def verify_snapshot_integrity(con,daily_run_id):
    row=daily_metric_snapshot(con,daily_run_id)
    if not row: return {"exists":False,"valid":False}
    payload=json.loads(row["payload_json"])
    actual=canonical_payload_hash(payload)
    return {"exists":True,"valid":actual==row["immutable_hash"],
            "expected_hash":row["immutable_hash"],"actual_hash":actual}
