"""v0.89.1 Community Discovery Reliability Patch: engine-level tests.

Two Production reviews of v0.89.0 found four trust problems: a "recent
activity" date that can really be a search-index/crawl date, not a real post
date; a stronger duplicate candidate hidden behind a weaker one that merely
has a lower item_id; no visible reason for a classification; and a review
queue with no evidence-quality ordering. This file locks in the fixes with
synthetic fixtures that reproduce the exact real-data patterns found during
those reviews (see module docstrings on cd.assess_activity/_duplicate_rank/
confirm_activity_evidence/mark_independent) - never against the real rows
themselves, and never against a real Naver/Kakao API.
"""

from __future__ import annotations

from datetime import date

import pytest

from runtime import master_data
from runtime import community_discovery as cd

TODAY = date(2026, 9, 14)


def hit(url, *, title="", snippet="", published=None, source_name=None, source_url=None,
        provider=cd.KAKAO, kind="cafe", query="살사 동호회", genre_hint="SALSA"):
    return cd.Hit(provider=provider, kind=kind, query=query, genre_hint=genre_hint, url=url,
                  title=title, snippet=snippet, published=published, source_name=source_name,
                  source_url=source_url)


@pytest.fixture
def six(pg):
    existing = {g["code"] for g in master_data.list_genres(pg)}
    for code in cd.TARGET_GENRES:
        if code not in existing:
            master_data.create_genre(pg, code=code, name=code.title())
    return {g["code"]: g["genre_id"] for g in master_data.list_genres(pg)}


def _items(pg, unique):
    return [i for i in cd.list_items(pg, limit=500)[0] if unique in i["identity_key"]]


# === 1. months_ago(): a calendar-month window, never a fixed day count ========================

def test_months_ago_clamps_to_a_real_day_in_a_shorter_month():
    # Aug 31 minus 6 months: Feb has no 31st, so the result is Feb 28 - never
    # a rollover into March (the doc example, since 2026 is not a leap year).
    assert cd.months_ago(date(2026, 8, 31), 6) == date(2026, 2, 28)
    # 2024 is a leap year: the clamp lands on Feb 29, not Feb 28.
    assert cd.months_ago(date(2024, 8, 31), 6) == date(2024, 2, 29)


@pytest.mark.parametrize("d, expected", [
    (date(2026, 9, 14), date(2025, 9, 14)),     # exactly 12 months back
    (date(2026, 1, 1), date(2025, 1, 1)),        # crosses a year boundary
])
def test_months_ago_twelve_months(d, expected):
    assert cd.months_ago(d, 12) == expected


@pytest.mark.parametrize("evidence_date, expected", [
    (date(2025, 9, 14), cd.ACTIVE),   # exactly 12 months ago: still inside the window
    (date(2025, 9, 13), cd.STALE),    # 12 months + 1 day: just outside
    (date(2025, 9, 15), cd.ACTIVE),   # 11 months 30 days: just inside
])
def test_the_twelve_month_window_boundary_is_exact(evidence_date, expected):
    hits = [hit("https://x.example/1", title=f"{evidence_date.isoformat()} 정모 안내")]
    assert cd.assess_activity(hits, TODAY).verdict == expected


# === 2. Activity date provenance: a text-embedded date beats a search-index one ===============

def test_a_provider_index_date_never_masks_an_older_real_post_date():
    """The exact failure a Production review found on a real candidate: the
    provider's own metadata date (when a search engine re-crawled/re-indexed
    the page) said today, but the post's own text carried a real, much older
    date. The stored activity_date must be the real one, not "today", and
    STALE must be reachable from it - never silently upgraded to ACTIVE."""
    hits = [hit("https://cafe.daum.net/old1/1", title="2024년 8월 정모 후기", published=TODAY)]
    result = cd.assess_activity(hits, TODAY)
    assert result.activity_date == date(2024, 8, 1)
    assert result.verdict == cd.STALE
    assert result.confidence == cd.INFERRED       # never CONFIRMED by an automated run


