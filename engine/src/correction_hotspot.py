import json
from collections import defaultdict

def _ratio(n,d):
    return round(n/d,4) if d else None

def _parse(v):
    if not v:
        return None
    try:
        return json.loads(v)
    except Exception:
        return None

def analyze_correction_hotspots(con):
    actions=con.execute("""SELECT * FROM human_review_actions
                           WHERE review_type='FIELD'
                           ORDER BY action_id""").fetchall()
    event_sources=defaultdict(list)
    for r in con.execute("""SELECT DISTINCT event_instance_id,source_id
                            FROM event_instance_candidates
                            ORDER BY event_instance_id,source_id""").fetchall():
        event_sources[r["event_instance_id"]].append(r["source_id"])

    def bucket():
        return {"reviews":0,"modifications":0,"rejections":0,"holds":0,"approvals":0}

    by_field=defaultdict(bucket)
    by_source=defaultdict(bucket)
    by_source_field=defaultdict(bucket)
    disagreements=[]

    for a in actions:
        field=a["field_name"] or "UNKNOWN"
        eid=a["event_instance_id"]
        action=a["action"]
        sources=event_sources.get(eid) or ["UNATTRIBUTED"]

        def bump(b):
            b["reviews"]+=1
            if action=="MODIFY": b["modifications"]+=1
            elif action=="REJECT": b["rejections"]+=1
            elif action=="HOLD": b["holds"]+=1
            elif action=="APPROVE": b["approvals"]+=1

        bump(by_field[field])
        for sid in sources:
            bump(by_source[sid])
            bump(by_source_field[(sid,field)])

        old=_parse(a["old_value_json"])
        new=_parse(a["new_value_json"])
        if action in ("MODIFY","REJECT") and old!=new:
            disagreements.append({
                "action_id":a["action_id"],"event_instance_id":eid,"field":field,
                "sources":sources,"action":action,"old":old,"new":new,
                "reason":a["reason"],"actor":a["actor"]
            })

    def finalize(d):
        rows=[]
        for key,v in d.items():
            x=dict(v)
            x["correction_rate"]=_ratio(v["modifications"]+v["rejections"],v["reviews"])
            x["modify_rate"]=_ratio(v["modifications"],v["reviews"])
            x["reject_rate"]=_ratio(v["rejections"],v["reviews"])
            x["hold_rate"]=_ratio(v["holds"],v["reviews"])
            x["approval_rate"]=_ratio(v["approvals"],v["reviews"])
            x["_key"]=key
            rows.append(x)
        return rows

    fields=[]
    for x in finalize(by_field):
        x["field"]=x.pop("_key"); fields.append(x)

    sources=[]
    for x in finalize(by_source):
        sid=x.pop("_key")
        s=con.execute("""SELECT name,platform,authority_level,access_state
                         FROM sources WHERE source_id=?""",(sid,)).fetchone()
        x.update({
            "source_id":sid,
            "source_name":s["name"] if s else None,
            "platform":s["platform"] if s else None,
            "authority_level":s["authority_level"] if s else None,
            "access_state":s["access_state"] if s else None,
        })
        sources.append(x)

    source_fields=[]
    for x in finalize(by_source_field):
        sid,field=x.pop("_key")
        s=con.execute("SELECT name,platform FROM sources WHERE source_id=?",(sid,)).fetchone()
        x.update({"source_id":sid,"source_name":s["name"] if s else None,
                  "platform":s["platform"] if s else None,"field":field})
        source_fields.append(x)

    def rank(x):
        return (x["modifications"]+x["rejections"],x["reviews"],x["holds"])

    fields.sort(key=rank,reverse=True)
    sources.sort(key=rank,reverse=True)
    source_fields.sort(key=rank,reverse=True)

    top=[]
    for x in source_fields[:10]:
        score=(x["modifications"]+x["rejections"])*3+x["holds"]*2+x["reviews"]
        top.append({**x,"hotspot_score":score,
                    "priority":"P1" if score>=6 else ("P2" if score>=3 else "P3")})

    return {
        "field_hotspots":fields,
        "source_hotspots":sources,
        "source_field_hotspots":source_fields,
        "top_hotspots":top,
        "disagreement_examples":disagreements,
        "interpretation":{
            "correction_rate":"(MODIFY+REJECT)/all field reviews",
            "hotspot_score":"3*(MODIFY+REJECT) + 2*HOLD + all reviews",
            "priority":"P1>=6, P2>=3, else P3"
        }
    }
