"""v0.96.22 - read robots.txt the way robots.txt is defined.

`runtime.acquisition.robots_allows()` used `urllib.robotparser`, which answers a
different question than RFC 9309 asks. Two defects, each reproduced here
against the real robots.txt of a registered, enabled source:

1. precedence is file order, not specificity - `Entry.allowance()` returns the
   first matching rule, so `Allow: /` above `Disallow: /?genre=` allows
   everything;
2. no wildcards - `RuleLine.applies_to()` is `startswith`, and the constructor
   percent-encodes the pattern, so `Disallow: /?*&type=` becomes a literal
   `/?%2A&type=` that can never match.

A third was suspected and disproved: a query-string rule *can* match on its
own, on the deployed Python 3.12 and on 3.14. Only the two above are real.

Measured over all 1,148 URLs this project's acquisition requests: the corrected
reading changes exactly **one** decision, from allow to **block**. Nothing
becomes newly permitted. This is a compliance fix, not a coverage one - and the
release's own hypothesis (that a `Sitemap:` line was ending the rule group, and
that some source was therefore wrongly blocked) is disproved by T1-T3 below.
"""

from __future__ import annotations

import urllib.robotparser

import pytest

from runtime import robots

UA = "DanceMate"


def _stdlib(text: str, url: str, agent: str = UA) -> bool:
    """What v0.96.21 decided, for the before/after assertions."""
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(text.splitlines())
    return bool(parser.can_fetch(agent, url))


# --- T1-T3: Sitemap is not an access rule and never ends a group ----------

SITEMAP_AFTER = """\
User-agent: *
Allow: /

Sitemap: https://example.com/sitemap.xml

Disallow: /private/
"""

SITEMAP_BEFORE = """\
User-agent: *
Sitemap: https://example.com/sitemap.xml
Allow: /
Disallow: /private/
"""

SITEMAP_MANY = """\
Sitemap: https://example.com/a.xml
User-agent: *
Allow: /
Sitemap: https://example.com/b.xml
Disallow: /private/
Sitemap: https://example.com/c.xml
"""

NO_SITEMAP = """\
User-agent: *
Allow: /
Disallow: /private/
"""


@pytest.mark.parametrize("label,text", [
    ("Sitemap between the rules", SITEMAP_AFTER),
    ("Sitemap before the rules", SITEMAP_BEFORE),
    ("Sitemap three times", SITEMAP_MANY),
    ("no Sitemap at all", NO_SITEMAP),
])
def test_a_sitemap_line_changes_no_access_decision(label, text):
    """T1-T3. All four files mean the same thing, and the release's stated
    hypothesis is refuted by the fourth: the stdlib gets `/private/` wrong even
    with no `Sitemap` line anywhere, so `Sitemap` was never the cause."""
    assert robots.allows(text, "https://example.com/private/x", UA) is False, label
    assert robots.allows(text, "https://example.com/public/x", UA) is True, label
    assert _stdlib(text, "https://example.com/private/x") is True, (
        f"{label}: the stdlib's first-match rule allows it, with or without Sitemap")


def test_the_sitemap_url_is_not_treated_as_a_path_rule():
    text = "User-agent: *\nSitemap: https://example.com/sitemap.xml\n"
    assert robots.allows(text, "https://example.com/sitemap.xml", UA) is True
    assert robots.allows(text, "https://example.com/anything", UA) is True


# --- T4: empty Disallow ---------------------------------------------------

def test_an_empty_disallow_forbids_nothing():
    """T4. `Disallow:` with no value is the documented way to say "allow all"."""
    text = "User-agent: *\nDisallow:\n"
    assert robots.allows(text, "https://example.com/anything", UA) is True
    assert robots.allows(text, "https://example.com/", UA) is True


def test_an_empty_disallow_does_not_cancel_a_real_one():
    text = "User-agent: *\nDisallow:\nDisallow: /private/\n"
    assert robots.allows(text, "https://example.com/private/x", UA) is False
    assert robots.allows(text, "https://example.com/open", UA) is True


# --- T5/T6: precedence ----------------------------------------------------

def test_a_more_specific_allow_beats_a_broader_disallow():
    """T5. The shape RFC 9309 section 2.2.2 exists for."""
    text = "User-agent: *\nDisallow: /events/\nAllow: /events/public/\n"
    assert robots.allows(text, "https://example.com/events/public/1", UA) is True
    assert robots.allows(text, "https://example.com/events/private/1", UA) is False


