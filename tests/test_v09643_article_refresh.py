"""v0.96.43 - an article DanceMate already fetched is re-checked, and a
protected item is put in front of a person instead of being guessed at.

The defect, as found on Production fd93625 (v0.96.42): a fetched article body
was settled for good. `acquisition.SETTLED` holds FETCHED_FULL/PARTIAL,
`next_attempt_at()` answers None for them and `due_for_acquisition()` never
selects them again, so a publisher's edit to the post *body* was never read -
the discovery record (search title, snippet) could stay the same, and
v0.96.42's input signature compares only what was stored. 358 Daum and 505
danceinfo.net bodies sat that way, 41 of them feeding an Event that has not
ended.

Every test drives v0.96.42's own pipeline (`tests.test_v09642_source_revision.
Pipe`: intake, engine-ingest, engine-reprocess, event-normalization, the real
engine) plus the new re-check, `article_refresh.run()`, over a fake web server
reached through the real `acquisition.fetch()` - so the article region a Daum
page is read from, the hashing and the redaction are the production ones. No
request leaves the test, nothing is committed, and ENGINE_VERSION never moves.
"""

from __future__ import annotations

import email.message
import io
import urllib.error
from datetime import date, datetime, timedelta, timezone

import pytest

from runtime import (
    acquisition,
    article_refresh,
    config,
    content_store,
    db,
    duplicates,
    engine_ingest,
    image_fetch,
    normalization,
)
from tests.conftest import register_venue
from tests.test_v09642_source_revision import (  # noqa: F401 - pytest fixtures
    _as_legacy,
    _intercept_engine,
    _yield,
    client,
    pipe,
)


# --- a fake web server, reached through the real acquisition.fetch() ----------

def _headers(values: dict[str, str]) -> email.message.Message:
    message = email.message.Message()
    for key, value in values.items():
        message[key] = value
    return message


class _Resp(io.BytesIO):
    def __init__(self, body: bytes, url: str, headers: dict[str, str]):
        super().__init__(body)
        self.status = 200
        self._url = url
        self.headers = _headers({"Content-Type": "text/html; charset=utf-8", **headers})

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def daum_page(body: str, *, title: str = "글", nav: str = "카페 메뉴",
              footer: str = "푸터", ad: str = "광고") -> str:
    """Daum's mobile article page as acquisition reads it: the post sits
    between the font-size control and the search footer."""
    return (f'<html><head><meta property="og:title" content="{title}"></head><body>'
            f"<nav>{nav}</nav><aside>{ad}</aside>"
            f"<div>글자크기 크게 가</div><div class='article'>{body}</div>"
            f"<div>다음검색</div><footer>{footer}</footer></body></html>")


class Server:
    def __init__(self):
        self.pages: dict[str, dict] = {}
        self.requests: list[tuple[str, dict]] = []
        self.disallowed: set[str] = set()
        self.before: dict[str, object] = {}

    def page(self, url: str, html: str, *, etag: str | None = None,
             honour_validators: bool = False) -> None:
        self.pages[url] = {"html": html, "etag": etag, "honour": honour_validators,
                           "error": None}

    def fail(self, url: str, code: int, *, retry_after: str | None = None) -> None:
        self.pages.setdefault(url, {"html": "", "etag": None, "honour": False})
        self.pages[url]["error"] = (code, retry_after)

    def robots(self, url: str, *, user_agent: str = "DanceMate") -> bool:
        return url not in self.disallowed

    def open(self, request, timeout=None):
        url = request.full_url
        headers = {k.lower(): v for k, v in request.header_items()}
        self.requests.append((url, headers))
        if url in self.before:
            self.before.pop(url)()
        page = self.pages.get(url)
        if page is None:
            raise AssertionError(f"unexpected fetch: {url}")
        if page["error"]:
            code, retry_after = page["error"]
            if code == 0:
                raise urllib.error.URLError("timed out")
            raise urllib.error.HTTPError(
                url, code, "error", _headers({"Retry-After": retry_after} if retry_after else {}),
                io.BytesIO(b""))
        if page["honour"] and page["etag"] and headers.get("if-none-match") == page["etag"]:
            raise urllib.error.HTTPError(url, 304, "Not Modified",
                                         _headers({"ETag": page["etag"]}), io.BytesIO(b""))
        extra = {"ETag": page["etag"]} if page["etag"] else {}
        return _Resp(page["html"].encode("utf-8"), url, extra)

    def fetcher(self, url: str, headers: dict[str, str]):
        return acquisition.fetch(url, opener=self.open, headers=headers)


def _noop(_seconds):
    return None


class Art:
    """The v0.96.42 pipe plus a web server and the re-check."""

    def __init__(self, pipe, server):
        self.pipe, self.server = pipe, server
        self.last: dict = {}

    def article(self, n: int, body: str, *, title: str, age: timedelta = timedelta(days=4),
                method_page=None) -> int:
        """A Daum post collected, its article fetched, read, and then left
        alone for ``age`` - the state every Production article is in."""
        url = f"https://cafe.daum.net/v43{self.pipe.unique}/{n}"
        mobile = f"https://m.cafe.daum.net/v43{self.pipe.unique}/{n}"
        record = {"source_url": url, "title": title, "body": f"{title} 요약",
                  "acquisition_quality": "METADATA_ONLY"}
        assert self.pipe.collect(record) == "NEW"
        item_id = self.pipe.item_id(url)
        self.server.page(mobile, method_page or daum_page(body, title=title))
        outcome = acquisition.fetch(url, opener=self.server.open)
        assert outcome.status == acquisition.FETCHED_FULL, outcome
        content_store.record_outcome(self.pipe.pg, item_id, outcome)
        self.pipe.tick()
        self.age(item_id, age)
        self.server.requests.clear()
        return item_id

    def mobile(self, item_id: int) -> str:
        return self.pipe.content(item_id)["fetched_url"]

    def age(self, item_id: int, by: timedelta) -> None:
        """Move every clock this item carries back by ``by``."""
        with self.pipe.pg.cursor() as cur:
            cur.execute(
                "UPDATE source_item_content SET fetched_at = fetched_at - %(by)s, "
                "  first_attempt_at = first_attempt_at - %(by)s, "
                "  last_attempt_at = last_attempt_at - %(by)s, "
                "  reprocessed_at = reprocessed_at - %(by)s, "
                "  refresh_attempted_at = refresh_attempted_at - %(by)s, "
                "  refresh_checked_at = refresh_checked_at - %(by)s, "
                "  refresh_next_at = refresh_next_at - %(by)s "
                "WHERE source_item_id = %(id)s", {"by": by, "id": item_id})
            cur.execute("UPDATE source_items SET collected_at = collected_at - %(by)s "
                        "WHERE source_item_id = %(id)s", {"by": by, "id": item_id})

    def revise(self, item_id: int, body: str, *, title: str = "글", **page) -> None:
        self.server.page(self.mobile(item_id), daum_page(body, title=title, **page))

    def refresh(self, **kwargs) -> dict:
        self.last = article_refresh.run(self.pipe.pg, fetcher=self.server.fetcher,
                                        sleep=_noop, **kwargs)
        return self.last

    def state(self, item_id: int) -> dict:
        return article_refresh.state(article_refresh.inspect(self.pipe.pg, item_id))

    def log(self, item_id: int) -> list[tuple]:
        with self.pipe.pg.cursor() as cur:
            cur.execute("SELECT purpose, refresh_result, outcome FROM content_fetch_log "
                        "WHERE source_item_id = %s ORDER BY content_fetch_id", (item_id,))
            return cur.fetchall()


