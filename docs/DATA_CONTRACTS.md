# DATA CONTRACTS

> **TerraView24** : *Damage done by humans, measured against the norm*
>
> Part of the TerraView24 doc set. See `ARCHITECTURE.md` for the system overview.

The only coupling between the pipeline and the frontend. Both sides code against this file and nothing else, which means pipeline and frontend work can proceed in parallel from day one.

**Build the frontend against fixture files matching these schemas before the pipeline produces anything real.** Do not wait for live data to start the globe. The fixtures must include the awkward cases, listed at the end of this file, because those are what break naive renderers.

All payloads are served from the `data` branch over the CDN read path.

---

## Paths

```
data/
├── heartbeat.json                # Phase 0 proof and the staleness signal
├── events/
│   ├── live.json                 # MERGED pin set, hard cap 3000 features. What the frontend reads
│   ├── live.<family>.json        # per family, written by one workflow only
│   └── detail/<event_id>.json    # lazy loaded, fetched on click only
├── layers/
│   ├── species_ranges.json       # polygons
│   ├── protected_areas.json      # polygons
│   └── plumes/<date>.json        # surface fields, Phase 3
├── registry/
│   └── <family>.json             # pipeline internal, one per family, frontend ignores
├── gkg_index.json                # pipeline internal, compact news index, expired aggressively
├── meta.json                     # MERGED run status, counts, freshness. What the frontend reads
├── meta.<family>.json            # per family, written by one workflow only
├── vercel.json                   # disables Vercel builds for this branch
└── archive/YYYY-MM.json
```

**Why the per family split.** Two workflows must never write the same file. The concurrency control is
an optimistic fetch, rebase and retry push, not a lock, so a shared file would produce a genuine
conflict on every overlapping write. See `ARCHITECTURE.md` section 9a. Each writing workflow owns
`registry/<family>.json`, `events/live.<family>.json` and `meta.<family>.json`, and nothing else.

**`live.json` and `meta.json` are derived.** They are rebuilt from whichever per family files exist, as
the last step of every write. The frontend reads only the merged files and never the per family ones. A
merge is always well defined, so a late writer produces a correct union instead of clobbering a peer.
The 3000 feature cap is applied at merge time, across families, after ranking.

---

## `heartbeat.json`

Written by the Phase 0 workflow and kept afterwards as the freshness signal. One authoritative counter, everything else derived.

```json
{
  "run_number": 7,
  "written_at": "2026-11-06T09:00:11Z",
  "source_commit": "0215a5bad276",
  "triggered_by": "workflow_dispatch",
  "dispatch_source": "external-timer",
  "dispatch_scheduled_for": "2026-11-06T09:00:00Z",
  "dispatch_lag_seconds": 11,
  "expected_cadence_minutes": 60,
  "stale_after_minutes": 150,
  "writes_by_trigger": { "schedule": 1, "external_timer": 6, "manual": 4 },
  "first_unassisted_write": "2026-11-05T23:34:22Z",
  "last_unassisted_write": "2026-11-06T09:00:11Z"
}
```

| Field | Rule |
|---|---|
| `run_number` | GitHub's run counter across **all** triggers. It is not a count of scheduled runs and the page must never label it as one. Label it "Run" |
| `triggered_by` | `github.event_name`: `schedule` or `workflow_dispatch` |
| `dispatch_source` | A **claim**, passed as a `workflow_dispatch` input. `external-timer` from the Worker, `manual` by default. GitHub cannot tell the Worker from a person running `curl` |
| `dispatch_scheduled_for`, `dispatch_lag_seconds` | The checkable part. The time the timer says it fired against the time the run actually wrote |
| `writes_by_trigger` | **The one authoritative counter.** A `schedule` event counts as `schedule`. A `workflow_dispatch` with `dispatch_source == external-timer` counts as `external_timer`. Anything else counts as `manual` |
| unassisted writes | **Derived, never stored.** `schedule + external_timer`. The page computes it |
| `first_unassisted_write`, `last_unassisted_write` | Timestamps of the first and latest unassisted write |
| `stale_after_minutes` | The pipeline owns the staleness decision. The page says "older than it should be" when the age of `written_at` exceeds it |

The previous attempt shipped two counters, `schedule_writes_total` and `unassisted_writes_total`, which started out disagreeing and made the page deny a criterion it had met. Do not recreate that.

---

## `events/live.json`

GeoJSON `FeatureCollection`. Deliberately lean: everything needed to render and gate a pin, nothing more. Detail is a separate fetch.

```json
{
  "type": "FeatureCollection",
  "generated_at": "2026-11-05T06:00:00Z",
  "pipeline_version": "1.4.0",
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Point", "coordinates": [101.4523, -1.8841] },
      "properties": {
        "event_id": "thm_8528347bfffffff_20261031",
        "event_type": "forest_fire",
        "family": "thermal",
        "stage": "CORROBORATED",
        "severity": 0.78,
        "sigma": 4.2,
        "baseline_quality": "good",
        "corroboration_type": "independent_cross_sensor",
        "first_detected": "2026-10-31T03:12:00Z",
        "last_detected": "2026-11-05T02:44:00Z",
        "is_active": true,
        "bbox": [101.41, -1.92, 101.49, -1.84],
        "area_km2": 34.6,
        "h3_r5_current": "8528347bfffffff",
        "interactive": true,
        "inside_protected_area": false,
        "intersects_species_range": true
      }
    }
  ]
}
```

