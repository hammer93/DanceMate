"""v0.96.8 - the collector's prior stops overruling "this is not an event"
(Information Engine 0.95).

``classify()`` opened with the collector's ``known_event_type`` and returned
it immediately, so the recap/administrative guard written on the very next
line never ran for a post that carried one. On Production that put 126
events on display that are not announcements at all: a club's own video and
photo archive of a night already danced ("정기모임 영상 #01", "살사정모
(23/07/31) 영상 #14", "정모 … 사진"), and one notice whose whole purpose is
to say the night is off ("26년9월25일(금) 수라댄 금요정모 휴강" - LISTED and
upcoming when it was measured).

The guard already recognised every one of them. The change is that it is
asked first, and it is the only rule placed above the prior.

**The prior itself is untouched, and must be.** 324 of Production's 851
events exist only because of it and 56 of those are still upcoming: the
milonga listing directory whose entries are brand names with no scene word
in them ("orange", "디디디", "바모스"), and every Naver community board's
real announcement, which is as title-only as its archive rows are.
``KEPT_BY_THE_PRIOR`` is that set. A test that only proved the false
positives were gone would be satisfied by deleting the feature, so each of
those is asserted to still classify by the prior and, separately, to read
exactly what it reads *without* one - eight of the ten lose their type (six
to OTHER, one to CLASS, and item 2103's "7:30 오픈강습" line to
MILONGA_WITH_CLASS, which is not the type its listing page guarantees). The
two that would not notice are named rather than quietly left in.

**One word joined the guard**: 휴강, beside the 취소 안내 / 취소 및 already
in its administrative half. The Daum board collector's own title test asks
whether a heading names the club's own night on a specific day; item 3635
answers yes to both and then cancels it, which that test has no way to see.
Across the whole corpus the word changes three posts and only 3635 carries
an events row.

Sweeping all 2,327 collected items changes 154 classifications: 126 stop
being events, one of them still upcoming. **0 genuine nights lost, 0 genuine
upcoming nights lost, 0 posts promoted into being an event.**
"""

import pytest

from src.classifier import classify, is_non_event_notice
from src.collectors.base import RawPostRecord
from src.live_pipeline import EVENT_CLASSIFICATIONS, process_discovered_post
from tests.fixture_v0968_known_event_type_precedence import (
    CANCELLED_BUT_NO_EVENT, CORRECTED_BY_PRECEDENCE, KEPT_BY_THE_PRIOR,
    NO_PRIOR_UNCHANGED,
)


class Dummy:
    """A connection the live pipeline never touches for these posts."""


def _post(title, body, published, ket=None, **kw):
    return RawPostRecord(
        source_id="SRC-D-022", platform="DAUM_CAFE",
        source_url="https://example.invalid/post",
        title=title, body=body, published_at=published,
        acquisition_quality="FULL_TEXT", known_event_type=ket, **kw)


def _processed(title, body, published, ket=None, **kw):
    return process_discovered_post(Dummy(), _post(title, body, published, ket, **kw),
                                   "SECONDARY")


# --- T1/T3/T4: the prior loses to a title that disowns the event -----------

@pytest.mark.parametrize("ref,title,body,published,ket", CORRECTED_BY_PRECEDENCE,
                         ids=[row[0] for row in CORRECTED_BY_PRECEDENCE])
def test_a_recap_or_a_cancellation_is_not_an_event_whatever_board_it_came_from(
        ref, title, body, published, ket):
    """Every one of these is an ``events`` row on Production at engine 0.94."""
    # The fixture must still reproduce the *precondition* of the defect: a
    # real prior, and a title the guard already knew about. A fixture that
    # stopped matching the guard would pass for the wrong reason.
    assert ket, f"{ref}: fixture lost its known_event_type"
    assert is_non_event_notice(title), (
        f"{ref}: fixture no longer matches the guard that was being skipped")
    assert classify(title, body, known_event_type=ket) == "OTHER", ref
    assert _processed(title, body, published, ket)["events"] == [], ref


