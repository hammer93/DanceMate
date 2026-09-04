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
    # All three Naver platforms are one NAVER API HUB subscription. The
    # variables keep their old names; the keys behind them are API HUB keys.
    "NAVER_CAFE": ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"),
    "NAVER_BLOG": ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"),
    "NAVER_WEB": ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"),
}

# Platforms this version can actually collect from. FACEBOOK is deliberately
# absent: its access restrictions make it a poor first real source, and the
# engine's own source list already marks it ACCESS_LIMITED.
#
# WEB needs no credential and no engine-side collector - runtime.web_discovery
# scrapes the source's own board list page directly, so it is dispatched
# separately from the Daum/Naver branch below rather than through
# `_to_engine_source`/the engine's collector classes.
SUPPORTED_PLATFORMS = ("DAUM_CAFE", "NAVER_CAFE", "NAVER_BLOG", "NAVER_WEB", "WEB")

# Which Naver search each platform reads. API HUB serves blog, cafearticle and
# webkr for these credentials; news and local are not subscribed.
NAVER_KIND = {"NAVER_BLOG": "blog", "NAVER_CAFE": "cafe", "NAVER_WEB": "web"}

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


def _config(source: dict[str, Any]) -> dict[str, Any]:
    config = source.get("config") or {}
    return json.loads(config) if isinstance(config, str) else config


def _to_engine_source(source: dict[str, Any]) -> dict[str, Any]:
    """Shape a Source Master row the way the engine's collectors expect."""
    config = _config(source)
    queries = source.get("queries") or []
    if isinstance(queries, str):
        queries = json.loads(queries)
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
    config = _config(source)
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
    elif platform == "WEB":
        config = _config(source)
        discovery = _web_discovery_module(config.get("parser") or WEB_PARSER_BOARD)
        list_url = (config.get("board_urls") or [""])[0]
        records = discovery.parse_list(
            path.read_text(encoding="utf-8"), list_url
        )
        for record in records:
            record["source_id"] = engine_source["source_id"]
            record["platform"] = platform
    else:
        from src.collectors.naver import load_naver_snapshot  # noqa: PLC0415

        kind = NAVER_KIND.get(platform, "cafe")
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

    if platform == "WEB":
        return _collect_web(source, engine_source)

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
        kind = NAVER_KIND.get(platform, "cafe")
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


# Which discovery module reads a WEB source's list page(s), selected by the
# source's own config.parser - not by platform, since two WEB sources can
# have genuinely different page shapes (K-TANGO's HTML board rows vs
# danceinfo.net's embedded listing JSON) that no single regex or selector
# config could honestly cover (Section 34/35: verify before generalizing).
# "board" (K-TANGO-style HTML rows) is the default so every WEB source
# registered before this module existed keeps behaving exactly as before.
WEB_PARSER_BOARD = "board"
WEB_PARSER_DANCEINFO = "danceinfo_json"


def _web_discovery_module(parser: str):
    if parser == WEB_PARSER_DANCEINFO:
        from . import danceinfo_discovery  # noqa: PLC0415

        return danceinfo_discovery
    from . import web_discovery  # noqa: PLC0415

    return web_discovery


