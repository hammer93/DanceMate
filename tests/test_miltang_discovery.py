"""Discovery for Miltang (v0.83): SSR HTML, JSON-LD-first detail parsing.

Fixtures are hand-built, shaped like the real pages this module reads (list
cards, detail `<dl>` rows, JSON-LD blocks) - trimmed to just what the parser
uses, and with personal contact details (phone numbers, reservation links)
left out entirely rather than sanitized in place, per this task's own
instruction not to carry them into a fixture at all.
"""

from __future__ import annotations

import io

import pytest

from runtime import miltang_discovery as md

LIST_URL = "https://miltang.com/milongas?week=2026-08-31&date=2026-09-05"
NOTICES_URL = "https://miltang.com/notices"


def _detail_page(
    *, ld_json: str | None, title: str = "The PISTA Milonga",
    badge: str | None = "매주 토요일",
    date_row: str = "2026. 9. 5(토)",
    time_row: str | None = "19:00~23:00",
    place_row: str | None = (
        '<p class="font-bold">PISTA 피스타</p>'
        '<p class="text-fg3 text-xs mt-0.5">서울 월드컵북로6길 49 지하1층</p>'
    ),
    org_row: str | None = "PISTA",
    link_row: str | None = (
        '<a href="https://www.facebook.com/jiyu.banny">https://www.facebook.com/jiyu.banny</a>'
        '<a href="https://www.instagram.com/pista.tango/">https://www.instagram.com/pista.tango/</a>'
    ),
    description: str | None = None,
) -> str:
    rows = []
    rows.append(f'<div><dt>DATE</dt><dd>{date_row}</dd></div>')
    if time_row is not None:
        rows.append(f'<div><dt>TIME</dt><dd>{time_row}</dd></div>')
    if place_row is not None:
        rows.append(f'<div><dt>PLACE</dt><dd>{place_row}</dd></div>')
    if org_row is not None:
        rows.append(f'<div><dt>ORG</dt><dd>{org_row}</dd></div>')
    if link_row is not None:
        rows.append(f'<div><dt>LINK</dt><dd>{link_row}</dd></div>')
    badge_html = (
        f'<span class="inline-block text-xs font-bold text-brand-deep bg-brand-tint '
        f'px-2.5 py-1 rounded">{badge}</span>' if badge else ""
    )
    description_html = (
        f'<h3 class="text-xs font-bold text-brand tracking-widest">DESCRIPTION</h3>'
        f'<div class="text-sm ql-content">{description}</div>' if description else ""
    )
    ld_block = (
        f'<script type="application/ld+json">{ld_json}</script>' if ld_json else ""
    )
    return f"""<!DOCTYPE html><html><head><title>{title} — Miltang</title></head>
<body>
{ld_block}
<div>{badge_html}<h2 class="text-2xl font-bold text-fg1 mt-2 leading-snug">{title}</h2></div>
<dl class="border-t border-b border-line-soft py-4 space-y-2 text-sm">
{''.join(rows)}
</dl>
{description_html}
</body></html>"""


_MILONGA_LD = (
    '{"@context":"https://schema.org","@type":"Event","name":"The PISTA Milonga",'
    '"url":"https://miltang.com/milongas/731","startDate":"2026-09-05",'
    '"location":{"@type":"Place","name":"PISTA 피스타",'
    '"address":{"@type":"PostalAddress","streetAddress":"서울 월드컵북로6길 49 지하1층"}},'
    '"organizer":{"@type":"Organization","name":"PISTA"}}'
)

_NOTICE_LD = (
    '{"@context":"https://schema.org","@type":"Event","name":"BUSAN TANGO FESTIVAL",'
    '"startDate":"2026-10-21","endDate":"2026-10-29",'
    '"location":{"@type":"Place","name":"Detango 데땅고",'
    '"address":{"@type":"PostalAddress","streetAddress":"부산광역시 부산진구 서면로68번길 41"}}}'
)


# --- list page: detail-URL discovery only ------------------------------------

def _list_page(*ids: str, date_text: str = "2026년 9월 5일") -> str:
    cards = "".join(f'<a href="/milongas/{i}">card {i}</a>' for i in ids)
    return f"""<!DOCTYPE html><html><body>
<span>{date_text}</span>
{cards}
</body></html>"""


def test_list_page_yields_detail_urls():
    html_text = _list_page("731", "513", "734")
    urls = md._extract_detail_urls(html_text, LIST_URL, "milongas")
    assert urls == [
        "https://miltang.com/milongas/731",
        "https://miltang.com/milongas/513",
        "https://miltang.com/milongas/734",
    ]


