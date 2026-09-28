"""v0.96.25: a DanceInfo post gets its own poster, and nobody else's.

A danceinfo.net lesson page serves the post's own poster and then a
"다가오는 추천 행사" carousel of *other* events' posters. `extract_content_images()`
scanned the whole page, so every one of those foreign posters was stored as this
post's `poster_candidates`, fetched, OCR'd, and handed to the extractor as
evidence about this event.

What that cost, measured on Production before the fix: one carousel poster
(`posters/4588/...`) was attached to **39 different source items**, another
(`posters/4418/...`) to 9. A *labelled* venue read off one of them
("장소: Ae\" (분당)") was the stored venue of six unrelated Events, and
"장소:홍턴지하2층6룸" of two. The OCR was correct; it was about a different party.

The page answers ownership itself. `initialLesson.posters` (plus `thumbnail`)
is this lesson's own image list, and `initialRelated.links[]` carries each
carousel image beside the `/lessons/<id>` it belongs to. Over 237 stored items
and 2,177 stored candidate URLs, plus 25 live pages chosen where the cheap rules
disagree, that split left no residue: 0 of 232 poster images fell outside it.

Two cheaper rules were measured and rejected:

* **`/posters/<lesson id>/`** - the lesson id in the URL is always
  `contentIdx` (25/25), but **25 of the 66** posters those pages declare as
  their own live under a different poster-id directory. The rule would drop a
  quarter of the real posters.
* **`w=3840`** - every own poster is served at `w=3840` (66/66) and every
  carousel poster at `w=640` (166/166), but **12** of the site's own chrome
  images are served at `w=3840` too.

So ownership is read from the source, and the URL actually fetched is still the
one the page serves - same origin, same bytes, same OCR cache entry.
"""

from __future__ import annotations

import json

import pytest

from runtime import acquisition

BASE = "https://danceinfo.net/lessons/4641"
OWN = "https://img.danceinfo.net/posters/4641/1789653229683-own.png"
OWN_SECOND = "https://img.danceinfo.net/posters/9999/1789653229684-own2.png"
RELATED = "https://img.danceinfo.net/posters/1576/1789562675770-related.png"
RELATED_TWO = "https://img.danceinfo.net/posters/4588/1789566571834-shared.jpg"
LOGO = "https://img.danceinfo.net/images/ci_default_logo.png"


def _proxied(url: str, width: str = "3840") -> str:
    import urllib.parse

    return (f"https://danceinfo.net/_next/image?url={urllib.parse.quote(url, safe='')}"
            f"&w={width}&q=75")


def _page(*, posters: list[str], thumbnail: str | None, dom: list[str],
          related: list[str] | None = None, content_idx: int = 4641) -> str:
    """A danceinfo lesson page in the shape the live site serves."""
    payload = {"props": {"pageProps": {
        "initialLesson": {
            "contentIdx": content_idx, "date": "2026-10-03",
            "placeName": "광주 J 라틴", "posters": posters, "thumbnail": thumbnail,
        },
        "initialRelated": {"sectionTitle": "🔥 다가오는 추천 행사", "links": [
            {"href": "/lessons/1576", "imageUrl": u} for u in (related or [])
        ]},
    }}}
    tags = "\n".join(f'<img src="{src}" alt="">' for src in dom)
    return (f'<html><head><script id="__NEXT_DATA__" type="application/json">'
            f'{json.dumps(payload, ensure_ascii=False)}</script></head>'
            f"<body>{tags}</body></html>")


# --- T1-T3: the carousel is not this post's ---------------------------------

def test_only_the_posts_own_poster_survives_the_carousel():
    """T1. The live shape: own poster at w=3840, then other events' at w=640."""
    raw = _page(posters=[OWN], thumbnail=OWN,
                dom=[_proxied(LOGO, "640"), _proxied(OWN, "3840"),
                     _proxied(RELATED, "640"), _proxied(RELATED_TWO, "640")],
                related=[RELATED, RELATED_TWO])
    assert acquisition.extract_content_images(raw, BASE) == [_proxied(OWN, "3840")]


def test_a_poster_under_another_id_is_still_this_posts_when_the_page_says_so():
    """T2, corrected. The lesson id is not the poster id: 25 of 66 own posters
    measured on live pages sit under a different `/posters/<id>/`. The payload,
    not the path, decides."""
    raw = _page(posters=[OWN_SECOND], thumbnail=OWN_SECOND,
                dom=[_proxied(OWN_SECOND, "3840"), _proxied(RELATED, "640")],
                related=[RELATED])
    assert acquisition.extract_content_images(raw, BASE) == [_proxied(OWN_SECOND, "3840")]


