"""Deep content acquisition: representations, extraction, redaction, retry.

The behaviour these pin down was learned from the live board. Daum serves the
desktop article URL as an iframe shell — 168 characters of CSS — while the
mobile host serves the real post. Getting that wrong is the difference between
"we fetched the body" and "we fetched a page that contains no body", and only
one of those may be reported as FETCHED_FULL.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest

from runtime import acquisition

DAUM_URL = "https://cafe.daum.net/latindance/5HTC/22276"

# Shaped like the real mobile page: chrome, the font-size control, the article,
# then the search footer.
MOBILE_PAGE = """<html><head>
<meta property="og:title" content="9/5 THE PISTA MILONGA">
<meta property="og:description" content="9/5 THE PISTA MILONGA 입장료 13,000원">
</head><body>
<nav>CAFE 외부홍보게시판 앱으로보기</nav>
작성자 바니 | 작성시간 26.09.02 | 조회수 28 목록 댓글 0
글자크기 작게 가 글자크기 크게 가
9/5(토) THE PISTA MILONGA | 더 피스타 밀롱가. 매주 토요일 밤 홍대 PISTA에서 열리는 밀롱가.
DJ Epitone. 입장료 13,000원. 심야 밀롱가 패키지 23:30 - 04:30 사전결제 20,000원.
장소 홍대 PISTA 서울 마포구 월드컵북로6길 49 B1. 문의 바니 010-2803-3959.
<img src="/poster.jpg">
다음검색 현재 게시글 추가 기능 열기 북마크 공유하기 신고
</body></html>"""

# The desktop shell: an iframe and some CSS, no article at all.
DESKTOP_SHELL = """<html><head><title>Daum 카페</title></head><body>
<style>html, body, iframe { margin: 0; padding: 0; height: 100%; }</style>
<iframe id="down" src="/_c21_/home"></iframe></body></html>"""

# Shaped like a K-TANGO board post: site nav chrome, then readTop/readEdit/
# readBottom - the template several small Korean community boards share.
# readEdit is real article HTML (<p>/<b>/<br> tags), not the plain text a
# marker search would need; readBottom is prev/next navigation that must not
# leak into the body.
TEMPLATE_BOARD_URL = "http://www.k-tango.net/cnf/festival02/read.jsp?reqPageNo=1&no=10"
TEMPLATE_BOARD_PAGE = """<html><head><title>K-TANGO</title></head><body>
<header><nav>K-TANGO 소개 PROGRAM GALLERY NOTICE 로그인</nav></header>
<div class="board_con"><div class="inner"><div class="sub_tit"><h3>페스티벌 안내</h3></div></div></div>
<div class="programCon"><div class="programRead">
<div class="readTop">
<p class="imgTitle">2024 K-TANGO SF : 신청폼</p>
<p class="imgTitle_sub">K-TANGO 2024-09-01 16:06</p>
</div>
<div class="readEdit">
<p>일시 : 2024년 09월 26일 목요일 PM 19:00 ~ PM20:30</p>
<p>장소 : 연세대학교 대강당</p>
<p>참가비 : 20,000원</p>
<p>내용 : 해외탱고아티스트, 국내 탱고가수, 전통무용수들의 공연입니다. 100,000원 상당 공연티켓을 선착순 500명 무료배포합니다.</p>
<p>많은 신청 바랍니다. 문의는 홈페이지 공지사항을 참고해 주세요.</p>
</div>
<div class="readBottom"><table>
<tr><th>이전글</th><td><a href="read.jsp?reqPageNo=1&no=12">2025 K-TANGO CF</a></td></tr>
<tr><th>다음글</th><td><a href="read.jsp?reqPageNo=1&no=11">2024 K-TANGO SF : 서울밀롱가데이</a></td></tr>
</table></div>
</div></div>
<footer>K-TANGO CF 조직위원회 (주)KSACN TEL. 02-571-0108</footer>
</body></html>"""


class _Response(io.BytesIO):
    def __init__(self, body: str, *, status=200, url=DAUM_URL, content_type="text/html;charset=UTF-8"):
        super().__init__(body.encode("utf-8"))
        self.status = status
        self._url = url
        self.headers = _Headers(content_type)

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


class _Headers:
    def __init__(self, content_type: str):
        self._content_type = content_type

    def get(self, key, default=""):
        return self._content_type if key.lower() == "content-type" else default

    def get_content_charset(self):
        return "utf-8"


@pytest.fixture(autouse=True)
def allow_robots(monkeypatch):
    monkeypatch.setattr(acquisition, "robots_allows", lambda *a, **k: True)


# --- representations --------------------------------------------------------

def test_daum_desktop_urls_try_the_mobile_host_first():
    """The desktop page is an iframe shell; the article is on m.cafe.daum.net."""
    options = acquisition.representations(DAUM_URL)
    assert options[0].url == "https://m.cafe.daum.net/latindance/5HTC/22276"
    assert "iframe shell" in options[0].reason
    assert options[-1].url == DAUM_URL


def test_other_hosts_are_fetched_as_discovered():
    url = "https://example.invalid/post/1"
    assert [r.url for r in acquisition.representations(url)] == [url]


# --- extraction -------------------------------------------------------------

def test_the_article_region_is_preferred_over_og_description():
    """Measured live: article region 434 chars, og:description 190 (truncated)."""
    text, method = acquisition.extract_article(MOBILE_PAGE)
    assert method == acquisition.METHOD_ARTICLE_REGION
    assert "THE PISTA MILONGA" in text
    assert "앱으로보기" not in text, "navigation chrome must not be in the article"
    assert "북마크" not in text, "footer chrome must not be in the article"


def test_og_description_is_the_fallback_when_there_is_no_article_region():
    page = """<html><head>
    <meta property="og:description" content="9/5 밀롱가 입장료 13,000원 장소 홍대"></head>
    <body><nav>chrome</nav></body></html>"""
    text, method = acquisition.extract_article(page)
    assert method == acquisition.METHOD_OG_DESCRIPTION
    assert "13,000원" in text


def test_a_shell_page_yields_nothing_useful():
    text, method = acquisition.extract_article(DESKTOP_SHELL)
    assert len(text) < acquisition.FULL_TEXT_THRESHOLD
    assert method in (acquisition.METHOD_VISIBLE_TEXT, acquisition.METHOD_NONE)


def test_title_and_images_are_extracted():
    assert acquisition.extract_title(MOBILE_PAGE) == "9/5 THE PISTA MILONGA"
    images = acquisition.extract_images(MOBILE_PAGE, "https://m.cafe.daum.net/x/y/1")
    assert images == ["https://m.cafe.daum.net/poster.jpg"]


def test_a_template_board_post_is_read_from_its_readEdit_div():
    """K-TANGO and boards on the same template: the article is a real element,
    not a text marker, and is preferred over the whole-page fallback."""
    text, method = acquisition.extract_article(TEMPLATE_BOARD_PAGE)
    assert method == acquisition.METHOD_TEMPLATE_BOARD
    assert "연세대학교 대강당" in text
    assert "20,000원" in text
    assert "로그인" not in text, "header nav must not be in the article"
    assert "이전글" not in text, "prev/next footer must not be in the article"
    assert "조직위원회" not in text, "page footer must not be in the article"


# Shaped like danceinfo.net's own lesson/event detail page: nav chrome, then
# a structured 행사일/일정정보/장소/DJ block, a free-text description, and a
# trailing "다가오는 추천 행사" block naming other events' own dates - the real
# page's shape, not a captured copy of it.
DANCEINFO_PAGE = """<html><head>
<meta property="og:description" content="파티안내 · 2026-09-12 · 탱고 · 분당 실루엣 · 파티안내 일곱 해의…">
</head><body>
<nav>댄스인포 필터 강습/행사 장소 모임 인물</nav>
<p>파티안내 - 탱고 파티(페스티발) · 경기남부</p>
행사일 2026년 9월 12일 (토) 일정정보 5:30~9:30 장소 분당 실루엣 카카오맵 DJ DJ 네로
강의 소개
파티안내 Pm5:30~9:30 예매15,000/현매20,000
다가오는 추천 행사
9월 5일 토요일 오후 3시 다른 행사 안내
<footer>이용약관 개인정보처리방침</footer>
</body></html>"""


def test_a_danceinfo_post_is_read_between_its_own_markers():
    """danceinfo.net (v0.82): the structured 행사일/장소/DJ block and the free
    text both matter (venue/DJ labels only appear in the structured block),
    but the trailing "다가오는 추천 행사" block - other events' own dates -
    must not leak in, or a later date-segmentation pass could pick it up as
    if it were part of this event."""
    text, method = acquisition.extract_article(DANCEINFO_PAGE)
    assert method == acquisition.METHOD_DANCEINFO
    assert "분당 실루엣" in text
    assert "예매15,000" in text
    assert "필터 강습" not in text, "top nav must not be in the article"
    assert "다른 행사 안내" not in text, "the recommended-events block must not be in the article"
    assert "이용약관" not in text, "page footer must not be in the article"


# --- personal data ----------------------------------------------------------

def test_phone_numbers_are_removed_before_storage():
    text, count = acquisition.redact_personal_data("문의 바니 010-2803-3959 로 연락")
    assert "010-2803-3959" not in text
    assert "[전화번호]" in text
    assert count == 1


def test_bank_accounts_are_removed():
    text, count = acquisition.redact_personal_data("계좌: 하나은행 10291052767107 백은정")
    assert "10291052767107" not in text
    assert count == 1


def test_emails_are_removed():
    text, _ = acquisition.redact_personal_data("문의 organiser@example.invalid")
    assert "organiser@example.invalid" not in text


@pytest.mark.parametrize("fee", ["13,000원", "20,000원", "3,000원", "입장료 13,000원"])
def test_fees_survive_redaction(fee):
    """The whole point of acquisition is fees and times - they must not be eaten."""
    text, _ = acquisition.redact_personal_data(f"입장료 {fee} 입니다")
    assert fee in text


def test_times_survive_redaction():
    text, _ = acquisition.redact_personal_data("심야 패키지 23:30 - 04:30, 시작 20:00")
    assert "23:30" in text and "04:30" in text and "20:00" in text


# --- fetching ---------------------------------------------------------------

def _opener(pages: dict[str, _Response] | list):
    calls: list[str] = []

    def open_url(request, timeout=None):
        url = request.full_url
        calls.append(url)
        if isinstance(pages, dict):
            if url not in pages:
                raise AssertionError(f"unexpected fetch: {url}")
            body = pages[url]
        else:
            body = pages.pop(0)
        return body() if callable(body) else body

    open_url.calls = calls
    return open_url


def test_a_full_article_is_reported_as_fetched_full():
    opener = _opener({"https://m.cafe.daum.net/latindance/5HTC/22276": _Response(MOBILE_PAGE)})
    outcome = acquisition.fetch(DAUM_URL, opener=opener)
    assert outcome.status == acquisition.FETCHED_FULL
    assert outcome.method == acquisition.METHOD_ARTICLE_REGION
    assert outcome.content_length >= acquisition.FULL_TEXT_THRESHOLD
    assert outcome.redacted_spans >= 1, "the phone number should have been removed"
    assert outcome.content_hash


def test_a_full_template_board_page_is_reported_as_fetched_full():
    opener = _opener({TEMPLATE_BOARD_URL: _Response(TEMPLATE_BOARD_PAGE, url=TEMPLATE_BOARD_URL)})
    outcome = acquisition.fetch(TEMPLATE_BOARD_URL, opener=opener)
    assert outcome.status == acquisition.FETCHED_FULL
    assert outcome.method == acquisition.METHOD_TEMPLATE_BOARD
    assert "연세대학교" in outcome.text


def test_a_shell_only_page_is_never_reported_as_full():
    """The v0.75 failure mode: HTTP 200 with no article must not read as success."""
    pages = {
        "https://m.cafe.daum.net/latindance/5HTC/22276": lambda: _Response(DESKTOP_SHELL),
        DAUM_URL: lambda: _Response(DESKTOP_SHELL),
    }
    outcome = acquisition.fetch(DAUM_URL, opener=_opener(pages))
    assert outcome.status != acquisition.FETCHED_FULL
    assert outcome.status in (acquisition.FETCH_BLOCKED, acquisition.FETCHED_PARTIAL)
    assert outcome.error_code in ("BODY_UNAVAILABLE", "THIN_BODY")


def test_a_thin_body_is_partial_not_full():
    page = ("<html><body>글자크기 크게 가 짧은 공지입니다. 자세한 내용은 링크 참고. 다음검색</body></html>")
    # A fresh response per call: one BytesIO cannot be read twice.
    outcome = acquisition.fetch(
        DAUM_URL, opener=_opener([lambda: _Response(page), lambda: _Response(page)])
    )
    assert outcome.status == acquisition.FETCHED_PARTIAL
    assert outcome.error_code == "THIN_BODY"


def test_the_mobile_host_is_tried_before_the_discovered_url():
    opener = _opener({"https://m.cafe.daum.net/latindance/5HTC/22276": _Response(MOBILE_PAGE)})
    acquisition.fetch(DAUM_URL, opener=opener)
    assert opener.calls[0].startswith("https://m.cafe.daum.net/")


def test_a_login_wall_is_reported_as_login_required():
    import urllib.error

    def opener(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

    outcome = acquisition.fetch(DAUM_URL, opener=opener)
    assert outcome.status == acquisition.LOGIN_REQUIRED
    assert outcome.http_status == 403


def test_a_missing_page_is_blocked_not_failed():
    import urllib.error

    def opener(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    outcome = acquisition.fetch(DAUM_URL, opener=opener)
    assert outcome.status == acquisition.FETCH_BLOCKED
    assert outcome.error_code == "NOT_FOUND"


def test_a_network_error_is_a_failure_not_a_block():
    def opener(request, timeout=None):
        raise TimeoutError("timed out")

    outcome = acquisition.fetch(DAUM_URL, opener=opener)
    assert outcome.status == acquisition.FETCH_FAILED
    assert outcome.error_code == "NETWORK"


def test_non_html_is_unsupported():
    def pdf():
        return _Response("%PDF-1.4 binary", content_type="application/pdf")

    outcome = acquisition.fetch(DAUM_URL, opener=_opener([pdf, pdf]))
    assert outcome.status == acquisition.UNSUPPORTED


def test_robots_disallow_stops_the_fetch(monkeypatch):
    monkeypatch.setattr(acquisition, "robots_allows", lambda *a, **k: False)

    def opener(request, timeout=None):
        raise AssertionError("must not fetch a disallowed URL")

    outcome = acquisition.fetch(DAUM_URL, opener=opener)
    assert outcome.status == acquisition.FETCH_BLOCKED
    assert outcome.error_code == "ROBOTS_DISALLOWED"


def test_korean_text_survives_the_fetch():
    opener = _opener({"https://m.cafe.daum.net/latindance/5HTC/22276": _Response(MOBILE_PAGE)})
    outcome = acquisition.fetch(DAUM_URL, opener=opener)
    assert "밀롱가" in outcome.text
    assert not any(0xD800 <= ord(c) <= 0xDFFF for c in outcome.text)


# --- content hashing and retry ---------------------------------------------

def test_identical_text_hashes_identically():
    assert acquisition.content_hash("같은 본문") == acquisition.content_hash("같은 본문")
    assert acquisition.content_hash("본문 A") != acquisition.content_hash("본문 B")


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def test_a_settled_status_is_never_retried():
    for status in (acquisition.FETCHED_FULL, acquisition.FETCHED_PARTIAL,
                   acquisition.LOGIN_REQUIRED, acquisition.UNSUPPORTED):
        assert acquisition.next_attempt_at(status, None, 1, now=NOW) is None


def test_a_network_failure_retries_soon():
    # jitter=False for the exact policy. The spread itself is tested in
    # tests/test_blocked_retry.py, where it is the subject rather than noise.
    when = acquisition.next_attempt_at(
        acquisition.FETCH_FAILED, "NETWORK", 1, now=NOW, jitter=False)
    assert when == NOW + timedelta(minutes=15)


def test_a_blocked_page_waits_a_day_rather_than_being_hammered():
    when = acquisition.next_attempt_at(
        acquisition.FETCH_BLOCKED, "BLOCKED", 1, now=NOW, jitter=False)
    assert when == NOW + timedelta(days=1)


def test_a_blocked_page_is_asked_again_at_all():
    """It used to be in neither the settled set nor the retryable one, so the
    wait above was a promise nothing ever kept."""
    assert acquisition.FETCH_BLOCKED in acquisition.RETRYABLE


def test_retries_stop_after_the_attempt_limit():
    """A URL that never works must not be attacked on every scheduler tick."""
    assert acquisition.next_attempt_at(
        acquisition.FETCH_FAILED, "NETWORK", acquisition.MAX_ATTEMPTS["NETWORK"], now=NOW
    ) is None
    assert acquisition.next_attempt_at(
        acquisition.FETCH_BLOCKED, "NOT_FOUND", acquisition.MAX_ATTEMPTS["NOT_FOUND"], now=NOW
    ) is None


def test_a_not_found_page_is_retried_at_most_twice():
    assert acquisition.MAX_ATTEMPTS["NOT_FOUND"] <= 2


def test_there_is_a_delay_between_requests_to_the_same_site():
    assert acquisition.MIN_DELAY_SECONDS >= 1
