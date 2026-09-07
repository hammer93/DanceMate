"""v0.84.4: image-aware event classification.

process_discovered_post() used to call classify(title, body) - title and
body alone - before ever looking at a post's image_texts. A poster image
carrying every field the extractor needs is useless if the post never
clears the classification gate in the first place: an image-only K-TANGO
post (empty body) always classified OTHER and returned events=[] regardless
of how good its poster's OCR text was, wiring or no wiring (see v0.84.3's
own incident write-up in RELEASE_NOTES.md for how this was found).

This is not "hand image_texts to classify() too." classify_with_image_
evidence() (src/classifier.py) adds a second, independent, stricter layer
on top of the runtime's own trust gate (image_fallback.
gather_trusted_classification_texts() - a real poster candidate, OCR
succeeded, not a logo/nav asset, enough text to mean something):

  * only engages when the body itself was too thin to have decided anything
    (Section 12 - a text-rich OTHER stays OTHER, always)
  * requires the image to carry social/milonga context AND a date AND
    (a start time or a LABEL-tagged venue) - never a bare keyword
    (Section 9)
  * a poster naming more than one distinct date never promotes anything
    (Section 15)
  * an image whose text is only strong enough for CLASS (lesson/workshop,
    no social evidence) never promotes a milonga/social event (Section 14)

This file tests classify_with_image_evidence() directly (the classification
layer) and process_discovered_post() end to end (classification + the
image-field-fallback extraction that was already correct since v0.81.3/
v0.84.3, wired together, with the resulting event's own safety: OCR-only
evidence must never reach VERIFIED).
"""

from __future__ import annotations

from datetime import date

from src.classifier import classify, classify_with_image_evidence
from src.live_pipeline import process_discovered_post, EVENT_CLASSIFICATIONS
from src.extractor import IMAGE_OCR


PUBLISHED = date(2026, 9, 1)


class _Post:
    def __init__(self, title, body, published_at=PUBLISHED,
                acquisition_quality="FULL", known_event_type=None):
        self.title = title
        self.body = body
        self.published_at = published_at
        self.acquisition_quality = acquisition_quality
        self.known_event_type = known_event_type


# --- A: normal text-rich milonga - image must never be consulted -----------

def test_a_text_rich_post_classifies_from_body_alone_image_ignored():
    body = "9/5(토) 밀롱가 19:30-23:30 장소: PISTA 입장료 13,000원"
    without_image = classify("탱고의 밤", body)
    with_decoy_image = classify_with_image_evidence(
        "탱고의 밤", body, published=PUBLISHED,
        # A decoy that, if ever consulted, would win on its own: real
        # milonga signal with a different date/venue than the body's.
        trusted_image_texts=[("decoy.jpg",
            "8/1(토) 밀롱가 20:00-24:00 장소: OCHO 입장료 20,000원")],
    )
    assert with_decoy_image == (classify("탱고의 밤", body), None)
    assert with_decoy_image[1] is None, "a text-rich post must never record image evidence used"


def test_a_text_rich_other_post_stays_other_even_with_a_perfect_poster():
    """Section 12: a long, real OTHER body (a notice, not an event) is not
    overridden just because an attached image happens to look like a real
    milonga announcement."""
    body = ("공지: 본 게시판은 매월 회비 납부 안내와 대관 일정을 공유합니다. "
            "문의사항은 운영진에게 메시지로 남겨주세요. 감사합니다.")
    classification, image_ref = classify_with_image_evidence(
        "공지사항", body, published=PUBLISHED,
        trusted_image_texts=[("poster.jpg",
            "밀롱가 9/5(토) 19:30-23:30 장소: PISTA")],
    )
    assert classification == "OTHER"
    assert image_ref is None


# --- B: image-only real event -----------------------------------------------

def test_b_image_only_real_event_is_classified_and_recovered():
    classification, image_ref = classify_with_image_evidence(
        "탱고 이벤트", "", published=PUBLISHED,
        trusted_image_texts=[("poster.jpg",
            "밀롱가 9/5(토) 19:30-23:30 장소: PISTA 입장료 13,000원")],
    )
    assert classification == "MILONGA"
    assert image_ref == "poster.jpg"


