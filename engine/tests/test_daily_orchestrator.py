from pathlib import Path
from src.database import init_db
from src.daily_orchestrator import run_daily
ROOT=Path(__file__).resolve().parents[1]
def test_daily_orchestrator_snapshot(tmp_path):
    con=init_db(tmp_path/"daily.sqlite3")
    # Reports go to tmp_path, not into the checkout. The repository is mounted
    # read-only when this suite runs on the board, and a test that needs a
    # writable source tree fails there for reasons that have nothing to do with
    # what it is testing.
    t=run_daily(con,ROOT,run_date="2026-08-27",mode="snapshot",
                report_dir=tmp_path/"reports")
    assert t["daily_run"]["status"]=="PASS"
    assert t["daily_run"]["discovery_lineage_count"]==2
    assert t["daily_run"]["acquisition_run_count"]>=1
    assert t["daily_run"]["metric_status"]=="PASS"
    report=Path(t["summary"]["report"])
    assert report.exists()
    assert tmp_path in report.parents, "the run must not write into the checkout"
    con.close()
