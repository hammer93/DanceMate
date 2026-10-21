"""v0.96.46: every human decision is accepted only against what was previewed.

Review actions (EDIT / CONFIRM / APPROVE / REJECT / DUPLICATE) need the
current decision basis, from a form or from JSON alike; Duplicates answers
(MERGE / KEEP_SEPARATE) need a signed preview bound to their action, pair,
reviewer and a digest of the state they rest on. The parallel tests at the
end run on independent connections against committed rows of the disposable
database and clean up after themselves.
"""

from __future__ import annotations

import re
import threading
import time as clock
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from runtime import decision_contract as DC
from runtime import duplicates, review
from tests.test_v09642_source_revision import client, pipe  # noqa: F401 - fixtures
from tests.test_v09643_article_refresh import ktango  # noqa: F401 - fixture
from tests.test_v09639_evidence_and_listing import (  # noqa: F401 - fixtures
    _event, _id, run_normalization, settings, store, venue)
from tests.test_v09640_duplicate_revert import (  # noqa: F401 - fixtures
    _fingerprint, _verdict_id, console, two_clocks)
from tests.test_v09644_event_conflicts import corpus  # noqa: F401 - fixture

PURPOSE = duplicates.RESOLVE_TOKEN_PURPOSE
FACTS = {"pair": [1, 2, 3], "members": [[2, "x"], [3, "y"]]}


@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "tester")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-only")
    monkeypatch.delenv("ADMIN_TOKEN_SECRET", raising=False)


def _token(**kw):
    args = {"action": "MERGE", "subject": 1, "facts": FACTS, "reviewer": "tester", **kw}
    return DC.preview_token(PURPOSE, **args)


def _why(token, **kw):
    args = {"action": "MERGE", "subject": 1, "facts": FACTS, "reviewer": "tester", **kw}
    refused = DC.preview_refusal(token, PURPOSE, **args)
    return None if refused is None else refused.code


# --- the signed preview token itself -----------------------------------------------

def test_a_preview_token_opens_one_action_on_one_pair_for_one_reviewer(secret):
    token = _token()
    assert _why(token) is None
    assert _why(None) == DC.MISSING_PREVIEW_TOKEN
    assert _why("") == DC.MISSING_PREVIEW_TOKEN
    assert _why(token, action="KEEP_SEPARATE") == DC.WRONG_ACTION_TOKEN
    assert _why(_token(action="KEEP_SEPARATE")) == DC.WRONG_ACTION_TOKEN
    assert _why(token, subject=2) == DC.WRONG_SUBJECT_TOKEN
    assert _why(token, reviewer="someone-else") == DC.INVALID_PREVIEW_TOKEN
    assert _why(token, facts={**FACTS, "members": [[2, "x"], [3, "z"]]}) == DC.STALE_PREVIEW


@pytest.mark.parametrize("bad", ["x", "p1.1.MERGE.1.00.00", "1.dead", "0" * 64,
                                 "v1.1700000000." + "0" * 64])
def test_a_malformed_token_is_refused(secret, bad):
    assert _why(bad) == DC.INVALID_PREVIEW_TOKEN


def test_a_forged_or_altered_token_is_refused(secret):
    token = _token()
    head, signature = token.rsplit(".", 1)
    assert _why(head + "." + "0" * 64) == DC.INVALID_PREVIEW_TOKEN
    # Swapping the action, subject or digest in the clear breaks the signature.
    parts = token.split(".")
    for index, value in ((2, "KEEP_SEPARATE"), (3, "2"), (4, "0" * 32)):
        altered = parts.copy()
        altered[index] = value
        assert _why(".".join(altered), action=altered[2], subject=int(altered[3])) \
            == DC.INVALID_PREVIEW_TOKEN, index


def test_an_expired_or_future_token_is_refused(secret):
    old = _token(now=clock.time() - DC.PREVIEW_TOKEN_TTL_SECONDS - 5)
    assert _why(old) == DC.EXPIRED_PREVIEW
    future = _token(now=clock.time() + DC.CLOCK_SKEW_SECONDS + 60)
    assert _why(future) == DC.INVALID_PREVIEW_TOKEN


def test_a_token_from_another_purpose_or_key_is_refused(secret, monkeypatch):
    token = _token()
    assert DC.preview_refusal(token, "venue-decision", action="MERGE", subject=1,
                              facts=FACTS, reviewer="tester").code == DC.INVALID_PREVIEW_TOKEN
    monkeypatch.setenv("ADMIN_TOKEN_SECRET", "rotated")
    assert _why(token) == DC.INVALID_PREVIEW_TOKEN


def test_the_revert_token_does_not_open_a_resolve(secret):
    assert _why(duplicates.revert_token(FACTS, reviewer="tester")) == DC.INVALID_PREVIEW_TOKEN


# --- the review basis ----------------------------------------------------------------

def test_a_basis_is_required_well_formed_and_current():
    current = "0123456789abcdef0123456789abcdef"
    assert DC.basis_refusal(None, current).code == DC.MISSING_BASIS
    assert DC.basis_refusal("  ", current).code == DC.MISSING_BASIS
    assert DC.basis_refusal("xyz", current).code == DC.INVALID_BASIS
    assert DC.basis_refusal(current.upper(), current).code == DC.INVALID_BASIS
    assert DC.basis_refusal("f" * 32, current).code == DC.STALE_REVIEW_STATE
    assert DC.basis_refusal(current, current) is None
    assert DC.STATUS[DC.MISSING_BASIS] == 422 and DC.STATUS[DC.STALE_REVIEW_STATE] == 409


