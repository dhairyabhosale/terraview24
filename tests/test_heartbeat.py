"""Tests for heartbeat.json, the Phase 0 exit evidence.

The Phase 0 criterion is that a number changes on a deployed page because a job
wrote it with no human involved. These tests guard the two ways that could go
wrong: crediting a human write as unassisted (a false pass) and losing the
counter history (a false fail, which is what happened on attempt 1).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from pipeline.emit.heartbeat import (
    TRIGGER_EXTERNAL_TIMER,
    TRIGGER_KEYS,
    TRIGGER_MANUAL,
    TRIGGER_MODE_EXTERNAL_TIMER,
    TRIGGER_MODE_SCHEDULE_ONLY,
    TRIGGER_SCHEDULE,
    build_heartbeat,
    cadence_for,
    classify_trigger,
    derive_unassisted_total,
    load_schedule,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEDULE_PATH = REPO_ROOT / "trigger-schedule.json"

NOW = dt.datetime(2026, 11, 6, 9, 0, 11, tzinfo=dt.timezone.utc)
SCHEDULED = dt.datetime(2026, 11, 6, 9, 0, 0, tzinfo=dt.timezone.utc)


@pytest.fixture
def schedule() -> dict:
    return load_schedule(SCHEDULE_PATH)


# ---------------------------------------------------------------------------
# Trigger classification: the hyphen to underscore trap
# ---------------------------------------------------------------------------


def test_schedule_event_counts_as_schedule():
    assert classify_trigger("schedule", None) == TRIGGER_SCHEDULE


def test_external_timer_dispatch_counts_as_external_timer():
    """The input value is hyphenated, the counter key is not."""
    assert classify_trigger("workflow_dispatch", "external-timer") == TRIGGER_EXTERNAL_TIMER


def test_default_dispatch_counts_as_manual():
    assert classify_trigger("workflow_dispatch", "manual") == TRIGGER_MANUAL
    assert classify_trigger("workflow_dispatch", None) == TRIGGER_MANUAL
    assert classify_trigger("workflow_dispatch", "") == TRIGGER_MANUAL


def test_the_underscore_spelling_of_the_input_does_not_count_as_unassisted():
    """The trap, asserted directly.

    If someone passes the counter key as the input value, that must NOT be
    credited as an external timer write. Failing closed here is the difference
    between a real Phase 0 pass and a typo that looks like one.
    """
    assert classify_trigger("workflow_dispatch", "external_timer") == TRIGGER_MANUAL


def test_an_unrecognised_source_counts_as_manual():
    for source in ("External-Timer", " robot ", "cron", "worker", "true"):
        assert classify_trigger("workflow_dispatch", source) == TRIGGER_MANUAL


def test_surrounding_whitespace_on_the_real_value_is_tolerated():
    """Workflow inputs pick up stray whitespace. The intent is unambiguous."""
    assert classify_trigger("workflow_dispatch", " external-timer ") == TRIGGER_EXTERNAL_TIMER


def test_an_unknown_event_name_counts_as_manual():
    assert classify_trigger("push", None) == TRIGGER_MANUAL
    assert classify_trigger("repository_dispatch", "external-timer") == TRIGGER_MANUAL


# ---------------------------------------------------------------------------
# The derived count, which is never stored
# ---------------------------------------------------------------------------


def test_unassisted_total_is_schedule_plus_external_timer():
    counts = {"schedule": 1, "external_timer": 6, "manual": 4}
    assert derive_unassisted_total(counts) == 7


def test_manual_writes_alone_derive_zero_unassisted():
    """A manual dispatch does not satisfy the exit criterion."""
    assert derive_unassisted_total({"manual": 12}) == 0


def test_the_derived_total_is_not_written_into_the_payload(schedule):
    """One authoritative counter. Attempt 1 shipped two and they disagreed."""
    payload = build_heartbeat(
        previous=None,
        run_number=1,
        written_at=NOW,
        source_commit="abc123",
        event_name="schedule",
        dispatch_source=None,
        dispatch_scheduled_for=None,
        schedule=schedule,
    )
    serialised = json.dumps(payload)
    assert "unassisted_writes_total" not in serialised
    assert "schedule_writes_total" not in serialised
    assert payload["writes_by_trigger"] == {"schedule": 1, "external_timer": 0, "manual": 0}


# ---------------------------------------------------------------------------
# Counter accumulation
# ---------------------------------------------------------------------------


def test_counter_carries_forward_across_writes(schedule):
    previous = {
        "writes_by_trigger": {"schedule": 1, "external_timer": 6, "manual": 4},
        "first_unassisted_write": "2026-11-05T23:34:22Z",
        "last_unassisted_write": "2026-11-06T08:00:11Z",
    }
    payload = build_heartbeat(
        previous=previous,
        run_number=12,
        written_at=NOW,
        source_commit="deadbee",
        event_name="workflow_dispatch",
        dispatch_source="external-timer",
        dispatch_scheduled_for=SCHEDULED,
        schedule=schedule,
        external_timer_armed=True,
    )
    assert payload["writes_by_trigger"] == {
        "schedule": 1,
        "external_timer": 7,
        "manual": 4,
    }
    assert payload["first_unassisted_write"] == "2026-11-05T23:34:22Z"
    assert payload["last_unassisted_write"] == "2026-11-06T09:00:11Z"


def test_first_unassisted_write_is_set_once_and_never_moves(schedule):
    first = build_heartbeat(
        previous=None,
        run_number=1,
        written_at=NOW,
        source_commit="a",
        event_name="schedule",
        dispatch_source=None,
        dispatch_scheduled_for=None,
        schedule=schedule,
    )
    later = build_heartbeat(
        previous=first,
        run_number=2,
        written_at=NOW + dt.timedelta(hours=5),
        source_commit="b",
        event_name="schedule",
        dispatch_source=None,
        dispatch_scheduled_for=None,
        schedule=schedule,
    )
    assert later["first_unassisted_write"] == first["first_unassisted_write"]
    assert later["last_unassisted_write"] != later["first_unassisted_write"]


def test_a_manual_write_does_not_set_the_unassisted_timestamps(schedule):
    payload = build_heartbeat(
        previous=None,
        run_number=1,
        written_at=NOW,
        source_commit="a",
        event_name="workflow_dispatch",
        dispatch_source="manual",
        dispatch_scheduled_for=None,
        schedule=schedule,
    )
    assert payload["first_unassisted_write"] is None
    assert payload["last_unassisted_write"] is None
    assert derive_unassisted_total(payload["writes_by_trigger"]) == 0


def test_a_corrupt_previous_counter_does_not_erase_known_history(schedule):
    """A malformed file must not silently reset the Phase 0 evidence to zero."""
    previous = {
        "writes_by_trigger": {
            "schedule": 3,
            "external_timer": "lots",
            "manual": -1,
            "bogus": 9,
        }
    }
    payload = build_heartbeat(
        previous=previous,
        run_number=9,
        written_at=NOW,
        source_commit="a",
        event_name="schedule",
        dispatch_source=None,
        dispatch_scheduled_for=None,
        schedule=schedule,
    )
    assert payload["writes_by_trigger"]["schedule"] == 4
    assert payload["writes_by_trigger"]["external_timer"] == 0
    assert payload["writes_by_trigger"]["manual"] == 0
    assert set(payload["writes_by_trigger"]) == set(TRIGGER_KEYS)


# ---------------------------------------------------------------------------
# Dispatch lag, the checkable half of the claim
# ---------------------------------------------------------------------------


def test_dispatch_lag_is_measured_from_the_claimed_time_to_the_write(schedule):
    payload = build_heartbeat(
        previous=None,
        run_number=1,
        written_at=NOW,
        source_commit="a",
        event_name="workflow_dispatch",
        dispatch_source="external-timer",
        dispatch_scheduled_for=SCHEDULED,
        schedule=schedule,
        external_timer_armed=True,
    )
    assert payload["dispatch_lag_seconds"] == 11


def test_a_schedule_event_has_no_dispatch_lag(schedule):
    """GitHub does not tell us which minute it intended, so claiming a lag would
    be inventing a number."""
    payload = build_heartbeat(
        previous=None,
        run_number=1,
        written_at=NOW,
        source_commit="a",
        event_name="schedule",
        dispatch_source=None,
        dispatch_scheduled_for=None,
        schedule=schedule,
    )
    assert payload["dispatch_lag_seconds"] is None
    assert payload["dispatch_scheduled_for"] is None


# ---------------------------------------------------------------------------
# Cadence: one source of truth, stating whichever trigger is armed
# ---------------------------------------------------------------------------


def test_schedule_only_mode_declares_the_measured_github_cadence(schedule):
    cadence, stale, mode = cadence_for(schedule, "heartbeat.yml", external_timer_armed=False)
    assert mode == TRIGGER_MODE_SCHEDULE_ONLY
    assert cadence == 300, "GitHub's measured cadence is 4 to 5 hours, not hourly"
    assert stale > cadence


def test_external_timer_mode_declares_the_workflow_cadence(schedule):
    cadence, stale, mode = cadence_for(schedule, "heartbeat.yml", external_timer_armed=True)
    assert mode == TRIGGER_MODE_EXTERNAL_TIMER
    assert cadence == 60
    assert stale == 150


def test_stale_after_exceeds_cadence_for_every_workflow(schedule):
    """A staleness threshold at or below the cadence lights the banner permanently."""
    for entry in schedule["workflows"]:
        assert entry["stale_after_minutes"] > entry["cadence_minutes"], entry["file"]


def test_an_unknown_workflow_raises_rather_than_guessing_a_cadence(schedule):
    with pytest.raises(KeyError, match="one source of truth"):
        cadence_for(schedule, "not-a-workflow.yml", external_timer_armed=True)


def test_naive_timestamps_are_rejected(schedule):
    with pytest.raises(ValueError, match="timezone aware"):
        build_heartbeat(
            previous=None,
            run_number=1,
            written_at=dt.datetime(2026, 11, 6, 9, 0),
            source_commit="a",
            event_name="schedule",
            dispatch_source=None,
            dispatch_scheduled_for=None,
            schedule=schedule,
        )


def test_written_at_is_utc_with_a_trailing_z(schedule):
    """The page parses this. A missing timezone marker reads as local time in JS."""
    payload = build_heartbeat(
        previous=None,
        run_number=1,
        written_at=NOW.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))),
        source_commit="a",
        event_name="schedule",
        dispatch_source=None,
        dispatch_scheduled_for=None,
        schedule=schedule,
    )
    assert payload["written_at"] == "2026-11-06T09:00:11Z"


# ---------------------------------------------------------------------------
# Contract shape
# ---------------------------------------------------------------------------


def test_payload_carries_every_field_the_contract_names(schedule):
    payload = build_heartbeat(
        previous=None,
        run_number=1,
        written_at=NOW,
        source_commit="a",
        event_name="schedule",
        dispatch_source=None,
        dispatch_scheduled_for=None,
        schedule=schedule,
    )
    required = {
        "run_number",
        "written_at",
        "source_commit",
        "triggered_by",
        "dispatch_source",
        "dispatch_scheduled_for",
        "dispatch_lag_seconds",
        "expected_cadence_minutes",
        "stale_after_minutes",
        "writes_by_trigger",
        "first_unassisted_write",
        "last_unassisted_write",
    }
    assert required <= set(payload), required - set(payload)
