import hashlib
import json
from datetime import datetime, timezone

POLICY_VERSION="v0.73"

def _now():
    return datetime.now(timezone.utc).isoformat()

def _fingerprint(root_cause_type,version_label,code_ref,config_ref):
    raw="|".join([
        root_cause_type or "",
        version_label or "",
        code_ref or "",
        config_ref or "",
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def versions(con,root_cause_type=None):
    sql="""SELECT * FROM origin_threshold_recommendation_algorithm_versions"""
    params=()
    if root_cause_type:
        sql+=" WHERE root_cause_type=?"; params=(root_cause_type,)
    sql+=" ORDER BY algorithm_version_id"
    return [dict(r) for r in con.execute(sql,params).fetchall()]

def version(con,algorithm_version_id):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_algorithm_versions
                     WHERE algorithm_version_id=?""",(algorithm_version_id,)).fetchone()
    if not r:
        raise ValueError("algorithm version not found")
    return dict(r)

def register_version(con,root_cause_type,version_label,created_by,notes="",
                     parent_algorithm_version_id=None,code_ref=None,config_ref=None,
                     fingerprint=None,status="SHADOW"):
    if status not in ("DRAFT","SHADOW","CANARY","PROMOTED","FAILED","SUPERSEDED"):
        raise ValueError("invalid algorithm version status")
    if not root_cause_type or not version_label or not created_by:
        raise ValueError("root_cause_type, version_label, created_by required")
    fp=fingerprint or _fingerprint(root_cause_type,version_label,code_ref,config_ref)
    if parent_algorithm_version_id is not None:
        parent=version(con,parent_algorithm_version_id)
        if parent["root_cause_type"]!=root_cause_type:
            raise ValueError("parent algorithm version root cause mismatch")
    cur=con.execute("""INSERT INTO origin_threshold_recommendation_algorithm_versions(
      root_cause_type,version_label,parent_algorithm_version_id,fingerprint,
      code_ref,config_ref,status,created_by,notes,created_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (root_cause_type,version_label,parent_algorithm_version_id,fp,
       code_ref,config_ref,status,created_by,notes or "",_now()))
    con.commit()
    _event(con,cur.lastrowid,"VERSION_REGISTERED",created_by,
           {"version_label":version_label,"status":status,
            "parent_algorithm_version_id":parent_algorithm_version_id})
    return version(con,cur.lastrowid)

def ensure_legacy_version(con,root_cause_type):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_algorithm_versions
      WHERE root_cause_type=? ORDER BY algorithm_version_id DESC LIMIT 1""",
      (root_cause_type,)).fetchone()
    if r:
        return dict(r)
    return register_version(
        con,root_cause_type,"legacy-v0.63","system",
        notes="auto-bootstrap for pre-v0.64 recommendation policy",
        code_ref="legacy",config_ref="v0.63",status="SHADOW")

def current_version(con,root_cause_type):
    r=con.execute("""SELECT * FROM origin_threshold_recommendation_algorithm_versions
      WHERE root_cause_type=? AND status IN ('PROMOTED','CANARY','SHADOW')
      ORDER BY CASE status WHEN 'PROMOTED' THEN 1 WHEN 'CANARY' THEN 2 ELSE 3 END,
               algorithm_version_id DESC LIMIT 1""",(root_cause_type,)).fetchone()
    return dict(r) if r else ensure_legacy_version(con,root_cause_type)

def _event(con,algorithm_version_id,event_type,actor,detail):
    con.execute("""INSERT INTO origin_threshold_recommendation_algorithm_version_events(
      algorithm_version_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",
      (algorithm_version_id,event_type,actor,json.dumps(detail,ensure_ascii=False),_now()))
    con.commit()

def events(con,algorithm_version_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_algorithm_version_events"""
    params=()
    if algorithm_version_id:
        sql+=" WHERE algorithm_version_id=?"; params=(algorithm_version_id,)
    sql+=" ORDER BY algorithm_version_event_id"
    out=[]
    for r in con.execute(sql,params).fetchall():
        x=dict(r); x["detail"]=json.loads(x.pop("detail_json")); out.append(x)
    return out

def link_entity(con,algorithm_version_id,root_cause_type,entity_type,entity_id,relation_type):
    version(con,algorithm_version_id)
    existing=con.execute("""SELECT * FROM origin_threshold_recommendation_algorithm_lineage
      WHERE entity_type=? AND entity_id=? AND relation_type=?""",
      (entity_type,entity_id,relation_type)).fetchone()
    if existing:
        return dict(existing)
    cur=con.execute("""INSERT INTO origin_threshold_recommendation_algorithm_lineage(
      algorithm_version_id,root_cause_type,entity_type,entity_id,relation_type,created_at)
      VALUES(?,?,?,?,?,?)""",
      (algorithm_version_id,root_cause_type,entity_type,entity_id,relation_type,_now()))
    con.commit()
    return dict(con.execute("""SELECT * FROM origin_threshold_recommendation_algorithm_lineage
                              WHERE algorithm_lineage_id=?""",(cur.lastrowid,)).fetchone())

def lineage(con,algorithm_version_id=None,entity_type=None,entity_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_algorithm_lineage WHERE 1=1"""
    params=[]
    if algorithm_version_id is not None:
        sql+=" AND algorithm_version_id=?"; params.append(algorithm_version_id)
    if entity_type is not None:
        sql+=" AND entity_type=?"; params.append(entity_type)
    if entity_id is not None:
        sql+=" AND entity_id=?"; params.append(entity_id)
    sql+=" ORDER BY algorithm_lineage_id"
    return [dict(r) for r in con.execute(sql,tuple(params)).fetchall()]

def version_for_entity(con,entity_type,entity_id,relation_type=None):
    sql="""SELECT v.* FROM origin_threshold_recommendation_algorithm_lineage l
      JOIN origin_threshold_recommendation_algorithm_versions v
        ON v.algorithm_version_id=l.algorithm_version_id
      WHERE l.entity_type=? AND l.entity_id=?"""
    params=[entity_type,entity_id]
    if relation_type:
        sql+=" AND l.relation_type=?"; params.append(relation_type)
    sql+=" ORDER BY l.algorithm_lineage_id DESC LIMIT 1"
    r=con.execute(sql,tuple(params)).fetchone()
    return dict(r) if r else None

def mark_failed(con,algorithm_version_id,actor,reason):
    v=version(con,algorithm_version_id)
    con.execute("""UPDATE origin_threshold_recommendation_algorithm_versions
                   SET status='FAILED' WHERE algorithm_version_id=?""",
                (algorithm_version_id,))
    con.commit()
    _event(con,algorithm_version_id,"VERSION_FAILED",actor,{"reason":reason})
    return version(con,algorithm_version_id)

def mark_status(con,algorithm_version_id,status,actor,reason):
    if status not in ("DRAFT","SHADOW","CANARY","PROMOTED","FAILED","SUPERSEDED"):
        raise ValueError("invalid algorithm version status")
    con.execute("""UPDATE origin_threshold_recommendation_algorithm_versions
                   SET status=? WHERE algorithm_version_id=?""",
                (status,algorithm_version_id))
    con.commit()
    _event(con,algorithm_version_id,"STATUS_CHANGED",actor,
           {"status":status,"reason":reason})
    return version(con,algorithm_version_id)

def create_recovery_link(con,policy_recovery_case_id,failed_algorithm_version_id):
    existing=con.execute("""SELECT * FROM origin_threshold_recommendation_recovery_version_links
      WHERE policy_recovery_case_id=?""",(policy_recovery_case_id,)).fetchone()
    if existing:
        return dict(existing)
    cur=con.execute("""INSERT INTO origin_threshold_recommendation_recovery_version_links(
      policy_recovery_case_id,failed_algorithm_version_id,status,created_at)
      VALUES(?,?,?,?)""",
      (policy_recovery_case_id,failed_algorithm_version_id,"FAILED_VERSION_LOCKED",_now()))
    con.commit()
    return dict(con.execute("""SELECT * FROM origin_threshold_recommendation_recovery_version_links
                              WHERE recovery_version_link_id=?""",(cur.lastrowid,)).fetchone())

def recovery_links(con,policy_recovery_case_id=None):
    sql="""SELECT * FROM origin_threshold_recommendation_recovery_version_links"""
    params=()
    if policy_recovery_case_id is not None:
        sql+=" WHERE policy_recovery_case_id=?"; params=(policy_recovery_case_id,)
    sql+=" ORDER BY recovery_version_link_id"
    return [dict(r) for r in con.execute(sql,params).fetchall()]

def propose_successor(con,policy_recovery_case_id,version_label,created_by,
                      policy_recovery_remediation_id,notes="",code_ref=None,config_ref=None):
    link=con.execute("""SELECT * FROM origin_threshold_recommendation_recovery_version_links
      WHERE policy_recovery_case_id=?""",(policy_recovery_case_id,)).fetchone()
    if not link:
        raise ValueError("recovery failed-version lineage link not found")
    failed=version(con,link["failed_algorithm_version_id"])
    if failed["version_label"]==version_label:
        raise ValueError("failed algorithm version cannot be reused as successor")
    successor=register_version(
        con,failed["root_cause_type"],version_label,created_by,notes,
        parent_algorithm_version_id=failed["algorithm_version_id"],
        code_ref=code_ref,config_ref=config_ref,status="SHADOW")
    if successor["fingerprint"]==failed["fingerprint"]:
        raise ValueError("successor fingerprint must differ from failed version")
    con.execute("""UPDATE origin_threshold_recommendation_recovery_version_links
      SET successor_algorithm_version_id=?,policy_recovery_remediation_id=?,
          status='SUCCESSOR_PROPOSED'
      WHERE policy_recovery_case_id=?""",
      (successor["algorithm_version_id"],policy_recovery_remediation_id,
       policy_recovery_case_id))
    con.commit()
    link_entity(con,successor["algorithm_version_id"],failed["root_cause_type"],
                "RECOVERY_CASE",policy_recovery_case_id,"SUCCESSOR_FOR")
    link_entity(con,successor["algorithm_version_id"],failed["root_cause_type"],
                "RECOVERY_REMEDIATION",policy_recovery_remediation_id,"CREATED_BY")
    _event(con,successor["algorithm_version_id"],"RECOVERY_SUCCESSOR_PROPOSED",created_by,
           {"policy_recovery_case_id":policy_recovery_case_id,
            "failed_algorithm_version_id":failed["algorithm_version_id"],
            "policy_recovery_remediation_id":policy_recovery_remediation_id})
    return {"successor":successor,
            "link":recovery_links(con,policy_recovery_case_id)[0]}

def approve_successor(con,policy_recovery_case_id,reviewer,reason):
    link=con.execute("""SELECT * FROM origin_threshold_recommendation_recovery_version_links
      WHERE policy_recovery_case_id=?""",(policy_recovery_case_id,)).fetchone()
    if not link or not link["successor_algorithm_version_id"]:
        raise ValueError("successor algorithm version not proposed")
    rem=con.execute("""SELECT * FROM origin_threshold_recommendation_policy_recovery_remediations
      WHERE policy_recovery_remediation_id=?""",(link["policy_recovery_remediation_id"],)).fetchone()
    if not rem or rem["status"]!="EFFECTIVE":
        raise ValueError("successor requires EFFECTIVE recovery remediation")
    successor=version(con,link["successor_algorithm_version_id"])
    failed=version(con,link["failed_algorithm_version_id"])
    if successor["algorithm_version_id"]==failed["algorithm_version_id"]:
        raise ValueError("failed algorithm version cannot be approved as successor")
    if successor["fingerprint"]==failed["fingerprint"]:
        raise ValueError("successor fingerprint must differ from failed version")
    con.execute("""UPDATE origin_threshold_recommendation_recovery_version_links
      SET status='SUCCESSOR_APPROVED',approved_by=?,approved_at=?,reason=?
      WHERE policy_recovery_case_id=?""",
      (reviewer,_now(),reason,policy_recovery_case_id))
    con.commit()
    _event(con,successor["algorithm_version_id"],"RECOVERY_SUCCESSOR_APPROVED",reviewer,
           {"policy_recovery_case_id":policy_recovery_case_id,"reason":reason})
    return recovery_links(con,policy_recovery_case_id)[0]

def recovery_successor_ready(con,policy_recovery_case_id):
    link=con.execute("""SELECT * FROM origin_threshold_recommendation_recovery_version_links
      WHERE policy_recovery_case_id=?""",(policy_recovery_case_id,)).fetchone()
    if not link:
        return {"ready":False,"reason":"failed algorithm version lineage is missing"}
    if not link["successor_algorithm_version_id"]:
        return {"ready":False,"reason":"new successor algorithm version is required","link":dict(link)}
    if link["successor_algorithm_version_id"]==link["failed_algorithm_version_id"]:
        return {"ready":False,"reason":"failed algorithm version cannot be reused","link":dict(link)}
    if link["status"]!="SUCCESSOR_APPROVED":
        return {"ready":False,"reason":"successor algorithm version requires Human approval","link":dict(link)}
    succ=version(con,link["successor_algorithm_version_id"])
    failed=version(con,link["failed_algorithm_version_id"])
    if succ["fingerprint"]==failed["fingerprint"]:
        return {"ready":False,"reason":"successor fingerprint must differ from failed version","link":dict(link)}
    return {"ready":True,"reason":"new Human-approved successor algorithm version is ready",
            "link":dict(link),"successor":succ}

def status(con):
    return {
        "policy_version":POLICY_VERSION,
        "versions":versions(con),
        "lineage":lineage(con),
        "recovery_version_links":recovery_links(con),
        "events":events(con),
    }
