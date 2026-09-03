from pathlib import Path
from src.gate1_validation import run_validation

ROOT=Path(__file__).resolve().parents[1]

def test_gate1_14d_sample_passes():
    r=run_validation(
      ROOT/"data"/"ground_truth"/"gate1-ground-truth-14d-v0.8.csv",
      ROOT/"data"/"validation"/"gate1-dancemate-results-14d-v0.8.csv")
    assert r["gate"]=="PASS"
    assert r["aggregate"]["event_recall"]>=0.85
    assert r["aggregate"]["verified_precision"]==1.0
    assert r["aggregate"]["critical_cancellation_miss"]==0
    assert r["aggregate"]["false_verified"]==0

def test_gate1_p0_failure_fails():
    r=run_validation(
      ROOT/"data"/"ground_truth"/"gate1-ground-truth-14d-v0.8.csv",
      ROOT/"data"/"validation"/"gate1-dancemate-results-fail-v0.8.csv")
    assert r["gate"]=="FAIL"
    assert r["aggregate"]["critical_cancellation_miss"]>0
    assert r["aggregate"]["false_verified"]>0
