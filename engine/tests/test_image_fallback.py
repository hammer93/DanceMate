"""Image text fallback extraction (v0.81.3).

A poster image attached to a post often carries the date/time/fee the body
text never mentions. extract_with_image_fallback() reuses extract_single()
itself to read each image's already-OCR'd text as its own context - so
v0.81.2's Event Context Safety segmentation, the date year-safety rule, the
AM/PM ambiguity rule and the fee proximity rule all apply to image text
unchanged, with no separate parser. This file is the module doing no
fetching or OCR itself - image_texts here are plain strings standing in for
what the runtime would have already OCR'd and redacted.
"""

from __future__ import annotations

from datetime import date

from src.extractor import extract_single, extract_with_image_fallback, IMAGE_OCR
from src.verifier import verify


PUBLISHED = date(2026, 9, 1)


def _fields(ev) -> tuple:
    return (ev.date, ev.start_time, ev.end_time, ev.fee)


# --- 1-4: fallback fills a real gap -----------------------------------------

def test_missing_date_is_filled_from_the_image():
    ev = extract_with_image_fallback(
        "THE PISTA MILONGA", "19:30-23:30 장소: PISTA 입장료 13,000원",
        event_type="MILONGA", published=PUBLISHED,
        image_texts=[("img1", "9월 5일 THE PISTA MILONGA")],
    )
    assert ev.date == "2026-09-05"
    assert any(e.field == "date" and e.evidence_type == IMAGE_OCR for e in ev.evidences)


def test_missing_start_and_end_time_are_filled_from_the_image():
    ev = extract_with_image_fallback(
        "THE PISTA MILONGA", "9/5(토) 장소: PISTA 입장료 13,000원",
        event_type="MILONGA", published=PUBLISHED,
        image_texts=[("img1", "THE PISTA MILONGA 19:30~23:30")],
    )
    assert (ev.start_time, ev.end_time) == ("19:30", "23:30")
    assert any(e.field == "time" and e.evidence_type == IMAGE_OCR for e in ev.evidences)


def test_missing_fee_is_filled_from_the_image():
    ev = extract_with_image_fallback(
        "THE PISTA MILONGA", "9/5(토) 19:30-23:30 장소: PISTA",
        event_type="MILONGA", published=PUBLISHED,
        image_texts=[("img1", "THE PISTA MILONGA 입장료 13,000원")],
    )
    assert ev.fee == 13000
    assert any(e.field == "fee" and e.evidence_type == IMAGE_OCR for e in ev.evidences)


def test_all_three_missing_fields_are_filled_from_one_image():
    ev = extract_with_image_fallback(
        "THE PISTA MILONGA", "장소: PISTA",
        event_type="MILONGA", published=PUBLISHED,
        image_texts=[("img1", "THE PISTA MILONGA 9월 5일 19:30~23:30 입장료 13,000원")],
    )
    assert _fields(ev) == ("2026-09-05", "19:30", "23:30", 13000)


# --- 5-6: body value is never overwritten -----------------------------------

def test_body_value_is_not_overwritten_when_present():
    """Body says 20:00; the image's 19:30 must not replace it."""
    ev = extract_with_image_fallback(
        "THE PISTA MILONGA", "9/5(토) 20:00-23:30 장소: PISTA 입장료 13,000원",
        event_type="MILONGA", published=PUBLISHED,
        image_texts=[("img1", "THE PISTA MILONGA 19:30~23:30")],
    )
    assert ev.start_time == "20:00"


def test_a_conflicting_image_value_is_recorded_not_silently_dropped():
    """Date is missing (so the section-5 gate actually looks at the image);
    the image also names a time that disagrees with the body's own 20:00 -
    the body's time must stand, and the disagreement must not be silently
    dropped just because that field was not the one being filled."""
    ev = extract_with_image_fallback(
        "THE PISTA MILONGA", "20:00-23:30 장소: PISTA 입장료 13,000원",
        event_type="MILONGA", published=PUBLISHED,
        image_texts=[("img1", "THE PISTA MILONGA 9월 5일 19:30~23:00")],
    )
    assert ev.date == "2026-09-05"  # the gap the image was consulted for
    assert ev.start_time == "20:00"  # the body's own value, unchanged
    conflicts = [e for e in ev.evidences if e.value == "IMAGE_EVIDENCE_CONFLICT"]
    assert len(conflicts) == 1
    assert "time" in conflicts[0].raw_text


# --- 7: fields already complete never trigger image extraction -------------

def test_a_complete_body_never_consults_the_image():
    """Passing a garbage image_texts entry must have zero effect when the
    body already has date/time/fee - and, since nothing was consulted, no
    IMAGE_OCR evidence appears at all."""
    complete_body = "9/5(토) 20:00-23:30 장소: PISTA 입장료 13,000원"
    without = extract_single("THE PISTA MILONGA", complete_body,
                             event_type="MILONGA", published=PUBLISHED)
    with_image = extract_with_image_fallback(
        "THE PISTA MILONGA", complete_body, event_type="MILONGA", published=PUBLISHED,
        image_texts=[("img1", "9/6 완전히 다른 정보 99:99 100원")],
    )
    assert _fields(without) == _fields(with_image)
    assert not any(e.evidence_type == IMAGE_OCR for e in with_image.evidences)


