"""v0.96.40 - a person's duplicate verdict can be taken back.

A Same event / Different events answer on the Duplicates page was final.
`duplicates.preview_revert()` / `revert_decision()` withdraw one, at the
safety level the venue Revert has (v0.96.37/38): a read-only preview, a
confirm bound to that preview, the reviewer and the console's request token,
one transaction that re-checks everything under row locks, and an audit row
per verdict row (decision REVERT, naming it; migration 048).

Withdrawing a verdict is not splitting two posts. With the verdict gone the
duplicate rules decide again, in the same transaction, exactly as the next
scan would - so a pair the rules merge by themselves is merged again, by the
rules. The preview runs that scan as a dry run and the confirm checks the
real one did the same.

Everything runs the real route: a throwaway engine store, `normalize_all()`,
`duplicates.scan()`, the real tables inside the `pg` fixture's rolled-back
transaction. Production holds no person's duplicate verdict; none is created
there.
"""

from __future__ import annotations

import re
from contextlib import contextmanager

import psycopg
import pytest

from runtime import duplicates, master_data, normalization, venue_resolution
from tests.test_v09639_evidence_and_listing import (  # noqa: F401 - fixtures
    _consistent,
    _day,
    _event,
    _id,
    _snapshot,
    run_normalization,
    settings,
    store,
    venue,
)


def _pair_of(pg, left: int, right: int) -> dict:
    with pg.cursor() as cur:
        cur.execute("SELECT * FROM event_duplicate_pairs WHERE event_id = %s "
                    "AND other_event_id = %s", tuple(sorted((left, right))))
        names = [c.name for c in cur.description]
        row = cur.fetchone()
    assert row is not None, "the scan should have asked a person about this pair"
    return dict(zip(names, row))


def _trail(pg, event_ids) -> list[tuple]:
    with pg.cursor() as cur:
        cur.execute("SELECT decision_id, event_id, canonical_event_id, decision, decided_by, "
                    "  rule, reviewer, pair_id, reverts_decision_id "
                    "FROM event_duplicate_decisions WHERE event_id = ANY(%s) "
                    "ORDER BY decision_id", (list(event_ids),))
        return cur.fetchall()


def _fingerprint(pg, day) -> tuple:
    """Everything a revert may touch on that date, to prove a preview wrote none of it."""
    with pg.cursor() as cur:
        cur.execute("SELECT event_id, canonical_event_id, duplicate_decided_by, listing_state, "
                    "  identity_key, primary_source_item_id FROM events WHERE event_date = %s "
                    "ORDER BY event_id", (day,))
        events = cur.fetchall()
        cur.execute("SELECT count(*), max(decision_id) FROM event_duplicate_decisions")
        decisions = cur.fetchone()
        cur.execute("SELECT pair_id, state, resolved_by FROM event_duplicate_pairs "
                    "ORDER BY pair_id")
        pairs = cur.fetchall()
    return events, decisions, pairs


def _verdict_id(pg, event_id: int) -> int:
    with pg.cursor() as cur:
        cur.execute("SELECT max(decision_id) FROM event_duplicate_decisions WHERE event_id = %s "
                    "AND decided_by = 'HUMAN' AND decision <> 'REVERT'", (event_id,))
        return cur.fetchone()[0]


@pytest.fixture
def two_clocks(pg, store, run_normalization, unique, venue):
    """Same night, same resolved venue, 20:00 and 21:00: the rules ask a person."""
    day = _day(6)
    ids = [store.add(_id(unique, 10), name=f"Social A {unique}", day=day, start="20:00",
                     venue=venue["name"]),
           store.add(_id(unique, 11), name=f"Social B {unique}", day=day, start="21:00",
                     venue=venue["name"])]
    run_normalization()
    duplicates.scan(pg, on=day)
    a, b = _event(pg, ids[0]), _event(pg, ids[1])
    pair = _pair_of(pg, a["event_id"], b["event_id"])
    assert pair["rule"] == duplicates.RULE_VENUE_TIME_DIFFERS and pair["state"] == "OPEN"
    return {"day": day, "ids": ids, "a": a, "b": b, "pair": pair}


def _merge(pg, case, reviewer="operator"):
    duplicates.resolve_pair(pg, case["pair"]["pair_id"], decision=duplicates.DUPLICATE,
                            canonical_event_id=case["a"]["event_id"], reviewer=reviewer,
                            reason="one night")
    return _verdict_id(pg, case["b"]["event_id"])


