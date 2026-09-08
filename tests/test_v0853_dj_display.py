"""v0.85.3 DJ Duplicate UX Fix (Sections 30-34).

Found live in production (event_id 221245, SRC-D-003): a raw post title
already spelling out "(DJ : 유진)" as free text, plus the structured `dj`
field the engine has always extracted, rendered as two separate things -
"...(DJ : 유진) (DJ 유진)". Section 31 picks option A: skip the display
badge only when it would repeat the title verbatim; the title text and
the stored `dj` field are never touched. Section 32 limits normalization
to label spacing/case/colon/parens - no fuzzy name matching, so a
genuinely different DJ named in the title (Section 33) is never mistaken
for a match and stays visible as a real conflict signal.
"""

from __future__ import annotations

from runtime import public


def _event(**overrides):
    base = {
        "id": 1, "name": "더 피스타 밀롱가", "date": "2026-09-12",
        "fee": None, "dj": None, "cancelled": False,
    }
    base.update(overrides)
    return base


# 1. title "(DJ : 유진)" + dj "유진" -> shown once ------------------------------

def test_dj_already_in_title_is_shown_once():
    event = _event(name="[화정] 9월 8일 화정 공지 (DJ : 유진)", dj="유진")
    line2 = public._timeline_line2(event)
    assert line2.count("유진") == 1
    assert '<span class="dj">' not in line2


def test_dj_already_in_title_various_label_spellings():
    """Section 32: label spacing/colon/case variants only."""
    for title in (
        "9월 8일 공지 (DJ:유진)",
        "9월 8일 공지 (DJ : 유진)",
        "9월 8일 공지 (dj : 유진)",
        "9월 8일 공지 (DJ  :  유진)",
    ):
        event = _event(name=title, dj="유진")
        line2 = public._timeline_line2(event)
        assert line2.count("유진") == 1, f"failed for title: {title!r}"
        assert '<span class="dj">' not in line2


# 2. title has no DJ mention + dj "유진" -> structured DJ shown ---------------

def test_dj_shown_when_title_has_no_dj_mention():
    event = _event(name="9월 8일 화정 공지", dj="유진")
    line2 = public._timeline_line2(event)
    assert '<span class="dj">(DJ 유진)</span>' in line2


# 3. title DJ 민수 + structured dj 유진 -> not mistaken as duplicate ------------

def test_different_dj_in_title_is_not_hidden():
    """Section 33: a genuinely different name must never be treated as a
    match - hiding it would erase a real conflict signal."""
    event = _event(name="9월 8일 공지 (DJ : 민수)", dj="유진")
    line2 = public._timeline_line2(event)
    assert "민수" in line2  # from the title, unchanged
    assert '<span class="dj">(DJ 유진)</span>' in line2  # structured field still shown
    assert line2.count("유진") == 1
    assert line2.count("민수") == 1


# 4. raw title/data unchanged -------------------------------------------------

def test_raw_event_name_is_never_modified_by_the_dj_check():
    event = _event(name="[화정] 9월 8일 화정 공지 (DJ : 유진)", dj="유진")
    original_name = event["name"]
    public._timeline_line2(event)
    assert event["name"] == original_name  # the function must not mutate its input
    line2 = public._timeline_line2(event)
    assert "[화정] 9월 8일 화정 공지 (DJ : 유진)" in line2  # full title text still rendered verbatim


# --- supporting unit tests for the detector itself ---------------------------

def test_title_already_announces_dj_true_case():
    assert public._title_already_announces_dj("공지 (DJ : 유진)", "유진") is True


def test_title_already_announces_dj_false_when_absent():
    assert public._title_already_announces_dj("공지", "유진") is False


def test_title_already_announces_dj_false_when_different_name():
    assert public._title_already_announces_dj("공지 (DJ : 민수)", "유진") is False


def test_title_already_announces_dj_false_for_empty_dj():
    assert public._title_already_announces_dj("공지 (DJ : 유진)", "") is False


def test_title_already_announces_dj_false_for_empty_title():
    assert public._title_already_announces_dj("", "유진") is False


# --- regression: existing timeline behavior untouched (Section 47: 19-21) ---

def test_two_line_default_still_holds():
    event = _event(name="한강 밀롱가", dj=None)
    line2 = public._timeline_line2(event)
    assert "한강 밀롱가" in line2
    assert "입장료:" in line2


def test_fee_known_still_renders():
    event = _event(fee=20000)
    assert "20,000원" in public._timeline_line2(event)