@pytest.fixture
def art(pipe, monkeypatch):
    with pipe.pg.cursor() as cur:
        cur.execute("UPDATE sources SET enabled = true WHERE source_id = %s", (pipe.source_id,))
    server = Server()
    monkeypatch.setattr(acquisition, "robots_allows", server.robots)
    return Art(pipe, server)


def _clock(event) -> tuple[str, str]:
    return str(event["start_time"]), str(event["end_time"])


def _body(day: str, start: str, end: str, *, place: str = "스튜디오 오초",
          fee: str = "10,000원", extra: str = "") -> str:
    """A post body long enough to be a full article (>= 120 characters)."""
    return (f"이번 주 토요 밀롱가 안내입니다. 일시: {day} {start}~{end} "
            f"장소: {place} 입장료 {fee} 많은 참여 부탁드립니다. {extra} "
            "음악은 클래식 탱고 위주로 진행되며 초보자도 환영합니다. 편한 신발을 준비해 주세요.")


FAR = "2027년 3월 13일"
FAR_TITLE = "[홍대] 3월 13일 토요 밀롱가"


# --- the defect -----------------------------------------------------------------

def test_a_settled_article_used_to_be_unreachable_by_the_acquisition_queue(art):
    """Root cause, pinned: nothing in the first-acquisition path ever selects
    a fetched article again, however long ago it was fetched."""
    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE,
                          age=timedelta(days=30))
    assert acquisition.FETCHED_FULL in acquisition.SETTLED
    assert acquisition.next_attempt_at(acquisition.FETCHED_FULL, None, 1) is None
    queued = {r["source_item_id"] for r in content_store.due_for_acquisition(art.pipe.pg,
                                                                             limit=1000)}
    assert item_id not in queued


def test_the_versions_do_not_move():
    assert config.DEFAULT_ENGINE_VERSION == "1.18"  # v0.96.56: time-role bump
    assert normalization.NORMALIZATION_VERSION == "3"


# --- revisions reach the event --------------------------------------------------

def test_a_body_time_revision_reaches_the_event_with_its_identity(art):
    """The brief's own example: 20:00~23:00 becomes 21:00~00:00 in the post
    body, the aggregator's title and snippet do not move at all."""
    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    before = art.pipe.event(item_id)
    assert _clock(before) == ("20:00:00", "23:00:00")
    signature = content_store.input_signature(art.pipe.pg, item_id)

    art.revise(item_id, _body(FAR, "21:00", "00:00"))
    assert art.refresh()[article_refresh.REVISED] == 1
    assert art.state(item_id)["state"] == article_refresh.ARTICLE_CHANGED_REEXTRACTION_PENDING
    assert content_store.input_signature(art.pipe.pg, item_id) != signature
    assert art.pipe.queued(item_id)

    art.pipe.tick()
    assert art.pipe.last["reprocess"]["reprocessed"] == 1
    after = art.pipe.event(item_id)
    assert after["event_id"] == before["event_id"]
    assert after["candidate_id"] == before["candidate_id"]
    assert _clock(after) == ("21:00:00", "00:00:00")
    assert after["end_day_offset"] == 1
    assert not art.pipe.queued(item_id)
    assert art.state(item_id)["state"] == article_refresh.ARTICLE_CURRENT
    assert art.log(item_id)[-1][:2] == ("REFRESH", article_refresh.REVISED)


def test_a_body_venue_revision_moves_the_venue_within_the_venue_master(art):
    first = register_venue(art.pipe.pg, f"Hall A {art.pipe.unique}")
    second = register_venue(art.pipe.pg, f"Hall B {art.pipe.unique}")
    item_id = art.article(1, _body(FAR, "20:00", "23:00", place=first["name"]),
                          title=FAR_TITLE)
    assert art.pipe.event(item_id)["venue_id"] == first["venue_id"]
    with art.pipe.pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM venues")
        venues = cur.fetchone()[0]
    art.revise(item_id, _body(FAR, "20:00", "23:00", place=second["name"]))
    art.refresh()
    art.pipe.tick()
    after = art.pipe.event(item_id)
    assert after["venue_id"] == second["venue_id"]
    with art.pipe.pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM venues")
        assert cur.fetchone()[0] == venues, "no venue is invented"


def test_a_title_and_body_revised_together_are_one_re_extraction(art):
    """The discovery title moves (v0.96.42's path) and the article body moves
    (this release's) before the engine runs: one read, both changes."""
    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    before = art.pipe.event(item_id)
    url = f"https://cafe.daum.net/v43{art.pipe.unique}/1"
    new_title = "[홍대] 3월 13일 토요 밀롱가 (DJ 바비)"
    assert art.pipe.collect({"source_url": url, "title": new_title, "body": "요약 변경",
                             "acquisition_quality": "METADATA_ONLY"}) == "REVISED"
    art.revise(item_id, _body(FAR, "20:30", "23:30"))
    art.refresh()
    art.pipe.tick()
    assert art.pipe.last["reprocess"]["reprocessed"] == 1
    after = art.pipe.event(item_id)
    assert after["event_id"] == before["event_id"]
    assert after["event_name"] == new_title
    assert _clock(after) == ("20:30:00", "23:30:00")


def test_a_fee_revision_reaches_the_event(art):
    item_id = art.article(1, _body(FAR, "20:00", "23:00", fee="10,000원"), title=FAR_TITLE)
    art.revise(item_id, _body(FAR, "20:00", "23:00", fee="15,000원"))
    art.refresh()
    art.pipe.tick()
    assert art.pipe.event(item_id)["fee"] == 15000


