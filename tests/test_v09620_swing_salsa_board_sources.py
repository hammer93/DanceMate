"""v0.96.20 Salsa/Swing direct source coverage expansion.

This release adds no parser and no schema. It registers public Daum Cafe event
boards through the one path that already carries the whole admission gate -
`scripts/apply-board-sources.py`: preview, `/test` must PASS with items, enable
only then, record a decision, read the row back.

What had to change is that the gate was Salsa-only. v0.82 hard-coded
``genre_code="SALSA"`` and one ``board_url``, so a Swing board could not go
through it at all, and an *enabled* Source could never be re-pointed at a
better board. Both are now spec fields, and `docs/SALSA_BOARD_SOURCES.json`
still produces byte-identical configs - that is what the first test asserts.

Why boards at all, and why so few: measured read-only against Production on
2026-09-28, every one of the 8 registered NAVER_CAFE sources is
ROBOTS_DISALLOWED - 814 stored items, 0 usable bodies, which is where 346 of
Swing's 406 collected items go - and several Daum boards answer 200 with
BODY_UNAVAILABLE because they are members-only. So the Korean Swing scene
publishes its schedules where this project may not read them, and the sources
below are the ones whose bodies are actually public.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SALSA_SPEC = ROOT / "docs" / "SALSA_BOARD_SOURCES.json"
NEW_SPEC = ROOT / "docs" / "SWING_SALSA_BOARD_SOURCES.json"


def _script():
    spec = importlib.util.spec_from_file_location(
        "apply_board_sources", ROOT / "scripts" / "apply-board-sources.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _script()


@pytest.fixture(scope="module")
def specs():
    return json.loads(NEW_SPEC.read_text(encoding="utf-8"))


# --- the v0.82 round must be untouched by the generalization ---------------

def test_the_salsa_round_still_builds_exactly_the_config_it_always_did(script):
    """Every field this release added defaults to v0.82's behaviour.

    The Salsa specs carry no genre_code, no board_urls, no parser and no
    lookback_days, so each must come out as the literal the old code wrote.
    """
    for spec in json.loads(SALSA_SPEC.read_text(encoding="utf-8")):
        config = script.board_config(spec)
        assert config == {
            "parser": "daum_cafe_board",
            "community_id": spec["community_id"],
            "cafe_url": spec["url"],
            "board_name": spec["board_name"],
            "board_type": spec["board_type"],
            "board_urls": [spec["board_url"]],
            "lookback_days": 60,
            "genre_code": "SALSA",
        }, spec["source_key"]
        assert script.primary_board_url(spec) == spec["board_url"]


def test_a_cafe_the_communities_master_does_not_list_still_registers(script):
    """SRC-D-021 and SRC-D-031's cafes have no `communities` row, and a source
    does not need one - the collector's own parameter is optional."""
    config = script.board_config({
        "url": "https://cafe.daum.net/sdamu", "board_name": "b",
        "board_type": "EVENT_PRIMARY", "board_url": "https://x/y",
    })
    assert config["community_id"] is None


# --- the new spec ---------------------------------------------------------

def test_every_new_spec_is_shaped_for_the_existing_collector(script, specs):
    for spec in specs:
        config = script.board_config(spec)
        assert config["parser"] == "daum_cafe_board", spec["source_key"]
        assert config["board_urls"], spec["source_key"]
        assert config["board_type"] in ("EVENT_PRIMARY", "CLASS_PRIMARY")
        assert config["genre_code"] in ("SALSA", "SWING")
        assert 1 <= config["lookback_days"] <= 90, "the collector's own bound"
        for url in config["board_urls"]:
            assert url.startswith("https://cafe.daum.net/_c21_/bbs_list?grpid=")
            assert "&fldid=" in url, "a board is a grpid/fldid pair"


def test_no_new_spec_duplicates_a_source_key_or_a_board(specs):
    keys = [s["source_key"] for s in specs]
    assert len(keys) == len(set(keys))
    boards = [u for s in specs for u in s["board_urls"]]
    assert len(boards) == len(set(boards))


def test_a_row_that_already_exists_is_reused_never_re_added(specs):
    """SRC-D-023 and SRC-D-024 were registered disabled in the 2026-09-09
    round, and SRC-D-021 has been collecting since v0.85. Adding them again
    would be exactly the duplicate this release was told not to create, so each
    names the source_id it expects to find."""
    by_key = {s["source_key"]: s for s in specs}
    for key, source_id in (("SRC-D-021", 339), ("SRC-D-023", 5397),
                           ("SRC-D-024", 5398)):
        spec = by_key[key]
        assert spec["mode"] in ("REUSE", "UPGRADE"), key
        assert spec["expected_source_id"] == source_id, key
    assert by_key["SRC-D-031"]["mode"] == "ADD"
    assert "expected_source_id" not in by_key["SRC-D-031"]


