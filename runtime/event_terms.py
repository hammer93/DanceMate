"""Event terminology: a scene's own words for its events, mapped to the Event
Formats DanceMate already classifies by (v0.86.9).

Tango calls the same kind of night by several names - 밀롱가 / Milonga,
쁘락띠까 / Practica - and some names mean more than one kind at once: a
쁘롱가 / Pronga is a practica and a milonga in one evening. The field word and
the canonical format are kept apart on purpose: the word is what a post
says, the format is what DanceMate files it under.

Nothing here invents a vocabulary. The canonical set is the existing Event
Format one in `runtime.events_api` (MILONGA / PRACTICA / GENERAL / SOCIAL),
and a term's genre scope is a foreign key into the existing genres master.

Three consumers:

* **Settings** manages the terms (`create_term` / `update_term` /
  `delete_term`, each validated here, never in the route).
* **Classification** - the engine's tango-social detection is handed the
  enabled words that stand for a milonga or a practica
  (`detection_terms`), so a word an operator adds is recognised on the next
  collection without a code change.
* **Normalization** stores which formats an event's own title resolved to
  (`resolve_event_terms`) in `events.event_formats`, the one place a
  two-format night can be recorded as two.

Matching is deliberately literal. A term is compared after NFKC, whitespace
collapse and lower-casing - never fuzzily. A Latin-script term must stand on
its own as a word ("practica" does not match "practical"); a Korean term
matches inside a longer run, because Korean attaches its particles
("쁘롱가에서"). When matches overlap, the longest one wins; separate,
non-overlapping matches all count.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

from . import events_api

# The canonical formats a term may map to: the existing Event Format
# vocabulary, minus UNKNOWN (which is the absence of a mapping, not one).
FORMAT_CHOICES = (
    events_api.EVENT_FORMAT_MILONGA,
    events_api.EVENT_FORMAT_PRACTICA,
    events_api.EVENT_FORMAT_GENERAL,
    events_api.EVENT_FORMAT_SOCIAL,
)

# The formats the engine's existing tango-social detection stands for: its
# own hardcoded words (밀롱가, 쁘롱, 쁘락) have always made a post a milonga
# or practica event. Terms mapped to these are what it is handed.
DETECTION_FORMATS = frozenset({events_api.EVENT_FORMAT_MILONGA,
                               events_api.EVENT_FORMAT_PRACTICA})

_SPACE = re.compile(r"\s+")


class TermError(ValueError):
    """The term cannot be saved as asked. The message is for an operator."""


def normalize_term(text: str | None) -> str:
    """The lookup form of a term or a title: NFKC, one space, lower case.

    engine/src/classifier.py restates this (the engine is stdlib-only and
    never imports runtime); tests/test_v0869_event_terminology.py holds the
    two to the same answers.
    """
    folded = unicodedata.normalize("NFKC", text or "")
    return _SPACE.sub(" ", folded).strip().lower()


def term_spans(normalized_term: str, normalized_text: str) -> list[tuple[int, int]]:
    """Where a normalized term occurs in normalized text.

    Latin-script terms need a word boundary on both sides; anything else
    (Korean) may sit inside a longer run.
    """
    if not normalized_term or not normalized_text:
        return []
    escaped = re.escape(normalized_term)
    if normalized_term.isascii():
        pattern = re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])")
    else:
        pattern = re.compile(escaped)
    return [(m.start(), m.end()) for m in pattern.finditer(normalized_text)]


def ordered_formats(formats: Iterable[str]) -> tuple[str, ...]:
    """Formats in the canonical order, so "밀롱가 + 쁘렉" never reads backwards."""
    wanted = set(formats or ())
    known = tuple(f for f in FORMAT_CHOICES if f in wanted)
    return known + tuple(sorted(wanted - set(FORMAT_CHOICES)))


def resolve_event_terms(text: str | None,
                        terms: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    """Which enabled terms a title uses, and the formats they stand for.

    ``terms`` are rows shaped like `list_terms()` returns. Returns None when
    no enabled term occurs - an unknown word is never forced into a format.
    Otherwise::

        {"term": "쁘롱가",                 # the primary (longest) match
         "terms": ["쁘롱가"],              # every counted match, in text order
         "formats": ("MILONGA", "PRACTICA"),
         "event_term_ids": [5]}

    Deterministic: overlapping matches keep the longest (ties: earliest,
    then alphabetical, then oldest id); non-overlapping matches all count.
    """
    haystack = normalize_term(text)
    if not haystack:
        return None
    hits: list[tuple[int, int, dict[str, Any]]] = []
    for row in terms or ():
        if not row.get("enabled", True) or not row.get("formats"):
            continue
        for start, end in term_spans(row.get("normalized_term") or "", haystack):
            hits.append((start, end, row))
    if not hits:
        return None
    hits.sort(key=lambda h: (-(h[1] - h[0]), h[0], h[2]["normalized_term"],
                             h[2].get("event_term_id") or 0))
    chosen: list[tuple[int, int, dict[str, Any]]] = []
    for start, end, row in hits:
        if any(start < c_end and c_start < end for c_start, c_end, _ in chosen):
            continue
        chosen.append((start, end, row))
    primary = chosen[0][2]
    seen: set[Any] = set()
    in_order: list[dict[str, Any]] = []
    for _, _, row in sorted(chosen, key=lambda h: h[0]):
        key = row.get("event_term_id") or row["normalized_term"]
        if key not in seen:
            seen.add(key)
            in_order.append(row)
    formats = ordered_formats(f for row in in_order for f in row["formats"])
    return {
        "term": primary["term"],
        "terms": [row["term"] for row in in_order],
        "formats": formats,
        "event_term_ids": [row.get("event_term_id") for row in in_order],
    }


def detection_terms(terms: Iterable[dict[str, Any]]) -> tuple[str, ...]:
    """The normalized words the engine's tango-social detection should also
    recognise: enabled terms that stand for a milonga or a practica."""
    words = {row["normalized_term"] for row in terms or ()
             if row.get("enabled", True)
             and DETECTION_FORMATS.intersection(row.get("formats") or ())}
    return tuple(sorted(words))


# --- storage -------------------------------------------------------------------

_SELECT = (
    "SELECT t.event_term_id, t.genre_id, g.code AS genre_code, g.name AS genre_name, "
    "       t.term, t.normalized_term, t.enabled, t.created_at, t.updated_at, "
    "       COALESCE(array_agg(f.event_format ORDER BY f.event_format) "
    "                FILTER (WHERE f.event_format IS NOT NULL), '{}') AS formats "
    "FROM event_terms t "
    "JOIN genres g ON g.genre_id = t.genre_id "
    "LEFT JOIN event_term_formats f ON f.event_term_id = t.event_term_id "
)
_GROUP = " GROUP BY t.event_term_id, g.code, g.name "


def _rows(cur) -> list[dict[str, Any]]:
    names = [c.name for c in cur.description]
    rows = [dict(zip(names, r)) for r in cur.fetchall()]
    for row in rows:
        row["formats"] = ordered_formats(row.get("formats") or ())
    return rows


def list_terms(con, *, genre_id: int | None = None,
               enabled_only: bool = False) -> list[dict[str, Any]]:
    clauses, params = [], []
    if genre_id is not None:
        clauses.append("t.genre_id = %s")
        params.append(genre_id)
    if enabled_only:
        clauses.append("t.enabled")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with con.cursor() as cur:
        cur.execute(_SELECT + where + _GROUP +
                    "ORDER BY g.code, t.normalized_term, t.event_term_id", params)
        return _rows(cur)


def get_term(con, event_term_id: int) -> dict[str, Any] | None:
    with con.cursor() as cur:
        cur.execute(_SELECT + "WHERE t.event_term_id = %s" + _GROUP, (event_term_id,))
        rows = _rows(cur)
    return rows[0] if rows else None


def terms_by_genre(con) -> dict[int, list[dict[str, Any]]]:
    """Every enabled term, grouped by genre - one query, for a whole batch."""
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in list_terms(con, enabled_only=True):
        grouped.setdefault(row["genre_id"], []).append(row)
    return grouped


def terms_for(grouped: dict[int, list[dict[str, Any]]] | None,
              genre_id: int | None) -> list[dict[str, Any]]:
    """A genre's own terms; every genre's when the genre is not known."""
    if not grouped:
        return []
    if genre_id is None:
        return [row for rows in grouped.values() for row in rows]
    return list(grouped.get(genre_id, []))


def _clean(con, *, genre_id: Any, term: str | None, formats: Iterable[str] | None,
           exclude_id: int | None = None) -> tuple[int, str, str, tuple[str, ...]]:
    display = (term or "").strip()
    normalized = normalize_term(display)
    if not normalized:
        raise TermError("용어를 입력하세요")
    try:
        genre = int(genre_id)
    except (TypeError, ValueError):
        raise TermError("장르를 선택하세요") from None
    chosen = [str(f).strip().upper() for f in (formats or ()) if str(f).strip()]
    unknown = sorted(set(chosen) - set(FORMAT_CHOICES))
    if unknown:
        raise TermError(f"알 수 없는 분류입니다: {', '.join(unknown)}")
    if not chosen:
        raise TermError("표준 분류를 하나 이상 선택하세요")
    with con.cursor() as cur:
        cur.execute("SELECT 1 FROM genres WHERE genre_id = %s", (genre,))
        if cur.fetchone() is None:
            raise TermError("존재하지 않는 장르입니다")
        cur.execute(
            "SELECT event_term_id FROM event_terms "
            "WHERE genre_id = %s AND normalized_term = %s AND event_term_id <> %s",
            (genre, normalized, exclude_id or 0),
        )
        if cur.fetchone() is not None:
            raise TermError(f"같은 장르에 이미 있는 용어입니다: {display}")
    return genre, display, normalized, ordered_formats(chosen)


def _write_formats(cur, event_term_id: int, formats: tuple[str, ...]) -> None:
    cur.execute("DELETE FROM event_term_formats WHERE event_term_id = %s", (event_term_id,))
    for fmt in formats:
        cur.execute(
            "INSERT INTO event_term_formats (event_term_id, event_format) VALUES (%s, %s)",
            (event_term_id, fmt),
        )


def create_term(con, *, genre_id: Any, term: str | None, formats: Iterable[str] | None,
                enabled: bool = True) -> dict[str, Any]:
    genre, display, normalized, chosen = _clean(con, genre_id=genre_id, term=term,
                                                formats=formats)
    with con.transaction():
        with con.cursor() as cur:
            cur.execute(
                "INSERT INTO event_terms (genre_id, term, normalized_term, enabled) "
                "VALUES (%s, %s, %s, %s) RETURNING event_term_id",
                (genre, display, normalized, bool(enabled)),
            )
            event_term_id = cur.fetchone()[0]
            _write_formats(cur, event_term_id, chosen)
    return get_term(con, event_term_id)


def update_term(con, event_term_id: int, *, genre_id: Any, term: str | None,
                formats: Iterable[str] | None, enabled: bool) -> dict[str, Any]:
    if get_term(con, event_term_id) is None:
        raise TermError(f"용어 {event_term_id}을(를) 찾을 수 없습니다")
    genre, display, normalized, chosen = _clean(con, genre_id=genre_id, term=term,
                                                formats=formats, exclude_id=event_term_id)
    with con.transaction():
        with con.cursor() as cur:
            cur.execute(
                "UPDATE event_terms SET genre_id = %s, term = %s, normalized_term = %s, "
                "       enabled = %s, updated_at = now() WHERE event_term_id = %s",
                (genre, display, normalized, bool(enabled), event_term_id),
            )
            _write_formats(cur, event_term_id, chosen)
    return get_term(con, event_term_id)


def delete_term(con, event_term_id: int) -> dict[str, Any]:
    """A term is referenced by nothing - an event stores the formats it
    resolved to, not the term id - so it can simply go."""
    existing = get_term(con, event_term_id)
    if existing is None:
        raise TermError(f"용어 {event_term_id}을(를) 찾을 수 없습니다")
    with con.cursor() as cur:
        cur.execute("DELETE FROM event_terms WHERE event_term_id = %s", (event_term_id,))
    return existing
