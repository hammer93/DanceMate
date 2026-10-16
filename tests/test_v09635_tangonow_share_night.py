"""v0.96.35: when a TangoNOW share page's own structure says a dance night is
on it, and when it does not.

The problem. A share page carries no event type. Captured live on 2026-10-16,
the whole JSON-LD vocabulary of all 57 pages the sitemap then listed is
``@type``, ``name``, ``url``, ``description``, ``startDate``, ``endDate``,
``eventStatus``, ``eventAttendanceMode``, ``inLanguage``, ``image``,
``location`` and ``organizer`` - no ``category``, no ``genre``, no
``eventType`` - and ``description`` is only the date, clock and venue restated
in prose. The clubs publishing through it name their nights ``cabeceo``,
``ORANGE``, ``이뚜밀``, ``볼베르``, ``The PISTA``: brand names holding no word
any vocabulary could read. So 28 of the 68 stored pages held a real dated,
clocked night and produced nothing at all, nine of them nights no other source
in DanceMate has.

What must not happen in answering that. The same sitemap lists a movie night,
two tango weeks, four festivals, two marathons and a weekend, so "it came from
a tango calendar" proves nothing about any one page. These tests pin both
directions: every page the policy admits, and every page it must not.

Every fixture in this file is a verbatim JSON-LD capture from ktnow.kr on
2026-10-16, except the two synthetic ones each test names as synthetic.
"""

from __future__ import annotations

import json

import pytest

from runtime import tangonow_discovery

SHARE = "https://ktnow.kr/e/"


def _page(event: dict) -> str:
    """A share page as the site renders one: the JSON-LD and nothing we need."""
    return ('<!doctype html><html><head><script type="application/ld+json">'
            + json.dumps(event, ensure_ascii=False)
            + "</script></head><body></body></html>")


def _event(**overrides) -> dict:
    base = {
        "@context": "https://schema.org",
        "@type": "Event",
        "eventStatus": "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "inLanguage": "ko-KR",
    }
    base.update(overrides)
    return base


# --- the nine nights no other source has ------------------------------------
#
# source_item_id -> the page exactly as it was captured. These are the items the
# v0.96.35 audit verified one by one against the original pages, and they stay
# here as fixtures whether or not the sitemap still lists them: the sitemap is a
# rolling window of upcoming events, so every one of these will fall out of it,
# and the reading has to keep working.

