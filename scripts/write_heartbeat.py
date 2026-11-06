"""Entrypoint for heartbeat.yml. Writes heartbeat.json onto the data branch.

Reads its facts from the environment rather than from arguments, because the
facts come from GitHub's own context and a mismatch between a workflow
expression and an argument name is a silent failure. Every value is validated
here, so a missing one fails the step with a sentence instead of writing a
payload with `None` in it.

Usage:
    python scripts/write_heartbeat.py <data-branch-checkout-dir>
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline.emit.heartbeat import (
    build_heartbeat,
    derive_unassisted_total,
    load_schedule,
)
from pipeline.emit.push import commit_and_push

WORKFLOW_FILE = "heartbeat.yml"
HEARTBEAT_FILENAME = "heartbeat.json"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2

    data_dir = Path(argv[1]).resolve()
    if not data_dir.is_dir():
        print(f"error: {data_dir} is not a directory", file=sys.stderr)
        return 2

    schedule = load_schedule(REPO_ROOT / "trigger-schedule.json")

    event_name = _require_env("GITHUB_EVENT_NAME")
    run_number = int(_require_env("GITHUB_RUN_NUMBER"))
    source_commit = _require_env("GITHUB_SHA")[:12]

    # Both of these are claims from the dispatcher, absent on a schedule event.
    dispatch_source = os.environ.get("DISPATCH_SOURCE") or None
    scheduled_for = _parse_optional_iso(os.environ.get("DISPATCH_SCHEDULED_FOR"))

    # Whether the external timer is live. This drives which cadence the page
    # declares, so that before the Worker exists the page honestly states
    # GitHub's measured 4 to 5 hour cadence instead of an aspirational hourly
    # one. A repo variable, not a guess.
    external_timer_armed = _env_flag("EXTERNAL_TIMER_ARMED")

    heartbeat_path = data_dir / HEARTBEAT_FILENAME
    previous = _read_previous(heartbeat_path)

    payload = build_heartbeat(
        previous=previous,
        run_number=run_number,
        written_at=dt.datetime.now(dt.UTC),
        source_commit=source_commit,
        event_name=event_name,
        dispatch_source=dispatch_source,
        dispatch_scheduled_for=scheduled_for,
        schedule=schedule,
        workflow_file=WORKFLOW_FILE,
        external_timer_armed=external_timer_armed,
    )

    heartbeat_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    unassisted = derive_unassisted_total(payload["writes_by_trigger"])
    trigger_kind = _trigger_kind(payload)

    # Logged, not stored. The page derives the same number from the same rule.
    print(f"trigger:            {event_name} / {dispatch_source or 'none'} -> {trigger_kind}")
    print(f"run_number:         {payload['run_number']}")
    print(f"dispatch_lag_s:     {payload['dispatch_lag_seconds']}")
    print(f"writes_by_trigger:  {payload['writes_by_trigger']}")
    print(f"unassisted (derived): {unassisted}")
    print(f"trigger_mode:       {payload['trigger_mode']}")
    print(f"cadence/stale (min): {payload['expected_cadence_minutes']}/{payload['stale_after_minutes']}")

    log = commit_and_push(
        data_dir,
        paths=[HEARTBEAT_FILENAME],
        message=(
            f"heartbeat: run {run_number} via {trigger_kind}\n\n"
            f"Written by {event_name}. unassisted writes so far: {unassisted}."
        ),
    )
    if log.attempts == 0:
        print("no change to heartbeat.json, nothing committed")
    else:
        print(f"pushed: {log.summary()}")

    _write_step_summary(payload, unassisted, trigger_kind)
    return 0


def _trigger_kind(payload: dict) -> str:
    """Which counter this write incremented, read back from the payload itself."""
    from pipeline.emit.heartbeat import classify_trigger

    return classify_trigger(payload["triggered_by"], payload["dispatch_source"])


def _read_previous(path: Path) -> dict | None:
    """Read the existing heartbeat, tolerating absence and corruption.

    A corrupt file must not take the run down, but it also must not silently
    reset the counter: build_heartbeat carries forward whatever keys it can
    recognise. Here we only decide whether there is anything to carry.
    """
    if not path.exists():
        print(f"{path.name} does not exist yet, this is the first write")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(
            f"warning: {path.name} is unreadable ({exc}). Counters that cannot be "
            f"recovered will restart at zero, which is visible on the page.",
            file=sys.stderr,
        )
        return None


def _write_step_summary(payload: dict, unassisted: int, trigger_kind: str) -> None:
    """Put the numbers in the run summary, so the Actions tab is diagnostic.

    Attempt 1's hardest problem was telling "dispatched but never ran" from
    "scheduler did not fire". A run whose summary states its own trigger makes
    that distinction readable without opening logs.
    """
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = [
        "### heartbeat",
        "",
        f"- run_number: `{payload['run_number']}`",
        f"- triggered_by: `{payload['triggered_by']}`",
        f"- dispatch_source (a claim): `{payload['dispatch_source'] or 'none'}`",
        f"- counted as: `{trigger_kind}`",
        f"- dispatch_lag_seconds (checkable): `{payload['dispatch_lag_seconds']}`",
        f"- unassisted writes, derived: `{unassisted}`",
        f"- trigger_mode: `{payload['trigger_mode']}`",
        "",
    ]
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(
            f"error: {name} is not set. This script expects GitHub Actions context."
        )
    return value


def _env_flag(name: str) -> bool:
    """Parse a repo variable as a boolean.

    GitHub repo variables are strings, and an unset variable is an empty
    string, so this must treat absence as false without complaining.
    """
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _parse_optional_iso(value: str | None) -> dt.datetime | None:
    if not value or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