def _separate(pg, case, reviewer="operator"):
    duplicates.resolve_pair(pg, case["pair"]["pair_id"], decision=duplicates.DISTINCT,
                            reviewer=reviewer, reason="two nights")
    return _verdict_id(pg, case["a"]["event_id"])


def _revert(pg, decision_id, reviewer="operator", reason="test"):
    preview = duplicates.preview_revert(pg, decision_id=decision_id, reviewer=reviewer)
    assert preview["blockers"] == [], preview["blockers"]
    return preview, duplicates.revert_decision(pg, decision_id=decision_id,
                                               token=preview["token"], reviewer=reviewer,
                                               reason=reason)


def _settles(pg, run_normalization, day, ids, times=2):
    """Normalize -> scan, repeatedly: nothing moves and the invariant holds."""
    settled = _snapshot(pg, ids)
    for _ in range(times):
        run_normalization.again()
        found = duplicates.scan(pg, on=day)
        assert found["auto_merged"] == 0 and found["released"] == 0
        assert _snapshot(pg, ids) == settled
        _consistent(pg, ids)
    return settled


# --- MERGE -> Revert ------------------------------------------------------------

def test_merge_revert_puts_both_events_and_the_question_back(pg, two_clocks,
                                                           run_normalization):
    case = two_clocks
    verdict = _merge(pg, case)
    merged = _snapshot(pg, case["ids"])
    folded = merged[case["ids"][1]]
    assert folded[3] == case["a"]["event_id"] and folded[4] == "HIDDEN"

    before_preview = _fingerprint(pg, case["day"])
    preview = duplicates.preview_revert(pg, decision_id=verdict, reviewer="operator")
    assert _fingerprint(pg, case["day"]) == before_preview, "the preview wrote something"
    assert preview["status"] == "REVERT_SAFE" and preview["kind"] == duplicates.MERGE_VERDICT
    assert preview["planned"] == []                       # the rules only ask a person
    outlook = {o["event_id"]: o for o in preview["outlook"]}
    b = outlook[case["b"]["event_id"]]
    assert (b["canonical_before"], b["canonical_after"]) == (case["a"]["event_id"], None)
    assert (b["listing_before"], b["listing_after"]) == ("HIDDEN", "LISTED")
    assert (b["public_before"], b["public_after"]) == (False, True)
    assert preview["summary"]["public_changes"] == 1

    result = duplicates.revert_decision(pg, decision_id=verdict, token=preview["token"],
                                        reviewer="operator", reason="different nights")
    assert result["reverted"] == [verdict] and result["reconciliation"] == []
    after = _snapshot(pg, case["ids"])
    for cid in case["ids"]:
        assert after[cid][3] is None and after[cid][4] == "LISTED" and after[cid][5] is None
        assert after[cid][:3] == merged[cid][:3]          # event id, identity, series
    assert _pair_of(pg, case["a"]["event_id"], case["b"]["event_id"])["state"] == "OPEN"
    _settles(pg, run_normalization, case["day"], case["ids"])
    # still a question a person can answer again
    assert duplicates.count_open_pairs(pg) >= 1


def test_the_original_verdict_stays_and_the_revert_names_it(pg, two_clocks):
    verdict = _merge(pg, two_clocks)
    original = _trail(pg, [two_clocks["b"]["event_id"]])
    _revert(pg, verdict, reason="wrong merge")
    trail = _trail(pg, [two_clocks["b"]["event_id"]])
    assert trail[:len(original)] == original               # nothing rewritten
    revert = trail[-1]
    assert revert[3] == duplicates.REVERT and revert[4] == duplicates.HUMAN
    assert revert[5] == duplicates.RULE_HUMAN_REVERT and revert[8] == verdict
    assert revert[7] == two_clocks["pair"]["pair_id"]
    with pg.cursor() as cur:
        cur.execute("SELECT reason, before_json, after_json FROM event_duplicate_decisions "
                    "WHERE decision_id = %s", (revert[0],))
        reason, before, after = cur.fetchone()
    assert reason == "wrong merge"
    assert before["verdict"] == "MERGE" and before["original_decision"]["decision_id"] == verdict
    states = {e["event_id"]: e for e in before["events"]}
    assert states[two_clocks["b"]["event_id"]]["listing_state"] == "HIDDEN"
    now = {e["event_id"]: e for e in after["events"]}
    assert now[two_clocks["b"]["event_id"]]["listing_state"] == "LISTED"
    assert after["reconciliation"] == [] and after["pair"][1] == "OPEN"


