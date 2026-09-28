"""v0.96.22 - what the corrected robots reading means for the real sources.

Every robots.txt here was fetched from the host DanceMate actually collects
from, with this project's own User-Agent, on 2026-09-28. The point of these
tests is not the parser (that is `test_v09622_robots_semantics.py`) but the
answer for the paths acquisition really requests:

* the Daum board route this project depends on stays open,
* Naver Cafe stays closed,
* SEOUL lindyfest, registered by v0.96.21, stays open,
* socialdancelive's filtered query page becomes correctly closed - the single
  decision this release changes, out of 1,148 URLs measured,
* latindancekorea's HTML stays open and its `/api/` becomes correctly closed.
"""

from __future__ import annotations

import urllib.robotparser

import pytest

from runtime import acquisition, robots

from tests.fixture_v09622_robots_corpus import (
    CAFE_DAUM,
    CAFE_NAVER,
    DANCEINFO,
    LATINDANCEKOREA,
    MILTANG,
    SEOUL_LINDYFEST,
    SOCIALDANCELIVE,
    TANGOCALENDAR,
)

UA = "DanceMate"


def _stdlib(text: str, url: str) -> bool:
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(text.splitlines())
    return bool(parser.can_fetch(UA, url))


# --- T13: the site this release was sent to investigate -------------------

def test_latindancekorea_html_stays_open_and_its_api_becomes_closed():
    """T13. The brief expected this source to be wrongly blocked and to open up.
    It is the other way round: nothing here was wrongly blocked, and the
    corrected reading makes it *more* restricted, not less.

    Its `Disallow:` lines sit after a `Sitemap:` line, which is what made the
    Sitemap hypothesis look plausible. They are hidden by the `Allow: /` above
    them instead - precedence, not Sitemap.
    """
    host = "https://latindancekorea.com"
    for path in ("/", "/events", "/events/LonBu9Fu7xaeJLHb2KOT", "/classes"):
        assert robots.allows(LATINDANCEKOREA, host + path, UA) is True, path
    for path in ("/api/events", "/admin/x", "/organizer/y"):
        assert robots.allows(LATINDANCEKOREA, host + path, UA) is False, path
        assert _stdlib(LATINDANCEKOREA, host + path) is True, (
            f"{path} was falsely allowed before this release")


# --- T14/T15: a fully open and a genuinely closed source -----------------

def test_an_open_source_stays_open():
    """T14."""
    for path in ("/", "/events", "/anything/at/all?week=1"):
        assert robots.allows(TANGOCALENDAR, "https://tangocalendar.kr" + path,
                             UA) is True, path


def test_a_genuinely_closed_source_stays_closed():
    """T15. 401 stored items sit behind this file. Nothing here may open."""
    for path in ("/", "/allaboutswing", "/lindyclub2/1234", "/anything"):
        url = "https://cafe.naver.com" + path
        assert robots.allows(CAFE_NAVER, url, UA) is False, path
        assert _stdlib(CAFE_NAVER, url) is False, "and it was closed before too"


# --- T16: sources whose file carries a Sitemap ---------------------------

def test_danceinfo_keeps_its_listing_open_and_its_api_closed():
    """T16. `Allow: /`, a Sitemap, then two Disallow rules."""
    host = "https://danceinfo.net"
    for path in ("/", "/lessons", "/lessons?genre=all&category=all&location=all",
                 "/lessons/1576"):
        assert robots.allows(DANCEINFO, host + path, UA) is True, path
    for path in ("/api/anything", "/admin_w/x"):
        assert robots.allows(DANCEINFO, host + path, UA) is False, path


def test_seoul_lindyfest_stays_open():
    """T16/§47. v0.96.21 registered this source and its upcoming event must
    survive a robots change. Its file puts two Sitemap lines before the group."""
    host = "https://seoullindyfest.com"
    for path in ("/", "/schedule/", "/venues/"):
        assert robots.allows(SEOUL_LINDYFEST, host + path, UA) is True, path
    for path in ("/wp-login.php", "/cgi-bin/x", "/next/y", "/public.api/z"):
        assert robots.allows(SEOUL_LINDYFEST, host + path, UA) is False, path


def test_a_specific_allow_inside_a_disallowed_directory_is_honoured():
    """WordPress's own `Allow: /wp-admin/admin-ajax.php` under
    `Disallow: /wp-admin/` - the precedence rule, in a file we really fetch."""
    host = "https://seoullindyfest.com"
    assert robots.allows(SEOUL_LINDYFEST, host + "/wp-admin/", UA) is False
    assert robots.allows(SEOUL_LINDYFEST, host + "/wp-admin/admin-ajax.php",
                         UA) is True


