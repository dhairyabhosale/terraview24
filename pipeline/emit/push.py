"""Writing to the data branch: fetch, rebase, retry, with jitter.

This is the concurrency control for the whole pipeline, and it lives at the git
layer on purpose. The obvious alternative, one GitHub Actions concurrency group
shared by every writing workflow, is actively harmful: a concurrency group holds
at most ONE pending run, so a third arrival cancels the queued one. Under a 5
minute external timer that silently drops dispatches, and a dropped dispatch is
indistinguishable from the GitHub scheduler flakiness that cost hours to
diagnose on attempt 1. See ARCHITECTURE.md section 9a.

So: each workflow has its own concurrency group, each family owns its own files,
and genuine simultaneous writes are resolved here by rebasing and retrying.

The rebase is safe precisely because of the file ownership rule. Two workflows
never touch the same path, so a rebase of one family's commit onto another
family's commit has nothing to conflict over. If a conflict does occur, that is
a violation of the ownership rule and this module raises rather than resolving
it: silently picking a side would corrupt a registry.
"""

from __future__ import annotations

import random
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.detect.constants import (
    PUSH_BACKOFF_BASE_SECONDS,
    PUSH_JITTER_SECONDS,
    PUSH_MAX_ATTEMPTS,
)

DATA_BRANCH = "data"


class PushConflictError(RuntimeError):
    """A rebase hit a real content conflict.

    This means two workflows wrote the same file, which the per family file
    ownership rule forbids. Fix the ownership, do not add a merge strategy.
    """


class PushExhaustedError(RuntimeError):
    """Every attempt was rejected. The caller decides whether that fails the run."""


@dataclass
class PushAttemptLog:
    """What happened, so "dispatched but never wrote" is diagnosable later."""

    attempts: int = 0
    rebases: int = 0
    rejections: int = 0
    waits_seconds: list[float] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"attempts={self.attempts} rebases={self.rebases} "
            f"rejections={self.rejections} total_wait={sum(self.waits_seconds):.1f}s"
        )


def run_git(
    repo: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run one git command in `repo`, capturing output."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {repo} with exit {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


def has_staged_changes(repo: Path) -> bool:
    """True when there is something to commit.

    An unconditional commit would produce an empty commit on every run, which
    inflates the data branch (a size constraint, see ARCHITECTURE.md section 8)
    and makes the history useless for working out when a value actually moved.
    """
    result = run_git(repo, "diff", "--cached", "--quiet", check=False)
    return result.returncode != 0


def commit_and_push(
    repo: Path,
    *,
    paths: list[str],
    message: str,
    branch: str = DATA_BRANCH,
    max_attempts: int = PUSH_MAX_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[float], float] = random.uniform,
) -> PushAttemptLog:
    """Stage `paths`, commit, then push with rebase and retry.

    Returns the attempt log on success. Raises PushExhaustedError if every
    attempt is rejected, or PushConflictError if a rebase conflicts.
    """
    log = PushAttemptLog()

    run_git(repo, "add", "--", *paths)
    if not has_staged_changes(repo):
        return log

    run_git(repo, "commit", "-m", message)

    for attempt in range(1, max_attempts + 1):
        log.attempts = attempt

        push = run_git(repo, "push", "origin", f"HEAD:{branch}", check=False)
        if push.returncode == 0:
            return log

        log.rejections += 1
        if attempt == max_attempts:
            raise PushExhaustedError(
                f"push to {branch} rejected {log.rejections} times. {log.summary()}\n"
                f"last stderr: {push.stderr}"
            )

        # Someone else wrote first. Rebase our commit onto their work and retry.
        run_git(repo, "fetch", "origin", branch)
        rebase = run_git(repo, "rebase", f"origin/{branch}", check=False)
        log.rebases += 1

        if rebase.returncode != 0:
            run_git(repo, "rebase", "--abort", check=False)
            raise PushConflictError(
                f"rebase onto origin/{branch} conflicted, which means two workflows "
                f"wrote the same file. Per family file ownership is violated; see "
                f"ARCHITECTURE.md section 9a. Do not add a merge strategy here.\n"
                f"stderr: {rebase.stderr}"
            )

        wait = PUSH_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)) + jitter(
            0, PUSH_JITTER_SECONDS
        )
        log.waits_seconds.append(wait)
        sleep(wait)

    raise PushExhaustedError(f"unreachable retry exit. {log.summary()}")