def test_the_cancelled_friday_round_is_the_release_regression():
    """Item 3635 in full: the one false positive that was still upcoming.

    A Daum EVENT_PRIMARY board, a heading that names the club's own Friday
    round on a specific day - which is exactly what the collector's title
    test looks for - and a post that exists to cancel it.
    """
    ref, title, body, published, ket = CORRECTED_BY_PRECEDENCE[0]
    assert ref == "3635"
    assert ket == "SOCIAL"
    # The collector was right about everything it can see: the night is
    # named, the day is named. 휴강 is the part it cannot see.
    assert "금요정모" in title and "9월25일" in title
    assert classify(title.replace(" 휴강", ""), body,
                    known_event_type=ket) == "SOCIAL"
    assert classify(title, body, known_event_type=ket) == "OTHER"
    assert _processed(title, body, published, ket)["events"] == []


@pytest.mark.parametrize("ref,title,body,published,ket", CANCELLED_BUT_NO_EVENT,
                         ids=[row[0] for row in CANCELLED_BUT_NO_EVENT])
def test_the_other_two_posts_the_cancellation_word_reaches_produce_nothing(
        ref, title, body, published, ket):
    """The whole measured reach of 휴강 outside item 3635. Neither of these
    has an ``events`` row on Production before or after, so neither is a
    loss - they are here so that the word's blast radius stays a fact of
    the suite rather than a claim in a release note."""
    assert classify(title, body, known_event_type=ket) == "OTHER", ref
    assert _processed(title, body, published, ket)["events"] == [], ref


# --- T2/T5/T6/T7: everything the prior still decides -----------------------

@pytest.mark.parametrize("ref,title,body,published,ket,without_prior", KEPT_BY_THE_PRIOR,
                         ids=[row[0] for row in KEPT_BY_THE_PRIOR])
def test_the_prior_still_decides_every_post_that_does_not_disown_itself(
        ref, title, body, published, ket, without_prior):
    """The contract in one line: for a post the guard does not recognise,
    the prior is the answer - unchanged from engine 0.94."""
    assert not is_non_event_notice(title), (
        f"{ref}: a protected announcement now matches the non-event guard")
    assert classify(title, body, known_event_type=ket) == ket, ref


@pytest.mark.parametrize("ref,title,body,published,ket,without_prior", KEPT_BY_THE_PRIOR,
                         ids=[row[0] for row in KEPT_BY_THE_PRIOR])
def test_what_each_protected_post_reads_as_without_the_prior(
        ref, title, body, published, ket, without_prior):
    """Measured, not assumed. Eight of these ten lose their type entirely
    when the prior is taken away - that is the 324 Production events (56 of
    them upcoming) that deleting the feature would cost, which is why this
    release reorders it instead. The other two would not notice, and saying
    so here is what keeps the protection set honest."""
    assert classify(title, body) == without_prior, ref


def test_the_protection_set_is_not_made_only_of_easy_cases():
    """Guards the set itself: if every fixture classified correctly without
    the prior, the tests above would still pass while proving nothing about
    the feature they exist to protect."""
    depends = [r for r in KEPT_BY_THE_PRIOR if r[5] != r[4]]
    assert len(depends) >= 6, "protection set no longer exercises the prior"


@pytest.mark.parametrize("ref,title,body,published,ket,without_prior", KEPT_BY_THE_PRIOR,
                         ids=[row[0] for row in KEPT_BY_THE_PRIOR])
def test_a_protected_night_still_reaches_extraction(
        ref, title, body, published, ket, without_prior):
    """An event classification must still be handed to the extractor. What
    it makes of a title-only Naver row is its own business (a dateless post
    yields no candidate, exactly as before) - what matters here is that the
    classifier no longer stops it."""
    if ket not in EVENT_CLASSIFICATIONS:
        pytest.skip("CLASS reaches Events through the opt-in path, not here")
    assert _processed(title, body, published, ket)["classification"] == ket, ref


