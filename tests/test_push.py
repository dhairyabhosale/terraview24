"""Tests for the data branch push, using real local git repositories.

These drive actual git, not a mock, because the behaviour under test is git's:
a rejected non fast forward push, a clean rebase when two workflows touched
different files, and a conflict when they touched the same one. A mocked git
would only prove that the mock matches my assumptions about git.

No network: `origin` is a bare repo on disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.emit.push import (
    PushConflictError,
    commit_and_push,
    has_staged_changes,
    run_git,
)


def noop_sleep(_seconds: float) -> None:
    """Swallow backoff so the suite stays fast."""


def no_jitter(_a: float, _b: float) -> float:
    return 0.0


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    """A bare repo standing in for the GitHub remote, with a `data` branch."""
    bare = tmp_path / "origin.git"
    bare.mkdir()
    run_git(bare, "init", "--bare", "--initial-branch=data")

    seed = tmp_path / "seed"
    seed.mkdir()
    _init_repo(seed)
    (seed / "heartbeat.json").write_text('{"run_number": 0}\n', encoding="utf-8")
    run_git(seed, "add", "heartbeat.json")
    run_git(seed, "commit", "-m", "seed")
    run_git(seed, "branch", "-M", "data")
    run_git(seed, "remote", "add", "origin", str(bare))
    run_git(seed, "push", "origin", "data")
    return bare


def clone(origin: Path, path: Path) -> Path:
    run_git(path.parent, "clone", "--branch", "data", str(origin), str(path))
    _configure_identity(path)
    return path


def _init_repo(path: Path) -> None:
    run_git(path, "init")
    _configure_identity(path)


def _configure_identity(path: Path) -> None:
    run_git(path, "config", "user.email", "pipeline@terraview24.invalid")
    run_git(path, "config", "user.name", "terraview24 pipeline")
    # Deterministic: never let a developer's global rebase settings change the
    # behaviour under test.
    run_git(path, "config", "rebase.autoStash", "false")
    run_git(path, "config", "pull.rebase", "true")


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


def test_a_clean_push_succeeds_on_the_first_attempt(origin, tmp_path):
    repo = clone(origin, tmp_path / "runner")
    (repo / "heartbeat.json").write_text('{"run_number": 1}\n', encoding="utf-8")

    log = commit_and_push(
        repo,
        paths=["heartbeat.json"],
        message="heartbeat: run 1",
        sleep=noop_sleep,
        jitter=no_jitter,
    )

    assert log.attempts == 1
    assert log.rejections == 0
    assert log.rebases == 0

    verify = clone(origin, tmp_path / "verify")
    assert '"run_number": 1' in (verify / "heartbeat.json").read_text(encoding="utf-8")


def test_no_changes_means_no_commit_and_no_empty_push(origin, tmp_path):
    """An unconditional commit would add an empty commit on every run, inflating
    a branch whose size is a real constraint and destroying the ability to see
    when a value actually moved."""
    repo = clone(origin, tmp_path / "runner")
    before = run_git(repo, "rev-parse", "HEAD").stdout.strip()

    log = commit_and_push(
        repo,
        paths=["heartbeat.json"],
        message="heartbeat: no change",
        sleep=noop_sleep,
        jitter=no_jitter,
    )

    assert log.attempts == 0
    assert run_git(repo, "rev-parse", "HEAD").stdout.strip() == before


def test_has_staged_changes_detects_a_real_edit(origin, tmp_path):
    repo = clone(origin, tmp_path / "runner")
    run_git(repo, "add", "--", "heartbeat.json")
    assert has_staged_changes(repo) is False

    (repo / "heartbeat.json").write_text('{"run_number": 9}\n', encoding="utf-8")
    run_git(repo, "add", "--", "heartbeat.json")
    assert has_staged_changes(repo) is True


# ---------------------------------------------------------------------------
# Concurrent writes from two workflows, which is the case 9a is about
# ---------------------------------------------------------------------------


def test_two_workflows_writing_different_files_both_land(origin, tmp_path):
    """The core claim of the 9a design.

    Thermal and marine both write in the same window. Per family file ownership
    means the rebase has nothing to conflict over, so both commits survive and
    neither workflow needs a lock.
    """
    thermal = clone(origin, tmp_path / "thermal")
    marine = clone(origin, tmp_path / "marine")

    # Marine wins the race and pushes first.
    (marine / "meta.marine.json").write_text('{"family": "marine"}\n', encoding="utf-8")
    commit_and_push(
        marine,
        paths=["meta.marine.json"],
        message="marine: write",
        sleep=noop_sleep,
        jitter=no_jitter,
    )

    # Thermal is now behind, so its first push is rejected and it must rebase.
    (thermal / "meta.thermal.json").write_text(
        '{"family": "thermal"}\n', encoding="utf-8"
    )
    log = commit_and_push(
        thermal,
        paths=["meta.thermal.json"],
        message="thermal: write",
        sleep=noop_sleep,
        jitter=no_jitter,
    )

    assert log.rejections >= 1, "expected the stale push to be rejected"
    assert log.rebases >= 1, "expected a rebase onto the peer's commit"
    assert log.attempts >= 2

    verify = clone(origin, tmp_path / "verify")
    assert (verify / "meta.marine.json").exists(), "the peer's write was lost"
    assert (verify / "meta.thermal.json").exists(), "our write was lost"


def test_history_stays_linear_after_a_rebase(origin, tmp_path):
    """Rebase, not merge. A merge commit on data would also violate the linear
    history the main ruleset requires, so keeping the habit uniform is cheap."""
    a = clone(origin, tmp_path / "a")
    b = clone(origin, tmp_path / "b")

    (a / "meta.a.json").write_text("{}\n", encoding="utf-8")
    commit_and_push(a, paths=["meta.a.json"], message="a", sleep=noop_sleep, jitter=no_jitter)
    (b / "meta.b.json").write_text("{}\n", encoding="utf-8")
    commit_and_push(b, paths=["meta.b.json"], message="b", sleep=noop_sleep, jitter=no_jitter)

    verify = clone(origin, tmp_path / "verify")
    merges = run_git(verify, "log", "--merges", "--oneline").stdout.strip()
    assert merges == "", f"expected linear history, found merge commits:\n{merges}"


def test_two_workflows_writing_the_same_file_raises_rather_than_guessing(
    origin, tmp_path
):
    """Negative control, and a deliberate design boundary.

    A conflict here means the per family ownership rule was broken. Silently
    picking a side would corrupt a registry, so this must raise and say so.
    """
    a = clone(origin, tmp_path / "a")
    b = clone(origin, tmp_path / "b")

    (a / "shared.json").write_text('{"written_by": "a"}\n', encoding="utf-8")
    commit_and_push(
        a, paths=["shared.json"], message="a writes shared", sleep=noop_sleep, jitter=no_jitter
    )

    (b / "shared.json").write_text('{"written_by": "b"}\n', encoding="utf-8")
    with pytest.raises(PushConflictError, match="section 9a"):
        commit_and_push(
            b,
            paths=["shared.json"],
            message="b writes shared",
            sleep=noop_sleep,
            jitter=no_jitter,
        )


def test_a_conflict_leaves_no_rebase_in_progress(origin, tmp_path):
    """After the raise, the working tree must be usable.

    A half finished rebase on a runner is harmless, but on a developer machine
    it is a confusing mess, and the abort is one line.
    """
    a = clone(origin, tmp_path / "a")
    b = clone(origin, tmp_path / "b")

    (a / "shared.json").write_text('{"written_by": "a"}\n', encoding="utf-8")
    commit_and_push(a, paths=["shared.json"], message="a", sleep=noop_sleep, jitter=no_jitter)

    (b / "shared.json").write_text('{"written_by": "b"}\n', encoding="utf-8")
    with pytest.raises(PushConflictError):
        commit_and_push(b, paths=["shared.json"], message="b", sleep=noop_sleep, jitter=no_jitter)

    status = run_git(b, "status", "--porcelain=v2", "--branch").stdout
    assert "rebase" not in status.lower()
    assert not (b / ".git" / "rebase-merge").exists()
    assert not (b / ".git" / "rebase-apply").exists()