def _collect_web(source: dict[str, Any], engine_source: dict[str, Any]) -> CollectionResult:
    """Walk every list page a WEB source names in `config.board_urls`.

    No credential, no engine collector - the discovery module reads the
    source's own list page(s) directly.
    """
    config = _config(source)
    board_urls = config.get("board_urls") or []
    if not board_urls:
        raise CollectorUnavailable(
            "WEB source has no config.board_urls to collect from"
        )
    discovery = _web_discovery_module(config.get("parser") or WEB_PARSER_BOARD)

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for board_url in board_urls:
        for record in discovery.discover(
            board_url, source_id=engine_source["source_id"]
        ):
            url = record.get("source_url")
            if url and url in seen:
                continue
            if url:
                seen.add(url)
            records.append(record)

    return CollectionResult(
        mode=MODE_LIVE,
        items=[_to_raw_item(r) for r in records],
        detail=f"live WEB: {len(records)} records from {len(board_urls)} board(s)",
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
        # Same classification the scheduler uses, so the [Test] button and the
        # Sources list never disagree about what went wrong.
        from . import collector_errors  # noqa: PLC0415 - avoids an import cycle

        classified = collector_errors.classify(exc)
        result["status"] = classified.kind
        result["detail"] = classified.summary()
        result["retryable"] = classified.retryable
        if classified.status_code:
            result["http_status"] = classified.status_code
        return result

    # A snapshot run must never read as a live pass. An operator glancing at
    # "PASS" would otherwise conclude the credential works.
    result["status"] = "PASS" if collected.mode == MODE_LIVE else "PASS_SNAPSHOT"
    result["mode"] = collected.mode
    result["items"] = len(collected.items)
    result["detail"] = collected.detail
    result["sample_titles"] = [i.title for i in collected.items[:3] if i.title]

    # A live call that answered but matched nothing is the confusing case: the
    # credential works, the provider returned results, and the source's own
    # url_contains/cafe_name_hint filter rejected all of them. Reporting that
    # as a plain PASS sends an operator hunting for a credential problem that
    # does not exist, so say which half failed.
    if collected.mode == MODE_LIVE and not collected.items:
        diagnosis = _diagnose_empty_live(settings, source)
        result.update(diagnosis)
        if diagnosis.get("provider_results", 0) > 0:
            result["status"] = "PASS_NO_MATCH"
    return result


def _diagnose_empty_live(settings: Settings, source: dict[str, Any]) -> dict[str, Any]:
    """Why did a working live call yield nothing - no results, or a filter?

    Issues one unfiltered search so the provider's own result count can be
    compared with what the source's filter accepted. Read-only, one request.
    """
    platform = source["platform"]
    engine_source = _to_engine_source(source)
    queries = engine_source.get("queries") or []
    if not queries:
        return {"diagnosis": "the source has no search query"}

    try:
        engine_config = _engine_settings(settings)
        if platform == "DAUM_CAFE":
            from src.collectors.daum import (  # noqa: PLC0415
                DaumCafeSearchCollector, _matches_source,
            )

            daum = engine_config["daum"]
            collector = DaumCafeSearchCollector(
                daum["endpoint"], timeout_seconds=daum.get("timeout_seconds", 15)
            )
            payload = collector.search(queries[0], sort=daum.get("sort", "recency"),
                                       page=1, size=daum.get("size", 50))
            documents = payload.get("documents", [])
            matched = sum(1 for d in documents if _matches_source(d, engine_source))
            filters = {
                "cafe_name_hint": engine_source.get("cafe_name_hint"),
                "url_contains": engine_source.get("url_contains"),
            }
            sample_urls = [d.get("url") for d in documents[:3]]
        else:
            from src.collectors.naver import NaverSearchCollector  # noqa: PLC0415

            naver = engine_config["naver"]
            collector = NaverSearchCollector(
                timeout_seconds=naver.get("timeout_seconds", 15)
            )
            kind = NAVER_KIND.get(platform, "cafe")
            records = collector.search(
                queries[0], kind=kind, source_id=engine_source["source_id"],
                display=naver.get("display", 100), start=1,
                sort=naver.get("sort", "date"),
            )
            documents = records
            matched = len(records)
            filters = {}
            sample_urls = [r.source_url for r in records[:3]]
    except Exception as exc:
        return {"diagnosis": f"could not diagnose: {type(exc).__name__}: {exc}"}

    if not documents:
        return {
            "provider_results": 0,
            "diagnosis": f"the provider returned no result for {queries[0]!r}",
        }
    return {
        "provider_results": len(documents),
        "matched_by_filter": matched,
        "filters": filters,
        "provider_sample_urls": sample_urls,
        "diagnosis": (
            f"the provider returned {len(documents)} results for {queries[0]!r} but "
            f"this source's filter matched {matched}. "
            "Check url_contains / cafe_name_hint - the engine requires EVERY "
            "url_contains token to appear in the same URL."
        ),
    }