def test_the_milonga_directory_is_untouched():
    """SRC-W-005: 195 events, 51 upcoming, 0 false positives. Its entries are
    brand names ("orange") or names a keyword reading gets *wrong* rather
    than right - item 2103's "7:30 오픈강습" line reads MILONGA_WITH_CLASS
    on its own, which is not the type the listing page guarantees."""
    for ref, title, body, published, ket, without_prior in KEPT_BY_THE_PRIOR:
        if ref not in ("2070", "2103"):
            continue
        assert without_prior != "MILONGA", f"{ref}: no longer needs the prior"
        assert classify(title, body, known_event_type=ket) == "MILONGA", ref


# --- T8: a post with no prior classifies exactly as it did -----------------

@pytest.mark.parametrize("ref,title,body,published,expected", NO_PRIOR_UNCHANGED,
                         ids=[row[0] for row in NO_PRIOR_UNCHANGED])
def test_a_post_without_the_prior_is_unchanged(ref, title, body, published, expected):
    """The guard already ran first for these, so the precedence change
    cannot reach them. v0.96.5's rescues and v0.96.7's corrections, carried
    forward."""
    assert classify(title, body) == expected, ref


@pytest.mark.parametrize("ref,title,body,published,expected", NO_PRIOR_UNCHANGED,
                         ids=[row[0] for row in NO_PRIOR_UNCHANGED])
def test_a_post_without_the_prior_keeps_producing_what_it_did(
        ref, title, body, published, expected):
    events = _processed(title, body, published)["events"]
    if expected in EVENT_CLASSIFICATIONS:
        assert len(events) >= 1, f"{ref}: lost its event"
    else:
        assert events == [], f"{ref}: a lesson advert became an event"


# --- the contract, stated directly -----------------------------------------

def test_the_guard_is_the_only_rule_above_the_prior():
    """A post the guard does not recognise must still take the prior's
    answer without any further reading of its body - that is what "strong
    prior" means and what the 452 Production items depend on. A body full
    of lesson words does not change it."""
    body = "수강료 12만원 커리큘럼 1주차 개강 매주 토요일 6주 과정"
    assert classify("수라댄 금요정모", body, known_event_type="SOCIAL") == "SOCIAL"
    assert classify("까사밀롱가", body, known_event_type="MILONGA") == "MILONGA"
    # ...and the same post, once its title disowns itself, takes neither.
    assert classify("수라댄 금요정모 휴강", body, known_event_type="SOCIAL") == "OTHER"
    assert classify("지난 금요정모 후기", body, known_event_type="SOCIAL") == "OTHER"


def test_the_prior_is_not_re_read_through_the_classifier():
    """The rejected alternative: letting a post with a prior fall through
    the whole classifier and only using the prior as a tie-break. These two
    would classify CLASS and SOCIAL_WITH_CLASS respectively on their bodies
    alone, losing the type the collector's page structure guarantees."""
    assert classify("Milonga Dorada", "매주 화요일 오픈강습 7:30",
                    known_event_type="MILONGA") == "MILONGA"
    assert classify("살사아미고스 9.9.정모", "7:20~8:00 살사 오픈강습",
                    known_event_type="SOCIAL") == "SOCIAL"


def test_an_empty_title_still_takes_the_prior():
    """A blocked fetch with no title at all must not become OTHER: the
    guard is a positive test on a heading, never an absence one."""
    assert is_non_event_notice("") is False
    assert is_non_event_notice(None) is False
    assert classify("", "밀롱가 8시", known_event_type="MILONGA") == "MILONGA"
    assert classify(None, "", known_event_type="SOCIAL") == "SOCIAL"


def test_the_cancellation_word_is_exactly_one_word():
    """휴강 and nothing else. 폐강/연기/변경 were deliberately left out until
    they carry the same Production evidence, and a bare 취소 is still only
    read in the two bound forms the guard already had."""
    assert is_non_event_notice("금요정모 휴강")
    assert not is_non_event_notice("금요정모 폐강")
    assert not is_non_event_notice("금요정모 연기")
    assert not is_non_event_notice("금요정모 일정 변경")
    # the pre-existing bound forms, unchanged
    assert is_non_event_notice("금요정모 취소 안내")
    assert is_non_event_notice("금요정모 취소 및 환불")
    assert not is_non_event_notice("취소표 나왔습니다")
