"""Adapter between the Source Master and the Information Engine's collectors.

v0.75 writes no new collector. The engine already ships production collectors
for the Kakao Daum Cafe Search API and the Naver Blog/Cafe Search APIs, plus
snapshot loaders that replay recorded API responses through the same parsing
code. This module selects one for a Source Master row and translates its
`RawPostRecord` output into the runtime's `RawItem`.

Direction of travel:

    Source Master row  ->  engine collector  ->  RawPostRecord
                                             ->  RawItem  ->  source_items

Nothing here modifies engine source or engine schema.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings
from .intake import RawItem

# Which environment variable each platform's live collector needs. Checked
# before a collection is attempted so a missing key is reported as a
# configuration problem rather than a collection failure.
CREDENTIAL_ENV = {
    "DAUM_CAFE": ("KAKAO_REST_API_KEY",),
    "NAVER_CAFE": ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"),
    "NAVER_BLOG": ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"),
}

# Platforms v0.75 can actually collect from. FACEBOOK is deliberately absent:
# its access restrictions make it a poor first real source, and the engine's
# own source list already marks it ACCESS_LIMITED.
SUPPORTED_PLATFORMS = ("DAUM_CAFE", "NAVER_CAFE", "NAVER_BLOG")

MODE_LIVE = "live"
MODE_SNAPSHOT = "snapshot"


class CollectorUnavailable(RuntimeError):
    """The collector cannot run: unsupported platform or missing credentials."""


@dataclass(frozen=True)
class CollectionResult:
    mode: str
    items: list[RawItem]
    detail: str


def _engine_on_path(settings: Settings) -> None:
    root = str(settings.engine_root)
    if root not in sys.path:
        sys.path.insert(0, root)


def _engine_settings(settings: Settings) -> dict[str, Any]:
    path = settings.engine_root / "config" / "settings.json"
    return json.loads(path.read_text(encoding="utf-8"))


def missing_credentials(platform: str) -> list[str]:
    """Which required environment variables are absent for this platform."""
    return [name for name in CREDENTIAL_ENV.get(platform, ()) if not os.environ.get(name)]


def describe_capability(platform: str) -> dict[str, Any]:
    """What can this platform do right now, and why not more."""
    if platform not in SUPPORTED_PLATFORMS:
        return {
            "live": False,
            "snapshot": False,
            "detail": f"{platform} has no collector in v0.75",
        }
    missing = missing_credentials(platform)
    return {
        "live": not missing,
        "snapshot": True,
        "missing_credentials": missing,
        "detail": (
            "live collection available"
            if not missing
            else f"live collection needs {', '.join(missing)}"
        ),
    }


def _to_engine_source(source: dict[str, Any]) -> dict[str, Any]:
    """Shape a Source Master row the way the engine's collectors expect."""
    config = source.get("config") or {}
    queries = source.get("queries") or []
    if isinstance(queries, str):
        queries = json.loads(queries)
    if isinstance(config, str):
        config = json.loads(config)
    engine_source = {
        "source_id": source["source_key"],
        "platform": source["platform"],
        "source_role": source.get("source_role", "COMMUNITY"),
        "name": source.get("name"),
        "status": "ACTIVE" if source.get("enabled") else "INACTIVE",
        "authority_level": source.get("authority_level", "UNKNOWN"),
        "queries": queries,
    }
    # Collector-specific hints travel in config so the Source Master does not
    # need a column per platform.
    for key in ("cafe_name_hint", "url_contains", "access_state"):
        if key in config:
            engine_source[key] = config[key]
    return engine_source


