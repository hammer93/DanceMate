"""v0.86.0 Private Alpha Field Validation - engine-side fix.

Found during this release's own production field audit (Section 43's Wrong
DJ gate), not from a pre-written spec: a real DanceInfo post
(https://danceinfo.net/lessons/2401, event_id 32096) stored `dj = "DJ"` -
the literal label, not a name. `runtime.public`'s DJ-duplicate-suppression
badge then showed "(DJ DJ)", the second symptom that actually surfaced it
in the Timeline audit.
"""

from src.extractor import DJ_RE, extract_single


def test_a_repeated_dj_label_does_not_capture_itself_as_the_name():
    """The real shape: DanceInfo's own structured info box puts a bare
    "DJ" field label directly against a value that itself starts with the
    word "DJ" - "...구글맵 DJ DJ 네로 강의..." The old single-label pattern
    stopped at the first "DJ" and captured the second "DJ" as the name."""
    text = "장소 분당 실루엣 카카오맵 네이버지도 구글맵 DJ DJ 네로 강의 소개"
    match = DJ_RE.search(text)
    assert match is not None
    assert match.group(1) == "네로"


def test_a_normal_single_dj_label_is_unaffected():
    match = DJ_RE.search("시간: PM 07:30~11:30 장소: 아미고스튜디오 DJ : 로띠 입장료 13,000원")
    assert match.group(1) == "로띠"


def test_the_real_lovely_milonga_post_that_defined_this_fix():
    """Real body text (candidate_id 1440, post_id 298), trimmed to the
    relevant span - full regression via extract_single()."""
    candidate = extract_single(
        "🩷러블리밀롱가 7주년 파티안내🩷",
        "2026년 9월 12일 (토) 일정정보 5:30~9:30 장소 분당 실루엣 카카오맵 네이버지도 "
        "구글맵 DJ DJ 네로 강의 소개 🩷러블리밀롱가 7주년 파티안내🩷",
        published="2026-09-08",
    )
    assert candidate.dj == "네로"
