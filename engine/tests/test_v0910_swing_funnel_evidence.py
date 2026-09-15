"""Swing funnel reproduction (v0.91.0 PHASE 5).

Reproduces the *shape* of real production/live-web evidence without storing
verbatim post bodies where the source convention avoids that (test_social_
dance.py's own convention) - except where PHASE 2/4 already established a
short, non-sensitive real quote is the specific thing being regression-
tested (test_extraction_rules.py's own precedent for item 186).
"""

from src.classifier import classify, detect_genre_hints
from src.extractor import extract_single
from src.live_pipeline import EVENT_CLASSIFICATIONS


# --- SRC-D-010 item 2219: the first real upcoming Swing candidate -----------
#
# Re-verified against the live production row 2026-09-15
# (`select title, body from source_items where source_item_id = 2219`):
# FETCHED_FULL, full body available, already correct before and after every
# PHASE 2/4 change - used here as the "must never regress" pin.

_ITEM_2219_TITLE = "■ 스윙타임빠 (9월 16일) 수 소셜 공지"
_ITEM_2219_BODY = (
    "■ 스윙타임빠 (9월 16일) 수 소셜 공지 - 수요일 저녁 7시30분부터 소셜이 진행 됩니다. "
    "DJ \"유광\" PM 8:15~10:15 ■ 타임빠소셜 실시간 스트리밍 서비스 안내 수, 일요일 소셜은 "
    "스윙프렌즈 유튜브채널에서 실시간으로 현장을 보실수 있습니다. "
    "바로가기 : https://youtube.com/@Swingfriendslive"
)


def test_item_2219_is_a_real_upcoming_swing_social():
    classification = classify(_ITEM_2219_TITLE, _ITEM_2219_BODY)
    assert classification == "SOCIAL"
    assert classification in EVENT_CLASSIFICATIONS
    candidate = extract_single(
        _ITEM_2219_TITLE, _ITEM_2219_BODY,
        event_type=classification, published="2026-09-14", source_role="COMMUNITY",
    )
    assert candidate.date == "2026-09-16"
    assert (candidate.start_time, candidate.end_time) == ("20:15", "22:15")
    assert candidate.venue is None
    # No dedicated Balboa/Bachata/Kizomba word anywhere in this post - no
    # genre hint should fire just because the source's own community is
    # registered under Swing+Balboa.
    assert [e for e in candidate.evidences if e.field == "genre_hint"] == []


# --- SRC-D-012 item 186: the false venue must stay gone ---------------------
#
# Re-verified against the live production row 2026-09-15
# (`select title, body from source_items where source_item_id = 186`, and
# `select acquisition_status from source_item_content where source_item_id =
# 186` = FETCH_BLOCKED, so this METADATA_ONLY snippet is all the engine ever
# sees). Real, non-sensitive public search-snippet text, quoted verbatim -
# the same convention PHASE 2's own extraction_rules regression test used
# for this exact item.

_ITEM_186_TITLE = "Lv3.린디베이직💚 강습 신청"
_ITEM_186_BODY = (
    "대상: Lv.2 린디입문 과정 이수자 또는 스윙경력 4개월 이상 ✅ 강사 소개 🕺리더강사"
    "...5, 9/26) ⏰매주 토요일: 16:00~18:00 (소셜타임 18:00~22:00) 📍장소: 강습 인원..."
)


def test_item_186_is_a_social_with_class_and_why():
    """has_class=True ("강습" in the title/body) and social_evidence()=True:
    the class's own end time, "16:00~18:00", sits immediately before "(소셜
    타임 18:00~22:00)" - a clock directly followed by an announced social
    hour in the same parenthetical, which is exactly the "written next to
    its own clock" shape social_evidence() has recognised since PHASE 2,
    unrelated to and unchanged by the PHASE 4 priced-party bundle."""
    classification = classify(_ITEM_186_TITLE, _ITEM_186_BODY)
    assert classification == "SOCIAL_WITH_CLASS"
    assert classification in EVENT_CLASSIFICATIONS


def test_item_186_keeps_its_real_date_and_time_but_never_the_false_venue():
    candidate = extract_single(
        _ITEM_186_TITLE, _ITEM_186_BODY,
        event_type="SOCIAL_WITH_CLASS", published="2026-08-05", source_role="COMMUNITY",
    )
    assert candidate.date == "2026-09-26"
    assert (candidate.start_time, candidate.end_time) == ("16:00", "18:00")
    assert candidate.venue is None
    assert all(
        e.field != "venue" or "강습 인원" not in str(e.value)
        for e in candidate.evidences
    )


# --- BAL&HOP 2026: real live-fetched primary organizer evidence -------------
#
# Fetched live this phase via runtime.balnhop_discovery.discover() against
# https://balnhop.kr/ko (robots.txt absent -> allowed). title/body below are
# the real, verbatim `<title>`/`og:description` content returned by that
# real HTTP GET, 2026-09-15.

_BALNHOP_TITLE = "BAL&HOP 2026 - 9.18-20"
_BALNHOP_BODY = "All style swing dance festival in Korea"