def test_merge_then_normalize_then_scan_then_revert(pg, two_clocks, run_normalization):
    verdict = _merge(pg, two_clocks)
    for _ in range(2):
        run_normalization.again()
        duplicates.scan(pg, on=two_clocks["day"])
    _consistent(pg, two_clocks["ids"])
    _revert(pg, verdict)
    assert all(v[3] is None for v in _snapshot(pg, two_clocks["ids"]).values())
    _settles(pg, run_normalization, two_clocks["day"], two_clocks["ids"])


# --- KEEP_SEPARATE -> Revert ------------------------------------------------------

def test_keep_separate_revert_lets_the_rules_ask_again(pg, two_clocks, run_normalization):
    case = two_clocks
    verdict = _separate(pg, case)
    assert all(v[5] == duplicates.HUMAN for v in _snapshot(pg, case["ids"]).values())
    preview, result = _revert(pg, verdict)
    assert preview["kind"] == duplicates.KEEP_SEPARATE_VERDICT
    assert len(result["reverted"]) == 2                    # both halves of the answer
    after = _snapshot(pg, case["ids"])
    assert all(v[3] is None and v[4] == "LISTED" and v[5] is None for v in after.values())
    assert _pair_of(pg, case["a"]["event_id"], case["b"]["event_id"])["state"] == "OPEN"
    # the rules still only ask: no automatic merge of 20:00 and 21:00
    _settles(pg, run_normalization, case["day"], case["ids"])


def test_reverting_either_half_of_a_keep_separate_answer_is_the_same_revert(pg, two_clocks):
    _separate(pg, two_clocks)
    other_half = _verdict_id(pg, two_clocks["b"]["event_id"])
    preview, result = _revert(pg, other_half)
    assert sorted(result["reverted"]) == sorted(
        [_verdict_id(pg, two_clocks["a"]["event_id"]), other_half])


# --- the rules decide again: a verdict over a pair they now merge by themselves ---

@pytest.fixture
def unresolved_twins(pg, store, run_normalization, unique):
    """One 15:00 practica posted twice at words nobody has resolved: a question
    for a person (v0.96.23) until the venue is approved."""
    text = f"탱고 파시온 {unique} (서울 마포구 월드컵북로6길 69)"
    day = _day(3)
    ids = [store.add(_id(unique, 20), name=f"평일 낮쁘락 {unique}", day=day, start="15:00",
                     venue=text),
           store.add(_id(unique, 21), name=f"Pasion 낮쁘락 {unique}", day=day, start="15:00",
                     venue=text)]
    run_normalization()
    duplicates.scan(pg, on=day)
    a, b = _event(pg, ids[0]), _event(pg, ids[1])
    pair = _pair_of(pg, a["event_id"], b["event_id"])
    assert pair["rule"] == duplicates.RULE_UNRESOLVED_VENUE_TIME
    return {"day": day, "ids": ids, "a": a, "b": b, "pair": pair, "text": text}


def _approve(pg, settings, seoul_id, unique, case):
    with pg.cursor() as cur:
        cur.execute("SELECT unresolved_venue_id FROM unresolved_venues "
                    "WHERE normalized_text = %s", (master_data.normalize_alias(case["text"]),))
        uid = cur.fetchone()[0]
    name = f"Tango Pasion {unique}"
    preview = venue_resolution.preview_create(pg, unresolved_venue_id=uid, name=name,
                                              region_id=seoul_id, settings=settings)
    assert preview["blockers"] == []
    venue_resolution.confirm_create(pg, unresolved_venue_id=uid, name=name, region_id=seoul_id,
                                    token=preview["token"], settings=settings)
    return uid