def test_duplicate_detail_urls_are_removed():
    """A recurring ("매주") milonga's card links the SAME id on every day it
    recurs into - the list stage must not fetch its detail page twice."""
    html_text = _list_page("731", "513", "731")
    urls = md._extract_detail_urls(html_text, LIST_URL, "milongas")
    assert urls == [
        "https://miltang.com/milongas/731",
        "https://miltang.com/milongas/513",
    ]


def test_parse_list_returns_metadata_only_stubs():
    """The generic snapshot/dry-run entry point - detail URLs only, no
    body. Real field data comes from parse_detail()/discover()."""
    posts = md.parse_list(_list_page("731"), LIST_URL)
    assert len(posts) == 1
    assert posts[0]["source_url"] == "https://miltang.com/milongas/731"
    assert posts[0]["acquisition_quality"] == "METADATA_ONLY"
    assert posts[0]["body"] == ""


def test_parse_list_rejects_an_unrecognised_list_url():
    with pytest.raises(md.DiscoveryError):
        md.parse_list(_list_page("731"), "https://miltang.com/places")


def test_notices_list_yields_detail_urls_without_any_date_scoping():
    html_text = """<!DOCTYPE html><html><body>
<a href="/notices/3">a</a><a href="/notices/12">b</a>
</body></html>"""
    urls = md._extract_detail_urls(html_text, NOTICES_URL, "notices")
    assert urls == ["https://miltang.com/notices/3", "https://miltang.com/notices/12"]


# --- detail page: JSON-LD-first parsing --------------------------------------

def test_event_json_ld_is_parsed_first():
    page = _detail_page(ld_json=_MILONGA_LD)
    post = md.parse_detail(page, "https://miltang.com/milongas/731")
    assert post["title"] == "The PISTA Milonga"
    assert "2026년 9월 5일" in post["body"]
    assert "장소: PISTA 피스타 (서울 월드컵북로6길 49 지하1층)" in post["body"]
    assert "주최: PISTA" in post["body"]


def test_notice_json_ld_is_parsed_including_a_date_range():
    page = _detail_page(
        ld_json=_NOTICE_LD, title="BUSAN TANGO FESTIVAL", badge="행사",
        date_row="2026. 10. 21(수) ~ 2026. 10. 29(목)", time_row=None,
        place_row=(
            '<p class="font-bold">Detango 데땅고</p>'
            '<p class="text-fg3 text-xs mt-0.5">부산광역시 부산진구 서면로68번길 41</p>'
        ),
        org_row=None,
        link_row='<a href="https://www.facebook.com/share/p/1ANKLmedXp/">https://www.facebook.com/share/p/1ANKLmedXp/</a>',
        description="DE TANGO 17th Anniversary",
    )
    post = md.parse_detail(page, "https://miltang.com/notices/12")
    assert post["title"] == "BUSAN TANGO FESTIVAL"
    # The JSON-LD startDate (21st) wins, not the DATE row's own text.
    assert "2026년 10월 21일" in post["body"]
    assert "장소: Detango 데땅고 (부산광역시 부산진구 서면로68번길 41)" in post["body"]
    assert "DE TANGO 17th Anniversary" in post["body"]
    # No ORG row on this notice - must not appear as an empty "주최:" line.
    assert "주최:" not in post["body"]


def test_html_time_supplements_json_ld_since_json_ld_never_carries_it():
    """Confirmed live: JSON-LD `startDate` is date-only. TIME always comes
    from the `<dl>` row, never invented from anything else."""
    page = _detail_page(ld_json=_MILONGA_LD, time_row="19:00~23:00")
    post = md.parse_detail(page, "https://miltang.com/milongas/731")
    assert "시간: 19:00~23:00" in post["body"]


def test_overnight_time_folds_the_same_way_as_every_other_source():
    page = _detail_page(ld_json=_MILONGA_LD, time_row="23:30~28:30")
    post = md.parse_detail(page, "https://miltang.com/milongas/734")
    assert "시간: 23:30~04:30" in post["body"]


def test_no_time_row_leaves_no_time_rather_than_guessing():
    """A multi-day festival notice has no single time-of-day - absence must
    stay absent, not default to something."""
    page = _detail_page(ld_json=_NOTICE_LD, time_row=None)
    post = md.parse_detail(page, "https://miltang.com/notices/12")
    assert "시간:" not in post["body"]


