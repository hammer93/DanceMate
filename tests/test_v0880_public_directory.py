"""v0.88.0 Public Directory Tabs.

The first screen carries five tabs: 행사 (the events view, unchanged and still
the default) and the directory - 장소, 동호회, 정보원, 게시판. One genre
selection drives all of them through the v0.86.8 contract, and the tab and the
genres live in the URL (``?tab=venues&genres=TANGO``), so a reload or a shared
link lands on the same view.

Genre policy (runtime/directory.py): every genre ticked narrows nothing and
keeps rows with no genre; a narrowed selection keeps only rows with one of the
chosen genres, so a venue, community or source with no genre is left out; an
empty selection lists nothing - except a notice with no genre, which is a
global notice and is listed under every selection.

The page tests run against a stubbed data layer; the SQL tests use the
rolled-back PostgreSQL fixture.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import inspect
import json
import re

import pytest
from fastapi.testclient import TestClient

from runtime import boards, communities, directory, master_data, public

OPTIONS = [{"code": "TANGO", "label": "Tango"}, {"code": "SALSA", "label": "Salsa"},
           {"code": "SWING", "label": "Swing"}]
UTC_3AM = dt.datetime(2026, 9, 10, 3, 0, tzinfo=dt.timezone.utc)   # 12:00 in Seoul

VENUES = [
    {"venue_id": 1, "name": "라 벤따나 <b>", "address": "서울 마포구 독막로 1",
     "region_name": "서울", "genre_codes": ["TANGO"]},
    {"venue_id": 2, "name": "No Genre Hall", "address": None, "region_name": None,
     "genre_codes": []},
]
COMMUNITIES = [
    {"community_id": 1, "name": "<script>alert(1)</script>", "region_name": "서울",
     "description": "매주 금요일\n<i>초보 환영</i>", "homepage_url": "https://club.example/",
     "genre_codes": ["TANGO", "SALSA"], "venue_names": ["라 벤따나"]},
]
SOURCES = [
    {"name": "탱고 카페", "platform_label": "다음 카페", "tier": "PRIMARY", "tier_label": "공식",
     "genre_code": "TANGO", "region_name": "서울", "public_url": "https://cafe.daum.net/tango"},
    {"name": "전국 블로그", "platform_label": "네이버 블로그", "tier": "DIRECTORY",
     "tier_label": "일정모음", "genre_code": None, "region_name": None, "public_url": None},
]
NOTICES = [
    {"post_id": 7, "title": "전체 공지 <b>1</b>", "pinned": True, "published_at": UTC_3AM,
     "genre_codes": [], "excerpt": "첫 줄 <script>x()</script>\n둘째 줄 " + "가" * 120},
    {"post_id": 8, "title": "Tango only", "pinned": False, "published_at": UTC_3AM,
     "genre_codes": ["TANGO"]},
]
NOTICE_DETAIL = dict(
    NOTICES[0],
    body="첫 줄 <script>x()</script>\n둘째 줄\n\n링크 https://example.com/a?b=1&c=2). 끝",
)
TABS = ("venues", "communities", "sources", "notices")


@pytest.fixture
def client(env, monkeypatch):
    from runtime import app as app_module

    monkeypatch.setattr(app_module, "_settings", None)
    return TestClient(app_module.app, raise_server_exceptions=False)


@pytest.fixture
def stub(monkeypatch):
    """Every tab's loader replaced by one that records the genre constraint it
    was handed - the one thing the page decides - and returns fixed rows."""
    state = {"options": [dict(o) for o in OPTIONS], "calls": {},
             "rows": {"venues": VENUES, "communities": COMMUNITIES,
                      "sources": SOURCES, "notices": NOTICES},
             "detail": {7: NOTICE_DETAIL}}

    @contextlib.contextmanager
    def fake_connection():
        yield object()

    monkeypatch.setattr(public, "_connection", fake_connection)
    monkeypatch.setattr(public, "_genre_options",
                        lambda con: [dict(o) for o in state["options"]])

    def loader(tab):
        def load(con, genre_codes):
            state["calls"][tab] = None if genre_codes is None else list(genre_codes)
            return [dict(r) for r in state["rows"][tab]]
        return load

    for tab in TABS:
        monkeypatch.setattr(directory, f"public_{tab}", loader(tab))
    monkeypatch.setattr(directory, "public_notice",
                        lambda con, post_id: state["detail"].get(post_id))
    return state


def _tabs(page: str) -> list[tuple[str, str, bool]]:
    nav = re.search(r'<nav class="dirtabs"[^>]*>(.*?)</nav>', page, re.S).group(1)
    return [(label, href.replace("&amp;", "&"), bool(current)) for href, current, label in
            re.findall(r'<a href="([^"]*)"( aria-current="page")?>([^<]*)</a>', nav)]


# === 1. Tabs and URL state ====================================================

def test_four_directory_tabs_sit_beside_the_events():
    tabs = _tabs(public._directory_nav(public.EVENTS_TAB, {}))
    assert [t[0] for t in tabs] == ["행사", "장소", "동호회", "정보원", "게시판"]
    assert tabs[0] == ("행사", "/", True)                  # the plain first screen
    assert [t[1] for t in tabs[1:]] == [f"/?tab={t}" for t in TABS]


def test_every_tab_link_keeps_the_genre_choice_and_nothing_else():
    nav = public._directory_nav("venues", {"genres": "TANGO", "genres_set": "1"})
    tabs = {label: href for label, href, _ in _tabs(nav)}
    assert tabs["행사"] == "/?genres=TANGO&genres_set=1"
    assert tabs["장소"] == "/?tab=venues&genres=TANGO&genres_set=1"
    assert tabs["게시판"] == "/?tab=notices&genres=TANGO&genres_set=1"


@pytest.mark.parametrize("raw, expected", [
    (None, "events"), ("", "events"), ("events", "events"), ("VENUES", "venues"),
    (" notices ", "notices"), ("bogus", "events"), ("<script>", "events"),
])
def test_the_tab_parameter_is_normalised_never_trusted(raw, expected):
    assert public._directory_tab(raw) == expected


def test_a_shared_link_restores_the_tab_and_the_genres(stub, client):
    response = client.get("/?tab=venues&genres=TANGO")
    assert response.status_code == 200
    page = response.text
    assert stub["calls"]["venues"] == ["TANGO"]
    assert ("장소", "/?tab=venues&genres=TANGO&genres_set=1", True) in _tabs(page)
    assert 'value="TANGO" checked' in page and 'value="SALSA" checked' not in page
    # A genre change submitted from this tab stays on this tab.
    assert '<input type="hidden" name="tab" value="venues">' in page


@pytest.mark.parametrize("tab", TABS)
def test_every_tab_reads_the_same_genre_selection(stub, client, tab):
    assert client.get(f"/?tab={tab}&genres=SALSA,SWING&genres_set=1").status_code == 200
    assert stub["calls"][tab] == ["SALSA", "SWING"]


@pytest.mark.parametrize("query", ["", "&genres=TANGO,SALSA,SWING&genres_set=1"])
def test_every_genre_ticked_is_no_constraint(stub, client, query):
    client.get(f"/?tab=sources{query}")
    assert stub["calls"]["sources"] is None


def test_a_link_naming_a_disabled_or_unknown_genre_falls_back_to_all(stub, client):
    page = client.get("/?tab=communities&genres=BALLET").text
    assert stub["calls"]["communities"] is None
    assert page.count('" checked>') == 3


def test_one_enabled_genre_means_no_selector_and_no_constraint(stub, client):
    stub["options"] = [{"code": "TANGO", "label": "Tango"}]
    page = client.get("/?tab=venues&genres=SALSA&genres_set=1").text
    assert stub["calls"]["venues"] is None
    assert 'form class="row genres"' not in page


def test_unticking_everything_is_an_answer(stub, client):
    stub["rows"]["venues"] = []
    page = client.get("/?tab=venues&genres_set=1").text
    assert stub["calls"]["venues"] == []
    assert public.EMPTY_NOTHING_TICKED in page
    # The notices loader is still asked - with nothing ticked it returns the
    # global notices, which belong to every selection.
    client.get("/?tab=notices&genres_set=1")
    assert stub["calls"]["notices"] == []


@pytest.mark.parametrize("tab, empty", [
    ("venues", "등록된 장소가 없습니다."), ("communities", "등록된 동호회가 없습니다."),
    ("sources", "등록된 정보원이 없습니다."), ("notices", "등록된 공지가 없습니다."),
])
def test_every_tab_has_an_empty_state_and_never_an_empty_table(stub, client, tab, empty):
    stub["rows"][tab] = []
    response = client.get(f"/?tab={tab}")
    assert response.status_code == 200
    assert f'<p class="empty">{empty}</p>' in response.text
    assert '<ul class="dir">' not in response.text


def test_a_narrowed_empty_state_says_so(stub, client):
    stub["rows"]["communities"] = []
    narrowed = client.get("/?tab=communities&genres=SALSA").text
    assert "선택한 춤 종류에 해당하는 동호회가 없습니다." in narrowed
    assert "장르가 지정되지 않은 동호회는 춤 종류 전체를 볼 때만 표시됩니다." in narrowed


@pytest.mark.parametrize("tab", TABS)
def test_zero_enabled_genres_never_crash(stub, client, tab):
    stub["options"] = []
    response = client.get(f"/?tab={tab}&genres=TANGO&genres_set=1")
    assert response.status_code == 200
    assert stub["calls"][tab] is None                 # nothing to narrow by
    assert 'form class="row genres"' not in response.text


def test_the_events_view_is_still_the_default_and_carries_the_tabs():
    source = inspect.getsource(public.home)
    assert "_directory_nav(EVENTS_TAB, genre_query)" in source
    assert '_nav("today", genre_query=genre_query)' in source
    assert '_filter_bar("/", None, facets, options, selected, region)' in source
    assert "if current_tab != EVENTS_TAB" in source


def test_the_tab_row_scrolls_sideways_instead_of_wrapping():
    assert "nav.dirtabs { flex-wrap:nowrap; overflow-x:auto;" in public.STYLE


# === 2. Cards ===================================================================

def test_venue_cards(stub, client):
    page = client.get("/?tab=venues").text
    assert "라 벤따나 &lt;b&gt;" in page and "라 벤따나 <b>" not in page
    assert "서울 · 서울 마포구 독막로 1" in page
    assert 'href="https://map.naver.com/p/search/' in page
    assert '<li class="tag">Tango</li>' in page
    assert '<li class="tag">장르 미지정</li>' in page      # the venue with no genre


@pytest.mark.parametrize("tab, rows", [("venues", VENUES), ("sources", SOURCES)])
def test_venues_and_sources_are_one_entry_per_line(stub, client, tab, rows):
    """장소 and 정보원 read as a list: every entry is one <li> line - name,
    facts, genre tags, link - with no block element inside that could wrap it
    onto a second line."""
    page = client.get(f"/?tab={tab}").text
    assert '<ul class="dir rows">' in page
    listing = page.split('<ul class="dir rows">', 1)[1].split("<footer>", 1)[0]
    entries = listing.split('<li class="dir-row">')[1:]
    assert len(entries) == len(rows)
    for entry, row in zip(entries, rows):
        name = public.E(row["name"])
        assert entry.startswith(f'<span class="dir-name" title="{name}">{name}</span>')
        assert not re.search(r"<(p|div|br|h\d)\b", entry)
    assert "li.dir-row { display:flex;" in public.STYLE and "white-space:nowrap;" in public.STYLE


def test_the_full_values_stay_readable_when_the_line_is_cut(stub, client):
    page = client.get("/?tab=venues").text
    first = page.split('<li class="dir-row">')[1]
    assert '<span class="dir-name" title="라 벤따나 &lt;b&gt;">라 벤따나 &lt;b&gt;</span>' in first
    assert ('<span class="dir-meta" title="서울 · 서울 마포구 독막로 1">'
            "서울 · 서울 마포구 독막로 1</span>") in first
    assert '<ul class="tags" title="Tango"><li class="tag">Tango</li></ul>' in first
    assert '<ul class="tags" title="장르 미지정">' in page


def test_a_short_line_gives_way_in_order_and_never_overflows_the_page():
    """Facts first (they only get the space left over), then genres (capped,
    cut with an ellipsis); the name keeps a minimum and the link never shrinks;
    the list itself clips anything that still does not fit."""
    style = public.STYLE
    assert re.search(r"ul\.dir\.rows \{[^}]*overflow:hidden;", style)
    assert "li.dir-row { display:flex; align-items:center; gap:.6rem; min-width:0;" in style
    assert re.search(r"li\.dir-row \.dir-meta \{ flex:1 1 0%; min-width:0;[^}]*"
                     r"overflow:hidden;[^}]*text-overflow:ellipsis;", style)
    assert re.search(r"li\.dir-row \.dir-name \{ flex:0 1 auto; min-width:4\.5em; max-width:60%;"
                     r"[^}]*text-overflow:ellipsis;", style)
    # Genres give up room three times faster than the name.
    assert re.search(r"li\.dir-row \.tags \{ display:block; flex:0 3 auto; min-width:0; "
                     r"max-width:35%;[^}]*text-overflow:ellipsis;", style)
    assert "li.dir-row .dir-go { flex:0 0 auto;" in style


def test_venue_rows_carry_the_map_link_inside_the_line(stub, client):
    first = client.get("/?tab=venues").text.split('<li class="dir-row">')[1].split("</li><li", 1)[0]
    assert re.search(r'<span class="dir-go"><a href="https://map\.naver\.com/p/search/[^"]+" '
                     r'target="_blank" rel="noopener noreferrer">지도 &#8599;</a></span></li>$', first)


def test_source_rows_show_name_genre_and_only_public_fields(stub, client):
    """Even if a loader ever handed the page more than it should, a source row
    renders only its public fields - never keys, config, queries or notes."""
    stub["rows"]["sources"] = [dict(
        SOURCES[0], source_key="SRC-SECRET-1", config={"api_key": "SECRETCONF"},
        queries=["SECRETQUERY"], notes="SECRETNOTE", last_detail="SECRETDETAIL",
        url="https://collector.example/api?token=SECRETTOKEN")] + SOURCES[1:]
    page = client.get("/?tab=sources").text
    first = page.split('<li class="dir-row">')[1]
    assert first.startswith('<span class="dir-name" title="탱고 카페">탱고 카페</span>')
    assert '<ul class="tags" title="Tango"><li class="tag">Tango</li></ul>' in first
    assert 'href="https://cafe.daum.net/tango"' in first
    assert "SECRET" not in page and "collector.example" not in page


def test_communities_and_notices_keep_their_cards(stub, client):
    for tab in ("communities", "notices"):
        page = client.get(f"/?tab={tab}").text
        assert '<ul class="dir">' in page and 'class="dir-row"' not in page


def test_community_cards_escape_everything(stub, client):
    page = client.get("/?tab=communities").text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "&lt;i&gt;초보 환영&lt;/i&gt;" in page
    assert "장소: 라 벤따나" in page
    assert ('<a href="https://club.example/" target="_blank" rel="noopener noreferrer">'
            "홈페이지 &#8599;</a>") in page


def test_source_cards_show_only_public_facts(stub, client):
    page = client.get("/?tab=sources").text
    assert "다음 카페 · 공식 · 서울" in page
    assert '<li class="tag">장르 미확인</li>' in page
    assert page.count("바로가기") == 1                  # the source with no public URL has none


def test_notice_list(stub, client):
    page = client.get("/?tab=notices").text
    first = page.split('<li class="dir-item">')[1]
    assert first.startswith('<a class="dir-link" href="/notices/7">')
    assert "전체 공지 &lt;b&gt;1&lt;/b&gt;" in first
    assert '<li class="tag pin">고정</li><li class="tag">전체 공지</li>' in first
    assert "2026.09.10" in first                       # the date in Seoul
    summary = re.search(r'<p class="dir-desc">([^<]*)</p>', first).group(1)
    assert summary.startswith("첫 줄 &lt;script&gt;x()&lt;/script&gt; 둘째 줄 가")
    assert summary.endswith("…") and "\n" not in summary


# === 3. Notice detail ===========================================================

def test_notice_detail_renders_plain_text_safely(stub, client):
    response = client.get("/notices/7")
    assert response.status_code == 200
    page = response.text
    assert "<script>x()" not in page
    assert ("<p>첫 줄 &lt;script&gt;x()&lt;/script&gt;<br>둘째 줄</p><p>링크 "
            '<a href="https://example.com/a?b=1&amp;c=2" target="_blank" '
            'rel="nofollow noopener noreferrer">https://example.com/a?b=1&amp;c=2</a>). 끝</p>'
            ) in page
    assert '<a href="/?tab=notices">' in page


@pytest.mark.parametrize("path", ["/notices/99", "/notices/abc", "/notices/0",
                                  "/notices/-1", "/notices/%EF%BC%91", "/notices/1e3"])
def test_a_missing_draft_or_garbage_notice_is_a_404(stub, client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert "공지를 찾을 수 없습니다" in response.text


@pytest.mark.parametrize("body, expected", [
    ("", ""),
    ("   \n\n  ", ""),
    ("javascript:alert(1)", '<div class="notice-body"><p>javascript:alert(1)</p></div>'),
    ('<a href="https://evil.example">x</a>',
     '<div class="notice-body"><p>&lt;a href=&quot;<a href="https://evil.example" '
     'target="_blank" rel="nofollow noopener noreferrer">https://evil.example</a>'
     '&quot;&gt;x&lt;/a&gt;</p></div>'),
    ("a\r\nb", '<div class="notice-body"><p>a<br>b</p></div>'),
])
def test_notice_body_is_never_markup(body, expected):
    assert public._notice_body_html(body) == expected


# === 4. Links a reader may be sent to ===========================================

@pytest.mark.parametrize("url, expected", [
    ("https://cafe.daum.net/tango", "https://cafe.daum.net/tango"),
    ("http://club.example/board?page=2", "http://club.example/board?page=2"),
    ("https://example.com/list?api_key=SECRET", None),
    ("https://example.com/list?serviceKey=SECRET", None),
    ("https://example.com/list?access-token=SECRET", None),
    ("https://user:pw@example.com/", None),
    ("https://openapi.naver.com/v1/search/blog", None),
    ("https://example.com/feed.json", None),
    ("javascript:alert(1)", None),
    ("/relative/path", None),
    ("", None),
    (None, None),
])
def test_public_link_rules(url, expected):
    assert directory.public_link(url) == expected


def test_a_sources_collector_api_resolves_to_its_site_not_its_endpoint():
    assert directory.public_source_link("https://host.example/api/events") == "https://host.example/"


def test_the_source_query_never_reads_collector_settings():
    source = inspect.getsource(directory.public_sources)
    select = source.split("sql = (", 1)[1].split("WHERE", 1)[0]
    for column in ("config", "queries", "notes", "last_status", "last_detail",
                   "source_key", "authority_level", "access_state", "operational_decision"):
        assert column not in select


# === 5. SQL: the genre policy against real rows ===================================

def _mine(rows, unique, key="name"):
    return [r[key] for r in rows if unique in str(r[key])]


def _source(pg, unique, n, *, genre_id=None, enabled=True, url=None,
            role="COMMUNITY", platform="WEB"):
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO sources (source_key, name, platform, source_role, url, genre_id, "
            "  enabled, queries, config, notes, last_status, last_detail) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s) "
            "RETURNING source_id",
            (f"SRC-T88-{unique}-{n}", f"S088 {n} {unique}", platform, role, url, genre_id,
             enabled, json.dumps(["SECRETQUERY"]), json.dumps({"api_key": "SECRETCONFIG"}),
             "SECRETNOTE", "ERROR", "SECRETDETAIL"),
        )
        return cur.fetchone()[0]


@pytest.fixture
def world(pg, unique, seoul_id):
    code = f"T88{unique}"[:16].upper()
    other = f"U88{unique}"[:16].upper()
    genre = master_data.create_genre(pg, code=code, name=f"Tango88 {unique}")
    master_data.create_genre(pg, code=other, name=f"Other88 {unique}")
    gid = genre["genre_id"]
    tagged = master_data.create_venue(pg, name=f"V088 Tagged {unique}", region_id=seoul_id,
                                      address="서울 마포구 1")
    master_data.add_venue_genre(pg, tagged["venue_id"], gid)
    master_data.create_venue(pg, name=f"V088 Bare {unique}", region_id=seoul_id)
    off = master_data.create_venue(pg, name=f"V088 Off {unique}")
    master_data.add_venue_genre(pg, off["venue_id"], gid)
    master_data.update_venue(pg, off["venue_id"], enabled=False)
    return {"code": code, "other": other, "gid": gid, "tagged": tagged["venue_id"],
            "off": off["venue_id"], "seoul_id": seoul_id}


@pytest.mark.postgres
def test_venues_follow_the_policy(pg, unique, world):
    assert _mine(directory.public_venues(pg, [world["code"]]), unique) == [f"V088 Tagged {unique}"]
    assert _mine(directory.public_venues(pg, [world["other"]]), unique) == []
    assert sorted(_mine(directory.public_venues(pg, None), unique)) == \
        [f"V088 Bare {unique}", f"V088 Tagged {unique}"]      # no-genre kept, disabled never
    assert directory.public_venues(pg, []) == []


@pytest.mark.postgres
def test_venue_rows_carry_no_admin_only_fields(pg, unique, world):
    master_data.update_venue(pg, world["tagged"], notes="운영 메모 SECRETNOTE")
    row = next(r for r in directory.public_venues(pg, [world["code"]]) if unique in r["name"])
    assert set(row) == {"venue_id", "name", "address", "region_name", "genre_codes"}
    assert "SECRETNOTE" not in repr(row)


@pytest.mark.postgres
def test_a_venue_with_several_genres_shows_under_each(pg, unique, world):
    with pg.cursor() as cur:
        cur.execute("SELECT genre_id FROM genres WHERE code = %s", (world["other"],))
        other_id = cur.fetchone()[0]
    master_data.add_venue_genre(pg, world["tagged"], other_id)
    for codes in ([world["code"]], [world["other"]], [world["code"], world["other"]]):
        assert _mine(directory.public_venues(pg, codes), unique) == [f"V088 Tagged {unique}"]
    assert _mine(directory.public_venues(pg, ["NOSUCHGENRE"]), unique) == []


@pytest.mark.postgres
def test_communities_follow_the_policy_and_hide_notes(pg, unique, world):
    communities.create_community(pg, {
        "name": f"C088 Tagged {unique}", "genre_ids": [world["gid"]],
        "venue_ids": [world["tagged"], world["off"]], "notes": "운영자만 SECRETNOTE",
        "homepage_url": "https://club.example/?page=1", "region_id": world["seoul_id"]})
    communities.create_community(pg, {"name": f"C088 Bare {unique}"})
    communities.create_community(pg, {"name": f"C088 Off {unique}", "enabled": "0",
                                      "genre_ids": [world["gid"]]})
    narrowed = directory.public_communities(pg, [world["code"]])
    assert _mine(narrowed, unique) == [f"C088 Tagged {unique}"]
    row = next(r for r in narrowed if unique in r["name"])
    assert "notes" not in row and "SECRETNOTE" not in repr(row)
    assert row["venue_names"] == [f"V088 Tagged {unique}"]      # the disabled venue is left out
    assert row["genre_codes"] == [world["code"]]
    assert sorted(_mine(directory.public_communities(pg, None), unique)) == \
        [f"C088 Bare {unique}", f"C088 Tagged {unique}"]
    assert directory.public_communities(pg, []) == []


PUBLIC_SOURCE_KEYS = {"name", "platform_label", "tier", "tier_label", "genre_code",
                      "region_name", "public_url"}


@pytest.mark.postgres
def test_sources_follow_the_policy_and_expose_nothing_internal(pg, unique, world):
    _source(pg, unique, 1, genre_id=world["gid"], url=f"https://cafe.example/{unique}")
    _source(pg, unique, 2, url=f"https://blog.example/{unique}", role="AGGREGATOR")
    _source(pg, unique, 3, genre_id=world["gid"], enabled=False, url=f"https://off.example/{unique}")
    _source(pg, unique, 4, genre_id=world["gid"], url=f"https://k.example/{unique}?api_key=SECRETKEY")
    narrowed = directory.public_sources(pg, [world["code"]])
    assert _mine(narrowed, unique) == [f"S088 1 {unique}", f"S088 4 {unique}"]
    everything = directory.public_sources(pg, None)
    assert _mine(everything, unique) == [f"S088 1 {unique}", f"S088 4 {unique}",
                                         f"S088 2 {unique}"]      # tier first: AGGREGATOR last
    mine = [r for r in everything if unique in r["name"]]
    assert all(set(r) == PUBLIC_SOURCE_KEYS for r in mine)
    assert "SECRET" not in repr(mine)
    by_name = {r["name"]: r for r in mine}
    assert by_name[f"S088 1 {unique}"]["public_url"] == f"https://cafe.example/{unique}"
    assert by_name[f"S088 4 {unique}"]["public_url"] is None       # a key in the URL
    assert by_name[f"S088 2 {unique}"]["genre_code"] is None
    assert by_name[f"S088 1 {unique}"]["tier_label"] == "공식"
    assert directory.public_sources(pg, []) == []


@pytest.mark.postgres
def test_notices_global_ones_belong_to_every_selection(pg, unique, world):
    def post(title, **fields):
        return boards.create_post(pg, {"title": f"N088 {title} {unique}", "body": title,
                                       **fields})["post_id"]

    post("global")
    post("pinned-global", pinned="1")
    post("scoped", genre_ids=[world["gid"]])
    post("draft", status="DRAFT")
    post("hidden", status="HIDDEN", genre_ids=[world["gid"]])

    def titles(codes):
        return [t.split(" ")[1] for t in _mine(directory.public_notices(pg, codes), unique, "title")]

    assert titles(None) == ["pinned-global", "scoped", "global"]
    assert titles([world["code"]]) == ["pinned-global", "scoped", "global"]
    assert titles([world["other"]]) == ["pinned-global", "global"]
    assert titles([]) == ["pinned-global", "global"]


@pytest.mark.postgres
def test_a_notice_for_several_genres_shows_under_each_of_them(pg, unique, world):
    with pg.cursor() as cur:
        cur.execute("SELECT genre_id FROM genres WHERE code = %s", (world["other"],))
        other_id = cur.fetchone()[0]
    boards.create_post(pg, {"title": f"N088 multi {unique}", "body": "두 장르",
                            "genre_ids": [world["gid"], other_id]})
    for codes in ([world["code"]], [world["other"]], [world["code"], world["other"]], None):
        assert _mine(directory.public_notices(pg, codes), unique, "title") == \
            [f"N088 multi {unique}"]
    assert _mine(directory.public_notices(pg, ["NOSUCHGENRE"]), unique, "title") == []
    assert _mine(directory.public_notices(pg, []), unique, "title") == []


@pytest.mark.postgres
def test_a_notice_page_shows_only_what_is_published(pg, unique):
    published = boards.create_post(pg, {"title": f"N088 pub {unique}", "body": "본문"})
    draft = boards.create_post(pg, {"title": f"N088 draft {unique}", "status": "DRAFT"})
    shown = directory.public_notice(pg, published["post_id"])
    assert shown["body"] == "본문" and shown["genre_codes"] == []
    assert "author_name" not in shown
    assert directory.public_notice(pg, draft["post_id"]) is None
    assert directory.public_notice(pg, 10 ** 15) is None


# === 6. The real pages against the real schema ====================================

@pytest.mark.postgres
@pytest.mark.parametrize("path", ["/", "/?tab=venues", "/?tab=communities", "/?tab=sources",
                                  "/?tab=notices", "/?tab=venues&genres=TANGO",
                                  "/?tab=notices&genres_set=1"])
def test_every_tab_answers_against_the_migrated_database(pg, client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert '<nav class="dirtabs"' in response.text
    if path == "/":
        # The events view, as it was: its date tabs and filter bar are still there.
        assert '<nav><a href="/events?when=today"' in response.text
        assert 'aria-current="page">행사<' in response.text