def test_venue_approval_after_a_merge_then_revert_merges_again_by_rule(
        pg, unresolved_twins, run_normalization, settings, seoul_id, unique):
    case = unresolved_twins
    verdict = _merge(pg, case)
    _approve(pg, settings, seoul_id, unique, case)
    run_normalization()
    duplicates.scan(pg, on=case["day"])
    human = _snapshot(pg, case["ids"])[case["ids"][1]]
    assert human[3] == case["a"]["event_id"] and human[5] == duplicates.HUMAN

    preview, result = _revert(pg, verdict)
    # the rules' own fold: the older event heads it (v0.94.0), whichever one
    # the person had kept
    older, newer = sorted((case["a"]["event_id"], case["b"]["event_id"]))
    assert preview["planned"] == [["MERGE", newer, older,
                                   duplicates.RULE_SAME_DATE_VENUE_TIME]]
    assert result["reconciliation"] == preview["planned"]
    assert any("merge these posts by themselves" in w for w in preview["warnings"])
    kept = case["a"]["event_id"]
    assert preview["summary"]["public_changes"] == (0 if kept == older else 2)
    assert preview["summary"]["public_after"] == 1           # one night, shown once
    with pg.cursor() as cur:
        cur.execute("SELECT event_id, canonical_event_id, listing_state, duplicate_decided_by "
                    "FROM events WHERE event_id = ANY(%s) ORDER BY event_id", ([older, newer],))
        rows = cur.fetchall()
    assert rows == [(older, None, "LISTED", None), (newer, older, "HIDDEN", duplicates.AUTO)]
    _settles(pg, run_normalization, case["day"], case["ids"])


def test_keep_separate_revert_merges_only_when_the_rules_do(
        pg, unresolved_twins, run_normalization, settings, seoul_id, unique):
    case = unresolved_twins
    verdict = _separate(pg, case)
    _approve(pg, settings, seoul_id, unique, case)
    run_normalization()
    duplicates.scan(pg, on=case["day"])
    assert all(v[3] is None for v in _snapshot(pg, case["ids"]).values()), \
        "a person's keep-separate holds against the rules"
    preview, _ = _revert(pg, verdict)
    assert [a[0] for a in preview["planned"]] == ["MERGE"]
    assert sum(v[3] is not None for v in _snapshot(pg, case["ids"]).values()) == 1
    _settles(pg, run_normalization, case["day"], case["ids"])


def test_a_venue_revert_waits_for_the_persons_merge_and_works_after_it(
        pg, unresolved_twins, run_normalization, settings, seoul_id, unique):
    case = unresolved_twins
    verdict = _merge(pg, case)
    uid = _approve(pg, settings, seoul_id, unique, case)
    run_normalization()
    duplicates.scan(pg, on=case["day"])
    blocked = venue_resolution.preview_revert(pg, unresolved_venue_id=uid, settings=settings)
    assert any("by a person" in b for b in blocked["blockers"])
    _revert(pg, verdict)                                   # the rules fold it again (AUTO)
    preview = venue_resolution.preview_revert(pg, unresolved_venue_id=uid, settings=settings)
    assert preview["blockers"] == []
    venue_resolution.revert_decision(pg, unresolved_venue_id=uid, token=preview["token"],
                                     settings=settings)
    run_normalization()
    duplicates.scan(pg, on=case["day"])
    after = _snapshot(pg, case["ids"])
    assert all(v[3] is None and v[4] == "LISTED" for v in after.values())
    _consistent(pg, case["ids"])


# --- what blocks a revert ---------------------------------------------------------

def test_a_later_verdict_on_the_same_event_blocks_it(pg, store, run_normalization, unique,
                                                    two_clocks, venue):
    verdict = _merge(pg, two_clocks)
    third = store.add(_id(unique, 12), name=f"Social C {unique}", day=two_clocks["day"],
                      start="22:00", venue=venue["name"])
    run_normalization()
    duplicates.scan(pg, on=two_clocks["day"])
    c = _event(pg, third)
    later_pair = _pair_of(pg, two_clocks["a"]["event_id"], c["event_id"])
    duplicates.resolve_pair(pg, later_pair["pair_id"], decision=duplicates.DISTINCT,
                            reviewer="second")
    later = _verdict_id(pg, c["event_id"])
    preview = duplicates.preview_revert(pg, decision_id=verdict)
    assert preview["status"] == duplicates.REVERT_BLOCKED_DEPENDENCY
    assert any(f"#{later - 1}" in b or f"#{later}" in b for b in preview["blockers"])
    with pytest.raises(duplicates.RevertRefused) as refused:
        duplicates.revert_decision(pg, decision_id=verdict, token=preview["token"])
    assert refused.value.code == duplicates.REVERT_BLOCKED_DEPENDENCY
    # undo the later one first, then this one goes through
    _revert(pg, later)
    _revert(pg, verdict)
    assert _snapshot(pg, two_clocks["ids"])[two_clocks["ids"][1]][3] is None


