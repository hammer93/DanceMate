"""v0.80: is this usable to decide where to dance tonight?

Three questions, and none of them is "does the feature exist":

    can an operator find what to review, and does reviewing it change the site
    can a reader answer "today, Seoul, salsa" without knowing our vocabulary
    do we know whether anyone looked, without knowing who
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from runtime import (
    admin_pages,
    alpha_metrics,
    events_api,
    normalization,
    public,
    quality,
    review,
    source_ops,
)


# --- the review queue is about what is coming -------------------------------

def _row(**overrides):
    base = {
        "candidate_id": 1, "event_name": "밀롱가", "candidate_status": "POSSIBLE",
        "event_date": (events_api.today() + timedelta(days=14)).isoformat(),
        "start_time": "20:00", "venue": "PISTA", "fee": 13000,
        "review": {"review_state": "PENDING"}, "hints": [],
    }
    base.update(overrides)
    return base


def test_the_queue_opens_on_what_is_coming_not_on_everything():
    """A queue that opens on every row buries the handful that are tonight."""
    assert admin_pages.DEFAULT_REVIEW_FILTER == "upcoming"
    assert list(admin_pages.REVIEW_FILTERS)[:4] == [
        "upcoming", "today", "tomorrow", "week",
    ]


def test_a_past_event_is_not_in_the_upcoming_queue():
    past = _row(event_date=(events_api.today() - timedelta(days=3)).isoformat())
    assert admin_pages.REVIEW_FILTERS["upcoming"][1](past) is False
    assert admin_pages.REVIEW_FILTERS["all"][1](past) is True


@pytest.mark.parametrize("days,key", [(0, "today"), (1, "tomorrow"), (5, "week")])
def test_the_window_filters_select_their_window(days, key):
    row = _row(event_date=(events_api.today() + timedelta(days=days)).isoformat())
    assert admin_pages.REVIEW_FILTERS[key][1](row) is True


def test_the_missing_field_filters_only_offer_upcoming_work():
    """A missing fee on last month's milonga is not worth an afternoon."""
    past = _row(event_date=(events_api.today() - timedelta(days=2)).isoformat(),
                start_time=None, venue=None, fee=None)
    for key in ("unknown_time", "unknown_venue", "unknown_fee"):
        assert admin_pages.REVIEW_FILTERS[key][1](past) is False
    soon = _row(event_date=events_api.today().isoformat(),
                start_time=None, venue=None, fee=None)
    for key in ("unknown_time", "unknown_venue", "unknown_fee"):
        assert admin_pages.REVIEW_FILTERS[key][1](soon) is True


def test_how_close_an_event_is_gets_said_once():
    today = _row(event_date=events_api.today().isoformat())
    tomorrow = _row(event_date=(events_api.today() + timedelta(days=1)).isoformat())
    undated = _row(event_date=None)
    assert "오늘" in admin_pages._when_badge(today)
    assert "내일" in admin_pages._when_badge(tomorrow)
    assert "날짜 미확인" in admin_pages._when_badge(undated)


# --- a source decision is a person's, not the pipeline's ---------------------

def test_a_blocked_source_with_an_alternative_is_recommended_for_replacement():
    decision, reason = source_ops.recommend(
        {"enabled": True, "last_status": "PASS"},
        {"items": 21, "fetched": 0, "blocked": 21, "events": 0},
        alternatives=2,
    )
    assert decision == source_ops.REPLACE
    assert "21" in reason


def test_a_blocked_source_with_no_alternative_is_recommended_for_keeping():
    """Nothing else covers Busan swing. Dropping it would close the only door."""
    decision, reason = source_ops.recommend(
        {"enabled": True, "last_status": "PASS"},
        {"items": 22, "fetched": 0, "blocked": 22, "events": 0},
        alternatives=0,
    )
    assert decision == source_ops.KEEP
    assert "다른 소스가 없" in reason


def test_a_credential_failure_is_not_a_source_verdict():
    """Naver is failing for a reason outside this codebase."""
    decision, _ = source_ops.recommend(
        {"enabled": True, "last_status": "AUTH_FAILED"}, {"items": 0},
    )
    assert decision == source_ops.MONITOR


def test_a_working_source_is_active():
    decision, reason = source_ops.recommend(
        {"enabled": True, "last_status": "PASS"},
        {"items": 18, "fetched": 18, "blocked": 0, "events": 16},
    )
    assert decision == source_ops.ACTIVE
    assert "16" in reason


def test_an_unknown_decision_is_refused(pg, unique):
    from runtime import sources

    source = sources.create_source(
        pg, source_key=f"SRC-OP-{unique}", name=f"결정 테스트 {unique}",
        platform="DAUM_CAFE", source_role="COMMUNITY",
        url=f"https://cafe.daum.net/op{unique}", queries=["밀롱가"],
    )
    with pytest.raises(ValueError):
        source_ops.set_decision(pg, source["source_id"], "PROBABLY")