def test_recurrence_label_is_read_from_the_badge():
    page = _detail_page(ld_json=_MILONGA_LD, badge="매주 토요일")
    post = md.parse_detail(page, "https://miltang.com/milongas/731")
    assert "반복: 매주 토요일" in post["body"]


def test_a_notices_type_badge_is_not_mistaken_for_a_recurrence_label():
    page = _detail_page(ld_json=_NOTICE_LD, badge="행사", time_row=None)
    post = md.parse_detail(page, "https://miltang.com/notices/12")
    assert "반복:" not in post["body"]


def test_organizer_is_optional_and_absence_is_silent():
    # _NOTICE_LD carries no "organizer" key at all (confirmed live: BUSAN
    # TANGO FESTIVAL's own JSON-LD has none) - _MILONGA_LD would not
    # exercise this, since its JSON-LD organizer would win regardless of
    # org_row.
    page = _detail_page(ld_json=_NOTICE_LD, org_row=None, time_row=None)
    post = md.parse_detail(page, "https://miltang.com/milongas/731")
    assert "주최:" not in post["body"]


def test_original_link_extraction_preserves_every_channel():
    page = _detail_page(ld_json=_MILONGA_LD, link_row=(
        '<a href="https://open.kakao.com/o/g3wPepNh">k</a>'
        '<a href="https://www.facebook.com/jiyu.banny">f</a>'
        '<a href="https://www.instagram.com/pista.tango/">i</a>'
    ))
    post = md.parse_detail(page, "https://miltang.com/milongas/731")
    assert "open.kakao.com/o/g3wPepNh" in post["body"]
    assert "www.facebook.com/jiyu.banny" in post["body"]
    assert "www.instagram.com/pista.tango" in post["body"]


@pytest.mark.parametrize("url,expected", [
    ("https://www.facebook.com/jiyu.banny", True),
    ("https://www.instagram.com/pista.tango/", True),
    ("https://cafe.daum.net/amigostudio", True),
    ("https://open.kakao.com/o/g3wPepNh", True),
    ("https://www.facebook.com/share/p/1ANKLmedXp/", False),
    ("https://www.facebook.com/groups/760893148271767/posts/1446442926383449/", False),
])
def test_profile_or_root_link_classification(url, expected):
    assert md._is_profile_or_root_link(url) is expected


def test_a_profile_link_is_never_promoted_to_source_url():
    """Even when the ONLY original link on the page is a bare profile -
    source_url must still be this module's own Miltang detail URL, never
    the profile (Section 5/6)."""
    page = _detail_page(
        ld_json=_MILONGA_LD,
        link_row='<a href="https://www.facebook.com/jiyu.banny">f</a>',
    )
    post = md.parse_detail(page, "https://miltang.com/milongas/731")
    assert post["source_url"] == "https://miltang.com/milongas/731"
    assert "facebook.com/jiyu.banny" not in post["source_url"]


def test_no_json_ld_falls_back_to_the_dl_rows():
    page = _detail_page(ld_json=None)
    post = md.parse_detail(page, "https://miltang.com/milongas/731")
    assert post["title"] == "The PISTA Milonga"
    assert "2026년 9월 5일" in post["body"]
    assert "장소: PISTA 피스타 (서울 월드컵북로6길 49 지하1층)" in post["body"]


def test_malformed_json_ld_is_not_fatal():
    page = _detail_page(ld_json="{not json}")
    post = md.parse_detail(page, "https://miltang.com/milongas/731")
    assert post is not None
    assert post["title"] == "The PISTA Milonga"


def test_a_record_with_no_date_anywhere_is_dropped_not_guessed():
    page = _detail_page(ld_json=None, date_row="날짜 미정")
    post = md.parse_detail(page, "https://miltang.com/milongas/999")
    assert post is None


def test_a_record_with_no_title_anywhere_is_dropped():
    page = "<html><body><dl><div><dt>DATE</dt><dd>2026. 9. 5(토)</dd></div></dl></body></html>"
    assert md.parse_detail(page, "https://miltang.com/milongas/1") is None


def test_published_at_is_always_none():
    """Neither created_at nor updated_at is present on a detail page
    (confirmed live) - never guessed from the sitemap's own lastmod."""
    page = _detail_page(ld_json=_MILONGA_LD)
    post = md.parse_detail(page, "https://miltang.com/milongas/731")
    assert post["published_at"] is None