def test_a_more_specific_disallow_beats_a_broader_allow():
    """T6. This is the defect: written in this order, the stdlib allows it."""
    text = "User-agent: *\nAllow: /\nDisallow: /events/private/\n"
    assert robots.allows(text, "https://example.com/events/private/1", UA) is False
    assert robots.allows(text, "https://example.com/events/public/1", UA) is True
    assert _stdlib(text, "https://example.com/events/private/1") is True


def test_file_order_no_longer_decides():
    """The same two rules either way round mean the same thing."""
    forward = "User-agent: *\nAllow: /\nDisallow: /x/\n"
    reverse = "User-agent: *\nDisallow: /x/\nAllow: /\n"
    for text in (forward, reverse):
        assert robots.allows(text, "https://example.com/x/1", UA) is False
        assert robots.allows(text, "https://example.com/y/1", UA) is True
    assert _stdlib(forward, "https://example.com/x/1") is True
    assert _stdlib(reverse, "https://example.com/x/1") is False


def test_an_exact_tie_goes_to_the_least_restrictive_rule():
    text = "User-agent: *\nDisallow: /both/\nAllow: /both/\n"
    assert robots.allows(text, "https://example.com/both/1", UA) is True


# --- T7/T8: user-agent groups --------------------------------------------

def test_several_user_agent_lines_share_one_group():
    """T7."""
    text = "User-agent: GPTBot\nUser-agent: DanceMate\nDisallow: /\n"
    assert robots.allows(text, "https://example.com/x", UA) is False
    assert robots.allows(text, "https://example.com/x", "SomeoneElse") is True


def test_a_group_naming_us_wins_over_the_star_group():
    """T8."""
    text = ("User-agent: *\nDisallow: /\n\n"
            "User-agent: DanceMate\nAllow: /\nDisallow: /admin/\n")
    assert robots.allows(text, "https://example.com/public", UA) is True
    assert robots.allows(text, "https://example.com/admin/x", UA) is False
    assert robots.allows(text, "https://example.com/public", "Otherbot") is False


def test_the_same_agent_named_twice_has_its_rules_merged():
    text = ("User-agent: DanceMate\nDisallow: /a/\n\n"
            "User-agent: DanceMate\nDisallow: /b/\n")
    assert robots.allows(text, "https://example.com/a/1", UA) is False
    assert robots.allows(text, "https://example.com/b/1", UA) is False
    assert robots.allows(text, "https://example.com/c/1", UA) is True


def test_a_group_we_are_not_is_not_ours():
    """Our HTTP header is a Mozilla-compatible string; a site's `Mozilla` group
    is not addressed to this crawler, and substring matching would claim it."""
    text = "User-agent: Mozilla\nDisallow: /\n"
    assert robots.allows(text, "https://example.com/x", UA) is True
    text2 = "User-agent: Amazonbot\nDisallow: /\n"
    assert robots.allows(text2, "https://example.com/x", UA) is True


def test_a_longer_spelling_of_our_token_still_matches():
    text = "User-agent: DanceMate/0.76\nDisallow: /x/\n"
    assert robots.allows(text, "https://example.com/x/1", UA) is False


def test_rules_before_any_user_agent_line_belong_to_nobody():
    text = "Disallow: /orphan/\nUser-agent: *\nDisallow: /real/\n"
    assert robots.allows(text, "https://example.com/orphan/1", UA) is True
    assert robots.allows(text, "https://example.com/real/1", UA) is False


# --- T9/T10: comments and whitespace -------------------------------------

def test_a_trailing_comment_is_not_part_of_the_path():
    """T9."""
    text = "User-agent: *\nDisallow: /private/ # keep crawlers out\n"
    assert robots.allows(text, "https://example.com/private/x", UA) is False
    assert robots.allows(text, "https://example.com/private/x#frag", UA) is False


def test_a_whole_line_comment_is_ignored():
    text = "# this is our robots file\nUser-agent: *\n# and a note\nDisallow: /p/\n"
    assert robots.allows(text, "https://example.com/p/1", UA) is False


def test_surrounding_whitespace_does_not_change_a_rule():
    """T10."""
    text = "  User-agent:   *  \n\t Disallow:   /private/   \n"
    assert robots.allows(text, "https://example.com/private/x", UA) is False
    assert robots.allows(text, "https://example.com/open", UA) is True


