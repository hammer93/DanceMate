"""Preview/apply verified public boards through DanceMate's Admin Source API.

Run as the repository owner on the board. This uses .env Basic credentials
without putting a Korean name or a password on a shell command line. It does
not crawl private pages and never writes Sources with raw SQL.

v0.96.20: the spec file, not this script, now says which genre, platform, role,
authority and board type a source has. v0.82's Salsa round hard-coded
``genre_code="SALSA"`` and a single ``board_url``, which meant a Swing board
could not be registered through the one path that already carries the whole
admission gate - preview, ``/test`` must PASS with items, enable only then,
record a decision, then read the row back. Adding a second copy of that gate
for Swing would have been the wrong kind of duplication, so the gate stayed and
the spec grew fields. ``docs/SALSA_BOARD_SOURCES.json`` still applies unchanged:
every added field defaults to exactly what that file already meant.

A spec may also ask to be registered and left disabled (``"enable": false``) -
a board whose live yield was measured and found to be real but not an event
feed. It is written with its verified config so the next audit starts from
evidence rather than from a URL, ``/test`` still has to pass for it, and it is
recorded with `source_ops`' own MONITOR decision rather than a new word.
"""

from __future__ import annotations

import argparse
import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_FILE = ROOT / "docs" / "SALSA_BOARD_SOURCES.json"
# v0.82's name, kept so anything importing it still resolves.
SOURCE_FILE = DEFAULT_SOURCE_FILE


def _env() -> dict[str, str]:
    values = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


