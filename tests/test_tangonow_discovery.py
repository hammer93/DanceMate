"""Discovery for TangoNOW (v0.82): a public Firestore REST registry whose
documents carry typed values (`stringValue`, `integerValue`, ...) rather than
plain JSON - fixtures here are shaped like real Firestore `documents.list`
responses, trimmed to just the fields this module reads.
"""

from __future__ import annotations

import io
import json

import pytest

from runtime import tangonow_discovery as tn

LIST_URL = (
    "https://firestore.googleapis.com/v1/projects/ktangoguide/databases/"
    "(default)/documents/events?pageSize=300"
)


def _doc(doc_id: str, fields: dict) -> dict:
    def wrap(value):
        if isinstance(value, bool):
            return {"booleanValue": value}
        if isinstance(value, int):
            return {"integerValue": str(value)}
        if isinstance(value, list):
            return {"arrayValue": {"values": [wrap(v) for v in value]}}
        return {"stringValue": str(value)}

    return {
        "name": f"projects/ktangoguide/databases/(default)/documents/events/{doc_id}",
        "fields": {k: wrap(v) for k, v in fields.items()},
    }


# --- Firestore typed-value conversion ----------------------------------------

def test_typed_values_convert_to_plain_python():
    document = {
        "fields": {
            "title": {"stringValue": "밀빠쏘"},
            "price": {"integerValue": "13000"},
            "archived": {"booleanValue": False},
            "createdAt": {"timestampValue": "2026-08-26T23:51:03Z"},
            "imageUrls": {"arrayValue": {"values": [{"stringValue": "https://x/1.jpg"}]}},
            "meta": {"mapValue": {"fields": {"venueId": {"stringValue": "v1"}}}},
            "note": {"nullValue": None},
        }
    }
    fields = tn.document_fields(document)
    assert fields["title"] == "밀빠쏘"
    assert fields["price"] == 13000
    assert fields["archived"] is False
    assert fields["createdAt"] == "2026-08-26T23:51:03Z"
    assert fields["imageUrls"] == ["https://x/1.jpg"]
    assert fields["meta"] == {"venueId": "v1"}
    assert fields["note"] is None


# --- record filtering ---------------------------------------------------------

def test_archived_records_are_excluded():
    docs = [
        _doc("a1", {"title": "정상", "date": "2026-09-06", "status": "active"}),
        _doc("a2", {"title": "보관됨", "date": "2026-09-06", "status": "archived"}),
        _doc("a3", {"title": "취소됨", "date": "2026-09-06", "status": "cancelled"}),
    ]
    posts = tn.parse_documents(docs, LIST_URL)
    titles = [p["title"] for p in posts]
    assert titles == ["정상"]


def test_a_boolean_archived_flag_also_excludes():
    """`archived` (not `isArchived`) - confirmed against a live response;
    v0.82.1 fixed this exact field-name mismatch after finding it live."""
    docs = [_doc("a4", {"title": "숨김", "date": "2026-09-06", "archived": True})]
    assert tn.parse_documents(docs, LIST_URL) == []


def test_status_archived_and_boolean_archived_are_independent_signals():
    """Both were observed live to agree in every sampled case, but each is
    checked on its own - a record could in principle have one without the
    other, and either alone must still exclude it."""
    docs = [_doc("a4b", {"title": "숨김2", "date": "2026-09-06",
                          "status": "active", "archived": True})]
    assert tn.parse_documents(docs, LIST_URL) == []


def test_a_record_with_no_explicit_date_is_never_made_a_candidate():
    docs = [_doc("a5", {"title": "날짜없음"})]
    assert tn.parse_documents(docs, LIST_URL) == []


def test_a_blank_title_is_skipped():
    docs = [_doc("a6", {"title": "", "date": "2026-09-06"})]
    assert tn.parse_documents(docs, LIST_URL) == []


def test_missing_price_does_not_crash_or_fabricate_a_fee():
    docs = [_doc("a7", {"title": "요금없음", "date": "2026-09-06"})]
    posts = tn.parse_documents(docs, LIST_URL)
    assert "입장료" not in posts[0]["body"]


def test_image_heavy_record_with_thin_text_still_produces_a_candidate():
    """A record whose only real content is its poster is left for the
    existing OCR fallback, not dropped - this module must not require a
    poster-independent text body to exist."""
    docs = [_doc("a8", {
        "title": "포스터만", "date": "2026-09-06",
        "imageUrls": ["https://x/poster.jpg"],
    })]
    posts = tn.parse_documents(docs, LIST_URL)
    assert len(posts) == 1
    assert posts[0]["title"] == "포스터만"


