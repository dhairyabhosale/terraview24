"""Alignment between trigger-schedule.json, the workflow files and the Worker.

ARCHITECTURE.md section 1a requires an alignment test: every cadence the Worker
can fire must have a matching workflow_dispatch workflow. Without it, the
Worker can POST to a workflow file that does not accept dispatches, GitHub
answers 404, and the symptom is "the pipeline stopped" with no obvious cause.

A note on the parser used here. PyYAML is NOT a validator, and this project
learned that the hard way: a file it accepted was rejected by GitHub Actions on
every push. actionlint is the validator and runs separately, in
lint-workflows.yml and locally via scripts/get-actionlint.sh. This test uses a
parser only to assert structure that actionlint has no opinion about, such as
whether a cron string matches the one source of truth.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
SCHEDULE_PATH = REPO_ROOT / "trigger-schedule.json"

# Workflows that are not part of the pipeline and are never dispatched by the
# timer. Listed explicitly so a new pipeline workflow cannot be quietly
# exempted from the checks below by forgetting to register it.
NON_PIPELINE_WORKFLOWS = {"lint-workflows.yml"}

PINNED_RUNNER = "ubuntu-24.04"
PINNED_CHECKOUT = "actions/checkout@v5"


@pytest.fixture(scope="module")
def schedule() -> dict:
    return json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))


def load_workflow(path: Path) -> dict:
    """Parse a workflow, working around YAML 1.1 boolean keys.

    PyYAML resolves the bare key `on` to the boolean True, per YAML 1.1. So the
    trigger block is at key True, not "on". This is a parser quirk, not a
    problem with the file, and anyone reading this test needs to know it before
    they conclude the workflow is malformed.
    """
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if True in doc and "on" not in doc:
        doc["on"] = doc.pop(True)
    return doc


def pipeline_workflow_files() -> list[Path]:
    return sorted(
        p for p in WORKFLOW_DIR.glob("*.yml") if p.name not in NON_PIPELINE_WORKFLOWS
    )


# ---------------------------------------------------------------------------
# The alignment section 1a asks for
# ---------------------------------------------------------------------------


def test_every_scheduled_workflow_file_exists(schedule):
    for entry in schedule["workflows"]:
        path = WORKFLOW_DIR / entry["file"]
        assert path.is_file(), (
            f"trigger-schedule.json lists {entry['file']} but no such workflow exists. "
            f"The Worker would POST to it and get a 404."
        )


def test_every_pipeline_workflow_is_in_the_schedule(schedule):
    """The other direction: a workflow the timer does not know about.

    Such a workflow relies entirely on GitHub's own scheduler, measured at a
    4.68 hour median delay, which is almost certainly not what was intended.
    """
    listed = {entry["file"] for entry in schedule["workflows"]}
    for path in pipeline_workflow_files():
        assert path.name in listed, (
            f"{path.name} is not in trigger-schedule.json, so the external timer will "
            f"never fire it and it will run at GitHub's cadence of roughly once every "
            f"4 to 5 hours. Add it, or add it to NON_PIPELINE_WORKFLOWS."
        )


def test_every_scheduled_workflow_accepts_workflow_dispatch(schedule):
    for entry in schedule["workflows"]:
        doc = load_workflow(WORKFLOW_DIR / entry["file"])
        assert "workflow_dispatch" in doc["on"], (
            f"{entry['file']} has no workflow_dispatch trigger, so the Worker cannot "
            f"start it. This is the fast path; without it only the slow fallback works."
        )


def test_every_scheduled_workflow_declares_the_source_and_scheduled_for_inputs(schedule):
    """Both inputs, because one is the claim and the other makes it checkable."""
    for entry in schedule["workflows"]:
        doc = load_workflow(WORKFLOW_DIR / entry["file"])
        inputs = (doc["on"]["workflow_dispatch"] or {}).get("inputs") or {}
        assert "source" in inputs, f"{entry['file']} is missing the `source` input"
        assert "scheduled_for" in inputs, (
            f"{entry['file']} is missing the `scheduled_for` input, so "
            f"dispatch_lag_seconds cannot be computed and dispatch_source would be an "
            f"unfalsifiable claim"
        )


def test_source_input_defaults_to_manual(schedule):
    """Defaulting to external-timer would credit a hand run dispatch as unassisted
    and could produce a false Phase 0 pass."""
    for entry in schedule["workflows"]:
        doc = load_workflow(WORKFLOW_DIR / entry["file"])
        inputs = (doc["on"]["workflow_dispatch"] or {}).get("inputs") or {}
        assert inputs["source"].get("default") == "manual", entry["file"]


def test_schedule_fallback_is_retained_everywhere(schedule):
    """A late run beats no run, so `schedule` stays in every workflow."""
    for entry in schedule["workflows"]:
        doc = load_workflow(WORKFLOW_DIR / entry["file"])
        assert "schedule" in doc["on"], (
            f"{entry['file']} dropped its schedule fallback. If the Worker or its token "
            f"dies, nothing starts this workflow at all."
        )


def test_cron_expressions_match_the_single_source_of_truth(schedule):
    for entry in schedule["workflows"]:
        doc = load_workflow(WORKFLOW_DIR / entry["file"])
        crons = [item["cron"] for item in doc["on"]["schedule"]]
        assert crons == [entry["cron"]], (
            f"{entry['file']} cron {crons} does not match trigger-schedule.json "
            f"{entry['cron']!r}. Two copies of a cadence is how they drift."
        )


# ---------------------------------------------------------------------------
# The section 9a concurrency design
# ---------------------------------------------------------------------------


def test_no_workflow_uses_a_shared_concurrency_group():
    """The trap this project nearly shipped.

    A single shared group holds one pending run, so a third dispatch cancels
    the queued one and the loss looks like scheduler flakiness. Each workflow
    must dedupe only against itself.
    """
    groups: dict[str, str] = {}
    for path in pipeline_workflow_files():
        doc = load_workflow(path)
        group = doc["concurrency"]["group"]
        assert group != "data-branch-write", (
            f"{path.name} uses the superseded shared group. See ARCHITECTURE.md "
            f"section 9a."
        )
        assert group not in groups, (
            f"{path.name} shares concurrency group {group!r} with {groups[group]}. "
            f"Under a 5 minute timer that silently drops dispatches."
        )
        groups[group] = path.name


def test_writing_workflows_never_cancel_in_progress():
    """Cancelling a half finished write to the data branch is how a registry
    gets truncated."""
    for path in pipeline_workflow_files():
        doc = load_workflow(path)
        assert doc["concurrency"]["cancel-in-progress"] is False, path.name


def test_each_family_is_written_by_exactly_one_workflow(schedule):
    """The precondition that makes the rebase and retry push safe without a lock."""
    owners: dict[str, str] = {}
    for entry in schedule["workflows"]:
        family = entry["writes_family"]
        if family is None:
            continue
        assert family not in owners, (
            f"{entry['file']} and {owners[family]} both write family {family!r}. "
            f"Two workflows writing one file turns every overlapping run into a "
            f"rebase conflict."
        )
        owners[family] = entry["file"]


# ---------------------------------------------------------------------------
# Pins, from the measured platform behaviours in section 9
# ---------------------------------------------------------------------------


def test_every_workflow_pins_the_runner_image():
    """ubuntu-latest began migrating to Ubuntu 26 on 2026-10-19. A scoring
    pipeline whose OS image moves underneath it is not reproducible."""
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        doc = load_workflow(path)
        for job_name, job in doc["jobs"].items():
            assert job["runs-on"] == PINNED_RUNNER, (
                f"{path.name} job {job_name} runs on {job['runs-on']!r}, expected "
                f"{PINNED_RUNNER!r}"
            )


def test_every_checkout_is_v5():
    """v4 targets the deprecated Node 20 and annotates every run."""
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        assert "actions/checkout@v4" not in text, f"{path.name} still uses checkout@v4"
        if "actions/checkout" in text:
            assert PINNED_CHECKOUT in text, path.name


def test_every_workflow_sets_an_explicit_timeout():
    """A job with no timeout inherits 6 hours, which is long enough for a hung
    source request to look like a dead pipeline."""
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        doc = load_workflow(path)
        for job_name, job in doc["jobs"].items():
            assert "timeout-minutes" in job, f"{path.name} job {job_name}"


def test_no_yaml_key_has_a_null_value():
    """The attempt 1 failure, asserted directly.

    `env:` followed only by a comment parses as `env: null`. PyYAML accepts it;
    GitHub Actions rejects the whole file with only "workflow file issue".
    actionlint catches this too, and this assertion is the cheap second net.
    """
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        doc = load_workflow(path)
        _assert_no_null(doc, path.name, [])


def _assert_no_null(node: object, filename: str, trail: list[str]) -> None:
    if node is None:
        where = " -> ".join(trail) or "(root)"
        raise AssertionError(
            f"{filename} has a null value at {where}. A YAML key with only a comment "
            f"under it parses as null and GitHub Actions rejects the file."
        )
    if isinstance(node, dict):
        for key, value in node.items():
            # workflow_dispatch with no inputs is legitimately null-ish, and an
            # empty string default is a real value, so only recurse on mappings
            # and sequences we expect to be populated.
            if key in ("workflow_dispatch", "inputs") and value is None:
                continue
            _assert_no_null(value, filename, [*trail, str(key)])
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _assert_no_null(value, filename, [*trail, f"[{index}]"])


# ---------------------------------------------------------------------------
# Gating, and a guard that fails where it should
# ---------------------------------------------------------------------------


def test_unarmed_workflows_are_gated_on_two_variables(schedule):
    """PIPELINE_ENABLED plus one variable per family, so families arm one at a time."""
    for entry in schedule["workflows"]:
        if entry["armed"]:
            continue
        doc = load_workflow(WORKFLOW_DIR / entry["file"])
        conditions = [job.get("if", "") for job in doc["jobs"].values()]
        joined = " ".join(conditions)
        assert "PIPELINE_ENABLED" in joined, entry["file"]
        assert entry["gate_variable"] in joined, entry["file"]


def test_heartbeat_is_not_gated(schedule):
    """If the heartbeat can be switched off, the page cannot tell a stopped
    pipeline from a stopped heartbeat, and staleness stops meaning anything."""
    entry = next(e for e in schedule["workflows"] if e["file"] == "heartbeat.yml")
    assert entry["armed"] is True
    assert entry["gate_variable"] is None
    doc = load_workflow(WORKFLOW_DIR / "heartbeat.yml")
    for job_name, job in doc["jobs"].items():
        assert "if" not in job, f"heartbeat job {job_name} is gated and must not be"


def test_the_alignment_check_is_not_vacuous(tmp_path):
    """Deliberate negative control.

    A test that walks a list can pass by walking an empty list. This asserts the
    detector actually fires on a bad workflow, so the suite cannot pass because
    the glob silently matched nothing.
    """
    bad = tmp_path / "bad.yml"
    bad.write_text(
        "name: bad\n"
        "on:\n"
        "  schedule:\n"
        "    - cron: '0 * * * *'\n"
        "jobs:\n"
        "  go:\n"
        "    runs-on: ubuntu-latest\n"
        "    env:\n"
        "      # a comment and nothing else, so this key is null\n"
        "    steps:\n"
        "      - run: echo hi\n",
        encoding="utf-8",
    )
    doc = load_workflow(bad)

    assert doc["jobs"]["go"]["runs-on"] != PINNED_RUNNER
    with pytest.raises(AssertionError, match="null value"):
        _assert_no_null(doc, "bad.yml", [])


def test_workflow_files_are_discovered_at_all():
    """Guards the glob itself. Without this, every loop above could be empty."""
    assert len(pipeline_workflow_files()) >= 6
    assert (WORKFLOW_DIR / "heartbeat.yml").is_file()
