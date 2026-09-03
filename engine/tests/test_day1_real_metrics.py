import json
from pathlib import Path
from src.day1_real_metrics import calculate
ROOT=Path(__file__).resolve().parents[1]
def test_real_day1():
    m=calculate(json.loads((ROOT/"data"/"day1_real"/"2026-08-27.json").read_text(encoding="utf-8")))
    assert (m["event_count"],m["verified_fields"],m["expected_fields"],m["unknown_fields"])==(4,12,3,1)
    assert m["field_coverage_rate"]==0.75
    assert m["known_field_rate"]==0.9375
    assert m["fee_expected_rate"]==0.75
    assert m["observed_primary_access_problem_rate"]==1.0
    assert m["source_yield_rate"] is None
