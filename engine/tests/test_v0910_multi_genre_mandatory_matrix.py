"""PHASE 6 mandatory test matrix: the engine-layer half.

Genre attribution (Salsa/Bachata/Kizomba/Swing/Balboa) is a runtime concern
(source genre_id / event_genres / classifier.detect_genre_hints() - see
tests/test_v0910_multi_genre_public_filter.py and
engine/tests/test_v0910_genre_hint_evidence.py for the genre-attribution
half). classify()/extract_single() are genre-blind by design (PHASE 2's own
finding, unchanged) - what they own is whether a post announces a real,
dated social/workshop at all, which is what these cases pin.
"""

from src.classifier import classify, detect_genre_hints
from src.extractor import extract_single
from src.live_pipeline import EVENT_CLASSIFICATIONS


# --- SALSA / SALSA+BACHATA / SALSA+BACHATA+KIZOMBA parties -------------------

def test_a_salsa_party_is_a_real_event():
    title, body = "금요 살사 소셜 파티", "9월 5일 금요일 PM 9:00~2:00 DJ 안내"
    classification = classify(title, body)
    assert classification == "SOCIAL"
    candidate = extract_single(title, body, event_type=classification, published="2026-09-01")
    assert candidate.date == "2026-09-05"
    assert detect_genre_hints(title, body) == set()


def test_a_salsa_bachata_party_is_a_real_event_with_a_bachata_hint():
    title = "살사 바차타 소셜 파티 안내"
    body = "9월 20일 토요일 오후 8시 살사 바차타 함께 즐기는 소셜입니다"
    classification = classify(title, body)
    assert classification == "SOCIAL"
    candidate = extract_single(title, body, event_type=classification, published="2026-09-01")
    assert candidate.date == "2026-09-20"
    hints = [e for e in candidate.evidences if e.field == "genre_hint"]
    assert {e.value for e in hints} == {"BACHATA"}


def test_a_salsa_bachata_kizomba_party_gets_all_three_genre_evidence():
    title = "살사 바차타 키좀바 콤보 나이트"
    body = "살사, 바차타, 키좀바를 한 번에 즐기는 9월 20일 오후 8시 소셜 파티입니다"
    classification = classify(title, body)
    assert classification == "SOCIAL"
    candidate = extract_single(title, body, event_type=classification, published="2026-09-01")
    hints = {e.value for e in candidate.evidences if e.field == "genre_hint"}
    assert hints == {"BACHATA", "KIZOMBA"}


# --- SWING social / SWING+BALBOA ---------------------------------------------

def test_a_swing_social_is_a_real_event():
    title = "■ 스윙타임빠 (9월 16일) 수 소셜 공지"
    body = "수요일 저녁 7시30분부터 소셜이 진행 됩니다. DJ 데미안 PM 8:15~10:15"
    assert classify(title, body) == "SOCIAL"
    assert detect_genre_hints(title, body) == set()


def test_a_swing_balboa_class_gets_the_balboa_hint():
    title = "발보아 강습 안내"
    body = "9월 20일 발보아 기초를 배우는 시간입니다. 수업 후 소셜 20:00~22:00"
    classification = classify(title, body)
    assert classification == "SOCIAL_WITH_CLASS"
    candidate = extract_single(title, body, event_type=classification, published="2026-09-01")
    hints = {e.value for e in candidate.evidences if e.field == "genre_hint"}
    assert hints == {"BALBOA"}


# --- BACHATA workshop: precise about the CLASS-only policy -------------------
#
# The repository's actual, unchanged policy (PHASE 2/4): a standalone lesson
# advert is CLASS, and CLASS never reaches live_pipeline.EVENT_CLASSIFICATIONS
# - that boundary is not weakened here or anywhere in PHASE 6. What *does*
# cross it is the same evidence bundle PHASE 4 already built for exactly this
# shape: an explicit dated door/event-opening with a price on the social
# itself, alongside the class.

def test_a_bachata_workshop_enrollment_ad_alone_stays_a_class():
    title = "바차타 워크샵 수강생 모집"
    body = "8주 과정, 매주 화요일 저녁 진행합니다. 문의 주세요"
    classification = classify(title, body)
    assert classification == "CLASS"
    assert classification not in EVENT_CLASSIFICATIONS


def test_a_bachata_workshop_with_an_explicit_dated_party_announcement_is_an_event():
    """Same evidence bundle as the real Salsa fix (item 2079): a specific
    day, a named door/event opening, and a price on the social itself."""
    title = "바차타 워크샵 & 파티 안내"
    body = "클럽 오픈 오후 8시 워크샵+파티 25,000원 / 파티 15,000원 9월 20일"
    classification = classify(title, body)
    assert classification == "SOCIAL_WITH_CLASS"
    assert classification in EVENT_CLASSIFICATIONS
    candidate = extract_single(title, body, event_type=classification, published="2026-09-01")
    assert candidate.date == "2026-09-20"


# --- KIZOMBA social -----------------------------------------------------------

def test_a_kizomba_social_is_a_real_event_with_a_kizomba_hint():
    title = "키좀바 소셜 나이트"
    body = "9월 20일 토요일 저녁 8시 키좀바 소셜이 진행됩니다"
    classification = classify(title, body)
    assert classification == "SOCIAL"
    candidate = extract_single(title, body, event_type=classification, published="2026-09-01")
    hints = {e.value for e in candidate.evidences if e.field == "genre_hint"}
    assert hints == {"KIZOMBA"}


# --- provenance: news/secondary evidence, never promoted to organizer -------
#
# engine/src/models.py's own Evidence.source_role (default "SECONDARY") is
# the existing, already-used mechanism for this - every evidence row already
# carries whichever role the caller passed in; classify()/extract_single()
# never override it and never write anything resembling an "organizer" field
# (there is none in EventCandidate - runtime/admin.py's separate Organizers
# master-data page is not wired into event normalization, see the PHASE 5
# report). A news repost of a community's own party is exactly this shape:
# the aggregator/news post's own text may be the only thing collected, but
# it is stored as SECONDARY evidence, never as if the news outlet organized
# the party itself.

def test_a_news_repost_is_recorded_as_secondary_evidence_not_promoted():
    title, body = "홍대 살사 파티 소식", "이번 주 금요일 홍대에서 살사 파티가 열립니다 9월 20일"
    candidate = extract_single(
        title, body, event_type="SOCIAL", published="2026-09-01", source_role="SECONDARY",
    )
    assert candidate.evidences
    assert all(e.source_role == "SECONDARY" for e in candidate.evidences)


def test_an_external_ad_on_a_community_host_is_still_only_secondary_evidence():
    """An external promotion posted on someone else's board (PROMOTION_BOARD
    source_role, e.g. SRC-D-001/D-002) is not automatically that host's own
    event - the same source_role plumbing carries whatever the actual
    collector context says, never upgraded to PRIMARY by classify()/
    extract_single() themselves."""
    candidate = extract_single(
        "타 업체 홍보: 강남 살사 파티", "9월 20일 오후 8시 진행",
        event_type="SOCIAL", published="2026-09-01", source_role="SECONDARY",
    )
    assert all(e.source_role == "SECONDARY" for e in candidate.evidences)
