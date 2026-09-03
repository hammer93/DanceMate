from src.extractor import _norm_date

def test_korean_month_day_date():
    d,raw,inf=_norm_date("8월 22일 토요일",default_year=2026)
    assert d=="2026-08-22" and inf=="YEAR_FROM_CONTEXT"

def test_korean_full_year_date():
    d,raw,inf=_norm_date("2026년 8월 22일",default_year=2025)
    assert d=="2026-08-22" and inf is None

def test_korean_two_digit_year_date():
    d,raw,inf=_norm_date("26년 08월 22일",default_year=2025)
    assert d=="2026-08-22"