def test_a_real_community_with_no_dated_evidence_is_unverified_not_rejected():
    """A real group whose collected text names no date and no activity word
    at all is UNVERIFIED - not STALE (no date is known to be old) and never
    NOT_A_COMMUNITY (that classification is reserved for something that is
    plainly not a community; see test_stale_is_never_reclassified_as_not_a_
    community below for the kind-based half of this rule)."""
    hits = [hit("https://cafe.daum.net/quiet1/1", title="홍대 살사 동호회", snippet="")]
    result = cd.assess_activity(hits, TODAY)
    assert result.verdict == cd.UNVERIFIED
    assert result.activity_date is None
    assert result.confidence == cd.UNKNOWN_DATE


def test_a_confirmed_date_ages_into_stale_but_is_never_dropped():
    no_hits = [hit("https://x/1", title="사진")]
    kept = cd.assess_activity(no_hits, date(2028, 1, 1), previous_date=date(2026, 6, 1),
                              previous_confidence=cd.CONFIRMED)
    assert (kept.verdict, kept.activity_date, kept.confidence) == (cd.STALE, date(2026, 6, 1), cd.CONFIRMED)


# === 3. PostgreSQL: duplicate visibility, evidence actions, queues, manual review preservation =

@pytest.mark.postgres
def test_a_stale_real_community_is_never_reclassified_as_not_a_community(pg, unique, six):
    """대구 탱고카니발 (Production #291): a real, aging tango group looked
    NOT_A_COMMUNITY-worthy from a stale search snippet - it is STALE, a real
    community that has gone quiet, never something the classifier calls "not
    a community" just because it is old."""
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/tc{unique}/1", title="탱고 정모 안내",
                           source_name=f"탱고카니발{unique}", published=date(2024, 8, 26))],
                  ctx, None)
    [item] = _items(pg, unique)
    assert item["classification"] == cd.STALE
    assert item["kind"] == cd.KIND_COMMUNITY


@pytest.mark.postgres
def test_a_stronger_duplicate_is_never_hidden_behind_a_weaker_earlier_one(pg, unique, six, seoul_id):
    """스위티스윙: a weak candidate found first (so it holds the lower
    item_id and stays the anchor duplicate detection points at - Section 9
    keeps that mechanism exactly as it is) must never make a later, far
    stronger candidate for the same group invisible. Both stay visible in
    the same duplicate group, and the group's display order recommends the
    strong one first - never decided by item_id."""
    ctx = cd.load_context(pg, TODAY)
    name = f"스위티스윙{unique}"
    weak = hit(f"https://cafe.daum.net/weak{unique}/1", title="스윙", source_name=name)
    strong = hit(f"https://cafe.daum.net/strong{unique}/1", title="9월 정모 안내",
                published=date(2026, 9, 1), source_name=name, genre_hint="SWING")
    cd.store_hits(pg, [weak], ctx, None)
    cd.store_hits(pg, [strong], ctx, None)
    by_key = _items(pg, unique)
    weak_item = next(i for i in by_key if "weak" in i["identity_key"])
    strong_item = next(i for i in by_key if "strong" in i["identity_key"])
    assert weak_item["item_id"] < strong_item["item_id"]
    assert (strong_item["classification"], strong_item["duplicate_of_item_id"]) == \
        (cd.POSSIBLE_DUPLICATE, weak_item["item_id"])

    group = cd.duplicate_group(pg, weak_item["item_id"])
    assert {i["item_id"] for i in group} == {weak_item["item_id"], strong_item["item_id"]}
    assert group[0]["item_id"] == strong_item["item_id"]          # recommended first, not item_id order

    groups = cd.list_duplicate_groups(pg)
    assert any({i["item_id"] for i in g} == {weak_item["item_id"], strong_item["item_id"]} for g in groups)


