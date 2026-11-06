"""Fail if any committed baseline file approaches GitHub's file size limit.

GitHub **rejects** any single file over 100 MB and warns above 50 MB. The Tier 0
baselines are committed to `main` under `pipeline/baselines/` by design, as
inputs to CI rather than outputs of it, so this is a hard platform constraint
and not a tidiness preference.

The D1 estimate for `(h3_r5, week_of_year)` keying ran from about 55 MB to about
109 MB depending on how many cells have any fire history. That straddles the
limit, which is why the baseline is partitioned by `week_of_year` into 52 shards
of roughly 1 to 2 MB each.

The ceiling here is deliberately 40 MB, not 99 MB. A limit set just under the
platform's own limit gives no warning before failure, and the failure mode is a
rejected push after the work is done. 40 MB means a shard would have to grow
more than twentyfold before anything breaks, and the alarm sounds long before
the wall.

Usage:
    python scripts/check_baseline_sizes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_DIR = REPO_ROOT / "pipeline" / "baselines"

# Our ceiling, well below the platform's.
MAX_FILE_MB = 40.0

# GitHub's own thresholds, for the error message.
GITHUB_WARN_MB = 50.0
GITHUB_REJECT_MB = 100.0

# A whole-tree ceiling too. The data branch size constraint in ARCHITECTURE
# section 8 applies to clone time, and a thousand compliant shards is still a
# slow clone.
MAX_TOTAL_MB = 250.0

SKIP_SUFFIXES = {".md", ".txt", ".gitkeep"}


def main() -> int:
    if not BASELINE_DIR.is_dir():
        print(f"{BASELINE_DIR.relative_to(REPO_ROOT)} does not exist yet, nothing to check")
        return 0

    files = [
        p
        for p in sorted(BASELINE_DIR.rglob("*"))
        if p.is_file() and p.suffix.lower() not in SKIP_SUFFIXES
    ]

    if not files:
        print("no baseline data files committed yet, nothing to check")
        return 0

    oversized: list[tuple[Path, float]] = []
    total_mb = 0.0

    for path in files:
        mb = path.stat().st_size / 1_048_576
        total_mb += mb
        if mb > MAX_FILE_MB:
            oversized.append((path, mb))

    print(f"{len(files)} baseline file(s), {total_mb:.1f} MB total")
    largest = max(files, key=lambda p: p.stat().st_size)
    print(f"largest: {largest.relative_to(REPO_ROOT)} at {largest.stat().st_size / 1_048_576:.1f} MB")

    failed = False

    for path, mb in oversized:
        failed = True
        rel = path.relative_to(REPO_ROOT)
        print(f"\nERROR: {rel} is {mb:.1f} MB, over the {MAX_FILE_MB:.0f} MB ceiling.", file=sys.stderr)
        if mb > GITHUB_REJECT_MB:
            print("  GitHub will REJECT this file outright.", file=sys.stderr)
        elif mb > GITHUB_WARN_MB:
            print(f"  GitHub warns above {GITHUB_WARN_MB:.0f} MB and rejects above {GITHUB_REJECT_MB:.0f} MB.", file=sys.stderr)
        print(
            "  Fix by partitioning further, or by dropping rows that can never be\n"
            "  scored. Only `good` and `sparse` keys need statistics; `insufficient`\n"
            "  and `unavailable` are resolved from a compact cell level set.\n"
            "  See DETECTION_SPEC.md section 2, storage.",
            file=sys.stderr,
        )

    if total_mb > MAX_TOTAL_MB:
        failed = True
        print(
            f"\nERROR: baselines total {total_mb:.1f} MB, over the {MAX_TOTAL_MB:.0f} MB ceiling.\n"
            f"  Every individual file may be compliant and the clone still be slow.",
            file=sys.stderr,
        )

    if failed:
        return 1

    print(f"all within the {MAX_FILE_MB:.0f} MB per file and {MAX_TOTAL_MB:.0f} MB total ceilings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
