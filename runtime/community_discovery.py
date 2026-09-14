"""Community Discovery (v0.89.0).

Finds candidate Korean social-dance communities through the public search
APIs DanceMate already uses - NAVER API HUB search and Kakao Daum search,
through the Information Engine's own clients (runtime.collectors bridges to
them) - for an operator to review. It never writes to ``communities`` on its
own: a candidate becomes a Community only through the Admin review screen,
which calls the existing ``communities.create_community()`` contract.

Flow::

    queue_run (Admin) -> scheduler job 'community-discovery' -> execute_run:
        plan_queries -> provider calls (rate-limited; a failing provider is
        recorded and the others carry on) -> identify (public URL identity)
        -> aggregate per identity -> analyze (name / genres / region /
        activity / kind / venues) -> upsert one staging item per identity
        (first_seen / last_seen / seen_count) -> classify + confidence

Every judgement is deterministic text matching and is kept as a short reason
line, so an operator can see why a candidate got its label. The genre a query
was written for is a search hint only: a candidate's genres come from its own
text. Snippets are shortened and redacted (phone numbers, e-mail addresses,
account numbers, open-chat links) before they are stored.

v0.89.1 (Reliability Patch): two Production reviews found that a provider's
own search-result date can outrun what its content actually shows - a
search-index or last-modified timestamp standing in for a real post date. So
``activity_date`` now has its own ``activity_date_confidence``
(CONFIRMED/INFERRED/UNKNOWN, see ``assess_activity``) and, when the evidence
came from automation, an ``activity_evidence_*`` url/title/source an operator
can open and check before trusting it - CONFIRMED is never set by a run
itself, only by ``confirm_activity_evidence()`` after a human looks. A
POSSIBLE_DUPLICATE pair is never auto-merged and never hides its stronger
half: both candidates stay their own row (``list_duplicate_groups``), ranked
by evidence quality, not by which one happened to be found first
(``duplicate_cleared``/``mark_independent`` lets an operator say two
candidates are genuinely different organisations). A human's review_state
(APPROVED/LINKED/HELD/REJECTED) is never touched by a later run; when a held
or rejected candidate is seen again with a newer date, ``has_new_evidence``
flags it for a fresh look rather than changing anything on its own.
"""

from __future__ import annotations

import html
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Iterable, Sequence

from . import acquisition, collector_errors, collectors, communities, events_api, master_data
from .directory import DirectoryError, clean_line, parse_id, public_link

# --- vocabulary --------------------------------------------------------------------

TARGET_GENRES = ("SALSA", "SWING", "TANGO", "BALBOA", "BACHATA", "KIZOMBA")

# The default keywords per genre, inserted into community_discovery_queries by
# ensure_default_queries() for the genres that exist. An operator can switch
# any of them off or add more in the Admin screen.
DEFAULT_QUERIES: dict[str, tuple[str, ...]] = {
    "SALSA": ("살사 동호회", "살사 모임", "살사 커뮤니티", "살사 카페", "살사 초보 모임"),
    "SWING": ("스윙 동호회", "스윙댄스 동호회", "스윙 모임", "린디합 동호회", "스윙 카페"),
    "TANGO": ("탱고 동호회", "아르헨티나 탱고 동호회", "탱고 모임", "탱고 커뮤니티", "탱고 카페"),
    "BALBOA": ("발보아 동호회", "발보아 모임", "발보아 스윙", "Balboa Korea"),
    "BACHATA": ("바차타 동호회", "바차타 모임", "바차타 커뮤니티", "바차타 카페"),
    "KIZOMBA": ("키좀바 동호회", "키좀바 모임", "Kizomba Korea", "키좀바 커뮤니티"),
}

# Regions a run may be narrowed to (their master names prefix the keywords).
REGION_QUERY_CODES = ("KR-SEOUL", "KR-GYEONGGI", "KR-INCHEON", "KR-BUSAN", "KR-DAEJEON",
                      "KR-DAEGU", "KR-GWANGJU", "KR-ULSAN", "KR-JEJU")

NAVER = "NAVER"
KAKAO = "KAKAO"
PROVIDERS = (NAVER, KAKAO)
PROVIDER_LABELS = {NAVER: "Naver", KAKAO: "Kakao/Daum"}
SCOPE_ALL = "ALL"
SCOPES = (SCOPE_ALL, NAVER, KAKAO)
# The Source Master platform whose credentials each provider uses.
PROVIDER_PLATFORM = {NAVER: "NAVER_CAFE", KAKAO: "DAUM_CAFE"}

# Run status.
QUEUED = "QUEUED"
RUNNING = "RUNNING"
SUCCESS = "SUCCESS"
PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
FAILED = "FAILED"
OPEN_RUN_STATES = (QUEUED, RUNNING)

# One provider call's outcome.
CALL_SUCCESS = "SUCCESS"
CALL_NO_RESULTS = "NO_RESULTS"
ACCESS_LIMITED = "ACCESS_LIMITED"
RATE_LIMITED = "RATE_LIMITED"
CALL_ERROR = "ERROR"
STOPPING = frozenset({ACCESS_LIMITED, RATE_LIMITED})

# Candidate classification.
VERIFIED_NEW = "VERIFIED_NEW"
VERIFIED_EXISTING = "VERIFIED_EXISTING"
POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
UNVERIFIED = "UNVERIFIED"
STALE = "STALE"
INACTIVE = "INACTIVE"
NOT_A_COMMUNITY = "NOT_A_COMMUNITY"
CLASSIFICATIONS = (VERIFIED_NEW, VERIFIED_EXISTING, POSSIBLE_DUPLICATE, UNVERIFIED, STALE,
                   INACTIVE, NOT_A_COMMUNITY)
CLASSIFICATION_LABELS = {
    VERIFIED_NEW: "신규 후보", VERIFIED_EXISTING: "기존 동호회", POSSIBLE_DUPLICATE: "중복 의심",
    UNVERIFIED: "확인 필요", STALE: "오래된 자료", INACTIVE: "활동 중단", NOT_A_COMMUNITY: "동호회 아님",
}

ACTIVE = "ACTIVE"

# Activity date provenance (v0.89.1). An automated run only ever sets
# CONFIRMED never - it can set INFERRED (a real activity word and a real date
# both written in the same collected text) or UNKNOWN (no usable date). Only
# a human, through confirm_activity_evidence() after actually checking the
# page, can make it CONFIRMED.
CONFIRMED = "CONFIRMED"
INFERRED = "INFERRED"
UNKNOWN_DATE = "UNKNOWN"
ACTIVITY_DATE_CONFIDENCES = (CONFIRMED, INFERRED, UNKNOWN_DATE)

HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"

PENDING = "PENDING"
APPROVED = "APPROVED"
LINKED = "LINKED"
HELD = "HELD"
REJECTED = "REJECTED"
REVIEW_STATES = (PENDING, APPROVED, LINKED, HELD, REJECTED)
REVIEW_LABELS = {PENDING: "검토 대기", APPROVED: "등록됨", LINKED: "기존과 연결", HELD: "보류",
                 REJECTED: "제외"}
DONE_STATES = frozenset({APPROVED, LINKED})

# What a candidate is, as far as its own name and page tell.
KIND_COMMUNITY = "COMMUNITY"
KIND_VENUE = "VENUE"
KIND_ACADEMY = "ACADEMY"
KIND_INSTRUCTOR = "INSTRUCTOR"
KIND_EVENT = "EVENT"
KIND_AGGREGATOR = "AGGREGATOR"       # v0.89.2: an event/information aggregator (Section 12)
KIND_NEWS = "NEWS_OR_MEDIA"          # v0.89.3: a publisher/news page covering a community (Section 13-18)
KIND_BLOG = "BLOG"
KIND_OTHER = "OTHER"
KIND_UNKNOWN = "UNKNOWN"
NOT_COMMUNITY_KINDS = frozenset({KIND_VENUE, KIND_ACADEMY, KIND_INSTRUCTOR, KIND_EVENT,
                                 KIND_AGGREGATOR, KIND_NEWS, KIND_BLOG, KIND_OTHER})

VENUE_MATCH = "VENUE_MATCH"
VENUE_CANDIDATE = "VENUE_CANDIDATE"

# Platforms that are a group of people by construction.
GROUP_PLATFORMS = frozenset({"NAVER_CAFE", "DAUM_CAFE", "BAND", "DAANGN_GROUP"})

# --- limits (a search, not a crawl) --------------------------------------------------

MAX_QUERIES_PER_PROVIDER = 30
REGION_KEYWORDS_PER_GENRE = 2
MAX_EXTRA_KEYWORDS = 3
KEYWORD_MAX = 40
RESULTS_PER_CALL = {"cafe": 15, "web": 10}
CALL_DELAY_SECONDS = 0.5
# Calendar months, not a fixed day count - so "12 months ago" lands on the
# same day next year regardless of which months it spans (28/29/30/31-day
# months, leap years). See months_ago().
ACTIVE_WINDOW_MONTHS = 12
KEEP_RUNS = 30
PENDING_ITEM_RETENTION_DAYS = 400
STALE_RUN_MINUTES = 60
SNIPPET_MAX = 240
TITLE_MAX = 200
KEEP_QUERIES = 8
KEEP_NAMES = 5
MAX_VENUES = 5
MAX_ERROR_LINES = 5


class DiscoveryError(DirectoryError):
    """An operator request that cannot be carried out, said in words."""


