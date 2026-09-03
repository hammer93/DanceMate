"""Source Master: registration, validation, enable/disable and scheduling.

The rule under test throughout: a source is collected from only when an
operator has enabled it and its interval has elapsed. Registering is not
enabling, and enabling is what requires a collectable definition.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime import sources


# --- validation (pure, always runs) -----------------------------------------

def _valid(**overrides):
    payload = {
        "source_key": "SRC-T-001",
        "name": "Test source",
        "platform": "DAUM_CAFE",
        "source_role": "PROMOTION_BOARD",
        "url": None,
        "authority_level": "SECONDARY",
        "collection_interval_minutes": 60,
        "queries": ["밀롱가"],
    }
    payload.update(overrides)
    return payload


def test_a_well_formed_source_validates():
    sources.validate(**_valid())


@pytest.mark.parametrize("field", ["source_key", "name"])
def test_blank_required_fields_are_rejected(field):
    with pytest.raises(sources.SourceValidationError, match=field):
        sources.validate(**_valid(**{field: "  "}))


def test_unknown_platform_is_rejected():
    with pytest.raises(sources.SourceValidationError, match="platform"):
        sources.validate(**_valid(platform="INSTAGRAM"))


def test_unknown_role_is_rejected():
    with pytest.raises(sources.SourceValidationError, match="source_role"):
        sources.validate(**_valid(source_role="SOMETHING"))


def test_url_must_be_http():
    with pytest.raises(sources.SourceValidationError, match="url"):
        sources.validate(**_valid(url="ftp://example.invalid"))


@pytest.mark.parametrize("minutes", [0, 1, 5, 9])
def test_polling_faster_than_ten_minutes_is_rejected(minutes):
    """Protects both the microSD and the upstream service."""
    with pytest.raises(sources.SourceValidationError, match="at least 10"):
        sources.validate(**_valid(collection_interval_minutes=minutes))


def test_a_draft_source_may_have_no_query_yet():
    """A disabled source is a draft; the engine's own config has such entries."""
    sources.validate(**_valid(queries=[], url=None, for_collection=False))


def test_but_it_cannot_be_collected_from_without_one():
    with pytest.raises(sources.SourceValidationError, match="before it can be enabled"):
        sources.validate(**_valid(queries=[], url=None, for_collection=True))


def test_a_url_is_enough_to_be_collectable():
    sources.validate(
        **_valid(queries=[], url="https://cafe.daum.net/example", for_collection=True)
    )


# --- due-for-collection logic (pure) ----------------------------------------

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def _source(**overrides):
    payload = {"enabled": True, "collection_interval_minutes": 60, "last_collected_at": NOW}
    payload.update(overrides)
    return payload


def test_a_disabled_source_is_never_due():
    assert sources.is_due(_source(enabled=False, last_collected_at=None), now=NOW) is False


def test_a_never_collected_enabled_source_is_due():
    assert sources.is_due(_source(last_collected_at=None), now=NOW) is True


def test_a_source_inside_its_interval_is_not_due():
    last = NOW - timedelta(minutes=59)
    assert sources.is_due(_source(last_collected_at=last), now=NOW) is False


def test_a_source_past_its_interval_is_due():
    last = NOW - timedelta(minutes=61)
    assert sources.is_due(_source(last_collected_at=last), now=NOW) is True


def test_a_naive_timestamp_is_treated_as_utc_not_local():
    last = (NOW - timedelta(minutes=61)).replace(tzinfo=None)
    assert sources.is_due(_source(last_collected_at=last), now=NOW) is True


# --- database-backed behaviour ----------------------------------------------

pytestmark_db = pytest.mark.postgres


def test_source_is_created_disabled_by_default(pg, unique):
    created = sources.create_source(
        pg, source_key=f"SRC-T-{unique}", name="Draft", platform="DAUM_CAFE",
        source_role="PROMOTION_BOARD", queries=["밀롱가"],
    )
    assert created["enabled"] is False
    assert created["collection_interval_minutes"] == 60


def test_enable_and_disable_round_trip(pg, unique):
    created = sources.create_source(
        pg, source_key=f"SRC-T-{unique}", name="Toggle", platform="DAUM_CAFE",
        source_role="PROMOTION_BOARD", queries=["밀롱가"],
    )
    enabled = sources.set_enabled(pg, created["source_id"], True)
    assert enabled["enabled"] is True
    disabled = sources.set_enabled(pg, created["source_id"], False)
    assert disabled["enabled"] is False