@pytest.mark.parametrize("region", ["부산", "서울"])
def test_region_parsing_for_busan_and_seoul(region):
    docs = [_doc("a9", {"title": "지역행사", "date": "2026-09-06", "region": region})]
    posts = tn.parse_documents(docs, LIST_URL)
    assert f"지역: {region}" in posts[0]["body"]


def test_the_detail_url_is_built_from_the_document_name():
    docs = [_doc("l4HSkRtgLLJv2ndOa3Wq", {"title": "밀빠쏘", "date": "2026-09-06"})]
    posts = tn.parse_documents(docs, LIST_URL)
    assert posts[0]["source_url"] == (
        "https://firestore.googleapis.com/v1/projects/ktangoguide/databases/"
        "(default)/documents/events/l4HSkRtgLLJv2ndOa3Wq"
    )


# --- overnight time handling --------------------------------------------------

@pytest.mark.parametrize("raw_time,expected", [
    ("14:00-18:00", "2:00 pm to 6:00 pm"),
    ("21:00-03:00", "9:00 pm to 3:00 am"),
    ("20:30-28:30", "8:30 pm to 4:30 am"),  # 28:30 is next-day 04:30
    ("09:00~12:00", "9:00 am to 12:00 pm"),
])
def test_overnight_and_ordinary_times_render_as_explicit_am_pm(raw_time, expected):
    assert tn.format_time_range(raw_time) == expected


def test_an_unparsable_time_string_is_left_out_rather_than_guessed():
    assert tn.format_time_range("all night") is None
    assert tn.format_time_range(None) is None


# --- body synthesis feeds the engine's own extraction rules ------------------

def test_synthesized_time_is_read_as_explicit_by_the_engine():
    from engine.src import extraction_rules

    docs = [_doc("b1", {
        "title": "밀빠쏘", "date": "2026-09-06", "time": "14:00-18:00", "venue": "PISTA",
    })]
    body = tn.parse_documents(docs, LIST_URL)[0]["body"]
    reading = extraction_rules.parse_time_range(body)
    assert (reading.start, reading.end) == ("14:00", "18:00")
    assert reading.meridiem_evidence == extraction_rules.EVIDENCE_EXPLICIT


def test_synthesized_venue_is_read_by_the_engine():
    from engine.src import extraction_rules

    docs = [_doc("b2", {"title": "누베르", "date": "2026-09-06", "venue": "탱고 엔빠스 스튜디오"})]
    body = tn.parse_documents(docs, LIST_URL)[0]["body"]
    reading = extraction_rules.extract_venue(body)
    assert reading.name == "탱고 엔빠스 스튜디오"


def test_synthesized_fee_is_read_by_the_engine():
    from engine.src import extraction_rules

    docs = [_doc("b3", {"title": "Alonga", "date": "2026-09-06", "price": 13000})]
    body = tn.parse_documents(docs, LIST_URL)[0]["body"]
    reading = extraction_rules.extract_fee(body, "MILONGA")
    assert reading.amount == 13000


# --- pagination ---------------------------------------------------------------

class _Resp(io.BytesIO):
    def __init__(self, payload: dict):
        super().__init__(json.dumps(payload).encode("utf-8"))
        self.headers = _Headers()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


class _Headers:
    def get_content_charset(self):
        return "utf-8"


def test_discover_walks_multiple_pages_until_no_next_page_token(monkeypatch):
    monkeypatch.setattr(tn.acquisition, "robots_allows", lambda url, **kw: True)
    pages = [
        {"documents": [_doc("p1", {"title": "One", "date": "2026-09-06"})],
         "nextPageToken": "tok-2"},
        {"documents": [_doc("p2", {"title": "Two", "date": "2026-09-07"})]},
    ]
    calls = []

    def opener(request, timeout=None):
        calls.append(request.full_url)
        return _Resp(pages[len(calls) - 1])

    posts = tn.discover(LIST_URL, source_id="SRC-W-002", opener=opener)
    assert [p["title"] for p in posts] == ["One", "Two"]
    assert len(calls) == 2
    assert "pageToken=tok-2" in calls[1]