def test_a_carousel_poster_served_at_the_own_posters_width_is_still_dropped():
    """T3/T8. 19 stored items carry a carousel poster the page renders at
    w=3840; a width rule would keep every one of them."""
    raw = _page(posters=[OWN], thumbnail=OWN,
                dom=[_proxied(OWN, "3840"), _proxied(RELATED, "3840")],
                related=[RELATED])
    assert acquisition.extract_content_images(raw, BASE) == [_proxied(OWN, "3840")]


def test_site_chrome_at_the_own_posters_width_is_dropped_too():
    """12 of the site's own chrome images are served at w=3840."""
    raw = _page(posters=[OWN], thumbnail=OWN,
                dom=[_proxied(LOGO, "3840"), _proxied(OWN, "3840")],
                related=[])
    assert acquisition.extract_content_images(raw, BASE) == [_proxied(OWN, "3840")]


# --- T4: no own poster means no poster --------------------------------------

def test_a_post_with_no_poster_of_its_own_gets_none():
    """T4. Found on a real item (3831, `/lessons/4275`): the page renders a
    foreign poster at w=3840 and none of its own. "Use the neighbour's" is not
    a fallback - an empty list is the answer."""
    raw = _page(posters=[], thumbnail=None,
                dom=[_proxied(LOGO, "640"), _proxied(RELATED, "3840"),
                     _proxied(RELATED_TWO, "640")],
                related=[RELATED, RELATED_TWO])
    assert acquisition.danceinfo_own_images(raw) == []
    assert acquisition.extract_content_images(raw, BASE) == []


# --- T5: several own posters --------------------------------------------------

def test_every_own_poster_is_kept_in_the_order_the_page_serves_them():
    """T5. 39 stored items declare more than one own poster, up to eight."""
    third = "https://img.danceinfo.net/posters/4641/1789653229685-own3.png"
    raw = _page(posters=[OWN, OWN_SECOND, third], thumbnail=OWN,
                dom=[_proxied(LOGO, "640"), _proxied(OWN, "3840"),
                     _proxied(OWN_SECOND, "3840"), _proxied(RELATED, "640"),
                     _proxied(third, "3840")],
                related=[RELATED])
    assert acquisition.extract_content_images(raw, BASE) == [
        _proxied(OWN, "3840"), _proxied(OWN_SECOND, "3840"), _proxied(third, "3840")]


def test_the_thumbnail_counts_as_an_own_image_when_posters_is_empty():
    """T17. `thumbnail` is the same image `posters` names on every live page
    seen, but a page that carries only the thumbnail still names an own image."""
    raw = _page(posters=[], thumbnail=OWN,
                dom=[_proxied(OWN, "3840"), _proxied(RELATED, "640")], related=[RELATED])
    assert acquisition.danceinfo_own_images(raw) == [OWN]
    assert acquisition.extract_content_images(raw, BASE) == [_proxied(OWN, "3840")]


# --- T6-T7: the source-native field wins, whatever the DOM does -------------

def test_dom_order_does_not_decide_ownership():
    """T7. The carousel first, the own poster last."""
    raw = _page(posters=[OWN], thumbnail=OWN,
                dom=[_proxied(RELATED, "640"), _proxied(RELATED_TWO, "3840"),
                     _proxied(LOGO, "64"), _proxied(OWN, "3840")],
                related=[RELATED, RELATED_TWO])
    assert acquisition.extract_content_images(raw, BASE) == [_proxied(OWN, "3840")]


def test_a_missing_or_changed_width_parameter_does_not_matter():
    """T8. The identity is the image the URL points at, not how it is sized."""
    for variant in (_proxied(OWN, "1200"), _proxied(OWN, ""), OWN):
        raw = _page(posters=[OWN], thumbnail=OWN,
                    dom=[variant, _proxied(RELATED, "640")], related=[RELATED])
        assert acquisition.extract_content_images(raw, BASE) == [variant], variant


def test_an_own_poster_the_page_does_not_render_is_not_invented():
    """The URL stored is one the page actually serves. A payload poster with no
    `<img>` on the page is left out rather than synthesised into a direct
    `img.danceinfo.net` fetch this project has never made."""
    raw = _page(posters=[OWN, OWN_SECOND], thumbnail=OWN,
                dom=[_proxied(OWN, "3840"), _proxied(RELATED, "640")], related=[RELATED])
    assert acquisition.extract_content_images(raw, BASE) == [_proxied(OWN, "3840")]


# --- T9-T14: nothing foreign reaches the extractor --------------------------

