"""GKG slice coverage accounting, including the read lag rule.

This module exists because UNREPORTED is an assertion about a negative result.
"No matching coverage was found by this query strategy in this index" is only
true if the index actually covered the window. A slice that was never read is
not a slice that contained nothing.

Measured 2026-11-06: GDELT publishes a GKG slice name into lastupdate.txt
roughly 45 to 60 minutes before the object becomes readable, while export and
mentions from the same manifest line are readable immediately. So a 404 is
ambiguous on its own, and the disambiguator is the slice's age.

See DETECTION_SPEC.md section 6 and DATA_SOURCES.md.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum

from pipeline.detect.constants import (
    COVERAGE_MIN,
    GKG_READ_LAG_MINUTES,
    GKG_SLICE_INTERVAL_MINUTES,
)

GKG_BASE_URL = "https://data.gdeltproject.org/gdeltv2"

# The manifest serves http:// URLs which 301 to https://host:443/..., and that
# redirect is fine but the scheme is not optional: request https directly or
# follow redirects. Do not request http and treat the 301 as a failure.


class SliceState(StrEnum):
    """What we know about one 15 minute GKG slice."""

    READ = "read"
    """Fetched successfully. Counts towards coverage."""

    PENDING = "pending"
    """404, but younger than the read lag horizon, so not yet published.

    Expected, NOT an error. Must not fail the run. Retried on a later run, and
    does not count as read. Any pending slice in a window makes that window not
    fully observed.
    """

    MISSING = "missing"
    """404, and older than the read lag horizon. A real gap.

    Counts against index_coverage_fraction.
    """

    FAILED = "failed"
    """Fetched but unusable: a non 404 error, a truncated body, a bad zip.

    Treated as a real gap, like MISSING. A transport error is not an excuse to
    claim coverage we do not have.
    """


@dataclass(frozen=True)
class SliceOutcome:
    timestamp: dt.datetime
    state: SliceState

    @property
    def counts_as_read(self) -> bool:
        return self.state is SliceState.READ

    @property
    def counts_against_coverage(self) -> bool:
        return self.state in (SliceState.MISSING, SliceState.FAILED)


def slice_url(timestamp: dt.datetime) -> str:
    """URL for the GKG slice covering `timestamp`.

    GDELT slice names are timestamp derived, which is what makes backfill
    possible after a late or missed run.
    """
    return f"{GKG_BASE_URL}/{timestamp.strftime('%Y%m%d%H%M%S')}.gkg.csv.zip"


def slice_timestamps(
    window_start: dt.datetime, window_end: dt.datetime
) -> list[dt.datetime]:
    """Every slice timestamp in [window_start, window_end), aligned to the grid.

    GDELT slices land on 15 minute boundaries, so the window is snapped to that
    grid rather than to whatever the caller happened to pass in.
    """
    _require_utc(window_start, "window_start")
    _require_utc(window_end, "window_end")

    step = dt.timedelta(minutes=GKG_SLICE_INTERVAL_MINUTES)
    first = _floor_to_slice(window_start)
    out: list[dt.datetime] = []
    cursor = first
    while cursor < window_end:
        if cursor >= window_start:
            out.append(cursor)
        cursor += step
    return out


def is_within_read_lag(timestamp: dt.datetime, now: dt.datetime) -> bool:
    """True when a slice is too young to expect it to be readable yet.

    A 404 on such a slice is PENDING, not MISSING. This is the whole rule.
    """
    _require_utc(timestamp, "timestamp")
    _require_utc(now, "now")
    age_minutes = (now - timestamp).total_seconds() / 60.0
    return age_minutes < GKG_READ_LAG_MINUTES


def classify_404(timestamp: dt.datetime, now: dt.datetime) -> SliceState:
    """Classify a 404 by the slice's age. The disambiguator for an ambiguous 404."""
    if is_within_read_lag(timestamp, now):
        return SliceState.PENDING
    return SliceState.MISSING