def test_both_target_genres_gain_an_enabled_direct_source(specs):
    enabled = [s for s in specs if s.get("enable", True)]
    genres = {s["genre_code"] for s in enabled}
    assert genres == {"SALSA", "SWING"}
    assert sum(1 for s in enabled if s["genre_code"] == "SWING") == 2
    assert sum(1 for s in enabled if s["genre_code"] == "SALSA") == 1


def test_at_least_one_accepted_source_is_outside_seoul(specs):
    """A handful of Seoul boards is not coverage expansion. 린디성 is 수원."""
    regions = {s["region_code"] for s in specs if s.get("enable", True)}
    assert regions - {"KR-SEOUL"}, regions
    assert "KR-GYEONGGI" in regions


def test_the_class_board_is_registered_as_a_class_board_and_left_off(specs):
    """라틴파라다이스's public board is real and is entirely class recruitment.

    Read as EVENT_PRIMARY it produced two false events - the date from the
    party named in the title, the hours from the weekly class in the body. It
    is registered CLASS_PRIMARY, which yields none, and left disabled.
    """
    spec = next(s for s in specs if s["source_key"] == "SRC-D-031")
    assert spec["board_type"] == "CLASS_PRIMARY"
    assert spec.get("enable") is False
    assert "false event" in spec["notes"]


def test_every_spec_records_why_it_was_accepted(specs):
    """A Source row whose reason lives only in a chat log is a Source nobody
    can re-audit. Each spec carries its measured yield and its decision."""
    for spec in specs:
        assert spec["notes"].startswith("v0.96.20:"), spec["source_key"]
        assert "2026-09-28" in spec["notes"], spec["source_key"]
        assert spec["decision_reason"].startswith("v0.96.20:"), spec["source_key"]


# --- the admission gate itself -------------------------------------------

def test_an_enabled_source_is_not_silently_repointed(script, monkeypatch):
    """The guard that protects an enabled row still fires for everything but an
    explicit UPGRADE that names the source_id."""
    calls = []

    class FakeAdmin:
        def __init__(self, env):
            pass

        def request(self, path, *, method="GET", data=None):
            calls.append((method, path))
            if path == "/api/admin/genres":
                return [{"code": "SALSA", "genre_id": 1},
                        {"code": "SWING", "genre_id": 2}]
            if path == "/api/admin/regions":
                return [{"code": "KR-SEOUL", "region_id": 2}]
            if path == "/api/admin/sources":
                return [{"source_key": "SRC-D-021", "source_id": 339,
                         "enabled": True, "url": "https://old/board",
                         "name": "old name", "config": {}}]
            raise AssertionError(f"unexpected {method} {path}")

    monkeypatch.setattr(script, "Admin", FakeAdmin)
    monkeypatch.setattr(script, "_env", lambda: {})
    spec = {
        "mode": "REUSE", "expected_source_id": 339, "source_key": "SRC-D-021",
        "name": "new name", "genre_code": "SALSA", "region_code": "KR-SEOUL",
        "url": "https://cafe.daum.net/sdamu", "board_name": "b",
        "board_type": "EVENT_PRIMARY",
        "board_urls": ["https://cafe.daum.net/_c21_/bbs_list?grpid=W&fldid=1"],
    }
    path = Path(__file__).parent / "_v09620_tmp_spec.json"
    path.write_text(json.dumps([spec]), encoding="utf-8")
    try:
        with pytest.raises(RuntimeError, match="already enabled with different"):
            script.apply(write=False, source_file=path)
        spec["mode"] = "UPGRADE"
        path.write_text(json.dumps([spec]), encoding="utf-8")
        script.apply(write=False, source_file=path)      # previews cleanly
    finally:
        path.unlink()
    assert ("POST", "/api/admin/sources") not in calls, "preview writes nothing"


def test_an_upgrade_must_name_the_source_id_it_expects(script, monkeypatch):
    class FakeAdmin:
        def __init__(self, env):
            pass

        def request(self, path, *, method="GET", data=None):
            if path == "/api/admin/genres":
                return [{"code": "SALSA", "genre_id": 1}]
            if path == "/api/admin/regions":
                return [{"code": "KR-SEOUL", "region_id": 2}]
            if path == "/api/admin/sources":
                return [{"source_key": "SRC-D-021", "source_id": 339,
                         "enabled": True, "url": "u", "name": "n", "config": {}}]
            raise AssertionError(path)

    monkeypatch.setattr(script, "Admin", FakeAdmin)
    monkeypatch.setattr(script, "_env", lambda: {})
    spec = {
        "mode": "UPGRADE", "expected_source_id": 999, "source_key": "SRC-D-021",
        "name": "n2", "genre_code": "SALSA", "region_code": "KR-SEOUL",
        "url": "https://cafe.daum.net/sdamu", "board_name": "b",
        "board_type": "EVENT_PRIMARY", "board_urls": ["https://x?grpid=a&fldid=b"],
    }
    path = Path(__file__).parent / "_v09620_tmp_spec2.json"
    path.write_text(json.dumps([spec]), encoding="utf-8")
    try:
        with pytest.raises(RuntimeError, match="reuse guard failed"):
            script.apply(write=False, source_file=path)
    finally:
        path.unlink()
