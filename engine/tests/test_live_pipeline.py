import pytest

from src.collectors.base import RawPostRecord
from src.live_pipeline import process_discovered_post

class Dummy: pass

def test_metadata_only_never_self_verifies():
    post=RawPostRecord(
        source_id="SRC-D-001", platform="DAUM_CAFE", source_url="https://example.invalid/1",
        title="8/22 더 피스타 밀롱가", body="19:00-23:00 입장료 13,000원 PISTA",
        published_at="2026-08-18", acquisition_quality="METADATA_ONLY")
    r=process_discovered_post(Dummy(),post,"SECONDARY")
    assert r["events"][0].core_complete is True
    assert r["events"][0].status=="POSSIBLE"


# --- v0.82.5: Pohang/Daegu candidate=0 gap ----------------------------------
#
# Found live: miltang_discovery.discover() tags every `/milongas` record with
# known_event_type="MILONGA" (its own list-page structure already guarantees
# the type - see miltang_discovery.py's own comment at the tagging site).
# Real Pohang/Daegu posts under a brand name with no "milonga"/"밀롱가" word
# anywhere used to classify as OTHER and produce zero candidates; these
# fixtures reproduce parse_detail()'s own real body shape (`"YYYY년 M월 D일"`
# leading the body, exactly as _format_date_kr() renders it, followed by a
# Miltang-rendered bilingual venue name plus its real street address as a
# second parenthetical group - v0.82.1 + v0.82.5's _cut_at_boundary() fix).

def _miltang_post(title, body, source_url):
    return RawPostRecord(
        source_id="SRC-W-005", platform="WEB", source_url=source_url,
        title=title, body=body, published_at=None,
        acquisition_quality="FETCHED_FULL", known_event_type="MILONGA",
    )


POHANG = _miltang_post(
    "바모스",
    "2026년 9월 11일 시간: 20:30~23:30 장소: PosTango (포스탱고) "
    "(포항시 남구 중앙로 83, 3층) 반복: 매주 금요일",
    "https://miltang.com/milongas/636",
)
DAEGU = _miltang_post(
    "디디디",
    "2026년 9월 9일 장소: Tango Cafe Dia (탱고 카페 디아) "
    "(대구 북구 침산로 168 5층 507호) 주최: DoyaDoya 반복: 매주 수요일",
    "https://miltang.com/milongas/349",
)


def test_pohang_candidate_is_created():
    r = process_discovered_post(Dummy(), POHANG, "SECONDARY")
    assert r["classification"] == "MILONGA"
    assert len(r["events"]) == 1


def test_daegu_candidate_is_created():
    r = process_discovered_post(Dummy(), DAEGU, "SECONDARY")
    assert r["classification"] == "MILONGA"
    assert len(r["events"]) == 1


def test_pohang_date_and_time_are_correct():
    ev = process_discovered_post(Dummy(), POHANG, "SECONDARY")["events"][0]
    assert ev.date == "2026-09-11"
    assert (ev.start_time, ev.end_time) == ("20:30", "23:30")


def test_daegu_date_is_correct_and_no_time_is_invented():
    ev = process_discovered_post(Dummy(), DAEGU, "SECONDARY")["events"][0]
    assert ev.date == "2026-09-09"
    assert ev.start_time is None and ev.end_time is None


def test_pohang_venue_keeps_its_real_address():
    ev = process_discovered_post(Dummy(), POHANG, "SECONDARY")["events"][0]
    assert ev.venue == "PosTango (포스탱고) (포항시 남구 중앙로 83, 3층)"
    assert "포항" in ev.venue


def test_daegu_venue_keeps_its_real_address():
    ev = process_discovered_post(Dummy(), DAEGU, "SECONDARY")["events"][0]
    assert ev.venue == "Tango Cafe Dia (탱고 카페 디아) (대구 북구 침산로 168 5층 507호)"
    assert "대구" in ev.venue


def test_a_miltang_milonga_is_never_verified_from_discovery_alone():
    """Miltang stays SECONDARY/DIRECTORY (Section: False VERIFIED = 0) - the
    hint changes only which classification a brand name resolves to, never
    the evidence gate that decides POSSIBLE vs VERIFIED."""
    for post in (POHANG, DAEGU):
        ev = process_discovered_post(Dummy(), post, "SECONDARY")["events"][0]
        assert ev.status != "VERIFIED"


