"""v0.96.50: a filter changed on one calendar day stays on that day.

Found by the release's mobile E2E (tests/e2e/test_v09650_corrected_data.py,
E2E-31): on /events?date=YYYY-MM-DD the style form carried only `when` and
`region`, and the region chips only `when`, so a reader who picked a day on
the week calendar and then tapped 스윙 or 서울 was sent to today's list with
the day forgotten. The page said one thing and listed another.
"""

from __future__ import annotations

import re

from runtime import public

OPTIONS = [
    {"code": "TANGO", "label": "Tango"},
    {"code": "SALSA", "label": "Salsa"},
    {"code": "SWING", "label": "Swing"},
]
ALL = ["TANGO", "SALSA", "SWING"]
FACETS = {"genres": [], "regions": [],
          "region_options": [{"value": "서울", "label": "서울", "events": 2}]}


def _region_hrefs(html: str) -> list[str]:
    row = html.split('<span class="key">지역</span>', 1)[1]
    return re.findall(r'href="([^"]+)"', row)


def test_the_style_form_on_a_day_keeps_the_day():
    html = public._filter_bar("/events", None, FACETS, OPTIONS, ALL, None, day="2026-10-25")
    form = html.split("</form>", 1)[0]
    assert '<input type="hidden" name="date" value="2026-10-25">' in form
    assert 'name="when"' not in form


def test_every_region_chip_on_a_day_keeps_the_day():
    html = public._filter_bar("/events", None, FACETS, OPTIONS, ["SWING"], None,
                              day="2026-10-25")
    hrefs = _region_hrefs(html)
    assert hrefs and all("date=2026-10-25" in h for h in hrefs)
    assert all("when=" not in h for h in hrefs)


def test_a_list_page_is_unchanged():
    """Nothing about the `when` lists moves: no date is added to them."""
    html = public._filter_bar("/events", "upcoming", FACETS, OPTIONS, ALL, None)
    assert 'name="date"' not in html
    assert all("date=" not in h for h in _region_hrefs(html))
    assert '<input type="hidden" name="when" value="upcoming">' in html


def test_a_day_value_is_escaped_not_trusted():
    html = public._filter_bar("/events", None, FACETS, OPTIONS, ALL, None,
                              day='2026-10-25"><script>')
    assert '"><script>' not in html  # the page's own auto-submit script is not this
    assert "&quot;&gt;&lt;script&gt;" in html