@dataclass(frozen=True)
class CoverageReport:
    """Coverage over one confirmation window, and whether UNREPORTED is allowed.

    Two independent gates, because they fail for different reasons:

    1. MATURITY. Every slice older than the read lag horizon must have been
       attempted, and no slice may still be pending. A pending slice means the
       source has not published it yet, so the window is not finished, and no
       determination over it is safe at any coverage level.
    2. COVERAGE. Of the slices that are mature, at least `coverage_min` must
       have been read successfully.

    Pending slices are excluded from the coverage denominator. Including them
    would conflate "the source has not published this yet" with "we failed to
    read this", which are different facts with different remedies: the first is
    fixed by waiting, the second by investigating. Excluding them is safe only
    because gate 1 blocks independently on their presence. Remove gate 1 and
    this exclusion becomes a way to claim full coverage of a window that has
    barely been published.
    """

    outcomes: tuple[SliceOutcome, ...]

    @property
    def total_slices(self) -> int:
        """Every slice in the window, whatever its state."""
        return len(self.outcomes)

    @property
    def read_slices(self) -> int:
        return sum(1 for o in self.outcomes if o.counts_as_read)

    @property
    def pending_slices(self) -> int:
        """Young and unread: the source has not published these yet."""
        return sum(1 for o in self.outcomes if o.state is SliceState.PENDING)

    @property
    def gap_slices(self) -> int:
        """Mature and unread: real gaps, whatever the cause."""
        return sum(1 for o in self.outcomes if o.counts_against_coverage)

    @property
    def mature_slices(self) -> int:
        """Slices old enough that we should have been able to read them."""
        return self.read_slices + self.gap_slices

    @property
    def index_coverage_fraction(self) -> float:
        """Share of the MATURE window actually ingested.

        Zero when nothing in the window is mature yet, which is the honest
        answer: we know nothing about a window the source has not published.
        """
        if self.mature_slices == 0:
            return 0.0
        return self.read_slices / self.mature_slices

    @property
    def fully_observed(self) -> bool:
        """True when nothing in the window is still waiting to be published."""
        return self.pending_slices == 0

    def may_assert_unreported(self, coverage_min: float = COVERAGE_MIN) -> bool:
        """The gate. Both conditions, and neither implies the other."""
        if not self.fully_observed:
            return False
        if self.mature_slices == 0:
            return False
        return self.index_coverage_fraction >= coverage_min

    def reason_blocked(self, coverage_min: float = COVERAGE_MIN) -> str | None:
        """Why UNREPORTED is blocked, for the panel and the logs. None if allowed.

        The panel renders this verbatim. A deferred determination must be
        legible as "we have not finished checking", never as "we checked and
        found nothing", because those are opposite claims.
        """
        if not self.fully_observed:
            return (
                f"{self.pending_slices} of {self.total_slices} news index slices in this "
                f"window have not been published by the source yet. Determination deferred."
            )
        if self.mature_slices == 0:
            return "No news index slices in this window are available yet. Determination deferred."
        if self.index_coverage_fraction < coverage_min:
            return (
                f"News index covered {self.index_coverage_fraction:.1%} of this window, "
                f"below the {coverage_min:.0%} minimum. {self.gap_slices} slice(s) could "
                f"not be read. Determination deferred."
            )
        return None


def _floor_to_slice(timestamp: dt.datetime) -> dt.datetime:
    minute = (timestamp.minute // GKG_SLICE_INTERVAL_MINUTES) * GKG_SLICE_INTERVAL_MINUTES
    return timestamp.replace(minute=minute, second=0, microsecond=0)


def _require_utc(value: dt.datetime, name: str) -> None:
    """Reject naive datetimes.

    Every window in this project is computed from data timestamps, and a naive
    datetime is the standard way that silently becomes local time on one machine
    and UTC on another. ARCHITECTURE.md section 1a and DETECTION_SPEC.md
    section 8.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone aware, got naive {value!r}")
