"""Deployment-target helpers for the ROCKPro64 (PINE64 / RK3399 / ARM64).

Two different questions, deliberately kept apart:

  * ``current_architecture()`` - what am I running on right now?
  * ``dockerfile_arm64_report()`` - would the image we build run on the target?

The second one is a *static* check. It is what CI and the unit tests can
assert on a developer's amd64 laptop; it is not a claim that the image has
been executed on ARM64 hardware.
"""

from __future__ import annotations

import platform
import re
from pathlib import Path
from typing import Any

from .config import REPO_ROOT

TARGET_ARCHITECTURES = frozenset({"aarch64", "arm64"})
TARGET_DESCRIPTION = "PINE64 ROCKPro64 v2.1 / Rockchip RK3399 / ARM64 / Debian 13"

# Image tags that are published as multi-arch manifests including linux/arm64.
KNOWN_MULTIARCH_PREFIXES = ("python:", "postgres:")

# Anything that would pin the build to x86.
X86_MARKERS = re.compile(
    r"(amd64|x86_64|i386|--platform\s*=\s*linux/amd64)", re.IGNORECASE
)

FROM_LINE = re.compile(r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)", re.IGNORECASE | re.MULTILINE)


def current_architecture() -> str:
    return platform.machine().lower()


def is_deployment_target() -> bool:
    return current_architecture() in TARGET_ARCHITECTURES


def dockerfile_arm64_report(path: Path | None = None) -> dict[str, Any]:
    """Static ARM64 compatibility report for the runtime image definition."""
    path = path or (REPO_ROOT / "Dockerfile")
    if not path.is_file():
        return {"status": "FAIL", "detail": f"Dockerfile not found at {path}"}

    text = path.read_text(encoding="utf-8")
    # Comments describe the target; only instructions can pin an architecture.
    instructions = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )

    bases = FROM_LINE.findall(text)
    unknown = [b for b in bases if not b.startswith(KNOWN_MULTIARCH_PREFIXES)]
    x86_pins = X86_MARKERS.findall(instructions)

    if not bases:
        return {"status": "FAIL", "detail": "no FROM instruction found", "bases": []}
    if unknown:
        return {
            "status": "WARN",
            "detail": f"base image(s) not on the known multi-arch list: {unknown}",
            "bases": bases,
        }
    if x86_pins:
        return {
            "status": "FAIL",
            "detail": f"x86-specific markers in build instructions: {sorted(set(x86_pins))}",
            "bases": bases,
        }
    return {
        "status": "PASS",
        "detail": "all base images publish linux/arm64 manifests; no x86 pins",
        "bases": bases,
        "target": TARGET_DESCRIPTION,
    }
