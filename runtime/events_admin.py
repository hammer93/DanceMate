"""v0.77 console pages: Events, Unresolved Venues, Duplicates.

Two of these exist because automation deliberately stopped short.

    Unresolved Venues -- the extractor read a place name off a post and the
    Venue Master does not know it. Registering it automatically would turn a
    typo, a landmark or a misread line into a permanent master record, so it
    waits here for someone to say "yes, that is that studio" or "no, that is
    not a venue at all".

    Duplicates -- the rules merged what they could settle and stopped at the
    pairs they could not. Same venue, three hours apart: that is either one
    event posted twice with a corrected time, or two events in one studio on a
    Saturday night. Only a person can tell, and their answer is final.

Shares admin.py's rendering, authentication and settings binding.
"""

from __future__ import annotations

import html
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import (
    admin,
    db,
    duplicates,
    events_api,
    master_data,
    normalization,
    venue_resolution,
)
from .admin_auth import require_admin

router = APIRouter()
api = APIRouter(prefix="/api/admin", tags=["admin"])

E = html.escape

VENUE_TONE = {
    normalization.VENUE_RESOLVED: "ok",
    normalization.VENUE_UNRESOLVED: "warn",
    normalization.VENUE_ABSENT: "muted",
}


def _connection():
    return admin._connection()


def _clock(value: Any) -> str:
    if value is None:
        return "-"
    return value.strftime("%H:%M") if hasattr(value, "strftime") else str(value)[:5]


# --- events -----------------------------------------------------------------