def test_recording_a_decision_does_not_stop_collection(pg, unique):
    """Writing down 'replace this' and actually stopping are two steps."""
    from runtime import sources

    source = sources.create_source(
        pg, source_key=f"SRC-OP2-{unique}", name=f"결정 테스트2 {unique}",
        platform="DAUM_CAFE", source_role="COMMUNITY",
        url=f"https://cafe.daum.net/op2{unique}", queries=["밀롱가"],
        enabled=False,
    )
    updated = source_ops.set_decision(
        pg, source["source_id"], source_ops.REPLACE, reviewer="kimpro",
        reason="대체 소스 있음",
    )
    assert updated["operational_decision"] == source_ops.REPLACE
    assert updated["decision_reason"] == "대체 소스 있음"
    assert updated["decided_by"] == "kimpro"
    assert updated["enabled"] is False  # unchanged either way


# --- what a reader is told ---------------------------------------------------

def test_freshness_reads_as_time_ago_while_it_is_recent():
    """A fixed, midday-Seoul `now` rather than the real wall clock: 2 real
    hours before whatever moment the suite happens to run at can land on the
    previous Seoul calendar day if that moment is within two hours of local
    midnight, which would make "2시간 전" correctly read as a date instead -
    a real, working `_checked_line()` behaviour that has nothing to do with
    what this test means to check."""
    noon_kst = datetime(2026, 9, 5, 12, 0, tzinfo=events_api.SEOUL)
    rendered = public._checked_line({
        "last_checked": (noon_kst - timedelta(hours=2)).isoformat(),
        "date": (events_api.today(noon_kst) + timedelta(days=3)).isoformat(),
    }, now=noon_kst)
    assert "2시간 전 확인" in rendered


def test_freshness_reads_as_a_date_once_it_is_no_longer_today():
    old = datetime.now(timezone.utc) - timedelta(days=3)
    rendered = public._checked_line({
        "last_checked": old.isoformat(),
        "date": (events_api.today() + timedelta(days=3)).isoformat(),
    })
    assert "전 확인" not in rendered
    assert "확인" in rendered


def test_the_alpha_notice_says_what_it_is_without_a_wall_of_disclaimer():
    footer = public._footer()
    assert "DanceMate Alpha" in footer
    assert "원문을 함께 확인" in footer
    assert len(footer) < 400


# --- counting views without counting people ---------------------------------

def test_nothing_in_the_view_log_could_identify_a_person():
    """The schema is the guarantee, not a policy anyone has to remember."""
    from pathlib import Path

    sql = Path("migrations/runtime/015_alpha_readiness.sql").read_text(encoding="utf-8")
    table = sql[sql.index("CREATE TABLE IF NOT EXISTS alpha_view_log"):]
    table = table[:table.index(");")].lower()
    for forbidden in ("ip", "session", "user_id", "cookie", "agent", "referrer",
                      "fingerprint", "device"):
        assert forbidden not in table, forbidden


@pytest.mark.parametrize("kind", list(alpha_metrics.KINDS))
def test_every_kind_has_a_label_an_operator_can_read(kind):
    assert alpha_metrics.LABELS[kind]


def test_an_unknown_kind_is_not_recorded(settings):
    assert alpha_metrics.record(settings, "SOMETHING_ELSE") is False


def test_recording_never_breaks_a_page(settings, monkeypatch):
    """A metrics table that can 500 a reader's evening is worse than none."""
    from runtime import db as db_module

    def explode(*args, **kwargs):
        raise db_module.DatabaseUnavailable("no database")

    monkeypatch.setattr(alpha_metrics.db, "connect", explode)
    assert alpha_metrics.record(settings, alpha_metrics.EVENT_LIST_VIEW) is False


# --- SQL ---------------------------------------------------------------------

def _live(pg, unique, suffix="1", **overrides):
    candidate = {
        "candidate_id": int(f"{unique[-6:]}{suffix}"),
        "post_id": 1,
        "source_url": f"https://cafe.daum.net/a80/{unique}-{suffix}",
        "event_name": f"알파 테스트 밀롱가 {unique}",
        "event_type": "MILONGA",
        "event_date": events_api.today().isoformat(),
        "start_time": "20:00", "end_time": "23:30", "end_day_offset": 0,
        "venue": f"알파홀 {unique}", "fee": 13000,
        "candidate_status": "POSSIBLE",
        "provenance": normalization.PROVENANCE_LIVE,
        "time_evidence": "EXPLICIT",
    }
    candidate.update(overrides)
    return normalization.normalize_candidate(pg, candidate)