@pytest.mark.parametrize("region_name,venue,address", [
    ("서울", "PISTA 피스타", "서울 월드컵북로6길 49 지하1층"),
    ("부산", "Detango 데땅고", "부산광역시 부산진구 서면로68번길 41"),
])
def test_seoul_and_busan_samples_both_parse_cleanly(region_name, venue, address):
    ld = (
        '{"@context":"https://schema.org","@type":"Event","name":"샘플",'
        f'"startDate":"2026-09-05","location":{{"@type":"Place","name":"{venue}",'
        f'"address":{{"@type":"PostalAddress","streetAddress":"{address}"}}}}}}'
    )
    page = _detail_page(ld_json=ld, title="샘플")
    post = md.parse_detail(page, f"https://miltang.com/milongas/{region_name}")
    assert venue in post["body"]
    assert address in post["body"]


# --- fetching / discover() ---------------------------------------------------

class _Resp(io.BytesIO):
    def __init__(self, text: str):
        super().__init__(text.encode("utf-8"))
        self.headers = _Headers()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Headers:
    def get_content_charset(self):
        return "utf-8"


def test_discover_honours_robots_disallow(monkeypatch):
    monkeypatch.setattr(md.acquisition, "robots_allows", lambda url, **kw: False)
    monkeypatch.setattr(md, "_seoul_today", lambda: __import__("datetime").date(2026, 9, 5))
    with pytest.raises(md.DiscoveryError):
        md.discover(LIST_URL, source_id="SRC-W-005", opener=lambda *a, **kw: _Resp(""))


def test_an_http_error_is_reported_as_a_discovery_error(monkeypatch):
    import urllib.error

    monkeypatch.setattr(md.acquisition, "robots_allows", lambda url, **kw: True)
    monkeypatch.setattr(md, "_seoul_today", lambda: __import__("datetime").date(2026, 9, 5))

    def opener(request, timeout=None):
        raise urllib.error.HTTPError(LIST_URL, 500, "Server Error", {}, None)

    with pytest.raises(md.DiscoveryError):
        md.discover(LIST_URL, source_id="SRC-W-005", opener=opener)


def test_discover_rejects_a_list_page_that_lands_on_the_wrong_day(monkeypatch):
    """Confirmed live: `date=` without a matching `week=` silently falls
    back to the current week's Monday - discover() must catch that rather
    than collect the wrong day's events under the requested date's label."""
    monkeypatch.setattr(md.acquisition, "robots_allows", lambda url, **kw: True)
    monkeypatch.setattr(md, "_seoul_today", lambda: __import__("datetime").date(2026, 9, 12))

    def opener(request, timeout=None):
        # Always renders "2026년 8월 31일" regardless of what was requested -
        # the exact live drift this module found.
        return _Resp('<html><body><span>2026년 8월 31일</span></body></html>')

    with pytest.raises(md.DiscoveryError, match="rendered"):
        md.discover(LIST_URL, source_id="SRC-W-005", opener=opener)


def test_discover_raises_when_the_page_has_no_readable_day_header(monkeypatch):
    monkeypatch.setattr(md.acquisition, "robots_allows", lambda url, **kw: True)
    monkeypatch.setattr(md, "_seoul_today", lambda: __import__("datetime").date(2026, 9, 5))
    opener = lambda request, timeout=None: _Resp("<html><body>no date header here</body></html>")
    with pytest.raises(md.DiscoveryError, match="no readable day header"):
        md.discover(LIST_URL, source_id="SRC-W-005", opener=opener)


def test_discover_fetches_one_day_by_default_and_tags_source_and_platform(monkeypatch):
    monkeypatch.setattr(md.acquisition, "robots_allows", lambda url, **kw: True)
    monkeypatch.setattr(md, "_seoul_today", lambda: __import__("datetime").date(2026, 9, 5))
    calls = []

    def opener(request, timeout=None):
        calls.append(request.full_url)
        if "/milongas/731" in request.full_url:
            return _Resp(_detail_page(ld_json=_MILONGA_LD))
        return _Resp(_list_page("731"))

    posts = md.discover(LIST_URL, source_id="SRC-W-005", opener=opener)
    assert len(posts) == 1
    assert posts[0]["source_id"] == "SRC-W-005"
    assert posts[0]["platform"] == "WEB"
    # One list request (today) + one detail request.
    assert len(calls) == 2


