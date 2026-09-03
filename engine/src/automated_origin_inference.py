import json, re, hashlib
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import urlsplit

POLICY_VERSION='v0.62'

def _now(): return datetime.now(timezone.utc).isoformat()
def _norm(s):
    s=(s or '').lower(); s=re.sub(r'https?://\\S+',' ',s); s=re.sub(r'[^0-9a-z가-힣]+',' ',s)
    return ' '.join(s.split())
def _sim(a,b):
    a,b=_norm(a),_norm(b)
    return SequenceMatcher(None,a,b).ratio() if a and b else 0.0

def _posts(con,event_instance_id):
    rows=con.execute('''SELECT eic.source_id,rp.title,rp.body,rp.published_at,rp.source_url,rp.post_id
      FROM event_instance_candidates eic JOIN event_candidates ec ON ec.candidate_id=eic.candidate_id
      JOIN raw_posts rp ON rp.post_id=ec.post_id WHERE eic.event_instance_id=? ORDER BY rp.post_id''',(event_instance_id,)).fetchall()
    out=[]
    for r in rows:
        poster=con.execute('''SELECT media_url FROM acquired_media WHERE post_id=? AND poster_candidate=1 ORDER BY media_id DESC LIMIT 1''',(r['post_id'],)).fetchone()
        out.append(dict(r)|{'text':' '.join(x for x in (r['title'],r['body']) if x), 'poster_url':poster['media_url'] if poster else None})
    latest={x['source_id']:x for x in out}; return list(latest.values())

def infer_cross_post_cluster(con,event_instance_id,text_threshold=None):
    threshold_mode="EXPLICIT"
    canary_id=None
    if text_threshold is None:
        from .origin_threshold_promotion import effective_threshold
        eff=effective_threshold(con,event_instance_id)
        text_threshold=float(eff["threshold"])
        threshold_mode=eff["mode"]
        canary_id=eff["canary_id"]
    posts=_posts(con,event_instance_id); edges=[]
    for i,a in enumerate(posts):
        for b in posts[i+1:]:
            sim=_sim(a['text'],b['text']); same_poster=bool(a['poster_url'] and a['poster_url']==b['poster_url'])
            same_host=False
            try: same_host=bool(a['source_url'] and b['source_url'] and urlsplit(a['source_url']).netloc==urlsplit(b['source_url']).netloc)
            except: pass
            signals=[]
            if sim>=text_threshold: signals.append('NEAR_DUPLICATE_TEXT')
            if same_poster: signals.append('SAME_POSTER_URL')
            if same_host: signals.append('SAME_LINK_HOST')
            if 'NEAR_DUPLICATE_TEXT' in signals or (same_poster and sim>=.65): edges.append((a['source_id'],b['source_id'],sim,signals))
    # connected components of suspected cross-posts
    adj={x['source_id']:set() for x in posts}
    for a,b,_,_ in edges: adj[a].add(b); adj[b].add(a)
    comps=[]; seen=set()
    for s in adj:
        if s in seen: continue
        stack=[s]; c=[]
        while stack:
            x=stack.pop()
            if x in seen: continue
            seen.add(x); c.append(x); stack.extend(adj[x]-seen)
        if len(c)>=2: comps.append(c)
    results=[]
    byid={x['source_id']:x for x in posts}
    for comp in comps:
        ordered=sorted(comp,key=lambda s:(byid[s].get('published_at') or '9999',s))
        origin=ordered[0]
        key=hashlib.sha256(('|'.join(sorted(comp))).encode()).hexdigest()[:20]
        reasons=['near-duplicate/cross-post evidence detected','earliest observed publication is only a likely origin, not proof']
        cur=con.execute('''INSERT OR IGNORE INTO cross_post_clusters(event_instance_id,cluster_key,status,likely_origin_source_id,confidence,member_count,reasons_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)''',(event_instance_id,key,'AUTO_SUSPECTED_SYNDICATION',origin,'MEDIUM',len(comp),json.dumps(reasons),_now(),_now()))
        row=con.execute('SELECT cluster_id FROM cross_post_clusters WHERE event_instance_id=? AND cluster_key=?',(event_instance_id,key)).fetchone(); cid=row['cluster_id']
        con.execute('DELETE FROM cross_post_cluster_members WHERE cluster_id=?',(cid,))
        for sid in comp:
            sig=[]; sims=[]
            for a,b,sim,ss in edges:
                if sid in (a,b) and a in comp and b in comp: sig+=ss; sims.append(sim)
            score=(1.0 if sid==origin else .5)+(max(sims) if sims else 0)/10
            con.execute('''INSERT INTO cross_post_cluster_members(cluster_id,source_id,published_at,text_similarity,same_poster,same_link_origin,origin_score,signals_json) VALUES(?,?,?,?,?,?,?,?)''',(cid,sid,byid[sid].get('published_at'),max(sims) if sims else 0,int('SAME_POSTER_URL' in sig),int('SAME_LINK_HOST' in sig),score,json.dumps(sorted(set(sig)))))
        con.commit(); results.append(cluster(con,cid))
    return {
        'policy_version':POLICY_VERSION,
        'event_instance_id':event_instance_id,
        'applied_text_threshold':float(text_threshold),
        'threshold_mode':threshold_mode,
        'canary_id':canary_id,
        'clusters':results
    }