def test_no_bypass_switch_exists():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "runtime"
    for name in ("decision_contract.py", "admin_pages.py", "duplicates.py", "events_admin.py"):
        text = (root / name).read_text(encoding="utf-8")
        for switch in ("skip_basis", "legacy_mode", "trusted_client", "ignore_stale",
                       "force_merge"):
            assert switch not in text, (name, switch)


# --- Review: every action, form and JSON ------------------------------------------------

def _actions(pg, candidate_id) -> int:
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM human_review_actions WHERE candidate_id = %s",
                    (candidate_id,))
        return cur.fetchone()[0]


def _basis_of(client, cid) -> str:
    response = client.get(f"/api/admin/review/{cid}")
    assert response.status_code == 200
    basis = response.json()["basis"]
    page = client.get(f"/admin/review/{cid}").text
    assert set(re.findall(r'name="basis" value="([0-9a-f]{32})"', page)) == {basis}, \
        "the page and the API hand out the same basis"
    return basis


def _tone(response) -> str:
    assert response.status_code == 303
    return parse_qs(urlparse(response.headers["location"]).query)["tone"][0]


def _form(action, ktango, pipe):
    if action == "edit":
        return {"start_time": "20:00", "reason": "test"}
    if action == "duplicate":
        return {"duplicate_of_candidate_id": str(pipe.event(ktango[647])["candidate_id"])}
    return {"reason": "test"}


@pytest.mark.parametrize("action", ["approve", "edit", "reject", "duplicate", "confirm"])
def test_every_review_action_needs_its_current_basis_by_form(pipe, ktango, client, action):
    cid = pipe.event(ktango[643])["candidate_id"]
    fields = _form(action, ktango, pipe)
    for bad in ({}, {"basis": ""}, {"basis": "nonsense"}, {"basis": "0" * 32},
                {"basis": "0" * 32, "skip_basis": "true", "legacy_mode": "1"}):
        refused = client.post(f"/admin/review/{cid}/{action}", data={**fields, **bad},
                              follow_redirects=False)
        assert _tone(refused) == "bad", bad
    assert _actions(pipe.pg, cid) == 0
    basis = _basis_of(client, cid)
    done = client.post(f"/admin/review/{cid}/{action}", data={**fields, "basis": basis},
                       follow_redirects=False)
    assert _tone(done) == "ok"
    assert _actions(pipe.pg, cid) == 1
    replay = client.post(f"/admin/review/{cid}/{action}", data={**fields, "basis": basis},
                         follow_redirects=False)
    assert _tone(replay) == "bad"
    assert _actions(pipe.pg, cid) == 1, "the same form never records twice"
    with pipe.pg.cursor() as cur:
        cur.execute("SELECT reviewer FROM human_review_actions WHERE candidate_id = %s",
                    (cid,))
        assert cur.fetchone()[0] == "dancemate", "the authenticated user, not a default"


@pytest.mark.parametrize("action", ["APPROVE", "EDIT", "REJECT", "DUPLICATE", "CONFIRM"])
def test_every_review_action_needs_its_current_basis_by_json(pipe, ktango, client, action):
    cid = pipe.event(ktango[646])["candidate_id"]
    payload = {"action": action, "reason": "test"}
    if action == "EDIT":
        payload["fields"] = {"start_time": "15:00"}
    if action == "DUPLICATE":
        payload["duplicate_of_candidate_id"] = pipe.event(ktango[647])["candidate_id"]
    url = f"/api/admin/review/{cid}"
    cases = [({}, 422, DC.MISSING_BASIS), ({"basis": None}, 422, DC.MISSING_BASIS),
             ({"basis": 12345}, 422, DC.MISSING_BASIS),
             ({"basis": "zz"}, 422, DC.INVALID_BASIS),
             ({"basis": "a" * 32}, 409, DC.STALE_REVIEW_STATE),
             ({"skip_basis": True, "trusted_client": True}, 422, DC.MISSING_BASIS)]
    for extra, status, code in cases:
        response = client.post(url, json={**payload, **extra})
        assert response.status_code == status, (extra, response.text)
        assert response.json()["detail"]["code"] == code
        assert response.json()["detail"]["recorded"] is False
    basis = _basis_of(client, cid)
    other = client.post(url, json={**payload, "basis": basis, "reviewer": "someone-else"})
    assert other.status_code == 422 and other.json()["detail"]["code"] == DC.REVIEWER_MISMATCH
    assert _actions(pipe.pg, cid) == 0
    done = client.post(url, json={**payload, "basis": basis})
    assert done.status_code == 200, done.text
    assert done.json()["reviewer"] == "dancemate"
    replay = client.post(url, json={**payload, "basis": basis})
    assert replay.status_code == 409 and replay.json()["detail"]["code"] == DC.STALE_REVIEW_STATE
    assert _actions(pipe.pg, cid) == 1