def test_a_person_chosen_representative_post_blocks_it(pg, two_clocks):
    verdict = _merge(pg, two_clocks)
    duplicates.set_primary_source(pg, two_clocks["a"]["event_id"],
                                  two_clocks["b"]["source_item_id"], reviewer="operator")
    preview = duplicates.preview_revert(pg, decision_id=verdict)
    assert preview["status"] == duplicates.REVERT_BLOCKED_DEPENDENCY
    assert any("representative source" in b for b in preview["blockers"])


def test_a_changed_canonical_parent_blocks_it(pg, two_clocks):
    verdict = _merge(pg, two_clocks)
    with pg.cursor() as cur:                               # e.g. the canonical pruned
        cur.execute("UPDATE events SET canonical_event_id = NULL, duplicate_decided_by = NULL, "
                    "listing_state = 'LISTED' WHERE event_id = %s",
                    (two_clocks["b"]["event_id"],))
    preview = duplicates.preview_revert(pg, decision_id=verdict)
    assert any("no longer stands" in b for b in preview["blockers"])


def test_an_automatic_decision_or_a_revert_is_not_revertable(pg, two_clocks, store,
                                                           run_normalization, unique, venue):
    day = two_clocks["day"]
    twin = store.add(_id(unique, 13), name=f"Social A again {unique}", day=day, start="20:00",
                     venue=venue["name"])
    run_normalization()
    duplicates.scan(pg, on=day)
    auto = _verdict_id(pg, _event(pg, twin)["event_id"])
    assert auto is None                                    # the rules merged it, no person
    with pg.cursor() as cur:
        cur.execute("SELECT max(decision_id) FROM event_duplicate_decisions WHERE event_id = %s",
                    (_event(pg, twin)["event_id"],))
        auto = cur.fetchone()[0]
    assert duplicates.preview_revert(pg, decision_id=auto)["blockers"]
    verdict = _merge(pg, two_clocks)
    _, result = _revert(pg, verdict)
    revert_row = result["revert_decisions"][0]["decision_id"]
    assert duplicates.preview_revert(pg, decision_id=revert_row)["blockers"]
    with pytest.raises(LookupError):
        duplicates.preview_revert(pg, decision_id=10**12)


def test_repeating_a_revert_is_refused(pg, two_clocks):
    verdict = _merge(pg, two_clocks)
    preview, _ = _revert(pg, verdict)
    again = duplicates.preview_revert(pg, decision_id=verdict)
    assert again["status"] == "REVERT_ALREADY_APPLIED"
    with pytest.raises(duplicates.RevertRefused):
        duplicates.revert_decision(pg, decision_id=verdict, token=preview["token"])


def test_one_verdict_can_be_reverted_only_once_even_by_two_confirms(pg, two_clocks):
    """Two confirms racing: the first holds the verdict's rows FOR UPDATE and
    the second re-reads them after; if both ever got as far as writing, the
    unique index on reverts_decision_id refuses the second row."""
    verdict = _merge(pg, two_clocks)
    _revert(pg, verdict)
    with pytest.raises(psycopg.errors.UniqueViolation):
        with pg.transaction():
            with pg.cursor() as cur:
                cur.execute(
                    "INSERT INTO event_duplicate_decisions (event_id, decision, decided_by, "
                    "  rule, reviewer, reverts_decision_id) VALUES (%s, 'REVERT', 'HUMAN', "
                    "  'HUMAN_REVERT', 'second', %s)", (two_clocks["b"]["event_id"], verdict))


def test_only_a_person_reverts_and_a_revert_names_its_verdict(pg, two_clocks):
    for values in (("REVERT", "AUTO", 1), ("REVERT", "HUMAN", None), ("DISTINCT", "HUMAN", 1)):
        with pytest.raises(psycopg.errors.CheckViolation):
            with pg.transaction():
                with pg.cursor() as cur:
                    cur.execute(
                        "INSERT INTO event_duplicate_decisions (event_id, decision, decided_by, "
                        "  rule, reverts_decision_id) VALUES (%s, %s, %s, 'X', %s)",
                        (two_clocks["a"]["event_id"], *values))


# --- tokens ---------------------------------------------------------------------