def test_a_programme_revision_rebuilds_its_nights_from_the_new_body(art):
    """Two dated nights become two different ones: the nights follow the
    article, the item is read once."""
    body = ("주간 밀롱가 일정 안내입니다. 2027.03.12 (금) 20:00~23:00 금요 밀롱가 / "
            "2027.03.13 (토) 20:00~23:30 토요 밀롱가 장소: 스튜디오 오초 입장료 10,000원. "
            "음악은 클래식 탱고 위주로 진행되며 초보자도 환영합니다. 편한 신발을 준비해 주세요.")
    item_id = art.article(1, body, title="[홍대] 2027년 3월 주간 밀롱가")
    def keyed(events):
        return {(str(e["event_date"]), str(e["start_time"])):
                (e["event_name"], str(e["end_time"]), e["venue_text"]) for e in events}

    nights = keyed(art.pipe.events(item_id))
    assert set(nights) == {("2027-03-12", "20:00:00"), ("2027-03-13", "20:00:00")}
    revised = body.replace("2027.03.13 (토) 20:00~23:30 토요", "2027.03.14 (일) 19:00~22:00 일요")
    art.revise(item_id, revised)
    art.refresh()
    art.pipe.tick()
    assert art.pipe.last["reprocess"]["reprocessed"] == 1
    after = keyed(art.pipe.events(item_id))
    assert set(after) == {("2027-03-12", "20:00:00"), ("2027-03-14", "19:00:00")}
    # A multi-night post is re-persisted whole on any re-read (the 1->N
    # contract every engine bump and v0.96.42 revision already follows):
    # the unchanged night is the same night by (item, date, title), fields
    # and all, under a re-issued event_id.
    assert after[("2027-03-12", "20:00:00")] == nights[("2027-03-12", "20:00:00")]


def test_a_festival_period_is_never_derived_from_article_prose(art):
    """v0.96.41's contract holds: an Event's end_date comes only from a
    structured calendar's own stated period, never from a range in prose. A
    revised article festival range is read (the item is re-extracted) and
    still carries no end_date."""
    body = ("2027 봄 탱고 페스티벌 안내. 기간 2027년 3월 12일 ~ 3월 14일, 첫날 20:00 오프닝 "
            "밀롱가. 장소: 스튜디오 오초 입장료 30,000원 많은 참여 부탁드립니다. 워크숍과 "
            "밀롱가가 함께 진행됩니다. 편한 신발을 준비해 주세요.")
    item_id = art.article(1, body, title="[홍대] 2027 봄 탱고 페스티벌")
    art.revise(item_id, body.replace("3월 14일", "3월 15일"))
    assert art.refresh()[article_refresh.REVISED] == 1
    art.pipe.tick()
    assert art.pipe.last["reprocess"]["reprocessed"] == 1
    assert all(e["end_date"] is None for e in art.pipe.events(item_id))


def test_a_cancellation_notice_is_read_like_any_revision(art):
    """A body edited to say the night is cancelled goes through the same
    re-read; whatever the engine makes of the notice is what the item says,
    and nothing about the re-check itself decides it."""
    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    before = art.pipe.event(item_id)
    art.revise(item_id, "[공지] 3월 13일 토요 밀롱가는 사정으로 휴강합니다. 다음 주에 뵙겠습니다. "
               "이번 주 토요 밀롱가는 열리지 않습니다. 양해 부탁드립니다. 문의는 카페 쪽지로 "
               "주세요. 감사합니다. 다음 일정은 추후 공지하겠습니다.")
    assert art.refresh()[article_refresh.REVISED] == 1
    art.pipe.tick()
    assert art.pipe.last["reprocess"]["reprocessed"] == 1
    events = art.pipe.events(item_id)
    assert [e["event_id"] for e in events] in ([], [before["event_id"]])
    assert art.pipe.content(item_id)["extraction_outcome"] == content_store.OUTCOME_EXTRACTED


# --- nothing changes when nothing changed -----------------------------------------

def _frozen(art, item_id) -> tuple:
    content = art.pipe.content(item_id)
    event = art.pipe.event(item_id)
    return (content["content_hash"], content["fetched_at"], content["extracted_text"],
            content["title"], content["updated_at"], content["extracted_input_signature"],
            content["reprocessed_at"], event["event_id"], event["updated_at"],
            event["normalized_at"])


def test_an_unchanged_article_is_checked_and_nothing_else_moves(art):
    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    signature = content_store.input_signature(art.pipe.pg, item_id)
    frozen = _frozen(art, item_id)
    assert art.refresh()[article_refresh.UNCHANGED] == 1
    assert content_store.input_signature(art.pipe.pg, item_id) == signature
    assert not art.pipe.queued(item_id)
    art.pipe.tick()
    assert art.pipe.last["reprocess"]["reprocessed"] == 0
    assert _frozen(art, item_id) == frozen
    content = art.pipe.content(item_id)
    assert content["refresh_outcome"] == article_refresh.UNCHANGED
    assert content["refresh_checked_at"] is not None
    assert art.state(item_id)["state"] == article_refresh.ARTICLE_CURRENT
    assert art.refresh()["attempted"] == 0, "checked: not due again until its interval"


def test_page_furniture_outside_the_article_is_not_a_revision(art):
    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    frozen = _frozen(art, item_id)
    art.revise(item_id, _body(FAR, "20:00", "23:00"), nav="새 메뉴 2027", ad="다른 광고 50% 할인",
               footer="방문자 12345 2027-03-01 갱신")
    assert art.refresh()[article_refresh.UNCHANGED] == 1
    art.pipe.tick()
    assert _frozen(art, item_id) == frozen


def test_a_304_is_honoured_when_the_server_supports_it(art):
    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    art.server.page(art.mobile(item_id), daum_page(_body(FAR, "20:00", "23:00")),
                    etag='"v1"', honour_validators=True)
    assert art.refresh()[article_refresh.UNCHANGED] == 1
    assert "if-none-match" not in art.server.requests[-1][1], "no validator was held yet"
    assert art.pipe.content(item_id)["refresh_etag"] == '"v1"'
    frozen = _frozen(art, item_id)
    art.age(item_id, timedelta(days=4))
    assert art.refresh()[article_refresh.NOT_MODIFIED] == 1
    assert art.server.requests[-1][1]["if-none-match"] == '"v1"'
    art.pipe.tick()
    assert art.pipe.last["reprocess"]["reprocessed"] == 0
    content = art.pipe.content(item_id)
    assert content["content_hash"] == frozen[0] and content["extracted_text"] == frozen[2]


def test_a_server_that_ignores_validators_is_compared_by_hash(art):
    """danceinfo.net's measured behaviour: an ETag, and 200 to If-None-Match."""
    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    art.server.page(art.mobile(item_id), daum_page(_body(FAR, "20:00", "23:00")), etag='"x"')
    art.refresh()
    art.age(item_id, timedelta(days=4))
    assert art.refresh()[article_refresh.UNCHANGED] == 1, "a 200 is not a change by itself"
    art.age(item_id, timedelta(days=4))
    art.server.page(art.mobile(item_id), daum_page(_body(FAR, "21:00", "23:00")), etag='"x"')
    assert art.refresh()[article_refresh.REVISED] == 1, "nor is an unchanged ETag a non-change"