FOREIGN_OCR_FIELDS = [
    ("venue", "장소: Ae\" (분당)"),
    ("time", "19:00 ~ 23:00"),
    ("fee", "입장료 13,000원"),
    ("date", "2026-09-26"),
    ("event word", "밀롱가 소셜 파티"),
]


@pytest.mark.parametrize("field, _text", FOREIGN_OCR_FIELDS)
def test_a_foreign_posters_ocr_can_never_be_read_for_this_post(field, _text):
    """T9/T11/T12/T13/T14. The guarantee is structural, not a judgement made
    later: the foreign image is never in `poster_candidates`, so
    `engine_ingest._gather_image_texts()` has nothing to fetch for it and the
    extractor is never handed its text at all."""
    raw = _page(posters=[OWN], thumbnail=OWN,
                dom=[_proxied(OWN, "3840"), _proxied(RELATED, "640")], related=[RELATED])
    kept = acquisition.extract_content_images(raw, BASE)
    assert all(RELATED not in acquisition._served_image_target(u) for u in kept), field


def test_the_posts_own_poster_is_still_available_for_every_field():
    """T10. The fix removes foreign evidence, not the post's own: whatever the
    own poster says about venue, time, date or fee still reaches the extractor."""
    raw = _page(posters=[OWN], thumbnail=OWN,
                dom=[_proxied(OWN, "3840"), _proxied(RELATED, "640")], related=[RELATED])
    kept = acquisition.extract_content_images(raw, BASE)
    assert [acquisition._served_image_target(u) for u in kept] == [OWN]


# --- T21: no other host changes ---------------------------------------------

def test_a_page_that_is_not_a_danceinfo_lesson_page_is_scanned_as_before():
    """T21. `danceinfo_own_images()` answers None for every other host, so Daum,
    K-TANGO, Miltang, TangoNOW and an unknown WEB board keep exactly the
    behaviour they had."""
    raw = ('<html><body><img src="https://t1.daumcdn.net/cafeattach/a.jpg">'
           '<img src="/relative/b.png"></body></html>')
    assert acquisition.danceinfo_own_images(raw) is None
    assert acquisition.extract_content_images(raw, "https://cafe.daum.net/x/y/1") == [
        "https://t1.daumcdn.net/cafeattach/a.jpg",
        "https://cafe.daum.net/relative/b.png",
    ]


def test_the_template_board_boundary_still_scopes_a_daum_post():
    """v0.84.3's own contract, unchanged - the boundary path is reached exactly
    when it was before, because the danceinfo reader declined."""
    raw = ('<html><img src="https://host/nav.png">'
           '<div class="bbsDetailContent"><img src="https://host/poster.jpg"></div>'
           '<footer><img src="https://host/footer.png"></footer></html>')
    images = acquisition.extract_content_images(raw, "https://cafe.daum.net/x/y/1")
    assert "https://host/poster.jpg" in images


def test_a_danceinfo_page_without_the_payload_is_scanned_as_before():
    """A lesson URL whose page did not hydrate (an error shell, a schema
    change) falls through to the scan rather than silently storing nothing."""
    raw = '<html><body><img src="https://img.danceinfo.net/posters/1/a.png"></body></html>'
    assert acquisition.danceinfo_own_images(raw) is None
    assert acquisition.extract_content_images(raw, BASE) == [
        "https://img.danceinfo.net/posters/1/a.png"]


def test_a_payload_that_is_not_a_lesson_page_declines():
    raw = ('<html><head><script id="__NEXT_DATA__" type="application/json">'
           '{"props":{"pageProps":{"initialList":[]}}}</script></head><body>'
           '<img src="https://img.danceinfo.net/posters/1/a.png"></body></html>')
    assert acquisition.danceinfo_own_images(raw) is None


def test_a_broken_payload_declines_rather_than_raising():
    raw = ('<html><head><script id="__NEXT_DATA__" type="application/json">'
           'not json</script></head><body>'
           '<img src="https://img.danceinfo.net/posters/1/a.png"></body></html>')
    assert acquisition.danceinfo_own_images(raw) is None
    assert acquisition.extract_content_images(raw, BASE) == [
        "https://img.danceinfo.net/posters/1/a.png"]


# --- the payload body reader still works off the shared helper ---------------

def test_the_field_reader_and_the_image_reader_read_one_payload():
    """Both questions this module asks the payload go through
    `_danceinfo_lesson()`, so a page either hydrates for both or for neither."""
    raw = _page(posters=[OWN], thumbnail=OWN, dom=[_proxied(OWN, "3840")])
    body = acquisition.danceinfo_payload_body(raw)
    assert "2026-10-03" in body and "장소 광주 J 라틴" in body
    assert acquisition.danceinfo_own_images(raw) == [OWN]
