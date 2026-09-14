"""v0.89.2 Community Discovery Classification Precision Patch: context-aware
genre detection and entity-kind refinement (Section 3-5, 9-12).

Three Production discovery/verification passes found the same shape of
false positive over and over: a genre keyword that pattern-matches for a
reason that has nothing to do with dance (stock-market "swing", a food
"salsa", a cross-branded "mango tango" ice cream flavour, a poem that merely
name-drops tango's music history), and an event/information aggregator
(Dancehive) that is dance-related without being a community. This file locks
in the fix with the exact real patterns those reviews found - always a
synthetic fixture (see the module docstrings on
detect_genres/genre_negative_context/detect_kind in
runtime/community_discovery.py), never a real Naver/Kakao API call and never
a write to a real Production row.
"""

from __future__ import annotations

import pytest

from runtime import community_discovery as cd

ALL_GENRES = {code: n for n, code in enumerate(cd.TARGET_GENRES, start=1)}


def ctx_for(**overrides):
    base = dict(today=None, genre_ids=dict(ALL_GENRES), regions=[], region_names={},
                venues=[], venue_names={}, communities=[])
    base.update(overrides)
    return cd.Context(**base)


# === Section 3A/5, Case 2: SWING - stock/financial context ====================================

@pytest.mark.parametrize("text", [
    "SwingLog|스윙트레이딩 기록 분석 연구소. 스윙매매의 판단, 진입 전 체크리스트. "
    "#SwingLog #스윙로그 #스윙매매 #주식공부 #매매일지",
    "815머니톡: 스윙, 소부장 등 투자 성향과 관심 종목을 공유하는 카페입니다.",
])
def test_swing_stock_trading_context_is_not_a_dance_genre(text):
    """Case 2 (Section 17): SwingLog, a stock-swing-trading cafe - Production
    candidate #434/#433."""
    assert "SWING" not in cd.detect_genres(text, ALL_GENRES)
    assert "SWING" in cd.genre_negative_context(text, ALL_GENRES)


# === Section 3B: SWING - clothing / interior / amusement-ride general noun ====================

@pytest.mark.parametrize("text", [
    "스윙자켓 코디 추천, 이번 시즌 데님 스윙 자켓 룩북이에요",
    "거실 중문 스윙도어 시공 후기, 통유리 180도 스윙 도어 설치했습니다",
    "자이언트 스윙 놀이기구 타고 왔어요, 롤러코스터도 재밌었어요",
])
def test_swing_as_clothing_door_or_a_ride_is_not_a_dance_genre(text):
    assert "SWING" not in cd.detect_genres(text, ALL_GENRES)


def test_real_swing_dance_community_keeps_its_genre():
    """Case 4 (Section 17): a genuine swing dance meetup keeps SWING even
    though it uses the exact word ('스윙') a false positive also uses."""
    text = "이번 주 스윙댄스 정모 공지입니다. 발보아 워크샵도 함께 진행해요."
    genres = cd.detect_genres(text, ALL_GENRES)
    assert genres.get("SWING") and genres.get("BALBOA")
    assert not cd.genre_negative_context(text, ALL_GENRES)


# === Section 3C/5, Case 3: SALSA - food context ================================================

@pytest.mark.parametrize("text", [
    "살사소스 만드는 법: 토마토, 칠리, 라임을 넣고 만드는 홈메이드 살사소스 레시피",
    "GS25 편의점 닥터유 단백질칩 칠리살사맛 추천! 칠리살사맛으로 입문했어요",
])
def test_salsa_food_context_is_not_a_dance_genre(text):
    """Case 3 (Section 17): "살사소스 만드는 법" - a recipe, not a community."""
    assert "SALSA" not in cd.detect_genres(text, ALL_GENRES)
    assert "SALSA" in cd.genre_negative_context(text, ALL_GENRES)


def test_a_stray_food_word_never_erases_an_otherwise_real_salsa_genre():
    """Case 5 (Section 17): a food-context word appearing elsewhere in an
    otherwise genuine Salsa community post must never remove SALSA - the
    negative context has to be local/evidence-aware, not a whole-document
    veto."""
    text = "살사 동호회 정모 공지입니다. 이번 뒤풀이에 살사소스 제공됩니다!"
    genres = cd.detect_genres(text, ALL_GENRES)
    assert genres.get("SALSA") == "살사"
    assert "SALSA" not in cd.genre_negative_context(text, ALL_GENRES)


