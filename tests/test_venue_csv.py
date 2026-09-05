"""Venue Master CSV import/export.

Export gives every venue as a spreadsheet; import never writes on upload —
`preview()` classifies every row first (New / Update / Duplicate / Invalid),
and only `apply_import()` on that exact preview writes anything, atomically.
"""

from __future__ import annotations

import pytest

from runtime import master_data, master_edit, venue_csv


# --- formula injection / encoding (pure, no DB) -------------------------------

def test_export_csv_starts_with_a_utf8_bom():
    body = venue_csv.to_csv([])
    assert body.startswith(b"\xef\xbb\xbf")


def test_export_csv_has_the_documented_header():
    body = venue_csv.to_csv([])
    header = body.decode("utf-8-sig").splitlines()[0]
    assert header == ",".join(venue_csv.EXPORT_COLUMNS)


def test_template_has_the_documented_columns():
    body = venue_csv.template_csv()
    header = body.decode("utf-8-sig").splitlines()[0]
    assert header == ",".join(venue_csv.TEMPLATE_COLUMNS)


@pytest.mark.parametrize("dangerous", ["=1+1", "+CMD|'/c calc'", "-2+3", "@SUM(A1)"])
def test_a_leading_formula_character_is_neutralized(dangerous):
    row = {
        "venue_id": 1, "name": dangerous, "region_code": None, "address": None,
        "aliases": [], "notes": None, "enabled": True,
        "created_at": None, "updated_at": None,
    }
    body = venue_csv.to_csv([row]).decode("utf-8-sig")
    data_line = body.splitlines()[1]
    # Excel/Sheets never re-reads this as a formula: it no longer starts with
    # =, +, -, or @ once written.
    assert not data_line.lstrip('"').startswith(("=", "+", "-", "@"))
    assert dangerous.lstrip("=+-@") in data_line


def test_a_normal_name_is_not_touched():
    row = {
        "venue_id": 1, "name": "La Ventana", "region_code": "KR-SEOUL",
        "address": "서울 마포구 잔다리로 48, 2층", "aliases": ["라벤타나", "벤타나"],
        "notes": 'has a "quote"', "enabled": True,
        "created_at": None, "updated_at": None,
    }
    body = venue_csv.to_csv([row]).decode("utf-8-sig")
    assert "La Ventana" in body
    assert "라벤타나|벤타나" in body


def test_a_comma_in_the_address_survives_the_roundtrip():
    row = {
        "venue_id": 1, "name": "Comma Test", "region_code": None,
        "address": "서울, 마포구, 잔다리로 48", "aliases": [], "notes": None,
        "enabled": True, "created_at": None, "updated_at": None,
    }
    body = venue_csv.to_csv([row])
    parsed = venue_csv.parse_csv(body)
    assert parsed[0]["address"] == "서울, 마포구, 잔다리로 48"


def test_upload_over_the_size_limit_is_rejected():
    oversized = b"a" * (venue_csv.MAX_UPLOAD_BYTES + 1)
    with pytest.raises(venue_csv.ImportTooLarge):
        venue_csv.parse_csv(oversized)


# --- preview: matching policy (DB) --------------------------------------------

def _rows(*dicts):
    """A CSV DictReader-shaped row: every column present, even if empty."""
    template = dict.fromkeys(venue_csv.TEMPLATE_COLUMNS, "")
    return [{**template, **d} for d in dicts]


def test_preview_classifies_a_brand_new_venue_as_new(pg, unique):
    result = venue_csv.preview(pg, _rows({"name": f"신규 홀 {unique}"}))
    assert result["counts"]["NEW"] == 1
    assert result["rows"][0]["status"] == venue_csv.STATUS_NEW


def test_preview_rejects_a_blank_name(pg):
    result = venue_csv.preview(pg, _rows({"name": "", "address": "somewhere"}))
    assert result["counts"]["INVALID"] == 1
    assert "name is required" in result["rows"][0]["errors"][0]


def test_preview_flags_an_unregistered_region(pg, unique):
    result = venue_csv.preview(
        pg, _rows({"name": f"장소 {unique}", "region": "Atlantis"})
    )
    assert result["counts"]["INVALID"] == 1
    assert "INVALID_REGION" in result["rows"][0]["errors"][0]