def test_variable_page_sizes_are_not_assumed_equal(monkeypatch):
    monkeypatch.setattr(tn.acquisition, "robots_allows", lambda url, **kw: True)
    pages = [
        {"documents": [_doc(f"x{i}", {"title": f"E{i}", "date": "2026-09-06"})
                       for i in range(5)],
         "nextPageToken": "tok-2"},
        {"documents": [_doc("y1", {"title": "Last", "date": "2026-09-06"})]},
    ]
    calls = {"n": 0}

    def opener(request, timeout=None):
        page = pages[calls["n"]]
        calls["n"] += 1
        return _Resp(page)

    posts = tn.discover(LIST_URL, source_id="SRC-W-002", opener=opener)
    assert len(posts) == 6


def test_a_repeated_page_token_stops_pagination_rather_than_looping(monkeypatch):
    monkeypatch.setattr(tn.acquisition, "robots_allows", lambda url, **kw: True)

    def opener(request, timeout=None):
        # Always the same token: a misbehaving server that never progresses.
        return _Resp({
            "documents": [_doc("z1", {"title": "Loop", "date": "2026-09-06"})],
            "nextPageToken": "same-token",
        })

    posts = tn.discover(LIST_URL, source_id="SRC-W-002", opener=opener)
    # The same document ("z1") comes back on every page since the token
    # never advances; deduped by document id, not counted twice per page.
    assert len(posts) == 1


def test_discover_tags_every_post_with_source_and_platform(monkeypatch):
    monkeypatch.setattr(tn.acquisition, "robots_allows", lambda url, **kw: True)
    opener = lambda request, timeout=None: _Resp({
        "documents": [_doc("c1", {"title": "One", "date": "2026-09-06"})],
    })
    posts = tn.discover(LIST_URL, source_id="SRC-W-002", opener=opener)
    assert posts[0]["source_id"] == "SRC-W-002"
    assert posts[0]["platform"] == "WEB"


def test_discover_honours_robots_disallow(monkeypatch):
    monkeypatch.setattr(tn.acquisition, "robots_allows", lambda url, **kw: False)
    with pytest.raises(tn.DiscoveryError):
        tn.discover(LIST_URL, source_id="SRC-W-002", opener=lambda *a, **kw: _Resp({}))


def test_a_401_reports_a_named_public_rule_change_not_a_generic_error():
    import urllib.error

    def opener(request, timeout=None):
        raise urllib.error.HTTPError(LIST_URL, 401, "Unauthorized", {}, None)

    with pytest.raises(tn.DiscoveryError, match="public read rules"):
        tn._fetch_json(LIST_URL, timeout=5, opener=opener)


def test_malformed_json_raises_discovery_error():
    class _BadResp(io.BytesIO):
        def __init__(self):
            super().__init__(b"{not json}")
            self.headers = _Headers()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with pytest.raises(tn.DiscoveryError):
        tn._fetch_json(LIST_URL, timeout=5, opener=lambda *a, **kw: _BadResp())


def test_fetch_document_uses_the_documented_detail_endpoint(monkeypatch):
    monkeypatch.setattr(tn.acquisition, "robots_allows", lambda url, **kw: True)
    seen = {}

    def opener(request, timeout=None):
        seen["url"] = request.full_url
        return _Resp(_doc("l4HSkRtgLLJv2ndOa3Wq", {"title": "밀빠쏘", "date": "2026-09-06"}))

    tn.fetch_document("ktangoguide", "l4HSkRtgLLJv2ndOa3Wq", opener=opener)
    assert seen["url"] == (
        "https://firestore.googleapis.com/v1/projects/ktangoguide/databases/"
        "(default)/documents/events/l4HSkRtgLLJv2ndOa3Wq"
    )


# --- parse_list(): the fixture/snapshot dry-run entry point ------------------

def test_parse_list_reads_a_recorded_firestore_page_text():
    """The same entry point collectors._collect_snapshot() calls for every
    WEB source - a fixture dry-run must go through this, not a bespoke path."""
    raw_text = json.dumps({
        "documents": [_doc("s1", {"title": "스냅샷", "date": "2026-09-06"})],
    })
    posts = tn.parse_list(raw_text, LIST_URL)
    assert posts[0]["title"] == "스냅샷"


def test_parse_list_raises_on_invalid_json():
    with pytest.raises(tn.DiscoveryError):
        tn.parse_list("{not json}", LIST_URL)