def test_record_outcome_refuses_a_304():
    with pytest.raises(ValueError):
        content_store.record_outcome(None, 1, acquisition.AcquisitionOutcome(
            status=acquisition.NOT_MODIFIED))


# --- failures never read as current, never cost the body ------------------------

def _kept(art, item_id, before_event) -> None:
    content = art.pipe.content(item_id)
    assert content["acquisition_status"] == acquisition.FETCHED_FULL
    assert content["extracted_text"]
    art.pipe.tick()
    assert art.pipe.last["reprocess"]["reprocessed"] == 0
    assert art.pipe.event(item_id) == before_event


def test_a_rate_limit_backs_off_and_pauses_the_host(art):
    first = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    second = art.article(2, _body("2027년 3월 20일", "20:00", "23:00"),
                         title="[홍대] 3월 20일 토요 밀롱가")
    before = art.pipe.event(first)
    art.server.fail(art.mobile(first), 429, retry_after="7200")
    art.server.fail(art.mobile(second), 429)
    counts = art.refresh(max_refreshes=2)
    assert counts["attempted"] == 1 and counts[article_refresh.RATE_LIMITED] == 1
    assert counts["deferred_by_budget"] >= 1, "the host is paused after a 429"
    content = art.pipe.content(first)
    assert content["refresh_outcome"] == article_refresh.RATE_LIMITED
    assert content["refresh_checked_at"] is None
    wait = content["refresh_next_at"] - content["refresh_attempted_at"]
    assert timedelta(hours=2) <= wait <= article_refresh.BACKOFF_CAP
    assert art.state(first)["state"] == article_refresh.ARTICLE_REFRESH_FAILED
    _kept(art, first, before)


def test_a_403_is_never_worked_around_and_stops_re_checks(art):
    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    before = art.pipe.event(item_id)
    art.server.fail(art.mobile(item_id), 403)
    assert art.refresh()[article_refresh.FORBIDDEN] == 1
    assert len(art.server.requests) == 1
    _kept(art, item_id, before)
    state = art.state(item_id)
    assert state["state"] == article_refresh.ARTICLE_REFRESH_FAILED and state["stopped"]
    art.age(item_id, timedelta(days=30))
    art.server.requests.clear()
    assert art.refresh()["attempted"] == 0
    assert art.server.requests == []


def test_an_unavailable_article_keeps_its_event_and_stops_after_the_limit(art):
    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    before = art.pipe.event(item_id)
    art.server.fail(art.mobile(item_id), 404)
    for attempt in range(article_refresh.NOT_FOUND_LIMIT):
        assert art.refresh()[article_refresh.NOT_FOUND] == 1
        art.age(item_id, timedelta(days=2))
    assert art.refresh()["attempted"] == 0
    _kept(art, item_id, before)


def test_a_timeout_is_retried_later_and_a_success_clears_it(art):
    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    art.server.fail(art.mobile(item_id), 0)
    assert art.refresh()[article_refresh.FAILED] == 1
    content = art.pipe.content(item_id)
    assert content["refresh_failures"] == 1
    assert content["refresh_next_at"] - content["refresh_attempted_at"] == \
        article_refresh.BACKOFF_BASE
    assert art.refresh()["attempted"] == 0, "not before its backoff"
    art.age(item_id, timedelta(hours=2))
    art.revise(item_id, _body(FAR, "20:00", "23:00"))
    assert art.refresh()[article_refresh.UNCHANGED] == 1
    assert art.pipe.content(item_id)["refresh_failures"] == 0


def test_a_body_unavailable_page_never_replaces_the_body(art):
    """K-TANGO's v0.84 loss, the refresh way round: the page answers 200 with
    no article, and the body the event was read from stays."""
    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    before = art.pipe.event(item_id)
    art.server.page(art.mobile(item_id), "<html><body>로그인이 필요합니다</body></html>")
    assert art.refresh()[article_refresh.BODY_UNAVAILABLE] == 1
    _kept(art, item_id, before)


def test_a_page_read_through_another_method_is_not_compared(art):
    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    before = art.pipe.event(item_id)
    art.server.page(art.mobile(item_id),
                    "<html><body>" + _body(FAR, "21:00", "23:00") + "</body></html>")
    assert art.refresh()[article_refresh.ADAPTER_MISMATCH] == 1
    _kept(art, item_id, before)


def test_robots_disallow_is_honoured_without_a_request(art):
    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    art.server.disallowed.add(art.mobile(item_id))
    assert art.refresh()[article_refresh.ROBOTS_DISALLOWED] == 1
    assert art.server.requests == []
    assert art.state(item_id)["stopped"]


def test_a_revision_whose_request_fails_is_not_stored(art, monkeypatch):
    """Body write and re-extract request are one transaction."""
    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    before = art.pipe.content(item_id)
    art.revise(item_id, _body(FAR, "21:00", "23:00"))

    def boom(*_a, **_k):
        raise RuntimeError("invalidation failed")
    monkeypatch.setattr(content_store, "mark_needs_reextract", boom)
    with pytest.raises(RuntimeError):
        art.refresh()
    after = art.pipe.content(item_id)
    assert after["content_hash"] == before["content_hash"]
    assert after["extracted_text"] == before["extracted_text"]


# --- eligibility and budget --------------------------------------------------------

def test_a_just_fetched_article_is_not_due(art):
    art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE, age=timedelta(hours=1))
    assert art.refresh()["attempted"] == 0


def test_a_near_event_is_re_checked_daily_a_far_one_every_three_days(art):
    near_day = date.today() + timedelta(days=5)
    near = art.article(1, _body(f"{near_day.year}년 {near_day.month}월 {near_day.day}일",
                                "20:00", "23:00"),
                       title=f"[홍대] {near_day.month}월 {near_day.day}일 밀롱가",
                       age=timedelta(hours=30))
    far = art.article(2, _body(FAR, "20:00", "23:00"), title=FAR_TITLE, age=timedelta(hours=30))
    assert art.pipe.events(near), "the near night was built"
    due = {r["source_item_id"]: r for r in article_refresh.due_articles(art.pipe.pg)}
    assert near in due and far not in due
    assert due[near]["priority"] == 1