NINE = {
    6216: (f"{SHARE}occ_fb4d4ec5d68dd186986b68e391cd3d1cc5cf5b3a786eb2646f086c1082f94ab1",
           _event(name="PISTA | The PISTA",
                  description="2026-10-17(토) · 19:00~23:00 · DJ Eddy",
                  startDate="2026-10-17T19:00:00+09:00",
                  endDate="2026-10-17T23:00:00+09:00",
                  organizer={"@type": "Organization", "name": "PISTA"})),
    6219: (f"{SHARE}occ_224198dd19ab9f21c07f87756d7d5012d0ff25d484c3e6d97d1a06a0f55fc875",
           _event(name="엔빠스 | 볼베르",
                  description="2026-10-18(일) · 18:00~22:00 · EN PAZ · DJ 민트",
                  startDate="2026-10-18T18:00:00+09:00",
                  endDate="2026-10-18T22:00:00+09:00",
                  location={"@type": "Place", "name": "EN PAZ"},
                  organizer={"@type": "Organization", "name": "아론"})),
    6222: (f"{SHARE}occ_c3de6ea7b251f9e3e664982db16cad1dc6cdfbe445f3d638110c29d5f3bd353e",
           _event(name="이데알 탱고 까페 | Puerto Tango",
                  description="2026-10-18(일) · 18:00~22:00 · 이데알 탱고 까페 · DJ 유비아님",
                  startDate="2026-10-18T18:00:00+09:00",
                  endDate="2026-10-18T22:00:00+09:00",
                  location={"@type": "Place", "name": "이데알 탱고 까페"},
                  organizer={"@type": "Organization", "name": "PUERTO TANGO"})),
    6224: (f"{SHARE}occ_f9a0a2c4cc38bd2fabe33f1e1c4b41ad1e7c31e71667b344d340c2d1fb79b680",
           _event(name="PISTA | 비비밀",
                  description="2026-10-18(일) · 18:30~22:30 · DJ Vivian",
                  startDate="2026-10-18T18:30:00+09:00",
                  endDate="2026-10-18T22:30:00+09:00",
                  organizer={"@type": "Organization", "name": "비비안"})),
    6234: (f"{SHARE}occ_7cceecda138680387b2261fce0f3e6f0704ceac817cf1caea77a2652b3febb7c",
           _event(name="PISTA | The PISTA",
                  description="2026-10-24(토) · 19:00~23:00 · DJ Dada",
                  startDate="2026-10-24T19:00:00+09:00",
                  endDate="2026-10-24T23:00:00+09:00",
                  organizer={"@type": "Organization", "name": "PISTA"})),
    6238: (f"{SHARE}dov_brand_1768783589908_1_2026-10-29",
           _event(name="스튜디오 242 | 이뚜밀",
                  description="2026-10-29(thu) · 20:30~23:30 · 스튜디오 242",
                  startDate="2026-10-29T20:30:00+09:00",
                  endDate="2026-10-29T23:30:00+09:00",
                  location={"@type": "Place", "name": "스튜디오 242"},
                  organizer={"@type": "Organization", "name": "안나"})),
    6239: (f"{SHARE}occ_9b83da86a046c23166fe5acb1b0e58ca17a7d7ee1110a260ff1299df60cf507b",
           _event(name="PISTA | 돌아온 바다밀",
                  description="2026-10-30(금) · 20:00~02:00 · DJ 양반",
                  startDate="2026-10-30T20:00:00+09:00",
                  endDate="2026-10-31T02:00:00+09:00",
                  organizer={"@type": "Organization", "name": "바다"})),
    6242: (f"{SHARE}occ_fd39f8d3677204f57a0de0dd3a6e042e7eda72fd5414e6794a5542ec926e8d5c",
           _event(name="PISTA | The PISTA",
                  description="2026-10-31(토) · 19:00~23:00 · DJ Bubble T",
                  startDate="2026-10-31T19:00:00+09:00",
                  endDate="2026-10-31T23:00:00+09:00",
                  organizer={"@type": "Organization", "name": "PISTA"})),
    6388: (f"{SHARE}dov_brand_1765790609280_1_2026-10-23",
           _event(name="La Ventana | 라비오스",
                  description="2026-10-23(fri) · 20:00~24:00 · La Ventana",
                  startDate="2026-10-23T20:00:00+09:00",
                  endDate="2026-10-24T00:00:00+09:00",
                  location={"@type": "Place", "name": "La Ventana"},
                  organizer={"@type": "Organization", "name": "철환"})),
}

# The two pages that prove the title's first word is not the venue: one brand
# holding its nights at two different places, and a brand whose name is a
# different place again. Both captured 2026-10-16.
AB_TANGO_AT_ANDANTE = (
    f"{SHARE}occ_052bf977972456ce971f097624882d245ccf1bcf8771a080371ddfdd1740a49b",
    _event(name="A.B.Tango | MU!!LONGA",
           description="2026-10-16(금) · 20:00~01:00 · Andante · DJ Nacho",
           startDate="2026-10-16T20:00:00+09:00",
           endDate="2026-10-17T01:00:00+09:00",
           location={"@type": "Place", "name": "Andante"},
           organizer={"@type": "Organization", "name": "A.B.Tango"}))
LA_MELODIA_AT_ANDANTE = (
    f"{SHARE}occ_e6b4496ce48459a0f1bcfc41d85a526cc6b30e0a2e1f013cc524b76b8b73c9fc",
    _event(name="La melodia | La Melodía",
           description="2026-10-18(일) · 19:00~23:00 · Andante · DJ Hoon",
           startDate="2026-10-18T19:00:00+09:00",
           endDate="2026-10-18T23:00:00+09:00",
           location={"@type": "Place", "name": "Andante"},
           organizer={"@type": "Organization", "name": "멜로디언"}))
