import json
import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

from .database import (
    upsert_source_relationship,source_relationship_row,source_relationship_rows,
    upsert_evidence_origin_fingerprint,evidence_origin_fingerprint_row,
    evidence_origin_fingerprint_rows,persist_source_independence_evaluation,
    source_independence_evaluation_rows
)

POLICY_VERSION="v0.49"
RELATIONSHIP_TYPES={"INDEPENDENT","RELATED","SYNDICATED","UNKNOWN"}
CONFIDENCES={"LOW","MEDIUM","HIGH"}

def _decode(rows):
    out=[]
    for r in rows:
        x=dict(r)
        for f in ("relationship_evidence_json","syndication_signals_json","reasons_json"):
            if f in x and x.get(f):
                try: x[f]=json.loads(x[f])
                except Exception: pass
        out.append(x)
    return out

def normalize_text(text):
    text=(text or "").lower()
    text=re.sub(r"https?://\S+"," ",text)
    text=re.sub(r"[^0-9a-z가-힣]+"," ",text)
    return " ".join(text.split())

def content_fingerprint(text):
    n=normalize_text(text)
    if not n: return None
    return hashlib.sha256(n.encode("utf-8")).hexdigest()

def canonicalize_url(url):
    if not url: return None
    try:
        s=urlsplit(url.strip())
        path=re.sub(r"/+$","",s.path or "")
        return urlunsplit((s.scheme.lower(),s.netloc.lower(),path,"",""))
    except Exception:
        return url.strip()

def register_relationship(
    con, *, source_id_a,source_id_b,relationship_type,confidence="HIGH",
    provenance="HUMAN_REVIEW",reviewed_by=None,reason=None):
    relationship_type=relationship_type.upper()
    confidence=confidence.upper()
    if relationship_type not in RELATIONSHIP_TYPES:
        raise ValueError("relationship_type must be INDEPENDENT, RELATED, SYNDICATED, or UNKNOWN")
    if confidence not in CONFIDENCES:
        raise ValueError("confidence must be LOW, MEDIUM, or HIGH")
    rid=upsert_source_relationship(
        con,source_id_a=source_id_a,source_id_b=source_id_b,
        relationship_type=relationship_type,confidence=confidence,
        provenance=provenance,reviewed_by=reviewed_by,reason=reason)
    return {"relationship_id":rid,"source_id_a":source_id_a,"source_id_b":source_id_b,
            "relationship_type":relationship_type,"confidence":confidence,
            "provenance":provenance}

def register_fingerprint(
    con, *, event_instance_id,source_id,content=None,content_hash=None,
    poster_hash=None,canonical_url=None,origin_source_id=None,
    fingerprint_method="DERIVED"):
    ch=content_hash or content_fingerprint(content)
    cu=canonicalize_url(canonical_url)
    fid=upsert_evidence_origin_fingerprint(
        con,event_instance_id=event_instance_id,source_id=source_id,
        content_hash=ch,poster_hash=poster_hash,canonical_url=cu,
        origin_source_id=origin_source_id,fingerprint_method=fingerprint_method)
    return {"fingerprint_id":fid,"event_instance_id":event_instance_id,
            "source_id":source_id,"content_hash":ch,"poster_hash":poster_hash,
            "canonical_url":cu,"origin_source_id":origin_source_id}

