"""Validate fixtures/ against DATA_CONTRACTS.md.

Two jobs. First, assert the fixtures are contract shaped, because the frontend
is built against them and a malformed fixture teaches the frontend the wrong
shape. Second, assert every awkward case from the end of DATA_CONTRACTS.md is
actually present: a fixture set that quietly loses its hard cases is worse than
none, because it produces confidence that the renderer handles them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.detect.constants import (
    BASELINE_QUALITY_UNSCORABLE,
    BASELINE_QUALITY_VALUES,
    MAX_INTERACTIVE_FEATURES,
    SIGMA_CAP,
)
from pipeline.emit.heartbeat import TRIGGER_KEYS, derive_unassisted_total

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "fixtures"

STAGES = {"SUSPECTED", "CORROBORATED", "CONFIRMED", "UNREPORTED"}
CORROBORATION_TYPES = {
    "independent_cross_sensor",
    "adjacent_layer",
    "same_plane_persistence",
    "single_sensor",
}


@pytest.fixture(scope="module")
def live() -> dict:
    return json.loads((FIXTURES / "events" / "live.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def features(live) -> list[dict]:
    return live["features"]


@pytest.fixture(scope="module")
def details() -> dict[str, dict]:
    out = {}
    for path in (FIXTURES / "events" / "detail").glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        out[payload["event_id"]] = payload
    return out


# ---------------------------------------------------------------------------
# Contract shape
# ---------------------------------------------------------------------------


def test_live_is_a_feature_collection(live):
    assert live["type"] == "FeatureCollection"
    assert live["generated_at"].endswith("Z")
    assert live["pipeline_version"]


def test_every_feature_has_the_contract_properties(features):
    required = {
        "event_id",
        "event_type",
        "family",
        "stage",
        "severity",
        "sigma",
        "baseline_quality",
        "corroboration_type",
        "first_detected",
        "last_detected",
        "is_active",
        "bbox",
        "area_km2",
        "h3_r5_current",
        "interactive",
        "inside_protected_area",
        "intersects_species_range",
    }
    for f in features:
        missing = required - set(f["properties"])
        assert not missing, f"{f['properties'].get('event_id')} missing {missing}"


def test_enums_are_within_their_declared_sets(features):
    for f in features:
        p = f["properties"]
        assert p["stage"] in STAGES, p["event_id"]
        assert p["baseline_quality"] in BASELINE_QUALITY_VALUES, p["event_id"]
        assert p["corroboration_type"] in CORROBORATION_TYPES, p["event_id"]


def test_severity_is_normalised(features):
    for f in features:
        assert 0.0 <= f["properties"]["severity"] <= 1.0, f["properties"]["event_id"]


def test_suspected_events_are_never_interactive(features):
    """The pipeline owns this decision, not the client. SUSPECTED renders as a
    point primitive, so it must not carry interactive machinery."""
    for f in features:
        p = f["properties"]
        if p["stage"] == "SUSPECTED":
            assert p["interactive"] is False, p["event_id"]
        else:
            assert p["interactive"] is True, p["event_id"]


def test_unscorable_events_carry_null_sigma_not_zero(features):
    """A sigma of 0 means "exactly average". A sigma of null means "we could not
    score this". Conflating them is a claim the data does not support."""
    for f in features:
        p = f["properties"]
        if p["baseline_quality"] in BASELINE_QUALITY_UNSCORABLE:
            assert p["sigma"] is None, p["event_id"]
        else:
            assert isinstance(p["sigma"], int | float), p["event_id"]
            assert p["sigma"] is not None


def test_sigma_never_exceeds_the_cap(features):
    for f in features:
        sigma = f["properties"]["sigma"]
        if sigma is not None:
            assert sigma <= SIGMA_CAP, f["properties"]["event_id"]


def test_bbox_contains_its_own_centroid(features):
    for f in features:
        lon, lat = f["geometry"]["coordinates"]
        west, south, east, north = f["properties"]["bbox"]
        assert west <= lon <= east, f["properties"]["event_id"]
        assert south <= lat <= north, f["properties"]["event_id"]


def test_feature_count_is_within_the_hard_cap(features):
    assert len(features) <= MAX_INTERACTIVE_FEATURES