CABECEO = (
    f"{SHARE}occ_bb27ddc56d59c60dba2c4a586faca6961ecec9a3ee7bbebe4dad8067e5295495",
    _event(name="Andante | cabeceo",
           description="2026-10-22(목) · 19:30~23:30 · Andante · DJ Morning",
           startDate="2026-10-22T19:30:00+09:00",
           endDate="2026-10-22T23:30:00+09:00",
           location={"@type": "Place", "name": "Andante"},
           organizer={"@type": "Organization", "name": "One"}))

# --- the pages that are not a night ----------------------------------------

MOVIE_NIGHT = (
    f"{SHARE}occ_0526d51cb4b3247b63cd338249095d9ad687225e65977c2b744e2b9555d92a04",
    _event(name="Club Troilo | 트로일로 무비 나잇!!!",
           description="2026-10-17(토) · 18:30 · Club Troilo",
           startDate="2026-10-17",
           location={"@type": "Place", "name": "Club Troilo"}))
SEOUL_TANGO_WEEK = (
    f"{SHARE}occ_37117f467f3fcb37cc803917b6755fc7327b29c4630d91deb64ef18d08b75d8a",
    _event(name="SEOUL TANGO WEEK 2026",
           description="2026-11-12(목) · ELTANGO · Seoul Tango Academy",
           startDate="2026-11-12",
           location={"@type": "Place", "name": "ELTANGO · Seoul Tango Academy"},
           organizer={"@type": "Organization",
                      "name": "ELTANGO · Seoul Tango Academy"}))
MASAN_MARATHON = (
    f"{SHARE}t4yTitjlTQ6G8ZcDHJz1",
    _event(name="제1회 마산 가고파 국화 탱고 마라톤",
           description="2026-10-31(토) · Tango club Mi Noche",
           startDate="2026-10-31",
           location={"@type": "Place", "name": "Tango club Mi Noche"},
           organizer={"@type": "Organization", "name": "ISABELLE & SENS"}))
BUSAN_FESTIVAL = (
    f"{SHARE}0SB1vX8MbJ7I6l1dePUx",
    _event(name="BUSAN TANGO FESTIVAL",
           description="2026-10-21(wed) · 데땅고",
           startDate="2026-10-21",
           location={"@type": "Place", "name": "데땅고"},
           organizer={"@type": "Organization",
                      "name": "Lucas Carrizo, Maria Paula Tejeda"}))
ROYBEDDONG = (
    f"{SHARE}aSkYZREohvQi2RKzEXEA",
    _event(name="RoyBeDDong in BUSAN", description="2026-12-18(fri)",
           startDate="2026-12-18"))
EL_MAR_WEEKEND = (
    f"{SHARE}occ_059519e91def6d8b71d9321ef0dc1111085cb2792302488a74e9d996b9a81a04",
    _event(name="Busan Tango Weekend El Mar", description="2027-09-02(목) · Busan",
           startDate="2027-09-02", location={"@type": "Place", "name": "Busan"}))

# The two pages the engine already reads on their own words, kept here so a
# change to this policy cannot quietly start answering for them instead.
FRIDAY_PRACTICA = (
    f"{SHARE}occ_1d649fe79964d4371fc1925d65086395e36b0ecdecae39f28aeeaff0f9219d9c",
    _event(name="엔빠스 | 금요 쁘락띠까",
           description="2026-10-16(금) · 14:00~17:00 · EN PAZ",
           startDate="2026-10-16T14:00:00+09:00",
           endDate="2026-10-16T17:00:00+09:00",
           location={"@type": "Place", "name": "EN PAZ"},
           organizer={"@type": "Organization", "name": "아란&향연"}))
TOIP_MILONGA = (
    f"{SHARE}occ_e172a2721640302caa5a2e3d6fcdb87ea03631058e3af0ec01a8f4479fe6e269",
    _event(name="OCHO | 토이프밀롱가",
           description="2026-10-17(토) · 14:00~18:00 · OCHO · DJ 허그",
           startDate="2026-10-17T14:00:00+09:00",
           endDate="2026-10-17T18:00:00+09:00",
           location={"@type": "Place", "name": "OCHO"},
           organizer={"@type": "Organization", "name": "이프"}))