def test_discover_widens_across_days_ahead_with_matching_week_and_date(monkeypatch):
    """2026-09-05 (Sat) and 2026-09-06 (Sun) fall in the SAME ISO week
    (Monday 2026-08-31 through Sunday 2026-09-06) - both dated requests must
    carry that same `week=`, matching what the site itself expects."""
    monkeypatch.setattr(md.acquisition, "robots_allows", lambda url, **kw: True)
    monkeypatch.setattr(md, "_seoul_today", lambda: __import__("datetime").date(2026, 9, 5))
    seen_list_urls = []

    def opener(request, timeout=None):
        url = request.full_url
        if "/milongas/" in url and url.rsplit("/", 1)[-1].isdigit():
            return _Resp(_detail_page(ld_json=_MILONGA_LD))
        seen_list_urls.append(url)
        if "date=2026-09-05" in url:
            return _Resp(_list_page("731", date_text="2026년 9월 5일"))
        if "date=2026-09-06" in url:
            return _Resp(_list_page("513", date_text="2026년 9월 6일"))
        raise AssertionError(f"unexpected list url: {url}")

    posts = md.discover(LIST_URL, source_id="SRC-W-005", opener=opener, days_ahead=1)
    assert {p["source_url"] for p in posts} == {
        "https://miltang.com/milongas/731", "https://miltang.com/milongas/513",
    }
    assert any("week=2026-08-31" in u and "date=2026-09-05" in u for u in seen_list_urls)
    assert any("week=2026-08-31" in u and "date=2026-09-06" in u for u in seen_list_urls)


def test_days_ahead_is_clamped_to_a_sane_maximum(monkeypatch):
    monkeypatch.setattr(md.acquisition, "robots_allows", lambda url, **kw: True)
    monkeypatch.setattr(md, "_seoul_today", lambda: __import__("datetime").date(2026, 9, 5))
    fetched_days = set()

    def opener(request, timeout=None):
        url = request.full_url
        if "/milongas/" in url and url.rsplit("/", 1)[-1].isdigit():
            return _Resp(_detail_page(ld_json=_MILONGA_LD))
        import re as _re
        m = _re.search(r"date=(\d{4}-\d{2}-\d{2})", url)
        fetched_days.add(m.group(1))
        return _Resp("<html><body>" + m.group(1).replace("-0", "-").replace("2026-9", "2026년 9월").replace("2026-1", "2026년 1") + "</body></html>")

    with pytest.raises(md.DiscoveryError):
        # 9999 must clamp to MAX_DAYS_AHEAD, not fetch 10000 pages - this
        # fixture's own opener deliberately can't render every real date
        # header correctly, so it is expected to fail fast on a mismatch
        # rather than run away; the assertion below is what actually matters.
        md.discover(LIST_URL, source_id="SRC-W-005", opener=opener, days_ahead=9999)
    assert len(fetched_days) <= md.MAX_DAYS_AHEAD + 1


def test_notices_list_is_fetched_once_regardless_of_days_ahead(monkeypatch):
    monkeypatch.setattr(md.acquisition, "robots_allows", lambda url, **kw: True)
    calls = []

    def opener(request, timeout=None):
        calls.append(request.full_url)
        if "/notices/" in request.full_url:
            return _Resp(_detail_page(
                ld_json=_NOTICE_LD, title="BUSAN TANGO FESTIVAL", badge="행사",
                time_row=None, org_row=None,
            ))
        return _Resp("""<html><body>
<a href="/notices/12">a</a>
</body></html>""")

    posts = md.discover(NOTICES_URL, source_id="SRC-W-005", opener=opener, days_ahead=13)
    assert len(posts) == 1
    # One list fetch + one detail fetch, days_ahead ignored entirely.
    assert len(calls) == 2


def test_max_detail_fetches_bounds_a_very_large_list(monkeypatch):
    monkeypatch.setattr(md.acquisition, "robots_allows", lambda url, **kw: True)
    monkeypatch.setattr(md, "_seoul_today", lambda: __import__("datetime").date(2026, 9, 5))
    many_ids = [str(i) for i in range(md.MAX_DETAIL_FETCHES + 50)]

    def opener(request, timeout=None):
        url = request.full_url
        if "/milongas/" in url and url.rsplit("/", 1)[-1].isdigit():
            return _Resp(_detail_page(ld_json=_MILONGA_LD))
        return _Resp(_list_page(*many_ids, date_text="2026년 9월 5일"))

    posts = md.discover(LIST_URL, source_id="SRC-W-005", opener=opener)
    assert len(posts) == md.MAX_DETAIL_FETCHES