def derive_fingerprint_from_runtime(con,event_instance_id,source_id):
    # Use the newest linked raw post for this event/source. Exact normalized text,
    # poster URL, canonical URL, and explicit origin are conservative signals.
    row=con.execute("""SELECT rp.*
      FROM event_instance_candidates eic
      JOIN event_candidates ec ON ec.candidate_id=eic.candidate_id
      JOIN raw_posts rp ON rp.post_id=ec.post_id
      WHERE eic.event_instance_id=? AND eic.source_id=?
      ORDER BY rp.post_id DESC LIMIT 1""",(event_instance_id,source_id)).fetchone()
    if not row:
        return None

    poster=con.execute("""SELECT am.media_url
      FROM event_instance_candidates eic
      JOIN event_candidates ec ON ec.candidate_id=eic.candidate_id
      JOIN acquired_media am ON am.post_id=ec.post_id
      WHERE eic.event_instance_id=? AND eic.source_id=?
        AND am.poster_candidate=1
      ORDER BY am.media_id DESC LIMIT 1""",(event_instance_id,source_id)).fetchone()

    text=" ".join(x for x in (row["title"],row["body"]) if x)
    poster_hash=None
    if poster and poster["media_url"]:
        poster_hash=hashlib.sha256(
            canonicalize_url(poster["media_url"]).encode("utf-8")).hexdigest()

    return register_fingerprint(
        con,event_instance_id=event_instance_id,source_id=source_id,
        content=text,poster_hash=poster_hash,canonical_url=row["source_url"],
        fingerprint_method="RUNTIME_DERIVED")

def _fingerprint(con,event_instance_id,source_id):
    row=evidence_origin_fingerprint_row(con,event_instance_id,source_id)
    if row: return dict(row)
    derive_fingerprint_from_runtime(con,event_instance_id,source_id)
    row=evidence_origin_fingerprint_row(con,event_instance_id,source_id)
    return dict(row) if row else None

def evaluate_pair(con, *, event_instance_id,source_id_a,source_id_b,persist=True):
    if source_id_a==source_id_b:
        return {
            "event_instance_id":event_instance_id,
            "source_id_a":source_id_a,"source_id_b":source_id_b,
            "relationship_type":"RELATED","independence_status":"NOT_INDEPENDENT",
            "syndication_signals":["SAME_SOURCE"],"reasons":["same source cannot corroborate itself"]
        }

    explicit=source_relationship_row(con,source_id_a,source_id_b)
    from .automated_origin_inference import active_pair_signal
    auto_cluster=active_pair_signal(con,event_instance_id,source_id_a,source_id_b)
    fa=_fingerprint(con,event_instance_id,source_id_a)
    fb=_fingerprint(con,event_instance_id,source_id_b)

    signals=[]
    if fa and fb:
        if fa.get("origin_source_id") and fb.get("origin_source_id") and \
           fa["origin_source_id"]==fb["origin_source_id"]:
            signals.append("SAME_EXPLICIT_ORIGIN")
        if fa.get("origin_source_id")==source_id_b or fb.get("origin_source_id")==source_id_a:
            signals.append("DIRECT_ORIGIN_LINK")
        if fa.get("content_hash") and fa["content_hash"]==fb.get("content_hash"):
            signals.append("EXACT_CONTENT_FINGERPRINT")
        if fa.get("poster_hash") and fa["poster_hash"]==fb.get("poster_hash"):
            signals.append("EXACT_POSTER_FINGERPRINT")
        if fa.get("canonical_url") and fa["canonical_url"]==fb.get("canonical_url"):
            signals.append("SAME_CANONICAL_URL")

    reasons=[]
    relationship_type="UNKNOWN"
    status="UNKNOWN"

    # Hard syndication evidence always wins over platform difference.
    hard_syndication=bool(set(signals) & {
        "SAME_EXPLICIT_ORIGIN","DIRECT_ORIGIN_LINK",
        "EXACT_CONTENT_FINGERPRINT","SAME_CANONICAL_URL"
    })
    if auto_cluster and auto_cluster["status"]=="CONFIRMED_SYNDICATION":
        relationship_type="SYNDICATED"
        status="NOT_INDEPENDENT"
        signals.append("HUMAN_CONFIRMED_CROSS_POST_CLUSTER")
        reasons.append("human-confirmed cross-post cluster indicates syndication")
    elif auto_cluster and auto_cluster["status"]=="AUTO_SUSPECTED_SYNDICATION":
        relationship_type="RELATED"
        status="NOT_INDEPENDENT"
        signals.append("AUTO_SUSPECTED_CROSS_POST")
        reasons.append("automatic cross-post inference is shadow-safe: blocks double-counting but never asserts VERIFIED independence")
    elif auto_cluster and auto_cluster["status"]=="CONFIRMED_INDEPENDENT":
        relationship_type="INDEPENDENT"
        status="INDEPENDENT"
        reasons.append("human review confirmed cluster members are independently originated")
    elif hard_syndication:
        relationship_type="SYNDICATED"
        status="NOT_INDEPENDENT"
        reasons.append("shared origin/content lineage indicates syndication")
    elif explicit:
        relationship_type=explicit["relationship_type"]
        if relationship_type=="INDEPENDENT":
            status="INDEPENDENT"
        elif relationship_type in {"RELATED","SYNDICATED"}:
            status="NOT_INDEPENDENT"
        else:
            status="UNKNOWN"
        reasons.append(
            f"explicit relationship {relationship_type} ({explicit['confidence']})")
    elif "EXACT_POSTER_FINGERPRINT" in signals:
        # Same poster alone is meaningful but not enough to assert syndication:
        # independent venue/organizer accounts can legitimately reuse official art.
        relationship_type="RELATED"
        status="NOT_INDEPENDENT"
        reasons.append("same poster is treated conservatively as related evidence")
    else:
        # Platform difference is no longer sufficient to prove independence.
        status="UNKNOWN"
        relationship_type="UNKNOWN"
        reasons.append("no explicit independence or origin-lineage proof")

    result={
        "policy_version":POLICY_VERSION,
        "event_instance_id":event_instance_id,
        "source_id_a":source_id_a,"source_id_b":source_id_b,
        "relationship_type":relationship_type,
        "independence_status":status,
        "relationship_evidence":dict(explicit) if explicit else None,
        "syndication_signals":signals,"reasons":reasons
    }
    if persist:
        eid=persist_source_independence_evaluation(
            con,event_instance_id=event_instance_id,source_id_a=source_id_a,
            source_id_b=source_id_b,relationship_type=relationship_type,
            independence_status=status,
            relationship_evidence=result["relationship_evidence"],
            syndication_signals=signals,reasons=reasons)
        result["independence_evaluation_id"]=eid
    return result