def _record(page):
    url, event = page
    return tangonow_discovery.parse_share_page(_page(event), url)


# --- the nights, one by one -------------------------------------------------

@pytest.mark.parametrize("item_id", sorted(NINE))
def test_each_verified_missing_night_is_admitted(item_id):
    """The nine the audit verified against the original pages, all nine."""
    record = _record(NINE[item_id])
    assert record is not None
    assert record["source_night_fallback"] == "SOCIAL", item_id
    assert record["night_evidence"].startswith("TangoNOW share page:"), item_id


def test_the_evidence_says_which_corroboration_admitted_the_page():
    """A reason a person can read back off the stored record months later."""
    assert _record(NINE[6216])["night_evidence"] == (
        "TangoNOW share page: one dated night 2026-10-17 19:00~23:00, DJ Eddy")
    assert _record(NINE[6238])["night_evidence"] == (
        "TangoNOW share page: one dated night 2026-10-29 20:30~23:30, "
        "recurring brand occurrence at 스튜디오 242")


def test_a_brand_occurrence_with_a_venue_and_no_dj_is_admitted():
    """6238 and 6388 name no DJ. A registered recurring brand that states its
    own venue is the other corroboration, and without it two of the nine stay
    missing."""
    for item_id in (6238, 6388):
        record = _record(NINE[item_id])
        assert record["source_night_fallback"] == "SOCIAL"
        assert "recurring brand occurrence" in record["night_evidence"]


def test_a_one_off_occurrence_with_no_dj_is_not_admitted():
    """Synthetic: 6238's page at its `occ_` sibling URL. The brand record is
    the operator's own statement that this is a regular night at a fixed place
    and hour; a one-off page naming no DJ does not carry it, and guessing is
    what this whole policy exists not to do."""
    url, event = NINE[6238]
    record = tangonow_discovery.parse_share_page(
        _page(event), f"{SHARE}occ_" + "a" * 64)
    assert record is not None, "it is still a stored page"
    assert "source_night_fallback" not in record


def test_a_night_that_closes_after_midnight_is_still_one_night():
    record = _record(NINE[6239])
    assert record["source_night_fallback"] == "SOCIAL"
    assert "2026-10-30 20:00~02:00" in record["night_evidence"]


def test_a_night_that_closes_exactly_at_midnight_is_still_one_night():
    record = _record(NINE[6388])
    assert record["source_night_fallback"] == "SOCIAL"
    assert "2026-10-23 20:00~00:00" in record["night_evidence"]


# --- the pages that are not a night ----------------------------------------

@pytest.mark.parametrize("page,label", [
    (MOVIE_NIGHT, "a movie night"),
    (SEOUL_TANGO_WEEK, "a tango week"),
    (MASAN_MARATHON, "a marathon"),
    (BUSAN_FESTIVAL, "a festival"),
    (ROYBEDDONG, "a page stating only a date"),
    (EL_MAR_WEEKEND, "a weekend"),
])
def test_a_page_that_states_no_clock_is_never_admitted(page, label):
    """Every one of the ten stored pages that is not a night states no clock -
    which is also why none of them produced an Event before this release, and
    none may start to now."""
    record = _record(page)
    assert record is not None, f"{label} is still a stored page"
    assert "source_night_fallback" not in record, label
    assert "night_evidence" not in record, label


def test_a_timed_movie_night_is_refused_by_its_own_name():
    """Synthetic, and the case the clock test cannot reach: the real movie
    night above states 18:30 in its description and nothing in its structured
    dates, but nothing stops this provider filling those in tomorrow. A
    19:00~22:00 screening at a tango venue is structurally identical to a
    milonga, so only its own name can tell them apart."""
    url, event = MOVIE_NIGHT
    timed = dict(event, startDate="2026-10-17T19:00:00+09:00",
                 endDate="2026-10-17T22:00:00+09:00")
    record = tangonow_discovery.parse_share_page(_page(timed), url)
    assert record is not None
    assert "source_night_fallback" not in record