def test_preview_accepts_a_region_by_code_or_by_name(pg, unique, seoul_id, seoul_name):
    by_code = venue_csv.preview(pg, _rows({"name": f"코드매칭 {unique}", "region": "KR-SEOUL"}))
    by_name = venue_csv.preview(pg, _rows({"name": f"이름매칭 {unique}", "region": seoul_name}))
    assert by_code["rows"][0]["region_id"] == seoul_id
    assert by_name["rows"][0]["region_id"] == seoul_id


def test_preview_matches_an_explicit_id_to_an_existing_venue(pg, unique):
    venue = master_data.create_venue(pg, name=f"기존 장소 {unique}")
    result = venue_csv.preview(
        pg, _rows({"id": str(venue["venue_id"]), "name": f"이름 변경 {unique}"})
    )
    assert result["rows"][0]["status"] == venue_csv.STATUS_UPDATE
    assert result["rows"][0]["matched_venue_id"] == venue["venue_id"]
    assert result["rows"][0]["reasons"] == ["explicit id"]


def test_preview_rejects_an_explicit_id_that_does_not_exist(pg):
    result = venue_csv.preview(pg, _rows({"id": "999999999", "name": "유령 장소"}))
    assert result["counts"]["INVALID"] == 1


def test_preview_matches_by_exact_name_and_address(pg, unique):
    master_data.create_venue(
        pg, name=f"정확매칭 {unique}", address="서울 마포구 1번지"
    )
    result = venue_csv.preview(
        pg, _rows({"name": f"정확매칭 {unique}", "address": "서울 마포구 1번지"})
    )
    assert result["rows"][0]["status"] == venue_csv.STATUS_UPDATE
    assert "same name" in result["rows"][0]["reasons"]
    assert "same address" in result["rows"][0]["reasons"]


def test_preview_matches_by_a_registered_alias(pg, unique):
    master_data.create_venue(
        pg, name=f"본명 {unique}", aliases=[f"별칭 {unique}"]
    )
    result = venue_csv.preview(pg, _rows({"name": f"별칭 {unique}"}))
    assert result["rows"][0]["status"] == venue_csv.STATUS_UPDATE
    assert any(r.startswith("registered alias") for r in result["rows"][0]["reasons"])


def test_preview_warns_rather_than_merges_on_a_same_name_different_address(pg, unique):
    """PISTA/Seoul and PISTA/Busan are not the same venue."""
    master_data.create_venue(
        pg, name=f"PISTA {unique}", address="서울 마포구"
    )
    result = venue_csv.preview(
        pg, _rows({"name": f"PISTA {unique}", "address": "부산 해운대구"})
    )
    assert result["counts"]["DUPLICATE"] == 1
    assert result["rows"][0]["status"] == venue_csv.STATUS_DUPLICATE


# --- apply: writing, atomicity, idempotence -----------------------------------

def test_apply_creates_new_venues_and_records_an_audit_row(pg, unique):
    result = venue_csv.preview(pg, _rows({"name": f"생성 테스트 {unique}", "active": "true"}))
    applied = venue_csv.apply_import(
        pg, result["rows"], reviewer="tester", filename="rows.csv"
    )
    assert applied["created"] == 1
    venue = master_data.get_venue(pg, applied["rows"][0]["venue_id"])
    assert venue["name"] == f"생성 테스트 {unique}"

    with pg.cursor() as cur:
        cur.execute(
            "SELECT action, reviewer FROM master_data_actions "
            "WHERE entity_type = 'VENUE' AND entity_id = %s",
            (venue["venue_id"],),
        )
        row = cur.fetchone()
    assert row == ("VENUE_CSV_IMPORT", "tester")


def test_apply_updates_an_existing_venue_and_keeps_its_id(pg, unique):
    venue = master_data.create_venue(pg, name=f"수정 전 {unique}")
    result = venue_csv.preview(
        pg, _rows({"id": str(venue["venue_id"]), "name": f"수정 후 {unique}"})
    )
    applied = venue_csv.apply_import(pg, result["rows"], reviewer="t", filename="x.csv")
    assert applied["updated"] == 1
    reloaded = master_data.get_venue(pg, venue["venue_id"])
    assert reloaded["venue_id"] == venue["venue_id"]
    assert reloaded["name"] == f"수정 후 {unique}"