@router.get("/admin/events", response_class=HTMLResponse)
def admin_events(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    from . import pagination

    with _connection() as con:
        summary = normalization.metrics(con)
        duplicate_summary = duplicates.metrics(con)
        with con.cursor() as cur:
            cur.execute("SELECT count(*) FROM events")
            total = cur.fetchone()[0]
        page = pagination.resolve_page(request.query_params.get("page"), total)
        with con.cursor() as cur:
            cur.execute(
                # v0.94.0: the representative source (elected primary, else
                # the row's own) and how many folded posts stand behind it -
                # joined here, never looked up per row.
                "SELECT e.*, v.name AS venue_name, "
                "       src.name AS source_name, src.source_role, src.authority_level, "
                "       src.platform AS source_platform, "
                "       (COALESCE(si.raw->>'external_promotion', 'false') = 'true') "
                "         AS external_promotion, "
                "       (SELECT count(*) FROM events d WHERE d.canonical_event_id = e.event_id) "
                "         AS supporting "
                "FROM events e "
                "LEFT JOIN venues v ON v.venue_id = e.venue_id "
                "LEFT JOIN source_items si "
                "  ON si.source_item_id = COALESCE(e.primary_source_item_id, e.source_item_id) "
                "LEFT JOIN sources src ON src.source_id = si.source_id "
                "ORDER BY e.event_date DESC, e.start_time NULLS LAST, e.event_id "
                "LIMIT %s OFFSET %s",
                (pagination.PAGE_SIZE, pagination.sql_offset(page)),
            )
            names = [c.name for c in cur.description]
            rows = [dict(zip(names, row)) for row in cur.fetchall()]

    table = admin._table(
        ["Date", "Time", "Event", "Venue", "Fee", "Engine", "Review", "Source",
         "대표 출처", "Listing"],
        [
            [
                # v0.96.41: a festival's stated period, first day to last.
                E(str(row["event_date"])
                  + (f" ~ {row['end_date']}" if row.get("end_date") else "")),
                E(_clock(row["start_time"]) + " - " + _clock(row["end_time"])
                  + ("+1" if row["end_day_offset"] else "")),
                E(row["event_name"] or "-"),
                (E(row["venue_name"] or row["venue_text"] or "-") + " "
                 + admin._badge(row["venue_status"],
                                VENUE_TONE.get(row["venue_status"], "muted"))),
                f'{row["fee"]:,}' if row["fee"] is not None else "-",
                admin._badge(row["engine_status"],
                             "ok" if row["engine_status"] == "VERIFIED" else "warn"),
                E(row["review_state"]),
                admin._badge(row["provenance"],
                             "ok" if row["provenance"] == "LIVE" else "muted"),
                _primary_source_cell(row),
                (admin._badge("DUPLICATE", "muted")
                 if row["canonical_event_id"] else admin._badge(row["listing_state"],
                     "ok" if row["listing_state"] == "LISTED" else "muted")),
            ]
            for row in rows
        ],
        empty="no event normalised yet - run the event-normalization job",
    )

    cards = admin._cards([
        ("Events normalised", summary["total"], "one row per engine candidate"),
        ("Live", summary["live"], "traced to a live collection"),
        ("Listed to users", summary["listed"], "live, canonical, not rejected"),
        ("Venue resolved", summary["venue_resolved"], "matched to the Venue Master"),
        ("Venue unresolved", summary["venue_unresolved"],
         "read from a post, not recognised"),
        ("With a time", summary["with_time"], "start time extracted"),
        ("With a fee", summary["with_fee"], "fee extracted"),
        ("Auto-merged", duplicate_summary["auto_merged"],
         "same date, venue and start time"),
        ("Pairs for review", duplicate_summary["open_pairs"], "waiting on a person"),
    ])

    note = (
        '<p class="note">Only LIVE events appear on the user surface. A '
        "snapshot replay and a PoC fixture stay here and nowhere else.</p>"
    )
    body = "<h2>Events</h2>" + cards + note + table + pagination.nav(
        "/admin/events", {}, page, total
    )
    return HTMLResponse(admin._page("Events", "/admin/events", body,
                                    flash=admin._flash(request)))


# --- event sources (v0.94.0) -------------------------------------------------
#
# Which post represents an event, and every other post that stands behind
# it. Elected by runtime.duplicates.reconcile_primary_source(); a person can
# name a different post here, and that choice outlasts every later scan.

def _primary_source_cell(row: dict[str, Any]) -> str:
    from . import source_evidence

    evidence_class = source_evidence.classify(
        row.get("source_role"), row.get("authority_level"), row.get("source_platform"),
        bool(row.get("external_promotion")),
    )
    tone = "ok" if source_evidence.is_direct(evidence_class) else "muted"
    supporting = int(row.get("supporting") or 0)
    label = admin._badge(source_evidence.label_of(evidence_class), tone)
    name = E(row.get("source_name") or "-")
    extra = f" +{supporting}" if supporting else ""
    decided = " (사람)" if row.get("primary_source_decided_by") == duplicates.HUMAN else ""
    return (f'<a href="/admin/events/{row["event_id"]}/sources">{name}</a>{E(extra)}'
            f"<div class=\"note\">{label}{E(decided)}</div>")


@router.get("/admin/events/{event_id}/sources", response_class=HTMLResponse)
def admin_event_sources(event_id: int, request: Request,
                        _: str = Depends(require_admin)) -> HTMLResponse:
    from . import source_evidence

    with _connection() as con:
        members = duplicates.evidence_of(con, event_id)
        history = duplicates.primary_source_history(con, event_id) if members else []
    if not members:
        raise HTTPException(status_code=404, detail="no such event")
    head = next(m for m in members if m["is_canonical"])
    canonical_id = head["event_id"]
    back = f"/admin/events/{canonical_id}/sources"

    rows = []
    for m in members:
        flags = []
        if m["is_primary"]:
            flags.append(admin._badge("대표 출처", "ok"))
        if m["is_canonical"]:
            flags.append(admin._badge(f"canonical #{m['event_id']}", "muted"))
        else:
            flags.append(admin._badge(f"folded #{m['event_id']}", "muted"))
        if m.get("external_promotion"):
            flags.append(admin._badge("external promotion", "warn"))
        url = events_api.valid_public_url(m.get("source_url"))
        link = (f'<a href="{E(url)}" target="_blank" rel="noopener noreferrer">{E(url)}</a>'
                if url else "-")
        choose = ""
        if m.get("source_item_id") is not None and not m["is_primary"]:
            choose = (f'<form method="post" action="/admin/events/{canonical_id}/primary-source" '
                      f'class="inline"><input type="hidden" name="source_item_id" '
                      f'value="{m["source_item_id"]}">'
                      '<button class="primary" data-busy="...">대표 출처로 지정</button></form>')
        rows.append([
            " ".join(flags),
            f'{E(m.get("source_name") or "-")}<div class="note">{E(m.get("source_platform") or "-")}'
            f' · {E(m.get("source_role") or "-")} · {E(m.get("authority_level") or "-")}</div>',
            admin._badge(m["evidence_label"], "ok" if source_evidence.is_direct(m["evidence_class"])
                         else "muted") + f'<div class="note">{E(m["evidence_class"])}</div>',
            E(m.get("event_name") or "-"),
            E(_clock(m.get("start_time"))) + " · " + E(m.get("venue_text") or "-"),
            str(m["completeness"]),
            f'<div class="clip">{link}</div>',
            choose,
        ])
    table = admin._table(
        ["", "Source", "Evidence", "Post", "Time · Venue", "Completeness", "URL", ""], rows,
        empty="-",
    )

    reason = head.get("primary_source_reason") or "-"
    decided_by = head.get("primary_source_decided_by") or "AUTO (own post)"
    reset = ""
    if head.get("primary_source_decided_by") == duplicates.HUMAN:
        reset = (f'<form method="post" action="/admin/events/{canonical_id}/primary-source" '
                 'class="inline"><input type="hidden" name="action" value="reset">'
                 '<button data-busy="...">자동 판정으로 되돌리기</button></form>')
    cards = admin._cards([
        ("Event", f"#{canonical_id}", head.get("event_name") or ""),
        ("Posts", len(members), "canonical + folded duplicates"),
        ("Decided by", decided_by, "HUMAN outlasts every scan"),
    ])
    history_rows = [
        [E(str(h["decided_at"])[:16]), E(h["decided_by"]),
         E(h.get("source_name") or (str(h["source_item_id"]) if h["source_item_id"] else "own post")),
         E(h.get("evidence_class") or "-"), E(h.get("reason") or "-"), E(h.get("reviewer") or "-")]
        for h in history
    ]
    body = (
        f"<h2>Event #{canonical_id} - 출처 근거</h2>" + cards
        + f'<p class="note">Reconciliation 근거: {E(reason)}</p>' + reset
        + table
        + "<h3>History</h3>"
        + admin._table(["When", "By", "Representative", "Class", "Reason", "Reviewer"],
                       history_rows, empty="no change of representative recorded yet")
        + '<p class="note">우선순위: 주최 공식 &gt; 주최/동호회 &gt; 장소 공식 &gt; 홍보/공유 &gt; '
          "일정모음 &gt; 검색 결과. 같은 등급끼리는 바꾸지 않고, 날짜·장소·시간이 어긋나는 "
          "게시물은 대표가 되지 않습니다. external promotion으로 표시된 글은 홍보/공유 "
          "이상으로 올라가지 않습니다.</p>"
        + f'<p><a href="/admin/events">&larr; Events</a></p>'
    )
    return HTMLResponse(admin._page("Event Sources", "/admin/events", body,
                                    flash=admin._flash(request)))


@router.post("/admin/events/{event_id}/primary-source")
def admin_set_primary_source(
    event_id: int,
    action: str = Form(""),
    source_item_id: str = Form(""),
    reviewer: str = Depends(require_admin),
) -> RedirectResponse:
    target = f"/admin/events/{event_id}/sources"
    try:
        with _connection() as con:
            if action == "reset":
                result = duplicates.reset_primary_source(con, event_id, reviewer=reviewer)
                return admin._back(target, f"automatic selection: {result['reason']}")
            item = int(source_item_id)
            duplicates.set_primary_source(con, event_id, item, reviewer=reviewer)
    except (ValueError, LookupError) as exc:
        return admin._back(target, f"could not set the representative: {exc}", "bad")
    return admin._back(target, f"representative set to source item #{source_item_id}")


# --- unresolved venues ------------------------------------------------------
#
# The one screen where a venue string becomes a venue. Everything needed to
# decide is here -- what the post said, whether we already know the place, and
# a form prefilled from the string itself -- because the alternative was a trip
# to /admin/venues and back, and an operator who has left the queue to create a
# venue has lost the context they were about to use it for.
#
# No JavaScript framework. The New Venue form and the Not-a-venue confirmation
# are <details> blocks, which work with scripting off and need nothing loaded.

def _source_context(entry: dict[str, Any], sources: list[dict[str, Any]]) -> str:
    """The posts this string came from, with a line of surrounding text.

    "OCHO" could be a studio or the name of the event. Only the post says
    which, so the post is one click away and a snippet is already on screen.
    """
    if not sources:
        return ('<p class="note">No post is currently waiting on this string — '
                "it may already have been resolved or re-extracted.</p>")
    items = []
    for source in sources:
        link = (f'<a href="{E(source["source_url"])}" target="_blank" '
                f'rel="nofollow noopener">원문 보기</a>'
                if source.get("source_url") else '<span class="muted">no link</span>')
        snippet = (f'<div class="snippet">{E(source["snippet"])}</div>'
                   if source.get("snippet") else
                   '<div class="snippet">(본문에서 해당 문자열 주변을 찾지 못했습니다)</div>')
        items.append(
            f'<li><strong>{E(str(source["event_date"]))}</strong> '
            f'{E((source["event_name"] or "")[:60])} &middot; {link}{snippet}</li>'
        )
    return f'<ul class="sources">{"".join(items)}</ul>'


def _new_venue_form(entry: dict[str, Any], suggestion: dict[str, Any],
                    regions: list[dict[str, Any]], region_id: int | None,
                    *, open_form: bool = False, force: bool = False) -> str:
    """The New Venue form, prefilled from the raw string. Nothing is saved yet."""
    options = "".join(
        f'<option value="{r["region_id"]}"'
        + (" selected" if region_id == r["region_id"] else "")
        + f">{E(r['name'])}</option>"
        for r in regions
    )
    aliases = ", ".join(suggestion["aliases"])
    source = suggestion.get("address_source")
    told = []
    if suggestion["split_inferred"]:
        told.append("이름과 주소는 원문 문자열에서 나눈 값입니다")
    if source == "the post":
        told.append("주소는 게시글 본문에서 가져왔습니다")
    if suggestion.get("region_id"):
        told.append("지역은 주소를 보고 선택했습니다")
    inferred = (
        f'<p class="note">{E(", ".join(told))}. 저장 전에 확인하고, 틀렸으면 '
        "고치거나 지우세요.</p>" if told else ""
    )
    return f"""
<details class="newvenue"{' open' if open_form else ''}>
  <summary>New Venue</summary>
  <form method="post" action="/admin/venues/unresolved/{entry['unresolved_venue_id']}/create/preview">
    <div class="grid">
      <div><label>Name</label>
        <input name="name" value="{E(suggestion['name'])}" required></div>
      <div><label>Region</label>
        <select name="region_id"><option value="">-</option>{options}</select></div>
      <div><label>Address</label>
        <input name="address" value="{E(suggestion['address'] or '')}"></div>
      <div><label>Aliases (comma separated)</label>
        <input name="aliases" value="{E(aliases)}"></div>
      <div><label>Notes</label><input name="notes"></div>
    </div>
    {inferred}
    <p class="note">원문 문자열 <code>{E(entry['venue_text'])}</code> 은 자동으로
    alias에 포함됩니다 — 다음 수집부터 이 표현이 바로 인식됩니다.</p>
    <div class="actions">
      <input type="hidden" name="force" value="{'1' if force else '0'}">
      <button class="primary">Preview &middot; Create &amp; Link</button>
    </div>
    <p class="note">아직 저장되지 않습니다. 다음 화면에서 바뀌는 Event와 지역을 확인한 뒤
    승인해야 반영됩니다.</p>
  </form>
</details>"""


def _confidence_badge(confidence: str) -> str:
    tone = {"HIGH": "ok", "MEDIUM": "warn", "LOW": "muted"}.get(confidence, "muted")
    return admin._badge(confidence, tone)


def _link_suggestions_block(key: int, ranked: list[dict[str, Any]]) -> str:
    """Up to 3 ranked existing-venue candidates, each its own one-click Link
    Existing - never pre-selected, never submitted without the operator
    pressing the button themselves. Confidence and *why* travel together:
    a bare score is exactly the "warning nobody can check" this project
    already decided not to ship (venue_resolution.similar_venues())."""
    if not ranked:
        return ""
    rows = []
    for candidate in ranked:
        reasons = ", ".join(candidate.get("match_reasons") or ["registered alias/name/address"])
        rows.append(
            '<li>'
            f'{_confidence_badge(candidate["confidence"])} '
            f'<strong>{E(candidate["name"])}</strong>'
            + (f' &middot; {E(candidate["region_name"])}' if candidate.get("region_name") else "")
            + (f' &middot; {E(candidate["address"])}' if candidate.get("address") else "")
            + f' <span class="muted">{E(reasons)}</span> '
            f'<form class="inline" method="post" '
            f'action="/admin/venues/unresolved/{key}/link/preview">'
            f'<input type="hidden" name="venue_id" value="{candidate["venue_id"]}">'
            '<input type="hidden" name="add_alias" value="1">'
            '<button class="primary">Preview Link</button></form></li>'
        )
    return (
        '<div class="suggestions"><p class="note">추천 (자동 연결 아님, 확인 후 클릭):</p>'
        f'<ul class="sources">{"".join(rows)}</ul></div>'
    )


def _group_apply_block(key: int, group_ids: list[int], ranked: list[dict[str, Any]]) -> str:
    """Offered only when this entry is not alone in its group and the group's
    own top suggestion is confident enough to pre-fill - the operator still
    picks the venue and still presses Preview before anything is applied
    (spec item 10: preview 후 적용)."""
    others = [i for i in group_ids if i != key]
    if not others:
        return ""
    hidden = "".join(
        f'<input type="hidden" name="unresolved_venue_id" value="{i}">' for i in group_ids
    )
    prefill_venue_id = ""
    if ranked and ranked[0]["confidence"] != venue_resolution.CONFIDENCE_LOW:
        prefill_venue_id = str(ranked[0]["venue_id"])
    return f"""
<details>
  <summary>같은 장소로 보이는 대기열 {len(group_ids)}건 함께 처리</summary>
  <form method="post" action="/admin/venues/unresolved/group-link/preview">
    {hidden}
    <div><label>연결할 장소 (Venue ID)</label>
      <input name="venue_id" value="{E(prefill_venue_id)}" placeholder="venue id" required></div>
    <div class="actions"><button class="primary">Preview</button></div>
  </form>
</details>"""


#: v0.96.37: which part of the queue to show. The default leaves out strings no
#: event is waiting on any more - deciding them changes nothing a dancer sees -
#: and says how many it left out.
QUEUE_VIEWS = {
    "waiting": "대기 Event 있음",
    "upcoming": "예정 Event 있음",
    "address": "주소 확인됨",
    "all": "전체",
}


def _evidence_quality(entry: dict[str, Any], suggestion: dict[str, Any]) -> str:
    """How much the post says about where this is - not a verdict on it."""
    if not entry.get("event_count"):
        return admin._badge("NO EVENTS", "muted")
    if suggestion.get("address"):
        return admin._badge("ADDRESS", "ok")
    return admin._badge("NAME ONLY", "warn")


def _genres_by_text(con) -> dict[str, list[str]]:
    """Genre codes of the events waiting on each string, in one query."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT lower(e.venue_text), coalesce(g.code, '-'), count(*) "
            "FROM events e LEFT JOIN genres g ON g.genre_id = e.genre_id "
            "WHERE e.venue_status = 'UNRESOLVED' AND e.venue_text IS NOT NULL "
            "GROUP BY 1, 2 ORDER BY 1, 3 DESC"
        )
        found: dict[str, list[str]] = {}
        for text, code, count in cur.fetchall():
            found.setdefault(text, []).append(f"{code} {count}")
    return found


def _recent_decisions_block(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    items = "".join(
        f'<li><code>{E(r["raw_venue"])}</code> &middot; {E(r["action"])}'
        + (f' &rarr; {E(r["resolved_venue_name"])}' if r.get("resolved_venue_name") else "")
        + f' &middot; {E(r["reviewer"])} {E(str(r["created_at"])[:16])} '
        f'<form class="inline" method="post" '
        f'action="/admin/venues/unresolved/{r["unresolved_venue_id"]}/revert/preview">'
        '<button>Preview Revert</button></form></li>'
        for r in rows
    )
    return (
        "<details><summary>최근 결정 (정정하려면 Revert)</summary>"
        '<p class="note">Revert는 그 결정 하나만 되돌립니다: 그 문자열의 alias, 그 결정이 옮긴 '
        "Event의 장소·지역, 그 Event들의 자동 병합. 사람이 내린 병합 판정과 원래 결정의 감사 "
        "기록은 그대로 남습니다. 먼저 미리보기가 열립니다.</p>"
        f'<ul class="sources">{items}</ul></details>'
    )


@router.get("/admin/venues/unresolved", response_class=HTMLResponse)
def admin_unresolved_venues(request: Request,
                            _: str = Depends(require_admin)) -> HTMLResponse:
    view = request.query_params.get("show") or "waiting"
    if view not in QUEUE_VIEWS:
        view = "waiting"
    genre = (request.query_params.get("genre") or "").upper()
    with _connection() as con:
        everything = normalization.unresolved_venues(con, limit=5000)
        venues = master_data.list_venues(con, enabled_only=True)
        regions = master_data.list_regions(con, enabled_only=True)
        region_names = {r["region_id"]: r["name"] for r in regions}
        genres = _genres_by_text(con)
        suggestions = {
            entry["unresolved_venue_id"]: venue_resolution.prefill(con, entry)
            for entry in everything if entry.get("event_count")
        }

        def keep(entry: dict[str, Any]) -> bool:
            key = entry["unresolved_venue_id"]
            if genre and not any(g.startswith(genre + " ")
                                 for g in genres.get(entry["venue_text"].lower(), [])):
                return False
            if view == "all":
                return True
            if not entry.get("event_count"):
                return False
            if view == "upcoming":
                return bool(entry.get("upcoming_event_count"))
            if view == "address":
                return bool(suggestions[key].get("address"))
            return True

        pending = [e for e in everything if keep(e)]
        for entry in pending:
            suggestions.setdefault(entry["unresolved_venue_id"],
                                   venue_resolution.prefill(con, entry))
        contexts = {
            entry["unresolved_venue_id"]: venue_resolution.context(con, entry["venue_text"])
            for entry in pending
        }
        region_ids = {key: s["region_id"] for key, s in suggestions.items()}
        link_suggestions = {
            entry["unresolved_venue_id"]: venue_resolution.suggest_venue_links(
                con, name=suggestions[entry["unresolved_venue_id"]]["name"],
                address=suggestions[entry["unresolved_venue_id"]]["address"],
                raw_venue=entry["venue_text"], region_id=region_ids[entry["unresolved_venue_id"]],
            )
            for entry in pending
        }
        groups = venue_resolution.group_unresolved(pending, link_suggestions)
        group_of = {uid: group for group in groups for uid in group}
        decisions = venue_resolution.recent_decisions(con)

    options = "".join(
        f'<option value="{v["venue_id"]}">{E(v["name"])}'
        + (f' ({E(v["region_name"])})' if v.get("region_name") else "")
        + "</option>"
        for v in venues
    )

    banner = "" if venues else (
        '<div class="callout"><h3>등록된 장소가 아직 없습니다</h3>'
        "<p>여기서 바로 만들 수 있습니다. 아래 항목의 <strong>New Venue</strong>를 "
        "누르면 원문 문자열로 채워진 양식이 열리고, 저장과 동시에 대기 중인 "
        "Event가 정리됩니다. Venues 화면으로 옮겨갈 필요가 없습니다.</p></div>"
    )

    # Review order (v0.96.37): the SQL already sorts by what a dancer would see
    # change - upcoming listed events first, then live posts, then everything
    # waiting - so the page keeps that order instead of re-sorting it.
    items = []
    for entry in pending:
        key = entry["unresolved_venue_id"]
        suggestion = suggestions[key]
        also = ", ".join(E(str(a)) for a in (entry.get("alias_candidates") or [])
                         if str(a) != entry["venue_text"])
        if venues:
            link_form = (
                f'<form class="inline" method="post" '
                f'action="/admin/venues/unresolved/{key}/link/preview">'
                f'<select name="venue_id" required>'
                f'<option value="">기존 장소 선택…</option>{options}</select> '
                f'<label class="muted"><input type="checkbox" name="add_alias" '
                'value="1" checked> alias로 등록</label> '
                '<button class="primary">Preview Link</button></form>'
            )
        else:
            link_form = ('<span class="badge muted">No venues registered yet</span>')

        live = entry.get("live_event_count") or 0
        # A string only a fixture ever produced has no post to read, and a
        # decision about it changes nothing a dancer sees. Say so rather than
        # letting it sit in the queue looking like the others.
        live_note = (f" (live {live}건)" if live and live != (entry.get("event_count") or 0)
                     else "" if live else
                     ' <span class="badge muted">live 게시글 없음</span>')
        address = suggestion.get("address")
        address_note = (
            f'<span>주소: {E(address)} <span class="muted">({E(suggestion.get("address_source") or "")})</span></span>'
            if address else '<span class="muted">주소 근거 없음</span>'
        )
        region_note = (
            f'<span>지역 근거: {E(region_names.get(region_ids[key], str(region_ids[key])))}</span>'
            if region_ids.get(key) else '<span class="muted">지역 근거 없음</span>'
        )

        dismiss_form = f"""
<details>
  <summary>Not a venue</summary>
  <form method="post" action="/admin/venues/unresolved/{key}/dismiss">
    <p class="note">이 문자열을 장소가 아닌 것으로 처리합니다. 원문과 근거는
    삭제되지 않고, 이 문자열만 대기열에서 내려갑니다.</p>
    <div><label>사유 (선택)</label>
      <input name="reason" placeholder="행사명 / 건물 층수 / 오추출 등"></div>
    <div class="actions"><button>확인, 장소가 아닙니다</button></div>
  </form>
</details>"""

        items.append(f"""
<section class="item">
  <div class="raw">{E(entry['venue_text'])} {_evidence_quality(entry, suggestion)}</div>
  <div class="facts">
    <span>예정 노출 Event {entry.get('upcoming_event_count') or 0}건</span>
    <span>대기 중 Event {entry.get('event_count') or 0}건{live_note}</span>
    {address_note}
    {region_note}
    <span>장르: {E(', '.join(genres.get(entry['venue_text'].lower(), [])) or '-')}</span>
    <span>처음 발견 {E(str(entry['first_seen_at'])[:16])} &middot; 마지막 {E(str(entry['last_seen_at'])[:16])}</span>
    {f'<span>Also tried: {also}</span>' if also else ''}
  </div>
  {_source_context(entry, contexts[key])}
  {_link_suggestions_block(key, link_suggestions[key])}
  <div class="actionbar">
    {link_form}
    {_new_venue_form(entry, suggestion, regions, region_ids[key])}
    {dismiss_form}
  </div>
  {_group_apply_block(key, group_of[key], link_suggestions[key])}
</section>""")

    waiting = [e for e in everything if e.get("event_count")]
    cards = admin._cards([
        ("OPEN", len(everything), "queue entries not yet decided"),
        ("Events waiting", len(waiting), "entries with an event waiting on them"),
        ("Address known", sum(1 for e in waiting if suggestions[e["unresolved_venue_id"]].get("address")),
         "an address the string or its posts agree on"),
        ("Upcoming listed", sum(e.get("upcoming_event_count") or 0 for e in everything),
         "events still to come that a decision would place"),
    ])
    tabs = " &middot; ".join(
        (f"<strong>{E(label)}</strong>" if name == view else
         f'<a href="/admin/venues/unresolved?show={name}'
         + (f"&genre={E(genre)}" if genre else "") + f'">{E(label)}</a>')
        for name, label in QUEUE_VIEWS.items()
    )
    hidden = len(everything) - len(pending)
    note = (
        '<p class="note">이 문자열들은 추출기가 게시글에서 읽었지만 Venue Master가 '
        "알지 못하는 것입니다. 어느 결정이든 먼저 미리보기를 열어 바뀌는 Event, 지역, "
        "병합 가능성을 보여 주고, 승인해야만 반영됩니다. 자동 등록은 하지 않습니다 — "
        "잘못 읽은 한 줄이 영구 마스터 레코드가 되면 안 됩니다.</p>"
        f'<p class="note">보기: {tabs}'
        + (f" &middot; 장르 {E(genre)}" if genre else "")
        + (f" &middot; 이 보기에서 제외된 항목 {hidden}건" if hidden else "")
        + "</p>"
    )
    body = ("<h2>Unresolved Venues</h2>" + banner + cards + note
            + _recent_decisions_block(decisions)
            + (f'<div class="queue">{"".join(items)}</div>' if items
               else '<div class="tablewrap"><table><tbody><tr><td>'
                    "every venue we have read is recognised</td></tr></tbody></table></div>"))
    return HTMLResponse(admin._page("Unresolved Venues", "/admin/venues", body,
                                    flash=admin._flash(request)))


# --- previews and confirms (v0.96.37) ----------------------------------------
#
# Every decision is two requests. The preview is a POST only because it takes
# a form; it opens an autocommit connection and calls nothing that writes. The
# confirm carries the token the preview computed and is refused - with nothing
# written - when the token no longer matches what it would do.

_QUEUE = "/admin/venues/unresolved"


def _clock_range(event: dict[str, Any]) -> str:
    start, end = _clock(event.get("start_time")), event.get("end_time")
    if end is None:
        return start
    return f"{start}~{_clock(end)}" + ("(+1)" if event.get("end_day_offset") else "")


def _hidden(fields: dict[str, Any]) -> str:
    out = []
    for name, value in fields.items():
        for one in (value if isinstance(value, list) else [value]):
            out.append(f'<input type="hidden" name="{E(name)}" value="{E(str(one))}">')
    return "".join(out)


def _events_table(events: list[dict[str, Any]], venue_label: str) -> str:
    rows = [[
        f'#{e["event_id"]}',
        E(str(e["event_date"])),
        E((e.get("event_name") or "")[:50]),
        E(e.get("event_type") or "-"),
        E(_clock_range(e)),
        E(f'{e.get("venue_text") or "-"}') + (" (resolved)" if e.get("venue_id") else ""),
        E(f'#{e["proposed_venue_id"]} {e["proposed_venue_name"]}'
          if e.get("proposed_venue_name") else venue_label),
        E(e.get("region_code") or "-") + " &rarr; " + E(e.get("proposed_region_code") or "-"),
        ("바뀜" if e["identity_changes"] else "유지"),
        (f'folded into #{e["canonical_event_id"]}' if e.get("canonical_event_id")
         else "공개" if e.get("publicly_visible") else "비공개"),
    ] for e in events]
    return admin._table(
        ["Event", "Date", "Title", "Type", "Start/End", "Current venue", "Proposed venue",
         "Region", "Identity key", "Now"],
        rows, empty="이 결정으로 바뀌는 Event가 없습니다")


def _canonical_table(outlook: list[dict[str, Any]]) -> str:
    rows = [[f'#{o["event_id"]}', f'#{o["other_event_id"]}',
             E((o.get("other_event_name") or "")[:40]), E(o.get("rule") or ""),
             E(o["outcome"])] for o in outlook]
    return admin._table(["Event", "Other", "Other title", "Rule", "Next duplicates scan"],
                        rows, empty="다른 Event와 병합될 가능성이 없습니다")


def _also_linked_block(events: list[dict[str, Any]]) -> str:
    if not events:
        return ""
    rows = [[f'#{e["event_id"]}', E(str(e["event_date"])), E((e.get("event_name") or "")[:50]),
             E(e.get("venue_text") or "-"), E(e.get("matched_on") or "-"),
             "공개" if e.get("publicly_visible") else "비공개"] for e in events]
    return ("<h3>다음 정규화에서 함께 연결되는 Event</h3>"
            '<p class="note">이 결정이 등록하는 철자를 게시글이 읽고 있어, 승인 후 다음 정규화가 '
            "이 Event들도 같은 장소로 연결합니다. 승인 자체는 위 표의 Event만 바꿉니다.</p>"
            + admin._table(["Event", "Date", "Title", "Venue text", "Matched spelling", "Now"],
                           rows, empty=""))


def _preview_page(title: str, preview: dict[str, Any], *, venue_label: str,
                  facts: str, confirm_action: str, fields: dict[str, Any],
                  confirm_label: str, extra: str = "", form_extra: str = "") -> HTMLResponse:
    summary = preview["summary"]
    cards = admin._cards([
        ("Events", summary["events"], "this decision changes"),
        ("Public now", summary["publicly_visible"], "of them shown to dancers"),
        ("Upcoming public", summary["upcoming_visible"], "still to come"),
        ("Region changes", summary["region_changes"], "what the region filter sees"),
        ("Identity keys", summary["identity_changes"], "recomputed from the venue"),
        ("Folds", summary.get("predicted_auto_folds", summary.get("released_folds", 0)),
         "automatic merges this makes or releases"),
    ])
    blockers = "".join(f"<li>{E(b)}</li>" for b in preview["blockers"])
    warnings = "".join(f"<li>{E(w)}</li>" for w in preview["warnings"])
    if preview["blockers"]:
        decision = (
            '<div class="callout"><h3>승인할 수 없습니다</h3>'
            f'<ul class="sources">{blockers}</ul>'
            "<p class=\"note\">아무것도 저장되지 않았습니다.</p></div>"
        )
    else:
        decision = (
            f'<form method="post" action="{E(confirm_action)}">'
            + _hidden({**fields, "token": preview["token"]})
            + form_extra
            + f'<div class="actions"><button class="primary">{confirm_label}</button> '
            f'<a href="{_QUEUE}"><button type="button">Cancel</button></a></div></form>'
            '<p class="note">승인 시점에 이 미리보기를 다시 계산해 위 내용과 같을 때만 '
            "반영합니다. 그 사이 대기열이나 Event가 바뀌었으면 아무것도 저장하지 않고 "
            "미리보기를 다시 요청합니다.</p>"
        )
    body = (
        f"<h2>Unresolved Venues</h2><div class=\"callout\"><h3>{E(title)}</h3>{facts}</div>"
        + cards
        + (f'<div class="callout"><h3>확인할 점</h3><ul class="sources">{warnings}</ul></div>'
           if warnings else "")
        + extra
        + "<h3>바뀌는 Event</h3>" + _events_table(preview["events"], venue_label)
        + _also_linked_block(preview.get("also_linked") or [])
        + "<h3>병합(canonical) 영향</h3>" + _canonical_table(preview["canonical"])
        + decision
        + f'<p class="note"><a href="{_QUEUE}">← 대기열로 돌아가기</a></p>'
    )
    return HTMLResponse(admin._page("Unresolved Venues", "/admin/venues", body),
                        status_code=409 if preview["blockers"] else 200)


def _alias_rows(plan: list[dict[str, Any]]) -> str:
    rows = [[E(a["alias"]), E(a["status"]),
             E(f'#{a["owner_venue_id"]} {a["owner_name"]}' if a.get("owner_venue_id") else "-")]
            for a in plan]
    return "<h3>Alias</h3>" + admin._table(["Spelling", "Status", "Owner today"], rows,
                                           empty="alias를 등록하지 않습니다")


def _evidence_block(entry: dict[str, Any], evidence: dict[str, Any]) -> str:
    return ("<h3>원문 근거</h3>"
            + (f'<p class="note">게시글들이 동의하는 주소: {E(evidence["post_address"])}</p>'
               if evidence.get("post_address") else "")
            + _source_context(entry, evidence["posts"]))


def _refused(message: str, reasons: list[str], status: int = 409) -> HTMLResponse:
    items = "".join(f"<li>{E(r)}</li>" for r in reasons)
    body = ("<h2>Unresolved Venues</h2>"
            f'<div class="callout"><h3>{E(message)}</h3><ul class="sources">{items}</ul>'
            "<p class=\"note\">아무것도 저장되지 않았습니다.</p></div>"
            f'<p class="note"><a href="{_QUEUE}">← 대기열로 돌아가기</a></p>')
    return HTMLResponse(admin._page("Unresolved Venues", "/admin/venues", body),
                        status_code=status)


def _confirm(run) -> Any:
    """Run one confirm on its own transaction; a refusal writes nothing."""
    with db.connect(admin._settings()) as con:
        try:
            result = run(con)
            con.commit()
            return result
        except venue_resolution.StalePreview as exc:
            con.rollback()
            return _refused("미리보기 이후 내용이 바뀌었습니다", exc.reasons)
        except venue_resolution.DecisionRefused as exc:
            con.rollback()
            return _refused("승인할 수 없습니다", exc.reasons)
        except LookupError as exc:
            con.rollback()
            return _refused("찾을 수 없습니다", [str(exc)], status=404)
        except Exception as exc:
            con.rollback()
            return admin._back(_QUEUE, f"could not apply: {exc}", "bad")


@router.post("/admin/venues/unresolved/{unresolved_venue_id}/link/preview",
             response_class=HTMLResponse)
def admin_link_preview(
    unresolved_venue_id: int,
    venue_id: str = Form(""),
    add_alias: str = Form(""),
    reviewer: str = Depends(require_admin),
) -> Any:
    if not venue_id.isdigit():
        return admin._back(_QUEUE, "연결할 장소를 선택하세요", "bad")
    try:
        with _connection() as con:
            preview = venue_resolution.preview_link(
                con, unresolved_venue_id=unresolved_venue_id, venue_id=int(venue_id),
                add_alias=(add_alias == "1"), reviewer=reviewer, settings=admin._settings())
    except LookupError as exc:
        return _refused("찾을 수 없습니다", [str(exc)], status=404)
    venue, entry = preview["venue"], preview["entry"]
    label = f'#{venue["venue_id"]} {venue["name"]} ({venue.get("region_code") or "-"})'
    facts = (f'<p><code>{E(entry["venue_text"])}</code> &rarr; <strong>{E(label)}</strong>'
             + (f' &middot; {E(venue["address"])}' if venue.get("address") else "") + "</p>")
    return _preview_page(
        "Link Existing 미리보기", preview, venue_label=label, facts=facts,
        confirm_action=f"{_QUEUE}/{unresolved_venue_id}/link",
        fields={"venue_id": venue["venue_id"], "add_alias": "1" if preview["add_alias"] else "0"},
        confirm_label="Confirm &amp; Link",
        extra=_alias_rows(preview["alias_plan"]) + _evidence_block(entry, preview["evidence"]),
    )


@router.post("/admin/venues/unresolved/{unresolved_venue_id}/link")
def admin_link_existing_venue(
    unresolved_venue_id: int,
    venue_id: str = Form(""),
    add_alias: str = Form(""),
    token: str = Form(""),
    reviewer: str = Depends(require_admin),
) -> Any:
    if not venue_id.isdigit():
        return admin._back(_QUEUE, "연결할 장소를 선택하세요", "bad")
    result = _confirm(lambda con: venue_resolution.confirm_link(
        con, unresolved_venue_id=unresolved_venue_id, venue_id=int(venue_id),
        add_alias=(add_alias == "1"), token=token, reviewer=reviewer,
        settings=admin._settings()))
    if not isinstance(result, dict):
        return result
    return admin._back(
        _QUEUE,
        f"linked to {result['venue']['name']}; "
        f"{result['events_updated']} event(s) resolved",
    )


def _create_fields(name: str, region_id: str, address: str, aliases: str, notes: str,
                   force: str) -> dict[str, Any]:
    return {"name": name, "region_id": region_id, "address": address,
            "aliases": aliases, "notes": notes, "force": "1" if force == "1" else "0"}


def _create_args(fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": fields["name"],
        "region_id": int(fields["region_id"]) if str(fields["region_id"]).isdigit() else None,
        "address": fields["address"],
        "aliases": [a.strip() for a in fields["aliases"].split(",") if a.strip()],
        "notes": fields["notes"], "force": fields["force"] == "1",
    }


@router.post("/admin/venues/unresolved/{unresolved_venue_id}/create/preview",
             response_class=HTMLResponse)
def admin_create_preview(
    unresolved_venue_id: int,
    name: str = Form(""),
    region_id: str = Form(""),
    address: str = Form(""),
    aliases: str = Form(""),
    notes: str = Form(""),
    force: str = Form("0"),
    reviewer: str = Depends(require_admin),
) -> Any:
    fields = _create_fields(name, region_id, address, aliases, notes, force)
    try:
        with _connection() as con:
            preview = venue_resolution.preview_create(
                con, unresolved_venue_id=unresolved_venue_id, reviewer=reviewer,
                settings=admin._settings(), **_create_args(fields))
            regions = master_data.list_regions(con, enabled_only=True)
    except LookupError as exc:
        return _refused("찾을 수 없습니다", [str(exc)], status=404)
    venue, entry = preview["venue"], preview["entry"]
    label = f'NEW {venue["name"]} ({venue.get("region_code") or "-"})'
    facts = (f'<p><code>{E(entry["venue_text"])}</code> &rarr; 새 장소 <strong>'
             f'{E(venue["name"])}</strong> &middot; 지역 {E(venue.get("region_code") or "없음")}'
             f' &middot; 주소 {E(venue.get("address") or "없음")}</p>')
    extra = _alias_rows(preview["alias_plan"])
    if preview["duplicates"]:
        rows = "".join(
            f'<li><strong>#{m["venue_id"]} {E(m["name"])}</strong>'
            + (f' &middot; {E(m["region_name"])}' if m.get("region_name") else "")
            + (f' &middot; {E(m["address"])}' if m.get("address") else "")
            + f' &middot; <span class="muted">{E(", ".join(m["match_reasons"]))}</span> '
            f'<form class="inline" method="post" action="{_QUEUE}/{unresolved_venue_id}/link/preview">'
            f'<input type="hidden" name="venue_id" value="{m["venue_id"]}">'
            '<input type="hidden" name="add_alias" value="1">'
            '<button class="primary">Preview Link</button></form></li>'
            for m in preview["duplicates"])
        extra = (
            '<div class="callout"><h3>비슷한 장소가 이미 등록되어 있습니다</h3>'
            f'<ul class="sources">{rows}</ul>'
            "<p class=\"note\">같은 장소라면 위에서 연결하세요. 정말 다른 장소(다른 주소, "
            "다른 층의 별도 공간)라면 아래에서 그렇다고 표시하고 다시 미리 보세요.</p>"
            + _new_venue_form(entry, {"name": fields["name"], "address": fields["address"] or None,
                                      "aliases": fields["aliases"].split(", ") if fields["aliases"] else [],
                                      "split_inferred": False},
                              regions, _create_args(fields)["region_id"], open_form=True,
                              force=True)
            + "</div>" + extra)
    return _preview_page(
        "New Venue 미리보기", preview, venue_label=label, facts=facts,
        confirm_action=f"{_QUEUE}/{unresolved_venue_id}/create", fields=fields,
        confirm_label="Confirm &amp; Create",
        extra=extra + _evidence_block(entry, preview["evidence"]),
    )


@router.post("/admin/venues/unresolved/{unresolved_venue_id}/create")
def admin_create_and_link_venue(
    unresolved_venue_id: int,
    name: str = Form(""),
    region_id: str = Form(""),
    address: str = Form(""),
    aliases: str = Form(""),
    notes: str = Form(""),
    force: str = Form("0"),
    token: str = Form(""),
    reviewer: str = Depends(require_admin),
) -> Any:
    fields = _create_fields(name, region_id, address, aliases, notes, force)
    result = _confirm(lambda con: venue_resolution.confirm_create(
        con, unresolved_venue_id=unresolved_venue_id, token=token, reviewer=reviewer,
        settings=admin._settings(), **_create_args(fields)))
    if not isinstance(result, dict):
        return result
    return admin._back(
        _QUEUE,
        f"created {result['venue']['name']} and resolved "
        f"{result['events_updated']} event(s)",
    )


@router.post("/admin/venues/unresolved/group-link/preview", response_class=HTMLResponse)
def admin_group_link_preview(
    unresolved_venue_id: list[int] = Form(...),
    venue_id: str = Form(...),
    add_alias: str = Form("1"),
    reviewer: str = Depends(require_admin),
) -> Any:
    """Show exactly what Group Apply is about to do before it does it - every
    string, every event it moves, and what the next scan would fold - and
    nothing is written here."""
    if not venue_id.isdigit():
        return _refused("찾을 수 없습니다", [f"venue id {venue_id}"], status=404)
    try:
        with _connection() as con:
            preview = venue_resolution.preview_group(
                con, unresolved_venue_ids=unresolved_venue_id, venue_id=int(venue_id),
                add_alias=(add_alias == "1"), reviewer=reviewer, settings=admin._settings())
    except LookupError as exc:
        return _refused("찾을 수 없습니다", [str(exc)], status=404)
    if not preview["rows"]:
        return admin._back(_QUEUE, "미리 볼 대기열 항목이 없습니다", "bad")
    venue = preview["venue"]
    label = f'#{venue["venue_id"]} {venue["name"]} ({venue.get("region_code") or "-"})'
    strings = "".join(
        f'<li><code>{E(r["entry"]["venue_text"])}</code> &middot; Event {r["summary"]["events"]}건'
        + "".join(f' <span class="badge bad">{E(b)}</span>' for b in r["blockers"]) + "</li>"
        for r in preview["rows"])
    facts = (f'<p>아래 {len(preview["rows"])}건을 <strong>{E(label)}</strong>에 함께 연결합니다. '
             "하나라도 승인할 수 없으면 전부 반영하지 않습니다.</p>"
             f'<ul class="sources">{strings}</ul>')
    merged = {**preview, "events": [e for r in preview["rows"] for e in r["events"]],
              "canonical": [o for r in preview["rows"] for o in r["canonical"]]}
    return _preview_page(
        "Group Apply 미리보기", merged, venue_label=label, facts=facts,
        confirm_action=f"{_QUEUE}/group-link/confirm",
        fields={"unresolved_venue_id": [r["entry"]["unresolved_venue_id"] for r in preview["rows"]],
                "venue_id": venue["venue_id"], "add_alias": "1" if add_alias == "1" else "0"},
        confirm_label="Confirm &amp; Apply",
        extra=_alias_rows([a for r in preview["rows"] for a in r["alias_plan"]]),
    )


@router.post("/admin/venues/unresolved/group-link/confirm")
def admin_group_link_confirm(
    unresolved_venue_id: list[int] = Form(...),
    venue_id: str = Form(...),
    add_alias: str = Form(""),
    token: str = Form(""),
    reviewer: str = Depends(require_admin),
) -> Any:
    if not venue_id.isdigit():
        return _refused("찾을 수 없습니다", [f"venue id {venue_id}"], status=404)
    result = _confirm(lambda con: venue_resolution.confirm_group(
        con, unresolved_venue_ids=unresolved_venue_id, venue_id=int(venue_id),
        add_alias=(add_alias == "1"), token=token, reviewer=reviewer,
        settings=admin._settings()))
    if not isinstance(result, dict):
        return result
    return admin._back(
        _QUEUE,
        f"linked {result['linked_count']} string(s) to "
        f"{result['venue']['name'] if result['venue'] else venue_id}; "
        f"{result['events_updated']} event(s) resolved",
    )


@router.post("/admin/venues/unresolved/{unresolved_venue_id}/revert/preview",
             response_class=HTMLResponse)
def admin_revert_preview(unresolved_venue_id: int,
                         reviewer: str = Depends(require_admin)) -> Any:
    try:
        with _connection() as con:
            preview = venue_resolution.preview_revert(
                con, unresolved_venue_id=unresolved_venue_id, reviewer=reviewer,
                settings=admin._settings())
    except LookupError as exc:
        return _refused("찾을 수 없습니다", [str(exc)], status=404)
    entry, venue, alias = preview["entry"], preview["venue"], preview["alias"]
    decision = preview["decision"]
    facts = (f'<p><code>{E(entry["venue_text"])}</code> &middot; 현재 {E(entry["state"])}'
             + (f' &rarr; #{venue["venue_id"]} {E(venue["name"])}' if venue else "")
             + "</p>"
             + (f'<p class="note">되돌릴 결정: #{decision["venue_action_id"]} '
                f'{E(decision["action"])} &middot; {E(decision["reviewer"])} &middot; '
                f'{E(str(decision["created_at"])[:16])}</p>' if decision else "")
             + "<p>되돌리면 이 항목은 다시 OPEN이 되고"
             + (f', alias <code>{E(alias["alias"])}</code>가 제거되며' if alias else "")
             + " 아래 Event는 이 결정이 없었을 때 정규화가 읽는 상태로 돌아갑니다. "
             "장소 자체는 지워지지 않습니다.</p>")
    return _preview_page(
        "Revert 미리보기", preview, venue_label="(원문 문자열, 미확정)", facts=facts,
        confirm_action=f"{_QUEUE}/{unresolved_venue_id}/revert", fields={},
        confirm_label="Confirm Revert",
        form_extra=('<p><label>사유 <input name="reason" maxlength="500" '
                    'placeholder="왜 되돌리는지 (감사 기록에 남습니다)"></label></p>'),
    )


@router.post("/admin/venues/unresolved/{unresolved_venue_id}/revert")
def admin_revert_decision(
    unresolved_venue_id: int,
    token: str = Form(""),
    reason: str = Form(""),
    reviewer: str = Depends(require_admin),
) -> Any:
    result = _confirm(lambda con: venue_resolution.revert_decision(
        con, unresolved_venue_id=unresolved_venue_id, token=token, reviewer=reviewer,
        reason=reason[:500], settings=admin._settings()))
    if not isinstance(result, dict):
        return result
    return admin._back(
        _QUEUE,
        f"reverted; {result['events_updated']} event(s) back to their raw string, "
        f"{result['automatic_merges_released']} automatic merge(s) released",
    )


@router.post("/admin/venues/unresolved/{unresolved_venue_id}/dismiss")
def admin_dismiss_venue(
    unresolved_venue_id: int,
    reason: str = Form(""),
    reviewer: str = Depends(require_admin),
) -> RedirectResponse:
    target = "/admin/venues/unresolved"
    with db.connect(admin._settings()) as con:
        try:
            venue_resolution.dismiss(
                con, unresolved_venue_id=unresolved_venue_id, reviewer=reviewer,
                reason=reason.strip() or None,
            )
            con.commit()
        except Exception as exc:
            con.rollback()
            return admin._back(target, f"could not dismiss: {exc}", "bad")
    return admin._back(target, "장소가 아닌 것으로 기록했습니다")


# --- duplicates -------------------------------------------------------------

@router.get("/admin/duplicates", response_class=HTMLResponse)
def admin_duplicates(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    from . import pagination

    with _connection() as con:
        total = duplicates.count_open_pairs(con)
        page = pagination.resolve_page(request.query_params.get("page"), total)
        pairs = duplicates.open_pairs(
            con, limit=pagination.PAGE_SIZE, offset=pagination.sql_offset(page)
        )
        summary = duplicates.metrics(con)
        verdicts = duplicates.recent_human_verdicts(con)

    rows = []
    for pair in pairs:
        left = (f'<strong>#{pair["event_id"]}</strong> {E(pair["event_name"] or "")}<br>'
                f'{E(_clock(pair["start_time"]))} · {E(pair["venue_text"] or "-")}')
        right = (f'<strong>#{pair["other_event_id"]}</strong> {E(pair["other_event_name"] or "")}<br>'
                 f'{E(_clock(pair["other_start_time"]))} · {E(pair["other_venue_text"] or "-")}')
        form = (
            f'<form method="post" action="/admin/duplicates/{pair["pair_id"]}" class="inline">'
            f'<button class="primary" name="action" value="keep_{pair["event_id"]}">'
            f'Same event, keep #{pair["event_id"]}</button> '
            f'<button class="primary" name="action" value="keep_{pair["other_event_id"]}">'
            f'Same event, keep #{pair["other_event_id"]}</button> '
            '<button name="action" value="distinct">Different events</button>'
            "</form>"
        )
        rows.append([
            E(str(pair["event_date"])),
            left, right,
            E(", ".join(pair["matched"])),
            E(", ".join(pair["differs"])),
            form,
        ])

    cards = admin._cards([
        ("Auto-merged", summary["auto_merged"], "by rule, no judgement call"),
        ("Decided by a person", summary["human_decided"], "final; never revisited"),
        ("Waiting on you", summary["open_pairs"], "the rules could not settle these"),
        ("Listed", summary["listed"], "shown on the user surface"),
    ])

    note = (
        '<p class="note">The rules merge only what they can settle outright: '
        "same date, same <em>resolved</em> venue, same start time. These pairs "
        "matched on some of that and not the rest - including two posts that "
        "write the same venue words for a place nothing has resolved, which is "
        "as likely to be two parties as one. Your answer is final - the scan "
        "will not revisit a pair you have decided.</p>"
    )
    body = ("<h2>Duplicates</h2>" + cards + note + admin._table(
        ["Date", "Event", "Other", "Matched", "Differs", "Decide"], rows,
        empty="nothing ambiguous - the rules settled everything they found",
    ) + pagination.nav("/admin/duplicates", {}, page, total)
        + _human_verdicts_block(verdicts))
    return HTMLResponse(admin._page("Duplicates", "/admin/duplicates", body,
                                    flash=admin._flash(request)))


@router.post("/admin/duplicates/{pair_id}")
def admin_resolve_duplicate(
    pair_id: int,
    action: str = Form(...),
    reviewer: str = Depends(require_admin),
) -> RedirectResponse:
    target = "/admin/duplicates"
    try:
        with _connection() as con:
            if action == "distinct":
                duplicates.resolve_pair(con, pair_id, decision=duplicates.DISTINCT,
                                        reviewer=reviewer)
                return admin._back(target, "recorded as different events")
            if not action.startswith("keep_"):
                return admin._back(target, f"unknown action {action}", "bad")
            canonical = int(action.removeprefix("keep_"))
            result = duplicates.resolve_pair(
                con, pair_id, decision=duplicates.DUPLICATE,
                canonical_event_id=canonical, reviewer=reviewer,
            )
    except Exception as exc:
        return admin._back(target, f"could not resolve: {exc}", "bad")
    return admin._back(target, f"merged into #{result['canonical_event_id']}")


# v0.96.40: a person's duplicate verdict can be taken back - preview first,
# then a confirm bound to that preview, the console's request token and the
# reviewer. The verdict's own audit rows stay; the revert adds its own.

_DUPLICATES = "/admin/duplicates"


def _verdict_label(kind_or_decision: str) -> str:
    return ("Same event (MERGE)" if kind_or_decision in (duplicates.DUPLICATE,
                                                          duplicates.MERGE_VERDICT)
            else "Different events (KEEP_SEPARATE)")


def _human_verdicts_block(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    items = "".join(
        f'<li>#{r["decision_id"]} {E(_verdict_label(r["decision"]))} &middot; '
        f'event #{r["event_id"]} {E((r.get("event_name") or "")[:40])}'
        + (f' &rarr; #{r["canonical_event_id"]}' if r.get("canonical_event_id") else "")
        + f' &middot; {E(r.get("reviewer") or "-")} {E(str(r["created_at"])[:16])} '
        f'<form class="inline" method="post" '
        f'action="{_DUPLICATES}/decisions/{r["decision_id"]}/revert/preview">'
        '<button>Preview Revert</button></form></li>'
        for r in rows)
    return (
        "<details><summary>사람이 내린 중복 판정 (정정하려면 Revert)</summary>"
        '<p class="note">Revert는 판정 하나만 철회합니다. 판정이 사라지면 중복 규칙이 그 날짜를 '
        "다시 판단하므로, 규칙만으로 같은 행사라고 볼 수 있는 두 게시글은 다시 자동 병합됩니다. "
        "원래 판정의 감사 기록은 그대로 남습니다. 먼저 미리보기가 열립니다.</p>"
        f'<ul class="sources">{items}</ul></details>')


def _duplicate_refused(message: str, reasons: list[str], code: str | None = None,
                       status: int = 409) -> HTMLResponse:
    items = "".join(f"<li>{E(r)}</li>" for r in reasons)
    body = ("<h2>Duplicates</h2>"
            f'<div class="callout"><h3>{E(message)}</h3>'
            + (f'<p><span class="badge bad">{E(code)}</span></p>' if code else "")
            + f'<ul class="sources">{items}</ul>'
            "<p class=\"note\">아무것도 저장되지 않았습니다.</p></div>"
            f'<p class="note"><a href="{_DUPLICATES}">← 중복 판정으로 돌아가기</a></p>')
    return HTMLResponse(admin._page("Duplicates", _DUPLICATES, body), status_code=status)


def _state(canonical: Any, listing: str | None, public: bool) -> str:
    return ((f"folded into #{canonical}" if canonical else "독립")
            + f" · {listing or '-'} · " + ("공개" if public else "비공개"))


@router.post("/admin/duplicates/decisions/{decision_id}/revert/preview",
             response_class=HTMLResponse)
def admin_duplicate_revert_preview(decision_id: int,
                                   reviewer: str = Depends(require_admin)) -> Any:
    try:
        with _connection() as con:
            preview = duplicates.preview_revert(con, decision_id=decision_id, reviewer=reviewer)
    except LookupError as exc:
        return _duplicate_refused("찾을 수 없습니다", [str(exc)], status=404)
    decision, summary = preview["decision"], preview["summary"]
    pair = preview["pair"]
    facts = (
        f'<p>되돌릴 판정: <strong>#{decision["decision_id"]} '
        f'{E(_verdict_label(preview["kind"]))}</strong> &middot; '
        f'{E(decision.get("reviewer") or "-")} &middot; {E(str(decision["created_at"])[:16])}'
        + (f' &middot; 사유 {E(decision["reason"])}' if decision.get("reason") else "")
        + "</p><p>판정 기록: "
        + ", ".join(f'#{r["decision_id"]} (event #{r["event_id"]})'
                    for r in preview["verdict_rows"])
        + (f' &middot; 질문(pair) #{pair["pair_id"]} 현재 {E(pair["state"])} &rarr; OPEN'
           if pair else " &middot; 연결된 질문(pair) 없음")
        + f' &middot; 안전 상태 <span class="badge '
        + ("ok" if preview["status"] == "REVERT_SAFE" else "bad")
        + f'">{E(preview["status"])}</span></p>')
    cards = admin._cards([
        ("Events", summary["events"], "the verdict is withdrawn from"),
        ("Public now", summary["publicly_visible"], "of the events below"),
        ("Public after", summary["public_after"], "once the scan has run"),
        ("Public changes", summary["public_changes"], "shown or hidden by this"),
        ("Canonical changes", summary["canonical_changes"], "folds made or undone"),
        ("Scan actions", summary["scan_actions"], "the duplicate rules then take"),
    ])
    rows = [[f'#{o["event_id"]}', E(str(o["event_date"])), E((o["event_name"] or "")[:40]),
             E(_clock(o["start_time"])), E(o.get("venue_text") or "-"),
             E(_state(o["canonical_before"], o["listing_before"], o["public_before"])),
             E(_state(o["canonical_after"], o["listing_after"], o["public_after"])),
             E(f'{o["decided_by_before"] or "-"} → {o["decided_by_after"] or "-"}')]
            for o in preview["outlook"]]
    planned = [[E(a[0]), f"#{a[1]}", f"#{a[2]}", E(a[3])] for a in preview["planned"]]
    blockers = "".join(f"<li>{E(b)}</li>" for b in preview["blockers"])
    warnings = "".join(f"<li>{E(w)}</li>" for w in preview["warnings"])
    if preview["blockers"]:
        decision_html = (
            '<div class="callout"><h3>되돌릴 수 없습니다</h3>'
            f'<p><span class="badge bad">{E(preview["status"])}</span></p>'
            f'<ul class="sources">{blockers}</ul>'
            "<p class=\"note\">아무것도 저장되지 않았습니다.</p></div>")
    else:
        decision_html = (
            f'<form method="post" action="{_DUPLICATES}/decisions/{decision_id}/revert">'
            + _hidden({"token": preview["token"]})
            + '<p><label>사유 <input name="reason" maxlength="500" '
              'placeholder="왜 되돌리는지 (감사 기록에 남습니다)"></label></p>'
            + '<div class="actions"><button class="primary">Confirm Revert</button> '
            f'<a href="{_DUPLICATES}"><button type="button">Cancel</button></a></div></form>'
            '<p class="note">승인 시점에 이 미리보기를 다시 계산해 위 내용과 같을 때만 반영하고, '
            "그 날짜의 중복 스캔이 위 표와 다르게 동작하면 전부 되돌립니다.</p>")
    body = (
        f'<h2>Duplicates</h2><div class="callout"><h3>중복 판정 Revert 미리보기</h3>{facts}</div>'
        + cards
        + (f'<div class="callout"><h3>확인할 점</h3><ul class="sources">{warnings}</ul></div>'
           if warnings else "")
        + "<h3>현재 → 예상 Canonical / Listing / 공개 상태</h3>"
        + admin._table(["Event", "Date", "Title", "Start", "Venue", "Now", "After revert",
                        "Verdict by"], rows, empty="바뀌는 Event가 없습니다")
        + "<h3>자동 중복 재판정 (duplicates.scan, 같은 날짜)</h3>"
        + admin._table(["Action", "Event", "Other", "Rule"], planned,
                       empty="규칙이 새로 병합·해제·질문하는 것이 없습니다")
        + decision_html
        + f'<p class="note"><a href="{_DUPLICATES}">← 중복 판정으로 돌아가기</a></p>')
    return HTMLResponse(admin._page("Duplicates", _DUPLICATES, body),
                        status_code=409 if preview["blockers"] else 200)


@router.post("/admin/duplicates/decisions/{decision_id}/revert")
def admin_duplicate_revert(
    decision_id: int,
    token: str = Form(""),
    reason: str = Form(""),
    reviewer: str = Depends(require_admin),
) -> Any:
    with db.connect(admin._settings()) as con:
        try:
            result = duplicates.revert_decision(con, decision_id=decision_id, token=token,
                                                reviewer=reviewer, reason=reason[:500])
            con.commit()
        except duplicates.StaleRevertPreview as exc:
            con.rollback()
            return _duplicate_refused("미리보기 이후 내용이 바뀌었습니다", exc.reasons, exc.code)
        except duplicates.RevertRefused as exc:
            con.rollback()
            return _duplicate_refused("되돌릴 수 없습니다", exc.reasons, exc.code)
        except LookupError as exc:
            con.rollback()
            return _duplicate_refused("찾을 수 없습니다", [str(exc)], status=404)
        except Exception as exc:
            con.rollback()
            return admin._back(_DUPLICATES, f"could not revert: {exc}", "bad")
    merged_again = sum(1 for a in result["reconciliation"] if a[0] == "MERGE")
    return admin._back(
        _DUPLICATES,
        f"verdict #{decision_id} reverted ({result['kind']}); the duplicate rules then "
        f"made {len(result['reconciliation'])} change(s), {merged_again} merge(s)",
    )


# --- JSON -------------------------------------------------------------------

@api.get("/events/metrics")
def api_event_metrics(_: str = Depends(require_admin)) -> JSONResponse:
    with _connection() as con:
        return admin._dump({
            "events": normalization.metrics(con),
            "duplicates": duplicates.metrics(con),
        })


@api.get("/venues/unresolved")
def api_unresolved_venues(_: str = Depends(require_admin)) -> JSONResponse:
    with _connection() as con:
        return admin._dump({"unresolved": normalization.unresolved_venues(con)})


@api.post("/events/reextract")
def api_reextract(limit: int = 50, after_item_id: int | None = None,
                  force: bool = False,
                  _: str = Depends(require_admin)) -> JSONResponse:
    """Re-run the current engine over stored bodies, a batch at a time.

    This is the *diagnostic* path. The operational one is the
    `engine-reprocess` scheduler job, which walks the same queue in small
    batches without holding an HTTP request open.

    Default (`force=false`): the incremental queue - bodies whose stored
    extraction came from another ENGINE_VERSION. Every success stamps the
    running version, so repeating the call advances instead of re-reading
    the same first rows, which is exactly what the pre-v0.96.3 endpoint did
    (`WHERE true ORDER BY fetched_at LIMIT n`, with nothing in
    `mark_reprocessed()` changing that order).

    `force=true` selects every item, already-current ones included, ordered
    by `source_item_id`. That set does not shrink as rows are stamped, so
    page it with `after_item_id`: pass back the `next_after_item_id` the
    previous response returned.

    Candidates a person has acted on are skipped either way, so this can
    never overwrite a review.
    """
    from . import engine_ingest

    return admin._dump(engine_ingest.reprocess_acquired(
        admin._settings(), limit=limit, force=force, after_item_id=after_item_id,
    ))


@api.get("/events/reextract-backlog")
def api_reextract_backlog(_: str = Depends(require_admin)) -> JSONResponse:
    """How much stored content the running engine has not read yet.

    The read-only counterpart of the endpoint above: what a re-extract
    rollout is measured against, with no work done and nothing written.
    """
    from . import content_store

    settings = admin._settings()
    with _connection() as con:
        return admin._dump(
            content_store.reprocess_backlog(con, settings.engine_version))


@api.get("/events/normalization-backlog")
def api_normalization_backlog(_: str = Depends(require_admin)) -> JSONResponse:
    """How many candidates the running normalization has not built yet.

    The read-only counterpart of the normalize endpoint below, and what a
    v0.96.6 rollout is measured against: `pending` falling to 0 is the whole
    convergence criterion, and the breakdown says why each one is queued.
    """
    return admin._dump(normalization.backlog(admin._settings()))


@api.post("/events/normalize")
def api_normalize(_: str = Depends(require_admin)) -> JSONResponse:
    """Rebuild the event rows now, rather than waiting for the next tick.

    One batch, the same one the scheduler does - not "everything". A backlog
    is drained by letting the scheduler run, or by calling this repeatedly;
    either way each call advances, because the candidates it finishes leave
    the queue for good.
    """
    built = normalization.normalize_all(admin._settings())
    with _connection() as con:
        found = duplicates.scan(con)
    return admin._dump({"normalized": built, "duplicates": found})


@api.get("/events/search-preview")
def api_search_preview(when: str = "today", _: str = Depends(require_admin)) -> JSONResponse:
    """What the user surface would return right now, for an operator check."""
    try:
        with _connection() as con:
            return admin._dump(events_api.search(con, when=when.strip()))
    except events_api.SearchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


# --- removing a venue -------------------------------------------------------
#
# The listing lives on the v0.75 master-data page; the removal machinery is
# venue resolution, so the routes live here beside the rest of it.

@router.post("/admin/venues/{venue_id}/delete")
def admin_delete_venue(
    venue_id: int,
    unlink: str = Form("0"),
    reviewer: str = Depends(require_admin),
) -> Any:
    target = "/admin/venues"
    with db.connect(admin._settings()) as con:
        try:
            result = venue_resolution.delete_venue(
                con, venue_id, reviewer=reviewer, unlink=(unlink == "1"),
            )
            con.commit()
        except venue_resolution.VenueInUse as in_use:
            # Reached only if the page was stale: the button that offers a plain
            # delete is not rendered for a venue in use.
            return admin._back(
                target,
                f"이 장소는 Event {in_use.usage['events']}건에서 사용 중입니다 — "
                "Unlink & Delete 를 사용하세요",
                "bad",
            )
        except Exception as exc:
            return admin._back(target, f"could not delete venue: {exc}", "bad")

    detail = f"deleted {result['venue']['name']}"
    if result["events_unlinked"]:
        detail += (f"; {result['events_unlinked']} event(s) back to their raw string, "
                   f"{result['strings_requeued']} queued for review")
    if result["automatic_merges_released"]:
        detail += f"; {result['automatic_merges_released']} automatic merge(s) released"
    return admin._back(target, detail)


@router.post("/admin/venues/{venue_id}/enabled")
def admin_set_venue_enabled(
    venue_id: int,
    enabled: str = Form("1"),
    reviewer: str = Depends(require_admin),
) -> RedirectResponse:
    target = "/admin/venues"
    wanted = enabled == "1"
    with db.connect(admin._settings()) as con:
        try:
            result = venue_resolution.set_venue_enabled(
                con, venue_id, wanted, reviewer=reviewer,
            )
            con.commit()
        except Exception as exc:
            return admin._back(target, f"could not update venue: {exc}", "bad")
    return admin._back(
        target,
        f"{result['venue']['name']} {'reactivated' if wanted else 'deactivated'}",
    )


@api.get("/venues/{venue_id}/usage")
def api_venue_usage(venue_id: int, _: str = Depends(require_admin)) -> JSONResponse:
    """What would change if this venue were deleted."""
    with _connection() as con:
        return admin._dump({"venue_id": venue_id, "usage": venue_resolution.usage(con, venue_id)})


@api.get("/venues/history")
def api_venue_history(limit: int = 50, _: str = Depends(require_admin)) -> JSONResponse:
    with _connection() as con:
        return admin._dump({"actions": venue_resolution.history(con, limit=limit)})