def test_a_blank_line_does_not_end_a_group():
    text = "User-agent: *\nAllow: /\n\nDisallow: /private/\n"
    assert robots.allows(text, "https://example.com/private/x", UA) is False


# --- T11/T12: field case, and fields we do not know ----------------------

def test_field_names_are_case_insensitive():
    """T11. 445 of the lines in the corpus this project fetches are mixed-case."""
    text = "USER-AGENT: *\nDISALLOW: /private/\nALLOW: /private/open\n"
    assert robots.allows(text, "https://example.com/private/x", UA) is False
    assert robots.allows(text, "https://example.com/private/open", UA) is True


def test_an_unknown_field_does_not_break_the_group():
    """T12. Crawl-delay, Host, Request-rate, anything: not an access rule, and
    not a reason to forget the rules around it."""
    text = ("User-agent: *\nCrawl-delay: 10\nAllow: /\n"
            "Request-rate: 1/10s\nDisallow: /private/\nHost: example.com\n")
    assert robots.allows(text, "https://example.com/private/x", UA) is False
    assert robots.allows(text, "https://example.com/open", UA) is True


def test_a_line_with_no_colon_is_ignored():
    text = "User-agent: *\nthis line is nonsense\nDisallow: /private/\n"
    assert robots.allows(text, "https://example.com/private/x", UA) is False


# --- wildcards and the end anchor ---------------------------------------

def test_a_star_inside_a_pattern_matches_any_run_of_characters():
    """socialdancelive.com writes six of these; sidf.kr writes eighty."""
    text = "User-agent: *\nAllow: /\nDisallow: /?*&type=\n"
    assert robots.allows(text, "https://example.com/?genre=salsa&type=posters",
                         UA) is False
    assert robots.allows(text, "https://example.com/?genre=salsa", UA) is True
    assert _stdlib(text, "https://example.com/?genre=salsa&type=posters") is True


def test_a_star_prefixed_pattern_matches_mid_path():
    text = "User-agent: *\nDisallow: /*?locale=\n"
    assert robots.allows(text, "https://example.com/events?locale=en", UA) is False
    assert robots.allows(text, "https://example.com/events?page=2", UA) is True


def test_a_trailing_dollar_anchors_the_end():
    """No robots file this project fetches uses `$` today. It is one line of the
    same matcher, and leaving it out would silently mis-read one that appears."""
    text = "User-agent: *\nDisallow: /*.pdf$\n"
    assert robots.allows(text, "https://example.com/a/b.pdf", UA) is False
    assert robots.allows(text, "https://example.com/a/b.pdf?v=1", UA) is True


def test_a_query_string_rule_matches_on_its_own_even_today():
    """The defect that was suspected and is not real.

    A query-string rule alone is handled correctly by the stdlib too, on the
    deployed Python 3.12 and on 3.14. It goes wrong only when an `Allow:` sits
    above it - which is defect 1, precedence, not encoding. Pinned so the
    release's claim about its own root cause stays honest.
    """
    text = "User-agent: *\nDisallow: /?genre="
    url = "https://example.com/?genre=salsa"
    assert robots.allows(text, url, UA) is False
    assert _stdlib(text, url) is False, "the stdlib gets this one right"

    with_allow = "User-agent: *\nAllow: /\nDisallow: /?genre="
    assert robots.allows(with_allow, url, UA) is False
    assert _stdlib(with_allow, url) is True, "and this one wrong, by precedence"


def test_a_url_with_no_path_is_the_site_root():
    text = "User-agent: *\nDisallow: /\n"
    assert robots.allows(text, "https://example.com", UA) is False
    assert robots.allows(text, "https://example.com/", UA) is False


# --- the decision is explainable ----------------------------------------

def test_the_winning_rule_is_reported():
    text = "User-agent: *\nAllow: /\nDisallow: /?*&type=\n"
    decision = robots.evaluate(text, "https://example.com/?a=1&type=x", UA)
    assert decision.allowed is False
    assert decision.agent == "*"
    assert decision.rule == "Disallow: /?*&type="


def test_no_rules_means_allowed():
    for text in ("", "# nothing here\n", "Sitemap: https://x/y.xml\n"):
        assert robots.allows(text, "https://example.com/anything", UA) is True