def test_a_stale_preview_is_refused_and_writes_nothing(pg, two_clocks, store,
                                                       run_normalization, unique, venue):
    verdict = _merge(pg, two_clocks)
    preview = duplicates.preview_revert(pg, decision_id=verdict, reviewer="operator")
    # the date changes after the preview: another post of 20:00 at the venue
    store.add(_id(unique, 14), name=f"Social A repost {unique}", day=two_clocks["day"],
              start="20:00", venue=venue["name"])
    run_normalization()
    before = _fingerprint(pg, two_clocks["day"])
    with pytest.raises(duplicates.StaleRevertPreview):
        duplicates.revert_decision(pg, decision_id=verdict, token=preview["token"],
                                   reviewer="operator")
    assert _fingerprint(pg, two_clocks["day"]) == before


@pytest.mark.parametrize("forge", ["garbage", "", "expired", "other_reviewer",
                                   "other_decision", "venue_preview"])
def test_a_token_that_was_not_issued_for_this_revert_is_refused(pg, two_clocks, forge,
                                                                 settings):
    verdict = _merge(pg, two_clocks)
    preview = duplicates.preview_revert(pg, decision_id=verdict, reviewer="operator")
    token = {
        "garbage": "123.abc",
        "": "",
        "expired": duplicates.revert_token(preview["facts"], reviewer="operator",
                                           now=1_000_000_000),
        "other_reviewer": duplicates.revert_token(preview["facts"], reviewer="intruder"),
        "other_decision": duplicates.revert_token({**preview["facts"], "decisions": [1]},
                                                  reviewer="operator"),
        # v0.96.37's venue preview token over the very same facts: another key
        "venue_preview": venue_resolution.preview_token(preview["facts"], reviewer="operator"),
    }[forge]
    before = _fingerprint(pg, two_clocks["day"])
    with pytest.raises(duplicates.StaleRevertPreview):
        duplicates.revert_decision(pg, decision_id=verdict, token=token, reviewer="operator")
    assert _fingerprint(pg, two_clocks["day"]) == before


def test_a_failure_part_way_rolls_everything_back(pg, two_clocks, monkeypatch):
    verdict = _merge(pg, two_clocks)
    preview = duplicates.preview_revert(pg, decision_id=verdict, reviewer="operator")
    before = _fingerprint(pg, two_clocks["day"])
    real_scan = duplicates.scan

    def failing_scan(con, **kwargs):
        if kwargs.get("dry_run"):
            return real_scan(con, **kwargs)
        raise RuntimeError("the database went away mid-revert")

    monkeypatch.setattr(duplicates, "scan", failing_scan)
    with pytest.raises(RuntimeError):
        duplicates.revert_decision(pg, decision_id=verdict, token=preview["token"],
                                   reviewer="operator")
    assert _fingerprint(pg, two_clocks["day"]) == before


def test_a_verdict_from_before_this_release_has_no_pair_id_and_still_reverts(pg, two_clocks):
    """0.96.39's resolve_pair wrote no pair_id; the pair is found by its events."""
    case = two_clocks
    for event_id in (case["a"]["event_id"], case["b"]["event_id"]):
        duplicates.record_decision(pg, event_id=event_id, canonical_event_id=None,
                                   decision=duplicates.DISTINCT, decided_by=duplicates.HUMAN,
                                   rule=duplicates.RULE_HUMAN_REVIEW, reviewer="legacy")
    with pg.cursor() as cur:
        cur.execute("UPDATE event_duplicate_pairs SET state = 'DISTINCT', resolved_by = 'legacy' "
                    "WHERE pair_id = %s", (case["pair"]["pair_id"],))
    _, result = _revert(pg, _verdict_id(pg, case["a"]["event_id"]))
    assert len(result["reverted"]) == 2 and result["pair_id"] == case["pair"]["pair_id"]
    assert _pair_of(pg, case["a"]["event_id"], case["b"]["event_id"])["state"] == "OPEN"


def test_no_other_event_is_touched(pg, two_clocks, store, run_normalization, unique):
    other = store.add(_id(unique, 15), name=f"Elsewhere {unique}", day=two_clocks["day"],
                      start="19:00", venue=f"다른 홀 {unique}")
    run_normalization()
    duplicates.scan(pg, on=two_clocks["day"])
    kept = _snapshot(pg, [other])
    verdict = _merge(pg, two_clocks)
    _revert(pg, verdict)
    assert _snapshot(pg, [other]) == kept


# --- the console ------------------------------------------------------------------

