"""Tests for the GKG read lag rule and coverage accounting.

The rule under test exists to stop one specific bug: publishing "satellites saw
this, media did not" about a window the pipeline never finished reading. These
tests are therefore about a claim, not about arithmetic.
"""

from __future__ import annotations

import datetime as dt

import pytest

from pipeline.detect.constants import (
    COVERAGE_MIN,
    GKG_READ_LAG_MINUTES,
    GKG_SLICE_INTERVAL_MINUTES,
)
from pipeline.sources.gkg_coverage import (
    CoverageReport,
    SliceOutcome,
    SliceState,
    classify_404,
    is_within_read_lag,
    slice_timestamps,
    slice_url,
)

NOW = dt.datetime(2026, 11, 6, 5, 31, tzinfo=dt.UTC)


def ts(**kwargs: int) -> dt.datetime:
    return NOW - dt.timedelta(**kwargs)


# ---------------------------------------------------------------------------
# The read lag classification
# ---------------------------------------------------------------------------


def test_404_on_a_young_slice_is_pending_not_missing():
    """The observed failure: the manifest names a slice that is not readable yet.

    Measured 2026-11-06, the 05:30Z slice was named by lastupdate.txt and
    returned 404 on three consecutive attempts.
    """
    young = ts(minutes=1)
    assert is_within_read_lag(young, NOW) is True
    assert classify_404(young, NOW) is SliceState.PENDING


def test_404_on_a_mature_slice_is_a_real_gap():
    mature = ts(minutes=GKG_READ_LAG_MINUTES + 1)
    assert is_within_read_lag(mature, NOW) is False
    assert classify_404(mature, NOW) is SliceState.MISSING


def test_the_boundary_is_the_constant_not_a_hardcoded_number():
    """Exactly at the horizon counts as mature, so the boundary is not ambiguous."""
    at_horizon = ts(minutes=GKG_READ_LAG_MINUTES)
    assert is_within_read_lag(at_horizon, NOW) is False
    assert classify_404(at_horizon, NOW) is SliceState.MISSING


def test_the_observed_lag_window_is_covered_by_the_constant():
    """Slices 45 to 60 minutes old were observed 404. The constant must cover that.

    This pins the measurement into the test suite. If someone lowers
    GKG_READ_LAG_MINUTES below the observed lag, this fails rather than
    silently reclassifying unpublished slices as real gaps.
    """
    assert GKG_READ_LAG_MINUTES >= 60
    for age in (45, 50, 60):
        assert classify_404(ts(minutes=age), NOW) is SliceState.PENDING


def test_naive_datetimes_are_rejected():
    """A naive datetime is how a window silently becomes local time on one box."""
    naive = dt.datetime(2026, 11, 6, 5, 0)
    with pytest.raises(ValueError, match="timezone aware"):
        is_within_read_lag(naive, NOW)
    with pytest.raises(ValueError, match="timezone aware"):
        slice_timestamps(naive, NOW)


# ---------------------------------------------------------------------------
# The gate, which is the point of the module
# ---------------------------------------------------------------------------


def test_manifest_names_an_unreadable_slice_so_coverage_falls_below_threshold():
    """The required case: the manifest advertises a slice that cannot be read.

    Four slices, one of them mature and unreadable. Coverage is 3/4 = 75 percent,
    which is below COVERAGE_MIN, so UNREPORTED must not be asserted.

    This is the test that fails if the 404 path is left unimplemented: an
    implementation that trusted the manifest would record 4 of 4 read and sail
    through the gate.
    """
    outcomes = (
        SliceOutcome(ts(minutes=200), SliceState.READ),
        SliceOutcome(ts(minutes=185), SliceState.READ),
        SliceOutcome(ts(minutes=170), SliceState.READ),
        SliceOutcome(ts(minutes=155), SliceState.MISSING),
    )
    report = CoverageReport(outcomes)

    assert report.mature_slices == 4
    assert report.index_coverage_fraction == pytest.approx(0.75)
    assert report.index_coverage_fraction < COVERAGE_MIN
    assert report.may_assert_unreported() is False
    assert "below the" in (report.reason_blocked() or "")


