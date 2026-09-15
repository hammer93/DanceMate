"""Priced-party evidence bundle (v0.91.0 PHASE 4).

Root-cause fix for a real false negative: SRC-D-011 item 2079 ("홍턴 추석
이벤트") is a genuine Salsa social with its own priced admission and its own
door-opening time, but `social_evidence()`'s clock-adjacency rule (which
stays exactly as it was - see test_social_dance.py) correctly calls its two
소셜 mentions "merely mentioned" (they're prices: "워크샵+소셜 20,000원 /
소셜 12,000원"), because neither one sits next to a clock. That made a real
event fall into CLASS, which never reaches extraction. `party_evidence_bundle()`
(src/classifier.py) is a second, narrower kind of evidence: a specific day, a
named door/event opening, and a price tied directly to the social word,
required together. Each negative below pins one real reason a lesson advert
must NOT cross this bar.
"""

from src.classifier import classify, party_evidence_bundle
from src.extractor import extract_single
from src.live_pipeline import EVENT_CLASSIFICATIONS


# --- the real item, reproduced exactly from the read-only production copy --
#
# `select body from source_items where source_item_id = 2079` on production,
# re-verified 2026-09-15. No PII, no account/phone numbers - a public Daum
# Cafe search snippet, quoted verbatim (not paraphrased) because this is the
# specific false negative being fixed, not a general shape.

_ITEM_2079_TITLE = "홍턴 추석 이벤트"
_ITEM_2079_BODY = (
    "클럽 오픈 오후 8시 DJ BLD & DJ 나리 워크샵+소셜 20,000원 / 소셜 12,000원 "
    "🔥 9월 25일(금) | 추석 살사데이 라틴으로 더 풍성한 한가위! 오후 7시 핸슨 "
    "— 핸슨살사..."
)


def test_item_2079_now_classifies_as_a_real_social_with_class():
    """Before this fix: classify() returned CLASS and live_pipeline never
    built a candidate for this post at all (verified against the engine
    SQLite store: zero event_candidates rows for post_id 679, item 2079)."""
    classification = classify(_ITEM_2079_TITLE, _ITEM_2079_BODY)
    assert classification == "SOCIAL_WITH_CLASS"
    assert classification in EVENT_CLASSIFICATIONS
    assert party_evidence_bundle(_ITEM_2079_TITLE, _ITEM_2079_BODY) is True


def test_item_2079_extracts_a_real_upcoming_date_and_no_guessed_time():
    """The date is unambiguous (9월 25일(금), anchored to the post's own
    published_at) and must resolve. The post carries two different clocks for
    two different things ("클럽 오픈 오후 8시" and a second, separately
    introduced "오후 7시 핸슨" program) - genuinely ambiguous which one (if
    either) is the social's own start time, so extract_single() must not
    guess one; start_time stays None rather than silently picking either
    reading, exactly as a second, independent aggregator's 19:00 posting for
    the same event must never be assumed correct without the primary post's
    own unambiguous support."""
    candidate = extract_single(
        _ITEM_2079_TITLE, _ITEM_2079_BODY,
        event_type="SOCIAL_WITH_CLASS", published="2026-09-09",
        source_role="COMMUNITY",
    )
    assert candidate.date == "2026-09-25"
    assert candidate.start_time is None
    assert candidate.venue is None


# --- hard negatives: what must NOT cross the bar -----------------------------

def test_a_lesson_that_only_mentions_a_social_after_class_stays_a_class():
    """Real shape: SRC-D-011 item 2225 ("[일요일 강습 오픈] 강남역 뉴욕바,
    9/20~11/1..."), re-verified against production 2026-09-15. Names a date
    (9월 20일) and even uses the word "오픈" ("새 시즌 오픈합니다") - but it is
    a class's own season opening, not a club's or a party's, and the 소셜
    mention ("수업 후 쌤들과 소셜 및 정모 있어요") has no price anywhere near
    it. Must remain CLASS, unpromoted, exactly as production shows it today."""
    title = "[일요일 강습 오픈] 강남역 뉴욕바, 9/20~11/1, 6..."
    body = (
        "9월 20일 새 시즌 오픈합니다 살사 바차타 강남 라틴 댄스 동호회 많은 "
        "신청 부탁...분들 많이 소개해주세요 수업 후 쌤들과 소셜 및 정모 "
        "있어요 많은 신청 부탁드려요..."
    )
    assert party_evidence_bundle(title, body) is False
    classification = classify(title, body)
    assert classification == "CLASS"
    assert classification not in EVENT_CLASSIFICATIONS


