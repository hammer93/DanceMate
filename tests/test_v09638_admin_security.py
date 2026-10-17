"""v0.96.38 Admin Security Hardening & Safe Decision Reversal.

Three contracts, each tested at the layer it lives in:

* **Request authenticity (`runtime.admin_csrf`).** Every state-changing admin
  route - enumerated from the app itself, not from a list kept by hand - is
  refused without the credential (401), and with it but without a valid
  request token for its own path, or from another origin (403). A refused
  request opens no database connection at all. The console's own forms carry
  the token, so the console keeps working.
* **Decision tokens (`venue_resolution.preview_token`).** Bound to the facts
  previewed, the reviewer shown them, the time shown, and the entry's latest
  audit row: expired, other-reviewer and replayed-after-revert tokens are
  refused.
* **Revert integrity.** A revert writes what normalization derives once the
  decision is gone, from each event's *own* alias candidates in the engine
  store - proven by running the real `normalize_all()` after it - and is
  refused when another spelling would undo it or a person's later decision
  depends on it.

Every database test runs on the rolled-back ``pg`` connection.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import timedelta

import pytest

from runtime import (
    admin_csrf,
    candidates as candidate_store,
    db,
    duplicates,
    events_api,
    master_data,
    master_edit,
    normalization,
    venue_resolution,
)
from runtime.engine_adapter import ENGINE_DB_FILENAME

USER, PASSWORD = "tester", "test-only"
SAFE = {"GET", "HEAD", "OPTIONS"}


def _mutation_routes():
    from runtime.app import app

    found = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if not (path.startswith("/admin") or path.startswith("/api/admin")):
            continue
        for method in sorted(set(getattr(route, "methods", ()) or ()) - SAFE):
            concrete = re.sub(r"\{entity_type\}", "VENUE", path)
            concrete = re.sub(r"\{action\}", "enable", concrete)
            concrete = re.sub(r"\{[a-z_]+\}", "1", concrete)
            found.append((method, concrete))
    return found


MUTATIONS = _mutation_routes()


# --- the request token itself -------------------------------------------------

@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", USER)
    monkeypatch.setenv("ADMIN_PASSWORD", PASSWORD)
    monkeypatch.delenv("ADMIN_TOKEN_SECRET", raising=False)


def test_a_request_token_opens_exactly_one_path_for_one_user(secret):
    token = admin_csrf.issue("/admin/venues/1/delete")
    assert admin_csrf.refusal(token, path="/admin/venues/1/delete", user=USER) is None
    assert admin_csrf.refusal(token, path="/admin/venues/2/delete", user=USER)
    assert admin_csrf.refusal(token, path="/admin/venues/1/enabled", user=USER)
    assert admin_csrf.refusal(token, path="/admin/venues/1/delete", user="someone-else")


@pytest.mark.parametrize("bad", ["", "x", "v1.1.ab", "v2.1.0", "v1.abc.00",
                                 "v1.9999999999.0", "0" * 64])
def test_a_malformed_or_forged_request_token_is_refused(secret, bad):
    assert admin_csrf.refusal(bad, path="/admin/venues/1/delete", user=USER)


def test_a_tampered_request_token_is_refused(secret):
    token = admin_csrf.issue("/admin/venues/1/delete")
    version, issued, signature = token.split(".")
    flipped = signature[:-1] + ("0" if signature[-1] != "0" else "1")
    assert admin_csrf.refusal(f"{version}.{issued}.{flipped}",
                              path="/admin/venues/1/delete", user=USER)
    later = f"{version}.{int(issued) + 60}.{signature}"   # re-dated, same signature
    assert admin_csrf.refusal(later, path="/admin/venues/1/delete", user=USER)


def test_a_request_token_expires_and_cannot_be_issued_ahead(secret):
    now = time.time()
    old = admin_csrf.issue("/admin/x", now=now - admin_csrf.TOKEN_TTL_SECONDS - 1)
    assert "expired" in admin_csrf.refusal(old, path="/admin/x", user=USER)
    ahead = admin_csrf.issue("/admin/x", now=now + 3600)
    assert "future" in admin_csrf.refusal(ahead, path="/admin/x", user=USER)


def test_rotating_the_secret_invalidates_every_token(secret, monkeypatch):
    token = admin_csrf.issue("/admin/x")
    monkeypatch.setenv("ADMIN_TOKEN_SECRET", "rotated")
    assert admin_csrf.refusal(token, path="/admin/x", user=USER)


def test_no_token_contains_or_is_keyed_with_the_password_itself(secret):
    import hashlib
    import hmac

    token = admin_csrf.issue("/admin/x")
    assert PASSWORD not in token
    assert admin_csrf.signing_key("csrf") != PASSWORD.encode()
    assert admin_csrf.signing_key("csrf") != admin_csrf.signing_key("venue-decision")
    raw = hmac.new(PASSWORD.encode(), f"v1|{USER}|/admin/x|{token.split('.')[1]}".encode(),
                   hashlib.sha256).hexdigest()
    assert token.split(".")[2] != raw


def test_every_post_form_gets_a_token_bound_to_its_own_action(secret):
    page = ('<form method="get" action="/admin/events"></form>'
            '<form class="inline" method="post" action="/admin/venues/7/delete?return_to=%2F">'
            '</form><form method="POST" action=\'/admin/regions\'></form>')
    out = admin_csrf.inject(page)
    tokens = re.findall(r'<form[^>]*action=["\']([^"\']+)["\'][^>]*>'
                        r'<input type="hidden" name="csrf_token" value="([^"]+)">', out)
    assert [t[0] for t in tokens] == ["/admin/venues/7/delete?return_to=%2F", "/admin/regions"]
    assert admin_csrf.refusal(tokens[0][1], path="/admin/venues/7/delete", user=USER) is None
    assert admin_csrf.refusal(tokens[1][1], path="/admin/regions", user=USER) is None
    assert '<form method="get" action="/admin/events"><input' not in out


# --- every admin mutation over HTTP ------------------------------------------

@pytest.fixture
def guarded(env, secret, monkeypatch):
    """A client whose app may not open a database connection: a refused
    request must be refused before it gets one."""
    from fastapi.testclient import TestClient

    from runtime import admin
    from runtime import app as app_module

    opened = []

    @contextmanager
    def refuse(*args, **kwargs):
        opened.append(args)
        raise AssertionError("a refused request opened a database connection")
        yield  # pragma: no cover

    monkeypatch.setattr(app_module, "_settings", None)
    monkeypatch.setattr(db, "connect", refuse)
    monkeypatch.setattr(admin, "_connection", refuse)
    client = TestClient(app_module.app, raise_server_exceptions=False)
    client.console_tokens = False
    client.opened = opened
    return client


def test_the_inventory_covers_every_admin_mutation_route():
    paths = {p for _, p in MUTATIONS}
    # The routes the brief names, so a renamed route cannot silently drop out.
    for expected in ("/admin/venues/unresolved/1/dismiss", "/admin/venues/1/delete",
                     "/admin/venues/unresolved/1/link", "/admin/venues/unresolved/1/create",
                     "/admin/venues/unresolved/group-link/confirm",
                     "/admin/venues/unresolved/1/revert", "/admin/duplicates/1",
                     "/admin/master-data/VENUE/1/alias-add", "/api/admin/sources/1",
                     "/admin/review/1/enable", "/admin/sources/import/confirm"):
        assert expected in paths, expected
    assert len(MUTATIONS) >= 60


@pytest.mark.parametrize("method,path", MUTATIONS)
def test_an_unauthenticated_mutation_is_refused(guarded, method, path):
    good = admin_csrf.issue(path, user=USER)
    for headers in ({}, {admin_csrf.HEADER: good}):
        response = guarded.request(method, path, headers=headers)
        assert response.status_code == 401, (method, path, response.status_code)
    wrong = guarded.request(method, path, headers={admin_csrf.HEADER: good},
                            auth=(USER, "wrong-password"))
    assert wrong.status_code == 401
    assert guarded.opened == []


@pytest.mark.parametrize("method,path", MUTATIONS)
def test_an_authenticated_mutation_without_a_valid_token_is_refused(guarded, method, path):
    other = "/admin/venues/999999/delete" if path != "/admin/venues/999999/delete" else "/admin/x"
    cases = {
        "no token": {},
        "forged": {admin_csrf.HEADER: "v1.%d.%s" % (int(time.time()), "0" * 64)},
        "another action's token": {admin_csrf.HEADER: admin_csrf.issue(other, user=USER)},
        "expired": {admin_csrf.HEADER: admin_csrf.issue(
            path, user=USER, now=time.time() - admin_csrf.TOKEN_TTL_SECONDS - 5)},
        "a preview token": {admin_csrf.HEADER: venue_resolution.preview_token(
            {"action": "LINK_EXISTING"}, reviewer=USER)},
    }
    for name, headers in cases.items():
        response = guarded.request(method, path, headers=headers, auth=(USER, PASSWORD))
        assert response.status_code == 403, (name, method, path, response.status_code)
    assert guarded.opened == []


@pytest.mark.parametrize("method,path", MUTATIONS)
def test_a_cross_site_mutation_is_refused_even_with_a_valid_token(guarded, method, path):
    token = admin_csrf.issue(path, user=USER)
    for headers in ({"Origin": "https://evil.example"},
                    {"Origin": "null"},
                    {"Sec-Fetch-Site": "cross-site"},
                    {"Sec-Fetch-Site": "same-site"},
                    {"Referer": "https://evil.example/page"}):
        response = guarded.request(method, path, auth=(USER, PASSWORD),
                                   headers={**headers, admin_csrf.HEADER: token})
        assert response.status_code == 403, (headers, method, path)
    assert guarded.opened == []


def test_a_form_field_token_is_read_like_the_header(guarded):
    path = "/admin/venues/unresolved/1/dismiss"
    refused = guarded.post(path, auth=(USER, PASSWORD), data={"csrf_token": "nope"})
    assert refused.status_code == 403
    # A valid one passes the guard and reaches the route (which then opens
    # its connection - the only request in this file allowed to try).
    response = guarded.post(path, auth=(USER, PASSWORD),
                            data={"csrf_token": admin_csrf.issue(path, user=USER)},
                            headers={"Origin": "http://testserver"})
    assert response.status_code != 403
    assert guarded.opened


def test_the_token_endpoint_needs_the_credential_and_an_admin_path(guarded):
    assert guarded.get("/api/admin/csrf-token", params={"path": "/admin/x"}).status_code == 401
    bad = guarded.get("/api/admin/csrf-token", params={"path": "/events/1/feedback"},
                      auth=(USER, PASSWORD))
    assert bad.status_code == 400
    body = guarded.get("/api/admin/csrf-token", params={"path": "/api/admin/sources?x=1"},
                       auth=(USER, PASSWORD)).json()
    assert body["path"] == "/api/admin/sources" and body["header"] == admin_csrf.HEADER
    assert admin_csrf.refusal(body["token"], path="/api/admin/sources", user=USER) is None


def test_public_and_health_routes_are_untouched(guarded):
    assert guarded.get("/health").status_code == 200


# --- the console still works through its own forms ---------------------------

class _Shared:
    def __init__(self, con):
        self._con = con

    def commit(self):
        pass

    def rollback(self):
        pass

    def __getattr__(self, name):
        return getattr(self._con, name)


@pytest.fixture
def console(pg, secret, monkeypatch):
    """The real app on the test's own connection, posting *only* what its
    pages hand it - no token is added by the test client."""
    from fastapi.testclient import TestClient

    from runtime import admin
    from runtime.app import app

    @contextmanager
    def shared(*args, **kwargs):
        yield _Shared(pg)

    monkeypatch.setattr(admin, "_connection", shared)
    monkeypatch.setattr(db, "connect", shared)
    client = TestClient(app)
    client.auth = (USER, PASSWORD)
    client.console_tokens = False
    return client


_FORM = re.compile(r'<form\b([^>]*)>', re.I)


def _forms(html: str) -> list[dict]:
    out = []
    for tag in _FORM.finditer(html):
        attrs = tag.group(1)
        inner = html[tag.end():html.find("</form>", tag.end())]
        if not re.search(r'method=["\']?post', attrs, re.I):
            continue
        action = re.search(r'action=["\']([^"\']*)["\']', attrs).group(1)
        fields = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', inner))
        out.append({"action": action.replace("&amp;", "&"), "fields": fields})
    return out


def _fingerprint(pg) -> tuple:
    with pg.cursor() as cur:
        cur.execute(
            "SELECT (SELECT count(*) FROM venues), (SELECT count(*) FROM venue_aliases), "
            "(SELECT count(*) FROM venue_resolution_actions), "
            "(SELECT count(*) FROM master_data_actions), "
            "(SELECT md5(string_agg(unresolved_venue_id || state, ',' "
            "   ORDER BY unresolved_venue_id)) FROM unresolved_venues), "
            "(SELECT md5(string_agg(event_id || ':' || coalesce(venue_id::text, '') || ':' "
            "   || coalesce(region_id::text, '') || ':' || venue_status || ':' "
            "   || identity_key || ':' || coalesce(canonical_event_id::text, ''), ',' "
            "   ORDER BY event_id)) FROM events)")
        return cur.fetchone()


def _event(pg, unique, suffix, **overrides) -> dict:
    candidate = {
        "candidate_id": int(f"{unique[-6:]}{suffix}"), "post_id": 1,
        "source_url": f"https://cafe.daum.net/v38/{unique}-{suffix}",
        "event_name": f"보안 밀롱가 {unique}-{suffix}", "event_type": "MILONGA",
        "event_date": (events_api.today() + timedelta(days=10)).isoformat(),
        "start_time": "20:00", "end_time": "23:30", "end_day_offset": 0,
        "venue": f"보안홀 {unique}", "candidate_status": "POSSIBLE",
        "provenance": normalization.PROVENANCE_LIVE,
    }
    candidate.update(overrides)
    return normalization.normalize_candidate(pg, candidate)


def _entry(pg, text: str) -> dict:
    with pg.cursor() as cur:
        cur.execute("SELECT unresolved_venue_id FROM unresolved_venues WHERE normalized_text = %s",
                    (master_data.normalize_alias(text),))
        return normalization.unresolved_venue(pg, cur.fetchone()[0])


def _seoul(pg) -> int:
    return next(r["region_id"] for r in master_data.list_regions(pg) if r["code"] == "KR-SEOUL")


def test_every_console_page_hands_each_post_form_a_valid_token(console):
    from runtime.app import app

    pages = sorted({r.path for r in app.routes
                    if "GET" in (getattr(r, "methods", ()) or ())
                    and r.path.startswith("/admin") and "{" not in r.path
                    and not r.path.endswith(".csv")})
    checked = forms = 0
    for page in pages:
        response = console.get(page)
        if response.status_code != 200 or "text/html" not in response.headers.get(
                "content-type", ""):
            continue
        checked += 1
        for form in _forms(response.text):
            forms += 1
            path = form["action"].split("?")[0]
            token = form["fields"].get("csrf_token")
            assert token, (page, form["action"])
            assert admin_csrf.refusal(token, path=path, user=USER) is None, (page, path)
    assert checked >= 5 and forms >= 5, (checked, forms)


def test_the_console_dismisses_with_the_token_its_page_gave_it(console, pg, unique):
    text = f"보안홀 {unique}"
    _event(pg, unique, "1", venue=text)
    uid = _entry(pg, text)["unresolved_venue_id"]
    page = console.get("/admin/venues/unresolved?show=all")
    form = next(f for f in _forms(page.text)
                if f["action"] == f"/admin/venues/unresolved/{uid}/dismiss")
    before = _fingerprint(pg)
    refused = console.post(form["action"], data={"reason": "test"}, follow_redirects=False)
    assert refused.status_code == 403 and _fingerprint(pg) == before
    done = console.post(form["action"], data={**form["fields"], "reason": "test"},
                        headers={"Origin": "http://testserver"}, follow_redirects=False)
    assert done.status_code == 303
    assert normalization.unresolved_venue(pg, uid)["state"] == "DISMISSED"


def test_preview_then_confirm_needs_both_tokens_and_the_credential(console, pg, unique):
    text = f"보안홀 {unique}"
    _event(pg, unique, "1", venue=text)
    venue = master_data.create_venue(pg, name=f"보안 스튜디오 {unique}", region_id=_seoul(pg))
    uid = _entry(pg, text)["unresolved_venue_id"]
    queue = console.get("/admin/venues/unresolved?show=all")
    preview_form = next(f for f in _forms(queue.text)
                        if f["action"] == f"/admin/venues/unresolved/{uid}/link/preview")
    before = _fingerprint(pg)
    page = console.post(preview_form["action"],
                        data={**preview_form["fields"], "venue_id": str(venue["venue_id"]),
                              "add_alias": "1"})
    assert page.status_code == 200 and _fingerprint(pg) == before      # read-only
    offered = _forms(page.text)
    confirm = next((f for f in offered
                    if f["action"] == f"/admin/venues/unresolved/{uid}/link"), None)
    assert confirm, ([f["action"] for f in offered], re.findall(r"<form[^>]*>", page.text))
    fields = confirm["fields"]
    assert fields["csrf_token"] and fields["token"]
    without_csrf = {k: v for k, v in fields.items() if k != "csrf_token"}
    assert console.post(confirm["action"], data=without_csrf,
                        follow_redirects=False).status_code == 403
    without_auth = console.post(confirm["action"], data=fields, auth=None,
                                follow_redirects=False)
    assert without_auth.status_code == 401
    without_preview = {**fields, "token": ""}
    assert console.post(confirm["action"], data=without_preview,
                        follow_redirects=False).status_code == 409
    assert _fingerprint(pg) == before
    done = console.post(confirm["action"], data=fields, follow_redirects=False)
    assert done.status_code == 303
    assert normalization.unresolved_venue(pg, uid)["state"] == "LINKED"


# --- the decision token -------------------------------------------------------

def test_a_decision_token_is_bound_to_its_reviewer_and_expires(pg, secret, unique):
    text = f"보안홀 {unique}"
    _event(pg, unique, "1", venue=text)
    venue = master_data.create_venue(pg, name=f"보안 스튜디오 {unique}", region_id=_seoul(pg))
    uid = _entry(pg, text)["unresolved_venue_id"]
    preview = venue_resolution.preview_link(pg, unresolved_venue_id=uid,
                                            venue_id=venue["venue_id"], reviewer="kim")
    before = _fingerprint(pg)
    with pytest.raises(venue_resolution.StalePreview):
        venue_resolution.confirm_link(pg, unresolved_venue_id=uid, venue_id=venue["venue_id"],
                                      token=preview["token"], reviewer="lee")
    old = venue_resolution.preview_token(
        preview["facts"], reviewer="kim",
        now=time.time() - venue_resolution.PREVIEW_TOKEN_TTL_SECONDS - 5)
    with pytest.raises(venue_resolution.StalePreview):
        venue_resolution.confirm_link(pg, unresolved_venue_id=uid, venue_id=venue["venue_id"],
                                      token=old, reviewer="kim")
    assert _fingerprint(pg) == before
    venue_resolution.confirm_link(pg, unresolved_venue_id=uid, venue_id=venue["venue_id"],
                                  token=preview["token"], reviewer="kim")
    assert normalization.unresolved_venue(pg, uid)["state"] == "LINKED"


def test_a_decision_token_cannot_be_replayed_after_a_revert(pg, secret, unique):
    """The revert puts the entry back exactly as it was, so without the audit
    row among the facts the old preview's token would match again."""
    text = f"보안홀 {unique}"
    _event(pg, unique, "1", venue=text)
    venue = master_data.create_venue(pg, name=f"보안 스튜디오 {unique}", region_id=_seoul(pg))
    uid = _entry(pg, text)["unresolved_venue_id"]
    preview = venue_resolution.preview_link(pg, unresolved_venue_id=uid, venue_id=venue["venue_id"])
    venue_resolution.confirm_link(pg, unresolved_venue_id=uid, venue_id=venue["venue_id"],
                                  token=preview["token"])
    back = venue_resolution.preview_revert(pg, unresolved_venue_id=uid)
    venue_resolution.revert_decision(pg, unresolved_venue_id=uid, token=back["token"])
    before = _fingerprint(pg)
    with pytest.raises(venue_resolution.StalePreview):
        venue_resolution.confirm_link(pg, unresolved_venue_id=uid, venue_id=venue["venue_id"],
                                      token=preview["token"])
    with pytest.raises(venue_resolution.DecisionRefused):     # nothing left to revert
        venue_resolution.revert_decision(pg, unresolved_venue_id=uid, token=back["token"])
    assert _fingerprint(pg) == before


