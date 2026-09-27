"""v0.96.21: an English month naming a range of its own days.

`DATE_PATTERNS` held eight patterns and not one of them spoke English. Every
shape was numeric ("2026.10.08", "9.18-20", "10/8") or Korean ("10월 8일",
"9월 19,20일"), so a page that writes its dates for an English-reading audience
produced no date at all - not a wrong date, not an unplaceable one, nothing:

    >>> _norm_date("DATE Oct 8-11, 2026")
    (None, None, None)

SEOUL lindyfest 2026 is that page. v0.96.20 probed it live, found it
robots-permitted with its whole body fetching in full, and had to leave it as
WATCH for exactly this reason - a real upcoming Korean swing festival
(8-11 October 2026, BIG APPLE, Seoul) that the engine could not place on a
calendar.

**The contract this follows is the one that already existed.** v0.91.0 PHASE 5
added the numeric same-month range "9.18-20" (BAL&HOP's own page title) and
settled what a multi-day span means here: `event_date` is the range's **first
day**, and the full span is recorded as a `MULTI_DAY_EVENT` context evidence
with inference `DATE_RANGE_START_ONLY`, because `events` has no end-date
column. v0.92.0 did the identical thing for the Korean "9월 19,20일". This
release adds the English form and nothing else - no event per day, no invented
end date, no new provenance value.

**Measured before writing it**, over all 2,535 stored items and all 1,589
stored OCR texts: 20 English month tokens in 16 items, 27 in 21 OCR texts, and
**zero** same-month day ranges anywhere. A `git stash` baseline diff over the
whole corpus then changed **0** source_items - the shape is genuinely new
content, so the release moves no stored row and can break none.
"""

# --- A. the grammar this release supports ---------------------------------
#
# (text, expected ISO date). Every one carries its own year, so every one
# resolves EXPLICIT_YEAR with no anchor at all.
PARSED = [
    ("Oct 8-11, 2026", "2026-10-08"),
    ("Oct 8–11, 2026", "2026-10-08"),          # en dash
    ("Oct 8—11, 2026", "2026-10-08"),          # em dash
    ("October 8-11, 2026", "2026-10-08"),
    ("Oct. 8-11, 2026", "2026-10-08"),
    ("October 8–11, 2026", "2026-10-08"),
    ("Oct. 8–11, 2026", "2026-10-08"),
    ("OCT 8-11, 2026", "2026-10-08"),
    ("oct 8-11, 2026", "2026-10-08"),
    ("Oct 8 - 11, 2026", "2026-10-08"),             # spaced dash
    ("Oct 8–11,2026", "2026-10-08"),           # no space before the year
    ("Sep 28-30, 2026", "2026-09-28"),
    ("Sept 28-30, 2026", "2026-09-28"),
    ("Sept. 28-30, 2026", "2026-09-28"),
    ("September 28-30, 2026", "2026-09-28"),
    ("Dec 1-3, 2026", "2026-12-01"),
    ("May 1-2, 2026", "2026-05-01"),
    ("Feb 27-28, 2026", "2026-02-27"),
    ("Jan 30-31, 2026", "2026-01-30"),
    ("June 5-7, 2026", "2026-06-05"),
    ("Jul 4-6, 2026", "2026-07-04"),
    ("Aug 14-16, 2026", "2026-08-14"),
    ("Mar 6-8, 2026", "2026-03-06"),
    ("Apr 17-19, 2026", "2026-04-17"),
    ("Nov 20-22, 2026", "2026-11-20"),
    # the target's own sentence, with the words around it
    ("DATE Oct 8-11, 2026 LOCATION BIG APPLE, SEOUL", "2026-10-08"),
]

# Every month, long and short, so the vocabulary is not three names deep.
EVERY_MONTH = [
    ("January", 1), ("Jan", 1), ("February", 2), ("Feb", 2),
    ("March", 3), ("Mar", 3), ("April", 4), ("Apr", 4), ("May", 5),
    ("June", 6), ("Jun", 6), ("July", 7), ("Jul", 7),
    ("August", 8), ("Aug", 8), ("September", 9), ("Sept", 9), ("Sep", 9),
    ("October", 10), ("Oct", 10), ("November", 11), ("Nov", 11),
    ("December", 12), ("Dec", 12),
]