### Field rules

| Field | Rule |
|---|---|
| `event_id` | Stable across runs. Format `<family_prefix>_<h3_r5>_<first_detection_date>`. The frontend uses it as a cache key, so it must never change for a continuing event. **The `h3_r5` component is stamped once at first detection and never recomputed.** |
| `h3_r5_current` | The cell containing the event's current centroid. Mutable. It is allowed to differ from the cell inside `event_id`, and that divergence is intended. Use this field, not the id, for any geographic query or display |
| `stage` | One of `SUSPECTED`, `CORROBORATED`, `CONFIRMED`, `UNREPORTED`. Drives colour and interactivity |
| `severity` | Normalised 0 to 1 within family. Drives pin size. Never compare across families |
| `sigma` | A number, or `null` when `baseline_quality` is `insufficient` or `unavailable`. The frontend must render `null` as "not scored", never as 0 or as blank |
| `baseline_quality` | One of `good`, `sparse`, `insufficient`, `unavailable`. Definitions in `DETECTION_SPEC.md` section 2 |
| `corroboration_type` | One of `independent_cross_sensor`, `adjacent_layer`, `same_plane_persistence`, `single_sensor` |
| `interactive` | `false` for all `SUSPECTED`. The frontend uses this to decide billboard versus point primitive, so the pipeline owns that decision, not the client |
| `intersects_species_range` | Set by the spatial join. The frontend uses it to keep the relevant species polygon lit when the pin opens |

### The 3000 cap

The pipeline enforces it, not the frontend. Rank by `severity * recency_decay` and truncate. Record the truncated count in `meta.json` so the UI can say "showing 3000 of 7412 active detections" honestly.

---

## `events/detail/<event_id>.json`

Fetched on pin click. May be large. Powers the entire panel.

```json
{
  "event_id": "thm_8528347bfffffff_20261031",
  "event_type": "forest_fire",
  "stage": "CORROBORATED",
  "headline_claim": "Sustained anomalous thermal activity, 4.2 sigma above the regional October norm, corroborated across 4 passes by an independent sensor.",
  "location": {
    "centroid": [101.4523, -1.8841],
    "bbox": [101.41, -1.92, 101.49, -1.84],
    "h3_r5_current": "8528347bfffffff",
    "admin": { "country": "Indonesia", "region": "Riau" }
  },
  "statistics": {
    "sigma": 4.2,
    "sigma_floored": false,
    "sigma_capped": false,
    "observed_frp_sum": 1840.2,
    "baseline_mean_log": 5.35,
    "baseline_std_log": 0.61,
    "baseline_quality": "good",
    "baseline_version": "firms_noaa20_2021_2025",
    "years_observed": 5,
    "detections_total": 212,
    "trend_slope": 0.04,
    "pixel_count": 412,
    "area_km2": 34.6,
    "growth_rate_km2_per_day": 5.2
  },
  "classification": {
    "predicted_class": "forest_fire",
    "confidence": 0.91,
    "alternatives": [
      { "class": "crop_residue_burning", "confidence": 0.07 }
    ]
  },
  "timeline": [
    {
      "timestamp": "2026-10-31T03:12:00Z",
      "sensor": "VIIRS_NOAA20",
      "pixel_count": 44,
      "frp_sum": 180.1,
      "stage_after": "SUSPECTED"
    }
  ],
  "corroboration": {
    "corroboration_type": "independent_cross_sensor",
    "corroboration_degraded": false,
    "pass_count": 4,
    "sensors": ["VIIRS_NOAA20", "MODIS_TERRA"],
    "adjacent_layer_agreement": [
      { "layer": "openaq", "station_id": "ID-1204", "metric": "pm25", "value": 184, "distance_km": 22 }
    ]
  },
  "context": {
    "inside_protected_area": false,
    "nearest_protected_area": { "name": "Tesso Nilo National Park", "distance_km": 18 },
    "intersecting_species_ranges": [
      { "scientific_name": "Panthera tigris", "common_name": "Tiger", "red_list_category": "EN" }
    ],
    "landcover": "tropical_moist_forest"
  },
  "confirmation": {
    "state": "pending",
    "window_closes": "2026-11-07T00:00:00Z",
    "query_strategy": "gkg_bulk_local_filter",
    "query_strategy_version": 1,
    "index_coverage_fraction": 1.0,
    "articles": []
  },
  "caveats": [
    "Baseline derived from 5 years of VIIRS NOAA-20 history, calendar years 2021 to 2025.",
    "Baseline is science quality data and the observation is near real time data, which differ slightly.",
    "Classification is probabilistic. Alternatives are shown with confidence."
  ]
}
```

### Rules

