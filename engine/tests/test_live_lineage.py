from pathlib import Path
import json
from src.database import init_db,seed_sources
from src.live_lineage_harness import run_live_lineage_snapshot
ROOT=Path(__file__).resolve().parents[1]
def test_live_lineage_snapshot(tmp_path):
    con=init_db(tmp_path/"live.sqlite3")
    seed_sources(con,json.loads((ROOT/"config"/"sources.json").read_text(encoding="utf-8")))
    t=run_live_lineage_snapshot(con,ROOT)
    assert t["lineage"]["status"]=="COMPLETE"
    assert [x["stage"] for x in t["runs"]]==["DISCOVERY","ACQUISITION","RECOVERY"]
    assert t["runs"][1]["parent_observation_id"]==t["runs"][0]["observation_id"]
    assert t["runs"][2]["parent_observation_id"]==t["runs"][1]["observation_id"]
    assert len(t["posts"])>=1
    assert len(t["events"])>=1
    assert t["events"][0]["status"]=="VERIFIED"
    con.close()
