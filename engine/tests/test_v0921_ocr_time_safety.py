"""A poster's bare 9:10 is not evidence for a morning Event start."""

from src.extractor import extract_with_image_fallback


def test_ambiguous_bare_clock_on_poster_is_review_evidence_not_event_time():
    event = extract_with_image_fallback(
        "9/16 salsa social", "", event_type="SOCIAL", published="2026-09-10",
        image_texts=[("poster", "HA 9:10 ~ 12:00 입장료 10,000원")],
    )
    assert event.date == "2026-09-16"
    assert event.start_time is None
    assert event.end_time is None
    assert any(e.field == "context" and e.value == "IMAGE_TIME_AMBIGUOUS"
               for e in event.evidences)


def test_explicit_evening_poster_clock_still_fills_event_time():
    event = extract_with_image_fallback(
        "9/18 salsa party", "", event_type="SOCIAL", published="2026-09-10",
        image_texts=[("poster", "금요일 저녁 9:10~12:00")],
    )
    assert event.start_time == "21:10"
    assert event.end_time == "00:00"
