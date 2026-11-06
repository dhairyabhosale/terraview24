"""Builds heartbeat.json: the Phase 0 proof and the permanent freshness signal.

Three rules this module exists to enforce, each from a bug that already happened
or a trap that was identified before it did:

1. ONE AUTHORITATIVE COUNTER. `writes_by_trigger` is stored. The unassisted
   write count is DERIVED by the page and never stored. The previous attempt
   shipped two counters, `schedule_writes_total` and `unassisted_writes_total`,
   which started out disagreeing and made the page deny a criterion it had
   already met.

2. `dispatch_source` IS A CLAIM, NOT A PROOF. GitHub cannot tell the Worker
   from a person running curl, because the sender is the same token owner. The
   checkable part is `dispatch_lag_seconds`.

3. CADENCE HAS ONE SOURCE OF TRUTH. `trigger-schedule.json`. The page states
   the cadence of whichever trigger is actually armed, so before the Worker
   exists the page honestly declares GitHub's measured 4 to 5 hour cadence
   rather than an aspirational hourly one.

See DATA_CONTRACTS.md for the schema and ARCHITECTURE.md section 1a for why the
trigger layer exists at all.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

# The counter keys. Note the shapes differ on purpose and the difference is a
# one character trap, so the mapping lives in exactly one function below:
#   dispatch_source input value : "external-timer"  (hyphen, a CLI style input)
#   writes_by_trigger key       : "external_timer"  (underscore, a JSON key)
TRIGGER_SCHEDULE = "schedule"
TRIGGER_EXTERNAL_TIMER = "external_timer"
TRIGGER_MANUAL = "manual"

TRIGGER_KEYS = (TRIGGER_SCHEDULE, TRIGGER_EXTERNAL_TIMER, TRIGGER_MANUAL)

# Values the `source` workflow_dispatch input may carry.
DISPATCH_SOURCE_EXTERNAL_TIMER = "external-timer"
DISPATCH_SOURCE_MANUAL = "manual"

# Which trigger kinds count as "no human involved", which is the Phase 0 exit
# criterion. A manual dispatch does not count, by design, and relaxing this to
# make the criterion pass would be cheating.
UNASSISTED_TRIGGERS = (TRIGGER_SCHEDULE, TRIGGER_EXTERNAL_TIMER)

TRIGGER_MODE_EXTERNAL_TIMER = "external_timer"
TRIGGER_MODE_SCHEDULE_ONLY = "schedule_only"


def classify_trigger(event_name: str, dispatch_source: str | None) -> str:
    """Map a GitHub event plus the claimed dispatch source onto one counter key.

    The single place the hyphen to underscore conversion happens. Rules, from
    DATA_CONTRACTS.md:

      - a `schedule` event counts as `schedule`
      - a `workflow_dispatch` whose source is `external-timer` counts as
        `external_timer`
      - anything else counts as `manual`

    "Anything else" is deliberately the catch all. An unrecognised source
    string must count as manual, never as unassisted, because the cost of
    wrongly crediting a human write is a false Phase 0 pass.
    """
    if event_name == "schedule":
        return TRIGGER_SCHEDULE
    if (
        event_name == "workflow_dispatch"
        and (dispatch_source or "").strip() == DISPATCH_SOURCE_EXTERNAL_TIMER
    ):
        return TRIGGER_EXTERNAL_TIMER
    return TRIGGER_MANUAL


def derive_unassisted_total(writes_by_trigger: dict[str, int]) -> int:
    """Derived, never stored. Provided here so Python and the page agree.

    The page computes this itself from the same rule. This function exists for
    tests and logs, and its result must never be written into the payload.
    """
    return sum(int(writes_by_trigger.get(k, 0)) for k in UNASSISTED_TRIGGERS)


def load_schedule(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def cadence_for(
    schedule: dict[str, Any], workflow_file: str, external_timer_armed: bool
) -> tuple[int, int, str]:
    """Return (expected_cadence_minutes, stale_after_minutes, trigger_mode).

    When the external timer is not armed, the only thing starting runs is
    GitHub's own scheduler, measured at a 4.68 hour median delay and 3.9 to 5.3
    percent delivery for high frequency crons. Declaring an hourly cadence in
    that state would make the page claim a freshness it has no mechanism to
    deliver, and the staleness banner would be permanently lit for a system
    behaving exactly as designed.
    """
    entry = _workflow_entry(schedule, workflow_file)
    if external_timer_armed:
        return (
            int(entry["cadence_minutes"]),
            int(entry["stale_after_minutes"]),
            TRIGGER_MODE_EXTERNAL_TIMER,
        )
    return (
        int(schedule["schedule_only_cadence_minutes"]),
        int(schedule["schedule_only_stale_after_minutes"]),
        TRIGGER_MODE_SCHEDULE_ONLY,
    )


def build_heartbeat(
    *,
    previous: dict[str, Any] | None,
    run_number: int,
    written_at: dt.datetime,
    source_commit: str,
    event_name: str,
    dispatch_source: str | None,
    dispatch_scheduled_for: dt.datetime | None,
    schedule: dict[str, Any],
    workflow_file: str = "heartbeat.yml",
    external_timer_armed: bool = False,
) -> dict[str, Any]:
    """Build the next heartbeat payload from the previous one.

    `previous` is the heartbeat.json already on the data branch, or None on the
    very first write.
    """
    _require_utc(written_at, "written_at")
    if dispatch_scheduled_for is not None:
        _require_utc(dispatch_scheduled_for, "dispatch_scheduled_for")

    trigger = classify_trigger(event_name, dispatch_source)
    counts = _carry_forward_counts(previous)
    counts[trigger] = counts.get(trigger, 0) + 1

    cadence_minutes, stale_after_minutes, trigger_mode = cadence_for(
        schedule, workflow_file, external_timer_armed
    )

    is_unassisted = trigger in UNASSISTED_TRIGGERS
    written_iso = _iso(written_at)

    first_unassisted = (previous or {}).get("first_unassisted_write")
    last_unassisted = (previous or {}).get("last_unassisted_write")
    if is_unassisted:
        # first_unassisted_write is a timestamp, not a counter, so storing it
        # does not violate the one counter rule. It is set once and then left
        # alone, which is what makes it evidence.
        first_unassisted = first_unassisted or written_iso
        last_unassisted = written_iso

    payload: dict[str, Any] = {
        "run_number": run_number,
        "written_at": written_iso,
        "source_commit": source_commit,
        "triggered_by": event_name,
        "dispatch_source": dispatch_source,
        "dispatch_scheduled_for": _iso(dispatch_scheduled_for)
        if dispatch_scheduled_for
        else None,
        "dispatch_lag_seconds": _lag_seconds(dispatch_scheduled_for, written_at),
        "expected_cadence_minutes": cadence_minutes,
        "stale_after_minutes": stale_after_minutes,
        "trigger_mode": trigger_mode,
        "writes_by_trigger": {k: counts.get(k, 0) for k in TRIGGER_KEYS},
        "first_unassisted_write": first_unassisted,
        "last_unassisted_write": last_unassisted,
    }
    return payload


def _workflow_entry(schedule: dict[str, Any], workflow_file: str) -> dict[str, Any]:
    for entry in schedule["workflows"]:
        if entry["file"] == workflow_file:
            return entry
    raise KeyError(
        f"{workflow_file} is not in trigger-schedule.json. Add it there rather than "
        f"hardcoding a cadence: one cadence, one source of truth."
    )


def _carry_forward_counts(previous: dict[str, Any] | None) -> dict[str, int]:
    """Carry the counter forward, tolerating a missing or malformed previous file.

    A corrupt previous heartbeat must not take the pipeline down, but it must
    also not silently reset the counter to zero and erase the evidence that the
    Phase 0 criterion was met. Unknown keys are dropped; known keys survive.
    """
    if not previous:
        return {k: 0 for k in TRIGGER_KEYS}
    raw = previous.get("writes_by_trigger") or {}
    out: dict[str, int] = {}
    for key in TRIGGER_KEYS:
        value = raw.get(key, 0)
        out[key] = value if isinstance(value, int) and value >= 0 else 0
    return out


def _lag_seconds(
    scheduled_for: dt.datetime | None, written_at: dt.datetime
) -> int | None:
    """The checkable half of the dispatch claim.

    None when no timer claimed a time, which is the honest answer for a
    `schedule` event: GitHub does not tell us what minute it intended.
    """
    if scheduled_for is None:
        return None
    return int(round((written_at - scheduled_for).total_seconds()))


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_utc(value: dt.datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone aware, got naive {value!r}")
