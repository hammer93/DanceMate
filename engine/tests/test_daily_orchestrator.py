from pathlib import Path
from src.database import init_db
from src.daily_orchestrator import run_daily
ROOT=Path(__file__).resolve().parents[1]
def test_daily_orchestrator_snapshot(tmp_path):
    con=init_db(tmp_path/"daily.sqlite3")
    t=run_daily(con,ROOT,run_date="2026-08-27",mode="snapshot")
    assert t["daily_run"]["status"]=="PASS"
    assert t["daily_run"]["discovery_lineage_count"]==2
    assert t["daily_run"]["acquisition_run_count"]>=1
    assert t["daily_run"]["metric_status"]=="PASS"
    assert Path(t["summary"]["report"]).exists()
    con.close()