def _parse_published(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    for candidate in (text, f"{text}T00:00:00+00:00"):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _to_raw_item(record: Any) -> RawItem:
    """Translate one engine RawPostRecord into a runtime RawItem."""
    payload = record.to_dict() if hasattr(record, "to_dict") else dict(record)
    url = payload.get("source_url") or ""
    return RawItem(
        # The engine identifies a post by its URL; nothing upstream gives a
        # better stable id across Daum and Naver alike.
        external_id=url or f"{payload.get('source_id')}:{payload.get('title')}",
        url=url or None,
        title=payload.get("title"),
        body=payload.get("body"),
        published_at=_parse_published(payload.get("published_at")),
        raw=payload,
    )


def _snapshot_path(settings: Settings, source: dict[str, Any]) -> Path | None:
    config = source.get("config") or {}
    if isinstance(config, str):
        config = json.loads(config)
    configured = config.get("snapshot_path")
    if configured:
        candidate = Path(configured)
        if not candidate.is_absolute():
            candidate = settings.engine_data_dir / configured
        return candidate if candidate.is_file() else None

    defaults = {
        "DAUM_CAFE": "collector_snapshots/daum-cafe-sample.json",
        "NAVER_CAFE": "collector_snapshots/naver-cafe-sample.json",
        "NAVER_BLOG": "collector_snapshots/naver-blog-sample.json",
    }
    relative = defaults.get(source["platform"])
    if not relative:
        return None
    candidate = settings.engine_data_dir / relative
    return candidate if candidate.is_file() else None


def collect(
    settings: Settings, source: dict[str, Any], *, mode: str = MODE_LIVE
) -> CollectionResult:
    """Run the engine's collector for one Source Master row.

    ``mode='live'`` calls the real upstream API and needs credentials.
    ``mode='snapshot'`` replays a recorded response through the same parsing
    code - the correct way to exercise the pipeline without an API key, and
    honest about being offline data.
    """
    platform = source["platform"]
    if platform not in SUPPORTED_PLATFORMS:
        raise CollectorUnavailable(f"{platform} has no collector in v0.75")

    _engine_on_path(settings)
    engine_source = _to_engine_source(source)

    if mode == MODE_SNAPSHOT:
        return _collect_snapshot(settings, source, engine_source)
    if mode != MODE_LIVE:
        raise CollectorUnavailable(f"unknown collection mode: {mode}")

    missing = missing_credentials(platform)
    if missing:
        raise CollectorUnavailable(
            f"live collection from {platform} needs {', '.join(missing)} in .env"
        )
    return _collect_live(settings, source, engine_source)


def _collect_snapshot(
    settings: Settings, source: dict[str, Any], engine_source: dict[str, Any]
) -> CollectionResult:
    path = _snapshot_path(settings, source)
    if path is None:
        raise CollectorUnavailable(
            f"no snapshot available for {source['platform']}; "
            "set config.snapshot_path or ship a fixture"
        )
    platform = source["platform"]
    if platform == "DAUM_CAFE":
        from src.collectors.daum import load_snapshot  # noqa: PLC0415

        records = load_snapshot(path, engine_source, query="snapshot")
    else:
        from src.collectors.naver import load_naver_snapshot  # noqa: PLC0415

        kind = "blog" if platform == "NAVER_BLOG" else "cafe"
        records = load_naver_snapshot(
            path, kind=kind, source_id=engine_source["source_id"], query="snapshot"
        )
    return CollectionResult(
        mode=MODE_SNAPSHOT,
        items=[_to_raw_item(r) for r in records],
        detail=f"snapshot {path.name}: {len(records)} records",
    )


def _collect_live(
    settings: Settings, source: dict[str, Any], engine_source: dict[str, Any]
) -> CollectionResult:
    platform = source["platform"]
    engine_config = _engine_settings(settings)

    if platform == "DAUM_CAFE":
        from src.collectors.daum import DaumCafeSearchCollector  # noqa: PLC0415

        daum = engine_config["daum"]
        collector = DaumCafeSearchCollector(
            daum["endpoint"], timeout_seconds=daum.get("timeout_seconds", 15)
        )
        records = collector.collect_source(
            engine_source,
            sort=daum.get("sort", "recency"),
            page=daum.get("page", 1),
            size=daum.get("size", 50),
        )
    else:
        from src.collectors.naver import NaverSearchCollector  # noqa: PLC0415

        naver = engine_config["naver"]
        collector = NaverSearchCollector(
            timeout_seconds=naver.get("timeout_seconds", 15)
        )
        kind = "blog" if platform == "NAVER_BLOG" else "cafe"
        records = []
        seen: set[str] = set()
        for query in engine_source.get("queries") or []:
            for record in collector.search(
                query,
                kind=kind,
                source_id=engine_source["source_id"],
                display=naver.get("display", 100),
                start=naver.get("start", 1),
                sort=naver.get("sort", "date"),
            ):
                # The same post can match several queries; store it once.
                if record.source_url and record.source_url in seen:
                    continue
                if record.source_url:
                    seen.add(record.source_url)
                records.append(record)

    return CollectionResult(
        mode=MODE_LIVE,
        items=[_to_raw_item(r) for r in records],
        detail=f"live {platform}: {len(records)} records",
    )


def test_source(settings: Settings, source: dict[str, Any]) -> dict[str, Any]:
    """Admin [Test] button: can this source be collected, and how?

    Deliberately does not write anything - it reports reachability and
    configuration, so an operator can tell a misconfigured source from an
    unreachable one before enabling it.
    """
    platform = source["platform"]
    capability = describe_capability(platform)
    result: dict[str, Any] = {
        "source_key": source.get("source_key"),
        "platform": platform,
        **capability,
    }
    if not capability["snapshot"] and not capability["live"]:
        result["status"] = "UNSUPPORTED"
        return result

    snapshot = _snapshot_path(settings, source)
    result["snapshot_path"] = str(snapshot) if snapshot else None

    mode = MODE_LIVE if capability["live"] else MODE_SNAPSHOT
    try:
        collected = collect(settings, source, mode=mode)
    except CollectorUnavailable as exc:
        result["status"] = "NOT_CONFIGURED"
        result["detail"] = str(exc)
        return result
    except Exception as exc:  # a failing upstream must not 500 the admin page
        result["status"] = "FAIL"
        result["detail"] = f"{type(exc).__name__}: {exc}"
        return result

    result["status"] = "PASS"
    result["mode"] = collected.mode
    result["items"] = len(collected.items)
    result["detail"] = collected.detail
    result["sample_titles"] = [i.title for i in collected.items[:3] if i.title]
    return result
