from datetime import datetime, timezone, timedelta

import pytest

from src.database import init_db
from src.origin_threshold_recommendation_challenge import (
    create_challenge,challenges,add_shadow_outcome,evaluate_challenge,
    human_decision,selected_steps_for_scope,link_runtime,finalize_runtime,
    runtime_results,quality_profiles,status
)

def _rec(steps=("DATA_QUALITY_FIX","INDEPENDENCE_GRAPH_FIX"),source="CONTEXT_COMPARATIVE_RANKING"):
    return {
        "selected_steps":list(steps),"source":source,
        "comparative_score":0.81,"context_signature":"CTX"
    }

def _challenge(con,scope=1):
    return create_challenge(
        con,scope,"SOURCE_LOCAL_RECURRENCE","CTX",
        _rec(),["COLLECTOR_FIX","DATA_QUALITY_FIX"])

def _shadow(con,cid,n=8,rec="SAFE",det="SAFE",recq=None,detq=None):
    last=None
    for i in range(n):
        last=add_shadow_outcome(
            con,cid,100+i,rec,det,human_confirmed=True,
            recommended_quality_delta=recq,
            deterministic_quality_delta=detq)
    return last

def test_create_challenge_keeps_recommended_and_baseline(tmp_path):
    con=init_db(tmp_path/"create.sqlite3")
    c=_challenge(con)
    assert c["recommended_signature"]=="DATA_QUALITY_FIX+INDEPENDENCE_GRAPH_FIX"
    assert c["deterministic_signature"]=="COLLECTOR_FIX+DATA_QUALITY_FIX"
    assert c["status"]=="SHADOW_ACTIVE"
    con.close()

def test_create_challenge_is_idempotent_while_active(tmp_path):
    con=init_db(tmp_path/"idem.sqlite3")
    a=_challenge(con); b=_challenge(con)
    assert a["challenge_id"]==b["challenge_id"]
    assert len(challenges(con,1))==1
    con.close()

def test_non_human_shadow_does_not_count_decisive(tmp_path):
    con=init_db(tmp_path/"nonhuman.sqlite3")
    c=_challenge(con)
    for i in range(8):
        add_shadow_outcome(con,c["challenge_id"],i,"SAFE","UNSAFE",human_confirmed=False)
    ev=evaluate_challenge(con,c["challenge_id"])
    assert ev["decisive_count"]==0
    assert ev["status"]=="SHADOW_ACTIVE"
    con.close()

def test_challenge_requires_eight_human_distinct_events(tmp_path):
    con=init_db(tmp_path/"count.sqlite3")
    c=_challenge(con)
    _shadow(con,c["challenge_id"],7,"SAFE","UNSAFE")
    ev=evaluate_challenge(con,c["challenge_id"])
    assert ev["status"]=="SHADOW_ACTIVE"
    add_shadow_outcome(con,c["challenge_id"],999,"SAFE","UNSAFE",human_confirmed=True)
    ev=evaluate_challenge(con,c["challenge_id"])
    assert ev["status"]=="READY_FOR_HUMAN_DECISION"
    con.close()

def test_recommended_win_counts_when_only_recommendation_safe(tmp_path):
    con=init_db(tmp_path/"recwin.sqlite3")
    c=_challenge(con)
    ev=_shadow(con,c["challenge_id"],8,"SAFE","UNSAFE")
    assert ev["recommended_win_count"]==8
    assert ev["deterministic_win_count"]==0
    assert ev["recommended_win_rate"]==1.0
    con.close()

def test_baseline_win_counts_when_only_baseline_safe(tmp_path):
    con=init_db(tmp_path/"basewin.sqlite3")
    c=_challenge(con)
    ev=_shadow(con,c["challenge_id"],8,"UNSAFE","SAFE")
    assert ev["deterministic_win_count"]==8
    assert ev["recommended_win_count"]==0
    assert ev["recommended_win_rate"]==0.0
    con.close()

def test_quality_delta_breaks_safe_safe_tie(tmp_path):
    con=init_db(tmp_path/"quality.sqlite3")
    c=_challenge(con)
    ev=_shadow(con,c["challenge_id"],8,"SAFE","SAFE",recq=.04,detq=.00)
    assert ev["recommended_win_count"]==8
    assert ev["tie_count"]==0
    con.close()

def test_human_cannot_accept_before_shadow_ready(tmp_path):
    con=init_db(tmp_path/"early.sqlite3")
    c=_challenge(con)
    _shadow(con,c["challenge_id"],4,"SAFE","UNSAFE")
    with pytest.raises(ValueError,match="not ready"):
        human_decision(con,c["challenge_id"],"ACCEPT_RECOMMENDATION","architect","too early")
    con.close()