class ProviderUnavailable(RuntimeError):
    """A provider cannot run at all this time (e.g. no credential configured)."""

    def __init__(self, status: str, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


# --- words the analysis reads ----------------------------------------------------------

GENRE_WORDS: dict[str, tuple[str, ...]] = {
    "SALSA": ("살사", "salsa"),
    "BACHATA": ("바차타", "bachata"),
    "KIZOMBA": ("키좀바", "kizomba", "어반키즈", "urbankiz"),
    "SWING": ("스윙", "swing", "린디", "lindy", "지터벅", "jitterbug", "찰스턴", "charleston"),
    "BALBOA": ("발보아", "balboa"),
    "TANGO": ("탱고", "땅고", "tango", "밀롱가", "milonga"),
}
COMMUNITY_WORDS = ("동호회", "모임", "커뮤니티", "동아리", "소사이어티", "society", "크루", "crew")
ACTIVITY_WORDS = ("정모", "파티", "강습", "모집", "번개", "행사", "일정", "공지", "소셜", "social",
                  "밀롱가", "워크샵", "워크숍", "수업", "개강", "기수")
INACTIVE_WORDS = ("활동 중단", "활동중단", "운영 중단", "운영중단", "잠정 중단", "폐쇄", "해체", "휴면",
                  "운영 종료", "운영종료", "문을 닫")
VENUE_WORDS = ("살사바", "스윙바", "댄스바", "라틴바", "탱고바", "댄스홀", "볼룸", "ballroom", "라운지")
VENUE_NAME_END = re.compile(r"(바|빠|bar|홀|hall|lounge)$", re.I)
ACADEMY_WORDS = ("학원", "아카데미", "academy", "스튜디오", "studio")
INSTRUCTOR_WORDS = ("강사", "쌤", "선생님", "개인레슨", "개인 레슨", "lesson")
EVENT_WORDS = ("페스티벌", "festival", "워크샵", "워크숍", "workshop", "캠프", "camp", "위켄드",
               "weekend", "대회", "competition")
# v0.89.2 (Classification Precision Patch): an event/information aggregator
# (Dancehive - "이 모든 정보를 한 곳에 모아") is dance-related but is not
# itself a community (Section 12) - checked only when no COMMUNITY_WORDS is
# also present, same guard as EVENT_WORDS/VENUE_WORDS above.
AGGREGATOR_WORDS = ("한 곳에 모아", "한곳에 모아", "이벤트를 모아", "행사를 모아", "일정을 모아",
                    "정보를 모아", "한눈에 보는", "한눈에 확인", "어플리케이션", "디렉토리",
                    "directory", "aggregator", "플랫폼", "platform")

# v0.89.2: a genre word that pattern-matches only because of a same-genre
# false-positive neighbour - stock-market "swing" (스윙매매), a food "salsa"
# (살사소스), a cross-branded product ("망고탱고" ice cream) - three real
# Production reviews found these attached to entities with no dance
# connection at all. Never counted on its own (see detect_genres); it stays
# counted when the SAME text also has its own clean, independent occurrence,
# so a single stray off-topic word can never erase a genre that has its own
# real evidence (Section 5, Case 5: "이번 뒤풀이에 살사소스 제공" inside an
# otherwise genuine Salsa community post).
GENRE_NEGATIVE_WORDS: dict[str, tuple[str, ...]] = {
    "SWING": ("스윙매매", "스윙 매매", "스윙트레이딩", "스윙 트레이딩", "매매일지", "주식", "트레이딩",
              "매매", "종목", "코인", "투자", "차트", "스윙자켓", "스윙 자켓", "스윙도어", "스윙 도어",
              "swing door", "swing trading", "골프", "자이언트 스윙", "놀이기구", "롤러코스터",
              "rope swing", "그네"),
    "SALSA": ("살사소스", "살사 소스", "칠리살사", "칠리 살사", "salsa sauce", "chili salsa",
              "소스", "레시피", "recipe", "스낵", "snack", "과자", "토마토소스"),
    "TANGO": ("망고탱고", "망고 탱고", "탱고 아이스크림", "시인", "문학", "시집", "가사", "ost",
              "앨범", "영화", "콘서트 후기"),
}
# Characters either side of a genre word to look for a negative neighbour -
# enough to catch a tight compound ("스윙매매", "살사소스", "망고탱고") and a
# short hashtag cluster ("#SwingLog #스윙로그 #스윙매매 #주식공부") without
# reaching all the way into an unrelated sentence elsewhere in the same
# snippet (Section 5, Case 5's "이번 뒤풀이에 살사소스 제공" sits well past
# this many characters from a genuine Salsa community's own mention).
GENRE_CONTEXT_WINDOW = 18

# v0.89.2: a search hit whose own text says it is someone else's promotion,
# not the host cafe/community's own activity (Section 6-8) - the exact
# CASINO RUEDA production failure was a third-party tango academy's class
# enrollment ad, posted to a Cafe's own advertisement board, whose TANGO
# genre and date the old classifier read as CASINO RUEDA's own. A board-name
# word here is a real, commonly-seen Korean cafe convention (the real case's
# own board was literally named "외부홍보게시판(레슨)"), not a guess.
#
# Only the unambiguous board names count on their own (Section 18: "board
# title만으로 100% external이라고 단정하지 않는다") - a name that structurally
# can only mean "not this cafe's own" (광고방/외부홍보/...). Genuinely generic
# board names a real community could just as easily use for its own posts
# ("정보공유", "자유게시판", "홍보방") are deliberately left out of this list
# rather than guessed at from the name alone; an explicit phrase is what
# marks those as someone else's promotion instead.
AD_BOARD_WORDS = ("광고방", "외부홍보", "타동호회홍보", "타동호회 홍보", "행사홍보")
EXTERNAL_PROMOTION_PHRASES = ("홍보합니다", "공유합니다", "외부 강사", "타 학원", "타학원",
                              "다른 카페의", "다른 동호회의", "제휴 홍보")

# v0.89.3 (Evidence Attribution Patch): a Production validation run found the
# real CASINO RUEDA row's collected snippet never contains any AD_BOARD_WORDS
# or EXTERNAL_PROMOTION_PHRASES at all - the Naver/Kakao search API simply
# does not return the board name a human sees by opening the real page. Its
# actual instructor-bio phrase ("20여년 강습경력") is exactly the shape of
# language a for-profit academy/instructor uses to advertise themselves, on
# whatever cafe happens to host the post - a peer-run community's own event
# announcement essentially never brags about an instructor's tenure this
# way. Neither list is trusted alone, though (Section 12: an academy word by
# itself never forces NOT_A_COMMUNITY - a real Community teaches classes
# too): hit_is_external only acts on these when the SAME text also lacks
# the host's own community language AND names a differently-branded academy
# (see _mentions_other_entity below).
INSTRUCTOR_BIO_PHRASES = ("년 강습경력", "년경력", "년째 강습", "전임강사", "대표강사", "수석강사", "원장")
ENROLLMENT_PHRASES = ("수강생", "수강신청", "수강 신청", "등록문의", "등록 문의", "강습 신청",
                      "입문반", "초급반 모집", "class registration")
# Section 6's override: a real Community that also runs paid classes keeps
# its HOST reading when its own text carries its own community-activity
# language - deliberately narrower than COMMUNITY_WORDS/ACTIVITY_WORDS
# (which an academy ad's incidental hashtags can trip: the real CASINO RUEDA
# text contains a bare "모임" and "#2040동호회" hashtag despite being someone
# else's ad) so this check only recognizes language that actually describes
# the host's own regular gathering, not a passing mention.
HOST_COMMUNITY_SIGNAL_WORDS = ("정모", "회원", "우리 동호회", "이번 주 모임", "정기 소셜", "기 모집", "번개")
# A hashtag or bracketed name naming the promoted academy/course, found
# alongside the phrases above - never a single hardcoded organization name
# (Section 10 explicitly forbids a CASINO-RUEDA-specific rule); any mention
# containing one of these generic academy words and differing from the
# host's own name is treated as "a different organizer is being promoted
# here" (Section 5).
_MENTION_ACADEMY_HINTS = ACADEMY_WORDS
_HASHTAG = re.compile(r"#([^\s#\[\]()]{2,20})")
_BRACKETED_MENTION = re.compile(r"[\[(]([^\])]{2,20})[\])]")

# v0.89.3 (Section 13-18): a news/media page that merely mentions a dance
# community in its coverage is not itself a community. "news." is an
# unambiguous Korean publisher-subdomain convention (news.kbs.co.kr,
# news.sbs.co.kr, news.jtbc.co.kr, ...) and counts alone; a bare top-level
# wire-service domain is more ambiguous on its own (Section 18: "domain만으로
# 전부 판단하지 않는다" - a Naver Blog can host a media article, a community's
# own site can sit on a plain .com), so those require in-text journalism
# language too. Deliberately excludes the bare word "뉴스" itself: a
# Community's own post proudly saying "우리 동호회가 KBS 뉴스에 소개됐습니다"
# must never flip the COMMUNITY's own cafe into NEWS_OR_MEDIA (Section 21).
NEWS_KNOWN_HOSTS = frozenset({"yna.co.kr", "yonhapnews.co.kr", "chosun.com", "joongang.co.kr",
                              "hani.co.kr", "khan.co.kr", "mk.co.kr", "sbs.co.kr", "mbc.co.kr",
                              "kbs.co.kr", "ytn.co.kr", "newsis.com", "edaily.co.kr", "hankyung.com",
                              "donga.com", "seoul.co.kr", "koreaherald.com", "yonhap.co.kr"})
NEWS_CONTEXT_WORDS = ("기자", "보도", "취재", "앵커", "특파원", "무단전재", "재배포 금지", "제보")
# Section 14's URL-path signal - never body text alone for an ambiguous
# (non-"news.") domain: a community's own cafe URL structurally never
# contains one of these, so this is a safe co-signal where NEWS_KNOWN_HOSTS
# membership by itself would not be (Section 18).
NEWS_PATH_HINTS = ("/news/", "/article/", "/articles/", "newsview", "articleview", "/read/")

# Hosts that are never a community's own page.
OTHER_HOSTS = frozenset({"youtube.com", "youtu.be", "namu.wiki", "wikipedia.org", "news.naver.com",
                         "n.news.naver.com", "v.daum.net", "tv.naver.com", "map.naver.com",
                         "place.map.kakao.com", "map.kakao.com", "kin.naver.com", "danceinfo.net",
                         "tistory.com", "naver.com", "daum.net", "google.com"})
# Neighbourhoods and cities that say which region a group dances in.
REGION_HINTS: dict[str, tuple[str, ...]] = {
    "KR-SEOUL": ("서울", "홍대", "강남", "신촌", "합정", "건대", "신림", "사당", "압구정", "이태원", "잠실",
                 "종로", "역삼", "선릉"),
    "KR-GYEONGGI": ("경기", "수원", "성남", "분당", "일산", "고양", "안양", "용인", "부천", "의정부",
                    "안산", "평택", "화성", "김포", "파주", "광명"),
    "KR-INCHEON": ("인천", "부평", "송도"),
    "KR-BUSAN": ("부산", "서면", "해운대"),
    "KR-DAEJEON": ("대전", "유성", "둔산"),
    "KR-DAEGU": ("대구", "동성로"),
    "KR-GWANGJU": ("광주",),
    "KR-ULSAN": ("울산",),
    "KR-JEJU": ("제주", "서귀포"),
    # v0.89.4 (Region Master Coverage & Resolution): DanceMate's own Region
    # master is not one consistent granularity - mostly province/metro level
    # (경기/충북/경북/경남/...), but four cities (청주/진주/창원/포항) already
    # have their OWN dedicated Region rows from earlier ad hoc additions.
    # Kept exactly as-is (Section 22: no deletion, no restructuring) - a
    # province's hints below never repeat a city that already has its own
    # row, or "청주"/"진주"/"창원"/"포항" text would match two Regions at
    # once and go unresolved by the existing (correct) ambiguity rule
    # instead of resolving to that city's own row as it already does today.
    "KR-CHUNGBUK": ("충북", "충청북도", "충주", "제천"),
    "KR-GYEONGBUK": ("경북", "경상북도", "경주", "구미", "안동", "영주"),
    "KR-GYEONGNAM": ("경남", "경상남도", "김해", "거제", "통영", "양산"),
    # New Regions (Section 5-6): provinces with real Production Community
    # evidence (전주 #30, 여수 #33, 천안+서산+당진 #23/#35) but no Region row
    # at all until this release - see migrations/runtime/038_region_master_
    # coverage.sql. 서산 and 당진 both under KR-CHUNGNAM is exactly Section
    # 18's safe case: two different cities that share one canonical parent
    # resolve to that one Region without picking between them (detect_region
    # de-duplicates by Region code, never by which hint matched).
    "KR-JEONBUK": ("전북", "전라북도", "전주", "군산", "익산"),
    "KR-JEONNAM": ("전남", "전라남도", "여수", "순천", "목포"),
    "KR-CHUNGNAM": ("충남", "충청남도", "천안", "아산", "서산", "당진"),
    "KR-GANGWON": ("강원", "강원도", "강원특별자치도", "춘천", "원주", "강릉"),
}
GENERIC_NAME_WORDS = ("동호회", "모임", "커뮤니티", "동아리", "카페", "클럽", "club", "cafe", "댄스",
                      "dance", "초보", "소셜", "social", "korea", "코리아", "한국", "스튜디오")


# --- small text helpers ------------------------------------------------------------------

_TAG = re.compile(r"<[^>]+>")
_OPEN_CHAT = re.compile(r"https?://open\.kakao\.com/\S*", re.I)
_TEXT_DATE = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")
_TEXT_MONTH = re.compile(r"(20\d{2})\s*년\s*(\d{1,2})\s*월")
_BRACKETED = re.compile(r"[\[\(【][^\]\)】]*[\]\)】]")
_NAME_EDGE = re.compile(r"^[\W_]+|[\W_]+$")
_CAFE_TITLE_SUFFIX = re.compile(
    r"\s*[:\-|]\s*(네이버\s*카페|naver\s*cafe|다음\s*카페|daum\s*카페|daum\s*cafe)\s*$", re.I)
_ID = re.compile(r"[A-Za-z0-9_.\-@]{2,64}")


def strip_markup(value: Any) -> str:
    return " ".join(_TAG.sub("", html.unescape(str(value or ""))).split())


def clean_snippet(text: str, limit: int = SNIPPET_MAX) -> str:
    """Short, and with nothing personal in it."""
    cleaned = _OPEN_CHAT.sub("", strip_markup(text))
    cleaned, _ = acquisition.redact_personal_data(cleaned)
    return " ".join(cleaned.split())[:limit]


def normalize_query(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text or "").split()).lower()


def normalize_name(name: str | None) -> str | None:
    if not name:
        return None
    key = master_data.normalize_alias(_BRACKETED.sub("", name)) or master_data.normalize_alias(name)
    return key or None


def is_generic_name(normalized: str | None) -> bool:
    """A name made only of genre, region and 'club' words says nothing about who it is."""
    if not normalized:
        return True
    residue = normalized
    words = [w for ws in GENRE_WORDS.values() for w in ws] + list(GENERIC_NAME_WORDS) \
        + [w for ws in REGION_HINTS.values() for w in ws]
    for word in sorted({master_data.normalize_alias(w) for w in words}, key=len, reverse=True):
        if word:
            residue = residue.replace(word, "")
    return len(residue) < 2


