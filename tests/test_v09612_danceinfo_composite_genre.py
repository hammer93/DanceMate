"""v0.96.12 - a night filed under two genres stops being filed under none.

danceinfo.net's ``genreName`` is a compound label, not a single enum value: a
night that plays bachata and salsa is filed under "바차타/살사". ``parse_list()``
compared that whole string to the source's configured genre with ``==``, which
asks the site whether its night is *only* salsa - a question it never answers
yes to. Every composite night was dropped at discovery, before a source_item
existed, so no amount of re-extraction could ever recover it.

Measured read-only against the live list pages on 2026-09-24, over 235 distinct
listings across today+7 days:

    바차타/살사        83     바차타               71     살사            23
    키좀바             16     탱고                 14     기타             7
    바차타/살사/키좀바   5     바차타/주크            5     살사/키좀바       4
    바차타/살사/주크     2     주크                  2     살사/탱고        1
    살사/기타           1     바차타/살사/기타        1

The salsa source therefore saw 23 of the 120 listings it should have. 45 of the
97 it was missing are filed by the site itself under a category this module
already reads as an EVENT (파티/출빠정보/정모) - among them every salsa social
running on 2026-09-24, which the audit measured at 0 of 7 found.

The separator is "/" and nothing else: the only non-hangul character appearing
inside any of those 235 labels, all 11 occurrences of it. This reads what is
there rather than inventing a wider punctuation schema the site does not use.
"""

from __future__ import annotations

import json

from runtime import danceinfo_discovery as di

LIST_URL = "https://danceinfo.net/lessons?genre=all&category=all&location=all"


def _page(lessons: list[dict]) -> str:
    payload = {
        "props": {"pageProps": {"initialDays": [
            {"date": "2026-09-24", "lessons": lessons},
        ]}}
    }
    return (
        '<html><body><script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(payload)}</script></body></html>"
    )


def _titles(lessons: list[dict], genre_name: str) -> list[str]:
    return [p["title"] for p in di.parse_list(_page(lessons), LIST_URL,
                                              genre_name=genre_name)]


def _lesson(idx: int, genre: str | None, title: str, category_idx: int = 2) -> dict:
    return {"contentIdx": idx, "genreName": genre, "title": title,
            "date": "2026-09-24", "categoryIdx": category_idx,
            "categoryName": "출빠정보"}


# --- genre_tokens(): the label read as what it is -----------------------------

def test_a_single_genre_is_its_own_only_token():
    assert di.genre_tokens("살사") == {"살사"}


def test_a_composite_label_is_every_genre_it_names():
    assert di.genre_tokens("바차타/살사") == {"바차타", "살사"}
    assert di.genre_tokens("바차타/살사/키좀바") == {"바차타", "살사", "키좀바"}


def test_whitespace_around_a_separator_does_not_make_a_different_genre():
    assert di.genre_tokens("바차타 / 살사") == {"바차타", "살사"}


def test_a_missing_label_names_no_genre_at_all():
    """An empty or absent genreName matched nothing before this release and
    matches nothing after it - `not in set()` is the same answer `!=` gave."""
    assert di.genre_tokens(None) == set()
    assert di.genre_tokens("") == set()
    assert di.genre_tokens("/") == set()


# --- the filter: T1-T8 --------------------------------------------------------

def test_t1_an_exactly_matching_single_genre_is_accepted():
    """The behaviour every existing danceinfo source already relies on."""
    assert _titles([_lesson(1, "살사", "살사 소셜파티")], "살사") == ["살사 소셜파티"]


def test_t2_a_two_genre_night_is_accepted_by_either_of_its_genres():
    lessons = [_lesson(2, "바차타/살사", "THURSDAY BONITA 추석연휴시작!")]
    assert _titles(lessons, "살사") == ["THURSDAY BONITA 추석연휴시작!"]


def test_t3_a_three_genre_night_is_accepted_by_any_of_its_genres():
    lessons = [_lesson(3, "바차타/살사/키좀바", "홍턴 추석 연휴 수~토요일 스페셜 이벤트!")]
    assert _titles(lessons, "살사") == ["홍턴 추석 연휴 수~토요일 스페셜 이벤트!"]


def test_t4_a_genre_the_night_does_not_name_is_still_rejected():
    """Widening the read must not widen it to everything: a bachata-only
    night is not a salsa source's to collect."""
    assert _titles([_lesson(4, "바차타", "바차타 소셜")], "살사") == []


