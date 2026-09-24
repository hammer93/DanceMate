"""v0.96.13 - a danceinfo.net post stops being judged on its own preview.

danceinfo.net renders a "행사일" heading, with the event's date/schedule/venue/DJ
under it, on only some of its lesson pages. `extract_article()` looked for that
heading in the page's visible text and, not finding it, fell through to
og:description - which the site truncates at about 140 characters with an
ellipsis. The post's body then stopped before the post had said anything.

Measured on Production's stored DanceInfo corpus before this was written:

    method              n     ends "…"   avg chars   max
    og_description     162      152         139      160
    danceinfo_region    19        0         411      806

and of the 22 items DanceInfo itself files under an Event category that
produced no candidate at all, 19 were og:description ones.

What the cut removes is exactly what decides the reading. 클럽 하바나's stored
body ends at "…바차타 무료 오픈강습"; the page continues "🕣 20:30 ~ 21:30 바차타
무료 오픈강습 🕤 21:30 ~ 미니 소셜 파티" - a social beside its own clock, the
evidence `classifier.social_evidence()` has asked for since v0.79.

Every one of those fields is on the page already, in the Next.js hydration
payload `danceinfo_discovery.parse_list()` has read the list stage out of since
v0.82. This reads the detail stage out of the same place, and composes it in
the shape the "행사일" region already produced, so nothing downstream is asked
to read a new format.

Re-running the classifier over today's 40 live listings, unchanged, with the
old body and the new one: body length 194 -> 526 chars on average; five
classifications change (홍턴 추석 연휴 OTHER -> SOCIAL_WITH_CLASS, 부산 루에다
OTHER -> SOCIAL_WITH_CLASS, 브라비오크루 정모 OTHER -> SOCIAL, 추석연휴 CHUSEOK
SPECIAL PARTY SOCIAL -> SOCIAL_WITH_CLASS, 보니따 OTHER -> CLASS once its full
body shows a 10만원 풀패스 workshop block); 24 courses stay courses and no event
of any kind is lost.
"""

from __future__ import annotations

import json

from runtime import acquisition


def _page(lesson: dict | None, *, visible_extra: str = "") -> str:
    payload = {"props": {"pageProps": {"initialLesson": lesson}}} if lesson is not None \
        else {"props": {"pageProps": {}}}
    return (
        "<html><body><div>필터 강습 장소 모임 인물</div>"
        f"<div>{visible_extra}</div>"
        '<script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(payload, ensure_ascii=False)}</script>"
        "<footer>이용약관 개인정보처리방침</footer></body></html>"
    )


_HAVANA = {
    "date": "2026-09-23",
    "eventDays": "2026-09-23,2026-09-25,2026-09-26",
    "schedule": "20:30 ~ 21:30 오픈강습, 21:30 ~ 미니 소셜 파티",
    "placeName": "하바나",
    "djNames": "DJ 깔리드",
    "description": "춤추는 놀이터 하바나에서 추석 연휴를 맞아 소셜파티를 개최합니다.",
}


# --- the payload is read, and read whole -------------------------------------

def test_a_lesson_page_is_read_from_its_own_payload():
    text, method = acquisition.extract_article(_page(_HAVANA))
    assert method == acquisition.METHOD_DANCEINFO_PAYLOAD
    assert "2026-09-23" in text
    assert "21:30 ~ 미니 소셜 파티" in text
    assert "장소 하바나" in text
    assert "DJ 깔리드" in text
    assert "소셜파티를 개최합니다" in text


def test_the_composed_body_keeps_the_labels_the_extractors_already_read():
    """The shape is the one the 행사일 region produced, because
    `extraction_rules.extract_venue()` reads a 장소 label and
    `extractor.DJ_RE` reads a DJ one. This release changes how many pages
    reach them, never what they see."""
    text, _ = acquisition.extract_article(_page(_HAVANA))
    assert "전체일정 " in text
    assert "일정정보 " in text
    assert "장소 " in text
    assert "DJ " in text
    assert "강의 소개 " in text


def test_the_page_chrome_never_enters_the_body():
    text, _ = acquisition.extract_article(_page(_HAVANA, visible_extra="다가오는 추천 행사 9월 5일 다른 행사"))
    assert "필터 강습" not in text
    assert "이용약관" not in text
    assert "다른 행사" not in text


def test_a_field_the_page_does_not_carry_is_left_out_entirely():
    """An empty "장소" label is a label extract_venue() would try to read a
    venue out of, so a missing field is omitted rather than written blank."""
    lesson = dict(_HAVANA)
    del lesson["placeName"]
    lesson["djNames"] = ""
    text, _ = acquisition.extract_article(_page(lesson))
    assert "장소" not in text
    assert "DJ" not in text
    assert "일정정보" in text