def test_a_basis_for_one_candidate_does_not_open_another(pipe, ktango, client):
    one = pipe.event(ktango[643])["candidate_id"]
    two = pipe.event(ktango[647])["candidate_id"]
    response = client.post(f"/api/admin/review/{two}",
                           json={"action": "CONFIRM", "basis": _basis_of(client, one)})
    assert response.status_code == 409
    assert _actions(pipe.pg, two) == 0


def _content_hash(pipe, item_id, value):
    with pipe.pg.cursor() as cur:
        cur.execute("UPDATE source_item_content SET content_hash = %s WHERE source_item_id = %s",
                    (value, item_id))


@pytest.mark.parametrize("change", ["source_revised", "poster_reread", "event_changed",
                                    "other_reviewer"])
def test_a_change_after_the_page_was_opened_refuses_the_decision(pipe, ktango, client, change):
    item_id = ktango[647]
    event = pipe.event(item_id)
    cid = event["candidate_id"]
    basis = _basis_of(client, cid)
    with pipe.pg.cursor() as cur:
        if change == "source_revised":
            cur.execute("UPDATE source_item_content SET content_hash = md5(random()::text) "
                        "WHERE source_item_id = %s", (item_id,))
        elif change == "poster_reread":
            cur.execute("INSERT INTO source_item_image (source_item_id, image_url, image_index, "
                        "  content_hash, ocr_text) VALUES (%s, 'https://x.invalid/p.jpg', 9, "
                        "  'h', '2024.09.29 20:00')", (item_id,))
        elif change == "event_changed":
            cur.execute("UPDATE events SET start_time = '21:00' WHERE event_id = %s",
                        (event["event_id"],))
    if change == "other_reviewer":
        review.record(pipe.pg, candidate_id=cid, action=review.CONFIRM, reviewer="other")
    before = _actions(pipe.pg, cid)
    response = client.post(f"/api/admin/review/{cid}", json={"action": "CONFIRM",
                                                              "basis": basis})
    assert response.status_code == 409, change
    assert _actions(pipe.pg, cid) == before
    form = client.post(f"/admin/review/{cid}/edit",
                       data={"basis": basis, "start_time": "20:00"}, follow_redirects=False)
    assert _tone(form) == "bad"
    assert _actions(pipe.pg, cid) == before
    assert (review.state(pipe.pg, cid).get("corrected_json") or {}) == {}, "no edit applied"


def test_a_recheck_that_found_nothing_new_keeps_the_basis(pipe, ktango, client):
    item_id = ktango[647]
    cid = pipe.event(item_id)["candidate_id"]
    basis = _basis_of(client, cid)
    with pipe.pg.cursor() as cur:
        cur.execute("UPDATE source_item_content SET fetched_at = now() + interval '1 hour' "
                    "WHERE source_item_id = %s", (item_id,))
        cur.execute("UPDATE source_items SET collected_at = now() WHERE source_item_id = %s",
                    (item_id,))
    assert _basis_of(client, cid) == basis, "a fetch time is not something a reviewer saw"
    assert client.post(f"/api/admin/review/{cid}",
                       json={"action": "CONFIRM", "basis": basis}).status_code == 200


def test_a_review_mutation_needs_a_login_and_a_request_token(pipe, ktango, client):
    cid = pipe.event(ktango[647])["candidate_id"]
    basis = _basis_of(client, cid)
    url = f"/api/admin/review/{cid}"
    assert client.post(url, json={"action": "CONFIRM", "basis": basis},
                       auth=None).status_code == 401
    assert client.post(url, json={"action": "CONFIRM", "basis": basis},
                       auth=("dancemate", "wrong")).status_code == 401
    client.console_tokens = False
    assert client.post(url, json={"action": "CONFIRM", "basis": basis}).status_code == 403
    assert client.post(url, json={"action": "CONFIRM", "basis": basis},
                       headers={"X-CSRF-Token": "v1.1.00"}).status_code == 403
    assert _actions(pipe.pg, cid) == 0


def test_the_review_api_detail_is_read_only_and_404s_unknown(pipe, ktango, client):
    cid = pipe.event(ktango[643])["candidate_id"]
    before = _actions(pipe.pg, cid)
    body = client.get(f"/api/admin/review/{cid}").json()
    assert DC.BASIS_RE.match(body["basis"]) and body["review"]["review_state"] == "PENDING"
    assert client.get("/api/admin/review/987654321098").status_code == 404
    assert _actions(pipe.pg, cid) == before
    assert client.get("/api/admin/review/1", auth=None).status_code == 401


# --- Duplicates: the signed preview over HTTP ---------------------------------------------

def _preview(console, pair_id, action):
    return console.post(f"/admin/duplicates/{pair_id}/preview", data={"action": action})


def _signed(response) -> str:
    assert response.status_code == 200, response.text[:400]
    return re.search(r'name="token" value="([^"]+)"', response.text).group(1)


def _decisions(pg) -> tuple:
    with pg.cursor() as cur:
        cur.execute("SELECT count(*), max(decision_id) FROM event_duplicate_decisions")
        return cur.fetchone()


