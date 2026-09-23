"""Salsa/Swing funnel reproduction (v0.91.0 PHASE 2).

Reproduces the *shape* of real production evidence (Daum Cafe search
snippets, SRC-D-010/011/012/020, 2026-09) without storing any verbatim post
body - same convention as test_social_dance.py. Each case pins one concrete
funnel outcome that was traced against the live engine SQLite store and the
production events table, so a future change that quietly regresses the
funnel shows up here instead of only in a production count.
"""

from src.classifier import classify, social_evidence
from src.extractor import extract_single
from src.live_pipeline import EVENT_CLASSIFICATIONS


# --- a clean salsa party: date + clock together -> promotes -----------------
#
# Real evidence (re-verified against the live production row 2026-09-15,
# `select body from source_items where source_item_id=2079`): SRC-D-011 item
# 2079 ("홍턴 추석 이벤트") body is "클럽 오픈 오후 8시 ... 워크샵+소셜
# 20,000원 / 소셜 12,000원 ... 9월 25일(금) | 추석 살사데이 ...". The date
# "9월 25일(금)" is verbatim in the stored body. But "오후 8시" (the club-open
# time) sits next to "DJ BLD & DJ 나리", not next to 소셜/파티, so
# social_evidence() (correctly) calls the two 소셜 mentions "merely
# mentioned" (they're prices, "워크샵+소셜 20,000원"), not an announcement -
# the post reads as CLASS and never reaches extraction (CLASS is deliberately
# excluded from EVENT_CLASSIFICATIONS - a lesson advert is not a night out).
# This case reproduces only the *shape* (paraphrased text, not the stored
# body) with the clock and the party word placed adjacent instead, which is
# the one difference that makes a post a real, promotable social.

def test_a_salsa_party_with_its_own_clock_promotes():
    title = "추석 살사 파티 안내"
    body = "9월 25일(금) 오후 8시 소셜 파티, 입장료 20,000원"
    classification = classify(title, body)
    assert classification == "SOCIAL"
    assert classification in EVENT_CLASSIFICATIONS
    candidate = extract_single(title, body, event_type=classification, published="2026-09-09")
    assert candidate.date == "2026-09-25"


# --- the same date is genuinely ambiguous without a clock --------------------
#
# Pins the real, currently-correct outcome for the 2079 shape itself: a class
# word plus a social word mentioned nowhere near a clock is CLASS, and CLASS
# never becomes a candidate. Not a bug - the post itself never announces a
# time for the social part, so nothing downstream should guess one.

def test_a_class_notice_that_only_mentions_a_social_stays_a_class():
    title = "9월 살사 기초완성반 모집"
    body = "8주 강습 프로그램입니다. 수업 후 회원들과 소셜도 즐길 수 있어요"
    assert social_evidence(title, body) is False
    classification = classify(title, body)
    assert classification == "CLASS"
    assert classification not in EVENT_CLASSIFICATIONS


# --- a swing social with a labelled but truncated venue ----------------------
#
# Real shape: SRC-D-012 item 186. The snippet is a Daum search result cut off
# mid-sentence right after "장소:", so the words that survive ("강습 인원",
# "class headcount") are a fragment of a later sentence, not a place. Before
# the v0.91.0 fix (engine/src/extraction_rules.py's truncation guard) this
# fragment was accepted as a venue and reached the events table
# (event_id 13668, venue_text="강습 인원"). The date and time are genuine -
# only the venue was false, so the fix must clear the venue without touching
# either.

def test_a_swing_class_with_a_social_and_a_cut_off_venue_has_no_false_venue():
    """The subject here is the truncation guard, not the classification.
    v0.96.10 reads this shape as the course it is - a title selling
    enrolment, a social that appears only beside a clock in the body - so
    the reading asserted below changed; the extractor is still handed the
    type it would have had, because the false venue must stay gone whatever
    the post turns out to be."""
    title = "린디베이직 강습 신청"
    body = "매주 토요일: 16:00~18:00 (소셜타임 18:00~22:00) 장소: 강습 인원..."
    assert classify(title, body) == "CLASS"
    candidate = extract_single(title, body, event_type="SOCIAL_WITH_CLASS",
                               published="2026-08-05")
    assert candidate.venue is None


# --- an announced swing social keeps working exactly as before --------------
#
# Real shape: SRC-D-010 item 2219, already correct in production (candidate
# id 1997: date 2026-09-16, time 20:15-22:15, no venue label at all). Pinned
# here so the v0.91.0 venue fix is proven not to touch a post that never had
# a "장소:" label to begin with.

def test_an_announced_swing_social_with_no_venue_label_is_unaffected():
    title = "■ 스윙타임빠 (9월 16일) 수 소셜 공지"
    body = "수요일 저녁 7시30분부터 소셜이 진행 됩니다. DJ 유광 PM 8:15~10:15"
    classification = classify(title, body)
    assert classification == "SOCIAL"
    candidate = extract_single(title, body, event_type=classification, published="2026-09-14")
    assert candidate.date == "2026-09-16"
    assert (candidate.start_time, candidate.end_time) == ("20:15", "22:15")
    assert candidate.venue is None