def cluster(con,cid):
    r=con.execute('SELECT * FROM cross_post_clusters WHERE cluster_id=?',(cid,)).fetchone(); x=dict(r); x['reasons']=json.loads(x.pop('reasons_json'))
    ms=con.execute('SELECT * FROM cross_post_cluster_members WHERE cluster_id=? ORDER BY origin_score DESC,member_id',(cid,)).fetchall(); x['members']=[]
    for m in ms:
        d=dict(m); d['signals']=json.loads(d.pop('signals_json')); x['members'].append(d)
    return x

def clusters(con,event_instance_id=None):
    rows=con.execute('SELECT cluster_id FROM cross_post_clusters'+(' WHERE event_instance_id=?' if event_instance_id is not None else '')+' ORDER BY cluster_id',((event_instance_id,) if event_instance_id is not None else ())).fetchall()
    return [cluster(con,r['cluster_id']) for r in rows]

def review_cluster(con,cluster_id,decision,reviewer,reason):
    if decision not in {'CONFIRM_SYNDICATION','CONFIRM_INDEPENDENT','HOLD'}: raise ValueError('invalid decision')
    if not reviewer or not reason: raise ValueError('reviewer and reason required')
    row=con.execute('SELECT event_instance_id FROM cross_post_clusters WHERE cluster_id=?',(cluster_id,)).fetchone()
    if not row: raise ValueError('cluster not found')
    con.execute('INSERT INTO origin_inference_reviews(cluster_id,decision,reviewer,reason,reviewed_at) VALUES(?,?,?,?,?)',(cluster_id,decision,reviewer,reason,_now()))
    status={'CONFIRM_SYNDICATION':'CONFIRMED_SYNDICATION','CONFIRM_INDEPENDENT':'CONFIRMED_INDEPENDENT','HOLD':'AUTO_SUSPECTED_SYNDICATION'}[decision]
    con.execute('UPDATE cross_post_clusters SET status=?,updated_at=? WHERE cluster_id=?',(status,_now(),cluster_id)); con.commit()
    # If this Event is part of a bounded threshold canary, Human review is
    # also the runtime outcome signal. False positive triggers auto rollback.
    from .origin_threshold_promotion import record_canary_outcome
    record_canary_outcome(
        con,event_instance_id=row['event_instance_id'],
        cluster_id=cluster_id,decision=decision,critical=False)

    # Full-promotion guard uses decisive Human outcomes and a Base-vs-Promoted
    # counterfactual. HOLD remains non-decisive and is not used.
    if decision in {'CONFIRM_SYNDICATION','CONFIRM_INDEPENDENT'}:
        from .origin_threshold_runtime_guard import observe_runtime_outcome
        mx=con.execute(
            'SELECT MAX(text_similarity) v FROM cross_post_cluster_members WHERE cluster_id=?',
            (cluster_id,)).fetchone()
        ev=con.execute(
            'SELECT status FROM event_instances WHERE event_instance_id=?',
            (row['event_instance_id'],)).fetchone()
        observe_runtime_outcome(
            con,event_instance_id=row['event_instance_id'],
            cluster_id=cluster_id,human_outcome=decision,
            max_text_similarity=float((mx['v'] if mx else 0) or 0),
            event_status=(ev['status'] if ev else None),
            critical=bool(ev and ev['status']=='VERIFIED'))
    return cluster(con,cluster_id)

def active_pair_signal(con,event_instance_id,a,b):
    row=con.execute('''SELECT c.cluster_id,c.status FROM cross_post_clusters c JOIN cross_post_cluster_members ma ON ma.cluster_id=c.cluster_id JOIN cross_post_cluster_members mb ON mb.cluster_id=c.cluster_id WHERE c.event_instance_id=? AND ma.source_id=? AND mb.source_id=? ORDER BY c.cluster_id DESC LIMIT 1''',(event_instance_id,a,b)).fetchone()
    return dict(row) if row else None
