"""Source Master CSV import/export.

Export gives every source as a spreadsheet; import never writes on upload -
`preview()` classifies every row first (New / Update / Invalid), and only
`apply_import()` on that exact preview writes anything, atomically. Unlike
venues, a source is only ever matched by an explicit id or its own
source_key - never by name, since two sources can legitimately share one.
"""

from __future__ import annotations

import pytest

from runtime import master_data, source_csv, sources


# --- formula injection / encoding (pure, no DB) -------------------------------

def test_export_csv_starts_with_a_utf8_bom():
    body = source_csv.to_csv([])
    assert body.startswith(b"\xef\xbb\xbf")


def test_export_csv_has_the_documented_header():
    body = source_csv.to_csv([])
    header = body.decode("utf-8-sig").splitlines()[0]
    assert header == ",".join(source_csv.EXPORT_COLUMNS)


def test_template_has_the_documented_columns():
    body = source_csv.template_csv()
    header = body.decode("utf-8-sig").splitlines()[0]
    assert header == ",".join(source_csv.TEMPLATE_COLUMNS)


def test_no_credential_column_is_ever_exported():
    """Nothing in the sources table is a secret - API keys/tokens live only
    in .env - but this pins that guarantee against future schema drift."""
    secret_hints = ("secret", "token", "password", "api_key", "credential")
    for column in source_csv.EXPORT_COLUMNS:
        assert not any(hint in column.lower() for hint in secret_hints), column


@pytest.mark.parametrize("dangerous", ["=1+1", "+CMD|'/c calc'", "-2+3", "@SUM(A1)"])
def test_a_leading_formula_character_is_neutralized(dangerous):
    row = {
        "source_id": 1, "source_key": "SRC-T-001", "name": dangerous,
        "platform": "WEB", "source_role": "COMMUNITY", "authority_level": "SECONDARY",
        "genre_code": None, "region_name": None, "url": None, "queries": [],
        "collection_interval_minutes": 60, "enabled": False, "notes": None,
        "last_status": None, "last_collected_at": None,
        "created_at": None, "updated_at": None,
    }
    body = source_csv.to_csv([row]).decode("utf-8-sig")
    data_line = body.splitlines()[1]
    assert not data_line.lstrip('"').startswith(("=", "+", "-", "@"))
    assert dangerous.lstrip("=+-@") in data_line


def test_queries_roundtrip_through_the_separator():
    row = {
        "source_id": 1, "source_key": "SRC-T-001", "name": "Seoul Tango",
        "platform": "NAVER_BLOG", "source_role": "COMMUNITY", "authority_level": "SECONDARY",
        "genre_code": "TANGO", "region_name": "Seoul", "url": None,
        "queries": ["서울 탱고", "밀롱가"], "collection_interval_minutes": 240,
        "enabled": True, "notes": None, "last_status": None, "last_collected_at": None,
        "created_at": None, "updated_at": None,
    }
    body = source_csv.to_csv([row])
    parsed = source_csv.parse_csv(body)
    assert parsed[0]["queries"] == "서울 탱고|밀롱가"


def test_upload_over_the_size_limit_is_rejected():
    oversized = b"a" * (source_csv.MAX_UPLOAD_BYTES + 1)
    with pytest.raises(source_csv.ImportTooLarge):
        source_csv.parse_csv(oversized)


# --- preview: matching policy (DB) --------------------------------------------

def _rows(*dicts):
    """A CSV DictReader-shaped row: every column present, even if empty."""
    template = dict.fromkeys(source_csv.TEMPLATE_COLUMNS, "")
    return [{**template, **d} for d in dicts]


def _preview(pg, dicts):
    genres = master_data.list_genres(pg)
    regions = master_data.list_regions(pg)
    return source_csv.preview(pg, _rows(*dicts), genres=genres, regions=regions)


def test_preview_classifies_a_brand_new_disabled_source_as_new(pg, unique):
    result = _preview(pg, [{
        "source_key": f"SRC-T-{unique}", "name": f"신규 소스 {unique}",
        "platform": "WEB", "source_role": "COMMUNITY",
    }])
    assert result["counts"]["NEW"] == 1
    assert result["rows"][0]["status"] == source_csv.STATUS_NEW


