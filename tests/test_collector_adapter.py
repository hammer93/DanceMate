"""The adapter between the Source Master and the Information Engine collectors.

v0.75 writes no collector of its own. These tests hold that line: the engine's
existing Daum and Naver collectors are what runs, and their output is
translated rather than reimplemented.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from runtime import collectors


def _source(**overrides):
    payload = {
        "source_id": 1,
        "source_key": "SRC-D-001",
        "name": "외부홍보게시판(파티)",
        "platform": "DAUM_CAFE",
        "source_role": "PROMOTION_BOARD",
        "authority_level": "SECONDARY",
        "enabled": True,
        "url": None,
        "queries": ["밀롱가"],
        "config": {"cafe_name_hint": "라틴속으로", "url_contains": ["6uP", "5HTC"]},
    }
    payload.update(overrides)
    return payload


# --- capability reporting ---------------------------------------------------

def test_only_the_engine_backed_platforms_and_web_are_collectable():
    """FACEBOOK and DIRECTORY have no collector; WEB needs no credential."""
    assert set(collectors.SUPPORTED_PLATFORMS) == {
        "DAUM_CAFE", "NAVER_CAFE", "NAVER_BLOG", "NAVER_WEB", "WEB",
    }
    assert collectors.missing_credentials("WEB") == []


def test_each_naver_platform_reads_the_search_api_hub_serves_for_it():
    assert collectors.NAVER_KIND == {
        "NAVER_BLOG": "blog", "NAVER_CAFE": "cafe", "NAVER_WEB": "web",
    }
    # One API HUB subscription behind all three.
    for platform in collectors.NAVER_KIND:
        assert collectors.CREDENTIAL_ENV[platform] == (
            "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET")


def test_facebook_is_not_offered_as_a_first_real_source():
    """Access restrictions make it a poor first source; the engine marks it so."""
    report = collectors.describe_capability("FACEBOOK")
    assert report["live"] is False and report["snapshot"] is False


def test_missing_credentials_are_named_rather_than_implied(monkeypatch):
    monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)
    report = collectors.describe_capability("DAUM_CAFE")
    assert report["live"] is False
    assert report["missing_credentials"] == ["KAKAO_REST_API_KEY"]
    assert "KAKAO_REST_API_KEY" in report["detail"]


def test_naver_needs_both_halves_of_its_credential(monkeypatch):
    monkeypatch.setenv("NAVER_CLIENT_ID", "id")
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)
    assert collectors.missing_credentials("NAVER_BLOG") == ["NAVER_CLIENT_SECRET"]


def test_credentials_present_means_live_is_available(monkeypatch):
    monkeypatch.setenv("KAKAO_REST_API_KEY", "test-key")
    report = collectors.describe_capability("DAUM_CAFE")
    assert report["live"] is True
    assert report["missing_credentials"] == []


def test_live_collection_without_a_key_is_refused_before_any_request(settings, monkeypatch):
    monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)
    with pytest.raises(collectors.CollectorUnavailable, match="KAKAO_REST_API_KEY"):
        collectors.collect(settings, _source(), mode=collectors.MODE_LIVE)


def test_an_unsupported_platform_is_refused(settings):
    with pytest.raises(collectors.CollectorUnavailable, match="no collector"):
        collectors.collect(settings, _source(platform="FACEBOOK"))


# --- translation ------------------------------------------------------------

def test_published_date_parsing_handles_the_engine_formats():
    assert collectors._parse_published("2026-08-22") == datetime(
        2026, 8, 22, tzinfo=timezone.utc
    )
    assert collectors._parse_published("2026-08-22T10:00:00Z") == datetime(
        2026, 8, 22, 10, 0, tzinfo=timezone.utc
    )
    assert collectors._parse_published(None) is None
    assert collectors._parse_published("not a date") is None


def test_a_source_master_row_becomes_an_engine_source():
    engine_source = collectors._to_engine_source(_source())
    assert engine_source["source_id"] == "SRC-D-001"
    assert engine_source["platform"] == "DAUM_CAFE"
    assert engine_source["queries"] == ["밀롱가"]
    # collector hints travel in config so the table needs no column per platform
    assert engine_source["cafe_name_hint"] == "라틴속으로"
    assert engine_source["url_contains"] == ["6uP", "5HTC"]


def test_a_disabled_source_is_marked_inactive_for_the_engine():
    assert collectors._to_engine_source(_source(enabled=False))["status"] == "INACTIVE"


# --- snapshot collection through the engine's own code ----------------------

def test_snapshot_collection_runs_the_engine_collector(engine_settings):
    """No credentials needed: the recorded response goes through real parsing."""
    result = collectors.collect(engine_settings, _source(), mode=collectors.MODE_SNAPSHOT)
    assert result.mode == "snapshot"
    assert result.items, "the shipped Daum fixture should yield at least one record"
    item = result.items[0]
    assert item.url and item.url.startswith("http")
    assert item.title
    assert item.external_id == item.url


def test_snapshot_items_carry_the_engine_payload_for_ingest(engine_settings):
    item = collectors.collect(engine_settings, _source(), mode=collectors.MODE_SNAPSHOT).items[0]
    # engine_ingest rebuilds a RawPostRecord from exactly these keys
    for key in ("source_id", "platform", "source_url", "title", "body"):
        assert key in item.raw


def test_collected_text_is_not_mangled(engine_settings):
    """Korean and emoji must survive the collector -> RawItem translation."""
    item = collectors.collect(engine_settings, _source(), mode=collectors.MODE_SNAPSHOT).items[0]
    assert not any(0xD800 <= ord(c) <= 0xDFFF for c in item.title or ""), (
        "lone surrogates mean the text was decoded as bytes somewhere"
    )


def test_test_source_reports_snapshot_when_live_is_unavailable(engine_settings, monkeypatch):
    monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)
    report = collectors.test_source(engine_settings, _source())
    # PASS_SNAPSHOT, not PASS: a snapshot run must never read as a live pass.
    assert report["status"] == "PASS_SNAPSHOT"
    assert report["mode"] == "snapshot"
    assert report["items"] >= 1
    assert report["missing_credentials"] == ["KAKAO_REST_API_KEY"]


def test_test_source_reports_unsupported_rather_than_raising(settings):
    report = collectors.test_source(settings, _source(platform="FACEBOOK"))
    assert report["status"] == "UNSUPPORTED"


# --- WEB board collection: no engine collector, no credential --------------

def _web_source(**overrides):
    payload = {
        "source_id": 99,
        "source_key": "SRC-W-001",
        "name": "K-TANGO",
        "platform": "WEB",
        "source_role": "ORGANIZER",
        "authority_level": "PRIMARY_ORGANIZER",
        "enabled": True,
        "url": "http://www.k-tango.net/",
        "queries": [],
        "config": {"board_urls": ["http://www.k-tango.net/cnf/festival02/index.jsp"]},
    }
    payload.update(overrides)
    return payload


def test_web_needs_no_credential_and_is_always_live(settings):
    report = collectors.describe_capability("WEB")
    assert report["live"] is True
    assert report["missing_credentials"] == []


def test_web_collection_dispatches_to_web_discovery(settings, monkeypatch):
    from runtime import web_discovery

    calls = []

    def fake_discover(list_url, *, source_id, platform="WEB", **kwargs):
        calls.append((list_url, source_id))
        return [
            {
                "source_url": "http://www.k-tango.net/cnf/festival02/read.jsp?no=10",
                "title": "2024 K-TANGO SF",
                "body": "",
                "published_at": "2024-09-01T00:00:00+00:00",
                "acquisition_quality": "METADATA_ONLY",
            }
        ]

    monkeypatch.setattr(web_discovery, "discover", fake_discover)
    result = collectors.collect(settings, _web_source(), mode=collectors.MODE_LIVE)

    assert calls == [
        ("http://www.k-tango.net/cnf/festival02/index.jsp", "SRC-W-001")
    ]
    assert result.mode == collectors.MODE_LIVE
    assert len(result.items) == 1
    assert result.items[0].url == "http://www.k-tango.net/cnf/festival02/read.jsp?no=10"


def test_web_collection_without_board_urls_is_refused(settings):
    with pytest.raises(collectors.CollectorUnavailable, match="board_urls"):
        collectors.collect(settings, _web_source(config={}), mode=collectors.MODE_LIVE)


def test_web_collection_deduplicates_across_configured_boards(settings, monkeypatch):
    from runtime import web_discovery

    def fake_discover(list_url, *, source_id, platform="WEB", **kwargs):
        return [
            {
                "source_url": "http://www.k-tango.net/cnf/festival02/read.jsp?no=10",
                "title": "same post, different board",
                "body": "",
                "published_at": None,
                "acquisition_quality": "METADATA_ONLY",
            }
        ]

    monkeypatch.setattr(web_discovery, "discover", fake_discover)
    source = _web_source(config={
        "board_urls": [
            "http://www.k-tango.net/cnf/festival02/index.jsp",
            "http://www.k-tango.net/cnf/festival/index.jsp",
        ]
    })
    result = collectors.collect(settings, source, mode=collectors.MODE_LIVE)
    assert len(result.items) == 1


def test_test_source_never_writes_anything(engine_settings):
    """The [Test] button must be safe to press on a production source."""
    import inspect

    body = inspect.getsource(collectors.test_source)
    for writer in ("store_item", "start_run", "INSERT", "record_collection_result"):
        assert writer not in body