def test_t5_a_bachata_source_accepts_the_same_composite_night():
    lessons = [_lesson(5, "바차타/살사", "BACHATA, SALSA, SOCIAL PARTY")]
    assert _titles(lessons, "바차타") == ["BACHATA, SALSA, SOCIAL PARTY"]


def test_t6_a_kizomba_source_accepts_a_three_genre_night():
    lessons = [_lesson(6, "바차타/살사/키좀바", "NEW.SOL BAR 추석 영업안내")]
    assert _titles(lessons, "키좀바") == ["NEW.SOL BAR 추석 영업안내"]


def test_t7_a_partial_word_is_not_a_genre():
    """A token test, not a substring test. "살사" is a genre of "바차타/살사"
    but not of a longer word that merely contains those two syllables, and a
    fragment of a real genre is not that genre."""
    assert _titles([_lesson(7, "살사바", "살사바 소개")], "살사") == []
    assert _titles([_lesson(8, "바차타/살사", "소셜")], "차타") == []
    assert _titles([_lesson(9, "키좀바", "키좀바 클래스")], "좀바") == []


def test_t8_a_listing_with_no_genre_label_is_dropped_as_before():
    lessons = [_lesson(10, None, "장르 없는 글"), _lesson(11, "", "빈 장르")]
    assert _titles(lessons, "살사") == []
    assert _titles(lessons, "탱고") == []


# --- regression: the tango source this release does not set out to change -----

def test_the_tango_default_still_collects_exactly_its_own_nights():
    lessons = [
        _lesson(20, "탱고", "러블리밀롱가 7주년 파티안내"),
        _lesson(21, "바차타/살사", "보니따에서 보내는 추석연휴"),
        _lesson(22, "살사", "살사 소셜파티"),
    ]
    assert _titles(lessons, di.TANGO_GENRE_NAME) == ["러블리밀롱가 7주년 파티안내"]


def test_a_night_naming_two_genres_reaches_both_of_their_sources():
    """The one real composite spanning two configured danceinfo sources on
    2026-09-24 was "살사/탱고" (contentIdx 4049). Both sources collect it; the
    uniqueness key is (source_id, external_id), so each stores its own row and
    the existing duplicate/canonical machinery settles them - the same shape
    two Daum boards watching one cafe post already produce in Production."""
    lessons = [_lesson(4049, "살사/탱고", "라우탱고아카데미 ☆9월 무료특강안내", category_idx=4)]
    assert _titles(lessons, "살사") == ["라우탱고아카데미 ☆9월 무료특강안내"]
    assert _titles(lessons, "탱고") == ["라우탱고아카데미 ☆9월 무료특강안내"]


# --- the category contract v0.96.10 wrote is untouched ------------------------

def test_a_newly_reachable_course_is_still_read_as_a_course():
    """Recall is not worth a lesson becoming an event. 50 of the 97 listings
    the salsa source newly reaches are filed 강습 (categoryIdx 5), and this
    release changes nothing about how that is read."""
    course = _lesson(30, "바차타/살사", "강북살사 살사&바차타 초중급반", category_idx=5)
    posts = di.parse_list(_page([course]), LIST_URL, genre_name="살사")
    assert len(posts) == 1
    assert posts[0]["source_category"] == di.SOURCE_CATEGORY_CLASS


def test_a_newly_reachable_night_is_still_read_as_a_night():
    night = _lesson(31, "바차타/살사", "CASS 추석 한가위 BIG PARTY", category_idx=1)
    posts = di.parse_list(_page([night]), LIST_URL, genre_name="살사")
    assert posts[0]["source_category"] == di.SOURCE_CATEGORY_EVENT


def test_an_open_class_stays_the_undecided_thing_it_was():
    """오픈강습 (idx 4) is deliberately unmapped and stays that way."""
    lesson = _lesson(32, "살사/탱고", "라우탱고아카데미 ☆9월 무료특강안내", category_idx=4)
    posts = di.parse_list(_page([lesson]), LIST_URL, genre_name="살사")
    assert posts[0]["source_category"] is None


def test_every_other_field_on_the_record_is_unchanged():
    night = _lesson(33, "바차타/살사", "MAX NIGHT Free Salsa On1 Class")
    post = di.parse_list(_page([night]), LIST_URL, genre_name="살사")[0]
    assert post["source_url"] == "https://danceinfo.net/lessons/33"
    assert post["body"] == ""
    assert post["published_at"] is None
    assert post["acquisition_quality"] == "METADATA_ONLY"
    assert post["source_category_label"] == "출빠정보"