@pytest.mark.parametrize("name", [
    "Club Troilo | 트로일로 무비 나잇!!!", "SEOUL TANGO WEEK 2026",
    "탱고 페스티발", "국화 탱고 마라톤", "Busan Tango Weekend El Mar",
    "Andante | 초급 강습", "PISTA | 월요 클래스", "Tango Workshop with Maestro",
    "Andante | Beginner Class", "서울 탱고 대회", "라이브 공연 나잇",
])
def test_a_name_announcing_another_format_is_refused(name):
    """Synthetic: a real admitted night's structure under each name. A false
    refusal here costs a recovery and never creates a false event, which is
    the direction this list is allowed to be wrong in."""
    url, event = CABECEO
    record = tangonow_discovery.parse_share_page(
        _page(dict(event, name=name)), url)
    assert "source_night_fallback" not in record, name


@pytest.mark.parametrize("name", [
    "Andante | cabeceo", "PISTA | The PISTA", "A.B.Tango | MU!!LONGA",
    "La melodia | La Melodía", "스튜디오 242 | 이뚜밀", "Andante | ALMIL",
    "PISTA | 돌아온 바다밀", "La Ventana | 라비오스", "ORANGE",
    "Andante | Alonga", "엔빠스 | 볼베르", "Mi Vida tango studio | 금비다",
])
def test_no_real_night_name_is_caught_by_the_refusal_list(name):
    url, event = CABECEO
    record = tangonow_discovery.parse_share_page(
        _page(dict(event, name=name)), url)
    assert record["source_night_fallback"] == "SOCIAL", name


def test_a_multi_day_span_is_refused_even_when_it_is_clocked():
    """Synthetic: the festival above, given the clocked dates a multi-day event
    would carry. Three days is not one night, whatever its name."""
    url, event = BUSAN_FESTIVAL
    spanning = dict(event, name="BUSAN TANGO WEEKENDER",
                    startDate="2026-10-21T19:00:00+09:00",
                    endDate="2026-10-23T23:00:00+09:00")
    record = tangonow_discovery.parse_share_page(_page(spanning), url)
    assert "source_night_fallback" not in record


def test_a_start_with_no_end_is_refused():
    url, event = NINE[6216]
    stripped = {k: v for k, v in event.items() if k != "endDate"}
    record = tangonow_discovery.parse_share_page(_page(stripped), url)
    assert record is not None
    assert "source_night_fallback" not in record


def test_an_end_before_its_start_is_refused():
    url, event = NINE[6216]
    backwards = dict(event, endDate="2026-10-17T18:00:00+09:00")
    record = tangonow_discovery.parse_share_page(_page(backwards), url)
    assert "source_night_fallback" not in record


def test_a_date_only_pair_is_refused():
    url, event = NINE[6216]
    dateless = dict(event, startDate="2026-10-17", endDate="2026-10-17")
    record = tangonow_discovery.parse_share_page(_page(dateless), url)
    assert "source_night_fallback" not in record


# --- the page is still read the way it always was ---------------------------

def test_a_cancelled_page_is_still_no_record_at_all():
    url, event = NINE[6216]
    for status in ("https://schema.org/EventCancelled",
                   "https://schema.org/EventPostponed"):
        assert tangonow_discovery.parse_share_page(
            _page(dict(event, eventStatus=status)), url) is None


def test_malformed_json_ld_is_no_record_rather_than_a_crash():
    url = NINE[6216][0]
    for html in ('<script type="application/ld+json">{not json</script>',
                 '<script type="application/ld+json">[]</script>',
                 '<script type="application/ld+json">{"@type":"WebPage"}</script>',
                 "<html><body>nothing at all</body></html>", "", None):
        assert tangonow_discovery.parse_share_page(html, url) is None


@pytest.mark.parametrize("field", ["name", "startDate", "location", "organizer",
                                   "description", "eventStatus", "image"])
def test_a_missing_field_never_raises(field):
    url, event = NINE[6219]
    stripped = {k: v for k, v in event.items() if k != field}
    tangonow_discovery.parse_share_page(_page(stripped), url)


def test_a_page_with_a_junk_location_shape_never_raises():
    url, event = NINE[6219]
    for location in ("a string", [], 7, {"@type": "Place"}, {"name": None}):
        record = tangonow_discovery.parse_share_page(
            _page(dict(event, location=location)), url)
        assert record is not None