# --- revert integrity, against the real normalization pass -------------------

ENGINE_SCHEMA = """
CREATE TABLE raw_posts(
    post_id INTEGER PRIMARY KEY, source_id TEXT, source_url TEXT, title TEXT,
    body TEXT, collected_at TEXT, cafe_name TEXT
);
CREATE TABLE event_candidates(
    candidate_id INTEGER PRIMARY KEY, post_id INTEGER, name TEXT,
    event_type TEXT, event_date TEXT, start_time TEXT, end_time TEXT,
    end_day_offset INTEGER, fee INTEGER, fee_display_text TEXT, venue TEXT,
    dj TEXT, status TEXT, core_complete INTEGER
);
CREATE TABLE evidences(
    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id INTEGER,
    field TEXT, value TEXT, raw_text TEXT, evidence_type TEXT,
    source_role TEXT, inference TEXT, context_id TEXT
);
"""


class Store:
    """A throwaway engine store: posts, candidates, and the venue evidence
    whose `alias_candidates` normalize_all() reads per candidate."""

    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._open() as con:
            con.executescript(ENGINE_SCHEMA)

    @contextmanager
    def _open(self):
        con = sqlite3.connect(self.path)
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def add(self, candidate_id: int, *, venue: str, aliases: list[str], day: str,
            start: str = "20:00", name: str | None = None) -> int:
        with self._open() as con:
            con.execute("INSERT INTO raw_posts VALUES (?,?,?,?,?,?,?)",
                        (candidate_id, "SRC", f"https://example.test/v38/{candidate_id}",
                         f"post {candidate_id}", "body", "2026-10-01T00:00:00", "cafe"))
            con.execute(
                "INSERT INTO event_candidates(candidate_id, post_id, name, event_type, "
                "  event_date, start_time, venue, status, core_complete) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (candidate_id, candidate_id, name or f"Revert Milonga {candidate_id}",
                 "MILONGA", day, start, venue, "POSSIBLE", 1))
            con.execute(
                "INSERT INTO evidences(candidate_id, field, value, raw_text) "
                "VALUES (?, 'venue', ?, ?)",
                (candidate_id, json.dumps({"value": venue, "alias_candidates": aliases},
                                          ensure_ascii=False), venue))
        return candidate_id