def test_the_duplicates_page_opens_a_preview_and_the_preview_writes_nothing(console, pg,
                                                                            two_clocks):
    case = two_clocks
    pair_id = case["pair"]["pair_id"]
    page = console.get("/admin/duplicates")
    assert f'action="/admin/duplicates/{pair_id}/preview"' in page.text
    assert f'action="/admin/duplicates/{pair_id}"' not in page.text, "no direct answer"
    before = _fingerprint(pg, case["day"])
    for action in (f"keep_{case['a']['event_id']}", f"keep_{case['b']['event_id']}",
                   "distinct"):
        preview = _preview(console, pair_id, action)
        assert preview.status_code == 200 and "Confirm" in preview.text
        assert _fingerprint(pg, case["day"]) == before
    assert _preview(console, pair_id, "keep_nonsense").status_code == 422
    assert _preview(console, 987654321, "distinct").status_code == 404


@pytest.mark.parametrize("answer", ["merge", "keep_separate"])
def test_a_confirmed_preview_is_recorded_once(console, pg, two_clocks, answer):
    case = two_clocks
    pair_id = case["pair"]["pair_id"]
    action = f"keep_{case['a']['event_id']}" if answer == "merge" else "distinct"
    token = _signed(_preview(console, pair_id, action))
    done = console.post(f"/admin/duplicates/{pair_id}", data={"action": action, "token": token,
                                                              "reason": "one night"},
                        follow_redirects=False)
    assert done.status_code == 303
    count = _decisions(pg)
    with pg.cursor() as cur:
        cur.execute("SELECT state, resolved_by FROM event_duplicate_pairs WHERE pair_id = %s",
                    (pair_id,))
        assert cur.fetchone() == (("MERGED" if answer == "merge" else "DISTINCT"), "tester")
        cur.execute("SELECT reviewer, reason FROM event_duplicate_decisions WHERE pair_id = %s",
                    (pair_id,))
        assert set(cur.fetchall()) == {("tester", "one night")}
    replay = console.post(f"/admin/duplicates/{pair_id}", data={"action": action,
                                                                "token": token},
                          follow_redirects=False)
    assert replay.status_code == 409 and DC.ALREADY_RESOLVED in replay.text
    assert _decisions(pg) == count
    again = _preview(console, pair_id, action)
    assert again.status_code == 409 and 'name="token"' not in again.text


def test_every_wrong_token_is_refused_and_writes_nothing(console, pg, two_clocks, monkeypatch):
    case = two_clocks
    pair_id = case["pair"]["pair_id"]
    keep_a, keep_b = f"keep_{case['a']['event_id']}", f"keep_{case['b']['event_id']}"
    merge = _signed(_preview(console, pair_id, keep_a))
    separate = _signed(_preview(console, pair_id, "distinct"))
    before = _fingerprint(pg, case["day"])
    url = f"/admin/duplicates/{pair_id}"
    refused = {
        "missing": ({"action": keep_a}, 422, DC.MISSING_PREVIEW_TOKEN),
        "forged": ({"action": keep_a, "token": merge[:-8] + "00000000"}, 422,
                   DC.INVALID_PREVIEW_TOKEN),
        "malformed": ({"action": keep_a, "token": "1.dead"}, 422, DC.INVALID_PREVIEW_TOKEN),
        "merge token for keep separate": ({"action": "distinct", "token": merge}, 422,
                                          DC.WRONG_ACTION_TOKEN),
        "keep separate token for merge": ({"action": keep_a, "token": separate}, 422,
                                          DC.WRONG_ACTION_TOKEN),
        "other event kept": ({"action": keep_b, "token": merge}, 409, DC.STALE_PREVIEW),
        "legacy switches": ({"action": keep_a, "force_merge": "1", "legacy_mode": "1"}, 422,
                            DC.MISSING_PREVIEW_TOKEN),
    }
    # The expired one: same facts, issued beyond the TTL.
    facts = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                       canonical_event_id=case["a"]["event_id"],
                                       reviewer="tester")["facts"]
    refused["expired"] = ({"action": keep_a, "token": DC.preview_token(
        PURPOSE, action="MERGE", subject=pair_id, facts=facts, reviewer="tester",
        now=clock.time() - DC.PREVIEW_TOKEN_TTL_SECONDS - 10)}, 409, DC.EXPIRED_PREVIEW)
    for name, (data, status, code) in refused.items():
        response = console.post(url, data=data, follow_redirects=False)
        assert response.status_code == status, (name, response.status_code)
        assert code in response.text, name
        assert _fingerprint(pg, case["day"]) == before, name
    other_pair = console.post(f"/admin/duplicates/{pair_id + 100000}",
                              data={"action": keep_a, "token": merge}, follow_redirects=False)
    assert other_pair.status_code == 422 and DC.WRONG_SUBJECT_TOKEN in other_pair.text
    # Another reviewer, with the first reviewer's preview.
    monkeypatch.setenv("ADMIN_USERNAME", "other")
    console.auth = ("other", "test-only")
    stolen = console.post(url, data={"action": keep_a, "token": merge}, follow_redirects=False)
    assert stolen.status_code == 422 and DC.INVALID_PREVIEW_TOKEN in stolen.text
    assert _fingerprint(pg, case["day"]) == before
    # A JSON body, without the console's form, opens nothing either.
    console.auth = ("tester", "test-only")
    monkeypatch.setenv("ADMIN_USERNAME", "tester")
    assert console.post(url, json={"action": keep_a}).status_code == 422
    assert _fingerprint(pg, case["day"]) == before