def test_preview_rejects_a_blank_source_key(pg):
    result = _preview(pg, [{"name": "이름만 있음", "platform": "WEB", "source_role": "COMMUNITY"}])
    assert result["counts"]["INVALID"] == 1
    assert "source_key is required" in result["rows"][0]["errors"][0]


def test_preview_rejects_an_unknown_platform(pg, unique):
    result = _preview(pg, [{
        "source_key": f"SRC-T-{unique}", "name": "X",
        "platform": "MYSPACE", "source_role": "COMMUNITY",
    }])
    assert result["counts"]["INVALID"] == 1


def test_preview_flags_an_unregistered_genre(pg, unique):
    result = _preview(pg, [{
        "source_key": f"SRC-T-{unique}", "name": "X", "platform": "WEB",
        "source_role": "COMMUNITY", "genre": "DISCO",
    }])
    assert result["counts"]["INVALID"] == 1
    assert "INVALID_GENRE" in result["rows"][0]["errors"][0]


def test_preview_accepts_a_genre_by_code_or_by_name(pg, unique):
    genre = master_data.list_genres(pg)[0]
    by_code = _preview(pg, [{
        "source_key": f"SRC-T-{unique}-1", "name": "X", "platform": "WEB",
        "source_role": "COMMUNITY", "genre": genre["code"],
    }])
    by_name = _preview(pg, [{
        "source_key": f"SRC-T-{unique}-2", "name": "X", "platform": "WEB",
        "source_role": "COMMUNITY", "genre": genre["name"],
    }])
    assert by_code["rows"][0]["genre_id"] == genre["genre_id"]
    assert by_name["rows"][0]["genre_id"] == genre["genre_id"]


def test_preview_matches_an_explicit_id_to_an_existing_source(pg, unique):
    source = sources.create_source(
        pg, source_key=f"SRC-T-{unique}", name=f"기존 소스 {unique}",
        platform="WEB", source_role="COMMUNITY",
    )
    result = _preview(pg, [{
        "id": str(source["source_id"]), "source_key": source["source_key"],
        "name": f"이름 변경 {unique}", "platform": "WEB", "source_role": "COMMUNITY",
    }])
    assert result["rows"][0]["status"] == source_csv.STATUS_UPDATE
    assert result["rows"][0]["matched_source_id"] == source["source_id"]
    assert result["rows"][0]["reasons"] == ["explicit id"]


def test_preview_rejects_an_explicit_id_that_does_not_exist(pg):
    result = _preview(pg, [{
        "id": "999999999", "source_key": "SRC-GHOST", "name": "유령",
        "platform": "WEB", "source_role": "COMMUNITY",
    }])
    assert result["counts"]["INVALID"] == 1


def test_preview_matches_by_source_key_alone(pg, unique):
    source = sources.create_source(
        pg, source_key=f"SRC-T-{unique}", name=f"원래 이름 {unique}",
        platform="WEB", source_role="COMMUNITY",
    )
    result = _preview(pg, [{
        "source_key": source["source_key"], "name": f"바뀐 이름 {unique}",
        "platform": "WEB", "source_role": "COMMUNITY",
    }])
    assert result["rows"][0]["status"] == source_csv.STATUS_UPDATE
    assert result["rows"][0]["matched_source_id"] == source["source_id"]
    assert result["rows"][0]["reasons"] == ["source_key"]


def test_two_sources_may_legitimately_share_a_name(pg, unique):
    """Unlike a venue, a source is never matched by name - so registering a
    second, differently-keyed source with the same display name is NEW, not
    a duplicate warning."""
    sources.create_source(
        pg, source_key=f"SRC-T-{unique}-A", name=f"K-TANGO {unique}",
        platform="WEB", source_role="COMMUNITY",
    )
    result = _preview(pg, [{
        "source_key": f"SRC-T-{unique}-B", "name": f"K-TANGO {unique}",
        "platform": "NAVER_BLOG", "source_role": "COMMUNITY",
    }])
    assert result["rows"][0]["status"] == source_csv.STATUS_NEW


