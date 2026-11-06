"""Every threshold in the pipeline, as a named constant.

Rule for this file: if a number influences whether a pin appears, what stage it
reaches, or what the panel claims about it, that number lives here with a comment
saying where it came from. A magic number buried in a function is a number nobody
can tune, review or defend.

Values marked TUNING START are starting points to be tuned empirically. When one
is settled, record the settled value in the doc section named beside it, not only
here, or the docs and the code drift apart.
"""

# ---------------------------------------------------------------------------
# Baseline grading. DETECTION_SPEC.md section 2.
# ---------------------------------------------------------------------------
# Four fixed values: good, sparse, insufficient, unavailable. The grading is a
# two part test on purpose. years_observed alone would grade a cell holding five
# years of exactly one detection as "good", which is five years of evidence that
# almost nothing burns there and no basis whatsoever for a variance estimate.

BASELINE_GOOD_MIN_YEARS = 4        # of the 5 window years, with any detection
BASELINE_GOOD_MIN_DETECTIONS = 20  # total for this (cell, month) across the window
BASELINE_SPARSE_MIN_YEARS = 3
BASELINE_SPARSE_MIN_DETECTIONS = 5

# Rationale, recorded so the numbers are defensible rather than arbitrary:
# 4 of 5 years is where a standard deviation over yearly aggregates stops being
# dominated by a single outlier year. 20 detections is roughly 4 per year, enough
# that the log space variance comes from spread rather than from presence or
# absence. The sparse tier keeps the original 3 year cutoff so earlier behaviour
# stays reachable and comparable.

BASELINE_QUALITY_SCORABLE = ("good", "sparse")
BASELINE_QUALITY_UNSCORABLE = ("insufficient", "unavailable")
BASELINE_QUALITY_VALUES = BASELINE_QUALITY_SCORABLE + BASELINE_QUALITY_UNSCORABLE

# ---------------------------------------------------------------------------
# Sigma scoring. DETECTION_SPEC.md section 4.
# ---------------------------------------------------------------------------
# raw_sigma = (log1p(observed) - baseline_mean_log) / max(baseline_std_log, FLOOR)
# sigma     = min(raw_sigma, SIGMA_CAP)
#
# baseline_mean_log and baseline_std_log are ALREADY statistics of log1p values.
# Only the observed value is transformed at the call site. Applying log1p to the
# stored mean a second time was an error in the first draft of the spec, caught
# before any code depended on it. The stored names carry the unit for exactly
# this reason.

BASELINE_STD_LOG_FLOOR = 0.25  # substituting this sets sigma_floored
SIGMA_CAP = 10.0               # exceeding this sets sigma_capped

# Both the floor and the cap fail conservatively on purpose. Substituting the
# floor understates a score. A capped sigma reported as "at least this extreme"
# is more honest than a precise figure the baseline cannot support.

# A std_log of exactly zero must NEVER reach the scoring path. Grading assigns
# such a cell "insufficient". If one arrives at scoring anyway that is a grading
# bug, so score.py raises rather than papering over it. This ruling is stated
# here as well as in DETECTION_SPEC.md section 2 because this is where someone
# will be standing when they are tempted to add a fallback.
BASELINE_STD_LOG_ZERO_IS_A_BUG = True

# ---------------------------------------------------------------------------
# Stage promotion. DETECTION_SPEC.md section 6.
# ---------------------------------------------------------------------------
SUSPECTED_SIGMA_MIN = 3.0  # on either detection_count or frp_sum

# Absolute floors, per family, for clusters that cannot be scored against a norm
# (baseline_quality insufficient or unavailable). These are the only route to
# SUSPECTED without a sigma, and they are deliberately blunt.
# TUNING START. DETECTION_SPEC.md section 6.
ABSOLUTE_FLOORS = {
    "thermal": {"pixel_count": 5, "frp_sum": 20.0},
    "forest_loss": {"pixel_count": 10, "area_km2": 0.5},
}

# Confirmation windows, in days, measured on DATA TIMESTAMPS and never on run
# times. Forest loss reporting lags, hence the longer window.
CONFIRMATION_WINDOW_DAYS = {
    "thermal": 7,
    "forest_loss": 21,
    "atmospheric": 7,
    "marine": 14,
}

# ---------------------------------------------------------------------------
# Clustering. DETECTION_SPEC.md section 3.
# ---------------------------------------------------------------------------
# TUNING START, all three. The time scaling constant is the knob that decides
# whether a fire burning over four days is one event or four, so it is the one
# that most changes what a pin means. Tune on known multi day fires and record
# the settled value in DETECTION_SPEC.md section 3.
DBSCAN_EPS_KM = 2.0
DBSCAN_TIME_SCALE_KM_PER_DAY = 1.5
DBSCAN_MIN_SAMPLES = 3

# Cross run matching: a cluster from today must be matched to the registry entry
# it continues, or events fragment across runs.
# TUNING START.
CROSS_RUN_BBOX_OVERLAP_MIN = 0.3
CROSS_RUN_TEMPORAL_ADJACENCY_HOURS = 48

# ---------------------------------------------------------------------------
# GDELT confirmation. DETECTION_SPEC.md section 6.
# ---------------------------------------------------------------------------
COVERAGE_MIN = 0.9  # TUNING START. index_coverage_fraction needed to assert UNREPORTED

# The GKG read lag. Measured 2026-11-06: GKG objects are not readable until
# roughly 45 to 60 minutes after their own timestamp, while export and mentions
# from the SAME manifest line are readable immediately. So lastupdate.txt naming
# a GKG slice is not a statement that the slice can be fetched.
#
# 75 minutes is the observed ceiling of 60 plus margin. Re measure from a GitHub
# runner in Phase 3 with a time based stopping rule: the original figure is one
# observation window, one morning, one residential IP, and cannot tell a
# structural lag from a transient backlog.
GKG_READ_LAG_MINUTES = 75

GKG_SLICE_INTERVAL_MINUTES = 15  # GDELT publishes a slice every 15 minutes

# Why this constant is load bearing rather than tidy: UNREPORTED is an assertion
# about a negative result. An implementation that treated the manifest as ground
# truth would record full coverage over a window it had failed to read, then
# publish "satellites saw this, media did not" about an event the media may well
# have covered in the slices it never fetched. That is a false headline finding
# manufactured by an unhandled 404.

QUERY_STRATEGY = "gkg_bulk_local_filter"
QUERY_STRATEGY_VERSION = 1  # bump when the relevance filter changes; marks
# earlier UNREPORTED determinations as not comparable. It never rewrites them.

# ---------------------------------------------------------------------------
# Emission. DATA_CONTRACTS.md.
# ---------------------------------------------------------------------------
MAX_INTERACTIVE_FEATURES = 3000  # hard cap, enforced by the pipeline at merge time

# ---------------------------------------------------------------------------
# Writing to the data branch. ARCHITECTURE.md section 9a.
# ---------------------------------------------------------------------------
# Concurrency is optimistic and lives at the git layer: fetch, rebase, retry,
# with jitter. There is no lock, because a GitHub concurrency group holds only
# one pending run and a shared group would silently drop dispatches.
PUSH_MAX_ATTEMPTS = 5
PUSH_BACKOFF_BASE_SECONDS = 2.0
PUSH_JITTER_SECONDS = 3.0