def test_apply_preserves_the_event_venue_relation_across_an_update(pg, unique, seoul_id):
    from datetime import date

    from runtime import normalization

    venue = master_data.create_venue(pg, name=f"관계 보존 {unique}", region_id=seoul_id)
    normalized = normalization.normalize_candidate(pg, {
        "candidate_id": int(f"{unique[-6:]}1"), "post_id": 1,
        "source_url": f"https://cafe.daum.net/rel/{unique}",
        "event_name": f"관계 테스트 밀롱가 {unique}", "event_type": "MILONGA",
        "event_date": date.today().isoformat(), "start_time": "19:30",
        "end_time": "23:30", "end_day_offset": 0,
        "venue": f"관계 보존 {unique}", "fee": 10000,
        "candidate_status": "POSSIBLE", "provenance": "LIVE",
    })
    assert normalized["venue_id"] == venue["venue_id"]

    result = venue_csv.preview(pg, _rows({
        "id": str(venue["venue_id"]), "name": f"관계 보존 {unique}",
        "notes": "CSV로 갱신됨",
    }))
    venue_csv.apply_import(pg, result["rows"], reviewer="t", filename="x.csv")

    with pg.cursor() as cur:
        cur.execute(
            "SELECT venue_id FROM events WHERE event_id = %s", (normalized["event_id"],)
        )
        (still_linked,) = cur.fetchone()
    assert still_linked == venue["venue_id"]


def test_apply_adds_new_aliases_without_removing_existing_ones(pg, unique):
    venue = master_data.create_venue(
        pg, name=f"별칭 병합 {unique}", aliases=[f"기존별칭 {unique}"]
    )
    result = venue_csv.preview(pg, _rows({
        "id": str(venue["venue_id"]), "name": f"별칭 병합 {unique}",
        "aliases": f"새별칭 {unique}",
    }))
    venue_csv.apply_import(pg, result["rows"], reviewer="t", filename="x.csv")

    alias_texts = {a["alias"] for a in master_data.venue_aliases(pg, venue["venue_id"])}
    assert f"기존별칭 {unique}" in alias_texts
    assert f"새별칭 {unique}" in alias_texts


def test_apply_skips_duplicate_rows_and_writes_nothing_for_them(pg, unique):
    master_data.create_venue(pg, name=f"충돌 {unique}", address="서울 A")
    result = venue_csv.preview(
        pg, _rows({"name": f"충돌 {unique}", "address": "부산 B"})
    )
    applied = venue_csv.apply_import(pg, result["rows"], reviewer="t", filename="x.csv")
    assert applied["duplicate_skipped"] == 1
    assert applied["created"] == 0 and applied["updated"] == 0


def test_apply_refuses_the_whole_batch_if_any_row_is_invalid(pg, unique):
    result = venue_csv.preview(pg, _rows(
        {"name": f"유효 {unique}"}, {"name": ""},
    ))
    with pytest.raises(venue_csv.ImportRejected):
        venue_csv.apply_import(pg, result["rows"], reviewer="t", filename="x.csv")

    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM venues WHERE name = %s", (f"유효 {unique}",))
        (count,) = cur.fetchone()
    assert count == 0, "an invalid row in the batch must block the whole import"


def test_reimporting_an_unmodified_row_changes_nothing(pg, unique):
    """A no-op update writes nothing and is counted separately from a real one."""
    venue = master_data.create_venue(
        pg, name=f"변경없음 {unique}", address="서울 어딘가", notes="원래 메모"
    )
    result = venue_csv.preview(pg, _rows({
        "id": str(venue["venue_id"]), "name": f"변경없음 {unique}",
        "address": "서울 어딘가", "notes": "원래 메모",
    }))
    applied = venue_csv.apply_import(pg, result["rows"], reviewer="t", filename="x.csv")
    assert applied["noop"] == 1
    assert applied["updated"] == 0


def test_export_then_reimport_with_no_edits_is_a_full_roundtrip_noop(pg, unique):
    """Export -> Preview -> Confirm with no edits must change nothing."""
    master_data.create_venue(
        pg, name=f"라운드트립 {unique}", address="서울 라운드트립로 1",
        aliases=[f"별칭라운드 {unique}"], notes="메모",
    )
    exported = venue_csv.export_rows(pg)
    csv_bytes = venue_csv.to_csv(exported)
    reparsed = venue_csv.parse_csv(csv_bytes)

    result = venue_csv.preview(pg, reparsed)
    assert result["counts"]["NEW"] == 0
    assert result["counts"]["DUPLICATE"] == 0
    assert result["counts"]["INVALID"] == 0

    applied = venue_csv.apply_import(pg, result["rows"], reviewer="t", filename="export.csv")
    assert applied["created"] == 0
    assert applied["updated"] == 0
    assert applied["noop"] == result["counts"]["UPDATE"]
