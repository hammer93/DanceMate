from pathlib import Path
from src.database import init_db
from src.lineage_snapshot import run_snapshot

def test_lineage_snapshot(tmp_path):
    con=init_db(tmp_path/"l.sqlite3")
    t=run_snapshot(con)
    assert t["lineage"]["status"]=="COMPLETE"
    assert len(t["runs"])==3
    assert [x["stage"] for x in t["runs"]]==["DISCOVERY","ACQUISITION","RECOVERY"]
    assert t["runs"][1]["parent_observation_id"]==t["runs"][0]["observation_id"]
    assert t["runs"][2]["parent_observation_id"]==t["runs"][1]["observation_id"]
    assert len(t["posts"])==1
    assert len(t["events"])==1
    assert t["events"][0]["status"]=="VERIFIED"
    con.close()