# --- T17: several groups, and the board route this project depends on ----

def test_the_daum_board_route_stays_open_and_the_rest_of_c21_stays_closed():
    """T17. Four specific Allow rules above one broad Disallow - the exact
    shape RFC 9309's specificity rule exists for, met in production. This is
    how every Daum Cafe board in the registry is read."""
    host = "https://cafe.daum.net"
    allowed = ("/_c21_/bbs_list?grpid=WCz&fldid=1nCx",
               "/_c21_/bbs_read?grpid=WCz&fldid=1nCx&datanum=1",
               "/_c21_/home", "/_c21_/bbs_search_read",
               "/neoswing/EBv/1731", "/sdamu/1nCx/1170")
    for path in allowed:
        assert robots.allows(CAFE_DAUM, host + path, UA) is True, path
    for path in ("/_c21_/bbs_write", "/_c21_/member_join", "/_c21_/"):
        assert robots.allows(CAFE_DAUM, host + path, UA) is False, path


def test_a_group_naming_other_bots_does_not_apply_to_us():
    """T17. socialdancelive closes the door on GPTBot and Amazonbot in one
    shared group; DanceMate is governed by the `*` group instead."""
    host = "https://www.socialdancelive.com"
    assert robots.allows(SOCIALDANCELIVE, host + "/posters/x", UA) is True
    assert robots.allows(SOCIALDANCELIVE, host + "/posters/x", "GPTBot") is False
    assert robots.allows(SOCIALDANCELIVE, host + "/posters/x", "Amazonbot") is False


def test_miltang_rules_survive_the_comment_block_after_them():
    host = "https://miltang.com"
    for path in ("/milongas", "/milongas?week=1", "/notices"):
        assert robots.allows(MILTANG, host + path, UA) is True, path
    for path in ("/admin", "/admin/x", "/more", "/auth/login"):
        assert robots.allows(MILTANG, host + path, UA) is False, path


# --- the one decision this release changes -------------------------------

def test_socialdancelive_filtered_query_page_becomes_correctly_blocked():
    """The whole user-visible effect of this release, on its own.

    DanceMate has been fetching
    `https://www.socialdancelive.com/?genre=salsa&type=posters`. That site's
    robots.txt disallows it twice - `Disallow: /?genre=` hidden behind the
    `Allow: /` above it, and `Disallow: /?*&type=` which the stdlib cannot
    express at all.
    """
    url = "https://www.socialdancelive.com/?genre=salsa&type=posters"
    assert _stdlib(SOCIALDANCELIVE, url) is True, "what v0.96.21 decided"
    decision = robots.evaluate(SOCIALDANCELIVE, url, UA)
    assert decision.allowed is False
    assert decision.agent == "*"
    assert decision.rule.startswith("Disallow: /?")


def test_every_path_socialdancelive_disallows_is_refused():
    """Thirteen paths were falsely allowed, not one. The fix is generic."""
    host = "https://www.socialdancelive.com"
    for path in ("/admin", "/auth", "/create", "/my", "/home-public-cache",
                 "/?location=x", "/?genre=x", "/?category=x", "/?date=x",
                 "/?sort=x", "/?type=x", "/?a=1&type=x", "/?a=1&genre=x"):
        assert robots.allows(SOCIALDANCELIVE, host + path, UA) is False, path
        assert _stdlib(SOCIALDANCELIVE, host + path) is True, (
            f"{path} was falsely allowed before")


def test_the_poster_pages_that_carry_the_events_stay_allowed():
    """§21/§48: the five stored items and the three events they produced are all
    under `/posters/`, which robots permits. Nothing is lost."""
    host = "https://www.socialdancelive.com"
    for path in ("/posters/busan-26-09-19-seoul-salsa-and-bachata-party-x?lang=ko",
                 "/posters/daejeon-sns-sunday-night-social-26-09-20-y?lang=ko",
                 "/posters", "/"):
        assert robots.allows(SOCIALDANCELIVE, host + path, UA) is True, path


# --- T18/T19: the acquisition path around the decision -------------------