@pytest.mark.postgres
def test_marking_two_candidates_independent_stops_future_auto_matching(pg, unique, six):
    ctx = cd.load_context(pg, TODAY)
    name = f"따로{unique}"
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/ia{unique}/1", title="살사", source_name=name)],
                  ctx, None)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/ib{unique}/1", title="9월 정모",
                           published=date(2026, 9, 1), source_name=name)], ctx, None)
    items = {("a" if "ia" in i["identity_key"] else "b"): i for i in _items(pg, unique)}
    assert items["b"]["classification"] == cd.POSSIBLE_DUPLICATE

    cd.mark_independent(pg, items["b"]["item_id"], reviewer="tester")
    refreshed = cd.get_item(pg, items["b"]["item_id"])
    assert refreshed["duplicate_cleared"] is True
    assert refreshed["classification"] != cd.POSSIBLE_DUPLICATE
    assert refreshed["duplicate_of_item_id"] is None
    assert cd.duplicate_group(pg, items["a"]["item_id"]) == []       # no longer grouped

    # A later run must not re-flag the pair against each other.
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/ib{unique}/1", title="9월 정모 갱신",
                           published=date(2026, 9, 2), source_name=name)], ctx, None)
    assert cd.get_item(pg, items["b"]["item_id"])["classification"] != cd.POSSIBLE_DUPLICATE


@pytest.mark.postgres
def test_confirming_evidence_only_ever_happens_through_an_explicit_admin_action(pg, unique, six):
    """Mirrors the ad hoc manual correction once applied to Production #291,
    now a reusable, audited action: an operator opens the real page and
    records what they actually found. review_state is left exactly where it
    was - confirming evidence is not the same decision as reopening a review.
    """
    ctx = cd.load_context(pg, TODAY)
    # Looks recently active from the provider's own metadata alone (no date
    # written in the post's own text) - exactly the shape of the real
    # Production case this action was built to correct.
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/ev{unique}/1", title="9월 정모 사진",
                           published=TODAY, source_name=f"탱고행사{unique}")], ctx, None)
    [seeded] = _items(pg, unique)
    assert (seeded["classification"], seeded["activity_date_confidence"]) == (cd.VERIFIED_NEW, cd.INFERRED)
    cd.set_review_state(pg, seeded["item_id"], cd.HELD, reviewer="tester")

    updated = cd.confirm_activity_evidence(
        pg, seeded["item_id"], activity_date="2024-08-26",
        evidence_url="https://cafe.daum.net/ev/notice/1", evidence_title="2024년 8월 정모 공지",
        reviewer="tester")
    assert updated["activity_date"] == date(2024, 8, 26)
    assert updated["activity_date_confidence"] == cd.CONFIRMED
    assert updated["classification"] == cd.STALE
    assert updated["review_state"] == cd.HELD                       # untouched by confirming evidence


@pytest.mark.postgres
def test_manual_review_decisions_survive_a_later_automated_run(pg, unique, six):
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/hold{unique}/1", title="살사",
                           source_name=f"보류중{unique}")], ctx, None)
    [seeded] = _items(pg, unique)
    cd.set_review_state(pg, seeded["item_id"], cd.HELD, reviewer="tester")
    assert cd.has_new_evidence(cd.get_item(pg, seeded["item_id"])) is False

    # A later run re-finds the same group - review_state must not move, and
    # the item should now show up as carrying new evidence since last_seen
    # (that run) moved past reviewed_at (the hold). Backdate reviewed_at
    # explicitly: everything in this test runs inside one uncommitted
    # transaction, where PostgreSQL's now() does not advance on its own.
    pg.execute("UPDATE community_discovery_items SET reviewed_at = now() - interval '1 day' "
              "WHERE item_id = %s", (seeded["item_id"],))
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/hold{unique}/1", title="10월 정모 공지",
                           published=date(2026, 10, 1), source_name=f"보류중{unique}")], ctx, None)
    after = cd.get_item(pg, seeded["item_id"])
    assert after["review_state"] == cd.HELD
    assert cd.has_new_evidence(after) is True