def test_a_re_collected_discovery_record_brings_the_check_forward(art):
    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE,
                          age=timedelta(hours=20))
    assert item_id not in {r["source_item_id"] for r in article_refresh.due_articles(art.pipe.pg)}
    with art.pipe.pg.cursor() as cur:
        cur.execute("UPDATE source_items SET collected_at = now() WHERE source_item_id = %s",
                    (item_id,))
    due = {r["source_item_id"]: r for r in article_refresh.due_articles(art.pipe.pg)}
    assert due[item_id]["signal"]


def test_what_is_never_re_checked(art):
    """Whole-page text, a disabled source, a past event's old article, and a
    blocked item are not selected."""
    whole = art.article(1, "", title=FAR_TITLE, method_page=(
        "<html><body>" + _body(FAR, "20:00", "23:00") + " 추천글 조회수 123</body></html>"))
    assert art.pipe.content(whole)["acquisition_method"] == acquisition.METHOD_VISIBLE_TEXT
    old = art.article(2, _body("2025년 3월 13일", "20:00", "23:00"),
                      title="[홍대] 2025년 3월 13일 토요 밀롱가", age=timedelta(days=40))
    assert {r["source_item_id"] for r in article_refresh.due_articles(art.pipe.pg)} \
        .isdisjoint({whole, old})
    assert art.state(whole)["state"] == article_refresh.NOT_ELIGIBLE
    assert "whole-page" in art.state(whole)["reason"]
    assert art.state(old)["state"] == article_refresh.NOT_ELIGIBLE
    live = art.article(3, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    with art.pipe.pg.cursor() as cur:
        cur.execute("UPDATE sources SET enabled = false WHERE source_id = %s",
                    (art.pipe.source_id,))
    assert live not in {r["source_item_id"] for r in article_refresh.due_articles(art.pipe.pg)}


def test_the_per_tick_and_per_host_budgets_hold(art):
    ids = [art.article(n, _body(FAR, "20:00", "23:00"), title=f"{FAR_TITLE} {n}")
           for n in range(1, 5)]
    counts = art.refresh()
    assert counts["attempted"] == article_refresh.MAX_REFRESHES_PER_TICK
    host = article_refresh.host_of(art.mobile(ids[0]))
    with art.pipe.pg.cursor() as cur:
        for _ in range(article_refresh.HOST_DAILY_BUDGET):
            cur.execute("INSERT INTO content_fetch_log (source_item_id, host, outcome, purpose, "
                        "  refresh_result) VALUES (%s, %s, 'FETCHED_FULL', 'REFRESH', "
                        "  'UNCHANGED')", (ids[0], host))
    art.server.requests.clear()
    counts = art.refresh()
    assert counts["attempted"] == 0 and counts["deferred_by_budget"] >= 1
    assert art.server.requests == []
    assert art.state(ids[3])["state"] == article_refresh.ARTICLE_REFRESH_PENDING


# --- concurrency --------------------------------------------------------------------

def test_revision_b_fetched_while_a_is_being_extracted_is_read_next(art, monkeypatch):
    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    art.revise(item_id, _body(FAR, "20:30", "23:00"))
    art.refresh()
    stored = {"done": False}

    def fetch_b(post):
        if not stored["done"] and "20:30" in (post.body or ""):
            stored["done"] = True
            art.age(item_id, timedelta(days=4))
            art.revise(item_id, _body(FAR, "21:00", "23:00"))
            assert art.refresh()[article_refresh.REVISED] == 1

    _intercept_engine(monkeypatch, fetch_b)
    art.pipe.tick()
    assert stored["done"]
    assert str(art.pipe.event(item_id)["start_time"]) == "20:30:00"
    assert art.pipe.queued(item_id), "B was stored after A was selected"
    monkeypatch.undo()
    monkeypatch.setattr(db, "connect", _yield(art.pipe.pg))
    art.pipe.tick()
    assert str(art.pipe.event(item_id)["start_time"]) == "21:00:00"
    assert not art.pipe.queued(item_id)


def test_revision_c_before_b_is_extracted_ends_on_c_with_one_read(art):
    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    art.revise(item_id, _body(FAR, "20:30", "23:00"))
    art.refresh()
    art.age(item_id, timedelta(days=4))
    art.revise(item_id, _body(FAR, "21:00", "23:30"))
    assert art.refresh()[article_refresh.REVISED] == 1
    art.pipe.tick()
    assert art.pipe.last["reprocess"]["reprocessed"] == 1
    assert _clock(art.pipe.event(item_id)) == ("21:00:00", "23:30:00")


def test_an_older_response_never_overwrites_a_newer_body(art):
    """Two fetchers, one URL: while the re-check waits on the server, the
    admin re-acquire stores a newer body. The re-check's response is older
    and is dropped (SUPERSEDED), whatever it says."""
    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    mobile = art.mobile(item_id)
    art.revise(item_id, _body(FAR, "20:30", "23:00"))

    def newer_first():
        newer = acquisition.AcquisitionOutcome(
            status=acquisition.FETCHED_FULL, method=acquisition.METHOD_ARTICLE_REGION,
            fetched_url=mobile, text=_body(FAR, "22:00", "23:59"))
        content_store.record_outcome(art.pipe.pg, item_id, newer)

    art.server.before[mobile] = newer_first
    assert art.refresh()[article_refresh.SUPERSEDED] == 1
    assert "22:00" in art.pipe.content(item_id)["extracted_text"]
    art.pipe.tick()
    assert str(art.pipe.event(item_id)["start_time"]) == "22:00:00"


def test_a_stale_unchanged_answer_never_reverts_a_newer_body(art):
    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    mobile = art.mobile(item_id)

    def newer_first():
        content_store.record_outcome(art.pipe.pg, item_id, acquisition.AcquisitionOutcome(
            status=acquisition.FETCHED_FULL, method=acquisition.METHOD_ARTICLE_REGION,
            fetched_url=mobile, text=_body(FAR, "22:00", "23:59")))

    art.server.before[mobile] = newer_first
    assert art.refresh()[article_refresh.SUPERSEDED] == 1
    content = art.pipe.content(item_id)
    assert "22:00" in content["extracted_text"] and content["refresh_checked_at"] is None


def test_a_normalization_failure_after_a_revision_is_retried(art, monkeypatch):
    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    art.revise(item_id, _body(FAR, "21:00", "23:00"))
    art.refresh()
    real = normalization.normalize_candidate
    calls = {"n": 0}

    def once(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("normalization failed")
        return real(*a, **k)
    monkeypatch.setattr(normalization, "normalize_candidate", once)
    art.pipe.tick()
    assert art.pipe.last["normalize"]["failed"] == 1
    assert str(art.pipe.event(item_id)["start_time"]) == "20:00:00"
    art.pipe.tick()
    assert str(art.pipe.event(item_id)["start_time"]) == "21:00:00"


# --- human decisions come first -------------------------------------------------

def test_a_reviewed_candidate_is_kept_through_an_article_revision(art):
    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    before = art.pipe.event(item_id)
    with art.pipe.pg.cursor() as cur:
        cur.execute("INSERT INTO human_review_actions (candidate_id, source_item_id, action) "
                    "VALUES (%s, %s, 'EDIT')", (before["candidate_id"], item_id))
    art.revise(item_id, _body(FAR, "21:00", "23:00"))
    assert art.refresh()[article_refresh.REVISED] == 1
    art.pipe.tick()
    assert _clock(art.pipe.event(item_id)) == _clock(before)
    assert art.pipe.content(item_id)["extraction_outcome"] == \
        content_store.OUTCOME_KEPT_HUMAN_REVIEWED
    assert engine_ingest.freshness(art.pipe.settings, art.pipe.pg, item_id)["state"] == \
        content_store.HUMAN_DECISION_KEPT


@pytest.mark.parametrize("decision", [duplicates.DUPLICATE, duplicates.DISTINCT])
def test_a_human_duplicate_verdict_survives_an_article_revision(art, decision):
    a = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    b = art.article(2, _body(FAR, "20:00", "23:00"), title=f"{FAR_TITLE} 안내")
    ea, eb = art.pipe.event(a), art.pipe.event(b)
    duplicates.record_decision(
        art.pipe.pg, event_id=ea["event_id"],
        canonical_event_id=eb["event_id"] if decision == duplicates.DUPLICATE else None,
        decision=decision, decided_by=duplicates.HUMAN, rule="TEST", reviewer="tester")
    kept = art.pipe.event(a)
    art.revise(a, _body(FAR, "20:00", "23:30"))
    art.refresh()
    art.pipe.tick()
    after = art.pipe.event(a)
    assert after["event_id"] == ea["event_id"]
    assert str(after["end_time"]) == "23:30:00"
    assert (after["canonical_event_id"], after["listing_state"]) == \
        (kept["canonical_event_id"], kept["listing_state"])
    with art.pipe.pg.cursor() as cur:
        cur.execute("SELECT decided_by, decision FROM event_duplicate_decisions "
                    "WHERE event_id = %s ORDER BY decision_id DESC LIMIT 1", (ea["event_id"],))
        assert cur.fetchone() == (duplicates.HUMAN, decision)


# --- the guarded fetch -----------------------------------------------------------

class _Req:
    def __init__(self, url):
        self.full_url = url


def _public(monkeypatch, address="93.184.216.34"):
    monkeypatch.setattr(image_fetch.socket, "getaddrinfo",
                        lambda host, port: [(None, None, None, None, (address, 0))])


def test_a_private_address_is_refused_before_any_request(monkeypatch):
    _public(monkeypatch, "127.0.0.1")
    with pytest.raises(acquisition.FetchRefused) as refused:
        article_refresh.guarded_open(urllib_request("https://m.cafe.daum.net/x/1"))
    assert refused.value.code == "UNSAFE_ADDRESS"


def urllib_request(url):
    import urllib.request

    return urllib.request.Request(url)


@pytest.mark.parametrize("old, new, code", [
    ("https://m.cafe.daum.net/a/1", "https://login.kakao.com/x", "CROSS_HOST_REDIRECT"),
    ("https://m.cafe.daum.net/a/1", "http://m.cafe.daum.net/a/1", "DOWNGRADE_REDIRECT"),
])
def test_a_redirect_off_the_article_is_refused(monkeypatch, old, new, code):
    _public(monkeypatch)
    handler = article_refresh._RefreshRedirectHandler()
    with pytest.raises(acquisition.FetchRefused) as refused:
        handler.redirect_request(urllib_request(old), None, 302, "Found", {}, new)
    assert refused.value.code == code


def test_a_redirect_robots_disallows_is_refused(monkeypatch):
    _public(monkeypatch)
    monkeypatch.setattr(acquisition, "robots_allows", lambda url, **k: False)
    handler = article_refresh._RefreshRedirectHandler()
    with pytest.raises(acquisition.FetchRefused) as refused:
        handler.redirect_request(urllib_request("https://m.cafe.daum.net/a/1"), None, 302,
                                 "Found", {}, "https://m.cafe.daum.net/a/2")
    assert refused.value.code == "ROBOTS_DISALLOWED"


def test_a_redirect_into_a_private_network_is_refused(monkeypatch):
    monkeypatch.setattr(acquisition, "robots_allows", lambda url, **k: True)
    _public(monkeypatch, "10.0.0.5")
    handler = article_refresh._RefreshRedirectHandler()
    with pytest.raises(acquisition.FetchRefused) as refused:
        handler.redirect_request(urllib_request("https://m.cafe.daum.net/a/1"), None, 302,
                                 "Found", {}, "https://m.cafe.daum.net/a/2")
    assert refused.value.code == "UNSAFE_ADDRESS"


def test_an_oversized_page_is_refused_not_truncated():
    big = _Resp(b"x" * (article_refresh.MAX_ARTICLE_BYTES + 1), "https://a.test/", {})
    with pytest.raises(acquisition.FetchRefused) as refused:
        article_refresh._Bounded(big, article_refresh.MAX_ARTICLE_BYTES).read()
    assert refused.value.code == "RESPONSE_TOO_LARGE"
    declared = _Resp(b"x", "https://a.test/", {"Content-Length": str(10 ** 9)})
    with pytest.raises(acquisition.FetchRefused):
        article_refresh._Bounded(declared, article_refresh.MAX_ARTICLE_BYTES).read()


def test_a_refused_request_is_a_refusal_outcome(monkeypatch):
    monkeypatch.setattr(acquisition, "robots_allows", lambda url, **k: True)

    def refuse(request, timeout=None):
        raise acquisition.FetchRefused("CROSS_HOST_REDIRECT", "off host")
    outcome = acquisition.fetch("https://m.cafe.daum.net/a/1", opener=refuse)
    assert (outcome.status, outcome.error_code) == (acquisition.FETCH_BLOCKED,
                                                    "CROSS_HOST_REDIRECT")
    assert article_refresh.classify({"acquisition_method": "article_region"}, outcome) == \
        article_refresh.REFUSED


@pytest.mark.parametrize("result, failures, retry_after, expected", [
    (article_refresh.FAILED, 1, None, timedelta(hours=1)),
    (article_refresh.FAILED, 3, None, timedelta(hours=4)),
    (article_refresh.FAILED, 30, None, article_refresh.BACKOFF_CAP),
    (article_refresh.RATE_LIMITED, 1, "120", timedelta(hours=1)),
    (article_refresh.RATE_LIMITED, 1, "36000", timedelta(hours=10)),
    (article_refresh.RATE_LIMITED, 1, str(10 ** 9), article_refresh.BACKOFF_CAP),
    (article_refresh.NOT_FOUND, 1, None, article_refresh.NOT_FOUND_WAIT),
])
def test_backoff(result, failures, retry_after, expected):
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    assert article_refresh.backoff(result, failures, retry_after, now) - now == expected


@pytest.mark.parametrize("result, failures", [
    (article_refresh.FORBIDDEN, 1), (article_refresh.ROBOTS_DISALLOWED, 1),
    (article_refresh.NOT_FOUND, article_refresh.NOT_FOUND_LIMIT)])
def test_a_stopping_failure_has_no_next_attempt(result, failures):
    assert article_refresh.backoff(result, failures, None, datetime.now(timezone.utc)) is None


def test_an_http_date_retry_after_is_read():
    now = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)
    assert article_refresh._retry_after("Tue, 20 Oct 2026 03:00:00 GMT", now) == \
        timedelta(hours=3)


# --- protected source review: the K-TANGO 643 / 646 / 647 shapes ----------------
#
# Production, read-only, 2026-10-20: each was served a ~720-character body
# once (2026-09-04) and refused every time since; the discovery snippet is
# empty; each still carries a poster URL; each feeds one past Event that an
# older engine read and the running one has not:
#
#   643  공지 2025 K-TANGO CF 일정표 NEW       Event 1597462  2025-05-08 00:00
#   646  2024 K-TANGO SF : 서울밀롱가데이       Event  430222  2024-09-27 14:00-18:00
#   647  2024 K-TANGO SF 한강탱고축제           Event   21912  2024-09-29 16:00
#
# 644 / 648 / 649 share the shape but feed no Event, so they are not review
# items. None of them is re-fetched or corrected here.

KTANGO = {
    643: ("공지 2025 K-TANGO CF 일정표 NEW",
          "2025 K-TANGO CF 일정표 2025.05.08 (목) 00:00 오픈 밀롱가 일정 공지입니다."),
    646: ("2024 K-TANGO SF : 서울밀롱가데이",
          "2024 K-TANGO SF 서울밀롱가데이 2024.09.27 (금) 14:00~18:00 밀롱가 많은 참여 바랍니다."),
    647: ("2024 K-TANGO SF 한강탱고축제",
          "2024 K-TANGO SF 한강탱고축제 2024.09.29 (일) 16:00 밀롱가 많은 참여 바랍니다."),
}


def _protected(pipe, number: int) -> int:
    title, text = KTANGO[number]
    url = f"http://www.k-tango.test/{pipe.unique}/read.jsp?no={number}"
    pipe.collect({"source_url": url, "title": title, "body": "",
                  "acquisition_quality": "METADATA_ONLY"})
    item_id = pipe.item_id(url)
    padded = text + " 장소: 케이탱고 홀 회비 10,000원 " + "자세한 내용은 포스터를 참고해 주세요. " * 12
    content_store.record_outcome(pipe.pg, item_id, acquisition.AcquisitionOutcome(
        status=acquisition.FETCHED_FULL, method=acquisition.METHOD_TEMPLATE_BOARD,
        fetched_url=url, text=padded))
    pipe.tick()
    content_store.record_outcome(pipe.pg, item_id, acquisition.AcquisitionOutcome(
        status=acquisition.FETCH_BLOCKED, method=acquisition.METHOD_NONE, fetched_url=url,
        error_code="BODY_UNAVAILABLE",
        images=[f"http://www.k-tango.test/upload/editor/{number}.png"]))
    return item_id


@pytest.fixture
def ktango(pipe, monkeypatch):
    def no_fetch(*_a, **_k):
        raise AssertionError("a protected item was fetched")
    monkeypatch.setattr(acquisition, "fetch", no_fetch)
    monkeypatch.setattr(article_refresh, "fetch_article", no_fetch)
    items = {n: _protected(pipe, n) for n in KTANGO}
    for item_id in items.values():
        _as_legacy(pipe, item_id)   # finished before v0.96.42, as on Production
    return items


def test_the_three_protected_items_are_review_items(pipe, ktango):
    for number, item_id in ktango.items():
        fresh = engine_ingest.freshness(pipe.settings, pipe.pg, item_id)
        assert fresh["state"] == content_store.ENGINE_UPDATE_NOT_APPLIED, number
        assert fresh["basis"] == content_store.BASIS_DERIVED
        assert fresh["last_applied_engine_version"] == content_store.UNKNOWN
        assert content_store.FLAG_REVIEW_RECOMMENDED in fresh["flags"]
        review = content_store.protected_review(pipe.pg, item_id, fresh)
        assert review["review_recommended"]
        assert review["required_action"] == content_store.ACTION_REVIEW
        assert review["candidate_ids"] == fresh["candidate_ids"] != []
        assert [e["event_id"] for e in review["events"]] == \
            [e["event_id"] for e in pipe.events(item_id)]
        assert review["events_not_ended"] == 0, "past events: no upcoming user impact"
        evidence = review["evidence"]
        assert evidence["best_fetched_chars"] > acquisition.MINIMUM_USEFUL_TEXT
        assert not evidence["article_text_held"]
        assert evidence["poster_urls"]
    listed = {r["source_item_id"] for r in content_store.listing(
        pipe.pg, extraction="REVIEW", source_id=pipe.source_id,
        engine_version=pipe.settings.engine_version)}
    assert listed == set(ktango.values())


def test_643_is_not_corrected_by_any_automatic_pass(pipe, ktango):
    item_id = ktango[643]
    before = pipe.event(item_id)
    assert (str(before["event_date"]), str(before["start_time"])) == ("2025-05-08", "00:00:00")
    for _ in range(2):
        pipe.tick()
        article_refresh.run(pipe.pg, sleep=_noop)
    after = pipe.event(item_id)
    assert after == before, "00:00 is never turned into 20:00 without a person"
    content = pipe.content(item_id)
    assert content["acquisition_status"] == acquisition.FETCH_BLOCKED
    assert content["applied_engine_version"] is None, "no fake applied version"


def test_a_blocked_item_with_no_event_is_not_a_review_item(pipe):
    url = f"http://www.k-tango.test/{pipe.unique}/read.jsp?no=644"
    pipe.collect({"source_url": url, "title": "공지 2025 K-TANGO CF (Community&Festival) NEW",
                  "body": "", "acquisition_quality": "METADATA_ONLY"})
    item_id = pipe.item_id(url)
    content_store.record_outcome(pipe.pg, item_id, acquisition.AcquisitionOutcome(
        status=acquisition.FETCHED_FULL, method=acquisition.METHOD_TEMPLATE_BOARD,
        fetched_url=url, text="K-TANGO 커뮤니티 페스티벌 소개 " * 10))
    pipe.tick()
    content_store.record_outcome(pipe.pg, item_id, acquisition.AcquisitionOutcome(
        status=acquisition.FETCH_BLOCKED, method=acquisition.METHOD_NONE, fetched_url=url))
    pipe.tick()
    assert pipe.events(item_id) == []
    fresh = engine_ingest.freshness(pipe.settings, pipe.pg, item_id)
    assert content_store.FLAG_REVIEW_RECOMMENDED not in fresh["flags"]
    assert item_id not in {r["source_item_id"] for r in content_store.listing(
        pipe.pg, extraction="REVIEW", source_id=pipe.source_id,
        engine_version=pipe.settings.engine_version)}


def _snapshot(pipe, item_ids) -> tuple:
    with pipe.pg.cursor() as cur:
        cur.execute("SELECT * FROM source_item_content WHERE source_item_id = ANY(%s) "
                    "ORDER BY source_item_id", (list(item_ids),))
        content = cur.fetchall()
        cur.execute("SELECT * FROM events WHERE source_item_id = ANY(%s) ORDER BY event_id",
                    (list(item_ids),))
        events = cur.fetchall()
        cur.execute("SELECT count(*) FROM content_fetch_log")
        log = cur.fetchone()
        cur.execute("SELECT count(*) FROM human_review_actions")
        actions = cur.fetchone()
        cur.execute("SELECT count(*) FROM event_duplicate_decisions")
        decisions = cur.fetchone()
    return content, events, log, actions, decisions


def test_the_review_pages_link_the_right_things_and_change_nothing(pipe, ktango, client):
    before = _snapshot(pipe, ktango.values())
    for number, item_id in ktango.items():
        event = pipe.event(item_id)
        page = client.get(f"/admin/intake/{item_id}")
        assert page.status_code == 200
        text = page.text
        assert "Protected source review" in text and "REVIEW_RECOMMENDED" in text
        assert content_store.ENGINE_UPDATE_NOT_APPLIED in text
        assert f'/admin/review/{event["candidate_id"]}' in text
        assert f'/admin/events/{event["event_id"]}/sources' in text
        assert content_store.ACTION_REVIEW in text
        assert "past" in text
        assert article_refresh.SOURCE_FETCH_BLOCKED in text
        api = client.get(f"/api/admin/intake/{item_id}").json()
        assert api["protected_review"]["review_recommended"]
        assert api["protected_review"]["candidate_ids"] == [event["candidate_id"]]
        assert api["freshness"]["last_applied_engine_version"] == content_store.UNKNOWN
        assert api["article_refresh"]["state"] == article_refresh.SOURCE_FETCH_BLOCKED
        review = client.get(f"/admin/review/{event['candidate_id']}")
        assert review.status_code == 200
        assert f"/admin/intake/{item_id}" in review.text
    listed = client.get(f"/admin/intake?extraction=REVIEW&source_id={pipe.source_id}")
    assert all(f"/admin/intake/{i}" in listed.text for i in ktango.values())
    assert client.get("/api/admin/articles/refresh-summary").status_code == 200
    assert _snapshot(pipe, ktango.values()) == before


def test_a_review_mutation_without_its_token_changes_nothing(pipe, ktango, client):
    event = pipe.event(ktango[643])
    before = _snapshot(pipe, ktango.values())
    client.console_tokens = False
    response = client.post(f"/admin/review/{event['candidate_id']}/edit",
                           data={"start_time": "20:00", "reason": "guess"},
                           follow_redirects=False)
    assert response.status_code == 403
    assert _snapshot(pipe, ktango.values()) == before


def test_a_person_s_review_closes_the_item_and_changes_no_event(pipe, ktango, client):
    """CONFIRM through the existing Review route (token, audit trail): the
    item leaves the review list, its page says who decided, and the Event,
    the content row and the protection are exactly as they were."""
    item_id = ktango[647]
    event = pipe.event(item_id)
    content = pipe.content(item_id)
    # v0.96.46: the action carries the basis of the page it was taken on.
    page = client.get(f"/api/admin/review/{event['candidate_id']}").json()
    response = client.post(f"/admin/review/{event['candidate_id']}/confirm",
                           data={"reason": "poster says 2024.09.29 16:00",
                                 "basis": page["basis"]},
                           follow_redirects=False)
    assert response.status_code == 303
    with pipe.pg.cursor() as cur:
        cur.execute("SELECT action, reason FROM human_review_actions WHERE candidate_id = %s",
                    (event["candidate_id"],))
        assert cur.fetchall() == [("CONFIRM", "poster says 2024.09.29 16:00")]
    listed = {r["source_item_id"] for r in content_store.listing(
        pipe.pg, extraction="REVIEW", source_id=pipe.source_id,
        engine_version=pipe.settings.engine_version)}
    assert listed == {ktango[643], ktango[646]}
    fresh = engine_ingest.freshness(pipe.settings, pipe.pg, item_id)
    review = content_store.protected_review(pipe.pg, item_id, fresh)
    assert not review["review_recommended"]
    assert review["required_action"] == content_store.ACTION_NONE
    assert "reviewed by a person" in review["required_action_text"]
    assert pipe.event(item_id) == event
    assert pipe.content(item_id) == content


# --- the operator's counts -------------------------------------------------------

def test_the_summary_counts_what_happened(art):
    first = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    second = art.article(2, _body("2027년 3월 20일", "20:00", "23:00"),
                         title="[홍대] 3월 20일 토요 밀롱가")
    art.revise(first, _body(FAR, "21:00", "23:00"))
    art.server.fail(art.mobile(second), 503)
    art.refresh()
    summary = article_refresh.summary(art.pipe.pg)
    assert summary["eligible_full_articles"] >= 2
    assert summary["refresh_attempted_24h"] == 2
    assert summary["relevant_content_revised_24h"] == 1
    assert summary["reextraction_requested_24h"] == 1
    assert summary["refresh_failed_24h"] == 1
    assert summary["reextraction_completed"] == 0
    art.pipe.tick()
    assert article_refresh.summary(art.pipe.pg)["reextraction_completed"] == 1


def test_the_acquisition_job_runs_the_re_check_inside_its_own_tick(art, monkeypatch):
    from scheduler import acquisition_job

    item_id = art.article(1, _body(FAR, "20:00", "23:00"), title=FAR_TITLE)
    art.revise(item_id, _body(FAR, "21:00", "23:00"))
    monkeypatch.setattr(article_refresh, "fetch_article", art.server.fetcher)
    detail = acquisition_job.run(art.pipe.settings, sleep=_noop)
    assert "refresh 1/1 due" in detail and "revised=1" in detail
    assert art.pipe.content(item_id)["refresh_outcome"] == article_refresh.REVISED