def as_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    match = re.match(r"\s*(\d{4})-?(\d{2})-?(\d{2})", str(value))
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def text_dates(text: str, today: date) -> list[date]:
    """Dates written out with a year. A date without a year is not evidence of
    when anything happened; a future one counts as today (it was announced)."""
    found: list[date] = []
    for match in _TEXT_DATE.finditer(text or ""):
        try:
            found.append(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except ValueError:
            continue
    for match in _TEXT_MONTH.finditer(text or ""):
        try:
            found.append(date(int(match.group(1)), int(match.group(2)), 1))
        except ValueError:
            continue
    return [min(d, today) for d in found if 2015 <= d.year <= today.year + 1]


def _contains_any(text: str, words: Iterable[str]) -> str | None:
    lowered = text.lower()
    return next((w for w in words if w in lowered), None)


def months_ago(d: date, months: int) -> date:
    """``d``, shifted back by whole calendar months - the same day-of-month
    next/last year, clamped to a real day when the target month is shorter
    (Aug 31 minus 6 months is Feb 28, never Mar 3). Used for the 12-month
    activity window so the boundary is a calendar year, not a fixed 365/366
    day count that drifts across leap years."""
    import calendar

    month_index = d.month - 1 - months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


# --- queries ------------------------------------------------------------------------------

def ensure_default_queries(con) -> int:
    """Insert the default keywords for the genres that exist. Idempotent: a
    keyword an operator switched off stays off."""
    genres = {g["code"]: g["genre_id"] for g in master_data.list_genres(con)}
    added = 0
    with con.cursor() as cur:
        for code, keywords in DEFAULT_QUERIES.items():
            genre_id = genres.get(code)
            if genre_id is None:
                continue
            for keyword in keywords:
                cur.execute(
                    "INSERT INTO community_discovery_queries (genre_id, keyword, is_default) "
                    "VALUES (%s, %s, TRUE) ON CONFLICT DO NOTHING", (genre_id, keyword))
                added += cur.rowcount
    return added


def _rows(con, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    with con.cursor() as cur:
        cur.execute(sql, list(params))
        names = [c.name for c in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]


def list_queries(con, *, enabled_only: bool = False) -> list[dict[str, Any]]:
    rows = _rows(con, "SELECT q.*, g.code AS genre_code, g.name AS genre_name "
                      "FROM community_discovery_queries q JOIN genres g USING (genre_id)"
                 + (" WHERE q.enabled" if enabled_only else ""))
    order = {code: n for n, code in enumerate(TARGET_GENRES)}
    rows.sort(key=lambda r: (order.get(r["genre_code"], len(order)), r["genre_code"], r["query_id"]))
    return rows


def add_query(con, *, genre_id: Any, keyword: Any, provider_scope: Any = SCOPE_ALL) -> dict[str, Any]:
    gid = parse_id(genre_id, what="장르")
    text = clean_line(keyword, what="검색어", max_len=KEYWORD_MAX, required=True)
    scope = str(provider_scope or SCOPE_ALL).strip().upper()
    if gid is None:
        raise DiscoveryError("장르: 필수 항목입니다")
    if scope not in SCOPES:
        raise DiscoveryError(f"검색 범위: {', '.join(SCOPES)} 중 하나여야 합니다")
    if master_data.get_genre(con, gid) is None:
        raise DiscoveryError("장르: 존재하지 않는 항목입니다")
    with con.cursor() as cur:
        cur.execute("INSERT INTO community_discovery_queries (genre_id, keyword, provider_scope) "
                    "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING RETURNING query_id",
                    (gid, text, scope))
        row = cur.fetchone()
    if row is None:
        raise DiscoveryError(f"이미 있는 검색어입니다: {text}")
    return {"query_id": row[0], "keyword": text}


def set_query_enabled(con, query_id: int, enabled: bool) -> dict[str, Any]:
    with con.cursor() as cur:
        cur.execute("UPDATE community_discovery_queries SET enabled = %s, updated_at = now() "
                    "WHERE query_id = %s RETURNING keyword", (bool(enabled), query_id))
        row = cur.fetchone()
    if row is None:
        raise DiscoveryError(f"검색어 {query_id}을(를) 찾을 수 없습니다")
    return {"query_id": query_id, "keyword": row[0], "enabled": bool(enabled)}


@dataclass(frozen=True)
class PlannedQuery:
    provider: str
    text: str
    genre_code: str | None


def plan_queries(query_rows: Iterable[dict[str, Any]], *, genre_codes: Sequence[str],
                 region_names: Sequence[str] = (), extra_keywords: Sequence[str] = (),
                 providers: Sequence[str] = PROVIDERS,
                 max_per_provider: int = MAX_QUERIES_PER_PROVIDER) -> list[PlannedQuery]:
    """The searches a run makes, per provider.

    With no region: every enabled keyword of every chosen genre. With regions:
    each region name in front of the first REGION_KEYWORDS_PER_GENRE keywords
    of each genre - never every combination. Genres take turns so every genre
    gets its first query before any gets its second; duplicates (after
    normalisation) are dropped; each provider stops at max_per_provider.
    """
    wanted = [c for c in TARGET_GENRES if c in set(genre_codes)]
    wanted += [c for c in genre_codes if c not in wanted]
    by_genre: dict[str, list[tuple[str, str]]] = {c: [] for c in wanted}
    for row in query_rows:
        if row.get("enabled", True) and row.get("genre_code") in by_genre:
            by_genre[row["genre_code"]].append(
                (row["keyword"], (row.get("provider_scope") or SCOPE_ALL).upper()))
    extras = [" ".join(str(k).split()) for k in extra_keywords if str(k).strip()]
    plans: list[PlannedQuery] = []
    for provider in providers:
        lanes: list[list[tuple[str | None, str]]] = []
        for code in wanted:
            keywords = [kw for kw, scope in by_genre[code] if scope in (SCOPE_ALL, provider)]
            if region_names:
                lanes.append([(code, f"{region} {kw}") for region in region_names
                              for kw in keywords[:REGION_KEYWORDS_PER_GENRE]])
            else:
                lanes.append([(code, kw) for kw in keywords])
        if extras:
            lanes.append([(None, f"{region} {kw}") for region in region_names for kw in extras]
                         if region_names else [(None, kw) for kw in extras])
        seen: set[str] = set()
        out: list[PlannedQuery] = []
        depth = max((len(lane) for lane in lanes), default=0)
        for index in range(depth):
            for lane in lanes:
                if index >= len(lane) or len(out) >= max_per_provider:
                    continue
                code, text = lane[index]
                key = normalize_query(text)
                if key and key not in seen:
                    seen.add(key)
                    out.append(PlannedQuery(provider, " ".join(text.split()), code))
        plans.extend(out)
    return plans


# --- providers (the engine's clients) ----------------------------------------------------------

@dataclass
class Hit:
    provider: str
    kind: str
    query: str
    genre_hint: str | None
    url: str
    title: str
    snippet: str
    published: date | None
    source_name: str | None
    source_url: str | None


class NaverProvider:
    """NAVER API HUB search through the engine's NaverSearchCollector."""

    name = NAVER
    kinds = ("cafe", "web")
    SORT = {"cafe": "date", "web": "sim"}

    def __init__(self, collector):
        self.collector = collector

    def search(self, kind: str, query: str, size: int) -> list[dict[str, Any]]:
        records = self.collector.search(query, kind=kind, display=size, start=1, sort=self.SORT[kind])
        out = []
        for record in records:
            try:
                raw = json.loads(getattr(record, "raw_json", None) or "{}")
            except ValueError:
                raw = {}
            out.append({"url": record.source_url, "title": record.title, "snippet": record.body,
                        "published": record.published_at,
                        "source_name": getattr(record, "cafe_name", None) or None,
                        "source_url": (raw.get("cafeurl") if isinstance(raw, dict) else None) or None})
        return out


class KakaoProvider:
    """Kakao Daum search (cafe and web) through the engine's DaumCafeSearchCollector."""

    name = KAKAO
    kinds = ("cafe", "web")
    SORT = {"cafe": "recency", "web": "accuracy"}

    def __init__(self, clients: dict[str, Any]):
        self.clients = clients

    def search(self, kind: str, query: str, size: int) -> list[dict[str, Any]]:
        payload = self.clients[kind].search(query, sort=self.SORT[kind], page=1, size=size)
        documents = payload.get("documents") if isinstance(payload, dict) else None
        if not isinstance(documents, list):
            raise ValueError("malformed Kakao response: no documents list")
        return [{"url": d.get("url") or "", "title": strip_markup(d.get("title")),
                 "snippet": strip_markup(d.get("contents")), "published": d.get("datetime"),
                 "source_name": strip_markup(d.get("cafename")) or None, "source_url": None}
                for d in documents if isinstance(d, dict)]


def provider_availability() -> list[dict[str, Any]]:
    """Configured or not, by credential *name* only - never a value."""
    out = []
    for name in PROVIDERS:
        missing = collectors.missing_credentials(PROVIDER_PLATFORM[name])
        out.append({"provider": name, "label": PROVIDER_LABELS[name], "configured": not missing,
                    "missing": missing})
    return out


def default_provider_factory(settings) -> Callable[[str], Any]:
    def make(name: str):
        missing = collectors.missing_credentials(PROVIDER_PLATFORM[name])
        if missing:
            raise ProviderUnavailable(ACCESS_LIMITED,
                                      f"credentials not configured: {', '.join(missing)}")
        collectors._engine_on_path(settings)
        config = collectors._engine_settings(settings)
        if name == NAVER:
            from src.collectors.naver import NaverSearchCollector  # noqa: PLC0415

            timeout = (config.get("naver") or {}).get("timeout_seconds", 15)
            return NaverProvider(NaverSearchCollector(timeout_seconds=timeout))
        from src.collectors.daum import DaumCafeSearchCollector  # noqa: PLC0415

        daum = config["daum"]
        endpoint = daum["endpoint"]
        timeout = daum.get("timeout_seconds", 15)
        return KakaoProvider({
            "cafe": DaumCafeSearchCollector(endpoint, timeout_seconds=timeout),
            "web": DaumCafeSearchCollector(endpoint.rsplit("/", 1)[0] + "/web",
                                           timeout_seconds=timeout),
        })
    return make


def call_outcome(exc: BaseException) -> tuple[str, str]:
    """(status, redacted detail) for a failed provider call."""
    code = None
    seen: set[int] = set()
    err: BaseException | None = exc
    while err is not None and id(err) not in seen:
        seen.add(id(err))
        if isinstance(err, urllib.error.HTTPError):
            code = err.code
            break
        err = err.__cause__ or err.__context__
    classified = collector_errors.classify(exc)
    code = code or classified.status_code
    if code in (401, 403) or classified.kind in (collector_errors.AUTH_FAILED,
                                                 collector_errors.CREDENTIALS_MISSING,
                                                 collector_errors.QUOTA_EXCEEDED):
        status = ACCESS_LIMITED
    elif code == 429 or classified.kind == collector_errors.RATE_LIMITED:
        status = RATE_LIMITED
    else:
        status = CALL_ERROR
    label = classified.kind if status == CALL_ERROR else status
    detail = f"{label}{f' HTTP {code}' if code else ''}: {classified.detail}"
    return status, collector_errors.redact(detail)[:300]


def to_hit(row: dict[str, Any], provider: str, kind: str, planned: PlannedQuery) -> Hit | None:
    url = events_api.valid_public_url(str(row.get("url") or "").strip())
    if not url:
        return None
    source_url = events_api.valid_public_url(str(row.get("source_url") or "").strip())
    return Hit(provider=provider, kind=kind, query=planned.text, genre_hint=planned.genre_code,
               url=url, title=clean_snippet(row.get("title") or "", TITLE_MAX),
               snippet=clean_snippet(row.get("snippet") or ""), published=as_date(row.get("published")),
               source_name=clean_snippet(row.get("source_name") or "", 80) or None,
               source_url=source_url)


def _provider_summary(entry: dict[str, Any]) -> str:
    ok = entry["ok_calls"]
    failed = entry["failed_calls"]
    if not entry["queries"]:
        return CALL_NO_RESULTS
    if ok and not failed:
        return CALL_SUCCESS if entry["results"] else CALL_NO_RESULTS
    if ok:
        return PARTIAL_SUCCESS
    worst = [s for s in (ACCESS_LIMITED, RATE_LIMITED) if s in entry["failure_statuses"]]
    return worst[0] if worst else CALL_ERROR


def collect_hits(planned: Sequence[PlannedQuery], providers: Sequence[str],
                 provider_factory: Callable[[str], Any], *,
                 sleep: Callable[[float], None] = time.sleep) -> tuple[list[Hit], dict[str, Any]]:
    """Run the planned searches. A provider that cannot run, or a search kind
    that is refused or throttled, is recorded and skipped for the rest of the
    run - never retried in a loop - and the other providers carry on."""
    hits: list[Hit] = []
    status: dict[str, Any] = {}
    for name in providers:
        mine = [p for p in planned if p.provider == name]
        entry: dict[str, Any] = {"status": None, "queries": len(mine), "ok_calls": 0,
                                 "failed_calls": 0, "results": 0, "failure_statuses": [],
                                 "kinds": {}, "errors": []}
        status[name] = entry
        try:
            provider = provider_factory(name)
        except ProviderUnavailable as exc:
            entry.update(status=exc.status, failed_calls=0)
            entry["failure_statuses"].append(exc.status)
            entry["errors"].append(exc.detail)
            continue
        except Exception as exc:  # noqa: BLE001 - a provider must never take the run down
            outcome, detail = call_outcome(exc)
            entry.update(status=outcome)
            entry["failure_statuses"].append(outcome)
            entry["errors"].append(detail)
            continue
        blocked: dict[str, str] = {}
        for query in mine:
            for kind in provider.kinds:
                kind_state = entry["kinds"].setdefault(kind, {"ok": 0, "failed": 0, "results": 0})
                if kind in blocked:
                    continue
                try:
                    rows = provider.search(kind, query.text, RESULTS_PER_CALL.get(kind, 10))
                    if not isinstance(rows, list):
                        raise ValueError("malformed provider response")
                except Exception as exc:  # noqa: BLE001
                    outcome, detail = call_outcome(exc)
                    entry["failed_calls"] += 1
                    kind_state["failed"] += 1
                    entry["failure_statuses"].append(outcome)
                    if len(entry["errors"]) < MAX_ERROR_LINES:
                        entry["errors"].append(f"{kind}: {detail}")
                    if outcome in STOPPING:
                        blocked[kind] = outcome
                else:
                    found = [h for h in (to_hit(r, name, kind, query) for r in rows
                                         if isinstance(r, dict)) if h]
                    entry["ok_calls"] += 1
                    kind_state["ok"] += 1
                    kind_state["results"] += len(found)
                    entry["results"] += len(found)
                    hits.extend(found)
                sleep(CALL_DELAY_SECONDS)
        for kind, outcome in blocked.items():
            entry["kinds"][kind]["stopped"] = outcome
        entry["status"] = _provider_summary(entry)
    return hits, status


def overall_status(provider_status: dict[str, Any]) -> str:
    states = [v["status"] for v in provider_status.values()]
    if states and all(s in (CALL_SUCCESS, CALL_NO_RESULTS) for s in states):
        return SUCCESS
    if any(s in (CALL_SUCCESS, CALL_NO_RESULTS, PARTIAL_SUCCESS) for s in states):
        return PARTIAL_SUCCESS
    return FAILED


# --- identity ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Identity:
    platform: str
    key: str
    url: str


_RESERVED_NAVER = frozenset({"ca-fe", "cafes", "articleread.nhn", "f-e", "section", "cafe-home",
                             "joincafe", "mycafelist.nhn"})


def _split(url: str | None):
    if not url:
        return None
    try:
        parts = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return parts


def _host(parts) -> str:
    host = (parts.hostname or "").lower()
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host


def identify(url: str | None, source_url: str | None = None) -> Identity | None:
    """The public identity a result belongs to - one per group, not per post.

    A Naver/Daum cafe is its cafe id, a Band its band id, Instagram/Facebook
    their handle or group, a Daangn group its id, a personal blog its owner,
    any other site its host. The identity URL is also the normalised URL the
    candidate is tracked by.
    """
    parts = _split(url)
    if parts is None:
        return None
    host = _host(parts)
    segs = [s for s in parts.path.split("/") if s]
    query = urllib.parse.parse_qs(parts.query)
    if host == "cafe.naver.com":
        club = None
        home = _split(source_url)
        if home is not None and _host(home) == "cafe.naver.com":
            home_segs = [s for s in home.path.split("/") if s]
            if home_segs and home_segs[0].lower() not in _RESERVED_NAVER:
                club = home_segs[0]
        if club is None and segs and segs[0].lower() not in _RESERVED_NAVER:
            club = segs[0]
        if club is None:
            club = (query.get("clubid") or [None])[0]
        if not club or not _ID.fullmatch(club):
            return None
        return Identity("NAVER_CAFE", f"naver-cafe:{club.lower()}", f"https://cafe.naver.com/{club}")
    if host == "cafe.daum.net":
        if segs and _ID.fullmatch(segs[0]) and segs[0].lower() not in {"_c21_", "home"}:
            return Identity("DAUM_CAFE", f"daum-cafe:{segs[0].lower()}",
                            f"https://cafe.daum.net/{segs[0]}")
        return None
    if host == "band.us":
        if len(segs) >= 2 and segs[0] == "band" and segs[1].isdigit():
            return Identity("BAND", f"band:{segs[1]}", f"https://band.us/band/{segs[1]}")
        if segs and segs[0].startswith("@") and _ID.fullmatch(segs[0]):
            return Identity("BAND", f"band:{segs[0].lower()}", f"https://band.us/{segs[0]}")
        return None
    if host == "instagram.com":
        if segs and segs[0] not in {"p", "reel", "reels", "explore", "stories"} and _ID.fullmatch(segs[0]):
            return Identity("INSTAGRAM", f"instagram:{segs[0].lower()}",
                            f"https://www.instagram.com/{segs[0]}/")
        return None
    if host == "facebook.com":
        if len(segs) >= 2 and segs[0] == "groups" and _ID.fullmatch(segs[1]):
            return Identity("FACEBOOK", f"facebook:groups/{segs[1].lower()}",
                            f"https://www.facebook.com/groups/{segs[1]}")
        if segs and segs[0] not in {"events", "watch", "share", "story.php", "permalink.php",
                                    "photo.php"} and _ID.fullmatch(segs[0]):
            return Identity("FACEBOOK", f"facebook:{segs[0].lower()}",
                            f"https://www.facebook.com/{segs[0]}")
        return None
    if host == "daangn.com" and "group" in segs:
        index = segs.index("group")
        if len(segs) > index + 1:
            group = urllib.parse.unquote(segs[index + 1])
            return Identity("DAANGN_GROUP", f"daangn-group:{group.lower()}",
                            f"https://www.daangn.com/kr/group/{segs[index + 1]}/")
        return None
    if host == "blog.naver.com":
        user = segs[0] if segs else (query.get("blogId") or [None])[0]
        if user and _ID.fullmatch(user):
            return Identity("BLOG", f"naver-blog:{user.lower()}", f"https://blog.naver.com/{user}")
        return None
    if host.endswith(".tistory.com"):
        user = host.split(".")[0]
        return Identity("BLOG", f"tistory:{user}", f"https://{host}/")
    if host == "blog.daum.net" and segs:
        return Identity("BLOG", f"daum-blog:{segs[0].lower()}", f"https://blog.daum.net/{segs[0]}")
    if not host:
        return None
    if host in OTHER_HOSTS or any(host.endswith("." + other) for other in OTHER_HOSTS):
        return Identity("OTHER", f"web:{host}", f"https://{host}/")
    return Identity("WEB", f"web:{host}", f"{parts.scheme}://{host}/")


# --- analysis -----------------------------------------------------------------------------------------

@dataclass
class Context:
    today: date
    genre_ids: dict[str, int]
    regions: list[tuple[str, int, str, tuple[str, ...]]]
    region_names: dict[int, str]
    venues: list[dict[str, Any]]
    venue_names: dict[str, int]
    communities: list[dict[str, Any]]


def load_context(con, today: date | None = None) -> Context:
    genre_ids = {g["code"]: g["genre_id"] for g in master_data.list_genres(con)}
    regions, region_names = [], {}
    for r in master_data.list_regions(con):
        region_names[r["region_id"]] = r["name"]
        if r["code"] == "KR":
            continue
        hints = tuple(dict.fromkeys((r["name"],) + REGION_HINTS.get(r["code"], ())))
        regions.append((r["code"], r["region_id"], r["name"], hints))
    venues = []
    venue_names: dict[str, int] = {}
    for v in _rows(con, "SELECT v.venue_id, v.name, v.region_id, "
                        "  ARRAY(SELECT g.code FROM venue_genres vg JOIN genres g USING (genre_id) "
                        "        WHERE vg.venue_id = v.venue_id) AS genre_codes, "
                        "  ARRAY(SELECT a.normalized_alias FROM venue_aliases a "
                        "        WHERE a.venue_id = v.venue_id) AS aliases "
                        "FROM venues v WHERE v.enabled ORDER BY v.venue_id"):
        keys = {k for k in list(v["aliases"] or []) + [master_data.normalize_alias(v["name"])]
                if k and len(k) >= 3}
        for key in keys:
            venue_names.setdefault(key, v["venue_id"])
        venues.append({**v, "keys": sorted(keys, key=len, reverse=True)})
    comms = []
    for c in communities.list_communities(con):
        ident = identify(c.get("homepage_url"))
        comms.append({"community_id": c["community_id"], "name": c["name"],
                      "normalized": normalize_name(c["name"]),
                      "url_key": ident.key if ident else None, "region_id": c["region_id"]})
    return Context(today=today or date.today(), genre_ids=genre_ids, regions=regions,
                   region_names=region_names, venues=venues, venue_names=venue_names,
                   communities=comms)


def clean_name(value: str | None) -> str | None:
    if not value:
        return None
    name = " ".join(_NAME_EDGE.sub("", unicodedata.normalize("NFKC", strip_markup(value))).split())
    return name if 2 <= len(name) <= 60 else None


def extract_name(identity: Identity, hits: Sequence[Hit]) -> tuple[str | None, list[str]]:
    """The group's own name, or None. A cafe's name comes from the API's cafe
    name field (or a '<name> : 네이버 카페' page title); a homepage's from the
    first segment of its home page title when that segment reads like a
    group. A post title is never taken as a name."""
    names: list[str] = []
    for hit in hits:
        name = None
        if identity.platform in ("NAVER_CAFE", "DAUM_CAFE") and hit.source_name:
            name = clean_name(hit.source_name)
        elif identity.platform in ("NAVER_CAFE", "DAUM_CAFE", "BAND"):
            match = _CAFE_TITLE_SUFFIX.search(hit.title)
            if match:
                name = clean_name(hit.title[:match.start()])
        elif identity.platform == "WEB":
            path = urllib.parse.urlsplit(hit.url).path
            if path in ("", "/"):
                first = re.split(r"\s+[|\-–—:·]\s+", hit.title)[0]
                lowered = first.lower()
                if _contains_any(lowered, COMMUNITY_WORDS) or any(
                        _contains_any(lowered, words) for words in GENRE_WORDS.values()):
                    name = clean_name(first)
        if name:
            names.append(name)
    if not names:
        return None, []
    return Counter(names).most_common(1)[0][0], list(dict.fromkeys(names))[:KEEP_NAMES]


def _genre_scan(text: str, genre_ids: dict[str, int]) -> tuple[dict[str, str], dict[str, str]]:
    """One pass shared by detect_genres/genre_negative_context: for each
    genre word occurrence in ``text``, look at GENRE_CONTEXT_WINDOW
    characters either side for a same-genre false-positive neighbour
    (GENRE_NEGATIVE_WORDS). A genre counts (``found``) from its first clean,
    unwrapped occurrence; when every occurrence found is wrapped, the first
    one is kept only as an explanatory ``suppressed`` note - never counted.
    """
    lowered = text.lower()
    found: dict[str, str] = {}
    suppressed: dict[str, str] = {}
    # A genre word with no local negative neighbour but still floating in a
    # document that has no community/activity evidence of its own kind
    # anywhere (Section 3D/5: a poem or product name that merely name-drops
    # a genre word, no compound needed - "시인"/"가사"/"앨범" can sit a whole
    # sentence away from "탱고") is not trusted either. A real community's
    # own COMMUNITY_WORDS/ACTIVITY_WORDS mention anywhere in the text is
    # what tells the two apart - never a single stray negative word, which
    # the local-window check above already isolates.
    has_positive_context = bool(_contains_any(lowered, COMMUNITY_WORDS)
                                or _contains_any(lowered, ACTIVITY_WORDS))
    for code, words in GENRE_WORDS.items():
        if code not in genre_ids:
            continue
        negatives = GENRE_NEGATIVE_WORDS.get(code, ())
        clean, wrapped_word, wrapped_neg = None, None, None
        for word in words:
            w = word.lower()
            start = 0
            while True:
                idx = lowered.find(w, start)
                if idx == -1:
                    break
                start = idx + 1
                window = lowered[max(0, idx - GENRE_CONTEXT_WINDOW): idx + len(w) + GENRE_CONTEXT_WINDOW]
                neg = next((n for n in negatives if n in window), None)
                if neg is None:
                    clean = word
                    break
                if wrapped_word is None:
                    wrapped_word, wrapped_neg = word, neg
            if clean:
                break
        if clean and not has_positive_context:
            doc_neg = _contains_any(lowered, negatives)
            if doc_neg:
                clean, wrapped_word, wrapped_neg = None, clean, doc_neg
        if clean:
            found[code] = clean
        elif wrapped_word:
            suppressed[code] = f"'{wrapped_word}' near '{wrapped_neg}'"
    return found, suppressed


def detect_genres(text: str, genre_ids: dict[str, int]) -> dict[str, str]:
    """Genre -> the word that showed it. Only genres the master knows.

    v0.89.2 (Classification Precision Patch): a genre word wrapped in a
    same-genre false-positive context (stock-trading '스윙매매', a food
    '살사소스', a cross-branded '망고탱고', ...) does not count on its own -
    see _genre_scan. It still counts when the same text also carries an
    independent, unwrapped occurrence elsewhere, so a single stray off-topic
    mention can never erase a genre that has its own real evidence.
    """
    return _genre_scan(text, genre_ids)[0]


def genre_negative_context(text: str, genre_ids: dict[str, int]) -> dict[str, str]:
    """Genre -> a short, human-readable note ('word near neighbour') for a
    genre keyword that appeared in the text but only ever inside a
    same-genre false-positive context - never for a genre detect_genres
    already found for the same text. Purely explanatory (Section 19/20): it
    changes no stored genre relation, it only becomes a classification
    reason so an operator can see why a candidate did not gain a genre it
    otherwise looks like it should have."""
    return _genre_scan(text, genre_ids)[1]


def detect_region(text: str, regions) -> tuple[int | None, str | None]:
    """One region when exactly one matches; several -> none resolved, all named."""
    found: dict[str, tuple[int, str]] = {}
    for code, region_id, name, hints in regions:
        if any(hint in text for hint in hints):
            found[code] = (region_id, name)
    if len(found) == 1:
        region_id, name = next(iter(found.values()))
        return region_id, name
    if found:
        return None, "/".join(sorted(name for _, name in found.values()))
    return None, None


@dataclass(frozen=True)
class ActivityResult:
    verdict: str                       # ACTIVE / STALE / INACTIVE / UNVERIFIED
    activity_date: date | None
    confidence: str                    # CONFIRMED / INFERRED / UNKNOWN_DATE
    evidence_url: str | None
    evidence_title: str | None
    evidence_source: str | None
    reasons: list[str]


def _hit_date_evidence(hit: "Hit", today: date) -> tuple[list[date], str | None]:
    """The date(s) this one hit is worth trusting, and which kind of
    evidence they are.

    A date written out inside the post's own title/snippet is preferred over
    the provider's own ``published``/``datetime`` metadata: a search result's
    date field can reflect when it was last indexed, re-crawled or (for a
    pinned notice) re-saved, not when the content was actually posted - this
    is the exact failure a Production review of a real candidate found (a
    genre match and an activity word looked current; the real page's newest
    post was over a year old). Metadata is used only when the text itself
    names no date at all.
    """
    embedded = text_dates(f"{hit.title} {hit.snippet}", today)
    if embedded:
        return embedded, "text"
    if hit.published:
        return [hit.published], "provider_index"
    return [], None


# How trustworthy a source of dates is, most to least - used only to pick
# which evidence to report when several hits disagree, never to invent a
# CONFIRMED an automated run has no way to actually know.
_SOURCE_RANK = {"confirmed": 0, "text": 1, "provider_index": 2}


def assess_activity(hits: Sequence[Hit], today: date, *,
                    previous_date: date | None = None,
                    previous_confidence: str = UNKNOWN_DATE) -> ActivityResult:
    """ACTIVE needs a dated post that itself shows activity, within
    ACTIVE_WINDOW_MONTHS; a result's date alone is not enough. INACTIVE when a
    post says so. A previously CONFIRMED date (an operator checked the real
    page) is always kept in the running and re-judged against *today* - a
    fact that was confirmed once does not expire, but whether it still falls
    inside the window does.
    """
    candidates: list[tuple[date, str, Hit | None, str | None]] = []
    all_dates: list[date] = []
    inactive = None
    if previous_date is not None:
        if previous_confidence == CONFIRMED:
            candidates.append((previous_date, "confirmed", None, None))
        else:
            all_dates.append(previous_date)
    for hit in hits:
        text = f"{hit.title} {hit.snippet}"
        dates, source = _hit_date_evidence(hit, today)
        all_dates.extend(dates)
        word = _contains_any(text, ACTIVITY_WORDS)
        inactive = inactive or _contains_any(text, INACTIVE_WORDS)
        if word and dates:
            candidates.append((max(dates), source, hit, word))

    if inactive:
        return ActivityResult(INACTIVE, None, UNKNOWN_DATE, None, None, None,
                              [f"activity: '{inactive}'"])

    if candidates:
        best_date, source, hit, word = min(
            candidates, key=lambda c: (_SOURCE_RANK[c[1]], -c[0].toordinal()))
        confidence = CONFIRMED if source == "confirmed" else INFERRED
        evidence_url = hit.url if hit else None
        evidence_title = hit.title[:TITLE_MAX] if hit else None
        evidence_source = hit.provider if hit else "ADMIN"
        window_note = "" if source != "provider_index" else " (검색 결과 날짜, 본문에 날짜 없음)"
        if best_date >= months_ago(today, ACTIVE_WINDOW_MONTHS):
            reason = (f"activity: {best_date.isoformat()} ('{word}'){window_note}" if word
                      else f"activity: {best_date.isoformat()}{window_note}")
            return ActivityResult(ACTIVE, best_date, confidence, evidence_url, evidence_title,
                                  evidence_source, [reason])
        return ActivityResult(
            STALE, best_date, confidence, evidence_url, evidence_title, evidence_source,
            [f"latest {'confirmed' if confidence == CONFIRMED else 'known'} activity "
             f"{best_date.isoformat()} (over {ACTIVE_WINDOW_MONTHS} months old)"])

    if all_dates:
        # A date without a confirming activity word: still real, known
        # evidence (a text-embedded date, a provider's own metadata date, or
        # a carried-over previous finding) - INFERRED, not UNKNOWN, and never
        # dropped just because nothing else in this run's hits mentioned it.
        latest = max(all_dates)
        if latest < months_ago(today, ACTIVE_WINDOW_MONTHS):
            return ActivityResult(
                STALE, latest, INFERRED, None, None, None,
                [f"latest evidence {latest.isoformat()} (over {ACTIVE_WINDOW_MONTHS} months old, "
                 "no activity word)"])
        return ActivityResult(
            UNVERIFIED, latest, INFERRED, None, None, None,
            [f"latest evidence {latest.isoformat()}, no activity word confirms it"])
    return ActivityResult(UNVERIFIED, None, UNKNOWN_DATE, None, None, None, ["no dated activity"])


def _mentions_other_entity(text: str, host_name: str | None) -> str | None:
    """A hashtag or bracketed phrase naming an academy/studio that is not
    the host's own name (Section 5-6, 10) - the closest thing to a named-
    entity comparison this rule-based classifier can do without an NLP
    model. Never a single hardcoded organization name: any mention
    containing a generic academy word (ACADEMY_WORDS) that does not match
    the host is treated as evidence a different organizer is being
    promoted here. Returns None when there is nothing to compare (no
    academy-flavoured mention at all)."""
    host_key = master_data.normalize_alias(host_name) if host_name else None
    for pattern in (_HASHTAG, _BRACKETED_MENTION):
        for match in pattern.finditer(text):
            raw = match.group(1)
            if not _contains_any(raw.lower(), _MENTION_ACADEMY_HINTS):
                continue
            key = master_data.normalize_alias(raw)
            if not key or (host_key and key == host_key):
                continue
            return raw
    return None


def hit_is_external(hit: "Hit", host_name: str | None = None) -> str | None:
    """The external-promotion signal this ONE hit's own title/snippet
    carries, or None (Section 4-6, 18). Not a verdict about the whole
    candidate by itself - a board name alone is never treated as 100% proof
    (Section 18); _upsert only excludes a hit from the host's own genre/
    activity evidence when its own text carries one of these, and only
    calls the candidate 'external promotion evidence only' (detect_kind's
    external_only) when EVERY hit collected for it does.

    v0.89.3: when the search API gives no explicit ad-board name at all (a
    real, confirmed Production gap - CASINO RUEDA's collected snippet never
    says "광고방"), fall back to instructor-bio OR enrollment language
    (Section 4-6, 12) naming a differently-branded academy/course - but only
    when the SAME text does not also carry the host's own community-
    activity language (HOST_COMMUNITY_SIGNAL_WORDS), so a real Community
    that also teaches classes is never mistaken for someone else's ad.
    """
    text = f"{hit.title} {hit.snippet}"
    strong = _contains_any(text, AD_BOARD_WORDS)
    if strong:
        return strong
    phrase = _contains_any(text, EXTERNAL_PROMOTION_PHRASES)
    if phrase:
        return phrase
    # v0.89.3 real-world calibration: the actual CASINO RUEDA snippet has an
    # instructor-bio phrase ("20여년 강습경력") but no separate enrollment
    # phrase at all (its only recruitment language is the generic "모집해요",
    # deliberately excluded from ENROLLMENT_PHRASES - a real community
    # recruiting new members says this too). Requiring BOTH missed the real
    # row entirely; either phrase alone, still gated by the absence of the
    # host's own community language AND a differently-named academy mention,
    # is precise enough (confirmed by the read-only Production preview).
    bio = _contains_any(text, INSTRUCTOR_BIO_PHRASES)
    enroll = _contains_any(text, ENROLLMENT_PHRASES)
    if (bio or enroll) and not _contains_any(text, HOST_COMMUNITY_SIGNAL_WORDS):
        marker = bio or enroll
        other = _mentions_other_entity(text, host_name)
        if other:
            return f"instructor/academy self-promotion ('{marker}', mentions '{other}')"
        if not host_name:
            return f"instructor/academy self-promotion ('{marker}')"
    return None


def _looks_like_news(host: str, urls: Iterable[str], text: str) -> str | None:
    """A generalized publisher/news-page signal (Section 13-18) - never a
    single hardcoded outlet. "news." is an unambiguous Korean publisher-
    subdomain convention and counts alone; a bare wire-service domain is
    more ambiguous by itself (a Naver Blog can host a media article, a
    community's own site can sit on a plain .com - Section 18), so those
    need a URL-path hint too (Section 14) - never in-text words alone,
    since a real Community's own post can easily say it "was covered by"
    the news (Section 21) without that page becoming a news page itself; a
    community's own cafe URL structurally never contains "/news/"/
    "/article/" in its own path, so the path co-signal is safe where a
    bare NEWS_KNOWN_HOSTS match would not be.
    """
    if host.startswith("news."):
        return f"news subdomain ({host})"
    known_host = any(host == h or host.endswith("." + h) for h in NEWS_KNOWN_HOSTS)
    if not known_host:
        return None
    path_hint = any(p in (u or "").lower() for u in urls for p in NEWS_PATH_HINTS)
    word = _contains_any(text, NEWS_CONTEXT_WORDS)
    if path_hint or word:
        return f"known news domain ({host})" + (f" + '{word}'" if word else " + article URL path")
    return None


def detect_kind(identity: Identity, name: str | None, text: str, ctx: Context, *,
                external_only: bool = False, external_reason: str | None = None,
                news_reason: str | None = None) -> tuple[str, str]:
    """What this is: a group, or a venue/academy/instructor/event/
    aggregator/news page/blog/other.

    v0.89.2: ``external_only`` (Section 6-8) means every hit collected for
    this identity was itself someone else's promotion (an ad-board post, a
    cross-posted class enrollment) - there is no evidence at all of the host
    cafe/community's own activity, so kind can only ever be UNKNOWN, never a
    confident COMMUNITY read off the mere fact that the identity happens to
    be a cafe/group platform. This is the exact CASINO RUEDA production
    failure: a third-party tango academy's ad, read as CASINO RUEDA's own
    TANGO community signal purely because CASINO RUEDA is a Daum cafe.

    v0.89.3: ``news_reason`` (Section 13-18) means the identity's own host/
    URL and collected text look like a publisher/news page - checked first,
    since a news article that happens to also mention "동호회" is not a
    community candidate no matter what else its text contains (Production
    candidate #442, a KBS article describing a court case about a Salsa
    club's bylaws).
    """
    if news_reason:
        return KIND_NEWS, f"publisher/news page ({news_reason}); the page itself is not the community"
    if external_only:
        detail = f" ({external_reason})" if external_reason else ""
        return KIND_UNKNOWN, f"external promotion evidence only{detail}; no host activity"
    if identity.platform == "OTHER":
        return KIND_OTHER, f"not a group's own site ({identity.url})"
    if identity.platform == "BLOG":
        return KIND_BLOG, "personal blog"
    if name:
        key = master_data.normalize_alias(name)
        if key in ctx.venue_names:
            return KIND_VENUE, f"same name as registered venue #{ctx.venue_names[key]}"
        lowered = name.lower()
        word = _contains_any(lowered, ACADEMY_WORDS)
        if word:
            # Section 11: an academy-sounding name can still run a real
            # community - only default to ACADEMY when the collected text
            # lacks separate, independent community evidence (a community
            # word AND an activity word, not merely one - a single
            # coincidental word is not "복수 evidence").
            community_word = _contains_any(text, COMMUNITY_WORDS)
            activity_word = _contains_any(text, ACTIVITY_WORDS)
            if community_word and activity_word:
                return KIND_COMMUNITY, (f"academy-style name ('{word}') but community evidence "
                                        f"('{community_word}', '{activity_word}')")
            return KIND_ACADEMY, f"academy/studio name ('{word}')"
        word = _contains_any(lowered, INSTRUCTOR_WORDS)
        if word:
            return KIND_INSTRUCTOR, f"instructor name ('{word}')"
        word = _contains_any(lowered, VENUE_WORDS)
        if word or VENUE_NAME_END.search(_NAME_EDGE.sub("", lowered)):
            return KIND_VENUE, f"venue name ('{word or name}')"
    if identity.platform in GROUP_PLATFORMS:
        return KIND_COMMUNITY, f"group platform ({identity.platform})"
    community_word = _contains_any(text, COMMUNITY_WORDS)
    event_word = _contains_any(text, EVENT_WORDS)
    if event_word and not community_word:
        return KIND_EVENT, f"one-off event ('{event_word}')"
    aggregator_word = _contains_any(text, AGGREGATOR_WORDS)
    if aggregator_word and not community_word:
        return KIND_AGGREGATOR, f"event/information aggregator ('{aggregator_word}')"
    venue_word = _contains_any(text, VENUE_WORDS)
    if venue_word and not community_word:
        return KIND_VENUE, f"venue page ('{venue_word}')"
    if community_word:
        return KIND_COMMUNITY, f"community word ('{community_word}')"
    word = _contains_any(text, INSTRUCTOR_WORDS)
    if word:
        return KIND_INSTRUCTOR, f"instructor page ('{word}')"
    return KIND_UNKNOWN, "no community signal"


def match_venues(text: str, region_id: int | None, genre_codes: Iterable[str],
                 venues: Sequence[dict[str, Any]]) -> list[tuple[int, str, str]]:
    """Registered venues named in the text, by their own aliases (3+ chars).
    VENUE_MATCH only when the venue's region or genres agree with the
    candidate's; a bare name is a VENUE_CANDIDATE. Never by address - two
    venues in one building stay two venues."""
    normalized = master_data.normalize_alias(text)
    genres = set(genre_codes)
    out = []
    for venue in venues:
        key = next((k for k in venue["keys"] if k in normalized), None)
        if not key:
            continue
        agrees = (region_id is not None and venue["region_id"] == region_id) \
            or bool(genres & set(venue["genre_codes"] or []))
        out.append((venue["venue_id"], VENUE_MATCH if agrees else VENUE_CANDIDATE, key))
    out.sort(key=lambda v: (v[1] != VENUE_MATCH, v[0]))
    return out[:MAX_VENUES]


def confidence_for(item: dict[str, Any], genres: Iterable[str]) -> str:
    """Operator hint, not a verdict.

    v0.89.1: HIGH now also requires the activity date itself to be CONFIRMED
    - a human actually checked the real page - not merely INFERRED by
    automation. An automated run can still classify a candidate VERIFIED_NEW
    on inferred evidence (useful, keeps recall), it just never gets to call
    that MEDIUM-strength evidence HIGH on its own; only a person can.
    """
    confirmed = item.get("activity_date_confidence") == CONFIRMED
    if item["classification"] == VERIFIED_EXISTING:
        return HIGH
    official = item["platform"] in GROUP_PLATFORMS or item["platform"] == "WEB"
    if (item["classification"] == VERIFIED_NEW and official and item.get("candidate_name")
            and item.get("region_id") and list(genres) and confirmed):
        return HIGH
    if item["kind"] == KIND_COMMUNITY and (item["activity"] == ACTIVE or item["seen_count"] >= 2
                                          or len(item.get("providers") or []) >= 2):
        return MEDIUM
    return LOW


# --- runs ----------------------------------------------------------------------------------------------

def get_run(con, run_id: int) -> dict[str, Any] | None:
    rows = _rows(con, "SELECT * FROM community_discovery_runs WHERE run_id = %s", (run_id,))
    return rows[0] if rows else None


def list_runs(con, *, limit: int = 10) -> list[dict[str, Any]]:
    return _rows(con, "SELECT * FROM community_discovery_runs ORDER BY run_id DESC LIMIT %s", (limit,))


def open_run(con) -> dict[str, Any] | None:
    rows = _rows(con, "SELECT * FROM community_discovery_runs WHERE status IN ('QUEUED', 'RUNNING') "
                      "ORDER BY run_id LIMIT 1")
    return rows[0] if rows else None


def queue_run(con, *, providers: Sequence[str], genre_codes: Sequence[str],
              region_codes: Sequence[str] = (), extra_keywords: Sequence[str] = (),
              requested_by: str = "admin") -> dict[str, Any]:
    chosen = [p for p in PROVIDERS if p in {str(x).upper() for x in providers}]
    if not chosen:
        raise DiscoveryError("검색 서비스를 하나 이상 고르세요")
    asked = [str(c).strip().upper() for c in genre_codes if str(c).strip()]
    unknown = [c for c in asked if c not in TARGET_GENRES]
    if unknown:
        raise DiscoveryError(f"지원하지 않는 장르입니다: {', '.join(unknown)}")
    known = {g["code"] for g in master_data.list_genres(con)}
    genres = [c for c in TARGET_GENRES if c in asked and c in known]
    if not genres:
        raise DiscoveryError("장르를 하나 이상 고르세요")
    regions = {r["code"] for r in master_data.list_regions(con)}
    asked_regions = [str(c).strip().upper() for c in region_codes if str(c).strip()]
    bad = [c for c in asked_regions if c not in regions or c not in REGION_QUERY_CODES]
    if bad:
        raise DiscoveryError(f"지역: 선택할 수 없는 지역입니다 ({', '.join(bad)})")
    extras: list[str] = []
    for raw in extra_keywords:
        text = clean_line(raw, what="추가 검색어", max_len=KEYWORD_MAX)
        if text and normalize_query(text) not in {normalize_query(e) for e in extras}:
            extras.append(text)
    if len(extras) > MAX_EXTRA_KEYWORDS:
        raise DiscoveryError(f"추가 검색어는 {MAX_EXTRA_KEYWORDS}개까지입니다")
    current = open_run(con)
    if current:
        raise DiscoveryError(f"이미 대기 중이거나 실행 중인 검색이 있습니다 (#{current['run_id']})")
    ensure_default_queries(con)
    rows = _rows(con, "INSERT INTO community_discovery_runs (providers, genre_codes, region_codes, "
                      "  extra_keywords, requested_by) VALUES (%s, %s, %s, %s, %s) RETURNING *",
                 (chosen, genres, list(dict.fromkeys(asked_regions)), extras, requested_by))
    return rows[0]


def claim_next_run(con) -> int | None:
    """The oldest queued run, now RUNNING. A run left RUNNING by a restart is
    closed as FAILED first, so it cannot block the queue for ever."""
    with con.transaction():
        with con.cursor() as cur:
            cur.execute("UPDATE community_discovery_runs SET status = 'FAILED', completed_at = now(), "
                        "  error_summary = 'interrupted before completion' "
                        "WHERE status = 'RUNNING' AND started_at < now() - make_interval(mins => %s)",
                        (STALE_RUN_MINUTES,))
            cur.execute("UPDATE community_discovery_runs SET status = 'RUNNING', started_at = now() "
                        "WHERE run_id = (SELECT run_id FROM community_discovery_runs "
                        "  WHERE status = 'QUEUED' ORDER BY run_id LIMIT 1 FOR UPDATE SKIP LOCKED) "
                        "RETURNING run_id")
            row = cur.fetchone()
    return row[0] if row else None


def execute_run(con, run_id: int, *, provider_factory: Callable[[str], Any],
                sleep: Callable[[float], None] = time.sleep,
                today: date | None = None) -> dict[str, Any]:
    run = get_run(con, run_id)
    if run is None:
        raise DiscoveryError(f"검색 #{run_id}을(를) 찾을 수 없습니다")
    if run["status"] == QUEUED:
        with con.cursor() as cur:
            cur.execute("UPDATE community_discovery_runs SET status = 'RUNNING', started_at = now() "
                        "WHERE run_id = %s", (run_id,))
    ensure_default_queries(con)
    regions = {r["code"]: r["name"] for r in master_data.list_regions(con)}
    planned = plan_queries(list_queries(con, enabled_only=True), genre_codes=run["genre_codes"],
                           region_names=[regions[c] for c in run["region_codes"] if c in regions],
                           extra_keywords=run["extra_keywords"], providers=run["providers"])
    hits, provider_status = collect_hits(planned, run["providers"], provider_factory, sleep=sleep)
    ctx = load_context(con, today)
    with con.transaction():
        stats = store_hits(con, hits, ctx, run_id)
        final = overall_status(provider_status)
        errors = [f"{PROVIDER_LABELS.get(p, p)} {v['status']}: {v['errors'][0]}"
                  for p, v in provider_status.items() if v["errors"]]
        for entry in provider_status.values():
            entry.pop("failure_statuses", None)
        with con.cursor() as cur:
            cur.execute(
                "UPDATE community_discovery_runs SET status = %s, completed_at = now(), "
                "  query_count = %s, result_count = %s, new_items = %s, updated_items = %s, "
                "  provider_status = %s::jsonb, error_summary = %s WHERE run_id = %s",
                (final, len(planned), len(hits), stats["new"], stats["updated"],
                 json.dumps(provider_status, ensure_ascii=False),
                 "; ".join(errors)[:1000] or None, run_id))
        prune(con)
    return get_run(con, run_id)


def run_pending(settings, *, provider_factory: Callable[[str], Any] | None = None,
                sleep: Callable[[float], None] = time.sleep) -> str:
    """The scheduler job: run the oldest queued search, if there is one."""
    from . import db  # noqa: PLC0415

    with db.connect(settings, autocommit=True) as con:
        run_id = claim_next_run(con)
        if run_id is None:
            return "no queued community discovery run"
        try:
            run = execute_run(con, run_id,
                              provider_factory=provider_factory or default_provider_factory(settings),
                              sleep=sleep)
        except Exception as exc:
            detail = collector_errors.redact(f"{type(exc).__name__}: {exc}")[:500]
            with con.cursor() as cur:
                cur.execute("UPDATE community_discovery_runs SET status = 'FAILED', "
                            "  completed_at = now(), error_summary = %s WHERE run_id = %s",
                            (detail, run_id))
            raise
    providers = " ".join(f"{p}={v['status']}" for p, v in (run["provider_status"] or {}).items())
    return (f"run #{run_id} {run['status']} queries={run['query_count']} "
            f"results={run['result_count']} new={run['new_items']} "
            f"updated={run['updated_items']} {providers}")


def prune(con) -> None:
    """Lightweight history: the last KEEP_RUNS runs, and pending candidates
    that nothing has seen for PENDING_ITEM_RETENTION_DAYS."""
    with con.cursor() as cur:
        cur.execute("DELETE FROM community_discovery_runs WHERE status NOT IN ('QUEUED', 'RUNNING') "
                    "AND run_id NOT IN (SELECT run_id FROM community_discovery_runs "
                    "  ORDER BY run_id DESC LIMIT %s)", (KEEP_RUNS,))
        cur.execute("DELETE FROM community_discovery_items WHERE review_state = 'PENDING' "
                    "AND last_seen < now() - make_interval(days => %s)",
                    (PENDING_ITEM_RETENTION_DAYS,))


# --- storing candidates ----------------------------------------------------------------------------

def _merge_list(old: Sequence[str] | None, new: Iterable[str], keep: int) -> list[str]:
    merged = list(dict.fromkeys(list(new) + list(old or [])))
    return merged[:keep]


def store_hits(con, hits: Sequence[Hit], ctx: Context, run_id: int | None) -> dict[str, int]:
    """One staging row per public identity; repeated finds move last_seen."""
    groups: dict[str, dict[str, Any]] = {}
    skipped = 0
    for hit in hits:
        ident = identify(hit.url, hit.source_url)
        if ident is None:
            skipped += 1
            continue
        group = groups.setdefault(ident.key, {"identity": ident, "hits": []})
        group["hits"].append(hit)
    stats = {"new": 0, "updated": 0, "skipped": skipped}
    if not groups:
        return stats
    existing = {r["identity_key"]: r for r in _rows(
        con, "SELECT * FROM community_discovery_items WHERE identity_key = ANY(%s) FOR UPDATE",
        (list(groups),))}
    touched = []
    for key, group in groups.items():
        item_id, is_new = _upsert(con, group["identity"], group["hits"], ctx, existing.get(key), run_id)
        stats["new" if is_new else "updated"] += 1
        touched.append(item_id)
    for item_id in touched:
        reclassify(con, item_id, ctx)
    return stats


def _upsert(con, ident: Identity, hits: Sequence[Hit], ctx: Context,
            old: dict[str, Any] | None, run_id: int | None) -> tuple[int, bool]:
    text = " ".join(f"{h.title} {h.snippet} {h.source_name or ''}" for h in hits)
    # v0.89.2 (Section 6-8): a hit whose own text says it is someone else's
    # promotion (an ad-board post, a cross-posted class enrollment) never
    # feeds the HOST candidate's own genre or activity - only its real name
    # (source_name/cafe title, extracted from every hit below) is trusted,
    # since that is the cafe's own identity regardless of what got posted to
    # one of its boards. When literally every hit found is external, there
    # is no host evidence at all (external_only) and kind can only be
    # UNKNOWN - never the confident COMMUNITY a bare cafe/group platform
    # would otherwise imply (the CASINO RUEDA production failure).
    name, names = extract_name(ident, hits)
    candidate = (old or {}).get("candidate_name") or name
    # v0.89.3: name comparison in hit_is_external needs the host's own name
    # decided first - reordered from v0.89.2, where host_hits was computed
    # before candidate existed.
    external_flags = [hit_is_external(h, host_name=candidate) for h in hits]
    host_hits = [h for h, flag in zip(hits, external_flags) if not flag]
    external_only = not host_hits
    external_reason = next((f for f in external_flags if f), None)
    host_text = " ".join(f"{h.title} {h.snippet} {h.source_name or ''}" for h in host_hits)
    genres = detect_genres(f"{host_text} {candidate or ''}", ctx.genre_ids)
    genre_suppressed = genre_negative_context(f"{host_text} {candidate or ''}", ctx.genre_ids)
    region_id, region_text = detect_region(f"{text} {candidate or ''}", ctx.regions)
    if old and region_id is None and old.get("region_id"):
        region_id, region_text = old["region_id"], old.get("region_candidate")
    result = assess_activity(
        host_hits, ctx.today, previous_date=(old or {}).get("activity_date"),
        previous_confidence=(old or {}).get("activity_date_confidence") or UNKNOWN_DATE)
    activity, recent, activity_reasons = result.verdict, result.activity_date, result.reasons
    ident_parts = _split(ident.url)
    news_reason = _looks_like_news(_host(ident_parts) if ident_parts else "",
                                   [h.url for h in hits], host_text)
    kind, kind_reason = detect_kind(ident, candidate, host_text, ctx, external_only=external_only,
                                    external_reason=external_reason, news_reason=news_reason)
    # v0.89.3: the sticky-kind carryover below exists so a single weak,
    # uninformative hit (a bare photo, no text at all) never downgrades an
    # already-established kind. It must NOT apply when this hit was
    # confidently read as news/external-promotion evidence - that is a
    # positive, evidence-based negative finding, not an absence of signal,
    # and is exactly what Section 19 requires actually correcting a
    # previously-wrong COMMUNITY kind (the CASINO RUEDA case) instead of
    # leaving it stuck.
    if old and kind == KIND_UNKNOWN and not external_only and old.get("kind") != KIND_UNKNOWN:
        kind = old["kind"]
    venues = match_venues(f"{text} {candidate or ''}", region_id,
                          list(genres) + _item_genre_codes(con, (old or {}).get("item_id")),
                          ctx.venues)
    newest = max(hits, key=lambda h: (h.published or date.min))
    reasons = [f"platform: {ident.platform}", f"kind: {kind} - {kind_reason}"] \
        + [f"genre {code}: '{word}'" for code, word in genres.items()] \
        + [f"genre {code} not counted: {note}" for code, note in genre_suppressed.items()] \
        + ([f"region: {region_text}"] if region_text else []) + activity_reasons
    providers = sorted({h.provider for h in hits})
    queries = [h.query for h in hits]
    # Redacted again on the way in, whatever built the Hit: nothing personal is stored.
    values = {
        "platform": ident.platform, "community_url": ident.url,
        "title": clean_snippet(newest.title, TITLE_MAX),
        "candidate_name": candidate, "normalized_name": normalize_name(candidate),
        "snippet": clean_snippet(newest.snippet), "region_id": region_id,
        "region_candidate": region_text,
        "recent_activity_date": recent, "activity": activity, "kind": kind, "reasons": reasons,
    }
    # recent_activity_date/activity stay in sync with the new, provenance-aware
    # activity_date/confidence - existing code and tests that read the old
    # names keep working; activity_date is the one with real provenance.
    evidence = (result.evidence_url, result.evidence_title, result.evidence_source)
    with con.cursor() as cur:
        if old is None:
            cur.execute(
                "INSERT INTO community_discovery_items (identity_key, platform, community_url, title, "
                "  candidate_name, normalized_name, observed_names, snippet, region_id, "
                "  region_candidate, providers, queries, recent_activity_date, activity, "
                "  activity_date, activity_date_confidence, activity_evidence_url, "
                "  activity_evidence_title, activity_evidence_source, kind, reasons, last_run_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "  %s, %s, %s, %s) RETURNING item_id",
                (ident.key, values["platform"], values["community_url"], values["title"],
                 values["candidate_name"], values["normalized_name"], names, values["snippet"],
                 region_id, region_text, providers, _merge_list([], queries, KEEP_QUERIES),
                 recent, activity, result.activity_date, result.confidence, *evidence,
                 kind, reasons, run_id))
            item_id, is_new = cur.fetchone()[0], True
        else:
            cur.execute(
                "UPDATE community_discovery_items SET platform = %s, community_url = %s, title = %s, "
                "  candidate_name = %s, normalized_name = %s, observed_names = %s, snippet = %s, "
                "  region_id = %s, region_candidate = %s, providers = %s, queries = %s, "
                "  recent_activity_date = %s, activity = %s, activity_date = %s, "
                "  activity_date_confidence = %s, activity_evidence_url = %s, "
                "  activity_evidence_title = %s, activity_evidence_source = %s, kind = %s, "
                "  reasons = %s, last_seen = now(), seen_count = seen_count + 1, last_run_id = %s, "
                "  updated_at = now() WHERE item_id = %s",
                (values["platform"], values["community_url"], values["title"],
                 values["candidate_name"], values["normalized_name"],
                 _merge_list(old["observed_names"], names, KEEP_NAMES), values["snippet"],
                 region_id, region_text, sorted(set(old["providers"] or []) | set(providers)),
                 _merge_list(old["queries"], queries, KEEP_QUERIES), recent, activity,
                 result.activity_date, result.confidence, *evidence, kind, reasons, run_id,
                 old["item_id"]))
            item_id, is_new = old["item_id"], False
        for code, word in genres.items():
            cur.execute("INSERT INTO community_discovery_item_genres (item_id, genre_id, evidence) "
                        "VALUES (%s, %s, %s) ON CONFLICT (item_id, genre_id) DO NOTHING",
                        (item_id, ctx.genre_ids[code], word))
        for venue_id, match_kind, evidence in venues:
            cur.execute("INSERT INTO community_discovery_item_venues (item_id, venue_id, match_kind, "
                        "  evidence) VALUES (%s, %s, %s, %s) ON CONFLICT (item_id, venue_id) DO "
                        "UPDATE SET match_kind = CASE WHEN community_discovery_item_venues.match_kind "
                        "  = 'VENUE_MATCH' THEN 'VENUE_MATCH' ELSE EXCLUDED.match_kind END",
                        (item_id, venue_id, match_kind, evidence))
    return item_id, is_new


def _item_genre_codes(con, item_id: int | None) -> list[str]:
    if not item_id:
        return []
    return [r["code"] for r in _rows(con, "SELECT g.code FROM community_discovery_item_genres ig "
                                          "JOIN genres g USING (genre_id) WHERE ig.item_id = %s",
                                     (item_id,))]


def _regions_agree(a: int | None, b: int | None) -> bool:
    return a is None or b is None or a == b


def reclassify(con, item_id: int, ctx: Context) -> dict[str, Any]:
    """Classification and confidence from what is stored now, in a fixed order:
    already registered/linked or the same URL as a community -> existing; not a
    group -> not a community; same (specific) name as a community or an earlier
    candidate in a compatible region -> possible duplicate; then activity."""
    item = get_item(con, item_id)
    genres = item["genre_codes"]
    base = [r for r in (item["reasons"] or []) if not r.startswith("match: ")]
    existing_id = None
    duplicate_of = None
    extra: list[str] = []
    url_match = next((c for c in ctx.communities if c["url_key"] == item["identity_key"]), None)
    specific = not is_generic_name(item["normalized_name"])
    if item["review_state"] in DONE_STATES and item["registered_community_id"]:
        classification, existing_id = VERIFIED_EXISTING, item["registered_community_id"]
        extra.append(f"match: registered as community #{existing_id}")
    elif url_match:
        classification, existing_id = VERIFIED_EXISTING, url_match["community_id"]
        extra.append(f"match: same URL as community #{existing_id}")
    elif item["kind"] in NOT_COMMUNITY_KINDS:
        classification = NOT_A_COMMUNITY
    else:
        # v0.89.1: an operator who has looked at both and decided they are
        # genuinely different organisations clears this flag, and the
        # duplicate-matching below is skipped for good - it is judged on its
        # own evidence instead, never silently re-flagged by the next run.
        name_match = twin = None
        if not item.get("duplicate_cleared"):
            name_match = next((c for c in ctx.communities if specific and c["normalized"]
                               and c["normalized"] == item["normalized_name"]
                               and _regions_agree(c["region_id"], item["region_id"])), None)
            if not name_match and specific:
                # Still "earlier item is the anchor" - a deterministic,
                # order-independent-to-compute grouping key, not a claim that
                # the earlier one is the better candidate (list_duplicate_
                # groups()/the Admin screen rank the two on their actual
                # evidence, never on which was found first).
                twins = _rows(con, "SELECT item_id, region_id FROM community_discovery_items "
                                   "WHERE normalized_name = %s AND item_id < %s AND "
                                   "  duplicate_cleared = FALSE ORDER BY item_id",
                              (item["normalized_name"], item_id))
                twin = next((t for t in twins if _regions_agree(t["region_id"], item["region_id"])),
                           None)
        if name_match:
            classification, existing_id = POSSIBLE_DUPLICATE, name_match["community_id"]
            extra.append(f"match: same name as community #{existing_id}")
        elif twin:
            classification, duplicate_of = POSSIBLE_DUPLICATE, twin["item_id"]
            extra.append(f"match: same name as candidate #{duplicate_of}")
        elif item["activity"] == INACTIVE:
            classification = INACTIVE
        elif item["activity"] == STALE:
            classification = STALE
        elif item["kind"] == KIND_COMMUNITY and item["activity"] == ACTIVE:
            classification = VERIFIED_NEW
        else:
            classification = UNVERIFIED
    item.update(classification=classification)
    confidence = confidence_for(item, genres)
    with con.cursor() as cur:
        cur.execute("UPDATE community_discovery_items SET classification = %s, confidence = %s, "
                    "  existing_community_id = %s, duplicate_of_item_id = %s, reasons = %s "
                    "WHERE item_id = %s",
                    (classification, confidence, existing_id, duplicate_of, base + extra, item_id))
    item.update(confidence=confidence, existing_community_id=existing_id,
                duplicate_of_item_id=duplicate_of)
    return item


# --- reading candidates -----------------------------------------------------------------------------

_ITEM_SELECT = (
    "SELECT i.*, r.name AS region_name, ec.name AS existing_community_name, "
    "  rc.name AS registered_community_name, "
    "  ARRAY(SELECT g.code FROM community_discovery_item_genres ig JOIN genres g USING (genre_id) "
    "        WHERE ig.item_id = i.item_id ORDER BY g.code) AS genre_codes, "
    "  ARRAY(SELECT iv.venue_id FROM community_discovery_item_venues iv "
    "        WHERE iv.item_id = i.item_id ORDER BY iv.match_kind DESC, iv.venue_id) AS venue_ids, "
    "  ARRAY(SELECT v.name FROM community_discovery_item_venues iv JOIN venues v USING (venue_id) "
    "        WHERE iv.item_id = i.item_id ORDER BY iv.match_kind DESC, iv.venue_id) AS venue_names, "
    "  ARRAY(SELECT iv.match_kind FROM community_discovery_item_venues iv "
    "        WHERE iv.item_id = i.item_id ORDER BY iv.match_kind DESC, iv.venue_id) AS venue_kinds "
    "FROM community_discovery_items i "
    "LEFT JOIN regions r ON r.region_id = i.region_id "
    "LEFT JOIN communities ec ON ec.community_id = i.existing_community_id "
    "LEFT JOIN communities rc ON rc.community_id = i.registered_community_id"
)


def get_item(con, item_id: int) -> dict[str, Any] | None:
    rows = _rows(con, _ITEM_SELECT + " WHERE i.item_id = %s", (item_id,))
    return rows[0] if rows else None


# v0.89.1 review queues (Section 17) - each a shorthand for a combination of
# review_state/classification/relationship that would otherwise need several
# filter dropdowns set at once.
QUEUE_NEEDS_REVIEW = "needs_review"
QUEUE_DUPLICATE = "duplicate"
QUEUE_NEW_EVIDENCE = "new_evidence"
QUEUE_STALE = "stale"
QUEUE_UNVERIFIED = "unverified"
QUEUE_REJECTED = "rejected"
QUEUE_APPROVED = "approved"
QUEUES = (QUEUE_NEEDS_REVIEW, QUEUE_DUPLICATE, QUEUE_NEW_EVIDENCE, QUEUE_STALE, QUEUE_UNVERIFIED,
         QUEUE_REJECTED, QUEUE_APPROVED)
QUEUE_LABELS = {
    QUEUE_NEEDS_REVIEW: "검토 필요", QUEUE_DUPLICATE: "중복 의심", QUEUE_NEW_EVIDENCE: "새 근거 발견",
    QUEUE_STALE: "오래된 자료", QUEUE_UNVERIFIED: "확인 필요", QUEUE_REJECTED: "제외됨",
    QUEUE_APPROVED: "등록/연결됨",
}
# Sentinel for "no region resolved at all" - kept separate from a real region
# code so a filter can ask for exactly that (Section 20/21).
REGION_UNRESOLVED = "UNRESOLVED"

_NEW_EVIDENCE_SQL = ("i.review_state IN ('HELD', 'REJECTED') AND i.reviewed_at IS NOT NULL "
                     "AND i.last_seen > i.reviewed_at")


def list_items(con, *, provider: str | None = None, genre: str | None = None,
               region: str | None = None, classification: str | None = None,
               review_state: str | None = None, queue: str | None = None, limit: int = 50,
               offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    where, params = [], []
    if provider:
        where.append("%s = ANY(i.providers)")
        params.append(provider)
    if genre:
        where.append("EXISTS (SELECT 1 FROM community_discovery_item_genres ig JOIN genres g "
                     "USING (genre_id) WHERE ig.item_id = i.item_id AND g.code = %s)")
        params.append(genre)
    if region == REGION_UNRESOLVED:
        where.append("i.region_id IS NULL")
    elif region:
        where.append("i.region_id = (SELECT region_id FROM regions WHERE code = %s)")
        params.append(region)
    if classification:
        where.append("i.classification = %s")
        params.append(classification)
    if review_state:
        where.append("i.review_state = %s")
        params.append(review_state)
    if queue == QUEUE_NEEDS_REVIEW:
        where.append("i.review_state IN ('PENDING', 'HELD')")
    elif queue == QUEUE_DUPLICATE:
        where.append("(i.classification = 'POSSIBLE_DUPLICATE' OR i.duplicate_of_item_id IS NOT NULL "
                     "OR EXISTS (SELECT 1 FROM community_discovery_items t "
                     "           WHERE t.duplicate_of_item_id = i.item_id))")
    elif queue == QUEUE_NEW_EVIDENCE:
        where.append(_NEW_EVIDENCE_SQL)
    elif queue == QUEUE_STALE:
        where.append("i.classification = 'STALE'")
    elif queue == QUEUE_UNVERIFIED:
        where.append("i.classification = 'UNVERIFIED'")
    elif queue == QUEUE_REJECTED:
        where.append("i.review_state = 'REJECTED'")
    elif queue == QUEUE_APPROVED:
        where.append("i.review_state IN ('APPROVED', 'LINKED')")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = _rows(con, "SELECT count(*) AS n FROM community_discovery_items i" + clause, params)[0]["n"]
    # needs_review sorts by evidence quality (Section 18) - confirmed dates
    # first, then the most recently and most confidently active - never by
    # item_id, and never a hint that it should be auto-approved.
    if queue == QUEUE_NEEDS_REVIEW:
        order = (" ORDER BY CASE i.activity_date_confidence WHEN 'CONFIRMED' THEN 0 ELSE 1 END, "
                "  CASE i.confidence WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END, "
                "  i.activity_date DESC NULLS LAST, i.first_seen DESC, i.item_id DESC")
    else:
        order = (" ORDER BY CASE i.review_state WHEN 'PENDING' THEN 0 WHEN 'HELD' THEN 1 ELSE 2 END, "
                "  CASE i.confidence WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END, "
                "  CASE WHEN i.classification = 'NOT_A_COMMUNITY' THEN 1 ELSE 0 END, "
                "  i.last_seen DESC, i.item_id DESC")
    rows = _rows(con, _ITEM_SELECT + clause + order + " LIMIT %s OFFSET %s",
                 params + [int(limit), int(offset)])
    return rows, total


def has_new_evidence(item: dict[str, Any]) -> bool:
    """A HELD/REJECTED candidate that a later run has seen again since the
    operator's own review - never changes review_state by itself, only says
    "look again, something moved"."""
    return bool(item.get("review_state") in (HELD, REJECTED) and item.get("reviewed_at")
               and item.get("last_seen") and item["last_seen"] > item["reviewed_at"])


# --- review actions ----------------------------------------------------------------------------------

def _locked_item(con, item_id: int) -> dict[str, Any]:
    rows = _rows(con, "SELECT * FROM community_discovery_items WHERE item_id = %s FOR UPDATE", (item_id,))
    if not rows:
        raise DiscoveryError(f"후보 {item_id}을(를) 찾을 수 없습니다")
    return rows[0]


def registration_defaults(item: dict[str, Any], genre_ids: dict[str, int]) -> dict[str, Any]:
    """The Community form, pre-filled from the evidence for the operator to check."""
    from .directory import public_link  # noqa: PLC0415

    return {
        "name": item.get("candidate_name") or "", "region_id": item.get("region_id") or "",
        "description": "", "homepage_url": public_link(item.get("community_url")) or "",
        "notes": "", "enabled": "1",
        "genre_ids": [genre_ids[c] for c in item.get("genre_codes") or [] if c in genre_ids],
        "venue_ids": [v for v, k in zip(item.get("venue_ids") or [], item.get("venue_kinds") or [])
                      if k == VENUE_MATCH],
    }


def register_item(con, item_id: int, fields: dict[str, Any], *, reviewer: str = "admin") -> dict[str, Any]:
    """Register a candidate as a Community through the existing contract, and
    mark the candidate - both or neither."""
    with con.transaction():
        item = _locked_item(con, item_id)
        if item["review_state"] in DONE_STATES:
            raise DiscoveryError("이미 동호회로 등록되었거나 기존 동호회와 연결된 후보입니다")
        community = communities.create_community(con, fields, reviewer=reviewer)
        with con.cursor() as cur:
            cur.execute("UPDATE community_discovery_items SET review_state = 'APPROVED', "
                        "  registered_community_id = %s, existing_community_id = %s, "
                        "  classification = 'VERIFIED_EXISTING', confidence = 'HIGH', "
                        "  reviewed_by = %s, reviewed_at = now(), updated_at = now() "
                        "WHERE item_id = %s",
                        (community["community_id"], community["community_id"], reviewer, item_id))
    return community


def link_item(con, item_id: int, community_id: Any, *, reviewer: str = "admin") -> dict[str, Any]:
    cid = parse_id(community_id, what="동호회")
    if cid is None:
        raise DiscoveryError("동호회: 필수 항목입니다")
    with con.transaction():
        item = _locked_item(con, item_id)
        if item["review_state"] == APPROVED:
            raise DiscoveryError("이미 동호회로 등록된 후보입니다")
        community = communities.get_community(con, cid)
        if community is None:
            raise DiscoveryError("동호회: 존재하지 않는 항목입니다")
        with con.cursor() as cur:
            cur.execute("UPDATE community_discovery_items SET review_state = 'LINKED', "
                        "  registered_community_id = %s, existing_community_id = %s, "
                        "  classification = 'VERIFIED_EXISTING', confidence = 'HIGH', "
                        "  reviewed_by = %s, reviewed_at = now(), updated_at = now() "
                        "WHERE item_id = %s", (cid, cid, reviewer, item_id))
    return community


def set_review_state(con, item_id: int, state: str, *, reviewer: str = "admin") -> dict[str, Any]:
    if state not in (HELD, REJECTED, PENDING):
        raise DiscoveryError(f"알 수 없는 처리입니다: {state}")
    with con.transaction():
        item = _locked_item(con, item_id)
        if item["review_state"] in DONE_STATES:
            raise DiscoveryError("이미 동호회로 등록되었거나 연결된 후보는 보류/제외할 수 없습니다")
        with con.cursor() as cur:
            cur.execute("UPDATE community_discovery_items SET review_state = %s, reviewed_by = %s, "
                        "  reviewed_at = now(), updated_at = now() WHERE item_id = %s",
                        (state, reviewer, item_id))
    return {**item, "review_state": state}


def confirm_activity_evidence(con, item_id: int, *, activity_date: Any, evidence_url: str | None = None,
                              evidence_title: str | None = None,
                              reviewer: str = "admin") -> dict[str, Any]:
    """Record that an operator actually opened the page and found this date
    themselves (Section 6/15/16) - the only way ``activity_date_confidence``
    ever becomes CONFIRMED. Recomputes the ACTIVE/STALE verdict against
    *today* from that date and reclassifies, but never touches review_state:
    a HELD or REJECTED candidate stays exactly that until the operator
    separately reopens it - this only upgrades the evidence they see.
    """
    when = as_date(activity_date)
    if when is None:
        raise DiscoveryError("활동 날짜: 올바른 날짜가 아닙니다 (YYYY-MM-DD)")
    url = events_api.valid_public_url((evidence_url or "").strip()) if evidence_url else None
    title = clean_snippet(evidence_title or "", TITLE_MAX) or None
    with con.transaction():
        item = _locked_item(con, item_id)
        today = date.today()
        verdict = STALE if when < months_ago(today, ACTIVE_WINDOW_MONTHS) else ACTIVE
        reason = (f"activity: {when.isoformat()} (관리자 확인)" if verdict == ACTIVE else
                 f"latest confirmed activity {when.isoformat()} (over {ACTIVE_WINDOW_MONTHS} months old)")
        base = [r for r in (item["reasons"] or []) if not r.startswith("activity:")
               and not r.startswith("latest ") and not r.startswith("no dated")
               and not r.startswith("a date exists")]
        with con.cursor() as cur:
            cur.execute(
                "UPDATE community_discovery_items SET activity_date = %s, "
                "  activity_date_confidence = 'CONFIRMED', activity_evidence_url = %s, "
                "  activity_evidence_title = %s, activity_evidence_source = 'ADMIN', "
                "  recent_activity_date = %s, activity = %s, reasons = %s, updated_at = now() "
                "WHERE item_id = %s",
                (when, url, title, when, verdict, base + [reason], item_id))
        ctx = load_context(con, today)
    return reclassify(con, item_id, ctx)


def mark_independent(con, item_id: int, *, reviewer: str = "admin") -> dict[str, Any]:
    """"서로 다른 Community" (Section 11): an operator has looked at a
    POSSIBLE_DUPLICATE pair and decided the two are genuinely different
    organisations, not one hiding behind the other. Judged on its own
    evidence from here on; a future run never re-flags it against this same
    twin (duplicate_cleared), though a *different* twin can still surface."""
    with con.transaction():
        item = _locked_item(con, item_id)
        if item["review_state"] in DONE_STATES:
            raise DiscoveryError("이미 동호회로 등록되었거나 연결된 후보입니다")
        with con.cursor() as cur:
            cur.execute("UPDATE community_discovery_items SET duplicate_cleared = TRUE, "
                        "  updated_at = now() WHERE item_id = %s", (item_id,))
        ctx = load_context(con, date.today())
    return reclassify(con, item_id, ctx)


# --- duplicate groups (v0.89.1, Section 8-11) ------------------------------------------------

def _duplicate_rank(item: dict[str, Any]) -> tuple:
    """Lower sorts first = the recommended candidate to review first
    (Section 10) - never an automatic choice, only a display order:
    a confirmed date beats an inferred one, active beats stale beats
    unverified, a more recent date beats an older one, HIGH confidence beats
    MEDIUM beats LOW, having any public URL beats having none, and more
    recorded evidence beats less."""
    confidence_rank = {CONFIRMED: 0, INFERRED: 1, UNKNOWN_DATE: 2}
    activity_rank = {ACTIVE: 0, STALE: 1, UNVERIFIED: 2, INACTIVE: 3}
    strength_rank = {HIGH: 0, MEDIUM: 1, LOW: 2}
    activity_date = item.get("activity_date")
    return (
        confidence_rank.get(item.get("activity_date_confidence"), 2),
        activity_rank.get(item.get("activity"), 2),
        -(activity_date.toordinal() if activity_date else 0),
        strength_rank.get(item.get("confidence"), 2),
        0 if public_link(item.get("community_url")) else 1,
        -len(item.get("reasons") or []),
        item["item_id"],
    )


def _group_members(con, root_id: int, seen: set[int]) -> list[int]:
    """Every item connected to ``root_id`` through duplicate_of_item_id, in
    either direction, transitively - a chain of three or more stays one
    group (Section 9: "3개 이상도 지원")."""
    if root_id in seen:
        return []
    seen.add(root_id)
    members = [root_id]
    with con.cursor() as cur:
        cur.execute("SELECT duplicate_of_item_id FROM community_discovery_items WHERE item_id = %s",
                    (root_id,))
        row = cur.fetchone()
        if row and row[0]:
            members.extend(_group_members(con, row[0], seen))
        cur.execute("SELECT item_id FROM community_discovery_items WHERE duplicate_of_item_id = %s",
                    (root_id,))
        for (other_id,) in cur.fetchall():
            members.extend(_group_members(con, other_id, seen))
    return members


def duplicate_group(con, item_id: int) -> list[dict[str, Any]]:
    """This candidate and every other candidate linked to it as a possible
    duplicate, ranked (never re-ordered by picking a "winner" - see
    _duplicate_rank). Empty when the candidate has no such link."""
    ids = sorted(set(_group_members(con, item_id, set())) - {None})
    if len(ids) <= 1:
        return []
    items = [get_item(con, i) for i in ids]
    items = [i for i in items if i is not None]
    items.sort(key=_duplicate_rank)
    return items


def list_duplicate_groups(con) -> list[list[dict[str, Any]]]:
    """Every duplicate group currently on file, each already ranked. Used by
    the Admin screen so a strong candidate is shown next to the weaker twin
    it might otherwise be read as "just" a duplicate of, not hidden behind
    it (Section 8-9)."""
    with con.cursor() as cur:
        cur.execute("SELECT DISTINCT duplicate_of_item_id FROM community_discovery_items "
                    "WHERE duplicate_of_item_id IS NOT NULL")
        roots = [r[0] for r in cur.fetchall()]
    seen: set[int] = set()
    groups = []
    for root_id in roots:
        if root_id in seen:
            continue
        group = duplicate_group(con, root_id)
        seen.update(i["item_id"] for i in group)
        if group:
            groups.append(group)
    return groups


def register_item_and_link_group(con, item_id: int, fields: dict[str, Any],
                                 sibling_item_ids: Sequence[int], *,
                                 reviewer: str = "admin") -> dict[str, Any]:
    """"이 후보를 대표로 사용" (Section 11): register ``item_id`` as the new
    Community exactly as register_item() would, then link every candidate in
    ``sibling_item_ids`` to that same Community in the same action - the
    admin picks which one is the representative; nothing here decides that
    on its own. A sibling already APPROVED/LINKED is left untouched rather
    than raising, so a partially-reviewed group never blocks the rest."""
    community = register_item(con, item_id, fields, reviewer=reviewer)
    linked = []
    for sibling_id in sibling_item_ids:
        if sibling_id == item_id:
            continue
        sibling = get_item(con, sibling_id)
        if sibling is None or sibling["review_state"] in DONE_STATES:
            continue
        link_item(con, sibling_id, str(community["community_id"]), reviewer=reviewer)
        linked.append(sibling_id)
    return {"community": community, "linked": linked}