def test_event_ids_are_unique(features):
    ids = [f["properties"]["event_id"] for f in features]
    assert len(ids) == len(set(ids))


def test_every_feature_has_a_detail_payload(features, details):
    """The panel fetches detail by event_id on click. A missing file is a dead
    pin, which is worse than an absent one."""
    for f in features:
        assert f["properties"]["event_id"] in details, f["properties"]["event_id"]


# ---------------------------------------------------------------------------
# The awkward cases DATA_CONTRACTS.md requires
# ---------------------------------------------------------------------------


def test_case_1_an_event_with_null_sigma_and_unavailable_baseline(features):
    matches = [
        f
        for f in features
        if f["properties"]["sigma"] is None
        and f["properties"]["baseline_quality"] == "unavailable"
    ]
    assert matches, "fixture case 1 is missing"


def test_case_2_an_insufficient_baseline_suspected_via_absolute_floors(features):
    matches = [
        f
        for f in features
        if f["properties"]["baseline_quality"] == "insufficient"
        and f["properties"]["stage"] == "SUSPECTED"
    ]
    assert matches, "fixture case 2 is missing"


def test_case_3_two_events_whose_current_cell_differs_from_their_id(features):
    """The frozen event_id case.

    A spreading fire crosses an H3 boundary. The id keeps the cell it was first
    detected in, h3_r5_current moves, and the divergence is intended. Any code
    that parses geography out of the id is wrong, and two fixtures across two
    families exist so that bug cannot be special cased away.
    """
    diverged = [
        f
        for f in features
        if f["properties"]["event_id"].split("_")[1] != f["properties"]["h3_r5_current"]
    ]
    assert len(diverged) >= 2, f"fixture case 3 needs two events, found {len(diverged)}"
    assert len({f["properties"]["family"] for f in diverged}) >= 2, (
        "the divergence should appear in more than one family"
    )


def test_case_4_an_event_with_sigma_capped(features, details):
    capped = [d for d in details.values() if d["statistics"]["sigma_capped"] is True]
    assert capped, "fixture case 4 is missing"
    for d in capped:
        assert d["statistics"]["sigma"] == SIGMA_CAP
        assert "at least" in d["headline_claim"], (
            "a capped sigma must be claimed as 'at least this extreme', never as a "
            "precise figure the baseline cannot support"
        )


def test_case_5_a_degraded_same_plane_persistence_corroboration(features, details):
    matches = [
        f
        for f in features
        if f["properties"]["stage"] == "CORROBORATED"
        and f["properties"]["corroboration_type"] == "same_plane_persistence"
    ]
    assert matches, "fixture case 5 is missing"
    for f in matches:
        detail = details[f["properties"]["event_id"]]
        assert detail["corroboration"]["corroboration_degraded"] is True
        assert any(
            "independent cross sensor" in c.lower() for c in detail["caveats"]
        ), "a degraded event must say what it can no longer verify"


def test_case_6_an_unreported_event_with_a_strategy_version_and_no_articles(details):
    matches = [d for d in details.values() if d["stage"] == "UNREPORTED"]
    assert matches, "fixture case 6 is missing"
    for d in matches:
        conf = d["confirmation"]
        assert conf["state"] == "unreported"
        assert conf["articles"] == []
        assert isinstance(conf["query_strategy_version"], int)
        assert conf["query_strategy"]
        assert conf["pending_slices_in_window"] == 0, (
            "UNREPORTED must not be asserted while slices in the window are pending"
        )
        assert any("not the same as no coverage" in c for c in d["caveats"]), (
            "the UNREPORTED caveat must state that a negative result from one query "
            "strategy is not proof that no coverage exists anywhere"
        )