class Admin:
    def __init__(self, env: dict[str, str]):
        user = env.get("ADMIN_USERNAME", "dancemate")
        password = env.get("ADMIN_PASSWORD")
        if not password:
            raise RuntimeError("ADMIN_PASSWORD is absent; no Source write attempted")
        credential = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.authorization = f"Basic {credential}"
        host = env.get("DANCEMATE_BIND_ADDRESS", "127.0.0.1")
        if host in ("0.0.0.0", "::", ""):
            host = "127.0.0.1"
        port = int(env.get("DANCEMATE_PORT", "8080"))
        self.base = f"http://{host}:{port}"

    def request(self, path: str, *, method: str = "GET", data=None):
        headers = {"Authorization": self.authorization}
        payload = None
        if data is not None:
            if isinstance(data, dict):
                payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
                headers["Content-Type"] = "application/json; charset=utf-8"
            else:
                payload = urllib.parse.urlencode(data).encode("utf-8")
                headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(self.base + path, data=payload,
                                         headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
                if "json" in response.headers.get("Content-Type", ""):
                    return json.loads(body.decode("utf-8"))
                return {"http_status": response.status}
        except urllib.error.HTTPError as exc:
            detail = exc.read(500).decode("utf-8", errors="replace")
            raise RuntimeError(f"Admin API {path} returned {exc.code}: {detail}") from exc


def board_config(spec: dict) -> dict:
    """The `config` a spec asks for, defaulting to v0.82's Salsa round exactly.

    One board stays `board_url`; a source that reads several of its cafe's
    boards lists them in `board_urls`. Both produce the same shape the
    `daum_cafe_board` collector already reads.
    """
    board_urls = spec.get("board_urls") or [spec["board_url"]]
    return {
        "parser": spec.get("parser", "daum_cafe_board"),
        # Optional: a cafe the `communities` master does not list yet still
        # registers, exactly as SRC-D-021 has since v0.85.
        "community_id": spec.get("community_id"),
        "cafe_url": spec["url"],
        "board_name": spec["board_name"],
        "board_type": spec["board_type"],
        "board_urls": list(board_urls),
        "lookback_days": spec.get("lookback_days", 60),
        "genre_code": spec.get("genre_code", "SALSA"),
    }


def primary_board_url(spec: dict) -> str:
    """The url column: the board a reviewer should open first."""
    return spec.get("board_url") or (spec.get("board_urls") or [""])[0]


def apply(*, write: bool, source_file: Path = DEFAULT_SOURCE_FILE) -> None:
    admin = Admin(_env())
    specs = json.loads(source_file.read_text(encoding="utf-8"))
    genres = {row["code"]: row["genre_id"] for row in admin.request("/api/admin/genres")}
    regions = {row["code"]: row["region_id"] for row in admin.request("/api/admin/regions")}
    sources = {row["source_key"]: row for row in admin.request("/api/admin/sources")}
    for spec in specs:
        key = spec["source_key"]
        existing = sources.get(key)
        genre_code = spec.get("genre_code", "SALSA")
        if spec["region_code"] not in regions or genre_code not in genres:
            raise RuntimeError(f"missing Region/Genre master for {key}")
        config = board_config(spec)
        board_url = primary_board_url(spec)
        if spec["mode"] in ("REUSE", "UPGRADE") and (
            existing is None or existing["source_id"] != spec["expected_source_id"]
        ):
            raise RuntimeError(f"{key} reuse guard failed; review current Source")
        if existing and existing["enabled"]:
            same = (existing["url"] == board_url and existing["config"] == config
                    and existing["name"] == spec["name"])
            if same:
                print(f"{key}: already enabled with matching board config")
                continue
            # v0.96.20: an *enabled* row with different settings is normally a
            # mistake - two rounds disagreeing about the same source - so it
            # still aborts. UPGRADE is the one way to say it on purpose, and it
            # costs the same evidence as a fresh row: the source_id must be the
            # one the spec expects, and `/test` still has to PASS with items
            # before the row keeps its enabled flag. SRC-D-021 needed this: it
            # has collected since v0.85 through the cafe-name search route, and
            # its own public 정모 board (15 posts, every body readable) can only
            # be reached by giving it `parser: daum_cafe_board`.
            if spec["mode"] != "UPGRADE":
                raise RuntimeError(f"{key} is already enabled with different settings")
            print(f"{key}: UPGRADE of an enabled Source "
                  f"(was url={existing['url']})")
        if spec["mode"] == "ADD" and existing and (
            existing["url"] != board_url or existing["config"] != config
            or existing["name"] != spec["name"]
        ):
            raise RuntimeError(f"{key} exists with different settings; review before resuming")
        print(f"{key}: {spec['mode']} {genre_code} "
              f"community={spec.get('community_id')} "
              f"board={board_url} region={spec['region_code']} "
              f"enable={spec.get('enable', True)}")
        if not write:
            continue
        if spec["mode"] == "ADD" and not existing:
            row = admin.request("/api/admin/sources", method="POST", data={
                "source_key": key, "name": spec["name"],
                "platform": spec.get("platform", "DAUM_CAFE"),
                "source_role": spec.get("source_role", "COMMUNITY"),
                "authority_level": spec.get("authority_level", "PRIMARY_ORGANIZER"),
                "url": board_url, "genre_id": genres[genre_code],
                "region_id": regions[spec["region_code"]], "config": config,
                "queries": [], "enabled": False,
                "collection_interval_minutes": spec.get("interval_minutes", 180),
                "notes": spec.get(
                    "notes",
                    "Official public Community event-bearing board; 2026-09-16 audit"),
            })
        else:
            row = admin.request(f"/api/admin/sources/{existing['source_id']}",
                                method="PATCH", data={
                "name": spec["name"], "url": board_url, "config": config,
                "queries": [],
                "genre_id": genres[genre_code],
                "region_id": regions[spec["region_code"]],
                "authority_level": spec.get("authority_level", "PRIMARY_ORGANIZER"),
                "collection_interval_minutes": spec.get("interval_minutes", 180),
            })
        source_id = row["source_id"]
        test = admin.request(f"/api/admin/sources/{source_id}/test", method="POST")
        print(f"  test={test['status']} items={test.get('items', 0)}")
        if test["status"] != "PASS" or not test.get("items"):
            raise RuntimeError(f"{key} has no live public board yield; left disabled")
        reason = spec.get("decision_reason",
                          "Official dated public board verified 2026-09-16")
        if not spec.get("enable", True):
            # A board whose live yield is real but is not an event feed. The
            # row is written with its verified config and left off, so the next
            # audit argues with evidence instead of re-deriving it.
            # MONITOR is `source_ops.DECISIONS`' own word for this - "관찰 -
            # 판단 보류, 나중에 다시 본다" - so the operator UI shows the same
            # badge a human review would have set.
            admin.request(f"/admin/sources/{source_id}/decision", method="POST",
                          data=[("decision", "MONITOR"), ("reason", reason)])
            readback = {r["source_key"]: r
                        for r in admin.request("/api/admin/sources")}[key]
            if readback["enabled"] or readback["config"] != config:
                raise RuntimeError(f"{key} should be registered and left disabled")
            print(f"  MONITOR source_id={source_id} registered disabled PASS")
            continue
        admin.request(f"/api/admin/sources/{source_id}", method="PATCH",
                      data={"enabled": True})
        admin.request(f"/admin/sources/{source_id}/decision", method="POST",
                      data=[("decision", "ACTIVE"), ("reason", reason)])
        readback = {r["source_key"]: r for r in admin.request("/api/admin/sources")}[key]
        if not readback["enabled"] or readback["config"] != config:
            raise RuntimeError(f"{key} readback mismatch")
        print(f"  enabled source_id={source_id} PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--preview", action="store_true")
    group.add_argument("--apply", action="store_true")
    parser.add_argument("--file", default=str(DEFAULT_SOURCE_FILE),
                        help="spec file to apply (default: the v0.82 Salsa round)")
    args = parser.parse_args()
    apply(write=args.apply, source_file=Path(args.file))
