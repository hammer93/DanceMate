"""robots.txt, read the way robots.txt is defined (RFC 9309).

v0.96.22. `runtime.acquisition.robots_allows()` used `urllib.robotparser`, and
that module answers a different question than the standard asks. Two defects,
each reproduced against a real registered source - socialdancelive.com, whose
`User-agent: *` group is `Allow: /` followed by nineteen `Disallow:` rules:

1. **Precedence is file order, not specificity.** `Entry.allowance()` returns
   the first rule that matches and stops::

       for line in self.rulelines:
           if line.applies_to(filename):
               return line.allowance

   So `Allow: /` written above `Disallow: /?genre=` allows everything. RFC 9309
   section 2.2.2 says the **most specific** (longest) match wins, and that a tie
   goes to the least restrictive rule.

2. **No wildcards.** `RuleLine.applies_to()` is
   `self.path == "*" or filename.startswith(self.path)`, and the constructor
   percent-encodes the pattern, so `Disallow: /?*&type=` is stored as
   `/?%2A&type=` - a literal asterisk that can never match. Two of the thirteen
   robots files this project actually fetches use `*` inside a pattern
   (socialdancelive.com 6 rules, sidf.kr 80).

A third defect was suspected - that a query-string rule could never match
because the request is percent-encoded - and **disproved**: verified on both the
deployed Python 3.12 and 3.14, `Disallow: /?genre=` on its own blocks
`/?genre=salsa` correctly. It is only ever the two defects above.

The effect is a **false allow**: this project has been fetching
`https://www.socialdancelive.com/?genre=salsa&type=posters`, which that site's
robots.txt disallows - by `Disallow: /?genre=`, which defect 1 hides behind the
`Allow: /` above it, and by `Disallow: /?*&type=`, which defect 2 cannot express
at all. This module exists to stop that. It
makes nothing newly permitted - measured over all 1,148 URLs acquisition
requests, the corrected reading changes exactly one decision, and it changes it
to BLOCK.

What this module deliberately does **not** decide: what to do when robots.txt
cannot be read. That policy (401/403 deny, other 4xx allow, 5xx and network
failure allow) lives in `acquisition.robots_allows()` where it always has, and
v0.96.22 does not move it. Parsing correctness is not crawling policy.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass

# "Field: value", with the field name case-insensitive and surrounding space
# irrelevant. Anything without a colon is not a directive.
_FIELD = re.compile(r"^\s*([A-Za-z][A-Za-z_-]*)\s*:\s*(.*?)\s*$")

_RULE_FIELDS = ("allow", "disallow")


@dataclass(frozen=True)
class Decision:
    """Why a URL was allowed or refused, so an operator can check the reasoning."""

    allowed: bool
    agent: str | None = None          # the group that decided, e.g. "*"
    rule: str | None = None           # the winning rule, e.g. "Disallow: /?genre="


def _strip_comment(line: str) -> str:
    """A `#` starts a comment. Nothing in a path pattern needs a literal one."""
    return line.split("#", 1)[0]


def parse(text: str) -> dict[str, list[tuple[bool, str]]]:
    """``{agent_token_lowercase: [(is_allow, pattern), ...]}``.

    A `User-agent` line after a rule starts a new group; consecutive
    `User-agent` lines share one group. Two groups naming the same agent are
    merged, which is what RFC 9309 section 2.2.1 asks for. Every field that is
    not `user-agent`/`allow`/`disallow` is ignored without ending the group -
    `Sitemap`, `Crawl-delay` and anything else a site chooses to write are not
    access rules, and must not make the rules around them disappear. That last
    point is what an earlier reading of this bug suspected as the cause; it is
    not (the fixtures in `tests/test_v09622_robots_semantics.py` prove a
    `Sitemap` line changes nothing either way), but the behaviour is still the
    correct one to have.
    """
    groups: dict[str, list[tuple[bool, str]]] = {}
    agents: list[str] = []
    seen_rule = False
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line.strip():
            continue
        match = _FIELD.match(line)
        if match is None:
            continue
        field = match.group(1).strip().lower()
        value = match.group(2).strip()
        if field == "user-agent":
            if seen_rule:
                agents = []
                seen_rule = False
            token = value.lower()
            agents.append(token)
            groups.setdefault(token, [])
        elif field in _RULE_FIELDS:
            if not agents:
                # A rule before any User-agent line belongs to no group.
                continue
            seen_rule = True
            for agent in agents:
                groups[agent].append((field == "allow", value))
    return groups


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    """`*` is any run of characters; a trailing `$` anchors the end."""
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    compiled = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.compile("^" + compiled + ("$" if anchored else ""))


def _specificity(pattern: str) -> int:
    """How specific a rule is: the length of the path it names.

    RFC 9309 section 2.2.2 counts the octets of the pattern. The `$` anchor is
    notation rather than path, so it does not add length.
    """
    return len(pattern[:-1] if pattern.endswith("$") else pattern)


def target_of(url: str) -> str:
    """The path (and query) a rule is matched against.

    Rules are written unencoded - `Disallow: /?genre=` - so the request is
    compared unencoded too. A URL with no path at all is the site root.
    """
    parsed = urllib.parse.urlparse(url)
    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"
    return target


def group_for(groups: dict[str, list[tuple[bool, str]]],
              product_token: str) -> tuple[str | None, list[tuple[bool, str]]]:
    """The group that governs this crawler.

    A group naming this crawler wins over `*`. Matching is case-insensitive on
    the product token, and a robots file may name it more fully than we do
    (`DanceMate/0.76`) or less fully (`DanceMate`) - either is a match, and the
    longer agreement wins when a file has both. Substring matching is
    deliberately not used: our HTTP header is a Mozilla-compatible string, and
    a site's `User-agent: Mozilla` group is not addressed to us.
    """
    token = (product_token or "").strip().lower()
    best: str | None = None
    for agent in groups:
        if agent == "*" or not agent:
            continue
        if token and (token.startswith(agent) or agent.startswith(token)):
            if best is None or len(agent) > len(best):
                best = agent
    if best is not None:
        return best, groups[best]
    if "*" in groups:
        return "*", groups["*"]
    return None, []


def evaluate(text: str, url: str, product_token: str) -> Decision:
    """Whether robots.txt permits this URL for this crawler.

    No group for us and no `*` group, or a group with no rule that matches:
    allowed, because robots.txt only ever restricts.
    """
    groups = parse(text)
    agent, rules = group_for(groups, product_token)
    if not rules:
        return Decision(True, agent, None)
    target = target_of(url)
    winner: tuple[int, bool, str] | None = None
    for is_allow, pattern in rules:
        if not pattern:
            # "Disallow:" with an empty value restricts nothing (RFC 9309
            # section 2.2.2); an empty "Allow:" likewise says nothing.
            continue
        if not _pattern_regex(pattern).match(target):
            continue
        score = _specificity(pattern)
        if winner is None or score > winner[0]:
            winner = (score, is_allow, pattern)
        elif score == winner[0] and is_allow and not winner[1]:
            # Equal specificity: the least restrictive rule wins.
            winner = (score, is_allow, pattern)
    if winner is None:
        return Decision(True, agent, None)
    label = ("Allow" if winner[1] else "Disallow") + ": " + winner[2]
    return Decision(winner[1], agent, label)


def allows(text: str, url: str, product_token: str = "DanceMate") -> bool:
    """`evaluate()`, as the single boolean the acquisition path asks for."""
    return evaluate(text, url, product_token).allowed
