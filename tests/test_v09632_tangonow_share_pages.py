"""v0.96.32: TangoNOW, read through the surface its operator publishes.

The user asked a specific question: "TangoNOW는 로고를 클릭해야 정상적으로
동작하는 것 같다." Measured on 2026-10-13 in a real logged-out headless
Chrome, the answer is no. The click is an `<a href="/">` on a page already at
`/`; after it the URL is unchanged, the card count is unchanged (zero before,
zero after), and **no network request is issued at all** - only an ad banner
rotates. The list is empty because the site's own data endpoints refuse us:

    /                        200, a 7.7KB JS shell holding no event data
    /?mode=event             200, byte-identical to /
    /events-snapshot-week    401 {"error":"appcheck_required"}
    /events-bundle (CF)      401
    Firestore documents.list 403 (the public read rule, withdrawn 2026-09-25)

and the page itself renders the site's own "이 날 일정 없어요" to a visitor who
is not signed in. There is no credential we are entitled to, and the bundle
is disallowed by robots.txt on the operator's explicit instruction.

What the same robots.txt keeps open, and names, is `/e/` and the sitemap that
lists it. These tests pin that reading and the robots decisions behind it, so
a later change cannot quietly start reading something the operator closed.

Every fixture here is a verbatim capture from ktnow.kr on 2026-10-13.
"""

from __future__ import annotations

import io
import urllib.error
import urllib.request

import pytest

from runtime import collectors, robots, tangonow_discovery, tangonow_share_discovery

# ktnow.kr/robots.txt, 2026-10-13.
ROBOTS_TXT = """User-agent: *
Allow: /
Disallow: /admin/
# [데이터 보호 2026-09-12] 전체 이벤트 번들 JSON 은 수집 대상 아님(권고). /events-snapshot 은 정확히 그 경로(+쿼리)만.
# /events-snapshot-week 는 Googlebot 홈 렌더가 쓰므로 허용 유지. /e/ 공유 페이지도 허용.
Disallow: /events-bundle
Disallow: /events-snapshot$
Disallow: /events-snapshot?

# Sitemap
Sitemap: https://ktnow.kr/sitemap.xml
Sitemap: https://ktnow.kr/sitemap-events.xml

# Crawl-delay
Crawl-delay: 1
"""

SHARE_A = ("https://ktnow.kr/e/occ_4fff34783ed60051844e0b356e1aca86530e9b02"
           "da04653fc16d4342b7c18f79")
SHARE_B = ("https://ktnow.kr/e/occ_5cb355e96b85714174db9ee764cafe609da0e169"
           "803615db48ea04b4fc7b46c9")

SITEMAP_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{SHARE_A}</loc>
    <lastmod>2026-10-10T08:05:50.910Z</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.7</priority>
  </url>
  <url>
    <loc>{SHARE_B}</loc>
    <lastmod>2026-10-07T09:38:04.439Z</lastmod>
  </url>
