from datetime import date

import pytest

from runtime import collectors, daum_board_discovery
from runtime.web_discovery import DiscoveryError

LIST = "https://cafe.daum.net/_c21_/bbs_list?grpid=w40N&fldid=MANg"
CAFE = "https://cafe.daum.net/AmigoS"
HTML = r"""
<div id="app"></div><script>
articles.push({dataid: '132', grpid: 'w40N', fldid: 'MANg',
 title: '\uC0B4\uC0AC 9\/16\uC815\uBAA8', created: '26.09.14'});
articles.push({dataid: '132', grpid: 'w40N', fldid: 'MANg',
 title: '\uC0B4\uC0AC 9\/16\uC815\uBAA8', created: '26.09.14'});
articles.push({dataid: '98', grpid: 'w40N', fldid: 'MANg',
 title: 'old', created: '25.01.01'});
notices.push({dataid: '2', grpid: 'w40N', fldid: 'MANg',
 title: 'pinned', created: '24.01.01'});
</script>
"""


def test_public_ssr_board_article_is_bounded_and_stable():
    posts = daum_board_discovery.parse_list(
        HTML, LIST, cafe_url=CAFE, today=date(2026, 9, 16), community_id=34
    )
    assert len(posts) == 1
    post = posts[0]
    assert post["title"] == "살사 9/16정모"
    assert post["source_url"] == "https://cafe.daum.net/AmigoS/MANg/132"
    assert post["published_at"] == "2026-09-14T00:00:00+09:00"
    assert post["known_event_type"] == "SOCIAL"
    assert post["community_id"] == 34
    assert post["external_article_id"] == "w40N:MANg:132"
    assert post["external_promotion"] is False


def test_explicit_third_party_promotion_does_not_inherit_host_region():
    raw = HTML.replace(r"\uC0B4\uC0AC 9\/16\uC815\uBAA8",
                       "타동호회 홍보합니다 9/16 살사 파티")
    post = daum_board_discovery.parse_list(
        raw, LIST, cafe_url=CAFE, today=date(2026, 9, 16),
        board_type="EVENT_PRIMARY", community_id=34,
    )[0]
    assert post["external_promotion"] is True
    assert post["community_id"] == 34  # provenance, not an organizer claim
    assert "organizer" not in post


def test_opt_in_class_board_does_not_call_every_post_social():
    raw = HTML.replace(r"\uC0B4\uC0AC 9\/16\uC815\uBAA8", "10/3 살사 개강")
    post = daum_board_discovery.parse_list(
        raw, LIST, cafe_url=CAFE, today=date(2026, 9, 16),
        board_type="CLASS_PRIMARY"
    )[0]
    assert post["known_event_type"] == "CLASS"
    assert post["class_event_opt_in"] is True


def test_missing_ssr_rows_and_invalid_url_fail_closed():
    with pytest.raises(DiscoveryError):
        daum_board_discovery.parse_list("<div id='app'></div>", LIST, cafe_url=CAFE)
    with pytest.raises(DiscoveryError):
        daum_board_discovery.parse_list(HTML, LIST, cafe_url="https://example.com")


def test_bachata_only_row_on_mixed_salsa_board_is_not_salsa():
    raw = HTML.replace(r"\uC0B4\uC0AC 9\/16\uC815\uBAA8", "9/16 Bachata class")
    assert daum_board_discovery.parse_list(
        raw, LIST, cafe_url=CAFE, today=date(2026, 9, 16), genre_code="SALSA"
    ) == []


def test_daum_board_uses_public_list_without_api_credentials(monkeypatch):
    monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)
    source = {"platform": "DAUM_CAFE", "url": CAFE,
              "config": {"parser": "daum_cafe_board", "board_urls": [LIST]}}
    assert collectors.describe_capability("DAUM_CAFE", source)["live"] is True
    assert collectors.content_mode(source) == collectors.CONTENT_MODE_DETAIL_FETCH
    assert collectors.describe_capability("DAUM_CAFE")["live"] is False
    from scheduler.intake_job import choose_mode
    assert choose_mode(source)[0] == collectors.MODE_LIVE
    source["url"] = LIST
    source["config"]["cafe_url"] = CAFE
    assert collectors.describe_capability("DAUM_CAFE", source)["live"] is True


def test_dated_class_board_enters_existing_event_candidate_pipeline():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
    from src.collectors.base import RawPostRecord
    from src.live_pipeline import process_discovered_post

    post = RawPostRecord(
        source_id="TEST", platform="DAUM_CAFE", source_url="https://example.com/1",
        title="10/3 살사 개강", body="수업 장소: 홍대 인근 연습실",
        published_at="2026-09-09T00:00:00+09:00", class_event_opt_in=True,
    )
    result = process_discovered_post(None, post)
    assert result["classification"] == "CLASS"
    assert len(result["events"]) == 1
    assert result["events"][0].date == "2026-10-03"
    post.class_event_opt_in = False
    assert process_discovered_post(None, post)["events"] == []
    post.class_event_opt_in = True
    post.title = "살사 개강 신청 마감 9/26"
    post.body = "상세 수업 일정은 추후 안내"
    assert process_discovered_post(None, post)["events"] == []


@pytest.mark.parametrize("text,expected", [
    ("26.9.18 정모", "2026-09-18"),
    ("9.20 일 파티", "2026-09-20"),
    ("이번주 토요일 정모", "2026-09-19"),
    ("다음주 금요일 정모", "2026-09-25"),
    ("이번 토요일 정모", "2026-09-19"),
    ("매주 토요일 정모", "2026-09-19"),
    ("오늘 파티", "2026-09-16"),
    ("내일 파티", "2026-09-17"),
])
def test_cafe_dates_anchor_to_post_timestamp(text, expected):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
    from src.extractor import _norm_date

    assert _norm_date(text, published=date(2026, 9, 16))[0] == expected
    if "매주" in text:
        assert _norm_date(text, published=None)[0] is None


def test_official_board_region_fallback_is_guarded_not_generic():
    from runtime import normalization

    class Cursor:
        def __init__(self):
            self.query = ""

        def execute(self, query, params):
            self.query = query
            assert params == (5,)

        def fetchone(self):
            return (123,) if all(token in self.query for token in (
                "PRIMARY_ORGANIZER", "daum_cafe_board", "EVENT_PRIMARY",
                "CLASS_PRIMARY", "source_items", "external_promotion"
            )) else None

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    class Connection:
        def cursor(self):
            return Cursor()

    assert normalization._region_id(Connection(), None) is None
    assert normalization._official_board_region_id(Connection(), None) is None
    assert normalization._official_board_region_id(Connection(), 5) == 123
