"""Which code a backup's snapshot was taken under (v0.96.52). Stdlib only.

`scripts/backup.sh` runs on the host as the backup owner, beside whatever
image is running. Until v0.96.52 it labelled a backup with the release tag
of the running version and, when no tag existed but that version matched
the checkout's, with the checkout's HEAD. On a same-version redeploy before
the tag (v0.96.51's recovery: running 1c012c3, checkout 06c46cb) the
pre-deploy backup was labelled with the commit being *deployed*, not the
one that wrote the data. HEAD is what is about to run; it says nothing
about what ran.

Now the running commit comes from the running container's image label
(`org.opencontainers.image.revision`, set by `deploy-production.sh` at
build time), else from the release tag of the running version (images built
before v0.96.52 carry no label), else it is UNKNOWN - never guessed. The
checkout's HEAD is recorded beside it as the candidate commit.

    python3 -m runtime.backup_provenance --label L --running-version V \
        --tag-commit T --head H --checkout-version C

prints ``KEY=value`` lines for the shell (values are hex, versions or
UNKNOWN; nothing needs quoting).
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta, timezone

UNKNOWN = "UNKNOWN"
SOURCE_IMAGE_LABEL = "image-label"
SOURCE_RELEASE_TAG = "release-tag"
SOURCE_UNKNOWN = "unknown"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_VERSION = re.compile(r"^[0-9][0-9A-Za-z.+-]{0,40}$")
KST = timezone(timedelta(hours=9))


def _sha(value: str | None) -> str | None:
    value = (value or "").strip().lower()
    return value if _SHA.match(value) else None


def _version(value: str | None) -> str | None:
    value = (value or "").strip()
    return value if _VERSION.match(value) else None


def resolve(*, label: str | None, running_version: str | None, tag_commit: str | None,
            head: str | None, checkout_version: str | None,
            now: datetime | None = None) -> dict[str, str]:
    """The provenance fields a manifest records. Pure (``now`` aside)."""
    labelled, tagged = _sha(label), _sha(tag_commit)
    if labelled:
        running, source = labelled, SOURCE_IMAGE_LABEL
    elif tagged and _version(running_version):
        running, source = tagged, SOURCE_RELEASE_TAG
    else:
        running, source = UNKNOWN, SOURCE_UNKNOWN
    moment = (now or datetime.now(timezone.utc)).astimezone(KST)
    return {
        "RUNNING_COMMIT": running,
        "RUNNING_COMMIT_SOURCE": source,
        "CANDIDATE_COMMIT": _sha(head) or UNKNOWN,
        "CANDIDATE_VERSION": _version(checkout_version) or UNKNOWN,
        "SNAPSHOT_TIME_KST": moment.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for name in ("label", "running-version", "tag-commit", "head", "checkout-version"):
        parser.add_argument(f"--{name}", default="")
    args = parser.parse_args(argv)
    fields = resolve(label=args.label, running_version=args.running_version,
                     tag_commit=args.tag_commit, head=args.head,
                     checkout_version=args.checkout_version)
    for key, value in fields.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