</urlset>
"""

# The ORANGE share page, head only - the body is a one-line redirect stub.
SHARE_A_HTML = f"""<!doctype html>
<html lang="ko"><head>
  <title>ORANGE</title>
  <meta name="description" content="2026-10-13(화) · 19:30~24:00 · Andante · DJ Cya">
  <link rel="canonical" href="{SHARE_A}">
  <meta property="og:title" content="ORANGE">
  <script type="application/ld+json">{{"@context":"https://schema.org",
"@type":"Event","name":"ORANGE","url":"{SHARE_A}",
"description":"2026-10-13(화) · 19:30~24:00 · Andante · DJ Cya",
"startDate":"2026-10-13T19:30:00+09:00","endDate":"2026-10-14T00:00:00+09:00",
"eventStatus":"https://schema.org/EventScheduled",
"eventAttendanceMode":"https://schema.org/OfflineEventAttendanceMode",
"inLanguage":"ko-KR","location":{{"@type":"Place","name":"Andante"}},
"organizer":{{"@type":"Organization","name":"GaEa kim"}}}}</script>
</head><body><main><h1>ORANGE</h1></main></body></html>
"""

SHARE_B_HTML = f"""<!doctype html>
<html lang="ko"><head><title>Solo Tango 화요정모</title>
  <script type="application/ld+json">{{"@context":"https://schema.org",
"@type":"Event","name":"SOLO TANGO | Solo Tango 화요정모","url":"{SHARE_B}",
"description":"2026-10-13(화) · 20:00~23:30 · O Nada · DJ 프로디고",
"startDate":"2026-10-13T20:00:00+09:00","endDate":"2026-10-13T23:30:00+09:00",
"eventStatus":"https://schema.org/EventScheduled",
"location":{{"@type":"Place","name":"O Nada"}},
"organizer":{{"@type":"Organization","name":"솔로땅고"}}}}</script>
</head><body><main><h1>SOLO TANGO</h1></main></body></html>
"""

PAGES = {
    "https://ktnow.kr/sitemap-events.xml": SITEMAP_XML,
    SHARE_A: SHARE_A_HTML,
    SHARE_B: SHARE_B_HTML,
}


class _Response:
    def __init__(self, text: str):
        self._text = text
        self.headers = type("H", (), {"get_content_charset": lambda self: "utf-8"})()

    def read(self):
        return self._text.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener(pages=None, fail=()):
    """An opener over the captured pages. Longest key first, so a prefix of
    another URL never answers for it (v0.96.31's own fixture lesson)."""
    pages = PAGES if pages is None else pages

    def open_url(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url in fail:
            raise urllib.error.HTTPError(url, 503, "Service Unavailable", {}, None)
        for key in sorted(pages, key=len, reverse=True):
            if url == key:
                return _Response(pages[key])
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    return open_url


@pytest.fixture(autouse=True)
def _robots(monkeypatch):
    """Answer robots.txt from the captured file, never over the network."""
    from runtime import acquisition

    monkeypatch.setattr(
        acquisition, "robots_allows",
        lambda url, user_agent="DanceMate": robots.allows(
            ROBOTS_TXT, url, user_agent))


# --- T1: what the operator's robots.txt actually permits --------------------

@pytest.mark.parametrize("path,allowed", [
    ("/", True),
    ("/e/occ_4fff3478", True),
    ("/sitemap-events.xml", True),
    ("/sitemap.xml", True),
    # The operator's own data-protection lines, in both their shapes.
    ("/events-bundle", False),
    ("/events-bundle?days=14", False),
    ("/events-snapshot", False),
    ("/events-snapshot?days=7", False),
    # Kept open, and the comment says why: Googlebot's home render uses it.
    ("/events-snapshot-week", True),
    ("/admin/sources", False),
])
def test_robots_decisions_are_read_as_written(path, allowed):
    assert robots.allows(ROBOTS_TXT, "https://ktnow.kr" + path, "DanceMate") is allowed


def test_a_disallowed_path_is_never_fetched(monkeypatch):
    def refuse(request, timeout=None):
        raise AssertionError("a disallowed URL must not reach the network")

    with pytest.raises(tangonow_discovery.DiscoveryError, match="robots"):
        tangonow_discovery._fetch_text(
            "https://ktnow.kr/events-bundle", timeout=5, opener=refuse,
            accept="application/json")


# --- T2: the sitemap ---------------------------------------------------------

def test_the_sitemap_yields_its_share_pages():
    assert tangonow_discovery.parse_sitemap(
        SITEMAP_XML, tangonow_discovery.SITEMAP_URL) == [SHARE_A, SHARE_B]


def test_only_share_pages_are_taken_from_a_sitemap():
    xml = ("<urlset><url><loc>https://ktnow.kr/</loc></url>"
           "<url><loc>https://ktnow.kr/?mode=event</loc></url>"
           f"<url><loc>{SHARE_A}</loc></url>"
           "<url><loc>https://ktnow.kr/events-bundle</loc></url></urlset>")
    assert tangonow_discovery.parse_sitemap(xml, "x") == [SHARE_A]


def test_a_repeated_loc_is_listed_once():
    xml = f"<urlset><url><loc>{SHARE_A}</loc></url>" \
          f"<url><loc>{SHARE_A}</loc></url></urlset>"
    assert tangonow_discovery.parse_sitemap(xml, "x") == [SHARE_A]


def test_something_that_is_not_a_sitemap_is_an_error():
    with pytest.raises(tangonow_discovery.DiscoveryError, match="not a sitemap"):
        tangonow_discovery.parse_sitemap("<html><body>nope</body></html>", "x")


# --- T3: one share page ------------------------------------------------------

def test_a_share_page_reads_as_the_event_it_renders():
    record = tangonow_discovery.parse_share_page(SHARE_A_HTML, SHARE_A)
    assert record["title"] == "ORANGE"
    assert record["source_url"] == SHARE_A
    assert record["acquisition_quality"] == "FETCHED_FULL"
    assert record["body"] == (
        "2026년 10월 13일 시간: 19:30~00:00 장소: Andante DJ: Cya 주최: GaEa kim")


def test_the_body_uses_the_labels_the_extractor_already_reads():
    from engine.src import extraction_rules

    record = tangonow_discovery.parse_share_page(SHARE_A_HTML, SHARE_A)
    reading = extraction_rules.extract_venue(record["body"])
    assert reading is not None and reading.name == "Andante"


def test_the_pages_own_description_is_not_carried_as_prose():
    """It restates the date and time already rendered above as fields."""
    record = tangonow_discovery.parse_share_page(SHARE_A_HTML, SHARE_A)
    assert "·" not in record["body"]
    assert record["body"].count("2026") == 1


def test_a_page_with_no_event_is_not_a_record():
    assert tangonow_discovery.parse_share_page(
        "<html><head><title>x</title></head><body></body></html>", SHARE_A) is None


def test_a_page_whose_event_states_no_date_is_not_a_record():
    html = ('<script type="application/ld+json">{"@type":"Event",'
            '"name":"No date"}</script>')
    assert tangonow_discovery.parse_share_page(html, SHARE_A) is None


def test_a_cancelled_occurrence_is_not_a_record():
    html = ('<script type="application/ld+json">{"@type":"Event","name":"x",'
            '"startDate":"2026-10-13T19:30:00+09:00",'
            '"eventStatus":"https://schema.org/EventCancelled"}</script>')
    assert tangonow_discovery.parse_share_page(html, SHARE_A) is None


def test_a_postponed_occurrence_is_not_a_record():
    html = ('<script type="application/ld+json">{"@type":"Event","name":"x",'
            '"startDate":"2026-10-13T19:30:00+09:00",'
            '"eventStatus":"https://schema.org/EventPostponed"}</script>')
    assert tangonow_discovery.parse_share_page(html, SHARE_A) is None


def test_a_date_only_event_keeps_its_date_and_claims_no_hour():
    html = ('<script type="application/ld+json">{"@type":"Event",'
            '"name":"BUSAN TANGO FESTIVAL","startDate":"2026-10-21",'
            '"location":{"@type":"Place","name":"데땅고"}}</script>')
    record = tangonow_discovery.parse_share_page(html, SHARE_A)
    assert record["body"] == "2026년 10월 21일 장소: 데땅고"


def test_nothing_is_invented_for_a_field_the_page_omits():
    html = ('<script type="application/ld+json">{"@type":"Event","name":"x",'
            '"startDate":"2026-10-30T20:00:00+09:00"}</script>')
    record = tangonow_discovery.parse_share_page(html, SHARE_A)
    assert record["body"] == "2026년 10월 30일 시간: 20:00"
    assert "장소" not in record["body"] and "원" not in record["body"]


def test_a_venue_in_the_descriptions_tail_is_not_read_as_a_dj():
    """A venue called `DJ Bar` occupies the last segment when there is no DJ."""
    html = ('<script type="application/ld+json">{"@type":"Event",'
            '"name":"Thursday night","startDate":"2026-10-30T20:00:00+09:00",'
            '"endDate":"2026-10-31T02:00:00+09:00",'
            '"location":{"@type":"Place","name":"DJ Bar"},'
            '"description":"2026-10-30(금) · 20:00~02:00 · DJ Bar"}'
            "</script>")
    record = tangonow_discovery.parse_share_page(html, SHARE_A)
    assert record["body"] == "2026년 10월 30일 시간: 20:00~02:00 장소: DJ Bar"
    assert "DJ:" not in record["body"]


def test_a_dj_is_read_only_from_the_descriptions_last_segment():
    html = ('<script type="application/ld+json">{"@type":"Event",'
            '"name":"x","startDate":"2026-10-30T20:00:00+09:00",'
            '"location":{"@type":"Place","name":"PISTA"},'
            '"description":"2026-10-30(금) · DJ Henry · 20:00~02:00 · PISTA"}'
            "</script>")
    record = tangonow_discovery.parse_share_page(html, SHARE_A)
    assert "DJ:" not in record["body"]


# --- T4: the whole crawl ----------------------------------------------------

def test_the_crawl_returns_every_event_the_sitemap_lists():
    slept: list[float] = []
    records = tangonow_share_discovery.discover(
        source_id="SRC-W-002", opener=_opener(), sleep=slept.append)
    assert [r["title"] for r in records] == [
        "ORANGE", "SOLO TANGO | Solo Tango 화요정모"]
    assert all(r["source_id"] == "SRC-W-002" for r in records)
    assert all(r["platform"] == "WEB" for r in records)


def test_the_crawl_honours_the_sites_own_crawl_delay():
    slept: list[float] = []
    tangonow_share_discovery.discover(
        source_id="SRC-W-002", opener=_opener(), sleep=slept.append)
    # One pause between the two pages, none before the first.
    assert slept == [tangonow_discovery.CRAWL_DELAY]


def test_one_unreadable_page_does_not_cost_the_others():
    problems: list[str] = []
    records = tangonow_share_discovery.discover(
        source_id="SRC-W-002", opener=_opener(fail={SHARE_A}),
        problems=problems, sleep=lambda _s: None)
    assert [r["title"] for r in records] == ["SOLO TANGO | Solo Tango 화요정모"]
    assert len(problems) == 1
    assert SHARE_A in problems[0] and "FETCH_FAILED" in problems[0]


def test_a_run_where_no_page_can_be_read_fails():
    with pytest.raises(tangonow_discovery.DiscoveryError):
        tangonow_share_discovery.discover(
            source_id="SRC-W-002", opener=_opener(fail={SHARE_A, SHARE_B}),
            problems=[], sleep=lambda _s: None)


def test_a_sitemap_that_cannot_be_fetched_fails_the_run():
    with pytest.raises(tangonow_discovery.DiscoveryError, match="404|HTTP"):
        tangonow_share_discovery.discover(
            source_id="SRC-W-002", opener=_opener(pages={}),
            sleep=lambda _s: None)


# --- T5: the collector wiring ------------------------------------------------

def test_the_parser_key_resolves_to_the_share_module():
    assert collectors._web_discovery_module(
        collectors.WEB_PARSER_TANGONOW_SHARE) is tangonow_share_discovery


def test_the_share_parser_settles_its_body_during_discovery():
    assert collectors.content_mode(
        {"platform": "WEB",
         "config": {"parser": collectors.WEB_PARSER_TANGONOW_SHARE}}
    ) == collectors.CONTENT_MODE_DISCOVERY_FULL


def test_the_share_parser_is_not_a_non_html_api():
    from runtime import acquisition

    assert (collectors.WEB_PARSER_TANGONOW_SHARE
            not in acquisition.NON_HTML_API_PARSERS)


def test_the_firestore_parser_is_left_exactly_as_it_was():
    """v0.96.31's classification of the 403 is not revisited here."""
    assert collectors.WEB_PARSER_TANGONOW == "tangonow_firestore"
    assert collectors.content_mode(
        {"platform": "WEB", "config": {"parser": collectors.WEB_PARSER_TANGONOW}}
    ) == collectors.CONTENT_MODE_NON_HTML_API


def test_the_bundle_path_is_still_not_wired_in():
    """robots.txt disallows it; `discover_bundle` must stay unreachable."""
    assert tangonow_discovery.BUNDLE_URL
    for parser in (collectors.WEB_PARSER_TANGONOW,
                   collectors.WEB_PARSER_TANGONOW_SHARE):
        module = collectors._web_discovery_module(parser)
        assert getattr(module, "discover", None) is not getattr(
            tangonow_discovery, "discover_bundle")


def test_the_migration_switches_only_the_firestore_registration(repo_root):
    sql = io.open(repo_root / "migrations" / "runtime"
                  / "044_tangonow_share_pages.sql", encoding="utf-8").read()
    assert "tangonow_share_pages" in sql
    assert "sitemap-events.xml" in sql
    assert "SRC-W-002" in sql
    # Guarded, so re-running it cannot move a source somebody has since
    # pointed somewhere else.
    assert "config->>'parser' = 'tangonow_firestore'" in sql
    statements = " ".join(line for line in sql.splitlines()
                          if not line.lstrip().startswith("--")).upper()
    assert statements.strip().startswith("UPDATE SOURCES")
    for forbidden in ("DELETE", "DROP", "INSERT", "TRUNCATE"):
        assert forbidden not in statements
