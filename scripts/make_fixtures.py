"""Generate fixtures/ from DATA_CONTRACTS.md, including the awkward cases.

Ground rule 6: the frontend is built against fixtures, so frontend and pipeline
proceed in parallel. DATA_CONTRACTS.md is the only coupling between them.

The fixtures deliberately lead with the cases that break naive renderers, which
is the list at the end of DATA_CONTRACTS.md:

  1. sigma null with baseline_quality "unavailable"
  2. baseline_quality "insufficient", SUSPECTED via the absolute floors
  3. two events whose h3_r5_current differs from the cell inside the event_id
  4. sigma_capped true
  5. CORROBORATED with same_plane_persistence and corroboration_degraded true
  6. UNREPORTED with a populated query_strategy_version and no articles
  7. heartbeat.json fresh, stale, and with no unassisted write yet

A renderer that handles these handles the real feed. One that only handles a
tidy 4.2 sigma CORROBORATED event will fall over on day one.

Regenerate with:  python scripts/make_fixtures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "fixtures"

PIPELINE_VERSION = "0.1.0"
BASELINE_VERSION = "firms_noaa20_2021_2025"
GENERATED_AT = "2026-11-06T06:00:00Z"


def feature(
    *,
    event_id: str,
    lon: float,
    lat: float,
    event_type: str,
    family: str,
    stage: str,
    severity: float,
    sigma: float | None,
    baseline_quality: str,
    corroboration_type: str,
    first_detected: str,
    last_detected: str,
    area_km2: float,
    h3_r5_current: str,
    interactive: bool,
    inside_protected_area: bool = False,
    intersects_species_range: bool = False,
    is_active: bool = True,
) -> dict:
    half = max(area_km2, 1.0) ** 0.5 / 200.0
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "event_id": event_id,
            "event_type": event_type,
            "family": family,
            "stage": stage,
            "severity": severity,
            "sigma": sigma,
            "baseline_quality": baseline_quality,
            "corroboration_type": corroboration_type,
            "first_detected": first_detected,
            "last_detected": last_detected,
            "is_active": is_active,
            "bbox": [
                round(lon - half, 4),
                round(lat - half, 4),
                round(lon + half, 4),
                round(lat + half, 4),
            ],
            "area_km2": area_km2,
            "h3_r5_current": h3_r5_current,
            "interactive": interactive,
            "inside_protected_area": inside_protected_area,
            "intersects_species_range": intersects_species_range,
        },
    }


# ---------------------------------------------------------------------------
# The pin set
# ---------------------------------------------------------------------------

FEATURES = [
    # A plain, well behaved CORROBORATED event. The control case: if this one
    # does not render, nothing else is worth debugging.
    feature(
        event_id="thm_8528347bfffffff_20261031",
        lon=101.4523,
        lat=-1.8841,
        event_type="forest_fire",
        family="thermal",
        stage="CORROBORATED",
        severity=0.78,
        sigma=4.2,
        baseline_quality="good",
        corroboration_type="independent_cross_sensor",
        first_detected="2026-10-31T03:12:00Z",
        last_detected="2026-11-05T02:44:00Z",
        area_km2=34.6,
        h3_r5_current="8528347bfffffff",
        interactive=True,
        intersects_species_range=True,
    ),
    # CASE 1: unscorable because no baseline row exists for this cell and month.
    # A detection where nothing has burned in five years is potentially the most
    # interesting kind, and also the one the statistics cannot score. The panel
    # must say "not scored against a norm", never 0 and never blank.
    feature(
        event_id="thm_851f8d4bfffffff_20261103",
        lon=-62.1904,
        lat=-10.4412,
        event_type="forest_fire",
        family="thermal",
        stage="SUSPECTED",
        severity=0.41,
        sigma=None,
        baseline_quality="unavailable",
        corroboration_type="single_sensor",
        first_detected="2026-11-03T05:40:00Z",
        last_detected="2026-11-05T05:51:00Z",
        area_km2=8.2,
        h3_r5_current="851f8d4bfffffff",
        interactive=False,
    ),
    # CASE 2: a baseline row exists but fails the two part grading test, so the
    # event reaches SUSPECTED only through the absolute floors.
    feature(
        event_id="thm_8509a3b7fffffff_20261104",
        lon=133.8812,
        lat=-23.6980,
        event_type="forest_fire",
        family="thermal",
        stage="SUSPECTED",
        severity=0.33,
        sigma=None,
        baseline_quality="insufficient",
        corroboration_type="single_sensor",
        first_detected="2026-11-04T14:02:00Z",
        last_detected="2026-11-05T13:55:00Z",
        area_km2=5.1,
        h3_r5_current="8509a3b7fffffff",
        interactive=False,
    ),
    # CASE 3a: a spreading fire whose centroid has crossed an H3 boundary. The
    # event_id still carries the cell it was FIRST detected in, and that
    # divergence is intended. Any code that derives geography from the id
    # rather than from h3_r5_current is wrong, and these two fixtures are how
    # that bug gets caught before it ships.
    feature(
        event_id="thm_8528340ffffffff_20261028",
        lon=114.2210,
        lat=-2.4455,
        event_type="forest_fire",
        family="thermal",
        stage="CONFIRMED",
        severity=0.91,
        sigma=6.8,
        baseline_quality="good",
        corroboration_type="independent_cross_sensor",
        first_detected="2026-10-28T02:10:00Z",
        last_detected="2026-11-05T03:02:00Z",
        area_km2=212.4,
        h3_r5_current="8528341bfffffff",
        interactive=True,
        intersects_species_range=True,
    ),
    # CASE 3b: the same divergence in Family B, so the frontend cannot special
    # case it as a thermal quirk.
    feature(
        event_id="fls_8667b1a3fffffff_20261012",
        lon=-55.0132,
        lat=-6.7741,
        event_type="deforestation",
        family="forest_loss",
        stage="CORROBORATED",
        severity=0.64,
        sigma=3.7,
        baseline_quality="sparse",
        corroboration_type="adjacent_layer",
        first_detected="2026-10-12T00:00:00Z",
        last_detected="2026-11-02T00:00:00Z",
        area_km2=47.9,
        h3_r5_current="8667b1b7fffffff",
        interactive=True,
        inside_protected_area=True,
    ),
    # CASE 4: sigma hit the cap. The panel must render this as "at least this
    # extreme", not as a precise 10.0 that the baseline cannot support.
    feature(
        event_id="thm_85283447fffffff_20261105",
        lon=72.9104,
        lat=19.0760,
        event_type="industrial_thermal",
        family="thermal",
        stage="CORROBORATED",
        severity=0.88,
        sigma=10.0,
        baseline_quality="good",
        corroboration_type="adjacent_layer",
        first_detected="2026-11-05T16:20:00Z",
        last_detected="2026-11-05T22:41:00Z",
        area_km2=2.3,
        h3_r5_current="85283447fffffff",
        interactive=True,
    ),
    # CASE 5: corroboration is degraded. MODIS is not arriving, so the gate has
    # fallen back to same_plane_persistence and the panel must say that
    # independent cross sensor checking is no longer available.
    feature(
        event_id="thm_8510b64bfffffff_20261101",
        lon=25.4102,
        lat=60.1699,
        event_type="forest_fire",
        family="thermal",
        stage="CORROBORATED",
        severity=0.55,
        sigma=3.4,
        baseline_quality="sparse",
        corroboration_type="same_plane_persistence",
        first_detected="2026-11-01T11:30:00Z",
        last_detected="2026-11-04T12:10:00Z",
        area_km2=12.7,
        h3_r5_current="8510b64bfffffff",
        interactive=True,
    ),
    # CASE 6: the headline state. Detected, corroborated, aged past the
    # confirmation window, and no coverage found by this query strategy in an
    # index that did cover the window.
    feature(
        event_id="thm_8598b39bfffffff_20261020",
        lon=113.6500,
        lat=62.5400,
        event_type="forest_fire",
        family="thermal",
        stage="UNREPORTED",
        severity=0.72,
        sigma=5.1,
        baseline_quality="good",
        corroboration_type="independent_cross_sensor",
        first_detected="2026-10-20T04:15:00Z",
        last_detected="2026-10-29T05:02:00Z",
        area_km2=96.3,
        h3_r5_current="8598b39bfffffff",
        interactive=True,
        is_active=False,
    ),
]


def live_json() -> dict:
    return {
        "type": "FeatureCollection",
        "generated_at": GENERATED_AT,
        "pipeline_version": PIPELINE_VERSION,
        "features": FEATURES,
    }


# ---------------------------------------------------------------------------
# Detail payloads
# ---------------------------------------------------------------------------


def detail_for(props: dict, geometry: dict) -> dict:
    """Build a detail payload consistent with its live.json feature.

    headline_claim is generated HERE, on the pipeline side, exactly as
    DATA_CONTRACTS requires, so the frontend cannot overstate it. The wording
    changes with the evidence: an unscored event does not get a sigma sentence,
    and a degraded corroboration says so.
    """
    sigma = props["sigma"]
    quality = props["baseline_quality"]
    degraded = props["corroboration_type"] == "same_plane_persistence"
    unscored = sigma is None

    caveats = [
        "Baseline derived from 5 years of VIIRS NOAA-20 history, calendar years 2021 to 2025.",
        "Baseline is science quality data and the observation is near real time data, which differ slightly.",
    ]

    if unscored:
        headline = (
            "Cluster passed absolute size and intensity floors but could not be scored "
            "against a regional seasonal norm."
        )
        caveats.append(
            "No usable baseline exists for this cell and month, so no anomaly score is claimed."
            if quality == "unavailable"
            else "The baseline for this cell and month is too sparse to support a variance estimate."
        )
    else:
        capped = sigma >= 10.0
        magnitude = f"at least {sigma} sigma" if capped else f"{sigma} sigma"
        headline = (
            f"Sustained anomalous thermal activity, {magnitude} above the regional "
            f"November norm"
        )
        if degraded:
            headline += ", corroborated only by repeated passes of one sensor family."
        elif props["corroboration_type"] == "adjacent_layer":
            headline += ", corroborated by an independent physical measurement."
        else:
            headline += ", corroborated by an independent sensor."
        if capped:
            caveats.append(
                "The anomaly score reached the reporting cap, so the true value is higher "
                "than the figure shown."
            )

    if not unscored:
        # D1: the observed quantity is a trailing 28 day total, so a brief
        # intense event is averaged across four weeks of mostly nothing and
        # scores lower than its intensity suggests. The absolute floors are
        # what catch those, and saying so is the difference between an honest
        # limitation and a silently blunt detector.
        caveats.append(
            "The anomaly score compares a trailing 28 day total against the same "
            "quantity in past years, so a short intense event is understated. "
            "Brief events are caught by absolute size and intensity floors instead."
        )

    if degraded:
        caveats.append(
            "Independent cross sensor checking is not available for this event. "
            "Corroboration rests on repeated passes of one sensor family."
        )
    if quality == "sparse":
        caveats.append(
            "Baseline for this cell and week is sparse. Treat the score as indicative."
        )

    confirmation: dict
    if props["stage"] == "UNREPORTED":
        confirmation = {
            "state": "unreported",
            "window_closes": "2026-10-27T04:15:00Z",
            "query_strategy": "gkg_bulk_local_filter",
            "query_strategy_version": 1,
            "index_coverage_fraction": 0.97,
            "pending_slices_in_window": 0,
            "articles": [],
        }
        caveats.append(
            "No matching coverage was found by this query strategy in this index. "
            "That is not the same as no coverage existing anywhere."
        )
    elif props["stage"] == "CONFIRMED":
        confirmation = {
            "state": "confirmed",
            "window_closes": "2026-11-04T02:10:00Z",
            "query_strategy": "gkg_bulk_local_filter",
            "query_strategy_version": 1,
            "index_coverage_fraction": 1.0,
            "pending_slices_in_window": 0,
            "articles": [
                {
                    "title": "Peat fires spread across Central Kalimantan",
                    "source": "example-wire.invalid",
                    "url": "https://example-wire.invalid/kalimantan-peat-fires",
                    "published_at": "2026-10-30T09:12:00Z",
                }
            ],
        }
    else:
        confirmation = {
            "state": "pending",
            "window_closes": "2026-11-12T00:00:00Z",
            "query_strategy": "gkg_bulk_local_filter",
            "query_strategy_version": 1,
            "index_coverage_fraction": 0.42,
            "pending_slices_in_window": 6,
            "articles": [],
        }
        caveats.append(
            "Confirmation is still pending: part of the news index window has not been "
            "published by the source yet."
        )

    # Stated only when it is true. A cluster inside one cell needs no
    # explanation; one spanning several does, because the published sigma
    # describes the centroid cell and not the whole footprint.
    if (3 if props["area_km2"] > 100 else 1) > 1:
        caveats.append(
            "This event spans several H3 cells. The anomaly score describes the cell "
            "containing its centroid, not the whole footprint."
        )

    return {
        "event_id": props["event_id"],
        "event_type": props["event_type"],
        "stage": props["stage"],
        "headline_claim": headline,
        "location": {
            "centroid": geometry["coordinates"],
            "bbox": props["bbox"],
            "h3_r5_current": props["h3_r5_current"],
            "admin": {"country": "Unknown", "region": "Unknown"},
        },
        "statistics": {
            "sigma": sigma,
            "sigma_floored": quality == "sparse" and not unscored,
            "sigma_capped": (not unscored) and sigma >= 10.0,
            "observed_frp_sum": None if unscored else round(400.0 + (sigma or 0) * 310.0, 1),
            "baseline_mean_log": None if unscored else 5.35,
            "baseline_std_log": None if unscored else 0.61,
            "baseline_quality": quality,
            "baseline_version": None if quality == "unavailable" else BASELINE_VERSION,
            "years_observed": 0 if quality == "unavailable" else 5,
            "detections_total": 0 if quality == "unavailable" else 212,
            "trend_slope": None if unscored else 0.04,
            "pixel_count": 44,
            "area_km2": props["area_km2"],
            # How many H3 r5 cells the cluster footprint touches. Sigma scores
            # the CENTROID cell only, so where this exceeds 1 the caveat below
            # says the score describes one cell of several.
            "cells_intersected": 3 if props["area_km2"] > 100 else 1,
            "scored_cell": props["h3_r5_current"],
            "growth_rate_km2_per_day": 5.2 if props["is_active"] else 0.0,
        },
        "classification": {
            "predicted_class": props["event_type"],
            "confidence": 0.91,
            "alternatives": [{"class": "crop_residue_burning", "confidence": 0.07}],
        },
        "timeline": [
            {
                "timestamp": props["first_detected"],
                "sensor": "VIIRS_NOAA20",
                "pixel_count": 44,
                "frp_sum": 180.1,
                "stage_after": "SUSPECTED",
            },
            {
                "timestamp": props["last_detected"],
                "sensor": "VIIRS_NOAA20",
                "pixel_count": 61,
                "frp_sum": 240.7,
                "stage_after": props["stage"],
            },
        ],
        "corroboration": {
            "corroboration_type": props["corroboration_type"],
            "corroboration_degraded": degraded,
            "pass_count": 4,
            "sensors": ["VIIRS_NOAA20", "VIIRS_NOAA21"]
            if degraded
            else ["VIIRS_NOAA20", "MODIS_TERRA"],
            "adjacent_layer_agreement": [
                {
                    "layer": "openaq",
                    "station_id": "XX-0001",
                    "metric": "pm25",
                    "value": 184,
                    "distance_km": 22,
                }
            ]
            if props["corroboration_type"] == "adjacent_layer"
            else [],
        },
        "context": {
            "inside_protected_area": props["inside_protected_area"],
            "nearest_protected_area": {"name": "Unnamed reserve", "distance_km": 18},
            "intersecting_species_ranges": [
                {
                    "scientific_name": "Panthera tigris",
                    "common_name": "Tiger",
                    "red_list_category": "EN",
                }
            ]
            if props["intersects_species_range"]
            else [],
            "landcover": "tropical_moist_forest",
        },
        "confirmation": confirmation,
        # Never empty. Every event carries at least one honest limitation.
        "caveats": caveats,
    }


# ---------------------------------------------------------------------------
# meta.json and the three heartbeat states
# ---------------------------------------------------------------------------


def meta_json() -> dict:
    by_stage: dict[str, int] = {}
    for f in FEATURES:
        stage = f["properties"]["stage"]
        by_stage[stage] = by_stage.get(stage, 0) + 1
    return {
        "generated_at": GENERATED_AT,
        "pipeline_version": PIPELINE_VERSION,
        "runs": {
            "thermal": {
                "last_success": "2026-11-06T06:00:00Z",
                "status": "ok",
                "expected_cadence_minutes": 360,
                "data_as_of": "2026-11-06T04:48:00Z",
            },
            "forest_loss": {
                "last_success": "2026-11-03T04:00:00Z",
                "status": "ok",
                "expected_cadence_minutes": 10080,
                "data_as_of": "2026-11-01T00:00:00Z",
            },
            "atmospheric": {
                "last_success": "2026-11-05T01:00:00Z",
                "status": "degraded",
                "note": "OpenAQ timeout, partial",
                "expected_cadence_minutes": 1440,
                "data_as_of": "2026-11-04T22:00:00Z",
            },
        },
        "counts": {
            # Deliberately showing fewer than total, so the truncation message
            # has something to render.
            "total_active": 7412,
            "shown": len(FEATURES),
            "by_stage": by_stage,
        },
        "latency": {
            "measured": False,
            "observation_to_publish_minutes_p50": None,
            "note": "No latency is claimed until one has been measured.",
        },
        "baseline_version": BASELINE_VERSION,
        # Degraded, because fixture case 5 depends on the chrome rendering it.
        "corroboration_mode": "degraded",
    }


def heartbeats() -> dict[str, dict]:
    base = {
        "run_number": 48,
        "source_commit": "0215a5bad276",
        "triggered_by": "workflow_dispatch",
        "dispatch_source": "external-timer",
        "dispatch_scheduled_for": "2026-11-06T09:00:00Z",
        "dispatch_lag_seconds": 11,
        "expected_cadence_minutes": 60,
        "stale_after_minutes": 150,
        "trigger_mode": "external_timer",
    }
    return {
        # Fresh: written moments ago, well inside stale_after_minutes.
        "heartbeat.fresh.json": {
            **base,
            "written_at": "2026-11-06T09:00:11Z",
            "writes_by_trigger": {"schedule": 1, "external_timer": 42, "manual": 5},
            "first_unassisted_write": "2026-11-05T23:34:22Z",
            "last_unassisted_write": "2026-11-06T09:00:11Z",
        },
        # Stale: older than stale_after_minutes, so the page must say the update
        # job may have stopped. A stale globe that admits it is stale is
        # trustworthy; one that silently shows week old data is not.
        "heartbeat.stale.json": {
            **base,
            "run_number": 12,
            "written_at": "2026-11-04T02:11:00Z",
            "writes_by_trigger": {"schedule": 1, "external_timer": 10, "manual": 1},
            "first_unassisted_write": "2026-11-03T18:02:00Z",
            "last_unassisted_write": "2026-11-04T02:11:00Z",
        },
        # No unassisted write yet: the pre exit Phase 0 state. Every write so far
        # was a human pressing a button, so the derived count is zero and the
        # page must NOT claim the criterion is met.
        "heartbeat.no-unassisted.json": {
            "run_number": 3,
            "written_at": "2026-11-06T08:58:00Z",
            "source_commit": "abc123def456",
            "triggered_by": "workflow_dispatch",
            "dispatch_source": "manual",
            "dispatch_scheduled_for": None,
            "dispatch_lag_seconds": None,
            "expected_cadence_minutes": 300,
            "stale_after_minutes": 660,
            "trigger_mode": "schedule_only",
            "writes_by_trigger": {"schedule": 0, "external_timer": 0, "manual": 3},
            "first_unassisted_write": None,
            "last_unassisted_write": None,
        },
    }


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )


def main() -> int:
    written: list[str] = []

    write_json(FIXTURES / "events" / "live.json", live_json())
    written.append("events/live.json")

    for f in FEATURES:
        props = f["properties"]
        path = FIXTURES / "events" / "detail" / f"{props['event_id']}.json"
        write_json(path, detail_for(props, f["geometry"]))
        written.append(f"events/detail/{props['event_id']}.json")

    write_json(FIXTURES / "meta.json", meta_json())
    written.append("meta.json")

    for name, payload in heartbeats().items():
        write_json(FIXTURES / name, payload)
        written.append(name)

    for name in written:
        print(f"wrote fixtures/{name}")
    print(f"\n{len(written)} fixture files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