@pytest.fixture
def store(env, monkeypatch):
    monkeypatch.setenv("ENGINE_DATA_DIR", str(env / "engine-data"))
    return Store(env / "engine-data" / ENGINE_DB_FILENAME)


@pytest.fixture
def run_normalization(pg, store, monkeypatch):
    from runtime.config import load_settings

    settings = load_settings()

    @contextmanager
    def _connect(_settings, **_kwargs):
        yield pg

    monkeypatch.setattr(db, "connect", _connect)
    monkeypatch.setattr(candidate_store, "all_candidate_ids", lambda *a, **kw: None)

    def run():
        for _ in range(10):
            if normalization.normalize_all(settings)["selected"] == 0:
                return
        raise AssertionError("normalization did not converge")

    run.settings = settings
    return run


FIELDS = ("venue_id", "region_id", "venue_status", "identity_key", "series_key",
          "canonical_event_id", "listing_state")


def _event_ids(pg, candidate_ids) -> list[int]:
    with pg.cursor() as cur:
        cur.execute("SELECT event_id FROM events WHERE candidate_id = ANY(%s)",
                    (list(candidate_ids),))
        return [r[0] for r in cur.fetchall()]


def _state(pg, candidate_ids) -> dict[int, tuple]:
    with pg.cursor() as cur:
        cur.execute("SELECT candidate_id, " + ", ".join(FIELDS) + " FROM events "
                    "WHERE candidate_id = ANY(%s)", (list(candidate_ids),))
        return {r[0]: r[1:] for r in cur.fetchall()}