def test_b_process_discovered_post_creates_a_candidate_for_an_image_only_event():
    post = _Post("탱고 이벤트", "")
    poster_text = "밀롱가 9/5(토) 19:30-23:30 장소: PISTA 입장료 13,000원"
    result = process_discovered_post(
        None, post, source_role="PRIMARY",
        image_texts=[("poster.jpg", poster_text)],
        trusted_classification_texts=[("poster.jpg", poster_text)],
    )
    assert result["classification"] == "MILONGA"
    assert len(result["events"]) == 1
    ev = result["events"][0]
    assert ev.date == "2026-09-05"
    assert any(e.field == "context" and e.value == "IMAGE_CLASSIFICATION_USED"
               for e in ev.evidences)


def test_b_image_only_event_is_never_verified_even_when_source_role_qualifies():
    """Section 19-20: every field here is IMAGE_OCR evidence (there is no
    body at all) - core_complete requires TEXT evidence for date/time/fee,
    so this can never reach VERIFIED regardless of source_role."""
    post = _Post("탱고 이벤트", "", acquisition_quality="FULL")
    poster_text = "밀롱가 9/5(토) 19:30-23:30 장소: PISTA 입장료 13,000원"
    result = process_discovered_post(
        None, post, source_role="PRIMARY",
        image_texts=[("poster.jpg", poster_text)],
        trusted_classification_texts=[("poster.jpg", poster_text)],
    )
    ev = result["events"][0]
    assert ev.status == "POSSIBLE"
    assert all(e.evidence_type == IMAGE_OCR for e in ev.evidences if e.field in ("date", "time", "fee"))


# --- C: image-only class advertisement - no social evidence ----------------

def test_c_image_only_class_advertisement_does_not_become_an_event():
    """Title stays neutral - a title with its own class keyword would
    already classify as CLASS from the title alone, before the image is
    ever consulted, which would prove nothing about the new image path."""
    classification, image_ref = classify_with_image_evidence(
        "게시글", "", published=PUBLISHED,
        trusted_image_texts=[("poster.jpg",
            "탱고 초중급반 개강 9/5(토) 19:30-21:00 장소: PISTA 수강료 130,000원")],
    )
    assert classification not in EVENT_CLASSIFICATIONS
    assert image_ref is None


# --- D: image-only generic poster - missing signal --------------------------

def test_d_a_bare_milonga_word_with_no_date_or_time_does_not_promote():
    """Section 9: '밀롱가' alone, nothing else on the poster, is not treated
    as an announcement. Title stays neutral - a title that itself names the
    event ("이번 주 밀롱가") already classifies from title text alone under
    unchanged, pre-v0.84.4 rules, which would defeat the point of this
    fixture."""
    classification, image_ref = classify_with_image_evidence(
        "게시글", "", published=PUBLISHED,
        trusted_image_texts=[("poster.jpg", "다가오는 밀롱가에서 만나요 다들 준비하세요")],
    )
    assert classification == "OTHER"
    assert image_ref is None


def test_d_a_date_with_no_time_or_venue_does_not_promote():
    classification, image_ref = classify_with_image_evidence(
        "행사 안내", "", published=PUBLISHED,
        trusted_image_texts=[("poster.jpg", "밀롱가 9월 5일에 봐요")],
    )
    assert classification == "OTHER"
    assert image_ref is None


# --- E: logo/banner only - see test_image_fallback_trust.py for the
# runtime-level guarantee that a LOGO-classified image never reaches this
# function's trusted_image_texts at all. At this layer, an empty trusted
# list (what the runtime hands over once it has excluded the logo) behaves
# exactly like no image existed.

def test_e_no_trusted_image_text_stays_other():
    classification, image_ref = classify_with_image_evidence(
        "탱고 이벤트", "", published=PUBLISHED, trusted_image_texts=[],
    )
    assert classification == "OTHER"
    assert image_ref is None


# --- F: unrelated chrome text -----------------------------------------------

def test_f_unrelated_chrome_text_never_promotes():
    classification, image_ref = classify_with_image_evidence(
        "탱고 이벤트", "", published=PUBLISHED,
        trusted_image_texts=[("banner.jpg",
            "介 치과 예약 안내 평일 09:00-18:00 진료 문의 02-1234-5678")],
    )
    assert classification == "OTHER"
    assert image_ref is None


