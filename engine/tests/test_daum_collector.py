import json
from pathlib import Path
from src.collectors.daum import clean_markup, load_snapshot

ROOT=Path(__file__).resolve().parents[1]

def test_clean_markup():
    assert clean_markup("A <b>밀롱가</b> &amp; DJ") == "A 밀롱가 & DJ"

def test_snapshot_filters_target_board():
    sources=json.loads((ROOT/"config"/"sources.json").read_text(encoding="utf-8"))
    s=next(x for x in sources if x["source_id"]=="SRC-D-001")
    rows=load_snapshot(ROOT/"data"/"collector_snapshots"/"daum-cafe-sample.json",s)
    assert len(rows)==1
    assert rows[0].source_url.endswith("/22223")
    assert "<b>" not in rows[0].title
    assert rows[0].acquisition_quality=="METADATA_ONLY"