def test_no_images_is_the_same_as_before_this_release():
    ev = extract_with_image_fallback(
        "THE PISTA MILONGA", "장소: PISTA", event_type="MILONGA",
        published=PUBLISHED, image_texts=None,
    )
    assert ev.date is None and ev.start_time is None and ev.fee is None


# --- 8-9: existing safety rules apply unchanged to image text --------------

def test_yearless_image_date_resolves_near_the_posts_own_year_not_today():
    """The same v0.80.2 rule, applied to an image: a poster's bare '9월 5일'
    must land near when the POST was written, never silently jumping to
    today's real-world year just because that is when OCR happened to run."""
    old_post = date(2020, 1, 1)
    ev = extract_with_image_fallback(
        "OLD MILONGA", "장소: PISTA 입장료 10,000원",
        event_type="MILONGA", published=old_post,
        image_texts=[("img1", "OLD MILONGA 9월 5일 19:30~23:00")],
    )
    assert ev.date == "2019-09-05"


def test_ambiguous_image_time_stays_uncertain_not_guessed_as_pm():
    """A bare '7:30' with no AM/PM marker in the image must not be silently
    turned into 19:30 - the same rule extract_single() already enforces."""
    ev = extract_with_image_fallback(
        "SOME SOCIAL", "장소: PISTA 입장료 10,000원 9/5",
        event_type="SOCIAL", published=PUBLISHED,
        image_texts=[("img1", "SOME SOCIAL 7:30")],
    )
    assert ev.start_time is None


# --- 10: multi-program image safety (v0.81.2 rule reused) ------------------

def test_a_multi_program_poster_image_does_not_mix_programs():
    """A poster with two programs (class + social) must not pair one
    program's time with the other's fee, exactly like a multi-program post
    body already does not."""
    ev = extract_with_image_fallback(
        "밀롱가 나잇", "장소: PISTA",
        event_type="SOCIAL", published=PUBLISHED,
        image_texts=[("img1",
            "1. 클래스 9월 5일 18:00-19:30 10,000원 "
            "2. 소셜 9월 5일 20:00-23:00 15,000원 소셜 안내입니다")],
    )
    # Whichever program's fields were taken, start_time and fee must agree
    # with each other (both program 1's, or both program 2's) - never mixed.
    if ev.start_time == "18:00":
        assert ev.fee != 15000
    elif ev.start_time == "20:00":
        assert ev.fee != 10000


# --- 11-12: image evidence is visible, distinctly provenanced --------------

def test_image_evidence_is_tagged_distinctly_from_text_evidence():
    ev = extract_with_image_fallback(
        "THE PISTA MILONGA", "장소: PISTA",
        event_type="MILONGA", published=PUBLISHED,
        image_texts=[("https://example.test/poster.jpg",
                       "THE PISTA MILONGA 9월 5일 19:30~23:30 입장료 13,000원")],
    )
    image_evidences = [e for e in ev.evidences if e.evidence_type == IMAGE_OCR]
    assert image_evidences
    assert all(e.inference == "https://example.test/poster.jpg" for e in image_evidences)


def test_text_evidence_from_the_body_is_unaffected_by_image_fallback():
    ev = extract_with_image_fallback(
        "THE PISTA MILONGA", "9/5(토) 장소: PISTA",
        event_type="MILONGA", published=PUBLISHED,
        image_texts=[("img1", "19:30~23:30 입장료 13,000원")],
    )
    date_evidence = next(e for e in ev.evidences if e.field == "date")
    assert date_evidence.evidence_type == "TEXT"


# --- 13-14: image-only fill must never reach VERIFIED (false VERIFIED=0) ---

def test_all_three_fields_from_image_alone_never_reaches_verified():
    ev = extract_with_image_fallback(
        "THE PISTA MILONGA", "장소: PISTA",
        event_type="MILONGA", published=PUBLISHED,
        image_texts=[("img1", "THE PISTA MILONGA 9월 5일 19:30~23:30 입장료 13,000원")],
    )
    verify(ev, source_role="PRIMARY")
    assert ev.core_complete is False
    assert ev.status != "VERIFIED"


def test_text_only_complete_event_still_reaches_verified_unchanged():
    """The image-fallback change must not regress the ordinary VERIFIED path."""
    ev = extract_with_image_fallback(
        "THE PISTA MILONGA", "9/5(토) 19:30-23:30 장소: PISTA 입장료 13,000원",
        event_type="MILONGA", published=PUBLISHED, image_texts=None,
    )
    verify(ev, source_role="PRIMARY")
    assert ev.core_complete is True
    assert ev.status == "VERIFIED"


def test_a_mix_of_text_and_image_fields_still_withholds_verified():
    """Date and venue from the body, time and fee from the image: complete,
    but not entirely text-evidenced, so still not VERIFIED."""
    ev = extract_with_image_fallback(
        "THE PISTA MILONGA", "9/5(토) 장소: PISTA",
        event_type="MILONGA", published=PUBLISHED,
        image_texts=[("img1", "19:30~23:30 입장료 13,000원")],
    )
    verify(ev, source_role="PRIMARY")
    assert _fields(ev) == ("2026-09-05", "19:30", "23:30", 13000)
    assert ev.core_complete is False