def test_the_dashboard_buckets_match_what_the_search_returns(pg, unique):
    """Both draw from the same "a place to dance" definition - checked as the
    delta this test's own two rows cause, not as an absolute count against
    the live staging DB's total. A live board keeps accumulating real events
    (and the occasional real CANCELLED one) between test runs; scoping to the
    change this test itself made is what keeps that from ever flipping this
    test between pass and fail on its own.
    """
    before = {
        "today": quality.upcoming_buckets(pg)["today"],
        "tomorrow": quality.upcoming_buckets(pg)["tomorrow"],
    }
    before_served = {
        key: events_api.search(pg, when=key, limit=events_api.MAX_LIMIT)["total"]
        for key in ("today", "tomorrow")
    }

    _live(pg, unique, "1")
    _live(pg, unique, "2",
          event_date=(events_api.today() + timedelta(days=1)).isoformat())

    for key in ("today", "tomorrow"):
        bucket_delta = quality.upcoming_buckets(pg)[key] - before[key]
        served_delta = (
            events_api.search(pg, when=key, limit=events_api.MAX_LIMIT)["total"]
            - before_served[key]
        )
        assert bucket_delta == served_delta == 1, key


def test_the_coverage_matrix_shows_the_gaps(pg, unique, seoul_name):
    """'Salsa in Busan: 0' is a coverage gap no total can show."""
    _live(pg, unique, "1")
    matrix = quality.coverage_matrix(pg)
    assert matrix["genres"]
    assert seoul_name in matrix["regions"]
    for genre in matrix["genres"]:
        for region in matrix["regions"]:
            assert isinstance(matrix["grid"][genre].get(region, 0), int)


def test_a_review_correction_reaches_the_reader(pg, unique):
    """The whole point of a review queue: what a person fixes is what people see."""
    stored = _live(pg, unique, "1", start_time="07:30", time_evidence="ABSENT")
    before = events_api.get_event(pg, stored["event_id"])
    assert before["start_time"] == "07:30"

    review.record(
        pg, candidate_id=stored["candidate_id"], action=review.EDIT,
        reviewer="kimpro", before={"start_time": "07:30"},
        after={"start_time": "19:30", "venue": f"고친 장소 {unique}"},
        reason="게시글은 저녁이라고 적혀 있음",
    )
    state = review.state(pg, stored["candidate_id"])
    normalization.normalize_candidate(
        pg,
        {
            "candidate_id": stored["candidate_id"], "post_id": 1,
            "source_url": stored["source_url"],
            "event_name": stored["event_name"], "event_type": "MILONGA",
            "event_date": stored["event_date"].isoformat(),
            "start_time": "07:30", "end_time": "23:30", "end_day_offset": 0,
            "venue": f"알파홀 {unique}", "fee": 13000,
            "candidate_status": "POSSIBLE",
            "provenance": normalization.PROVENANCE_LIVE,
            "time_evidence": "ABSENT",
        },
        review_state=state,
    )
    after = events_api.get_event(pg, stored["event_id"])
    assert after["start_time"] == "19:30"
    assert after["venue"]["name"] == f"고친 장소 {unique}"
    assert after["human_reviewed"] is True
    # An edit is a person's word, not the engine's evidence gate.
    assert after["status"] != "VERIFIED"


def test_upcoming_yield_is_what_decides_whether_a_source_earns_its_requests(pg, unique):
    """A hundred past events and none upcoming is a source that has stopped
    being useful, and no total tells them apart."""
    from runtime import sources

    source = sources.create_source(
        pg, source_key=f"SRC-Y-{unique}", name=f"수확 테스트 {unique}",
        platform="DAUM_CAFE", source_role="COMMUNITY",
        url=f"https://cafe.daum.net/y{unique}", queries=["밀롱가"], enabled=True,
    )
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO source_items (source_id, external_id, url, title, content_hash) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING source_item_id",
            (source["source_id"], f"y-{unique}",
             f"https://cafe.daum.net/y{unique}/1/1", "밀롱가", f"hy-{unique}"),
        )
        item_id = cur.fetchone()[0]
    stored = _live(pg, unique, "9")
    with pg.cursor() as cur:
        cur.execute("UPDATE events SET source_item_id = %s WHERE event_id = %s",
                    (item_id, stored["event_id"]))

    assert source_ops.upcoming_yield(pg).get(source["source_id"]) == 1


def test_view_counts_are_aggregated_by_day_not_by_person(pg):
    before = alpha_metrics.summary(pg)["counts"][alpha_metrics.EVENT_LIST_VIEW]["today"]
    with pg.cursor() as cur:
        cur.execute("INSERT INTO alpha_view_log (kind) VALUES (%s)",
                    (alpha_metrics.EVENT_LIST_VIEW,))
    after = alpha_metrics.summary(pg)["counts"][alpha_metrics.EVENT_LIST_VIEW]["today"]
    assert after == before + 1


