"""v0.96.10 - the source's own category stops being thrown away.

danceinfo.net files every listing under a category of its own and keeps it on
the listing object in the page's own hydration payload. ``parse_list()`` read
``title`` and ``genreName`` off that object and dropped the rest, so a site
that had already sorted its courses from its nights handed us the answer and
we discarded it - the exact mirror of the Naver structure-trust defect, which
invents a prior the source never gave.

Measured read-only against the live list pages before this was written, over
485 listings across 13 days:

    idx  name                    n   reading
     1   파티(페스티발)/...      54   EVENT
     2   출빠정보/...            91   EVENT
     3   정모                     1   EVENT
     4   오픈강습/...            10   (deliberately none)
     5   강습                   329   CLASS

and over the 70 danceinfo items Production had stored: 60 강습 - holding three
visible events, all three false positives - against ten listings in a 출빠정보
category, holding seven events, every one of them real and including both that
were public upcoming.

The reading is taken from ``categoryIdx``, the site's own stable numeric key,
and never from the label: ``categoryName`` is a compound - "출빠정보/강습" is a
night that also teaches and stays a night - so a substring test for 강습 would
throw away exactly the listings this release must protect.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "engine") not in sys.path:
    sys.path.insert(0, str(REPO / "engine"))

from src.classifier import SOURCE_CATEGORY_CLASS, SOURCE_CATEGORY_EVENT  # noqa: E402
from src.collectors.base import RawPostRecord  # noqa: E402

from runtime import danceinfo_discovery as di  # noqa: E402
from runtime import engine_ingest  # noqa: E402

LIST_URL = "https://danceinfo.net/lessons?genre=all&category=all&location=all"


def _page(next_data: dict) -> str:
    return (
        "<html><head></head><body>"
        f'<script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(next_data)}</script></body></html>"
    )


def _listing(**overrides):
    """One lesson object with the keys the real payload carries."""
    lesson = {
        "contentIdx": 3786,
        "genreName": "탱고",
        "categoryIdx": 5,
        "categoryName": "강습",
        "title": "살사 소셜패턴",
        "date": "2026-09-19",
        "placeName": "",
    }
    lesson.update(overrides)
    return _page({"props": {"pageProps": {"initialDays": [
        {"date": lesson["date"], "lessons": [lesson]}
    ]}}})


# --- the mapping itself ----------------------------------------------------

@pytest.mark.parametrize("idx,expected", [
    (1, "EVENT"),   # 파티(페스티발)/출빠정보
    (2, "EVENT"),   # 출빠정보, 출빠정보/강습, 출빠정보/정모
    (3, "EVENT"),   # 정모
    (4, None),      # 오픈강습 - the boundary, deliberately unmapped
    (5, "CLASS"),   # 강습
])
def test_the_sites_own_key_decides_the_reading(idx, expected):
    assert di.source_category({"categoryIdx": idx}) == expected


@pytest.mark.parametrize("lesson", [
    {},                                  # no category at all
    {"categoryIdx": None},
    {"categoryIdx": "강습"},              # a label where the key belongs
    {"categoryIdx": 99},                 # a category the site invents later
])
def test_anything_unreadable_is_no_reading_at_all(lesson):
    """A category this release does not know must classify exactly as this
    module's output always has, not guess."""
    assert di.source_category(lesson) is None


def test_a_compound_label_is_never_substring_matched():
    """"출빠정보/강습" is a night that teaches. Reading the label instead of
    the key would file both of Production's public-upcoming danceinfo events
    as courses."""
    night = {"categoryIdx": 2, "categoryName": "출빠정보/강습"}
    assert "강습" in night["categoryName"]
    assert di.source_category(night) == "EVENT"
    festival = {"categoryIdx": 1, "categoryName": "파티(페스티발)/출빠정보/오픈강습"}
    assert di.source_category(festival) == "EVENT"


def test_the_runtimes_words_are_the_engines_words():
    """The engine package is stdlib-only and never imports runtime, so the two
    strings are written twice - the same arrangement classifier.py's own
    MIN_TEXT_FOR_IMAGE_TRUST already has. This is the test that holds them
    together."""
    assert di.SOURCE_CATEGORY_EVENT == SOURCE_CATEGORY_EVENT
    assert di.SOURCE_CATEGORY_CLASS == SOURCE_CATEGORY_CLASS


# --- the collector carries it ---------------------------------------------

def test_the_category_leaves_the_list_page_with_the_post():
    posts = di.parse_list(_listing(genreName="탱고", categoryIdx=5,
                                   categoryName="강습"), LIST_URL)
    assert len(posts) == 1
    assert posts[0]["source_category"] == "CLASS"
    assert posts[0]["source_category_label"] == "강습"


def test_the_label_travels_beside_the_reading():
    """So a person looking at a stored row can check the mapping was right
    rather than take it on trust."""
    posts = di.parse_list(_listing(categoryIdx=2, categoryName="출빠정보/강습"),
                          LIST_URL)
    assert posts[0]["source_category"] == "EVENT"
    assert posts[0]["source_category_label"] == "출빠정보/강습"


def test_a_listing_with_no_category_still_collects():
    """The keys are additions, not requirements: a payload without them is
    the payload this module read before v0.96.10 and must still parse."""
    page = _page({"props": {"pageProps": {"initialDays": [{
        "date": "2026-09-19",
        "lessons": [{"contentIdx": 1, "genreName": "탱고", "title": "밀롱가",
                     "date": "2026-09-19"}],
    }]}}})
    posts = di.parse_list(page, LIST_URL)
    assert len(posts) == 1
    assert posts[0]["source_category"] is None
    assert posts[0]["source_category_label"] is None
    assert posts[0]["source_url"] == "https://danceinfo.net/lessons/1"
    assert posts[0]["title"] == "밀롱가"


# --- and the runtime hands it to the engine -------------------------------

def test_the_runtime_puts_the_category_on_the_record():
    post = engine_ingest._to_raw_post(
        RawPostRecord,
        {"raw": {"source_category": "CLASS"}, "url": "https://x",
         "title": "살사 소셜패턴", "source_key": "S", "platform": "WEB"},
        None,
    )
    assert post.source_category == "CLASS"


def test_a_source_that_has_no_category_is_the_record_it_always_was():
    """T10. Every other collector - Daum boards, the Naver search adapters,
    K-TANGO, Miltang, TangoNOW - stores no such key, and nothing about their
    records or their classification changes."""
    post = engine_ingest._to_raw_post(
        RawPostRecord,
        {"raw": {"known_event_type": "MILONGA"}, "url": "https://x",
         "title": "수요 쁘롱가", "source_key": "S", "platform": "DAUM_CAFE"},
        None,
    )
    assert post.source_category is None
    assert post.known_event_type == "MILONGA"
    assert RawPostRecord(source_id="S", platform="WEB", source_url="u",
                         title="t", body="b").source_category is None