def test_a_pending_slice_blocks_unreported_even_at_full_mature_coverage():
    """Maturity and coverage are independent gates.

    A long window with one unpublished slice has mature coverage of 100 percent,
    so the coverage gate alone would pass it. The window is still unfinished.
    Without this gate, every window evaluated too early would assert UNREPORTED.
    """
    outcomes = (
        *(
            SliceOutcome(ts(minutes=200 + i * GKG_SLICE_INTERVAL_MINUTES), SliceState.READ)
            for i in range(40)
        ),
        SliceOutcome(ts(minutes=1), SliceState.PENDING),
    )
    report = CoverageReport(outcomes)

    assert report.index_coverage_fraction == pytest.approx(1.0)
    assert report.index_coverage_fraction >= COVERAGE_MIN
    assert report.fully_observed is False
    assert report.may_assert_unreported() is False
    assert "not been published" in (report.reason_blocked() or "")


def test_a_fully_read_mature_window_may_assert_unreported():
    """The positive case must actually pass, or the suite proves nothing."""
    outcomes = tuple(
        SliceOutcome(ts(minutes=200 + i * GKG_SLICE_INTERVAL_MINUTES), SliceState.READ)
        for i in range(20)
    )
    report = CoverageReport(outcomes)

    assert report.fully_observed is True
    assert report.index_coverage_fraction == pytest.approx(1.0)
    assert report.may_assert_unreported() is True
    assert report.reason_blocked() is None


def test_a_transport_failure_counts_against_coverage_like_a_gap():
    """A 500 or a truncated zip is not an excuse to claim coverage we lack."""
    outcomes = (
        SliceOutcome(ts(minutes=200), SliceState.READ),
        SliceOutcome(ts(minutes=185), SliceState.FAILED),
    )
    report = CoverageReport(outcomes)
    assert report.gap_slices == 1
    assert report.index_coverage_fraction == pytest.approx(0.5)
    assert report.may_assert_unreported() is False


def test_a_window_with_nothing_mature_yet_asserts_nothing():
    """Coverage of an unpublished window is 0.0, not 1.0 by vacuous division."""
    outcomes = (
        SliceOutcome(ts(minutes=5), SliceState.PENDING),
        SliceOutcome(ts(minutes=20), SliceState.PENDING),
    )
    report = CoverageReport(outcomes)
    assert report.mature_slices == 0
    assert report.index_coverage_fraction == 0.0
    assert report.may_assert_unreported() is False


def test_an_empty_window_asserts_nothing():
    """Guard against vacuous truth: no slices must not mean full coverage."""
    report = CoverageReport(())
    assert report.index_coverage_fraction == 0.0
    assert report.may_assert_unreported() is False


# ---------------------------------------------------------------------------
# A guard that must fail where it should, so the suite cannot pass vacuously
# ---------------------------------------------------------------------------


def test_the_gate_is_not_trivially_true():
    """Deliberate negative control.

    If someone replaces may_assert_unreported with `return True`, the assertions
    above still largely pass in spirit but this one states the requirement
    directly: there must exist an input for which the gate is False.
    """
    blocked = CoverageReport((SliceOutcome(ts(minutes=1), SliceState.PENDING),))
    allowed = CoverageReport((SliceOutcome(ts(minutes=200), SliceState.READ),))
    assert blocked.may_assert_unreported() is False
    assert allowed.may_assert_unreported() is True


# ---------------------------------------------------------------------------
# Slice naming and windowing
# ---------------------------------------------------------------------------


def test_slice_url_uses_https_and_the_observed_name_format():
    """http 301s to https://host:443/ and that redirect is not worth relying on."""
    url = slice_url(dt.datetime(2026, 11, 6, 5, 30, tzinfo=dt.UTC))
    assert url == "https://data.gdeltproject.org/gdeltv2/20261106053000.gkg.csv.zip"
    assert url.startswith("https://")


def test_slice_timestamps_align_to_the_fifteen_minute_grid():
    start = dt.datetime(2026, 11, 6, 4, 7, tzinfo=dt.UTC)
    end = dt.datetime(2026, 11, 6, 5, 0, tzinfo=dt.UTC)
    stamps = slice_timestamps(start, end)
    assert [s.strftime("%H%M") for s in stamps] == ["0415", "0430", "0445"]


def test_slice_timestamps_are_empty_for_an_inverted_window():
    start = dt.datetime(2026, 11, 6, 5, 0, tzinfo=dt.UTC)
    end = dt.datetime(2026, 11, 6, 4, 0, tzinfo=dt.UTC)
    assert slice_timestamps(start, end) == []
