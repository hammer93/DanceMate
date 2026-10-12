"""v0.96.31: the Miltang list page stopped stating its day in Korean.

Until 2026-09-21 a `/milongas` list page carried a visible
`2026년 9월 5일` header, and `_extract_page_date()` read it as the ground
truth for "which day did this page actually render" - the check that stops a
`date=` the controller silently ignored from being believed. On 2026-09-21
that header disappeared. The page now server-renders the selected day as an
ISO date into its own calendar component's arguments:

    x-data="milongaCalendar(JSON.parse('{"year":2026,"month":10,...}'),
             { selected: '2026-10-14', query: '', ... })"

Read live on 2026-10-12 for 2026-10-12, -10-14, -10-19, -11-03, -12-25 and
2027-01-02: `selected` equalled the requested `date=` every time, including
the two days that list nothing at all. The detail pages did not change - the
same JSON-LD `Event` block and the same DATE/TIME/PLACE `<dl>` rows - so
every event's date still comes from its own detail page and never from the
list URL.

So the collector failed on **one line** of **one page**, and because a single
unreadable day raised, the other thirteen were never requested: 82
consecutive failed runs, and with them Busan's 33, Daegu's 10 and Daejeon's
22 Tango events. This file holds both page shapes, the empty day, and the
partial-window behaviour that keeps one bad day from costing the rest.
"""

from __future__ import annotations

import io
from datetime import date

import pytest

from runtime import miltang_discovery as md

LIST_URL = "https://miltang.com/milongas"


def _new_shape(selected: str, *ids: str, year: int = 2026, month: int = 10) -> str:
    """The page as the site renders it today: no Korean header, the day in
    the calendar component's own arguments."""
    cards = "".join(
        f'<a href="/milongas/{i}" class="block"><h3>card {i}</h3></a>' for i in ids
    )
    calendar = (
        "{\\u0022year\\u0022:%d,\\u0022month\\u0022:%d,\\u0022weeks\\u0022:[[]]}"
        % (year, month)
    )
    return (
        "<html><body>"
        '<div class="flex gap-1">'
        f'<a href="/milongas?week=2026-10-12&amp;date={selected}" '
        'class="chip chip--region-active">전체</a></div>'
        f"{cards}"
        f"<div x-data=\"milongaCalendar(JSON.parse('{calendar}'), "
        f"{{ selected: '{selected}', query: '', endpoint: '/milongas/calendar', "
        "listUrl: '/milongas', dayParam: 'date' })\"></div>"
        "</body></html>"
    )


def _old_shape(date_text: str, *ids: str) -> str:
    """The page as it rendered until 2026-09-21."""
    cards = "".join(f'<a href="/milongas/{i}">card {i}</a>' for i in ids)
    return f"<html><body><span>{date_text}</span>{cards}</body></html>"


def _detail(ident: str, iso: str, title: str, venue: str) -> str:
    return (
        '<html><head><script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"Event",'
        f'"name":"{title}","startDate":"{iso}",'
        f'"location":{{"@type":"Place","name":"{venue}",'
        '"address":{"@type":"PostalAddress","streetAddress":"주소","addressCountry":"KR"}}}'
        "</script></head><body>"
        f'<h2 class="text-2xl font-bold text-fg1">{title}</h2>'
        f"<div><dt>DATE</dt><dd>{iso.replace('-', '. ')}(수)</dd></div>"
        "<div><dt>TIME</dt><dd>21:15~23:15</dd></div>"
        f'<div><dt>PLACE</dt><dd><p class="font-bold">{venue}</p></dd></div>'
        f"<!-- {ident} --></body></html>"
    )


# --- the day the page states -----------------------------------------------

def test_the_new_server_rendered_selected_date_is_read():
    """The replacement ground truth, and it carries the year."""
    page = _new_shape("2026-10-14", "199")
    assert md._extract_page_date(page) == date(2026, 10, 14)


def test_the_old_korean_header_is_still_read():
    """A cached or archived page is still readable; nothing is gained by
    refusing a date the page does state."""
    assert md._extract_page_date(_old_shape("2026년 9월 5일", "731")) == date(2026, 9, 5)