def test_enabling_an_uncollectable_source_is_refused(pg, unique):
    """Regression: the rule has to hold on the enable path, not just create."""
    created = sources.create_source(
        pg, source_key=f"SRC-T-{unique}", name="No query", platform="NAVER_BLOG",
        source_role="AGGREGATOR", queries=[],
    )
    with pytest.raises(sources.SourceValidationError, match="before it can be enabled"):
        sources.set_enabled(pg, created["source_id"], True)


def test_enabling_through_update_is_refused_too(pg, unique):
    """Regression: PATCH {"enabled": true} bypassed the guard entirely."""
    created = sources.create_source(
        pg, source_key=f"SRC-T-{unique}", name="No query", platform="NAVER_CAFE",
        source_role="PROMOTION_BOARD", queries=[],
    )
    with pytest.raises(sources.SourceValidationError, match="before it can be enabled"):
        sources.update_source(pg, created["source_id"], enabled=True)


def test_adding_a_query_then_enabling_works(pg, unique):
    created = sources.create_source(
        pg, source_key=f"SRC-T-{unique}", name="Later", platform="NAVER_BLOG",
        source_role="AGGREGATOR", queries=[],
    )
    sources.update_source(pg, created["source_id"], queries=["밀롱가"])
    assert sources.set_enabled(pg, created["source_id"], True)["enabled"] is True


def test_duplicate_source_key_is_rejected(pg, unique):
    key = f"SRC-T-{unique}"
    sources.create_source(
        pg, source_key=key, name="First", platform="DAUM_CAFE",
        source_role="PROMOTION_BOARD", queries=["밀롱가"],
    )
    with pytest.raises(Exception):
        sources.create_source(
            pg, source_key=key, name="Second", platform="DAUM_CAFE",
            source_role="PROMOTION_BOARD", queries=["밀롱가"],
        )


def test_duplicate_source_url_is_rejected(pg, unique):
    url = f"https://cafe.daum.net/dup{unique}"
    sources.create_source(
        pg, source_key=f"SRC-U1-{unique}", name="First", platform="WEB",
        source_role="DIRECTORY", url=url,
    )
    with pytest.raises(Exception):
        sources.create_source(
            pg, source_key=f"SRC-U2-{unique}", name="Second", platform="WEB",
            source_role="DIRECTORY", url=url.upper(),
        )


def test_sources_without_a_url_do_not_collide(pg, unique):
    """API-backed sources are identified by queries, not by a url."""
    for n in (1, 2):
        sources.create_source(
            pg, source_key=f"SRC-N{n}-{unique}", name=f"Query source {n}",
            platform="DAUM_CAFE", source_role="PROMOTION_BOARD", queries=["밀롱가"],
        )


def test_interval_below_the_floor_is_refused_on_update(pg, unique):
    created = sources.create_source(
        pg, source_key=f"SRC-T-{unique}", name="Fast", platform="DAUM_CAFE",
        source_role="PROMOTION_BOARD", queries=["밀롱가"],
    )
    with pytest.raises(sources.SourceValidationError, match="at least 10"):
        sources.update_source(pg, created["source_id"], collection_interval_minutes=1)


def test_due_sources_lists_only_enabled_ones(pg, unique):
    enabled = sources.create_source(
        pg, source_key=f"SRC-E-{unique}", name="On", platform="DAUM_CAFE",
        source_role="PROMOTION_BOARD", queries=["밀롱가"],
    )
    sources.create_source(
        pg, source_key=f"SRC-D-{unique}", name="Off", platform="DAUM_CAFE",
        source_role="PROMOTION_BOARD", queries=["밀롱가"],
    )
    sources.set_enabled(pg, enabled["source_id"], True)

    due_keys = {s["source_key"] for s in sources.due_sources(pg)}
    assert f"SRC-E-{unique}" in due_keys
    assert f"SRC-D-{unique}" not in due_keys


def test_recording_a_collection_result_stops_the_source_being_due(pg, unique):
    created = sources.create_source(
        pg, source_key=f"SRC-T-{unique}", name="Collected", platform="DAUM_CAFE",
        source_role="PROMOTION_BOARD", queries=["밀롱가"],
    )
    sources.set_enabled(pg, created["source_id"], True)
    sources.record_collection_result(pg, created["source_id"], status="PASS", detail="ok")

    refreshed = sources.get_source(pg, created["source_id"])
    assert refreshed["last_status"] == "PASS"
    assert refreshed["last_collected_at"] is not None
    assert sources.is_due(refreshed) is False