def test_the_duplicate_answer_needs_a_login_and_a_request_token(console, pg, two_clocks):
    pair_id = two_clocks["pair"]["pair_id"]
    token = _signed(_preview(console, pair_id, "distinct"))
    before = _fingerprint(pg, two_clocks["day"])
    url = f"/admin/duplicates/{pair_id}"
    assert console.post(url, data={"action": "distinct", "token": token},
                        auth=None).status_code == 401
    assert console.post(f"{url}/preview", data={"action": "distinct"},
                        auth=None).status_code == 401
    console.console_tokens = False
    assert console.post(url, data={"action": "distinct", "token": token}).status_code == 403
    assert console.post(f"{url}/preview", data={"action": "distinct"}).status_code == 403
    assert _fingerprint(pg, two_clocks["day"]) == before


def test_a_preview_goes_stale_when_what_it_rests_on_changes(pg, two_clocks):
    case = two_clocks
    pair_id = case["pair"]["pair_id"]

    def merge_preview():
        return duplicates.preview_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                          canonical_event_id=case["a"]["event_id"],
                                          reviewer="tester")

    token = merge_preview()["token"]
    with pg.cursor() as cur:      # the source re-extracted: the other event's start moved
        cur.execute("UPDATE events SET start_time = '21:30' WHERE event_id = %s",
                    (case["b"]["event_id"],))
    with pytest.raises(DC.DecisionRefused) as refused:
        duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                   canonical_event_id=case["a"]["event_id"], token=token,
                                   reviewer="tester")
    assert refused.value.code == DC.STALE_PREVIEW
    token = merge_preview()["token"]
    assert case["b"]["source_item_id"]
    with pg.cursor() as cur:      # the source itself was revised
        cur.execute("UPDATE source_items SET content_hash = 'revised' "
                    "WHERE source_item_id = %s", (case["b"]["source_item_id"],))
    with pytest.raises(DC.DecisionRefused) as refused:
        duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                   canonical_event_id=case["a"]["event_id"], token=token,
                                   reviewer="tester")
    assert refused.value.code == DC.STALE_PREVIEW
    assert _verdict_id(pg, case["b"]["event_id"]) is None
    fresh = merge_preview()["token"]
    done = duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                      canonical_event_id=case["a"]["event_id"], token=fresh,
                                      reviewer="tester")
    assert done["state"] == duplicates.MERGED


def test_an_old_token_is_dead_after_a_merge_and_its_revert(pg, two_clocks):
    case = two_clocks
    pair_id = case["pair"]["pair_id"]
    merge = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                       canonical_event_id=case["a"]["event_id"],
                                       reviewer="tester")["token"]
    separate = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DISTINCT,
                                          reviewer="tester")["token"]
    duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                               canonical_event_id=case["a"]["event_id"], token=merge,
                               reviewer="tester")
    with pytest.raises(DC.DecisionRefused) as refused:
        duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DISTINCT, token=separate,
                                   reviewer="tester")
    assert refused.value.code == DC.ALREADY_RESOLVED
    verdict = _verdict_id(pg, case["b"]["event_id"])
    preview = duplicates.preview_revert(pg, decision_id=verdict, reviewer="tester")
    duplicates.revert_decision(pg, decision_id=verdict, token=preview["token"],
                               reviewer="tester", reason="reopen")
    with pg.cursor() as cur:
        cur.execute("SELECT state FROM event_duplicate_pairs WHERE pair_id = %s", (pair_id,))
        assert cur.fetchone()[0] == duplicates.OPEN
    trail = _decisions(pg)
    for token, decision in ((merge, duplicates.DUPLICATE), (separate, duplicates.DISTINCT)):
        with pytest.raises(DC.DecisionRefused) as refused:
            duplicates.confirm_resolve(pg, pair_id, decision=decision, token=token,
                                       canonical_event_id=(case["a"]["event_id"]
                                                           if decision == duplicates.DUPLICATE
                                                           else None),
                                       reviewer="tester")
        assert refused.value.code == DC.STALE_PREVIEW, decision
    assert _decisions(pg) == trail, "the revert trail is kept and nothing is added"
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM event_duplicate_decisions WHERE pair_id = %s "
                    "AND decision = 'REVERT'", (pair_id,))
        assert cur.fetchone()[0] == 1


def test_a_merge_across_dates_is_never_previewable(pipe, corpus):
    """SEOUL TANGO WEEK's two events, put to the Duplicates page by hand, still
    cannot be merged: different dates, no token, nothing written."""
    low, high = sorted((corpus.ids["stw_miltang"], corpus.ids["stw_tangonow"]))
    with pipe.pg.cursor() as cur:
        cur.execute("INSERT INTO event_duplicate_pairs (event_id, other_event_id, rule) "
                    "VALUES (%s, %s, 'TEST') RETURNING pair_id", (low, high))
        pair_id = cur.fetchone()[0]
    preview = duplicates.preview_resolve(pipe.pg, pair_id, decision=duplicates.DUPLICATE,
                                         canonical_event_id=low, reviewer="tester")
    assert preview["blockers"] and preview["token"] is None
    assert "different dates" in preview["blockers"][0]
    with pytest.raises(DC.DecisionRefused):
        duplicates.confirm_resolve(pipe.pg, pair_id, decision=duplicates.DUPLICATE,
                                   canonical_event_id=low, token=_forge(pair_id),
                                   reviewer="tester")
    with pipe.pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM event_duplicate_decisions WHERE event_id = ANY(%s)",
                    ([low, high],))
        assert cur.fetchone()[0] == 0