def test_a_page_that_states_no_day_at_all_is_unreadable():
    page = "<html><body><a href='/milongas/1'>card</a></body></html>"
    assert md._extract_page_date(page) is None


def test_an_impossible_date_is_not_a_date():
    assert md._extract_page_date(_new_shape("2026-02-30")) is None


def test_the_url_is_never_the_answer():
    """A page whose controller ignored `date=` must not be believed: the
    whole reason this check exists."""
    page = _new_shape("2026-10-12", "199")          # page says the 12th
    assert md._extract_page_date(page) == date(2026, 10, 12)
    assert md._extract_page_date(page) != date(2026, 10, 14)


# --- a run over several days ------------------------------------------------

class _Resp:
    def __init__(self, text: str, charset: str = "utf-8"):
        self._body = text.encode(charset)
        self.headers = type("H", (), {"get_content_charset": lambda self: charset})()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener(pages: dict[str, str]):
    """An opener that answers from `pages`, keyed by the `date=` value for a
    list request and by the id for a detail request."""
    seen: list[str] = []

    def open_url(request, timeout=None):            # noqa: ARG001
        url = request.full_url if hasattr(request, "full_url") else str(request)
        seen.append(url)
        # Longest key first, so "/notices/5" is not answered by "/notices".
        for key in sorted(pages, key=len, reverse=True):
            if key in url:
                return _Resp(pages[key])
        raise AssertionError(f"unexpected fetch: {url}")

    open_url.seen = seen                            # type: ignore[attr-defined]
    return open_url


def test_a_day_with_no_milonga_is_an_empty_day_not_a_failure(monkeypatch):
    """VALID_EMPTY_DAY. The live site answers 200 with no cards for a day
    nobody has booked - read live for 2026-12-25 and 2027-01-02."""
    monkeypatch.setattr(md, "_seoul_today", lambda: date(2026, 12, 25))
    pages = {"date=2026-12-25": _new_shape("2026-12-25", year=2026, month=12)}
    problems: list[str] = []
    posts = md.discover(LIST_URL, source_id="SRC-W-005",
                        opener=_opener(pages), days_ahead=0, problems=problems)
    assert posts == []
    assert problems == [], "an empty day is not a problem to report"


def test_one_unreadable_day_does_not_cost_the_others(monkeypatch):
    """The defect that made this release: the first day failed, so the other
    thirteen were never asked for."""
    monkeypatch.setattr(md, "_seoul_today", lambda: date(2026, 10, 12))
    pages = {
        # day 0 renders nothing we can date
        "date=2026-10-12": "<html><body>no day stated</body></html>",
        "date=2026-10-13": _new_shape("2026-10-13", "199"),
        "date=2026-10-14": _new_shape("2026-10-14", "261"),
        "/milongas/199": _detail("199", "2026-10-13", "Abrazo 밀롱가", "PISTA"),
        "/milongas/261": _detail("261", "2026-10-14", "쁘롱가", "Amigo (아미고)"),
    }
    problems: list[str] = []
    posts = md.discover(LIST_URL, source_id="SRC-W-005",
                        opener=_opener(pages), days_ahead=2, problems=problems)
    titles = sorted(p["title"] for p in posts)
    assert titles == ["Abrazo 밀롱가", "쁘롱가"], "the readable days must survive"
    assert len(problems) == 1
    assert "2026-10-12" in problems[0] and "PARSING_FAILED" in problems[0]


def test_a_window_in_which_no_day_is_readable_still_raises(monkeypatch):
    """That is the shape genuinely having changed, not one bad day."""
    monkeypatch.setattr(md, "_seoul_today", lambda: date(2026, 10, 12))
    pages = {"/milongas": "<html><body>shape changed entirely</body></html>"}
    with pytest.raises(md.DiscoveryError, match="no readable day header"):
        md.discover(LIST_URL, source_id="SRC-W-005",
                    opener=_opener(pages), days_ahead=2, problems=[])