def independent_groups(con, *, event_instance_id,source_ids):
    # Build conservative groups: only pairs explicitly/evidentially INDEPENDENT
    # can form corroboration. Unknown never counts as independent.
    source_ids=list(dict.fromkeys(source_ids))
    pair_results=[]
    independent_pairs=set()
    for i,a in enumerate(source_ids):
        for b in source_ids[i+1:]:
            r=evaluate_pair(
                con,event_instance_id=event_instance_id,
                source_id_a=a,source_id_b=b,persist=True)
            pair_results.append(r)
            if r["independence_status"]=="INDEPENDENT":
                independent_pairs.add(tuple(sorted((a,b))))

    # For VERIFIED corroboration we need a clique of size >=2. For current PoC,
    # greedily choose mutually-independent sources. This avoids transitive
    # assumptions (A independent B, B independent C does not imply A independent C).
    best=[]
    for s in source_ids:
        trial=[]
        for x in [s]+[y for y in source_ids if y!=s]:
            if all(tuple(sorted((x,z))) in independent_pairs for z in trial):
                trial.append(x)
        if len(trial)>len(best): best=trial

    # A single source is not corroboration. Report zero proven-independent
    # corroborators unless at least one explicit/evidential independent pair exists.
    if len(best)<2:
        best=[]
    return {
        "source_ids":source_ids,
        "independent_source_ids":best,
        "independent_count":len(best),
        "pair_evaluations":pair_results
    }

def relationships(con):
    return [dict(r) for r in source_relationship_rows(con)]

def fingerprints(con,event_instance_id=None):
    return [dict(r) for r in evidence_origin_fingerprint_rows(con,event_instance_id)]

def independence_history(con,event_instance_id=None):
    return _decode(source_independence_evaluation_rows(con,event_instance_id))
