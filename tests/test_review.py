"""Human Verification Console: the five actions, and what they must not do.

The line these defend: a person's decision is recorded *alongside* the
Information Engine's status, never instead of it. APPROVE does not grant
VERIFIED, and nothing here writes to the engine's store.
"""

from __future__ import annotations

import pytest

from runtime import review

CANDIDATE = {
    "event_name": "9/5 THE PISTA MILONGA",
    "event_date": "2026-09-05",
    "start_time": None,
    "end_time": None,
    "venue": "PISTA",
    "fee": None,
}


# --- vocabulary (pure) ------------------------------------------------------

def test_the_five_actions_are_exactly_the_documented_ones():
    assert set(review.ACTIONS) == {"APPROVE", "EDIT", "REJECT", "DUPLICATE", "CONFIRM"}


def test_each_action_maps_to_a_review_state():
    for action in review.ACTIONS:
        assert action in review.STATE_BY_ACTION


def test_cancelled_candidates_are_not_queued_for_review():
    """The engine has settled them; re-queueing buries what needs attention."""
    assert "CANCELLED" not in review.REVIEWABLE_ENGINE_STATUSES
    assert "VERIFIED" not in review.REVIEWABLE_ENGINE_STATUSES
    assert set(review.REVIEWABLE_ENGINE_STATUSES) == {
        "POSSIBLE", "EXPECTED", "CONFLICT", "UNKNOWN"
    }


def test_editable_fields_are_the_decision_fields():
    for field in ("event_name", "event_date", "start_time", "end_time", "venue", "fee"):
        assert field in review.EDITABLE_FIELDS


def test_review_never_writes_to_the_engine():
    """A human decision must not mutate the engine's own candidate store."""
    import inspect

    source = inspect.getsource(review)
    for forbidden in ("sqlite3", "event_candidates", "engine_db", "persist_events"):
        assert forbidden not in source, forbidden


def test_corrections_are_overlaid_without_losing_the_engine_value():
    merged = review.apply_corrections(
        dict(CANDIDATE), {"corrected_json": {"start_time": "20:00", "venue": "홍대 PISTA"}}
    )
    assert merged["start_time"] == "20:00"
    assert merged["venue"] == "홍대 PISTA"
    assert merged["engine_venue"] == "PISTA", "the engine's value must still be visible"
    assert set(merged["corrected_fields"]) == {"start_time", "venue"}


def test_no_corrections_leaves_the_candidate_untouched():
    merged = review.apply_corrections(dict(CANDIDATE), {"corrected_json": {}})
    assert merged == CANDIDATE


# --- database-backed --------------------------------------------------------

@pytest.fixture
def candidate_id(unique) -> int:
    # Well outside any real engine candidate id.
    return 900000 + int(unique[-4:])


def test_a_new_candidate_is_pending(pg, candidate_id):
    assert review.state(pg, candidate_id)["review_state"] == review.PENDING


def test_approve_is_recorded_and_does_not_claim_verified(pg, candidate_id):
    review.record(pg, candidate_id=candidate_id, action=review.APPROVE,
                  before=CANDIDATE, reason="looks usable")
    state = review.state(pg, candidate_id)
    assert state["review_state"] == "APPROVED"
    assert state["last_action"] == review.APPROVE
    assert state["review_state"] != "VERIFIED", "APPROVE is not VERIFIED"


def test_confirm_is_recorded(pg, candidate_id):
    review.record(pg, candidate_id=candidate_id, action=review.CONFIRM)
    assert review.state(pg, candidate_id)["review_state"] == "CONFIRMED"


def test_edit_keeps_both_versions(pg, candidate_id):
    review.record(
        pg, candidate_id=candidate_id, action=review.EDIT,
        before=CANDIDATE, after={"start_time": "20:00", "fee": "13000"},
        reason="times are in the body",
    )
    actions = review.history(pg, candidate_id)
    assert len(actions) == 1
    assert actions[0]["before_json"]["venue"] == "PISTA"
    assert actions[0]["after_json"] == {"start_time": "20:00", "fee": "13000"}

    state = review.state(pg, candidate_id)
    assert state["review_state"] == "EDITED"
    assert state["corrected_json"] == {"start_time": "20:00", "fee": "13000"}