def test_a_disallowed_url_is_refused_by_fetch_without_a_request(monkeypatch):
    """T18. `fetch()` turns a robots refusal into FETCH_BLOCKED /
    ROBOTS_DISALLOWED and makes no HTTP request at all - the state v0.96.9's
    reconciliation already knows how to carry, and this release adds no new
    path of its own."""
    monkeypatch.setattr(acquisition, "_ROBOTS_CACHE", {
        "https://www.socialdancelive.com": SOCIALDANCELIVE})

    def _explode(*args, **kwargs):                       # pragma: no cover
        raise AssertionError("a disallowed URL must not be requested")

    monkeypatch.setattr(acquisition.urllib.request, "urlopen", _explode)
    out = acquisition.fetch(
        "https://www.socialdancelive.com/?genre=salsa&type=posters")
    assert out.status == acquisition.FETCH_BLOCKED
    assert out.error_code == "ROBOTS_DISALLOWED"
    assert out.text == ""


def test_an_allowed_url_is_not_refused_by_the_robots_step(monkeypatch):
    """T19. The mirror of the above: a permitted URL reaches the request stage.
    Proven by the request being attempted, not by its outcome."""
    monkeypatch.setattr(acquisition, "_ROBOTS_CACHE", {
        "https://www.socialdancelive.com": SOCIALDANCELIVE})
    attempted = []

    def _record(request, *args, **kwargs):
        attempted.append(request.full_url)
        raise acquisition.urllib.error.URLError("stop here")

    monkeypatch.setattr(acquisition.urllib.request, "urlopen", _record)
    acquisition.fetch("https://www.socialdancelive.com/posters/abc")
    assert attempted, "a permitted URL must be requested"


@pytest.mark.parametrize("code,expected_allowed", [
    (401, False), (403, False), (404, True), (410, True), (500, True),
])
def test_the_http_status_policy_for_robots_txt_is_unchanged(
        monkeypatch, code, expected_allowed):
    """§13. Parsing correctness is not crawling policy: 401/403 still deny,
    every other failure still allows, exactly as `urllib.robotparser.read()`
    behaved before this release."""
    monkeypatch.setattr(acquisition, "_ROBOTS_CACHE", {})

    def _fail(request, *args, **kwargs):
        raise acquisition.urllib.error.HTTPError(
            request.full_url, code, "nope", {}, None)

    monkeypatch.setattr(acquisition.urllib.request, "urlopen", _fail)
    assert acquisition.robots_allows("https://example.com/x") is expected_allowed


def test_a_network_failure_reading_robots_txt_still_allows(monkeypatch):
    monkeypatch.setattr(acquisition, "_ROBOTS_CACHE", {})

    def _fail(*args, **kwargs):
        raise acquisition.urllib.error.URLError("no route to host")

    monkeypatch.setattr(acquisition.urllib.request, "urlopen", _fail)
    assert acquisition.robots_allows("https://example.com/x") is True


def test_robots_txt_is_read_once_per_origin(monkeypatch):
    """§19. The cache is per origin and survives within the process, as before;
    a second question about the same host makes no second request."""
    monkeypatch.setattr(acquisition, "_ROBOTS_CACHE", {})
    calls = []

    class _Resp:
        status = 200

        def read(self, *a):
            return SOCIALDANCELIVE.encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _once(request, *args, **kwargs):
        calls.append(request.full_url)
        return _Resp()

    monkeypatch.setattr(acquisition.urllib.request, "urlopen", _once)
    host = "https://www.socialdancelive.com"
    assert acquisition.robots_allows(host + "/posters/a") is True
    assert acquisition.robots_allows(host + "/?genre=x") is False
    assert calls == [host + "/robots.txt"], calls


def test_robots_txt_is_requested_under_this_projects_own_name(monkeypatch):
    """The one behaviour change beyond parsing: robots.txt used to be fetched as
    `Python-urllib`, because `RobotFileParser.read()` calls urlopen bare. Asking
    under the same name every page is fetched with is what makes a per-agent
    group mean anything. Verified against all eighteen origins: same status."""
    monkeypatch.setattr(acquisition, "_ROBOTS_CACHE", {})
    seen = {}

    class _Resp:
        status = 200

        def read(self, *a):
            return b"User-agent: *\nDisallow: /\n"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _capture(request, *args, **kwargs):
        seen["ua"] = request.get_header("User-agent")
        return _Resp()

    monkeypatch.setattr(acquisition.urllib.request, "urlopen", _capture)
    acquisition.robots_allows("https://example.com/x")
    assert seen["ua"] == acquisition.USER_AGENT
    assert "DanceMate" in seen["ua"]