def test_balnhop_gets_a_known_event_type_from_its_own_dedicated_page():
    """The page's own scrapable text (title + meta description) has no
    소셜/파티/class word at all - classify() would otherwise call this OTHER,
    same as any other brand-name-only page. known_event_type is the existing,
    already-established mechanism (PHASE 2/live_pipeline docstring: "Source
    Registry / known series context") for exactly this: a collector that
    knows, from the page's own dedicated single-purpose structure, what kind
    of page it is."""
    assert classify(_BALNHOP_TITLE, _BALNHOP_BODY) == "OTHER"
    assert classify(_BALNHOP_TITLE, _BALNHOP_BODY, known_event_type="SOCIAL") == "SOCIAL"


def test_balnhop_extracts_its_start_date_and_flags_the_multi_day_span():
    """"2026 - 9.18-20" resolves its first day (2026-09-18) from the
    explicit year written right next to the range - not from published_at,
    which balnhop_discovery.py leaves None (this page has no true
    publication timestamp; see its module docstring for why anchoring to
    crawl time instead was tried and reverted). The schema has no end-date
    column, so the full three-day span is never silently truncated to one
    day without a trace: a MULTI_DAY_EVENT context evidence names the real
    range for a human, the same discipline an ambiguous multi-program post
    already gets via MULTI_EVENT_CONTEXT."""
    candidate = extract_single(
        _BALNHOP_TITLE, _BALNHOP_BODY,
        event_type="SOCIAL", published=None, source_role="PRIMARY",
    )
    assert candidate.date == "2026-09-18"
    assert candidate.venue is None
    range_evidence = [e for e in candidate.evidences if e.value == "MULTI_DAY_EVENT"]
    assert len(range_evidence) == 1
    assert range_evidence[0].raw_text == "9.18-20"
    date_evidence = next(e for e in candidate.evidences if e.field == "date")
    assert date_evidence.inference == "EXPLICIT_YEAR"


def test_balnhop_still_reads_2026_even_if_crawled_in_a_later_real_year():
    """The exact fragility PHASE 7 review caught: this is an evergreen page.
    If it is still online in 2027 still showing "BAL&HOP 2026" in its own
    title, a crawl that happens in 2027 must not relabel 2026's own festival
    as 2027's - the year comes from the title text itself, never from when
    the page was fetched."""
    candidate = extract_single(
        _BALNHOP_TITLE, _BALNHOP_BODY,
        event_type="SOCIAL", published="2027-05-01", source_role="PRIMARY",
    )
    assert candidate.date == "2026-09-18"


def test_a_yearless_day_range_still_anchors_normally_with_real_context():
    """The general safety net this fix must not break: a post with no
    explicit year next to its own "m.d-d" range still resolves via the
    existing published_at anchor, same as any other bare date."""
    candidate = extract_single(
        "스윙 페스티벌 안내", "9.18-20 스윙 페스티벌이 열립니다",
        event_type="SOCIAL", published="2026-09-01",
    )
    assert candidate.date == "2026-09-18"


def test_a_truly_yearless_unanchored_day_range_stays_unresolved():
    """No year in the text, no published_at to anchor against - stays
    unresolved, the same existing safety contract every other bare date
    already has (never guess a year from nothing)."""
    candidate = extract_single(
        "스윙 페스티벌 안내", "9.18-20 스윙 페스티벌이 열립니다",
        event_type="SOCIAL", published=None,
    )
    assert candidate.date is None


def test_balnhop_never_claims_balboa_from_its_own_name_alone():
    """"BAL" in "BAL&HOP" stands for Balboa, but that is this project's own
    inference, not the page's own text - the fetched title/description never
    spells out "발보아"/"Balboa", so no genre_hint fires. Explicit evidence
    only, never inferred from the brand name or from "스윙" alone."""
    assert detect_genre_hints(_BALNHOP_TITLE, _BALNHOP_BODY) == set()


def test_a_swing_post_that_does_name_balboa_explicitly_gets_the_hint():
    """Contrast case: an explicit "발보아" mention (the real shape a Swing+
    Balboa community, e.g. SRC-D-012's own registered community genres,
    would post) does get flagged - explicit evidence, not inference."""
    candidate = extract_single(
        "9월 발보아 특강 안내", "린디합과 함께 발보아 기초를 배우는 시간입니다 9월 20일",
        event_type="CLASS", published="2026-09-01",
    )
    hints = [e for e in candidate.evidences if e.field == "genre_hint"]
    assert len(hints) == 1
    assert hints[0].value == "BALBOA"


def test_no_new_event_is_created_per_day_for_a_multi_day_range():
    """Guards against the exact anti-pattern PHASE 5 warns against: one
    extract_single() call on a ranged post must yield exactly one candidate,
    never three (one per day of "9.18-20")."""
    candidate = extract_single(
        _BALNHOP_TITLE, _BALNHOP_BODY,
        event_type="SOCIAL", published="2026-09-15", source_role="PRIMARY",
    )
    assert candidate.date == "2026-09-18"
    # extract_single() always returns a single EventCandidate, never a list -
    # the type itself is the guarantee; this asserts the one date claimed is
    # the range's start, not some other day inside it.
    assert candidate.date not in ("2026-09-19", "2026-09-20")