# --- control group: an explicit "milonga" post is unaffected ----------------
#
# Cheongju/Jinju/Changwon's real posts already contain "milonga"/"밀롱가"
# literally, which is why they produced candidates before this release. These
# fixtures stand in for that shape with known_event_type left at its default
# (None) - the keyword-guessing path this release does not touch.

@pytest.mark.parametrize("city,venue", [
    ("청주", "PISTA"), ("진주", "라 밀롱가"), ("창원", "Tango House"),
])
def test_a_city_with_the_word_milonga_already_in_it_is_unchanged(city, venue):
    post = RawPostRecord(
        source_id="SRC-W-005", platform="WEB",
        source_url="https://example.invalid/control",
        title=f"{city} 밀롱가 안내",
        body=f"2026년 9월 12일 시간: 20:00~24:00 장소: {venue} ({city}시)",
        published_at=None, acquisition_quality="FETCHED_FULL",
    )
    r = process_discovered_post(Dummy(), post, "SECONDARY")
    assert r["classification"] == "MILONGA"
    assert city in r["events"][0].venue


# --- safety properties compose correctly with the hint ----------------------

def test_known_event_type_does_not_disable_multi_event_context_safety():
    """v0.81.2's Event Context Safety must hold even when the post also
    carries known_event_type - the hint only changes what classify() returns,
    never how extract_with_image_fallback() segments multiple programs."""
    post = RawPostRecord(
        source_id="SRC-W-005", platform="WEB",
        source_url="https://example.invalid/context",
        title="더블 밀롱가 데이",
        body=(
            "1) 9/5(토) 낮밀롱가 15:00-18:00 장소: A홀 입장료 10,000원 "
            "2) 9/5(토) 밤밀롱가 20:00-24:00 장소: B홀 입장료 15,000원"
        ),
        published_at="2026-09-01", acquisition_quality="FETCHED_FULL",
        known_event_type="MILONGA",
    )
    ev = process_discovered_post(Dummy(), post, "SECONDARY")["events"][0]
    assert ev.venue in ("A홀", "B홀")
    fee_evidence = [e for e in ev.evidences if e.field == "fee"]
    if ev.venue == "A홀":
        assert ev.fee != 15000
    else:
        assert ev.fee != 10000


def test_known_event_type_does_not_disable_old_post_year_safety():
    """v0.80.2's Date Safety must hold even with the hint set - a bare date
    still resolves against the post's own published year, not the current
    one, exactly as _norm_date() already guarantees."""
    post = RawPostRecord(
        source_id="SRC-W-005", platform="WEB",
        source_url="https://example.invalid/stale",
        title="가을 밀롱가",
        body="9/25 장소: PISTA",
        published_at="2024-09-20", acquisition_quality="FETCHED_FULL",
        known_event_type="MILONGA",
    )
    ev = process_discovered_post(Dummy(), post, "SECONDARY")["events"][0]
    assert ev.date == "2024-09-25"
    assert ev.date != "2026-09-25"


# --- class-only / performance-only stay excluded without the hint ----------
#
# discover() only sets known_event_type for `/milongas` records (see its own
# comment) - `/notices` posts (festival announcements, closures, general
# notices) are deliberately left unset and keep being read by their own text,
# exactly as test_social_dance.py's own
# test_a_lesson_that_names_a_milonga_is_still_a_lesson already pins.

def test_a_class_only_notice_without_the_hint_stays_excluded():
    post = RawPostRecord(
        source_id="SRC-W-005", platform="WEB",
        source_url="https://miltang.com/notices/1",
        title="밀롱가 강습 안내", body="8주 강습 모집",
        published_at=None, acquisition_quality="FETCHED_FULL",
    )
    r = process_discovered_post(Dummy(), post, "SECONDARY")
    assert r["classification"] == "CLASS"
    assert r["events"] == []


def test_a_performance_only_notice_without_the_hint_stays_excluded():
    post = RawPostRecord(
        source_id="SRC-W-005", platform="WEB",
        source_url="https://miltang.com/notices/2",
        title="공연 안내", body="이번 주 공연 일정을 안내드립니다",
        published_at=None, acquisition_quality="FETCHED_FULL",
    )
    r = process_discovered_post(Dummy(), post, "SECONDARY")
    assert r["classification"] == "OTHER"
    assert r["events"] == []