@pytest.fixture
def scenario(pg, store, run_normalization, unique):
    """The brief's case. One venue string X read by two posts: post A beside
    the spelling Y, post B beside the spelling Z. B is normalized first and A
    second, so the queue entry stores A's list (X, Y) - exactly the one list
    v0.96.37's revert check read."""
    n = int(unique[-6:])
    x = f"홀엑스 {unique} (서울 마포구 검증로 {n % 97 + 1})"
    hall, y, z = f"홀엑스 {unique}", f"와이 {unique}", f"제트 {unique}"
    day = (events_api.today() + timedelta(days=12)).isoformat()
    b = store.add(n * 10 + 2, venue=x, aliases=[x, hall, z], day=day, start="21:00")
    run_normalization()
    a = store.add(n * 10 + 1, venue=x, aliases=[x, hall, y], day=day, start="20:00")
    run_normalization()
    entry = _entry(pg, x)
    assert z not in entry["alias_candidates"] and y in entry["alias_candidates"]
    venue = master_data.create_venue(pg, name=f"홀브이 {unique}", region_id=_seoul(pg))
    before_decision = _state(pg, [a, b])
    preview = venue_resolution.preview_link(pg, unresolved_venue_id=entry["unresolved_venue_id"],
                                            venue_id=venue["venue_id"])
    assert {e["event_id"] for e in preview["events"]} == {
        normalization.get(pg, i)["event_id"] for i in _event_ids(pg, [a, b])}
    venue_resolution.confirm_link(pg, unresolved_venue_id=entry["unresolved_venue_id"],
                                  venue_id=venue["venue_id"], token=preview["token"])
    run_normalization()                        # the alias moved the master revision
    approved = _state(pg, [a, b])
    assert {s[0] for s in approved.values()} == {venue["venue_id"]}
    return {"x": x, "y": y, "z": z, "a": a, "b": b, "day": day, "venue": venue,
            "uid": entry["unresolved_venue_id"], "before_decision": before_decision,
            "approved": approved, "unique": unique}


