"""Salsa/Swing funnel root-cause fixes (v0.91.0 PHASE 2).

classify() is genre-blind by design: it looks for 소셜/파티/social/party and a
handful of class words in the raw text, not for "살사"/"스윙"/"바차타"
themselves (see src/classifier.py's own comment on SOCIAL_WORDS). That is
exactly what lets a Salsa or Swing post read as an event with zero
Salsa/Swing-specific vocabulary -- but it also means nothing here stops a
post that happens to use the same words for an unrelated "swing" (a golf
swing, a stock swing-trade, a door hinge) or an unrelated "salsa" (a sauce)
from being misread, if such a post ever reaches the classifier. These pin
that today's word list does not accidentally fire on the other senses of
the two words the collectors search for.
"""

from src.classifier import classify
from src.live_pipeline import EVENT_CLASSIFICATIONS


# --- "swing" that has nothing to do with the dance --------------------------
#
# "모집"/"lesson" are generic enough that a golf or stock course recruiting
# students trips has_class the same way a dance lesson advert does -- that
# alone doesn't put a public event in front of a reader, because CLASS (like
# OTHER) never reaches live_pipeline.EVENT_CLASSIFICATIONS. What must never
# happen is one of these picking up SOCIAL/SOCIAL_WITH_CLASS/MILONGA and
# becoming a candidate -- that's the invariant these two actually pin.

def test_golf_swing_lesson_never_becomes_a_candidate():
    assert classify(
        "골프 스윙 교정 레슨 모집",
        "임팩트 구간 스윙 궤도를 교정하는 8주 프로그램입니다. 회당 5만원",
    ) not in EVENT_CLASSIFICATIONS


def test_stock_swing_trading_course_never_becomes_a_candidate():
    assert classify(
        "주식 스윙매매 실전반 모집",
        "단기 스윙 트레이딩 전략을 다루는 온라인 강의입니다. 환불 규정 안내",
    ) not in EVENT_CLASSIFICATIONS


def test_a_swing_door_or_hinge_post_is_not_an_event():
    assert classify(
        "현관문 스윙도어 경첩 교체 후기",
        "자유형 스윙 힌지로 교체했더니 여닫이가 훨씬 부드러워졌습니다",
    ) == "OTHER"


def test_a_playground_swing_ride_is_not_an_event():
    assert classify(
        "놀이터 그네(스윙) 안전점검 공지",
        "노후된 스윙 놀이기구 체인과 좌석을 전면 교체합니다",
    ) == "OTHER"


# --- "salsa" that has nothing to do with the dance ---------------------------

def test_a_salsa_sauce_recipe_is_not_an_event():
    assert classify(
        "홈메이드 살사소스 레시피 공유",
        "토마토와 할라피뇨로 만드는 매콤한 살사 소스, 나초에 곁들이면 좋아요",
    ) == "OTHER"


# --- these same off-topic posts stay OTHER even mentioning a clock/fee ------
#
# has_class/has_social only look for the fixed word lists; a price or a time
# next to an unrelated "스윙"/"살사" is still not lesson/social vocabulary,
# so it should not tip these into CLASS or SOCIAL either.

def test_a_golf_swing_clinic_with_a_price_is_still_not_an_event():
    assert classify(
        "골프 스윙 클리닉 안내",
        "10월 5일 오후 2시, 참가비 30,000원, 스윙 분석 장비로 진단해 드립니다",
    ) == "OTHER"


# --- v0.91.0 PHASE 5: more senses of "swing" that are not the dance ---------

def test_a_swing_jacket_listing_is_not_an_event():
    """1940s-style clothing, not a dance floor."""
    assert classify(
        "빈티지 스윙 재킷 판매합니다",
        "체크무늬 울 소재 스윙 재킷, 55사이즈, 상태 좋음 8만원",
    ) == "OTHER"


def test_a_rope_swing_post_is_not_an_event():
    assert classify(
        "계곡 로프 스윙 명당 추천",
        "여름에 뛰어들기 좋은 로프 스윙 포인트 세 곳을 소개합니다",
    ) == "OTHER"


def test_the_bare_word_swing_alone_never_becomes_a_candidate():
    """A page that says only "스윙", with none of classify()'s own class/
    social/milonga words anywhere, must stay OTHER - the word alone is not
    evidence of an announced event of any kind."""
    classification = classify("스윙", "스윙")
    assert classification == "OTHER"
    assert classification not in EVENT_CLASSIFICATIONS
