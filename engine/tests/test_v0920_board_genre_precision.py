"""A Community's generic class introduction is not Event genre evidence."""

from src.extractor import extract_single


def _hints(candidate):
    return {e.value for e in candidate.evidences if e.field == "genre_hint"}


def test_salsa_only_class_does_not_inherit_generic_bachata_intro():
    candidate = extract_single(
        "10/3 살사 기초완성반 개강",
        "라틴속으로는 다양한 살사·바차타 강습을 엽니다. "
        "이번에 안내드릴 수업은 살사 기초완성반입니다.",
        event_type="CLASS", published="2026-09-09",
    )
    assert candidate.date == "2026-10-03"
    assert _hints(candidate) == set()


def test_combined_class_title_is_positive_multi_genre_evidence():
    candidate = extract_single(
        "10/3 살사&바차타 통합반 개강", "10월 3일 수업 시작",
        event_type="CLASS", published="2026-09-09",
    )
    assert _hints(candidate) == {"BACHATA"}


def test_party_body_can_still_supply_explicit_second_genre():
    candidate = extract_single(
        "10/3 살사 파티", "살사와 바차타를 함께 즐기는 소셜입니다.",
        event_type="SOCIAL", published="2026-09-09",
    )
    assert _hints(candidate) == {"BACHATA"}