def test_approval_normalize_revert_normalize_returns_to_the_state_before(
        pg, scenario, run_normalization):
    s = scenario
    back = venue_resolution.preview_revert(pg, unresolved_venue_id=s["uid"],
                                           settings=run_normalization.settings)
    assert back["blockers"] == []
    assert back["decision"]["action"] == venue_resolution.LINK_EXISTING
    venue_resolution.revert_decision(pg, unresolved_venue_id=s["uid"], token=back["token"],
                                     settings=run_normalization.settings, reason="test")
    reverted = _state(pg, [s["a"], s["b"]])
    assert reverted == s["before_decision"]
    run_normalization()                        # alias removed: every candidate re-read
    assert _state(pg, [s["a"], s["b"]]) == reverted == s["before_decision"]
    assert normalization.unresolved_venue(pg, s["uid"])["state"] == "OPEN"


def test_reproduced_the_queues_one_list_missed_another_posts_spelling(
        pg, scenario, run_normalization):
    """v0.96.37's defect, reproduced. After the decision a person teaches the
    venue the spelling Z (post B's). The entry's stored list (A's: X, Y) does
    not contain Z, so the old check passed - and the old revert's write was
    undone by the next pass, which reads B's own list."""
    s = scenario
    master_edit.add_alias(pg, s["venue"]["venue_id"], s["z"], reviewer="other-operator")
    run_normalization()
    entry = normalization.unresolved_venue(pg, s["uid"])
    old_rule_blocked = any(
        (found := master_data.resolve_venue(pg, other)) is not None
        and found["venue_id"] == s["venue"]["venue_id"]
        for other in entry["alias_candidates"]
        if master_data.normalize_alias(other) != entry["normalized_text"])
    assert not old_rule_blocked                 # what v0.96.37 decided from

    # The old write (every event back to unresolved, alias removed), then the
    # real normalization pass: B is linked again. Inside a savepoint, undone.
    with pytest.raises(_Undo):
        with pg.transaction():
            alias = next(a for a in master_data.venue_aliases(pg, s["venue"]["venue_id"])
                         if a["normalized_alias"] == entry["normalized_text"])
            with pg.cursor() as cur:
                cur.execute("UPDATE events SET venue_id = NULL, region_id = NULL, "
                            "venue_status = 'UNRESOLVED' WHERE candidate_id = ANY(%s)",
                            ([s["a"], s["b"]],))
            master_data.remove_venue_alias(pg, alias["venue_alias_id"])
            run_normalization()
            relinked = _state(pg, [s["b"]])[s["b"]][0]
            assert relinked == s["venue"]["venue_id"]          # RELINK_AFTER_REVERT
            raise _Undo

    # v0.96.38 reads B's own candidates and refuses instead.
    back = venue_resolution.preview_revert(pg, unresolved_venue_id=s["uid"],
                                           settings=run_normalization.settings)
    assert any(s["z"] in b and "link these events again" in b for b in back["blockers"])
    before = _fingerprint(pg)
    with pytest.raises(venue_resolution.DecisionRefused):
        venue_resolution.revert_decision(pg, unresolved_venue_id=s["uid"], token=back["token"],
                                         settings=run_normalization.settings)
    assert _fingerprint(pg) == before


