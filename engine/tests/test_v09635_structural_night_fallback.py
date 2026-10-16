"""v0.96.35: a source's structure may say there is a night here, and nothing more.

`known_event_type` has been admissible since v0.80 and keeps its precedence: a
collector reading a dedicated milonga board knows *which kind* of night every
post on it announces, so classify() returns it over any keyword reading. This
release adds the opposite kind of evidence with the opposite precedence.

TangoNOW's share pages carry no event type at all - captured live on 2026-10-16,
all 57 pages the sitemap then listed render `@type`, `name`, `url`,
`description`, `startDate`, `endDate`, `eventStatus`, `eventAttendanceMode`,
`inLanguage`, `image`, `location`, `organizer` and nothing else, and the
`description` is only the date, clock and venue restated. The clubs publishing
there name their nights `cabeceo`, `ORANGE`, `이뚜밀`, `The PISTA`, so 28 of 68
stored pages reached the end of classify() carrying a real dated, clocked night
and became OTHER. What the collector *can* establish is structural - see
`runtime.tangonow_discovery.share_night_evidence()` - and `source_night_fallback`
is how it says so.

The safety of it is entirely in where it is asked: last, after every refusal and
after every reading of the post's own words. These tests pin that, in both
directions, including over the real Production bodies of the posts this release
exists for and the ones it must not touch.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from src.classifier import (classify, classify_with_image_evidence,  # noqa: E402
                            is_non_event_notice)
from src.extraction_rules import extract_venue, known_venue_fallback  # noqa: E402
from src.extractor import extract_single  # noqa: E402
from src.live_pipeline import (EVENT_CLASSIFICATIONS,  # noqa: E402
                               process_discovered_post)
from src.collectors.base import RawPostRecord  # noqa: E402

# Verbatim Production bodies, SRC-W-002, collected 2026-10-13/15.
THE_PISTA = ("PISTA | The PISTA",
             "2026년 10월 17일 시간: 19:00~23:00 DJ: Eddy 주최: PISTA")
BIBIMIL = ("PISTA | 비비밀",
           "2026년 10월 18일 시간: 18:30~22:30 DJ: Vivian 주최: 비비안")
BADAMIL = ("PISTA | 돌아온 바다밀",
           "2026년 10월 30일 시간: 20:00~02:00 DJ: 양반 주최: 바다")
VOLVER = ("엔빠스 | 볼베르",
          "2026년 10월 18일 시간: 18:00~22:00 장소: EN PAZ DJ: 민트 주최: 아론")
ITTUMIL = ("스튜디오 242 | 이뚜밀",
           "2026년 10월 29일 시간: 20:30~23:30 장소: 스튜디오 242 주최: 안나")
LABIOS = ("La Ventana | 라비오스",
          "2026년 10월 23일 시간: 20:00~00:00 장소: La Ventana 주최: 철환")
MULONGA = ("A.B.Tango | MU!!LONGA",
           "2026년 10월 16일 시간: 20:00~01:00 장소: Andante DJ: Nacho 주최: A.B.Tango")
LA_MELODIA = ("La melodia | La Melodía",
              "2026년 10월 18일 시간: 19:00~23:00 장소: Andante DJ: Hoon 주최: 멜로디언")
MAJEMIL = ("PISTA | 마제밀",
           "2026년 10월 16일 시간: 20:00~00:30 장소: PISTA DJ: Isabelle 주최: 마르코, 제이콥")

# The two this release is forbidden to weaken, also verbatim.
CASA_MILONGA = ("OCHO | 까사밀롱가",
                "2026년 10월 13일 시간: 20:00~00:00 장소: OCHO DJ: 곤즈 주최: 제프")
FRIDAY_PRACTICA = ("엔빠스 | 금요 쁘락띠까",
                   "2026년 10월 16일 시간: 14:00~17:00 장소: EN PAZ 주최: 아란&향연")

# Every one of these classified as OTHER before this release, 마제밀 included:
# its name carries no night word either, and the 장소 field it does carry is
# read for the venue and never for the type.
BRAND_TITLES = [THE_PISTA, BIBIMIL, BADAMIL, VOLVER, ITTUMIL, LABIOS,
                MULONGA, LA_MELODIA, MAJEMIL]


# --- what the fallback may do ----------------------------------------------

@pytest.mark.parametrize("title,body", BRAND_TITLES)
def test_a_brand_name_is_nothing_without_the_fallback(title, body):
    """The state this release found: a real dated, clocked night, and no word
    in it any vocabulary reads."""
    assert classify(title, body) == "OTHER"


@pytest.mark.parametrize("title,body", BRAND_TITLES)
def test_the_fallback_promotes_exactly_that(title, body):
    assert classify(title, body, source_night_fallback="SOCIAL") == "SOCIAL"


@pytest.mark.parametrize("title,body", BRAND_TITLES)
def test_the_promoted_post_reaches_the_extractor(title, body):
    post = RawPostRecord(source_id="SRC-W-002", platform="WEB",
                         source_url="https://ktnow.kr/e/occ_x", title=title,
                         body=body, acquisition_quality="FETCHED_FULL",
                         source_night_fallback="SOCIAL")
    result = process_discovered_post(None, post, "AGGREGATOR")
    assert result["classification"] in EVENT_CLASSIFICATIONS
    assert len(result["events"]) == 1


# --- what it may not do ----------------------------------------------------

@pytest.mark.parametrize("title,body", [CASA_MILONGA, FRIDAY_PRACTICA])
def test_the_fallback_never_weakens_a_night_the_post_names_itself(title, body):
    """The taxonomy has no PRACTICA: 쁘락/practica are MILONGA_WORDS, so
    `금요 쁘락띠까` has always classified as MILONGA and must keep doing so.
    SOCIAL is the weaker answer, and a weaker answer must never win."""
    without = classify(title, body)
    assert without == "MILONGA"
    assert classify(title, body, source_night_fallback="SOCIAL") == without


def test_the_fallback_never_overturns_the_non_event_guard():
    """v0.96.8's recap/administrative guard is the one rule above
    `known_event_type` itself. A refusal is a refusal."""
    title = "금요정모 사진 #13"
    assert is_non_event_notice(title)
    assert classify(title, "2026년 10월 17일 시간: 19:00~23:00 장소: PISTA") == "OTHER"
    assert classify(title, "2026년 10월 17일 시간: 19:00~23:00 장소: PISTA",
                    source_night_fallback="SOCIAL") == "OTHER"


def test_the_fallback_never_overturns_a_course():
    """A post selling enrolment stays a course. v0.96.7/v0.96.10 reached those
    verdicts before the end of the function, so the fallback never sees them."""
    title = "탱고 초급 강습 10월 개강반 모집"
    body = "수강료 4주 12만원 매주 수요일 19:00~21:00 장소: PISTA"
    assert classify(title, body) == "CLASS"
    assert classify(title, body, source_night_fallback="SOCIAL") == "CLASS"


@pytest.mark.parametrize("injected", [
    "CLASS", "OTHER", "MILONGA_LIKE", "", "   ", "anything", "PRACTICA",
    None, 0, 1, True, [], {}, ("SOCIAL",),
])
def test_only_a_real_event_classification_gets_through(injected):
    """A collector cannot inject CLASS, OTHER or a type of its own invention,
    and a non-string cannot crash the comparison."""
    title, body = THE_PISTA
    assert classify(title, body, source_night_fallback=injected) == "OTHER"


@pytest.mark.parametrize("accepted", sorted(EVENT_CLASSIFICATIONS))
def test_every_real_event_classification_is_accepted(accepted):
    title, body = THE_PISTA
    assert classify(title, body, source_night_fallback=accepted) == accepted


def test_a_post_from_any_other_source_is_untouched():
    """The parameter defaults to None, which is every collector but one."""
    for title, body in BRAND_TITLES + [CASA_MILONGA, FRIDAY_PRACTICA]:
        assert classify(title, body) == classify(
            title, body, source_night_fallback=None)


def test_the_image_path_carries_the_fallback_without_consulting_a_poster():
    """classify_with_image_evidence() returns as soon as the text decided, so a
    promoted post never reaches the poster gate - and `image_ref` stays None,
    because no poster decided anything."""
    title, body = THE_PISTA
    classification, ref = classify_with_image_evidence(
        title, body, source_night_fallback="SOCIAL")
    assert (classification, ref) == ("SOCIAL", None)


# --- the venue is the page's own, never its heading or its organiser --------

def test_a_known_venue_name_in_the_organiser_field_is_not_a_place():
    """`주최: PISTA` is who is hosting. The three known names exist "for posts
    that name their place in prose and never label it", and a labelled value is
    the opposite of prose."""
    assert known_venue_fallback("DJ: Eddy 주최: PISTA") is None
    assert known_venue_fallback("주최: OCHO") is None
    assert known_venue_fallback("문의: O NADA") is None


def test_a_known_venue_named_in_real_prose_is_still_a_place():
    """The reading this fallback was added for, and the reading v0.96.35 had to
    leave alone. Note the Korean particle: v0.96.32 gave each known name its own
    word boundaries, so `PISTA에서` has never matched and this release does not
    change that - `홍대 PISTA 밀롱가` is the shape that does."""
    assert known_venue_fallback("홍대 PISTA 밀롱가") == ("PISTA", "PISTA")
    assert known_venue_fallback("📍 화정 오나다 20:00") == ("Tango O Nada",
                                                        "O Nada/오나다")
    assert known_venue_fallback("매주 토요일 밤, 홍대 PISTA에서") is None


def test_the_gloss_rule_from_v09632_still_holds():
    assert known_venue_fallback("오초(Ocho) 동작을 설명하면") is None


def test_a_labelled_place_still_outranks_everything():
    assert known_venue_fallback("장소: 어딘가 주최: PISTA") is None
    assert extract_venue("장소: Andante DJ: Nacho 주최: A.B.Tango").name == "Andante"


@pytest.mark.parametrize("title,body", [THE_PISTA, BIBIMIL, BADAMIL])
def test_a_page_stating_no_place_is_given_none(title, body):
    """The five PISTA pages name no place anywhere. Before this release the
    heading supplied one: `PISTA | 비비밀` was read as being held at the Seoul
    venue PISTA on the strength of its own first word, and the same provider
    proves that cannot be assumed - `A.B.Tango | 치초 후아나 Grand Milonga` is
    held at PISTA while `A.B.Tango | MU!!LONGA` is held at Andante."""
    assert extract_single(title, body, source_role="AGGREGATOR").venue is None


@pytest.mark.parametrize("title,body,expected", [
    (*MULONGA, "Andante"), (*LA_MELODIA, "Andante"), (*VOLVER, "EN PAZ"),
    (*ITTUMIL, "스튜디오 242"), (*LABIOS, "La Ventana"), (*MAJEMIL, "PISTA"),
    (*CASA_MILONGA, "OCHO"),
])
def test_a_page_that_labels_its_place_keeps_it(title, body, expected):
    """Including 마제밀, whose heading and whose own 장소 field agree: the fix is
    not "distrust PISTA", it is "read the field the page filled in"."""
    assert extract_single(title, body, source_role="AGGREGATOR").venue == expected


# --- the night's own clock -------------------------------------------------

@pytest.mark.parametrize("title,body,start,end,offset", [
    (*THE_PISTA, "19:00", "23:00", 0),
    (*BADAMIL, "20:00", "02:00", 1),
    (*LABIOS, "20:00", "00:00", 1),
    (*MULONGA, "20:00", "01:00", 1),
    (*ITTUMIL, "20:30", "23:30", 0),
])
def test_the_clock_is_the_page_own_and_crossing_midnight_is_kept(
        title, body, start, end, offset):
    ev = extract_single(title, body, source_role="AGGREGATOR")
    assert str(ev.start_time) == start
    assert str(ev.end_time) == end
    assert ev.end_day_offset == offset, "an overnight close is not another day"


@pytest.mark.parametrize("title,body,date", [
    (*THE_PISTA, "2026-10-17"), (*VOLVER, "2026-10-18"),
    (*ITTUMIL, "2026-10-29"), (*LABIOS, "2026-10-23"), (*BADAMIL, "2026-10-30"),
])
def test_the_date_is_the_page_own(title, body, date):
    assert str(extract_single(title, body, source_role="AGGREGATOR").date) == date
