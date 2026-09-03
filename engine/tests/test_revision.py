from src.revision import classify_revision,extract_change_hints
def test_revision_roles():
    assert classify_revision("오늘 밀롱가 취소합니다").role=="CANCELLATION"
    assert classify_revision("오늘만 시작 시간 변경합니다. 21시 시작").role=="UPDATE"
    assert classify_revision("8/29 밀롱가 20시").role=="ORIGINAL"
def test_change_hint():
    assert extract_change_hints("오늘만 시작 시간 변경합니다. 21시 시작")["start_time"]=="21:00"