class _Shared:
    def __init__(self, con):
        self._con = con

    def commit(self):
        pass

    def rollback(self):
        pass

    def __getattr__(self, name):
        return getattr(self._con, name)


@pytest.fixture
def console(pg, monkeypatch, run_normalization):
    """The app on the test's own connection. Depends on `run_normalization`
    so its own `db.connect` patch (the raw connection, whose rollback is real)
    is in place first and this one wins."""
    from fastapi.testclient import TestClient

    from runtime import admin, db
    from runtime.app import app

    monkeypatch.setenv("ADMIN_USERNAME", "tester")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-only")

    @contextmanager
    def shared(*args, **kwargs):
        yield _Shared(pg)

    monkeypatch.setattr(admin, "_connection", shared)
    monkeypatch.setattr(db, "connect", shared)
    client = TestClient(app)
    client.auth = ("tester", "test-only")
    return client


def test_the_console_resolves_previews_and_reverts(console, pg, two_clocks):
    case = two_clocks
    choice = {"action": f"keep_{case['a']['event_id']}"}
    # v0.96.46: an answer is confirmed from its signed preview.
    answer = console.post(f"/admin/duplicates/{case['pair']['pair_id']}/preview", data=choice)
    assert answer.status_code == 200
    signed = re.search(r'name="token" value="([^"]+)"', answer.text).group(1)
    done = console.post(f"/admin/duplicates/{case['pair']['pair_id']}",
                        data={**choice, "token": signed},
                        follow_redirects=False)
    assert done.status_code in (302, 303)
    verdict = _verdict_id(pg, case["b"]["event_id"])
    assert _trail(pg, [case["b"]["event_id"]])[-1][6] == "tester"   # the reviewer, recorded

    page = console.get("/admin/duplicates")
    assert f"/admin/duplicates/decisions/{verdict}/revert/preview" in page.text
    before = _fingerprint(pg, case["day"])
    preview = console.post(f"/admin/duplicates/decisions/{verdict}/revert/preview")
    assert preview.status_code == 200 and "Confirm Revert" in preview.text
    assert "REVERT_SAFE" in preview.text
    assert _fingerprint(pg, case["day"]) == before
    token = re.search(r'name="token" value="([0-9]+\.[0-9a-f]{64})"', preview.text).group(1)

    forged = console.post(f"/admin/duplicates/decisions/{verdict}/revert",
                          data={"token": "1.dead"}, follow_redirects=False)
    assert forged.status_code == 409 and "REVERT_STALE_PREVIEW" in forged.text
    assert _fingerprint(pg, case["day"]) == before

    done = console.post(f"/admin/duplicates/decisions/{verdict}/revert",
                        data={"token": token, "reason": "different nights"},
                        follow_redirects=False)
    assert done.status_code in (302, 303)
    assert _snapshot(pg, case["ids"])[case["ids"][1]][3] is None
    again = console.post(f"/admin/duplicates/decisions/{verdict}/revert/preview")
    assert again.status_code == 409 and "Confirm Revert" not in again.text


def test_a_blocked_revert_shows_why_and_no_confirm(console, pg, two_clocks):
    verdict = _merge(pg, two_clocks)
    duplicates.set_primary_source(pg, two_clocks["a"]["event_id"],
                                  two_clocks["b"]["source_item_id"], reviewer="operator")
    page = console.post(f"/admin/duplicates/decisions/{verdict}/revert/preview")
    assert page.status_code == 409
    assert duplicates.REVERT_BLOCKED_DEPENDENCY in page.text
    assert "Confirm Revert" not in page.text


@pytest.fixture
def client(env, monkeypatch):
    from fastapi.testclient import TestClient

    from runtime import app as app_module

    monkeypatch.setattr(app_module, "_settings", None)
    return TestClient(app_module.app, raise_server_exceptions=False)


def test_the_revert_routes_need_a_login_and_a_request_token(client, monkeypatch):
    for path in ("/admin/duplicates/decisions/1/revert/preview",
                 "/admin/duplicates/decisions/1/revert"):
        assert client.post(path).status_code in (401, 503), path
    monkeypatch.setenv("ADMIN_USERNAME", "tester")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-only")
    client.console_tokens = False
    for path in ("/admin/duplicates/decisions/1/revert/preview",
                 "/admin/duplicates/decisions/1/revert"):
        assert client.post(path, auth=("tester", "test-only")).status_code == 403, path