# --- it stays a danceinfo reading, and nothing else ---------------------------

def test_a_page_with_no_payload_falls_through_exactly_as_before():
    page = (
        "<html><head>"
        '<meta property="og:description" content="짧은 미리보기 본문입니다 여기서 잘립니다…">'
        "</head><body><div>본문 없음</div></body></html>"
    )
    text, method = acquisition.extract_article(page)
    assert method == acquisition.METHOD_OG_DESCRIPTION
    assert text.endswith("…")


def test_a_next_js_page_that_is_not_a_lesson_page_is_not_touched():
    """`initialLesson` is danceinfo's own key. Another Next.js site's payload
    yields nothing here and the existing fallbacks decide, as they always
    have."""
    page = (
        "<html><head>"
        '<meta property="og:description" content="다른 사이트의 요약 본문입니다 충분히 깁니다">'
        "</head><body>"
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"initialPost":{"title":"x"}}}}</script>'
        "</body></html>"
    )
    text, method = acquisition.extract_article(page)
    assert method == acquisition.METHOD_OG_DESCRIPTION
    assert "다른 사이트" in text


def test_a_broken_payload_is_not_an_exception():
    page = (
        "<html><head>"
        '<meta property="og:description" content="여기가 대신 읽혀야 합니다 충분히 긴 본문">'
        "</head><body>"
        '<script id="__NEXT_DATA__" type="application/json">{not json at all</script>'
        "</body></html>"
    )
    text, method = acquisition.extract_article(page)
    assert method == acquisition.METHOD_OG_DESCRIPTION
    assert "여기가 대신" in text


def test_a_payload_too_thin_to_mean_anything_falls_through():
    page = _page({"date": "2026-09-23"}).replace(
        "<html><body>",
        '<html><head><meta property="og:description" content="이쪽이 더 읽을 만한 본문입니다 최소 길이를 넘기기 위한 문장">'
        "</head><body>", 1)
    text, method = acquisition.extract_article(page)
    assert method == acquisition.METHOD_OG_DESCRIPTION


def test_danceinfo_payload_body_on_a_page_of_another_shape_is_empty():
    assert acquisition.danceinfo_payload_body("<html><body>no script</body></html>") == ""
    assert acquisition.danceinfo_payload_body(_page(None)) == ""
    assert acquisition.danceinfo_payload_body(_page("not a dict")) == ""


# --- the one rule reading the post whole reached ------------------------------

def test_a_course_the_site_filed_as_a_course_stays_one_once_its_timetable_is_read():
    """v0.96.13's own regression, and the reason engine 0.98 exists.

    "Largo Special KIZOMBA" is a four-week Wednesday kizomba course. Once its
    body is read whole, its own timetable ("매주 수요일, 4주 17:10~20:00")
    supplies the day and the clock `notice_evidence_bundle()` asks for, and
    the heading word carrying it is the adjective "Special" - so the bundle
    overturned danceinfo.net's own 강습 filing and the course went live as a
    SOCIAL. On the truncated body neither the day nor the clock was there.
    """
    import sys
    from pathlib import Path
    repo = Path(__file__).resolve().parents[1]
    if str(repo / "engine") not in sys.path:
        sys.path.insert(0, str(repo / "engine"))
    from src import classifier

    title = "Largo Special KIZOMBA"
    body = ("2026-09-29 전체일정 2026-09-29,2026-10-02,2026-10-09,2026-10-16,2026-10-23 "
            "일정정보 매주 수요일, 4주 17:10~20:00 강의 소개 레이디 집중 케어반, "
            "쏘셜 스킬/뮤지커리티 클래스, 커플 할인")
    assert classifier.notice_evidence_bundle(title, body) is True
    assert classifier.sold_as_a_course(title, body, source_category="CLASS") is True
    assert classifier.classify(title, body, None, None, "CLASS") == "CLASS"


def test_a_priced_door_on_a_named_day_still_beats_the_sites_course_filing():
    """The escape that is kept: a night with a door and a price is announced
    in its own right, whatever category the listing sits in."""
    import sys
    from pathlib import Path
    repo = Path(__file__).resolve().parents[1]
    if str(repo / "engine") not in sys.path:
        sys.path.insert(0, str(repo / "engine"))
    from src import classifier

    title = "포토파티 with 무료 오픈강습"
    body = "9월 26일(토) 파티 오픈 20:00 소셜 15,000원"
    assert classifier.party_evidence_bundle(title, body) is True
    assert classifier.sold_as_a_course(title, body, source_category="CLASS") is False
    assert classifier.classify(title, body, None, None, "CLASS") == "SOCIAL_WITH_CLASS"