def test_the_source_redirect_only_follows_this_events_own_links(pg, unique, client):
    """An open redirect on a public page lends DanceMate's address to anyone."""
    stored = _live(pg, unique, "1")
    response = client.get(
        f"/events/{stored['event_id']}/source?to=https://evil.invalid/",
        follow_redirects=False,
    )
    assert response.status_code in (400, 404, 503)


@pytest.fixture
def client(env, monkeypatch):
    from fastapi.testclient import TestClient

    from runtime import app as app_module

    monkeypatch.setattr(app_module, "_settings", None)
    return TestClient(app_module.app, raise_server_exceptions=False)


def test_detail_status_row_does_not_repeat_the_kind_of_event():
    """The detail page has a 종류 field; the 상태 badge must not say it again."""
    event = {
        "event_type_label": "소셜 (강습 포함)",
        "status_label": "확인 필요",
        "status": "POSSIBLE",
    }
    assert "소셜 (강습 포함)" in public._status_line(event)
    assert "소셜 (강습 포함)" not in public._status_line(event, with_type=False)
    assert "확인 필요" in public._status_line(event, with_type=False)


def test_decision_route_is_not_swallowed_by_the_source_action_catch_all():
    """/admin/sources/{id}/decision must reach admin_source_decision.

    /admin/sources/{source_id}/{action} matches the same path. Starlette
    resolves in registration order, so the specific route has to come first --
    otherwise every recorded decision is a 404 from the catch-all.
    """
    from runtime import admin

    matching = [
        r for r in admin.router.routes
        if "POST" in (getattr(r, "methods", None) or set())
        and r.path in ("/admin/sources/{source_id}/decision",
                       "/admin/sources/{source_id}/{action}")
    ]
    assert [r.endpoint.__name__ for r in matching][0] == "admin_source_decision"


# --- the five human actions, end to end, on nothing real --------------------

def test_every_review_action_records_and_settles_a_synthetic_candidate(pg, unique):
    """APPROVE, EDIT, REJECT, DUPLICATE and CONFIRM on candidates nobody posted.

    Deliberately driven through review.record on the rolled-back fixture rather
    than through the HTTP route: the route opens its own connection and would
    commit, which is how test rows once reached the staging database. The five
    actions are the thing under test, not the transport.
    """
    from runtime import review

    base = int(unique[-6:]) * 100
    before = {
        "event_name": "합성 밀롱가", "event_date": "2026-12-31",
        "start_time": "20:00", "venue": "합성홀", "fee": 15000,
    }

    approved = review.record(pg, candidate_id=base + 1, action=review.APPROVE,
                             before=before)
    assert approved["action"] == review.APPROVE
    assert review.state(pg, base + 1)["review_state"] == \
        review.STATE_BY_ACTION[review.APPROVE]

    review.record(pg, candidate_id=base + 2, action=review.EDIT, before=before,
                  after={"start_time": "21:00"})
    edited = review.state(pg, base + 2)
    assert edited["corrected_json"]["start_time"] == "21:00"
    # The engine's own reading is not overwritten, only overlaid.
    assert review.apply_corrections(dict(before), edited)["start_time"] == "21:00"

    review.record(pg, candidate_id=base + 3, action=review.REJECT, before=before,
                  reason="행사가 아님")
    assert review.state(pg, base + 3)["review_state"] == \
        review.STATE_BY_ACTION[review.REJECT]

    review.record(pg, candidate_id=base + 4, action=review.DUPLICATE,
                  before=before, duplicate_of_candidate_id=base + 1)
    assert review.state(pg, base + 4)["duplicate_of_candidate_id"] == base + 1

    review.record(pg, candidate_id=base + 5, action=review.CONFIRM, before=before)
    assert review.state(pg, base + 5)["review_state"] == \
        review.STATE_BY_ACTION[review.CONFIRM]


def test_the_review_actions_that_must_refuse(pg, unique):
    """Each guard, so a mis-click cannot record a decision that means nothing."""
    from runtime import review

    base = int(unique[-6:]) * 100 + 50
    before = {"event_name": "합성 밀롱가", "start_time": "20:00"}

    with pytest.raises(review.ReviewError):
        review.record(pg, candidate_id=base, action="MAYBE", before=before)
    with pytest.raises(review.ReviewError):
        review.record(pg, candidate_id=base, action=review.DUPLICATE, before=before)
    with pytest.raises(review.ReviewError):
        review.record(pg, candidate_id=base, action=review.DUPLICATE, before=before,
                      duplicate_of_candidate_id=base)
    with pytest.raises(review.ReviewError):
        review.record(pg, candidate_id=base, action=review.EDIT, before=before)
    with pytest.raises(review.ReviewError):
        review.record(pg, candidate_id=base, action=review.EDIT, before=before,
                      after={"start_time": "20:00"})