class _Undo(Exception):
    pass


def test_a_spelling_another_venue_owns_takes_its_event_there_and_normalization_agrees(
        pg, scenario, run_normalization):
    s = scenario
    other = master_data.create_venue(pg, name=s["z"], region_id=_seoul(pg))
    back = venue_resolution.preview_revert(pg, unresolved_venue_id=s["uid"],
                                           settings=run_normalization.settings)
    assert back["blockers"] == []
    going = {e["candidate_id"]: e["proposed_venue_id"] for e in back["events"]}
    assert going == {s["a"]: None, s["b"]: other["venue_id"]}
    assert any(f"#{other['venue_id']}" in w for w in back["warnings"])
    venue_resolution.revert_decision(pg, unresolved_venue_id=s["uid"], token=back["token"],
                                     settings=run_normalization.settings)
    written = _state(pg, [s["a"], s["b"]])
    assert written[s["a"]] == s["before_decision"][s["a"]]
    assert written[s["b"]][0] == other["venue_id"]
    run_normalization()
    assert _state(pg, [s["a"], s["b"]]) == written


def test_a_spelling_in_another_city_is_not_followed(pg, scenario, run_normalization):
    s = scenario
    daejeon = next(r["region_id"] for r in master_data.list_regions(pg)
                   if r["code"] == "KR-DAEJEON")
    master_data.create_venue(pg, name=s["z"], region_id=daejeon)
    back = venue_resolution.preview_revert(pg, unresolved_venue_id=s["uid"],
                                           settings=run_normalization.settings)
    assert back["blockers"] == []
    assert all(e["proposed_venue_id"] is None for e in back["events"])
    venue_resolution.revert_decision(pg, unresolved_venue_id=s["uid"], token=back["token"],
                                     settings=run_normalization.settings)
    run_normalization()
    assert _state(pg, [s["a"], s["b"]]) == s["before_decision"]


