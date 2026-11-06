# Tier 0 baselines: provenance and procurement notes

> **TerraView24** : *Damage done by humans, measured against the norm*
>
> What these files are, where the raw data came from, and what was verified
> about it. Specification in `docs/DETECTION_SPEC.md` section 2.

These artifacts are **inputs to CI, never outputs of it.** They are built by
hand from the notebooks, committed, and regenerated perhaps twice a year.
Nothing in `.github/workflows/` may write here.

---

## Sensor and window

**VIIRS NOAA-20 (JPSS-1) only, calendar years 2021 to 2025, a closed window.**

A closed window is reproducible: it does not move as new data lands, so a sigma
computed today and the same sigma recomputed in March agree.

### Why Suomi NPP is excluded

NASA stopped producing new S-NPP products on 2026-11-02, so its archive is
closed. A sigma score is a statement about one instrument's normal behaviour.
Blending two archives would let any residual calibration difference enter every
score as an unknown constant, and the pipeline could no longer say which part of
a 4.2 sigma reading was fire and which was instrument. Doing it properly means
deriving a cross sensor calibration from the 2018 to 2026 overlap, which is a
research project and is unnecessary when NOAA-20 alone clears the 5 year
minimum (its archive starts 2018-04-01, giving 8.6 years).

**What is lost, stated plainly:** cells whose fire regime changed before 2021,
and a shorter trend window than MODIS could offer.

NOAA-21 has only 3.7 years and is a corroborating sensor only. MODIS Terra and
Aqua are the independent cross check, with the retirement caveat in
`ARCHITECTURE.md` section 5a.

---

## Raw archive procurement

Requested through the asynchronous FIRMS archive download service at
`https://firms.modaps.eosdis.nasa.gov/download/`, which is manual by design and
unusable from CI.

### Requests

| Year | Request id | Requested (UTC) | Delivered | Zip | CSV | Rows | Status |
|---|---|---|---|---|---|---|---|
| 2021 | 839559 | 2026-11-06 15:29:29 | 2026-11-06 ~15:35 | 346.1 MB | 1,553.5 MB | **20,157,242** | **verified complete** |
| 2022 | | | | | | | not yet requested |
| 2023 | | | | | | | not yet requested |
| 2024 | | | | | | | not yet requested |
| 2025 | | | | | | | not yet requested |

**Settings used, and to be reused for every year:** global extent
`-180,-90,180,90`, source **VIIRS NOAA-20 (JPSS-1)**, format **CSV**, one
calendar year per request.

### Turnaround, measured

About **5 minutes** from submission to the file being generated, which is far
faster than the "slowest thing in the project" this was budgeted as.

Derived as follows, since no single source states it directly:

| Evidence | Value |
|---|---|
| Request time, from NASA's confirmation email | 2026-11-06 15:29:29 |
| CSV timestamp inside the zip | 2026-11-06 10:34:26, no timezone recorded |
| Download email received | about 15:35 UTC (21:05 IST) |
| File written locally | 15:40:48 UTC |

Zip entries store local time with no timezone. Reading the CSV timestamp as US
Eastern (EST, UTC-5 in November) gives **15:34:26 UTC**, which sits neatly
between the 15:29:29 request and the roughly 15:35 email. That is an inference
from a consistent fit, not a stated fact, but no other offset places the file
between the request and its own delivery email.

**So: generation about 4 minutes 57 seconds, email within a minute of that.**
Plan the remaining four years as minutes of waiting, not days. Re check this on
the next request before relying on it.

---

## What was verified about the 2021 delivery

Read by streaming the member straight out of the zip, without extracting.

| Check | Result |
|---|---|
| Rows | 20,157,242, zero malformed lines |
| Date range | 2021-01-01 to 2021-12-31 |
| Distinct days | **365 of 365. No missing days** |
| Thin days | **none** below 20 percent of the 47,944 median |
| Spatial extent | lat -88.48 to 81.92, lon -179.97 to 179.99. Global |
| `satellite` | `N20`, 100 percent |
| `instrument` | `VIIRS`, 100 percent |
| `version` | **`2`, 100 percent, meaning Collection 2 Standard Processing** |
| `confidence` | `n` 83.56, `l` 11.31, `h` 5.13 percent. Categorical, so VIIRS not MODIS |
| `daynight` | `D` 73.02, `N` 26.98 percent |
| `type` | `0` 92.87, `2` 6.32, `3` 0.72, `1` 0.08 percent |
| `frp` | 0.0 to 3245.11 MW, mean 9.93, zero unparseable |

### It is science quality, and the readme that says otherwise is wrong

The FIRMS archive readme states that standard quality data "is not yet
available from FIRMS for NOAA-20 and NOAA-21". **That is stale.** NASA defines
the `version` field as collection plus processing source, where a suffix means
real time and a bare collection number means Standard Processing. This file is
`version = 2` throughout, and a live API request for `VIIRS_NOAA20_SP` on a 2021
date returns rows with the same `version = 2`, while the NRT source returns
`2.0NRT` and nothing at all for 2021.

So **the baseline is SP, the live feed is NRT**, exactly as
`DETECTION_SPEC.md` section 2 assumes. That discontinuity is real and must stay
on every event's `caveats`, but it is the intended one rather than an
unexamined one.

---

## Two schema traps for whoever writes the notebook

**1. The archive and the API use different column names.** Positionally
identical for the first 14 fields, but index 2 is `brightness` in the archive
and `bright_ti4` in the API, and index 11 is `bright_t31` against `bright_ti5`.
The archive borrows MODIS channel names for the VIIRS I4 and I5 bands.
Normalise at ingest; never let either spelling reach the detection code.

**2. `type` exists only in the archive.** The live NRT feed has no such column.

**Therefore: do not filter the baseline by `type`.** A baseline filtered on a
field the live feed lacks would be a different population from the thing scored
against it, and the mismatch would be invisible in the output. Build the
baseline over all types, exactly as the live feed arrives.

### `type` is still valuable, as labels rather than as a filter

`type = 2`, "other static land source", covers **1,274,702 detections in 2021
alone**. Stationary, persistent, non vegetation heat sources are very largely
gas flares and industrial thermal, which are two of the four Family A classes.

That matters right now because the VIIRS Nightfire licence, the intended label
source for `gas_flaring`, was signed on 2026-11-06 and is **not approved**, with
no known start or expiry. This gives a free, already downloaded, independent
proxy label set that needs no licence. Treat it as a fallback for Phase 2 rather
than a replacement: Nightfire is purpose built for flaring and `type` is an
inferred attribute, so they are not equivalent in quality.

---

## Where the raw data lives

**Outside the repository, and it must stay there.**

```
D:\DB PC\Project\DL_FIRE_J1V-C2_839559.zip     346 MB, 2021
D:\DB PC\Project\Project-TerraWatch\           the repo, a sibling
```

The raw archives are a parent directory above the repository root, so git
cannot see them at any depth. That is a stronger guarantee than `.gitignore`,
which only protects against paths inside the working tree.

If raw data ever has to sit inside the repo, put it in `raw/` and add an
ignore rule first, in the same commit that creates the directory. A 346 MB zip
committed by accident cannot be removed from history without a force push, and
`main` blocks force pushes by ruleset, so the recovery would be genuinely
painful.