def _forge(pair_id):
    return DC.preview_token(PURPOSE, action="MERGE", subject=pair_id, facts={}, reviewer="x")


def _fold(pg, event_id, into):
    with pg.cursor() as cur:
        cur.execute("UPDATE events SET canonical_event_id = %s, duplicate_decided_by = 'AUTO', "
                    "listing_state = 'HIDDEN' WHERE event_id = %s", (into, event_id))


def test_a_rule_fold_into_the_other_member_can_be_split_but_not_merged_again(pg, two_clocks):
    case = two_clocks
    pair_id = case["pair"]["pair_id"]
    a, b = case["a"]["event_id"], case["b"]["event_id"]
    _fold(pg, b, a)
    merge = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                       canonical_event_id=a, reviewer="tester")
    assert merge["token"] is None and "already merged" in merge["blockers"][0]
    split = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DISTINCT,
                                       reviewer="tester")
    assert split["blockers"] == []
    shown = {o["event_id"]: o for o in split["outlook"]}
    assert (shown[b]["canonical_before"], shown[b]["canonical_after"]) == (a, None)
    assert shown[b]["listing_after"] == "LISTED", "the preview shows the unfold"
    duplicates.confirm_resolve(pg, pair_id, decision=duplicates.DISTINCT,
                               token=split["token"], reviewer="tester")
    with pg.cursor() as cur:
        cur.execute("SELECT canonical_event_id, duplicate_decided_by, listing_state "
                    "FROM events WHERE event_id = %s", (b,))
        assert cur.fetchone() == (None, "HUMAN", "LISTED")


def test_a_fold_into_a_third_event_is_never_moved_by_an_answer(pg, two_clocks, store,
                                                               run_normalization, unique):
    case = two_clocks
    pair_id = case["pair"]["pair_id"]
    other = store.add(_id(unique, 17), name=f"Elsewhere {unique}", day=case["day"],
                      start="18:00", venue=f"Other hall {unique}")
    run_normalization()
    third = _event(pg, other)["event_id"]
    _fold(pg, case["b"]["event_id"], third)
    before = _fingerprint(pg, case["day"])
    for decision, keep in ((duplicates.DISTINCT, None),
                           (duplicates.DUPLICATE, case["a"]["event_id"])):
        preview = duplicates.preview_resolve(pg, pair_id, decision=decision,
                                             canonical_event_id=keep, reviewer="tester")
        assert preview["token"] is None and f"#{third}" in preview["blockers"][0]
    assert _fingerprint(pg, case["day"]) == before


def test_a_keep_must_be_one_of_the_pair(pg, two_clocks):
    pair_id = two_clocks["pair"]["pair_id"]
    preview = duplicates.preview_resolve(pg, pair_id, decision=duplicates.DUPLICATE,
                                         canonical_event_id=1, reviewer="tester")
    assert preview["token"] is None and "one of the pair" in preview["blockers"][0]


# --- truly parallel: independent connections on committed rows -------------------------

@pytest.fixture
def committed(pg):
    """Two events of one far-future night and their open pair, committed, so
    independent connections see them; everything is deleted afterwards."""
    from runtime import db
    from runtime.config import load_settings

    settings = load_settings()
    assert settings.postgres_db != "dancemate"
    tag = f"dc46-{clock.time_ns()}"
    day = date(2099, 1, 1) + timedelta(days=clock.time_ns() % 3000)
    made = {"events": [], "pairs": [], "candidates": []}
    with db.connect(settings, autocommit=True) as con:
        with con.cursor() as cur:
            for offset, start in ((0, "20:00"), (1, "21:00")):
                candidate = 9_460_000_000 + (clock.time_ns() % 1_000_000) * 10 + offset
                cur.execute(
                    "INSERT INTO events (candidate_id, event_name, event_date, start_time, "
                    "  identity_key, provenance) VALUES (%s, %s, %s, %s, %s, 'LIVE') "
                    "RETURNING event_id", (candidate, f"Night {tag}", day, start,
                                           f"{tag}-{offset}"))
                made["events"].append(cur.fetchone()[0])
                made["candidates"].append(candidate)
            cur.execute("INSERT INTO event_duplicate_pairs (event_id, other_event_id, rule) "
                        "VALUES (%s, %s, 'TEST_PARALLEL') RETURNING pair_id",
                        tuple(sorted(made["events"])))
            made["pairs"].append(cur.fetchone()[0])
    made.update(settings=settings, day=day)
    yield made
    with db.connect(settings, autocommit=True) as con:
        with con.cursor() as cur:
            cur.execute("DELETE FROM event_duplicate_decisions WHERE event_id = ANY(%s) "
                        "OR canonical_event_id = ANY(%s)", (made["events"], made["events"]))
            cur.execute("DELETE FROM event_duplicate_pairs WHERE event_id = ANY(%s) "
                        "OR other_event_id = ANY(%s)", (made["events"], made["events"]))
            cur.execute("DELETE FROM event_primary_source_history WHERE event_id = ANY(%s)",
                        (made["events"],))
            cur.execute("DELETE FROM human_review_actions WHERE candidate_id = ANY(%s)",
                        (made["candidates"],))
            cur.execute("DELETE FROM candidate_review_state WHERE candidate_id = ANY(%s)",
                        (made["candidates"],))
            cur.execute("DELETE FROM events WHERE event_id = ANY(%s)", (made["events"],))