def test_another_decision_on_the_same_venue_is_left_standing(pg, scenario, run_normalization,
                                                              store):
    s = scenario
    second_text = f"홀엑스 별관 {s['unique']} (서울 마포구 검증로 2)"
    c = store.add(int(s["unique"][-6:]) * 10 + 3, venue=second_text, aliases=[second_text],
                  day=s["day"], start="22:00")
    run_normalization()
    second = _entry(pg, second_text)
    p = venue_resolution.preview_link(pg, unresolved_venue_id=second["unresolved_venue_id"],
                                      venue_id=s["venue"]["venue_id"])
    venue_resolution.confirm_link(pg, unresolved_venue_id=second["unresolved_venue_id"],
                                  venue_id=s["venue"]["venue_id"], token=p["token"])
    run_normalization()
    kept = _state(pg, [c])
    back = venue_resolution.preview_revert(pg, unresolved_venue_id=s["uid"],
                                           settings=run_normalization.settings)
    assert c not in {e["candidate_id"] for e in back["events"]}
    venue_resolution.revert_decision(pg, unresolved_venue_id=s["uid"], token=back["token"],
                                     settings=run_normalization.settings)
    run_normalization()
    assert _state(pg, [c]) == kept
    assert normalization.unresolved_venue(pg, second["unresolved_venue_id"])["state"] == "LINKED"
    assert second_text in [a["alias"] for a in
                           master_data.venue_aliases(pg, s["venue"]["venue_id"])]


def test_a_later_edit_of_the_decisions_own_spelling_blocks_the_revert(pg, scenario,
                                                                      run_normalization):
    s = scenario
    alias = next(a for a in master_data.venue_aliases(pg, s["venue"]["venue_id"])
                 if a["normalized_alias"] == master_data.normalize_alias(s["x"]))
    master_edit.remove_alias(pg, alias["venue_alias_id"], reviewer="other-operator", force=True)
    master_edit.add_alias(pg, s["venue"]["venue_id"], s["x"], reviewer="other-operator")
    back = venue_resolution.preview_revert(pg, unresolved_venue_id=s["uid"],
                                           settings=run_normalization.settings)
    assert any("other-operator" in b and "depends on this one" in b for b in back["blockers"])


def test_an_automatic_fold_made_by_the_approval_is_split_again(pg, scenario, run_normalization,
                                                               store):
    """A third post about A's night: unresolved, the pair is only a question;
    at the venue, the scan folds it; reverted, the fold is released and the
    scan after normalization does not make it again."""
    s = scenario
    twin = store.add(int(s["unique"][-6:]) * 10 + 4, venue=s["x"], aliases=[s["x"]],
                     day=s["day"], start="20:00", name=f"Revert Milonga {s['a']}")
    run_normalization()
    duplicates.scan(pg, on=events_api.today() + timedelta(days=12))
    folded = _state(pg, [s["a"], twin])
    assert any(v[5] for v in folded.values())
    back = venue_resolution.preview_revert(pg, unresolved_venue_id=s["uid"],
                                           settings=run_normalization.settings)
    assert back["summary"]["released_folds"] >= 1 and back["blockers"] == []
    venue_resolution.revert_decision(pg, unresolved_venue_id=s["uid"], token=back["token"],
                                     settings=run_normalization.settings)
    run_normalization()
    duplicates.scan(pg, on=events_api.today() + timedelta(days=12))
    assert all(v[5] is None for v in _state(pg, [s["a"], twin]).values())


