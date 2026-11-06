# DETECTION SPEC

> **TerraView24** : *Damage done by humans, measured against the norm*
>
> Part of the TerraView24 doc set. See `ARCHITECTURE.md` for the system overview.

This is the data science of the project. Everything else is plumbing around it.

The anomaly baseline is **mandatory**. Without it this is a feed renderer with a globe attached. With it, the claim changes from "a fire is here" to "there is more burning here than there should be at this time of year," which is a statement only a model can make.

---

## 1. Spatial indexing scheme

All baselines and all aggregation use **H3 hexagonal cells at resolution 5** (roughly 250 sq km per cell). Hexagons avoid the area distortion of a lat/lon grid at high latitudes, which matters because boreal fire is a large part of the thermal signal.

Every ingested record gets an `h3_r5` cell id at ingest time. Every baseline is keyed
**`(h3_r5, week_of_year)`**, and the quantity stored against each key is a **trailing 28 day total**.

**Decision D1, taken 2026-11-06.** This replaces the earlier `(h3_r5, month)` keying. The observed
value and the baseline are now the same quantity, so no proration is needed and the detector has no
blind period. Full reasoning, including the two rejected options, in `DECISION_D1.md`.

**Sigma is a property of the cell window, not of the cluster.** A cluster's own count and a cell's
28 day total are different quantities, and the claim this project makes ("there is more burning here
than there should be at this time of year") is a claim about a place and a season. Cluster size is
carried separately by `severity`, `area_km2` and `pixel_count`, so nothing is lost. Two events in one
hot cell share a sigma, and that is correct.

### Which cell scores a cluster that spans several

H3 r5 cells are roughly 253 sq km, so any large event covers several. The scoring cell is the one
containing the cluster's **centroid**, which is the cell already published as `h3_r5_current`.

The reason is selection bias, not convenience. **The cell must be chosen by a rule that cannot see the
score.** Taking the maximum sigma across the intersected cells would inflate it systematically, since
the maximum of several draws is biased upward and the bias grows with the number of cells, so the
largest events would acquire the highest sigmas as an artifact of their size. Choosing the cell with
the most detections is subtler but still biased, because detection count drives the numerator.
A centroid is fixed by geometry alone and is blind to both the observed value and the norm.

Aggregating across the intersected cells was also considered and rejected on arithmetic grounds: the
stored statistics are means and standard deviations of `log1p` values, and `log1p(a + b)` is not
`log1p(a) + log1p(b)`, so log space quantities cannot be summed across cells without rebuilding the
baseline in linear space and losing the skew correction that motivated the transform.

Record `cells_intersected` on every event, and where it exceeds 1, state in `caveats` that the score
describes the centroid cell rather than the whole footprint.

---

## 2. Tier 0: baseline construction (offline, once)

Notebook: `notebooks/01_build_thermal_baseline.ipynb`. Output committed to `pipeline/baselines/`. **Never recomputed in CI.**

### Sensor and window

**VIIRS NOAA-20 only, calendar years 2021 to 2025, a closed window.** A closed window is reproducible: it does not move as new data lands. NOAA-20's archive starts 2018-04-01, so it has 8.6 years and a 5 year window is fully buildable from it alone.

**Why Suomi NPP is excluded.** NASA stopped producing new S-NPP products on 2026-11-02, so its archive is closed. A sigma score is a statement about one instrument's normal behaviour. Blending two archives would let any residual calibration difference enter every score as an unknown constant, and the pipeline could no longer say which part of a 4.2 sigma reading was fire and which was instrument. Doing it properly means deriving a cross sensor calibration from the 2018 to 2026 overlap, which is a research project and is unnecessary when NOAA-20 alone clears the 5 year minimum. What is lost is stated plainly: cells whose fire regime changed before 2021, and a shorter trend window. Record this in `pipeline/baselines/README.md`.

NOAA-21 has 3.7 years and is a corroborating sensor only. MODIS Terra and Aqua are the independent cross check, with the retirement caveat in `ARCHITECTURE.md` section 5a.

**Discontinuity to record on every event:** the history is science quality (SP) data and the live feed is near real time (NRT) data. NRT is replaced by SP after about a 5 month lag, so the norm and the observation are not quite the same product.

### Procedure

1. Pull the FIRMS NOAA-20 SP archive for calendar years 2021 to 2025 through the asynchronous archive download service. Manual, by design.
2. Assign `h3_r5` to every detection. **The week key belongs to the window end, not to the
   detection**: a detection contributes to every trailing 28 day window that contains it, which is
   28 of them. Do not assign each detection a single week.
3. Aggregate per `(cell, week_of_year, year)` as a **trailing 28 day sum** ending in that week:
   - `detection_count`
   - `frp_sum`, `frp_mean`, `frp_p90`
4. Apply `log1p` to the per year `detection_count` and `frp_sum` values. Across the 5 years, compute per `(cell, week_of_year)`:
   - `count_mean_log`, `count_std_log`
   - `frp_sum_mean_log`, `frp_sum_std_log`
   - `years_observed` (how many of the 5 years had any detection in this trailing window)
   - `detections_total` (all detections across the five trailing 28 day windows for this key, so a
     span of 140 days, not 152)
5. Grade `baseline_quality` per the table below and write Parquet keyed on
   `(h3_r5, week_of_year)`, **partitioned by `week_of_year`** (see the storage section below).

**Note that adjacent week keys overlap.** Consecutive trailing 28 day windows share 21 of their 28
days, so neighbouring keys are heavily correlated. That is harmless for scoring, but the file must not
be read as 52 independent seasonal estimates: it is 52 overlapping views of the same year.

### Baseline quality

Four values, fixed. The grading is a **two part test**, because `years_observed` alone would grade a cell with five years of exactly one detection as `good`. That is five years of evidence that almost nothing burns there, and no basis at all for a variance estimate.

| `baseline_quality` | Rule | Scored? |
|---|---|---|
| `good` | `years_observed >= 4` AND `detections_total >= 20` AND `std_log > 0` | Yes |
| `sparse` | `years_observed >= 3` AND `detections_total >= 5` AND `std_log > 0`, and not `good` | Yes, with the panel flagging it |
| `insufficient` | A baseline row exists but fails the tests above | **No.** Emitted unscored with `sigma: null`. May be `SUSPECTED` only through the absolute floors |
| `unavailable` | No baseline row exists for this cell and month | **No.** Same handling. A detection where nothing has burned in 5 years is potentially the most interesting kind, and also the one the statistics cannot score |

Named constants, all in `pipeline/detect/constants.py`:

```python
BASELINE_GOOD_MIN_YEARS        = 4    # of 5 window years with any detection
BASELINE_GOOD_MIN_DETECTIONS   = 20   # total for this (cell, month) across the window
BASELINE_SPARSE_MIN_YEARS      = 3
BASELINE_SPARSE_MIN_DETECTIONS = 5
BASELINE_STD_LOG_FLOOR         = 0.25 # sets sigma_floored
SIGMA_CAP                      = 10.0 # sets sigma_capped
```

Rationale, rewritten for D1 on 2026-11-06. **The values did not change; their meaning did.**

`years_observed` is unaffected: 4 of 5 years is still where a standard deviation over yearly
aggregates stops being dominated by one outlier year.

`detections_total` now spans **140 days** (five trailing 28 day windows) rather than the 152 days
(five calendar months) it spanned before, which is 92 percent of the old span. So a threshold of 20
is now an effective 18.4 on the old scale: **slightly stricter, which is the safe direction**, since
it fails toward `insufficient`, meaning unscored and honestly labelled, rather than toward a
confident number the data cannot support. The old wording, "roughly 4 per year" of a month, no longer
describes what is being counted and has been removed rather than left beside an unchanged number,
because the next reader would reasonably assume it had been checked.

The sparse tier keeps the original 3 year cutoff so earlier behaviour stays reachable and comparable.

**`BASELINE_STD_LOG_FLOOR` is provisional and must be re measured.** 0.25 was chosen against the
spread of monthly aggregates. Overlapping 28 day windows are a different distribution, and because
adjacent windows share 21 of 28 days the year to year variance at a fixed week may well be lower. The
floor is the **denominator** of the sigma, so a floor set too high silently suppresses real anomalies,
which is a failure that produces no error and no symptom. Measure the distribution of `std_log`
across all graded cells in the Tier 0 notebook, choose the floor from it, and record both the
distribution and the chosen value here. **Do not carry 0.25 across on the assumption that it
transfers.**

**Both the floor and the cap fail conservatively on purpose.** Substituting the floor understates a score. A capped sigma reported as "at least this extreme" is more honest than a precise figure the baseline cannot support.

**A `std_log` of exactly zero must never reach the scoring path.** Grading assigns such a cell `insufficient`. If one arrives at scoring anyway, that is a grading bug: raise, do not paper over it. State this ruling in the code next to the constants as well as here.

### Storage: partitioning, and what is deliberately not stored

**GitHub rejects any single file over 100 MB** and warns above 50 MB. The baseline is committed to
`main` as a Tier 0 input to CI, so this is a hard constraint and not a tidiness concern. Estimated
sizes for `(h3_r5, week_of_year)` run from about 55 MB to about 109 MB depending on how many cells
have any fire history, which straddles the limit. Two measures, both required.

**1. Partition by `week_of_year`.**

```
pipeline/baselines/thermal_h3r5_week28d/
    week_of_year=01/part.parquet
    week_of_year=02/part.parquet
    ...
    week_of_year=52/part.parquet
```

Hive style, readable directly by `pyarrow.dataset`. Each shard lands around 1 to 2 MB, nowhere near
any limit.

Partitioning by week rather than by H3 base cell is chosen for a second reason that matters more at
run time: **a scoring run needs only the week it is scoring**, so it loads one or two shards instead
of the entire baseline. That turns a 109 MB read into roughly 2 MB on every run, which is runtime the
page publishes as latency (`ARCHITECTURE.md` section 8).

**2. Do not store rows that can never be scored.**

Only `good` and `sparse` keys carry statistics. Most `(cell, week)` keys in the world are near empty
and would otherwise dominate the file. To preserve the `insufficient` versus `unavailable` distinction
without storing every empty key, keep a compact cell level set of every `h3_r5` that saw **any**
detection in the window, as a single small file of one column.

Grading then resolves as:

| Lookup result | `baseline_quality` | Means |
|---|---|---|
| Key present with statistics | `good` or `sparse` | Scored |
| Key absent, cell in the observed set | `insufficient` | This cell burns, but not enough in this week to support a variance estimate |
| Key absent, cell not in the observed set | `unavailable` | Nothing has burned in this cell in 5 years |

This is a **small, deliberate refinement** of the definitions in the table above, which distinguished
the two by whether a row existed. The new distinction is arguably the more meaningful one, since a
detection in a cell that has never burned is exactly the interesting case the `unavailable` tier was
created to flag. Recorded here rather than applied silently.

**Enforced, not just intended:** `scripts/check_baseline_sizes.py` fails CI if any file under
`pipeline/baselines/` exceeds 40 MB, well below GitHub's limit, so the constraint is caught at commit
time rather than at push time.

### The problems you will hit, and the fixes

**Zero inflation.** Most cells in most months have zero fires. The mean and standard deviation of a mostly zero series are not meaningful, and a single detection in such a cell would score as an enormous sigma and flood the globe with false pins. The grading above is the fix: only `good` and `sparse` cells are scored, and everything else is gated by absolute size and FRP floors and labelled honestly.

**Skew.** Fire count distributions are heavily right skewed, so a Gaussian sigma is a poor fit. Transform with `log1p` **before** computing mean and standard deviation, and score in log space. The stored statistics are already log space quantities, which is why they are named `*_mean_log` and `*_std_log`. Document this; it is the kind of detail a reviewer will specifically look for.

**Trend contamination.** A 5 year window containing a genuine upward trend will bake that trend into the "norm," suppressing exactly the anomalies you want to find. Check for trend per cell and record `trend_slope` in the baseline. Where the slope is significant, note it on the event rather than silently absorbing it.

**Permanent hotspots.** Gas flares and some industrial sites burn year round. They will have a high, stable baseline and will correctly never trigger. This is the baseline working. Confirm this behaviour during validation; it is a good sanity check.

A matching baseline for Family B lives in `forestloss_h3r5_monthly.parquet`, built the same way from historical GLAD and RADD archives.

---

## 3. Clustering (`pipeline/detect/cluster.py`)

Raw detections are pixels. Pins must be **events**. Never render a pixel.

### Family A: thermal

**DBSCAN over scaled space and time.** Three dimensions: projected x, projected y, and time scaled into distance units.

- `eps`: approximately 2 km equivalent.
- Time scaling: 1 day maps to roughly 1.5 km of equivalent distance. This is the tuning knob that controls whether a fire burning over four days is one event or four. Tune it on known multi day fires and record the chosen value.
- `min_samples`: 3. Lower and you promote single pixel noise.

Use `cKDTree` backed neighbour queries. A naive all pairs approach over a global daily feed will not finish.

Do not deduplicate across sensors at ingest. Deduplicate at clustering and keep the sensor identities, because the corroboration type depends on which sensors saw the event.

Cluster output features, which become classifier inputs:
`pixel_count`, `frp_sum`, `frp_max`, `frp_mean`, `duration_hours`, `centroid`, `bbox`, `area_km2`, `sensors`, `pass_count`, `daynight_ratio`, `elongation` (major over minor axis of the fitted ellipse), `centroid_drift_km_per_day`, `landcover_class`.

### Family B: forest loss

**HDBSCAN** rather than DBSCAN. Forest loss patches vary enormously in density and HDBSCAN handles variable density without a global `eps`.

Shape features carry the classification here:
`area_km2`, `perimeter_area_ratio`, `elongation`, `rectangularity`, `fragmentation`, `edge_contact_with_prior_loss`, `distance_to_road`, `distance_to_water`, `inside_wdpa` (boolean, from spatial join), `growth_rate_km2_per_week`, `bare_earth_expansion_rate` (from Sentinel-2, carries the excavation case).

### Cross run matching

A cluster from today's run must be matched to the registry entry it continues, or events will fragment across runs. Match on bounding box overlap above a threshold plus temporal adjacency. On match, append the observation and recompute aggregate features over the full event history. The event's `event_id` never changes (see `ARCHITECTURE.md` section 6).

---

## 4. Scoring (`pipeline/detect/score.py`)

For each cluster, in log space, against the `(cell, month)` baseline:

```
raw_sigma = (log1p(observed) - baseline_mean_log) / max(baseline_std_log, BASELINE_STD_LOG_FLOOR)
sigma     = min(raw_sigma, SIGMA_CAP)
```

`baseline_mean_log` is already the mean of `log1p` values, so only the **observed** value is transformed here. Applying `log1p` to the stored mean a second time was an error in the first draft of this spec, found before any code depended on it.

Set `sigma_floored` when the floor was used and `sigma_capped` when the cap was used. Score both `detection_count` and `frp_sum`; keep both. The gate for `SUSPECTED` is `sigma >= 3.0` on either, plus the absolute floors.

Record `sigma`, `baseline_mean_log`, `baseline_std_log`, `baseline_quality`, `years_observed`, `detections_total` and `baseline_version` on every event. These are displayed in the panel. The number is the claim at stage 1. Events graded `insufficient` or `unavailable` carry `sigma: null`.

### Open issue D1: the unit of comparison

The baseline aggregates detections per `(cell, month)`, but a cluster is observed over hours or days. A cluster's count is not the same quantity as a calendar month total, and comparing them directly would understate every early month anomaly or need an unstated proration.

**Resolve this in the Tier 0 notebook, before `score.py` is written, and record the choice.** The recommended default: score the cell's **trailing 28 day total** (count and FRP sum) at run time against a baseline of trailing 28 day totals keyed `(h3_r5, week_of_year)`, so the observed and baseline quantities are the same unit and still have 5 samples per key. If calendar month keying is kept instead, the observed value must be the month to date total and the doc must say how early month values are handled. This is a decision for the human. Raise it at the start of Phase 1, do not pick silently.

**D1 does not block the FIRMS archive request** (ruling, 2026-11-06). The archive is raw detections,
and the keying choice only matters when the notebook aggregates them. The archive download is
asynchronous, emailed, and the slowest single item in the project, so **submit the request as early as
possible in Phase 1, before D1 is settled**, and build the scoring path against it while it runs.

**Note that section 2 currently assumes month keying** in its procedure, in the
`detections_total >= 20` threshold, and in the `thermal_h3r5_monthly.parquet` filename. If D1 resolves
to the trailing 28 day default, all three need rewriting, and the quality thresholds need
recalibrating for the new window. Do not treat section 2 as settled until D1 is.

---

## 5. Classification

### Family A classifier

Separates: `forest_fire`, `crop_residue_burning`, `gas_flaring`, `industrial_thermal`.

The discriminating logic, which the model should learn rather than you hard coding it:

| Class | Signature |
|---|---|
| `gas_flaring` | Stationary, permanent, aseasonal, high and stable FRP, strong night bias, zero centroid drift |
| `crop_residue_burning` | Brief duration, gridded and rectangular footprint, sharply seasonal, clusters densely over agricultural land cover, low FRP per pixel |
| `forest_fire` | Spreads. Non zero centroid drift, growing area over time, forest land cover, variable FRP |
| `industrial_thermal` | Fixed point, high FRP, deviates from **its own** historical norm rather than the regional one |

**Labels:** VIIRS Nightfire gives you flaring labels directly (V4.0, prefer the NOAA-20 and NOAA-21 streams). Crop burning labels come from land cover plus known seasonal windows (North India post monsoon and post winter harvest are dense, well documented label sources). Wildfire labels come from national fire agency perimeter datasets where available. The Nightfire licence is a signed agreement with a turnaround time, so start it early.

Model: gradient boosting. Report per class precision and recall in `notebooks/03_validate_detections.ipynb` and **surface the confusion matrix in the project write up.** Being open about where the classifier fails is worth more than a clean accuracy number.

### Family B classifier

Separates: `deforestation`, `mining_activity`, `urban_expansion_protected`.

- Mining reads as blobs: low elongation, high rectangularity, expanding radially, persistent bare earth, frequently near water.
- Logging reads as linear and gridded: high elongation, road adjacency, progressive edge expansion from prior loss.
- Urban expansion reads as built up signature adjacent to existing built up area, and is only its own class when `inside_wdpa` is true.

---

## 6. Stage promotion (`pipeline/state/promote.py`)

Evaluated for every live registry event on every run.

### SUSPECTED
```
(sigma >= 3.0  AND  pixel_count >= floor[family]  AND  frp_sum >= floor[family])
OR
(baseline_quality in {insufficient, unavailable}  AND  absolute floors passed)
```
Renders as a dim point primitive. Not interactive. Claim: the statistic only, or for unscored events, that the cluster passed absolute floors and could not be scored against a norm.

### CORROBORATED

A second **independent** signal agrees, recorded as `corroboration_type`. At least one of:

- `independent_cross_sensor`: a genuinely different instrument agrees (MODIS Terra or Aqua). This is why you do not deduplicate sensors at ingest.
- `adjacent_layer`: a different physical measurement agrees, meaning a Family C anomaly over the same bbox in the same window, or an OpenAQ station exceedance within range.

Agreement from NOAA-20 plus NOAA-21, or repeated passes of NOAA-20, is `same_plane_persistence`. These share an orbital plane (about 50 minutes apart), an identical instrument and a processing chain, so it is persistence and not independence. It does **not** satisfy the gate while an independent source is available.

**Degraded mode.** MODIS is ending (Terra around January to February 2027, Aqua between August 2026 and September 2027). When no MODIS data is arriving, the gate accepts `same_plane_persistence` with `pass_count >= 3`, sets `corroboration_degraded: true`, sets `meta.corroboration_mode` to `degraded`, and the panel states that independent cross sensor checking is no longer available. This behaviour is defined in the same commit as the gate, so the system degrades visibly and never quietly.

Becomes an interactive billboard.

### CONFIRMED

A relevance filter, run **locally** over the GDELT bulk GKG index, returns articles for the event's bbox and time window. Store the matched article set on the event.

Why bulk and not the DOC API: the DOC API allows one request per 5 seconds and returned HTTP 429 on every attempt from a normal client, probably throttling by source IP. Confirming 3000 events serially would take about 4.2 hours, and GitHub runner IP ranges are heavily shared. GKG slices are served from Google's CDN, about 5.4 MB per 15 minutes, with no rate limit encountered. Approved for Phase 3 with these conditions:

1. **The filter is readable code in the repo with its own tests.** A negative result is only as strong as the query strategy behind it, and a strategy that is code beats a remote service's undocumented ranking.
2. **`query_strategy_version` is stamped on every determination.** A change to the filter bumps the version and marks earlier determinations as not comparable. It never rewrites them.
3. **Relevance needs topical terms alongside the geographic match.** A naive geographic query returns every article mentioning the region. Match GKG themes and extracted locations, record the strategy, and make it reproducible.
4. **Confirmation is its own workflow** (`confirm.yml`), on its own cadence, so a slow index can never delay detection. It maintains a compact `gkg_index.json` of already filtered records, expired aggressively.

GKG slice file names are timestamp derived, so a late or missed run can backfill the slices it skipped. Record which slices were actually ingested.

#### The read lag rule

Measured 2026-11-06: **GKG objects are not readable until roughly 45 to 60 minutes after their own
timestamp**, while `export` and `mentions` from the same manifest line are readable immediately. So
`lastupdate.txt` naming a GKG slice is not a statement that the slice can be fetched. Evidence and
method in `DATA_SOURCES.md`.

This is a rule in the code, not a note in a document. In `constants.py`:

```python
GKG_READ_LAG_MINUTES = 75   # observed 45 to 60 min, plus margin. Re measure from a runner in Phase 3
```

A `404` on a GKG slice is classified by the slice's age, never treated as a uniform error:

| Slice age | `404` means | Effect on coverage |
|---|---|---|
| Younger than `GKG_READ_LAG_MINUTES` | **Not yet readable.** Expected, not an error | Slice is `pending`. It is retried on a later run and does **not** count as read |
| Older than `GKG_READ_LAG_MINUTES` | **A real gap.** The slice should have been there | Counts against `index_coverage_fraction` |

**The gate this feeds.** `UNREPORTED` may not be asserted until **every slice in the confirmation
window that is older than the lag horizon has been read successfully.** A window containing any
`pending` slice is not fully observed, so the event stays `pending` regardless of what
`index_coverage_fraction` computes to. The run must never fail because a recent slice returned `404`.

**Why this is load bearing rather than tidy.** `UNREPORTED` is an assertion about a negative result.
An implementation that treated the manifest as ground truth would record full coverage over a window it
had actually failed to read, and then publish "satellites saw this, media did not" about an event the
media may well have covered in the slices it never fetched. That is a false headline finding
manufactured by an unhandled `404`, and it is the most damaging single bug this project could ship.

**Required test:** a case where the manifest names a slice that is unreadable, asserting that
`index_coverage_fraction` comes out **below** `COVERAGE_MIN` and that `UNREPORTED` is therefore not
asserted. The suite must not be able to pass with the `404` path unimplemented.

**Re measure from a GitHub runner in Phase 3.** The 45 to 60 minute figure is one observation window,
one morning, one residential IP, and cannot distinguish a structural lag from a transient backlog. Use
a time based stopping rule per ground rule 11, and fix `GKG_READ_LAG_MINUTES` from that measurement.

### UNREPORTED
```
state == CORROBORATED  AND  age > confirmation_window[family]
AND  article_count == 0  AND  index_coverage_fraction >= COVERAGE_MIN
AND  pending_slices_in_window == 0
```

The final clause is the read lag rule above. A window holding any slice that is younger than
`GKG_READ_LAG_MINUTES` and not yet read is not a fully observed window, so the event stays `pending`
even when the computed coverage fraction clears the threshold.

Confirmation window: roughly 7 days for thermal, 21 days for forest loss, since forest loss reporting lags. `age` and the window are measured on **data timestamps**, never on run times.

`COVERAGE_MIN` is a named constant, starting at 0.9, tuned empirically. If the index did not cover the window, the event stays `pending`. Triggered runs can be late or missed, and an ingest gap would otherwise manufacture false `UNREPORTED` pins.

This is the headline state. It is also the one most likely to be challenged, so be precise about what it means: **no matching coverage was found by this query strategy in this index.** It does not mean no coverage exists anywhere. State that caveat in the panel.

---

## 7. Validation

Before any of this is presented as working, `notebooks/03_validate_detections.ipynb` must produce:

1. **Known event recall.** Take 20 to 30 major documented environmental events from the past 2 years. How many did the pipeline detect? Which did it miss and why?
2. **False positive audit.** Sample 50 `SUSPECTED` events at random and manually inspect against imagery. Report the rate.
3. **Classifier confusion matrix**, per class, held out.
4. **Baseline sanity:** confirm that known permanent flares do not trigger, and that known seasonal crop burning triggers in season and not out of it.
5. **Coverage bias analysis:** the `CONFIRMED` versus `UNREPORTED` split by region and income group. This is a genuine finding in its own right and belongs in the write up.
6. **Grading sanity:** the share of events by `baseline_quality`, and a check that no `std_log` of zero reaches scoring.

A reviewer will test the weakest pin, not the strongest. Section 7 is how you survive that.

---

## 8. Time handling

Every window, age and expiry in this spec is computed from **data timestamps** (satellite acquisition time, article publication time), never from the time a run happened to start. Triggered runs can be hours late or absent (`ARCHITECTURE.md` section 1a), so any rule phrased as "since the last run" is a bug. Anything that needs to know whether a window was fully observed records its own coverage, as `index_coverage_fraction` does for the news index.