def test_case_7_heartbeats_in_all_three_states():
    fresh = json.loads((FIXTURES / "heartbeat.fresh.json").read_text(encoding="utf-8"))
    stale = json.loads((FIXTURES / "heartbeat.stale.json").read_text(encoding="utf-8"))
    none_yet = json.loads(
        (FIXTURES / "heartbeat.no-unassisted.json").read_text(encoding="utf-8")
    )

    for payload in (fresh, stale, none_yet):
        assert set(payload["writes_by_trigger"]) == set(TRIGGER_KEYS)
        assert payload["written_at"].endswith("Z")

    assert derive_unassisted_total(fresh["writes_by_trigger"]) > 0
    assert derive_unassisted_total(stale["writes_by_trigger"]) > 0
    assert derive_unassisted_total(none_yet["writes_by_trigger"]) == 0, (
        "the no-unassisted fixture is the pre exit Phase 0 state and must derive zero"
    )
    assert none_yet["first_unassisted_write"] is None
    assert none_yet["trigger_mode"] == "schedule_only", (
        "with no external timer the page must declare GitHub's measured cadence"
    )


# ---------------------------------------------------------------------------
# Claim discipline, which is the project's credibility
# ---------------------------------------------------------------------------


def test_caveats_are_never_empty(details):
    """Every event has at least one honest limitation."""
    for event_id, d in details.items():
        assert d["caveats"], event_id


def test_headline_claim_is_present_and_never_asserts_destruction(details):
    """Ground rule 2, asserted mechanically.

    A pin says what the instrument measured and how far it deviates from a norm.
    It does not say "forest destruction here". These words are the ones a
    well meaning edit would reach for.
    """
    forbidden = ("destruction", "destroyed", "devastat", "illegal", "criminal", "proves")
    for event_id, d in details.items():
        claim = d["headline_claim"]
        assert claim and claim[0].isupper(), event_id
        lowered = claim.lower()
        for word in forbidden:
            assert word not in lowered, f"{event_id} headline_claim contains {word!r}"


def test_unscored_events_do_not_claim_a_sigma_in_their_headline(details):
    for event_id, d in details.items():
        if d["statistics"]["sigma"] is None:
            assert "sigma" not in d["headline_claim"].lower(), event_id
            assert "could not be scored" in d["headline_claim"], event_id


def test_unscored_events_null_their_baseline_statistics(details):
    for event_id, d in details.items():
        stats = d["statistics"]
        if stats["baseline_quality"] in BASELINE_QUALITY_UNSCORABLE:
            assert stats["sigma"] is None, event_id
            assert stats["baseline_mean_log"] is None, event_id
            assert stats["baseline_std_log"] is None, event_id


def test_meta_claims_no_latency_until_one_is_measured():
    meta = json.loads((FIXTURES / "meta.json").read_text(encoding="utf-8"))
    assert meta["latency"]["measured"] is False
    assert meta["latency"]["observation_to_publish_minutes_p50"] is None


def test_meta_counts_allow_the_truncation_message_to_be_exercised():
    meta = json.loads((FIXTURES / "meta.json").read_text(encoding="utf-8"))
    assert meta["counts"]["shown"] < meta["counts"]["total_active"]


def test_meta_reports_data_as_of_separately_from_last_success():
    """data_as_of is satellite acquisition time, a different and more honest
    number than when the pipeline last ran."""
    meta = json.loads((FIXTURES / "meta.json").read_text(encoding="utf-8"))
    for name, run in meta["runs"].items():
        assert "data_as_of" in run, name
        assert run["data_as_of"] != run["last_success"], name


def test_no_fixture_claims_the_page_is_real_time():
    """ARCHITECTURE section 7: the phrase stays off the page until a latency has
    been measured, and meta.latency.measured is still false.

    One exemption, and it is not a loophole. "near real time" is NASA's product
    designation: FIRMS serves NRT records which are replaced by science quality
    (SP) records after about a five month lag. DETECTION_SPEC section 2 requires
    that discontinuity to be recorded on every event, because the baseline is SP
    and the observation is NRT, so the norm and the observation are not quite the
    same product. That is a statement about the DATA, not a claim about the
    page's freshness, which is what the rule actually prohibits.

    So: "near real time" is allowed, bare "real time" is not.
    """
    for path in FIXTURES.rglob("*.json"):
        text = path.read_text(encoding="utf-8").lower()
        without_product_name = text.replace("near real time", "").replace(
            "near-real-time", ""
        )
        assert "real time" not in without_product_name, (
            f"{path.name} claims real time. Only the NASA product name "
            f"'near real time' is permitted."
        )
        assert "realtime" not in without_product_name, path.name