def test_preview_rejects_enabling_an_api_source_with_no_query_or_url(pg, unique):
    """The same rule sources.set_enabled() already enforces: an API-backed
    platform needs a query or a url before it can be turned on."""
    result = _preview(pg, [{
        "source_key": f"SRC-T-{unique}", "name": "X", "platform": "NAVER_BLOG",
        "source_role": "COMMUNITY", "enabled": "true",
    }])
    assert result["counts"]["INVALID"] == 1


def test_preview_accepts_enabling_an_api_source_with_a_query(pg, unique):
    result = _preview(pg, [{
        "source_key": f"SRC-T-{unique}", "name": "X", "platform": "NAVER_BLOG",
        "source_role": "COMMUNITY", "enabled": "true", "queries": "서울 탱고",
    }])
    assert result["counts"]["NEW"] == 1


def test_preview_rejects_a_non_numeric_interval(pg, unique):
    result = _preview(pg, [{
        "source_key": f"SRC-T-{unique}", "name": "X", "platform": "WEB",
        "source_role": "COMMUNITY", "collection_interval_minutes": "soon",
    }])
    assert result["counts"]["INVALID"] == 1


# --- apply: writing, atomicity, idempotence -----------------------------------

def test_apply_creates_a_new_source_and_records_an_audit_row(pg, unique):
    result = _preview(pg, [{
        "source_key": f"SRC-T-{unique}", "name": f"생성 테스트 {unique}",
        "platform": "WEB", "source_role": "COMMUNITY", "notes": "테스트",
    }])
    applied = source_csv.apply_import(
        pg, result["rows"], reviewer="tester", filename="rows.csv"
    )
    assert applied["created"] == 1
    source = sources.get_source(pg, applied["rows"][0]["source_id"])
    assert source["name"] == f"생성 테스트 {unique}"
    assert source["enabled"] is False  # new rows never come in enabled by default

    with pg.cursor() as cur:
        cur.execute(
            "SELECT action, reviewer FROM master_data_actions "
            "WHERE entity_type = 'SOURCE' AND entity_id = %s",
            (source["source_id"],),
        )
        row = cur.fetchone()
    assert row == ("SOURCE_CSV_IMPORT", "tester")


def test_apply_updates_an_existing_source(pg, unique):
    source = sources.create_source(
        pg, source_key=f"SRC-T-{unique}", name=f"원래 {unique}",
        platform="WEB", source_role="COMMUNITY", notes="old",
    )
    result = _preview(pg, [{
        "source_key": source["source_key"], "name": f"변경됨 {unique}",
        "platform": "WEB", "source_role": "COMMUNITY", "notes": "new",
    }])
    applied = source_csv.apply_import(
        pg, result["rows"], reviewer="tester", filename="rows.csv"
    )
    assert applied["updated"] == 1
    updated = sources.get_source(pg, source["source_id"])
    assert updated["name"] == f"변경됨 {unique}"
    assert updated["notes"] == "new"


def test_apply_is_a_noop_on_an_unchanged_roundtrip(pg, unique):
    source = sources.create_source(
        pg, source_key=f"SRC-T-{unique}", name=f"그대로 {unique}",
        platform="WEB", source_role="COMMUNITY",
    )
    result = _preview(pg, [{
        "source_key": source["source_key"], "name": source["name"],
        "platform": "WEB", "source_role": "COMMUNITY",
    }])
    applied = source_csv.apply_import(
        pg, result["rows"], reviewer="tester", filename="rows.csv"
    )
    assert applied == {
        "created": 0, "updated": 0, "noop": 1, "rows": applied["rows"],
    }


def test_apply_rejects_the_whole_batch_if_any_row_is_invalid(pg, unique):
    result = _preview(pg, [
        {"source_key": f"SRC-T-{unique}-ok", "name": "OK", "platform": "WEB",
         "source_role": "COMMUNITY"},
        {"source_key": "", "name": "no key", "platform": "WEB", "source_role": "COMMUNITY"},
    ])
    with pytest.raises(source_csv.ImportRejected):
        source_csv.apply_import(pg, result["rows"], reviewer="tester", filename="rows.csv")
    # Nothing from the valid row was written either - all or nothing.
    assert sources.get_source_by_key(pg, f"SRC-T-{unique}-ok") is None
