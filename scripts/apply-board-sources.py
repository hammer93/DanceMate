"""Preview/apply verified public boards through DanceMate's Admin Source API.

Run as the repository owner on the board. This uses .env Basic credentials
without putting a Korean name or a password on a shell command line. It does
not crawl private pages and never writes Sources with raw SQL.
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
SOURCE_FILE = ROOT / "docs" / "SALSA_BOARD_SOURCES.json"


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


def apply(*, write: bool) -> None:
    admin = Admin(_env())
    specs = json.loads(SOURCE_FILE.read_text(encoding="utf-8"))
    genres = {row["code"]: row["genre_id"] for row in admin.request("/api/admin/genres")}
    regions = {row["code"]: row["region_id"] for row in admin.request("/api/admin/regions")}
    sources = {row["source_key"]: row for row in admin.request("/api/admin/sources")}
    for spec in specs:
        key = spec["source_key"]
        existing = sources.get(key)
        if spec["region_code"] not in regions or "SALSA" not in genres:
            raise RuntimeError(f"missing Region/Genre master for {key}")
        config = {
            "parser": "daum_cafe_board", "community_id": spec["community_id"],
            "cafe_url": spec["url"],
            "board_name": spec["board_name"], "board_type": spec["board_type"],
            "board_urls": [spec["board_url"]], "lookback_days": 60,
            "genre_code": "SALSA",
        }
        if spec["mode"] == "REUSE" and (
            existing is None or existing["source_id"] != spec["expected_source_id"]
        ):
            raise RuntimeError(f"{key} reuse guard failed; review current Source")
        if existing and existing["enabled"]:
            if (existing["url"] != spec["board_url"] or existing["config"] != config
                    or existing["name"] != spec["name"]):
                raise RuntimeError(f"{key} is already enabled with different settings")
            print(f"{key}: already enabled with matching board config")
            continue
        if spec["mode"] == "ADD" and existing and (
            existing["url"] != spec["board_url"] or existing["config"] != config
            or existing["name"] != spec["name"]
        ):
            raise RuntimeError(f"{key} exists with different settings; review before resuming")
        print(f"{key}: {spec['mode']} community={spec['community_id']} "
              f"board={spec['board_url']} region={spec['region_code']}")
        if not write:
            continue
        if spec["mode"] == "ADD" and not existing:
            row = admin.request("/api/admin/sources", method="POST", data={
                "source_key": key, "name": spec["name"], "platform": "DAUM_CAFE",
                "source_role": "COMMUNITY", "authority_level": "PRIMARY_ORGANIZER",
                "url": spec["board_url"], "genre_id": genres["SALSA"],
                "region_id": regions[spec["region_code"]], "config": config,
                "queries": [], "enabled": False,
                "collection_interval_minutes": 180,
                "notes": "Official public Community event-bearing board; 2026-09-16 audit",
            })
        else:
            row = admin.request(f"/api/admin/sources/{existing['source_id']}",
                                method="PATCH", data={
                "name": spec["name"], "url": spec["board_url"], "config": config,
                "queries": [],
                "genre_id": genres["SALSA"],
                "region_id": regions[spec["region_code"]],
                "authority_level": "PRIMARY_ORGANIZER",
                "collection_interval_minutes": 180,
            })
        source_id = row["source_id"]
        test = admin.request(f"/api/admin/sources/{source_id}/test", method="POST")
        print(f"  test={test['status']} items={test.get('items', 0)}")
        if test["status"] != "PASS" or not test.get("items"):
            raise RuntimeError(f"{key} has no live public board yield; left disabled")
        admin.request(f"/api/admin/sources/{source_id}", method="PATCH",
                      data={"enabled": True})
        admin.request(f"/admin/sources/{source_id}/decision", method="POST",
                      data=[("decision", "ACTIVE"),
                            ("reason", "Official dated public board verified 2026-09-16")])
        readback = {r["source_key"]: r for r in admin.request("/api/admin/sources")}[key]
        if not readback["enabled"] or readback["config"] != config:
            raise RuntimeError(f"{key} readback mismatch")
        print(f"  enabled source_id={source_id} PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--preview", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    apply(write=args.apply)
