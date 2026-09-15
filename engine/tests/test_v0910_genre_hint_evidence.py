"""Secondary-genre evidence (v0.91.0 PHASE 4/5, corrected placement).

Originally added as `runtime.normalization.detect_secondary_genre_hints()` -
a pure detector nothing ever called, flagged in PHASE 4 review as dead
production code. Moved here: `classifier.detect_genre_hints()` is wired into
`extractor.extract_single()`, which turns every hit into a real "genre_hint"
Evidence on the candidate. The engine's `evidences` table already stores any
field name (see `database.persist_events()`), so this is genuine, already-
tested persistence, not a detector whose output is discarded - see
runtime/normalization.py's git history (PHASE 4) and the PHASE 4/5 reports
for why storing it against a *second* events.genre_id is a separate, larger
change (migration 040) this does not attempt.
"""

from src.classifier import detect_genre_hints
from src.extractor import extract_single


def test_a_pure_salsa_post_has_no_genre_hint():
    assert detect_genre_hints(
        "금요소셜데이♡인천살사엘마르 금요정모 9월11일♡",
        "유나쌤의 올레벨 살사 트레이닝, 수업 후 이어지는 소셜에서도 행복 타임 되시길 바랍니다.",
    ) == set()


def test_salsa_and_bachata_named_together_is_detected():
    """Real production text, re-verified against SRC-D-020 item 2100's own
    title: "🌈인천 살사&바차타 엘마르🌈뉴엘마르 2주년 파티(9...". Registered
    today as a Salsa-only source; the Bachata mention has nowhere else to be
    recorded."""
    assert detect_genre_hints("🌈인천 살사&바차타 엘마르🌈뉴엘마르 2주년 파티(9...", "") == {"BACHATA"}


def test_swing_and_balboa_named_together_is_detected():
    """The real shape a Swing+Balboa community (e.g. SRC-D-012's own
    community row carries both genres) posts when a class explicitly
    teaches Balboa alongside Lindy."""
    hints = detect_genre_hints("스윙 강습 안내", "이번 학기는 린디합과 발보아를 함께 배웁니다")
    assert hints == {"BALBOA"}


def test_a_bare_swing_word_is_never_a_balboa_hint():
    """Balboa is a kind of swing dance, but "스윙" alone is the post's own
    primary genre, not evidence of a second one - only the dedicated word
    "발보아"/"balboa" counts."""
    assert detect_genre_hints("스윙 소셜 안내", "이번 주 스윙 소셜 진행합니다") == set()


def test_the_word_latin_alone_never_implies_a_specific_genre():
    assert detect_genre_hints(
        "라틴댄스 동호회 정기모임 안내", "라틴 음악에 맞춰 자유롭게 즐기는 시간입니다",
    ) == set()


def test_extract_single_attaches_a_real_genre_hint_evidence():
    """The integration point: a hint is not just detectable, it lands on the
    actual candidate a caller receives, using the same Evidence/evidences
    contract every other field (date/time/venue/fee) already relies on."""
    candidate = extract_single(
        "🌈인천 살사&바차타 엘마르🌈뉴엘마르 2주년 파티(9...", "",
        event_type="SOCIAL", published="2026-09-10",
    )
    genre_hints = [e for e in candidate.evidences if e.field == "genre_hint"]
    assert len(genre_hints) == 1
    assert genre_hints[0].value == "BACHATA"
    assert genre_hints[0].inference == "SECONDARY_GENRE_WORD"


def test_extract_single_attaches_no_genre_hint_when_none_is_named():
    candidate = extract_single(
        "금요소셜데이 정모", "이번 주도 즐거운 소셜 되세요", event_type="SOCIAL", published="2026-09-10",
    )
    assert [e for e in candidate.evidences if e.field == "genre_hint"] == []