- `headline_claim` is **generated by the pipeline, not the frontend.** The claim discipline from ARCHITECTURE section 5 is enforced at the point of generation so the frontend cannot overstate it. It states the corroboration type honestly, and states plainly when the event is unscored.
- `caveats` is never empty. Every event has at least one honest limitation. The panel renders them.
- **Baseline statistics are stored in the space they live in.** `baseline_mean_log` and `baseline_std_log` are statistics of `log1p` transformed values. The names carry the unit so the call site cannot log them a second time.
- `sigma_floored` is true when `baseline_std_log` was below the floor and the floor was substituted. `sigma_capped` is true when the raw sigma exceeded the cap and the cap is reported, which the panel must display as "at least this extreme".
- When `baseline_quality` is `insufficient` or `unavailable`, `sigma`, `baseline_mean_log` and `baseline_std_log` are `null` and the panel says the event could not be scored against a norm.
- `confirmation.articles` holds title, source, url and publication date. On `UNREPORTED`, the array is empty and `state` is `"unreported"`, and the panel must show the query strategy and version so the negative result is inspectable.
- `query_strategy_version` is bumped whenever the relevance filter changes. A change marks earlier `UNREPORTED` determinations as **not comparable**. It never silently rewrites them.
- `index_coverage_fraction` is the share of the confirmation window for which GKG slices were actually ingested. `UNREPORTED` may only be asserted when it meets the coverage threshold in `DETECTION_SPEC.md` section 6.

---

## `layers/species_ranges.json`

GeoJSON `FeatureCollection` of polygons. Separate payload, separate toggle, separate visual language. This layer is **published reference data, not pipeline output**, and must never render like a detection.

```json
{
  "type": "Feature",
  "geometry": { "type": "MultiPolygon", "coordinates": [] },
  "properties": {
    "scientific_name": "Panthera tigris",
    "common_name": "Tiger",
    "red_list_category": "EN",
    "population_estimate": "...",
    "population_trend": "...",
    "assessment_year": 2022,
    "primary_threats": ["habitat_loss", "poaching", "human_conflict"],
    "conservation_actions": [],
    "source": "IUCN Red List",
    "source_url": "..."
  }
}
```

IUCN maps subspecies within the parent species, so an example such as the Sumatran tiger arrives inside `Panthera tigris`, not as its own polygon. Fill the population fields from the v4 API for the polygon actually supplied.

Geometry is simplified for rendering. Keep the simplification tolerance generous; these polygons are visual context, not a precision instrument, and full resolution range maps will destroy frame rate.

---

## `meta.json`

```json
{
  "generated_at": "2026-11-05T06:00:00Z",
  "pipeline_version": "1.4.0",
  "runs": {
    "thermal":      { "last_success": "2026-11-05T06:00:00Z", "status": "ok", "expected_cadence_minutes": 360, "data_as_of": "2026-11-05T04:48:00Z" },
    "forest_loss":  { "last_success": "2026-11-03T04:00:00Z", "status": "ok", "expected_cadence_minutes": 10080, "data_as_of": "2026-11-01T00:00:00Z" },
    "atmospheric":  { "last_success": "2026-11-05T01:00:00Z", "status": "degraded", "note": "OpenAQ timeout, partial", "expected_cadence_minutes": 1440, "data_as_of": "2026-11-04T22:00:00Z" }
  },
  "counts": {
    "total_active": 7412,
    "shown": 3000,
    "by_stage": { "SUSPECTED": 5102, "CORROBORATED": 1840, "CONFIRMED": 322, "UNREPORTED": 148 }
  },
  "latency": {
    "measured": false,
    "observation_to_publish_minutes_p50": null,
    "note": "No latency is claimed until one has been measured."
  },
  "baseline_version": "firms_noaa20_2021_2025",
  "corroboration_mode": "full"
}
```

- `data_as_of` is the **satellite acquisition time** of the newest record, which is a different and more honest number than `last_success`.
- `latency.measured` stays `false`, and the page claims no latency, until the end to end figure from acquisition to page render has actually been measured.
- `corroboration_mode` is `full` while independent sensors are arriving, and `degraded` when MODIS has stopped and the fallback in `ARCHITECTURE.md` section 5a is active.

The frontend surfaces freshness, staleness and degraded status in the UI chrome. A stale globe that admits it is stale is trustworthy. One that silently shows week old data is not.

---

## Versioning

`pipeline_version` is semver. Any breaking schema change is a major bump, and the frontend checks the major version on load and shows a clear message on mismatch rather than failing silently with undefined fields.

---

## Fixtures that must exist before the globe is built

1. An event with `sigma: null` and `baseline_quality: "unavailable"`.
2. An event with `baseline_quality: "insufficient"` that is `SUSPECTED` via the absolute floors.
3. Two events whose `h3_r5_current` differs from the cell inside their `event_id`.
4. An event with `sigma_capped: true`.
5. A `CORROBORATED` event with `corroboration_type: "same_plane_persistence"` and `corroboration_degraded: true`.
6. An `UNREPORTED` event with a populated `query_strategy_version` and an empty article list.
7. A `heartbeat.json` in each state: fresh, stale, and no unassisted write yet.
