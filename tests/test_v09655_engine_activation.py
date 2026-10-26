"""v0.96.55 - ENGINE 1.17 and review-aware re-extraction, activated.

The operator REJECTed all seven rows a bump would otherwise have decided
(DATA-01 x6 and DATA-07, review actions 1201-1209) and then authorized, as
two separate decisions, ENGINE_VERSION=1.17 and REVIEW_AWARE_REEXTRACT=1.

On the 2026-10-25 KST snapshot, at 1.17 with the gate on: no Event removed,
no id or fold moved, the seven rejected rows kept HIDDEN/REJECTED
(review_rejected_kept 7), Human records byte-identical, and one new
programme - 6826's Sunday 10/25 social. A second pass changes nothing.

The gate stays off by default in code: it is set per deployment, in `.env`.
The re-extract backlog now reports the setting the running process reads,
which is what a rollout is checked against.
"""

from __future__ import annotations

import pytest

from runtime import config
from runtime.normalization import NORMALIZATION_VERSION

ADMIN = ("dancemate", "test-admin-password")


def test_the_engine_is_bumped_and_normalization_is_not():
    # v0.96.56 bumps it again (1.18, time roles); normalization still 3.
    assert config.DEFAULT_ENGINE_VERSION == "1.18"
    assert NORMALIZATION_VERSION == "3"


def test_the_gate_is_still_a_deployment_decision(monkeypatch):
    monkeypatch.delenv("REVIEW_AWARE_REEXTRACT", raising=False)
    assert config.load_settings().review_aware_reextract is False


def _client(monkeypatch, gate):
    from fastapi.testclient import TestClient

    from runtime import app as app_module

    monkeypatch.setenv("ADMIN_USERNAME", ADMIN[0])
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN[1])
    if gate is None:
        monkeypatch.delenv("REVIEW_AWARE_REEXTRACT", raising=False)
    else:
        monkeypatch.setenv("REVIEW_AWARE_REEXTRACT", gate)
    monkeypatch.setattr(app_module, "_settings", None)
    return TestClient(app_module.app, raise_server_exceptions=False)


@pytest.mark.parametrize("gate, expected", [(None, False), ("0", False), ("1", True)])
def test_the_backlog_reports_the_gate_the_process_runs_with(pg, monkeypatch, gate, expected):
    backlog = _client(monkeypatch, gate).get("/api/admin/events/reextract-backlog",
                                             auth=ADMIN)
    assert backlog.status_code == 200
    body = backlog.json()
    assert body["review_aware_reextract"] is expected
    assert body["engine_version"] == config.load_settings().engine_version
    assert {"current", "outdated", "stalled", "with_content"} <= set(body)