def test_edits_accumulate_across_actions(pg, candidate_id):
    review.record(pg, candidate_id=candidate_id, action=review.EDIT,
                  before=CANDIDATE, after={"start_time": "20:00"})
    review.record(pg, candidate_id=candidate_id, action=review.EDIT,
                  before=CANDIDATE, after={"venue": "홍대 PISTA"})
    corrected = review.state(pg, candidate_id)["corrected_json"]
    assert corrected == {"start_time": "20:00", "venue": "홍대 PISTA"}


def test_edit_needs_an_actual_change(pg, candidate_id):
    with pytest.raises(review.ReviewError, match="at least one corrected field"):
        review.record(pg, candidate_id=candidate_id, action=review.EDIT,
                      before=CANDIDATE, after={})


def test_reject_records_but_deletes_nothing(pg, candidate_id):
    review.record(pg, candidate_id=candidate_id, action=review.EDIT,
                  before=CANDIDATE, after={"venue": "X"})
    review.record(pg, candidate_id=candidate_id, action=review.REJECT,
                  before=CANDIDATE, reason="advertisement, not an event")

    assert review.state(pg, candidate_id)["review_state"] == "REJECTED"
    actions = review.history(pg, candidate_id)
    assert len(actions) == 2, "the earlier action must survive a rejection"
    assert {a["action"] for a in actions} == {review.EDIT, review.REJECT}


def test_duplicate_links_to_another_candidate(pg, candidate_id):
    other = candidate_id + 1
    review.record(pg, candidate_id=candidate_id, action=review.DUPLICATE,
                  duplicate_of_candidate_id=other, reason="same milonga")
    state = review.state(pg, candidate_id)
    assert state["review_state"] == "DUPLICATE"
    assert state["duplicate_of_candidate_id"] == other


def test_duplicate_needs_a_target(pg, candidate_id):
    with pytest.raises(review.ReviewError, match="needs the candidate"):
        review.record(pg, candidate_id=candidate_id, action=review.DUPLICATE)


def test_a_candidate_cannot_duplicate_itself(pg, candidate_id):
    with pytest.raises(review.ReviewError, match="cannot be a duplicate of itself"):
        review.record(pg, candidate_id=candidate_id, action=review.DUPLICATE,
                      duplicate_of_candidate_id=candidate_id)


def test_an_unknown_action_is_refused(pg, candidate_id):
    with pytest.raises(review.ReviewError, match="unknown action"):
        review.record(pg, candidate_id=candidate_id, action="DELETE")


def test_the_audit_trail_records_who_and_when(pg, candidate_id):
    review.record(pg, candidate_id=candidate_id, action=review.APPROVE, reviewer="admin")
    action = review.history(pg, candidate_id)[0]
    assert action["reviewer"] == "admin"
    assert action["created_at"] is not None
    assert action["candidate_id"] == candidate_id


def test_action_count_increments(pg, candidate_id):
    for _ in range(3):
        review.record(pg, candidate_id=candidate_id, action=review.CONFIRM)
    assert review.state(pg, candidate_id)["action_count"] == 3


def test_metrics_count_today_by_action(pg, candidate_id):
    before = review.metrics(pg)["today"][review.APPROVE]
    review.record(pg, candidate_id=candidate_id, action=review.APPROVE)
    after = review.metrics(pg)
    assert after["today"][review.APPROVE] == before + 1
    assert set(after["today"]) == set(review.ACTIONS)


def test_states_are_fetched_in_one_query(pg, candidate_id):
    review.record(pg, candidate_id=candidate_id, action=review.APPROVE)
    found = review.states(pg, [candidate_id, candidate_id + 5000])
    assert candidate_id in found
    assert found[candidate_id]["review_state"] == "APPROVED"