# --- the body is still only what the page said ------------------------------

def test_the_body_carries_no_word_the_page_did_not_say():
    """The judgement travels in the record, never in the text handed to the
    extractor. Writing 소셜 into the body would put a word the page never said
    in front of the engine as though the page had said it."""
    for item_id in sorted(NINE):
        body = _record(NINE[item_id])["body"]
        for invented in ("소셜", "SOCIAL", "밀롱가", "social", "dance"):
            assert invented not in body, (item_id, invented)


def test_the_body_is_byte_for_byte_what_v09632_rendered():
    """The whole point of keeping the judgement out of the body: 39 of the 57
    pages gain the new keys, and not one of their bodies moves - so no stored
    item is re-keyed in order to carry a fact about its classification."""
    assert _record(NINE[6216])["body"] == (
        "2026년 10월 17일 시간: 19:00~23:00 DJ: Eddy 주최: PISTA")
    assert _record(NINE[6219])["body"] == (
        "2026년 10월 18일 시간: 18:00~22:00 장소: EN PAZ DJ: 민트 주최: 아론")
    assert _record(NINE[6238])["body"] == (
        "2026년 10월 29일 시간: 20:30~23:30 장소: 스튜디오 242 주최: 안나")


def test_a_page_the_policy_declines_produces_the_record_it_always_did():
    """Absent keys, not null ones. A page that has not changed must produce a
    byte-identical record, or every ordinary collection would read as a
    revision of something."""
    record = _record(MOVIE_NIGHT)
    assert set(record) == {"source_url", "title", "body", "published_at",
                           "acquisition_quality"}


def test_reading_the_same_page_twice_gives_the_same_record():
    """`intake.store_item()` compares these keys to decide whether an unchanged
    page needs re-reading, so a non-deterministic value here would re-key the
    whole source on every cycle."""
    for item_id in sorted(NINE):
        first, second = _record(NINE[item_id]), _record(NINE[item_id])
        assert json.dumps(first, sort_keys=True, ensure_ascii=False) == \
            json.dumps(second, sort_keys=True, ensure_ascii=False)


# --- the venue is the page's own, never its title ---------------------------

def test_the_title_prefix_is_never_the_venue():
    """A.B.Tango holds MU!!LONGA at Andante and 치초 후아나 Grand Milonga at
    PISTA, and La melodia holds La Melodía at Andante. This provider's brand
    and its venue are many-to-many, so the first word of a title is not a
    place however much it looks like one."""
    for page in (AB_TANGO_AT_ANDANTE, LA_MELODIA_AT_ANDANTE):
        body = _record(page)["body"]
        assert "장소: Andante" in body
        assert "장소: A.B.Tango" not in body
        assert "장소: La melodia" not in body


def test_a_page_stating_no_place_renders_no_place():
    """The five PISTA pages state no `location.name`. Nothing may supply one."""
    for item_id in (6216, 6224, 6234, 6239, 6242):
        assert "장소:" not in _record(NINE[item_id])["body"], item_id


# --- the pages the engine already reads ------------------------------------

def test_the_policy_also_admits_pages_the_engine_already_classifies():
    """Deliberately: the collector does not know what the engine will make of a
    page, and must not try to. 토이프밀롱가 names its night in its own words, so
    `classify()` answers MILONGA before the fallback is ever consulted - see
    engine/tests/test_v09635_structural_night_fallback.py, which holds that the
    fallback cannot weaken it."""
    assert _record(TOIP_MILONGA)["source_night_fallback"] == "SOCIAL"


def test_a_practica_naming_no_dj_is_declined_and_loses_nothing():
    """금요 쁘락띠까 states a venue but no DJ on a one-off occurrence page, so the
    corroboration is missing and the policy declines it. It costs nothing: the
    engine reads 쁘락띠까 in the title itself and has always called this one
    MILONGA. Missing evidence is not the same as a missing event."""
    record = _record(FRIDAY_PRACTICA)
    assert "source_night_fallback" not in record
    assert record["body"] == (
        "2026년 10월 16일 시간: 14:00~17:00 장소: EN PAZ 주최: 아란&향연")