def test_a_partial_window_with_nowhere_to_report_it_raises(monkeypatch):
    """A caller that passes no sink must not be handed a partial window as
    if it were a whole one."""
    monkeypatch.setattr(md, "_seoul_today", lambda: date(2026, 10, 12))
    pages = {
        "date=2026-10-12": _new_shape("2026-10-12", "199"),
        "date=2026-10-13": "<html><body>no day stated</body></html>",
        "/milongas/199": _detail("199", "2026-10-12", "무초밀롱가", "Ocho"),
    }
    with pytest.raises(md.DiscoveryError, match="unreadable"):
        md.discover(LIST_URL, source_id="SRC-W-005",
                    opener=_opener(pages), days_ahead=1)


def test_a_page_rendering_the_wrong_day_is_a_failure_not_a_silent_wrong_date(
        monkeypatch):
    monkeypatch.setattr(md, "_seoul_today", lambda: date(2026, 10, 12))
    pages = {"/milongas": _new_shape("2026-08-31", "199")}
    problems: list[str] = []
    with pytest.raises(md.DiscoveryError):
        md.discover(LIST_URL, source_id="SRC-W-005",
                    opener=_opener(pages), days_ahead=0, problems=problems)


def test_the_same_card_on_several_days_is_fetched_once(monkeypatch):
    """A weekly series reappears on every day its run covers. One id is one
    event with one date of its own - never one per day it was listed on."""
    monkeypatch.setattr(md, "_seoul_today", lambda: date(2026, 10, 12))
    pages = {
        "date=2026-10-12": _new_shape("2026-10-12", "199"),
        "date=2026-10-13": _new_shape("2026-10-13", "199"),
        "date=2026-10-14": _new_shape("2026-10-14", "199"),
        "/milongas/199": _detail("199", "2026-10-14", "쁘롱가", "Amigo (아미고)"),
    }
    opener = _opener(pages)
    posts = md.discover(LIST_URL, source_id="SRC-W-005", opener=opener,
                        days_ahead=2, problems=[])
    assert len(posts) == 1
    assert sum(1 for u in opener.seen if "/milongas/199" in u) == 1
    assert "2026년 10월 14일" in posts[0]["body"], \
        "the date comes from the detail page, not from a list day"


def test_each_requested_day_carries_its_own_matching_week(monkeypatch):
    """Both params together, or the controller falls back to this week."""
    monkeypatch.setattr(md, "_seoul_today", lambda: date(2026, 10, 31))
    pages = {
        "date=2026-10-31": _new_shape("2026-10-31", year=2026, month=10),
        "date=2026-11-01": _new_shape("2026-11-01", year=2026, month=11),
        "date=2026-11-02": _new_shape("2026-11-02", year=2026, month=11),
    }
    opener = _opener(pages)
    md.discover(LIST_URL, source_id="SRC-W-005", opener=opener,
                days_ahead=2, problems=[])
    assert "week=2026-10-26&date=2026-10-31" in "".join(opener.seen)
    assert "week=2026-10-26&date=2026-11-01" in "".join(opener.seen), \
        "a Sunday belongs to the week that started the Monday before it"
    assert "week=2026-11-02&date=2026-11-02" in "".join(opener.seen)


def test_the_year_rolls_over_with_the_requested_day(monkeypatch):
    monkeypatch.setattr(md, "_seoul_today", lambda: date(2026, 12, 31))
    pages = {
        "date=2026-12-31": _new_shape("2026-12-31", year=2026, month=12),
        "date=2027-01-01": _new_shape("2027-01-01", year=2027, month=1),
    }
    problems: list[str] = []
    assert md.discover(LIST_URL, source_id="SRC-W-005", opener=_opener(pages),
                       days_ahead=1, problems=problems) == []
    assert problems == []


def test_a_notices_url_is_unaffected(monkeypatch):
    """Notices are not date-scoped and never were."""
    monkeypatch.setattr(md, "_seoul_today", lambda: date(2026, 10, 12))
    pages = {"/notices": '<html><body><a href="/notices/5">n</a></body></html>',
             "/notices/5": _detail("5", "2026-10-20", "축제 공지", "PISTA")}
    posts = md.discover("https://miltang.com/notices", source_id="SRC-W-005",
                        opener=_opener(pages), days_ahead=13, problems=[])
    assert [p["title"] for p in posts] == ["축제 공지"]
    assert posts[0].get("known_event_type") is None, \
        "only /milongas guarantees what its rows are"