# --- G: old/archive flyer - existing date safety applies unchanged ---------
#
# An *explicit* 4-digit year ("2011.03.05") is trusted verbatim by
# _resolve_date_match() regardless of distance from `published` - if a
# poster states a full year, second-guessing it is not this engine's job,
# body text or image alike, and that is unchanged here (an explicit-year
# archive repost legitimately does promote, same as it always has for body
# text). The actual safety Section 16-17 describe is for a *yearless* date
# ("3/5", no year at all): _yearless_date() picks whichever nearby year
# lands closest to `published`, so a genuinely old, undated flyer is read as
# happening near when the post was (re-)discovered, never as some distant
# fixed year - MAX_DAYS_FROM_POST bounds how far even that guess may drift.
# This test proves that existing, load-bearing safety carries over to an
# image reading unchanged, not that old flyers are rejected outright.

def test_g_a_yearless_image_date_resolves_near_published_not_some_distant_year():
    old_flyer_published = date(2026, 9, 1)
    post = _Post("게시글", "", published_at=old_flyer_published)
    poster_text = "밀롱가 9월 5일 19:30-23:30 장소: PISTA 입장료 13,000원"
    result = process_discovered_post(
        None, post, source_role="SECONDARY",
        image_texts=[("poster.jpg", poster_text)],
        trusted_classification_texts=[("poster.jpg", poster_text)],
    )
    assert result["classification"] == "MILONGA"
    ev = result["events"][0]
    assert ev.date == "2026-09-05"
    assert abs((date.fromisoformat(ev.date) - old_flyer_published).days) <= 200


# --- H: ambiguous / multi-event poster --------------------------------------

def test_h_a_poster_naming_two_distinct_dates_does_not_promote():
    classification, image_ref = classify_with_image_evidence(
        "게시글", "", published=PUBLISHED,
        trusted_image_texts=[("poster.jpg",
            "9/5(토) 밀롱가 19:30-23:30 장소: PISTA / 9/12(토) 밀롱가 19:30-23:30 장소: OCHO")],
    )
    assert classification == "OTHER"
    assert image_ref is None


# --- known_event_type is untouched by any of this ---------------------------

def test_known_event_type_short_circuits_before_any_image_is_consulted():
    classification, image_ref = classify_with_image_evidence(
        "브랜드명", "", published=PUBLISHED, known_event_type="MILONGA",
        trusted_image_texts=[("poster.jpg", "완전히 무관한 텍스트")],
    )
    assert classification == "MILONGA"
    assert image_ref is None


# --- 647 regression: the exact incident shape --------------------------------

def test_647_shaped_image_only_post_recovers_without_becoming_verified():
    """The real K-TANGO shape that started this release: a post whose body
    used to be real text (a separate, already-ingested event exists for it
    from before the site started blocking), later re-fetched with an empty
    body and only a poster. This is the recovery path v0.84.3's own guard
    could never reach because classify() failed first - this is what makes
    it reachable, while still refusing VERIFIED."""
    post = _Post("K-TANGO 행사", "", acquisition_quality="FULL")
    poster_text = "밀롱가 8/1(토) 19:00-23:00 장소: 연세대학교 대강당"
    result = process_discovered_post(
        None, post, source_role="SECONDARY",
        image_texts=[("poster.jpg", poster_text)],
        trusted_classification_texts=[("poster.jpg", poster_text)],
    )
    assert result["classification"] == "MILONGA"
    ev = result["events"][0]
    assert ev.date == "2026-08-01"
    assert ev.venue == "연세대학교 대강당"
    assert ev.status == "POSSIBLE"


# --- body just under the trust threshold still engages the fallback --------

def test_a_body_under_the_trust_threshold_still_allows_image_classification():
    classification, image_ref = classify_with_image_evidence(
        "탱고 이벤트", "사진 참고", published=PUBLISHED,  # 4 chars, well under 20
        trusted_image_texts=[("poster.jpg",
            "밀롱가 9/5(토) 19:30-23:30 장소: PISTA 입장료 13,000원")],
    )
    assert classification == "MILONGA"
    assert image_ref == "poster.jpg"


def test_a_body_at_the_trust_threshold_blocks_image_classification():
    body = "이것은 스무 글자 이상인 무관한 본문입니다 진짜로요"  # >= 20 chars, OTHER
    classification, image_ref = classify_with_image_evidence(
        "탱고 이벤트", body, published=PUBLISHED,
        trusted_image_texts=[("poster.jpg",
            "밀롱가 9/5(토) 19:30-23:30 장소: PISTA 입장료 13,000원")],
    )
    assert classification == "OTHER"
    assert image_ref is None
