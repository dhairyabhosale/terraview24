# DECISION D1: the unit of comparison for scoring

> **TerraView24** : *Damage done by humans, measured against the norm*
>
> Open issue from `DETECTION_SPEC.md` section 4. **This needs a human decision.**
> Raised 2026-11-06, at the start of Phase 1, before `score.py` exists.

---

## The problem in one paragraph

The baseline aggregates detections per `(h3_r5, month)` across five years. A cluster is observed over
hours or days. **A cluster's detection count and a calendar month total are not the same quantity**,
so dividing one by the standard deviation of the other produces a number with no defensible meaning.
Comparing them directly would understate every early month anomaly, because a fire on the 2nd of the
month is being measured against a norm built from whole months.

Nothing in the pipeline fails loudly if this is got wrong. It produces plausible sigma values that are
quietly wrong, which is the worst failure mode available to this project, because sigma is the number
the panel puts in front of a reviewer.

---

## What is actually being compared, which is the part worth settling first

There is a second question hiding inside D1, and answering it first makes the rest easy.

`DETECTION_SPEC.md` section 4 says "for each cluster ... against the `(cell, month)` baseline", which
reads as scoring the **cluster**. The recommended fix in the same section says score "the cell's
trailing 28 day total", which scores the **cell window**. These are different things:

| | Scoring the cluster | Scoring the cell window |
|---|---|---|
| Unit | This event's own count | All detections in this cell over a fixed window |
| Against | A cell norm of a different unit. **Mismatched** | A cell norm of the same unit. **Matched** |
| If two events share a cell | Each gets its own sigma | Both carry the same sigma |
| The claim it supports | "This fire is unusually large" | "There is more burning in this cell than there should be at this time of year" |

**The second claim is the one this project set out to make.** The tagline is "measured against the
norm", and `DETECTION_SPEC.md` opens by saying the point is to move from "a fire is here" to "there is
more burning here than there should be at this time of year". That is a statement about a place and a
season, not about one cluster's size.

So: **sigma is a property of the cell window, and events inherit it.** Cluster size is already carried
separately by `severity`, `area_km2` and `pixel_count`, so nothing is lost. Two events in one hot cell
sharing a sigma is correct, not a defect.

If you disagree with that, stop here, because it changes every option below.

---

## The options

All three keep the mandatory parts: `log1p` before the statistics, five year closed window, NOAA-20
only, the four value grading, the floor and the cap.

### Option A: calendar month keys, observed value is month to date

Keep `(h3_r5, month)` exactly as section 2 already specifies. The observed quantity becomes the
month to date total for the cell.

- **For:** no change to the Tier 0 notebook, the parquet schema, the filename or the thresholds.
- **Against:** the observed window length varies from 1 to 31 days while the baseline window is always
  a whole month. On the 2nd of the month you are comparing 2 days against a 30 day norm, so **every
  early month event scores near zero sigma** and the detector is systematically blind for the first
  week of every month. Fixing that needs either a proration assumption (which is a model, stated
  nowhere, applied everywhere) or a separate baseline per day of month, which multiplies the keys by
  about 30 and is far worse than anything below.

**Assessment: rejected.** A detector with a predictable blind week is not defensible, and the fix is
worse than the alternatives.

### Option B: week of year keys, observed value is the trailing 28 day total

Baseline keyed `(h3_r5, week_of_year)`, 52 keys per cell. For each key, the distribution across the
five years of the trailing 28 day total ending in that week. At run time, score the cell's trailing 28
day total.

- **For:** observed and baseline are **the same quantity**, with no proration and no assumption. The
  window length is constant, so there is no blind period. Phase error is at most 3.5 days, since the
  observation can fall anywhere inside its week.
- **Against:** 52 keys per cell rather than 12, so the committed parquet is **about 4.3 times larger**.
  Adjacent week keys share 21 of their 28 days, so they are heavily correlated. That is harmless for
  scoring but means the baseline has fewer independent samples than the row count suggests, and the
  file should not be read as 52 independent seasonal estimates.

### Option C: 13 periods of 28 days, observed value is the trailing 28 day total

Divide the year into 13 periods of 28 days (364 days, with the remaining 1 or 2 days folded into the
last period). Baseline keyed `(h3_r5, period_of_year)`.

- **For:** the baseline window and the observation window are **exactly** the same length and the keys
  tile the year without overlap. Storage is the same as calendar months. The grading thresholds carry
  over almost unchanged.
- **Against:** phase error up to 14 days. A trailing 28 day window ending mid period is compared
  against a norm built from period aligned windows, so a sharply seasonal cell (crop burning is the
  obvious case, and it is one of our event classes) can be scored against a norm that is half in
  season and half out.

---

## Storage, which turns out to be decision relevant

H3 resolution 5 has 2,016,842 cells globally, roughly 585,000 over land. The number with any fire in
five years is the unknown; these are estimates to be replaced with the measured figure from the
notebook.

| Cells with fire | 12 month keys | 13 period keys | 52 week keys |
|---|---|---|---|
| ~88,000 (15 percent of land) | ~13 MB | ~14 MB | ~55 MB |
| ~175,000 (30 percent of land) | ~25 MB | ~27 MB | **~109 MB** |

**GitHub rejects any single file over 100 MB** without Git LFS, and warns above 50 MB. The baseline is
committed to `main` under `pipeline/baselines/` by design, as a Tier 0 input to CI. So Option B has a
real chance of hitting a hard platform limit, and Option C does not.

Two mitigations make Option B safe, and both are worth doing regardless:

1. **Do not store rows for cells that cannot be scored.** A cell graded `insufficient` or
   `unavailable` is never consulted for a sigma. Store a compact marker (cell, key, quality) for
   `insufficient` so the distinction from `unavailable` survives, and omit its statistics. This is
   where most of the rows are, because most cells in most weeks have almost nothing.
2. **Shard the parquet by H3 base cell** (122 of them) or by continent, so no single file approaches
   the limit even if the total does.

---

## Recommendation

**Option B: `(h3_r5, week_of_year)` with trailing 28 day totals, with unscorable rows dropped and the
parquet sharded.**

The deciding argument is `crop_residue_burning`. It is one of the four Family A classes, it is
*defined* by being sharply seasonal, and North India's post monsoon window is one of the project's
densest label sources. Option C's 14 day phase error lands exactly on that signal: a late October
observation scored against a period norm that straddles the start of the burning season will read as
anomalous when it is merely early, or as normal when it is genuinely extreme. Option B's 3.5 day error
does not do that.

The cost is storage, and storage has two known fixes while a phase error on the project's most
seasonal class has none.

**Why 28 days and not 7 or 14.** Shorter windows are more responsive to a single intense fire, but a
7 day total in a typical cell is zero far more often, which pushes many more cells into `insufficient`
and shrinks the scorable map. 28 days is the shortest window that keeps the zero inflation problem
manageable. It is a starting point to be tuned, not a settled value: validate it in the Tier 0
notebook against the known event recall test in `DETECTION_SPEC.md` section 7.1, and record the
settled figure.

**What this costs us, stated plainly.** A 28 day trailing total dilutes short sharp events. A
three day flare up in an otherwise quiet cell will lift a 28 day sum far less than it lifts a three
day sum, so sigma will understate brief events. The absolute floors are what catch those, and the
panel will say the event passed floors rather than claiming a large anomaly. That is the honest
behaviour, but it is a real limitation and it belongs in `caveats`.

---

## What it means for the baseline thresholds

This is the part most likely to be got wrong silently, because the constants keep working and only
their meaning changes.

```python
BASELINE_GOOD_MIN_YEARS        = 4     # unchanged
BASELINE_GOOD_MIN_DETECTIONS   = 20    # meaning changes, value stays
BASELINE_SPARSE_MIN_YEARS      = 3     # unchanged
BASELINE_SPARSE_MIN_DETECTIONS = 5     # meaning changes, value stays
BASELINE_STD_LOG_FLOOR         = 0.25  # revisit after measuring
SIGMA_CAP                      = 10.0  # unchanged
```

**`years_observed` is unaffected.** It still means "how many of the five window years had any detection
in this key", and 4 of 5 is still where a standard deviation over yearly aggregates stops being
dominated by one outlier year.

**`detections_total` keeps its value almost by luck, and the reasoning must be rewritten.** Today it
means "total detections in this `(cell, month)` across five years", which spans about 5 x 30.4 = 152
days. Under Option B it means "total detections in the five trailing 28 day windows for this
`(cell, week)`", which spans 5 x 28 = 140 days. That is 92 percent of the old span, so the old
threshold of 20 becomes an effective 18.4 on the previous scale. **Keeping 20 is therefore slightly
stricter than before, which is the safe direction**: it fails toward `insufficient`, meaning unscored
and honestly labelled, rather than toward a confident number the data cannot support.

So: **keep 20 and 5, and rewrite the comment** to say the span is 140 days rather than "roughly 4 per
year" of a month. Do not leave the old rationale next to the unchanged number, because the next reader
will reasonably assume it was checked and it was not.

**`BASELINE_STD_LOG_FLOOR` must be re measured.** 0.25 was chosen against the spread of monthly
aggregates. The spread of overlapping 28 day totals is not the same distribution, and because adjacent
windows share 21 days, the year to year variance at a fixed week may be lower than the month to month
variance was. **A floor that is too high silently suppresses real anomalies**, since it is the
denominator. Measure the distribution of `std_log` in the notebook and set the floor from it, rather
than carrying 0.25 across on the assumption that it transfers.

**Rename the artifact.** `thermal_h3r5_monthly.parquet` would be actively misleading. Use
`thermal_h3r5_week28d.parquet`, and bump `baseline_version` from `firms_noaa20_2021_2025` to
`firms_noaa20_2021_2025_week28d`, so any event scored under the old scheme is visibly not comparable.

---

## What is NOT blocked by this decision

**The FIRMS archive request.** The archive is raw detections; the keying choice only matters when the
notebook aggregates them. The download is asynchronous, emailed, and the slowest single item in the
project. **Submit it first, before this decision is made.** Confirmed as a ruling on 2026-11-06.

Also unblocked: the FIRMS ingest module, clustering, the registry and cross run matching, the emit
layer, and all frontend work.

**Blocked until this is settled:** the Tier 0 notebook's aggregation step, `score.py`, and the final
values of the grading constants.

---

## The decision

- [ ] **Option B** (recommended): `(h3_r5, week_of_year)`, trailing 28 day totals, unscorable rows
      dropped, parquet sharded
- [ ] Option C: `(h3_r5, period_of_year)`, 13 periods of 28 days
- [ ] Option A: calendar months, month to date (assessed and not recommended)
- [ ] Something else

Record the choice here and in `DETECTION_SPEC.md` sections 2 and 4 on the same day it is made, and
rewrite the section 2 procedure, the filename and the threshold rationale to match. Specification
drift between these two documents is exactly what makes a project like this unmanageable three weeks
in.