def _race(settings, jobs):
    """Run each job on its own connection, released together; commit each
    that returns, roll back each that raises."""
    from runtime import db

    barrier = threading.Barrier(len(jobs))
    results: list = [None] * len(jobs)

    def run(index, job):
        with db.connect(settings) as con:
            barrier.wait()
            try:
                results[index] = ("ok", job(con))
                con.commit()
            except Exception as exc:  # noqa: BLE001 - the outcome is the result
                con.rollback()
                results[index] = ("refused", exc)

    threads = [threading.Thread(target=run, args=(i, j)) for i, j in enumerate(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not any(t.is_alive() for t in threads), "a worker hung (unhandled lock wait)"
    return results


def _state_of(settings, made):
    from runtime import db

    with db.connect(settings, autocommit=True) as con:
        with con.cursor() as cur:
            cur.execute("SELECT event_id, canonical_event_id, duplicate_decided_by, "
                        "listing_state FROM events WHERE event_id = ANY(%s) ORDER BY event_id",
                        (made["events"],))
            events = cur.fetchall()
            cur.execute("SELECT state FROM event_duplicate_pairs WHERE pair_id = %s",
                        (made["pairs"][0],))
            pair = cur.fetchone()[0]
            cur.execute("SELECT decision, count(*) FROM event_duplicate_decisions "
                        "WHERE event_id = ANY(%s) GROUP BY decision ORDER BY decision",
                        (made["events"],))
            decisions = dict(cur.fetchall())
    return events, pair, decisions


def _tokens(settings, made):
    from runtime import db

    low, high = sorted(made["events"])
    with db.connect(settings, autocommit=True) as con:
        return {
            "merge_low": duplicates.preview_resolve(con, made["pairs"][0],
                                                    decision=duplicates.DUPLICATE,
                                                    canonical_event_id=low,
                                                    reviewer="admin-a")["token"],
            "merge_low_b": duplicates.preview_resolve(con, made["pairs"][0],
                                                      decision=duplicates.DUPLICATE,
                                                      canonical_event_id=low,
                                                      reviewer="admin-b")["token"],
            "merge_high_b": duplicates.preview_resolve(con, made["pairs"][0],
                                                       decision=duplicates.DUPLICATE,
                                                       canonical_event_id=high,
                                                       reviewer="admin-b")["token"],
            "separate_b": duplicates.preview_resolve(con, made["pairs"][0],
                                                     decision=duplicates.DISTINCT,
                                                     reviewer="admin-b")["token"],
            "separate_a": duplicates.preview_resolve(con, made["pairs"][0],
                                                     decision=duplicates.DISTINCT,
                                                     reviewer="admin-a")["token"],
        }


def _confirm(made, decision, token, reviewer, keep=None):
    def job(con):
        return duplicates.confirm_resolve(con, made["pairs"][0], decision=decision,
                                          canonical_event_id=keep, token=token,
                                          reviewer=reviewer)
    return job


@pytest.mark.parametrize("race", ["merge_vs_merge", "merge_vs_other_merge",
                                  "merge_vs_keep_separate", "keep_separate_vs_merge"])
def test_two_admins_answering_at_once_leave_exactly_one_answer(committed, race):
    settings, made = committed["settings"], committed
    low, high = sorted(made["events"])
    t = _tokens(settings, made)
    jobs = {
        "merge_vs_merge": [_confirm(made, duplicates.DUPLICATE, t["merge_low"], "admin-a", low),
                           _confirm(made, duplicates.DUPLICATE, t["merge_low_b"], "admin-b",
                                    low)],
        "merge_vs_other_merge": [
            _confirm(made, duplicates.DUPLICATE, t["merge_low"], "admin-a", low),
            _confirm(made, duplicates.DUPLICATE, t["merge_high_b"], "admin-b", high)],
        "merge_vs_keep_separate": [
            _confirm(made, duplicates.DUPLICATE, t["merge_low"], "admin-a", low),
            _confirm(made, duplicates.DISTINCT, t["separate_b"], "admin-b")],
        "keep_separate_vs_merge": [
            _confirm(made, duplicates.DISTINCT, t["separate_a"], "admin-a"),
            _confirm(made, duplicates.DUPLICATE, t["merge_low_b"], "admin-b", low)],
    }[race]
    results = _race(settings, jobs)
    outcomes = sorted(r[0] for r in results)
    assert outcomes == ["ok", "refused"], results
    loser = next(r[1] for r in results if r[0] == "refused")
    assert isinstance(loser, DC.DecisionRefused), repr(loser)
    assert loser.code in (DC.ALREADY_RESOLVED, DC.STALE_PREVIEW, DC.CONCURRENT_DECISION)
    winner = next(r[1] for r in results if r[0] == "ok")
    events, pair, decisions = _state_of(settings, made)
    if winner["state"] == duplicates.MERGED:
        assert pair == "MERGED" and decisions == {"DUPLICATE": 1}
        folded = [e for e in events if e[1] is not None]
        assert len(folded) == 1 and folded[0][2:] == ("HUMAN", "HIDDEN")
        assert folded[0][1] in made["events"] and folded[0][1] != folded[0][0]
    else:
        assert pair == "DISTINCT" and decisions == {"DISTINCT": 2}
        assert all(e[1] is None and e[2] == "HUMAN" and e[3] == "LISTED" for e in events)


def test_a_revert_racing_an_old_merge_token_never_lets_it_through(committed):
    settings, made = committed["settings"], committed
    low, _ = sorted(made["events"])
    from runtime import db

    t = _tokens(settings, made)
    with db.connect(settings) as con:
        duplicates.confirm_resolve(con, made["pairs"][0], decision=duplicates.DUPLICATE,
                                   canonical_event_id=low, token=t["merge_low"],
                                   reviewer="admin-a")
        con.commit()
    with db.connect(settings, autocommit=True) as con:
        verdict = _verdict_id(con, max(made["events"]))
        revert = duplicates.preview_revert(con, decision_id=verdict, reviewer="admin-a")
    assert revert["blockers"] == []

    def do_revert(con):
        return duplicates.revert_decision(con, decision_id=verdict, token=revert["token"],
                                          reviewer="admin-a", reason="parallel")

    results = _race(settings, [do_revert, _confirm(made, duplicates.DUPLICATE,
                                                   t["merge_low_b"], "admin-b", low)])
    assert results[0][0] == "ok", results
    assert results[1][0] == "refused" and isinstance(results[1][1], DC.DecisionRefused)
    events, pair, decisions = _state_of(settings, made)
    assert pair == "OPEN" and all(e[1] is None for e in events)
    assert decisions == {"DUPLICATE": 1, "REVERT": 1}


def test_the_same_confirm_sent_twice_at_once_is_recorded_once(committed):
    settings, made = committed["settings"], committed
    t = _tokens(settings, made)
    job = _confirm(made, duplicates.DISTINCT, t["separate_a"], "admin-a")
    results = _race(settings, [job, job, job])
    assert sorted(r[0] for r in results) == ["ok", "refused", "refused"], results
    assert _state_of(settings, made)[2] == {"DISTINCT": 2}


def _review_job(settings, made, basis, action=review.CONFIRM, reviewer="admin-a"):
    def job(con):
        return DC.record_review(con, settings, candidate_id=made["candidates"][0],
                                action=action, basis=basis, reviewer=reviewer,
                                after={"start_time": "19:00"} if action == review.EDIT
                                else None)
    return job


def _review_count(settings, made):
    from runtime import db

    with db.connect(settings, autocommit=True) as con:
        with con.cursor() as cur:
            cur.execute("SELECT count(*) FROM human_review_actions WHERE candidate_id = %s",
                        (made["candidates"][0],))
            return cur.fetchone()[0]


def test_two_review_confirms_at_once_record_one(committed):
    settings, made = committed["settings"], committed
    from runtime import db

    with db.connect(settings, autocommit=True) as con:
        basis = DC.review_basis(con, settings, made["candidates"][0])
    results = _race(settings, [_review_job(settings, made, basis),
                               _review_job(settings, made, basis, reviewer="admin-b")])
    assert sorted(r[0] for r in results) == ["ok", "refused"], results
    loser = next(r[1] for r in results if r[0] == "refused")
    assert loser.code in (DC.STALE_REVIEW_STATE, DC.CONCURRENT_DECISION)
    assert _review_count(settings, made) == 1


def test_an_edit_waiting_on_a_re_extraction_is_refused_once_it_lands(committed):
    """The re-extraction holds the Event's row; the edit waits for it, then
    finds a basis that no longer holds and records nothing."""
    settings, made = committed["settings"], committed
    from runtime import db

    with db.connect(settings, autocommit=True) as con:
        basis = DC.review_basis(con, settings, made["candidates"][0])
    outcome = {}
    with db.connect(settings) as writer:
        with writer.cursor() as cur:
            cur.execute("UPDATE events SET start_time = '22:00' WHERE event_id = %s",
                        (made["events"][0],))

        def edit():
            with db.connect(settings) as con:
                try:
                    outcome["result"] = _review_job(settings, made, basis, review.EDIT)(con)
                    con.commit()
                except Exception as exc:  # noqa: BLE001
                    con.rollback()
                    outcome["error"] = exc

        thread = threading.Thread(target=edit)
        thread.start()
        clock.sleep(0.5)
        assert thread.is_alive(), "the edit waits for the row the re-extraction holds"
        writer.commit()
        thread.join(30)
    assert not thread.is_alive()
    assert isinstance(outcome.get("error"), DC.DecisionRefused), outcome
    assert outcome["error"].code == DC.STALE_REVIEW_STATE
    assert _review_count(settings, made) == 0