def test_a_class_notice_with_no_day_level_date_stays_a_class():
    """Real shape: SRC-D-011 item 2078 ("[10월_강습 공지] ...토요반..."),
    re-verified against production 2026-09-15. Names only a month (10월), no
    day - the date gate in party_evidence_bundle() requires a specific day,
    the same requirement extractor.py's own candidate-acceptance gate
    enforces downstream, so this can never qualify no matter what else the
    text says."""
    title = "[10월_강습 공지] ✨살사 기초완성반 (토요반) - 쿠식..."
    body = (
        "재미있게 활용하고 싶은 분 3. 파트너와 함께 춤추는 즐거움과 자신감을 "
        "키우고 싶은 분 4. 소셜에서 부담 없이 살사를 즐길 수 있는 실전 감각을 "
        "익히고 싶은 분..."
    )
    assert party_evidence_bundle(title, body) is False
    assert classify(title, body) == "CLASS"


def test_a_season_ticket_priced_far_from_the_social_word_does_not_qualify():
    """The same distance discipline social_evidence() already applies: a
    price six words after the social word is a season ticket for it, not an
    admission fee to one specific night."""
    title = "타임빠 정기권 안내"
    body = "클럽 오픈 오후 8시 9월 20일 소셜의 입장을 할 수 있는 정기권입니다 3개월 단위 6만원"
    assert party_evidence_bundle(title, body) is False


def test_a_price_attached_to_the_workshop_not_the_social_does_not_qualify():
    """A door-open time and a date are real, but the only price is the
    workshop's own - the social is mentioned with nothing priced next to it,
    so this is still just a workshop advert that happens to also run a
    social, not a priced admission to one."""
    title = "워크샵 오픈 안내"
    body = "클럽 오픈 오후 8시 워크샵 30,000원 소셜도 있어요 9월 20일"
    assert party_evidence_bundle(title, body) is False
    assert classify(title, body) == "CLASS"


def test_a_class_or_season_opening_is_not_a_door_opening():
    """"시즌 오픈"/"강습 오픈"/"모집 오픈" all open a lesson round, never a
    club or a party - only 클럽/도어/파티 오픈 counts as this evidence."""
    for phrase in ("새 시즌 오픈합니다", "강습 오픈 안내", "모집 오픈"):
        body = f"{phrase} 9월 20일 소셜 20,000원"
        assert party_evidence_bundle("안내", body) is False


def test_open_ended_weekly_recurrence_never_qualifies():
    """No day-level date at all - "매주 토요일" is exactly the open-ended
    recurrence PHASE 2 already refuses to materialize into a single event,
    and this bundle must never manufacture one either."""
    body = "클럽 오픈 오후 8시 매주 토요일 소셜 20,000원"
    assert party_evidence_bundle("주말 소셜 안내", body) is False


def test_a_salsa_sauce_recipe_with_a_stray_price_and_date_is_still_not_a_class():
    """Food-salsa noise (PHASE 2 coverage) never has a class word at all, so
    it never reaches party_evidence_bundle() in the first place - classify()
    only calls it inside the `if has_class:` branch."""
    title = "홈메이드 살사소스 레시피 공유"
    body = "9월 20일 홈파티용 살사 소스 재료 15,000원 어치 구매했어요"
    assert classify(title, body) != "CLASS"
    assert classify(title, body) not in EVENT_CLASSIFICATIONS