@pytest.mark.postgres
def test_register_and_link_group_registers_once_and_links_every_sibling(pg, unique, six, seoul_id):
    ctx = cd.load_context(pg, TODAY)
    name = f"대표선택{unique}"
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/repw{unique}/1", title="스윙", source_name=name)],
                  ctx, None)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/reps{unique}/1", title="9월 정모",
                           published=date(2026, 9, 1), source_name=name)], ctx, None)
    items = {("weak" if "repw" in i["identity_key"] else "strong"): i for i in _items(pg, unique)}
    result = cd.register_item_and_link_group(
        pg, items["strong"]["item_id"], {"name": name, "region_id": seoul_id, "enabled": "1"},
        [items["weak"]["item_id"]], reviewer="tester")
    assert result["linked"] == [items["weak"]["item_id"]]
    strong_after = cd.get_item(pg, items["strong"]["item_id"])
    weak_after = cd.get_item(pg, items["weak"]["item_id"])
    assert strong_after["review_state"] == cd.APPROVED
    assert weak_after["review_state"] == cd.LINKED
    assert weak_after["registered_community_id"] == strong_after["registered_community_id"] == \
        result["community"]["community_id"]


@pytest.mark.postgres
def test_region_unresolved_candidates_are_filterable(pg, unique, six):
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/nr{unique}/1", title="살사 동호회",
                           source_name=f"지역없음{unique}")], ctx, None)
    [seeded] = _items(pg, unique)
    assert seeded["region_id"] is None
    unresolved, _ = cd.list_items(pg, region=cd.REGION_UNRESOLVED, limit=500)
    resolved, _ = cd.list_items(pg, region="KR-SEOUL", limit=500)
    assert seeded["item_id"] in {i["item_id"] for i in unresolved}
    assert seeded["item_id"] not in {i["item_id"] for i in resolved}


@pytest.mark.postgres
def test_review_queues_slice_the_candidate_list(pg, unique, six):
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/qs{unique}/1", title="정모 안내",
                           published=date(2024, 1, 1), source_name=f"큐스테일{unique}")], ctx, None)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/qu{unique}/1", title="아무 사진",
                           source_name=f"큐확인{unique}")], ctx, None)
    stale_id = next(i["item_id"] for i in _items(pg, unique) if "qs" in i["identity_key"])
    unverified_id = next(i["item_id"] for i in _items(pg, unique) if "qu" in i["identity_key"])
    cd.set_review_state(pg, unverified_id, cd.REJECTED, reviewer="tester")

    stale_queue, _ = cd.list_items(pg, queue=cd.QUEUE_STALE, limit=500)
    unverified_queue, _ = cd.list_items(pg, queue=cd.QUEUE_UNVERIFIED, limit=500)
    rejected_queue, _ = cd.list_items(pg, queue=cd.QUEUE_REJECTED, limit=500)
    needs_review, _ = cd.list_items(pg, queue=cd.QUEUE_NEEDS_REVIEW, limit=500)
    assert stale_id in {i["item_id"] for i in stale_queue}
    assert stale_id not in {i["item_id"] for i in unverified_queue}
    assert unverified_id in {i["item_id"] for i in rejected_queue}
    assert unverified_id not in {i["item_id"] for i in needs_review}   # rejected, not pending/held
    assert stale_id in {i["item_id"] for i in needs_review}


@pytest.mark.postgres
def test_needs_review_orders_by_evidence_quality_not_item_id(pg, unique, six):
    """The candidate stored *first* (lower item_id, weaker evidence) must not
    outrank a later, confirmed-and-active candidate in the needs-review queue
    - Section 18."""
    ctx = cd.load_context(pg, TODAY)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/nqa{unique}/1", title="사진",
                           source_name=f"약함{unique}")], ctx, None)
    cd.store_hits(pg, [hit(f"https://cafe.daum.net/nqb{unique}/1", title="사진",
                           source_name=f"강함{unique}")], ctx, None)
    weak_id = next(i["item_id"] for i in _items(pg, unique) if "nqa" in i["identity_key"])
    strong_id = next(i["item_id"] for i in _items(pg, unique) if "nqb" in i["identity_key"])
    assert weak_id < strong_id
    cd.confirm_activity_evidence(pg, strong_id, activity_date="2026-09-01",
                                 evidence_title="9월 정모", reviewer="tester")

    queue, _ = cd.list_items(pg, queue=cd.QUEUE_NEEDS_REVIEW, limit=500)
    ids = [i["item_id"] for i in queue if unique in i["identity_key"]]
    assert ids.index(strong_id) < ids.index(weak_id)