def test_a_failure_inside_the_revert_writes_nothing(pg, scenario, run_normalization,
                                                    monkeypatch):
    s = scenario
    back = venue_resolution.preview_revert(pg, unresolved_venue_id=s["uid"],
                                           settings=run_normalization.settings)
    before = _fingerprint(pg)

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(master_data, "remove_venue_alias", boom)
    with pytest.raises(RuntimeError):
        venue_resolution.revert_decision(pg, unresolved_venue_id=s["uid"], token=back["token"],
                                         settings=run_normalization.settings)
    assert _fingerprint(pg) == before


def test_the_revert_audit_keeps_the_original_and_says_what_it_did(pg, scenario,
                                                                  run_normalization):
    s = scenario
    with pg.cursor() as cur:
        cur.execute("SELECT venue_action_id, action, after_json FROM venue_resolution_actions "
                    "WHERE unresolved_venue_id = %s ORDER BY venue_action_id", (s["uid"],))
        original = cur.fetchall()
    back = venue_resolution.preview_revert(pg, unresolved_venue_id=s["uid"], reviewer="park",
                                           settings=run_normalization.settings)
    result = venue_resolution.revert_decision(pg, unresolved_venue_id=s["uid"],
                                              token=back["token"], reviewer="park",
                                              reason="wrong studio",
                                              settings=run_normalization.settings)
    with pg.cursor() as cur:
        cur.execute("SELECT venue_action_id, action, after_json FROM venue_resolution_actions "
                    "WHERE unresolved_venue_id = %s ORDER BY venue_action_id", (s["uid"],))
        after = cur.fetchall()
    assert after[:len(original)] == original          # nothing rewritten or removed
    row = result["action"]
    assert row["action"] == venue_resolution.DECISION_REVERT and row["reviewer"] == "park"
    assert row["after_json"]["original_decision"]["venue_action_id"] == original[-1][0]
    assert row["after_json"]["reason"] == "wrong studio"
    assert {e["event_id"] for e in row["after_json"]["events"]} == set(row["before_json"]["event_ids"])
    assert row["after_json"]["derived_by"].startswith("normalization.resolve_venue")


# --- one version everywhere -------------------------------------------------

def test_openapi_health_and_the_admin_banner_report_one_version(env, secret, monkeypatch):
    from fastapi.testclient import TestClient

    from runtime import app as app_module
    from runtime import config

    monkeypatch.setattr(app_module, "_settings", None)
    client = TestClient(app_module.app)
    deployed = client.get("/health").json()["version"]
    assert deployed == config.runtime_version()
    assert client.get("/version").json()["product_runtime"] == deployed
    # The OpenAPI document is built when the app is imported, so it is read
    # in a fresh process started the way the container starts one.
    import os
    import subprocess
    import sys

    probe = subprocess.run(
        [sys.executable, "-c", "from runtime.app import app; "
         "print(app.version, app.openapi()['info']['version'])"],
        cwd=config.REPO_ROOT, capture_output=True, text=True, check=True,
        env={**os.environ, "DANCEMATE_VERSION": "9.8.7"})
    assert probe.stdout.split() == ["9.8.7", "9.8.7"]
    released = (config.REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert config.PRODUCT_VERSION == released
    monkeypatch.delenv("DANCEMATE_VERSION", raising=False)
    assert config.runtime_version() == released


def test_a_new_venues_own_name_links_other_waiting_posts_and_the_preview_says_so(
        pg, store, run_normalization, unique):
    """Found on the Production clone: New Venue for `STUDIO RYU (...)` also
    registers `STUDIO RYU`, and posts that read just that - another queue
    entry - were linked by the next pass without the preview listing them."""
    n = int(unique[-6:])
    full = f"스튜디오알 {unique} (서울 마포구 동교로 {n % 50 + 1} 4층)"
    bare = f"스튜디오알 {unique}"
    day = (events_api.today() + timedelta(days=9)).isoformat()
    own = store.add(n * 10 + 5, venue=full, aliases=[full, bare], day=day)
    other = store.add(n * 10 + 6, venue=bare, aliases=[bare], day=day, start="21:30")
    run_normalization()
    uid = _entry(pg, full)["unresolved_venue_id"]
    preview = venue_resolution.preview_create(
        pg, unresolved_venue_id=uid, name=bare, region_id=_seoul(pg),
        aliases=[bare], settings=run_normalization.settings)
    later = {e["event_id"] for e in preview["also_linked"]}
    assert later == set(_event_ids(pg, [other]))
    assert preview["summary"]["linked_on_next_normalization"] == 1
    assert any("next normalization" in w for w in preview["warnings"])
    venue_resolution.confirm_create(pg, unresolved_venue_id=uid, name=bare,
                                    region_id=_seoul(pg), aliases=[bare],
                                    token=preview["token"],
                                    settings=run_normalization.settings)
    venue = normalization.unresolved_venue(pg, uid)["resolved_venue_id"]
    assert _state(pg, [other])[other][0] is None          # the confirm wrote only its own
    run_normalization()
    assert _state(pg, [own, other]) and {v[0] for v in _state(pg, [own, other]).values()} == {venue}