def test_human_accept_recommendation_selects_recommended_steps(tmp_path):
    con=init_db(tmp_path/"accept.sqlite3")
    c=_challenge(con)
    _shadow(con,c["challenge_id"],8,"SAFE","UNSAFE")
    d=human_decision(con,c["challenge_id"],"ACCEPT_RECOMMENDATION","architect","shadow wins")
    assert d["challenge"]["status"]=="HUMAN_ACCEPTED_RECOMMENDATION"
    sel=selected_steps_for_scope(con,1)
    assert sel["selected_side"]=="RECOMMENDATION"
    assert set(sel["steps"])=={"DATA_QUALITY_FIX","INDEPENDENCE_GRAPH_FIX"}
    con.close()

def test_human_choose_baseline_selects_deterministic_steps(tmp_path):
    con=init_db(tmp_path/"baseline.sqlite3")
    c=_challenge(con)
    _shadow(con,c["challenge_id"],8,"UNSAFE","SAFE")
    human_decision(con,c["challenge_id"],"CHOOSE_BASELINE","architect","baseline safer")
    sel=selected_steps_for_scope(con,1)
    assert sel["selected_side"]=="BASELINE"
    assert set(sel["steps"])=={"COLLECTOR_FIX","DATA_QUALITY_FIX"}
    con.close()

def test_hold_is_audited_but_does_not_create_selected_steps(tmp_path):
    con=init_db(tmp_path/"hold.sqlite3")
    c=_challenge(con)
    d=human_decision(con,c["challenge_id"],"HOLD","architect","need more evidence")
    assert d["challenge"]["status"]=="HOLD"
    assert selected_steps_for_scope(con,1) is None
    con.close()

def test_link_runtime_records_human_selected_side(tmp_path):
    con=init_db(tmp_path/"link.sqlite3")
    c=_challenge(con)
    _shadow(con,c["challenge_id"],8,"SAFE","UNSAFE")
    human_decision(con,c["challenge_id"],"ACCEPT_RECOMMENDATION","architect","use rec")
    rr=link_runtime(con,1,10,20)
    assert rr["selected_side"]=="RECOMMENDATION"
    assert rr["runtime_status"]=="ACTIVE"
    assert len(runtime_results(con))==1
    con.close()

def test_sustained_recommendation_with_shadow_win_is_helpful(tmp_path):
    con=init_db(tmp_path/"helpful.sqlite3")
    c=_challenge(con)
    _shadow(con,c["challenge_id"],8,"SAFE","UNSAFE")
    human_decision(con,c["challenge_id"],"ACCEPT_RECOMMENDATION","architect","rec wins")
    link_runtime(con,1,10,20)
    rr=finalize_runtime(con,20,"SUSTAINED_SUCCESS")
    assert rr["counterfactual_verdict"]=="RECOMMENDATION_HELPFUL"
    q=quality_profiles(con)[0]
    assert q["recommendation_helpful_count"]==1
    assert q["harmful_rate"]==0.0
    con.close()

def test_failed_recommendation_when_shadow_favored_baseline_is_harmful(tmp_path):
    con=init_db(tmp_path/"harmful.sqlite3")
    c=_challenge(con)
    _shadow(con,c["challenge_id"],8,"UNSAFE","SAFE")
    # Human can still choose recommendation after seeing the challenge; outcome evaluates that choice.
    human_decision(con,c["challenge_id"],"ACCEPT_RECOMMENDATION","architect","override for test")
    link_runtime(con,1,10,20)
    rr=finalize_runtime(con,20,"RECURRENCE_FAILED",5.0)
    assert rr["counterfactual_verdict"]=="RECOMMENDATION_HARMFUL"
    q=quality_profiles(con)[0]
    assert q["recommendation_harmful_count"]==1
    assert q["harmful_rate"]==1.0
    con.close()

def test_quality_profile_confidence_stays_low_under_three_runtime_results(tmp_path):
    con=init_db(tmp_path/"profile.sqlite3")
    for scope in (1,2):
        c=_challenge(con,scope)
        _shadow(con,c["challenge_id"],8,"SAFE","UNSAFE")
        human_decision(con,c["challenge_id"],"ACCEPT_RECOMMENDATION","architect","rec")
        link_runtime(con,scope,10+scope,20+scope)
        finalize_runtime(con,20+scope,"SUSTAINED_SUCCESS")
    q=quality_profiles(con)[0]
    assert q["runtime_decisive_count"]==2
    assert q["confidence_band"]=="LOW_DATA"
    assert q["acceptance_rate"]==1.0
    con.close()

def test_status_exposes_challenges_runtime_and_quality(tmp_path):
    con=init_db(tmp_path/"status.sqlite3")
    c=_challenge(con)
    _shadow(con,c["challenge_id"],8,"SAFE","UNSAFE")
    human_decision(con,c["challenge_id"],"ACCEPT_RECOMMENDATION","architect","rec")
    link_runtime(con,1,10,20)
    finalize_runtime(con,20,"SUSTAINED_SUCCESS")
    st=status(con)
    assert st["policy_version"]=="v0.73"
    assert len(st["challenges"])==1
    assert len(st["runtime_results"])==1
    assert len(st["quality_profiles"])==1
    con.close()