# === Section 3D/5: TANGO - unrelated/cultural/product context =================================

def test_tango_as_an_ice_cream_flavour_is_not_a_dance_genre():
    text = "배스킨라빈스 매장에서 가장 좋아하는 아이스크림, 상큼한 망고탱고 밀키소다"
    assert "TANGO" not in cd.detect_genres(text, ALL_GENRES)


def test_tango_in_a_poem_or_music_history_mention_is_not_a_dance_genre():
    """Section 24: "tango unrelated cultural mention" - a personal/poetry
    cafe discussing tango's music history, not a tango community (Production
    candidate #441)."""
    text = ("정통 라플라타 탱고 리듬을 담은 곡. 4월 19일, 몬테비데오의 작은 카페에서 첫 울림을 "
            "시작한 이 곡의 가사와 앨범 이야기, 시인이 남긴 시집 속 한 구절")
    assert "TANGO" not in cd.detect_genres(text, ALL_GENRES)


def test_a_bare_mention_of_music_never_disqualifies_a_real_tango_community():
    """Section 5's explicit caveat: a real Tango community also talks about
    music - "음악" alone must never suppress TANGO."""
    text = "홍대 아르헨티나 탱고 동호회 정모 안내: 이번 밀롱가는 음악 선곡에 신경 썼습니다"
    assert cd.detect_genres(text, ALL_GENRES).get("TANGO") == "탱고"


# === Section 12, Case 6: dance event aggregator ================================================

def test_a_dance_event_aggregator_is_not_a_community():
    """Case 6 (Section 17): Dancehive - Production candidate #430."""
    text = ("서울·부산·대구·광주·대전 등 전국 도시에서 매주 열리는 수백 개의 라틴 댄스 이벤트 - "
            "댄스하이브는 이 모든 정보를 한 곳에 모아, 입문자도 베테랑도 쉽게 행사를 찾을 수 있게")
    kind, reason = cd.detect_kind(cd.identify("https://dancehive.app/"), None, text, ctx_for())
    assert kind == cd.KIND_AGGREGATOR
    assert kind in cd.NOT_COMMUNITY_KINDS
    assert reason


def test_an_aggregator_word_never_overrides_a_real_community_word():
    text = "우리 동호회는 회원들의 정보를 모아 매달 정모를 진행합니다"
    kind, _ = cd.detect_kind(cd.identify("https://example-community.example/"), None, text, ctx_for())
    assert kind == cd.KIND_COMMUNITY


# === Section 11, 24: Community + academy ambiguous case ========================================

def test_an_academy_name_with_no_separate_community_evidence_is_an_academy():
    """Modelled on Production candidate #414 (탱고코리아 탱고집중코스): an
    academy-branded intensive-course name with only instructor/enrollment
    language - no independent community evidence."""
    kind, _ = cd.detect_kind(cd.identify("https://cafe.daum.net/ac2"), "탱고 인텐시브 아카데미",
                             "20년 강습경력, 수강생 모집합니다", ctx_for())
    assert kind == cd.KIND_ACADEMY


def test_an_academy_name_with_real_community_evidence_is_a_community():
    """Section 11: "Academy가 Community도 운영할 수 있으므로 무조건 reject하지는
    않는다" - an academy-style name still counts as a community once real,
    separate community evidence (a community word AND an activity word) is
    also present."""
    kind, reason = cd.detect_kind(
        cd.identify("https://cafe.daum.net/ac3"), "살사 아카데미 동호회",
        "매달 정모를 진행하는 회원 동호회입니다. 이번 달 정모 공지드립니다", ctx_for())
    assert kind == cd.KIND_COMMUNITY
    assert "academy" in reason


def test_a_venue_name_is_still_a_venue_regardless_of_genre_context():
    """Regression: v0.89.2's changes to detect_kind must not disturb the
    v0.89.0 venue/instructor/event checks that already worked."""
    kind, _ = cd.detect_kind(cd.identify("https://cafe.daum.net/bar1"), "홍대 살사바", "살사 소셜",
                             ctx_for())
    assert kind == cd.KIND_VENUE