# --- B. written as a date, but not a date ---------------------------------
#
# A range that runs backwards, or names a day its month does not have, is a
# date somebody wrote that cannot be placed. It reads as a refusal - raw text
# recorded, no date - exactly as an impossible numeric date already does.
REFUSED_AS_UNPLACEABLE = [
    "Oct 11-8, 2026",          # backwards
    "Feb 29-30, 2026",         # 2026 is not a leap year
    "Sep 30-31, 2026",         # September has 30 days
    "Apr 29-31, 2026",         # April has 30 days
]

# --- C. not a date at all -------------------------------------------------
#
# These must not even register as a date attempt, so a later pattern is still
# free to read a real date from the same text.
NOT_A_DATE = [
    "Oct 0-4, 2026",                    # day zero
    "Oct 8-99, 2026",                   # two-digit nonsense
    "Apr 31-32, 2026",                  # both ends impossible
    "May Dance Better Workshop",        # a month's name used as a word
    "March Into Swing",
    "March into swing 8-11 people",     # 'March into' is not March the 8th
    "Octoberfest 8-11, 2026",           # month name inside a longer word
    "Marching 8-11, 2026",
    "Mayday 1-2, 2026",
    "Augmented 5-7, 2026",
    "Decorate 1-3, 2026",
    "Janitor 4-6, 2026",
]

# --- D. the existing contract, which must not move ------------------------
#
# The numeric and Korean forms of the same span, and the precedence rule that
# a more specific pattern placed earlier wins wherever it sits in the text.
# (text, published anchor or None, expected). The Korean day-list pattern
# carries no year group of its own, so it has always needed the post's date to
# resolve - unchanged here, and asserted with the anchor its real Production
# case had.
EXISTING_RANGES = [
    ("BAL&HOP 2026 - 9.18-20", None, "2026-09-18"),
    ("2026년 9월 19,20일 스윙타임빠", "2026-09-01", "2026-09-19"),
    ("9월 19,20일 스윙타임빠", "2026-09-01", "2026-09-19"),
    ("2026.10.08 스윙 소셜", None, "2026-10-08"),
    ("26.9.16.정모", None, "2026-09-16"),
    ("2026년 10월 8일 파티", None, "2026-10-08"),
]

# A Korean date in the title and an English range further down: the Korean
# pattern is earlier in DATE_PATTERNS and must still win.
KOREAN_WINS = (
    "2026년 9월 19일 정모 안내\n해외 행사: Oct 8-11, 2026 SEOUL lindyfest",
    "2026-09-19",
)

# --- E. SEOUL lindyfest, end to end --------------------------------------
#
# The page's own visible text, as `acquisition.fetch()` returns it (v0.96.20
# probe, `visible_text`, 1,070 characters). Trimmed of nothing that matters;
# the account number the page prints is already redacted by acquisition.
LINDYFEST_TITLE = "SEOUL lindyfest 2026"
LINDYFEST_BODY = (
    "SEOUL lindyfest 2026 SEOUL lindyfest 2026 Home People Artists Music Staff "
    "Special Guests Media SLF 2025 SLF 2024 SLF 2020 SLF 2019 SLF 2018 SLF 2017 "
    "SLF 2016 SLF 2015 Registration Policy Schedule Dance Session Competition "
    "Judges Results Venues DANCE SAFE Facebook Instagram YouTube Best Social "
    "dancing and Cultural Exchange SEOUL LINDYFEST 린디하퍼들을 위한 최고의 축제 "
    "서울린디페스트가 다시 돌아옵니다. 춤을 통해서 즐거움을 느끼고 다양한 문화적 "
    "교류를 함께하기를 바랍니다. DATE Oct 8-11, 2026 LOCATION BIG APPLE, SEOUL "
    "[계좌번호] days hours minutes seconds until SEOUL lindyfest 2026"
)
LINDYFEST_DATE = "2026-10-08"
LINDYFEST_SPAN_RAW = "Oct 8-11"
