# ROADMAP

> **TerraView24** : *Damage done by humans, measured against the norm*
>
> Part of the TerraView24 doc set. See `ARCHITECTURE.md` for the system overview.

Phases 1 and 2 are the project. Phase 3 is the portfolio piece. Phase 4 may not ship, and that is acceptable.

**The governing rule: four well validated detectors beat twelve that all fire noise.** A reviewer will test the weakest pin, not the strongest. Depth over breadth at every decision point.

---

## Phase 0: Verification, scaffold and trigger

Short, unglamorous, and skipping it will cost a week later. It now has three parts, because the first build showed the trigger layer needs proving as hard as the data path does.

### 0a. Names and sources

- [ ] **Step 0, the name.** Add `terraview24.vercel.app` to a Vercel project and confirm it is assigned, and confirm the GitHub repo name is free. If either is taken, choose the name that is free on both, then use it for the display title, repo, package, Vercel project and host. Do this before writing any code. See `ARCHITECTURE.md` section 10.
- [ ] Re verify the keyless endpoints in `DATA_SOURCES.md` with live requests (cheap, minutes). Update the verification date. Report only what differs from the file. If nothing differs, continue without waiting.
- [ ] Settle the unresolved items that need a key in hand: FIRMS `DAY_RANGE` ceiling (documented as 1 to 5, example uses 7). Needs human step 7, which is why that step moved into Phase 0.

### 0b. Scaffold, data branch and page

- [ ] Repo scaffold per `ARCHITECTURE.md` section 3, including `.gitattributes` forcing LF and `fixtures/`.
- [ ] Orphan `data` branch, built with git plumbing so the working tree is untouched, and pushed **before** any workflow first runs.
- [ ] A `vercel.json` committed onto the `data` branch with `git.deploymentEnabled: false`. Verify by observation that a write to `data` produces **no** Vercel deployment.
- [ ] `heartbeat.yml` writing `heartbeat.json` per `DATA_CONTRACTS.md`, and a static Vercel page that reads it and reports its own state honestly (section 0c exit wording).
- [ ] `actionlint` clean on every workflow, as a local check and as `lint-workflows.yml`. Look at the Actions tab after the first push.
- [ ] Concurrency group `data-branch-write` with `cancel-in-progress: false`. Pin `ubuntu-24.04` and `actions/checkout@v5`.
- [ ] Ingest workflows ship inert behind `PIPELINE_ENABLED` plus one variable per family.

### 0c. Trigger layer

- [ ] Build `infra/trigger-worker/` per `ARCHITECTURE.md` section 1a, with its tests and a README written for the human who deploys it.
- [ ] Every workflow gains `workflow_dispatch` with a `source` input. All keep `schedule` as fallback.
- [ ] Measure the lag from the dispatch POST to the run's `created_at`, three times, and record it.
- [ ] The page shows "Run" (never "Scheduled run"), the last trigger, the derived unassisted write count, and a staleness message driven by `stale_after_minutes`.

**Exit criteria:** a number changes on a deployed page because a job wrote it with **no human involved**. A write whose `writes_by_trigger` counts as `schedule` or `external_timer` satisfies it. A manual dispatch does not. The page flips to its pass state by itself when the derived count first exceeds zero.

**Stopping rule for any timing diagnosis:** time based, not window based. Do not call a scheduler fault before roughly 10 hours of silence. Change one thing at a time, observe, then the next.

### Human actions in Phase 0, in this order

The agent cannot do these. It lists them up front, with exact instructions, as one checklist.

> **The authoritative version of this list, with exact commands, click paths, what to observe and what
> to send back, is `PHASE_0_HUMAN_CHECKLIST.md`.** Keep the two in step. Status as of 2026-11-06:
> step 0 settled (the name is `terraview24`, because `terraview.vercel.app` was taken), steps 1 and 2
> done by the agent over an already authenticated `gh`, and one step added below that this list
> originally missed.

1. Confirm the name is free (step 0 above) and create the empty public GitHub repo under `dhairyabhosale`.
2. **Branch protection on `main` first**, before any token exists: Settings, Rules, Rulesets. Block force pushes, require linear history, and target `main` only.
2a. **Push `main` before `data`.** On an **empty** repository GitHub makes the first branch pushed
   the default branch. `data` was pushed first, per the rule in 0b that it must exist before any
   workflow runs, and GitHub duly made `data` the default. The `main` ruleset targets
   `~DEFAULT_BRANCH`, so it silently moved with it: `data` became protected and `main` became
   unprotected, which is the exact inverse of the intent. Fixed with
   `gh api --method PATCH /repos/OWNER/REPO -f default_branch=main`, then verified per branch with
   `gh api /repos/OWNER/REPO/rules/branches/main`. Either push `main` first, or set the default
   branch explicitly straight after the first push. Measured 2026-11-06.
3. Vercel: install the Vercel GitHub App for this repo only (Project Settings, Git), and set `VITE_DATA_OWNER` and `VITE_DATA_REPO` environment variables. Deployment Protection may put sign in pages on team aliases, so share only the production host.
4. Create the fine grained token: this repo only, **Actions: write**, 90 day expiry. Put the expiry date in a calendar before leaving the page.
5. Cloudflare account (free). From `infra/trigger-worker/`: `wrangler login`, `wrangler secret put GITHUB_TOKEN`, `wrangler deploy`. Confirm the output shows the cron trigger and no `workers.dev` address.
6. Watch three consecutive Worker triggered writes land, with `dispatch_lag_seconds` in the expected band, before trusting it.
7. **FIRMS MAP_KEY now, not later.** 0a above requires the `DAY_RANGE` ceiling to be settled, which
   is impossible without a key, so this one credential belongs to Phase 0 even though the rest do not.
   Self service and immediate. The other secrets from `DATA_SOURCES.md` follow when their phases begin.
   The VIIRS Nightfire licence is a signature with a turnaround time, so start it early.

---

## Phase 1: Thermal, end to end

One family, one ingestion path, the full lifecycle. This is the hardest phase and the most important. **Arm one family only**: `PIPELINE_ENABLED` plus `ENABLE_THERMAL`.

### Pipeline
- [ ] FIRMS ingestion on **NOAA-20** (NOAA-21 and MODIS for corroboration), normalised records, retry and backoff.
- [ ] **Tier 0 baseline notebook.** NOAA-20, calendar years 2021 to 2025, closed window, to `(h3_r5, month)` norms. Zero inflation, `log1p` before the statistics, the four value `baseline_quality` grading and its named constants per `DETECTION_SPEC` section 2. **Start the archive request first.** It is asynchronous, emailed, and the slowest thing in the project. Build the scoring path against it while it runs.
- [ ] Resolve open issue D1 (unit of comparison, `DETECTION_SPEC` section 4) with the human before `score.py` is written.
- [ ] DBSCAN clustering over scaled space and time. Tune the time scaling constant against known multi day fires.
- [ ] Sigma scoring against baseline, `SUSPECTED` gate, including the unscored path.
- [ ] Registry with cross run event matching and the frozen `event_id`.
- [ ] Corroboration with typed independence, and the MODIS degraded mode defined in the same commit.
- [ ] Emit `live.json`, `detail/*.json`, `meta.json`.

### Frontend
- [ ] Steps 1 through 6 of `INTERACTION_SPEC` section 12, built against fixtures, including the awkward cases listed in `DATA_CONTRACTS.md`.
- [ ] Swap fixtures for real `data` branch payloads.
- [ ] Freshness chrome (`INTERACTION_SPEC` section 13): data age, staleness and degraded corroboration in plain words.

**Exit criteria:** a real fire detected by a triggered job in the last 6 hours, clustered, scored against a 5 year baseline, promoted to `CORROBORATED`, rendered as a pin on a deployed globe, clickable, with the full open and close choreography and a panel showing its real sigma score, its `baseline_quality` and its `corroboration_type`. The end to end latency from satellite acquisition to page render is **measured and shown on the page**.

That single working path is already a complete and defensible project. Everything after is extension.

> **Do not start Phase 3 before Phase 1 exits.** The `UNREPORTED` layer is the most interesting part and the temptation to jump is strong. It is also meaningless without a validated baseline underneath it.

---

## Phase 2: Classification and forest loss

### Thermal classifier
- [ ] VIIRS Nightfire labels for `gas_flaring`. The licence is a signed agreement, so **start it during Phase 1**.
- [ ] Land cover plus seasonal windows for `crop_residue_burning`. North India post monsoon and post harvest are dense, well documented label sources.
- [ ] Fire agency perimeters for `forest_fire` where available.
- [ ] Gradient boosting, held out evaluation, confusion matrix.

This classifier is the data science centrepiece. It is far more impressive than ten unrelated feeds, and `gas_flaring` is what makes it a real problem rather than a trivial two class split.

### Forest loss family
- [ ] GLAD and RADD ingestion, weekly workflow. Pin the dataset version explicitly, because a reprocessing silently rewrites history.
- [ ] HDBSCAN clustering, shape feature extraction.
- [ ] Forest loss baseline.
- [ ] WDPA spatial join, from the bulk download.
- [ ] Family B classifier: `deforestation`, `mining_activity`, `urban_expansion_protected`.

### Validation
- [ ] `notebooks/03_validate_detections.ipynb`, all six sections of `DETECTION_SPEC` section 7.

**Exit criteria:** six event types live, both classifiers evaluated, confusion matrices published in the repo.

---

## Phase 3: Confirmation, the unreported layer, and the species join

This is where the project becomes a portfolio piece rather than a competent pipeline.

- [ ] GDELT confirmation by **bulk GKG ingest with a local relevance filter**, as its own workflow. The filter is tested code, `query_strategy_version` is stamped on every determination, and ingest coverage is recorded so `UNREPORTED` is only asserted over an observed window.
- [ ] `CONFIRMED` stage, article sets attached to events.
- [ ] **`UNREPORTED` stage.** Distinct rendering. The headline.
- [ ] Coverage bias analysis: `CONFIRMED` versus `UNREPORTED` split by region and income group. **This is a genuine finding and belongs in the write up.**
- [ ] IUCN species ranges as a reference layer with its own toggle and visual language (API v4, Bearer token, polygons from the spatial data download).
- [ ] Spatial join: detections intersecting endangered species ranges.
- [ ] `INTERACTION_SPEC` section 9: related pins stay lit, species polygon stays visible behind the open panel.
- [ ] OpenAQ ingestion (v3), `air_quality_exceedance`, and satellite to ground cross validation.
- [ ] Global Fishing Watch, `illegal_fishing` via "AIS off" events from the Insights API inside marine protected areas. Cap request volume in code, since breaches are hard blocks of 24 hours or 30 days.

**Exit criteria:** the globe shows a map of environmental damage that satellites detected and media did not, with the species range intersection visible in a single frame.

---

## Phase 4: Heavy imagery processing

The heaviest phase. Deferred because of cost, **not dropped.** Ground rule 9 applies: nothing here leaves the plan without a demonstrated blocker and an explicit decision.

- [ ] Sentinel-5P plume surfaces, via **Microsoft Planetary Computer** (keyless STAC and signing, collection `sentinel-5p-l2-netcdf`). This is no longer blocked by auth, so deferring it is a sequencing choice under rule 7. Copernicus Data Space is the documented fallback, Earth Engine second choice.
- [ ] `water_contamination` via Sentinel-2/3 indices. Thematically excellent, practically hard: separating pollution from algal blooms, rainfall sediment and seasonal variation is the whole difficulty.
- [ ] Oil spill detection from Sentinel-1.
- [ ] Timeline scrubber for historical replay.

### Family E: topological change

Two subtypes sharing one NDWI differencing implementation. Build the shared water mask code once, then branch.

- [ ] **`river_course_change`** first. JRC Global Surface Water (keyless on Planetary Computer as `jrc-gsw`, with occurrence, recurrence, seasonality and transitions assets) gives a ready made multi decade baseline, so this is the cheapest entry point into imagery work and it validates the shared pipeline. Detect the dam signature as a pair: new permanent water upstream, lost flow downstream.
- [ ] **`coastal_erosion`** second, reusing the same water mask code against a coastline. **Tide normalisation is mandatory**, not optional; without it the detector measures tide state, not erosion. Be conservative on human attribution, since natural drivers are strong here. **Decision needed before this starts:** the Global Coastal Transect System (Deltares and TU Delft, 11 million plus transects, `coastpy`) or CoastSat (1984 to 2024, FES2022 tide model already integrated). Aqua Monitor is legacy and USGS shoreline change is US only. Details in `DATA_SOURCES.md`.

Earth Engine is now second choice behind Planetary Computer: still free for noncommercial use, but gated behind a mandatory Cloud project, a reviewed questionnaire and quota tiers (effective 2026-04-27). Keep it in reserve for server side reductions over long time series.

**Assessed and cut:** `land_subsidence` (InSAR time series, not viable at zero budget, and the only free pre processed source covers Europe only) and `excavation_terrain_change` (its implementable form duplicates `mining_activity`). Excavation intent is preserved as a `bare_earth_expansion_rate` feature in the Family B classifier. Full reasoning in `ARCHITECTURE.md` section 4.

---

## Timeline shaping

**If you have roughly one month:** Phase 0 and Phase 1 only, thermal family alone, no classifier. Ship a globe that detects statistically anomalous fire activity against a real baseline. That is a genuine project and it will finish. The first build spent most of its first day on Phase 0, so budget for that.

**If you have a semester:** Phases 0 through 3. This is the realistic target for the full concept.

Phase 4 is a stretch under any schedule.

---

## What to say about it

When presenting, lead with the `UNREPORTED` layer and the coverage bias finding, not with the globe. The globe is how the finding is delivered; it is not the finding.

Be explicit about the claim discipline from `ARCHITECTURE` section 5, and show the confusion matrix including where the classifier fails. Being open about limitations is worth more than a clean accuracy number, and it is what distinguishes this from a dashboard with nice graphics. The measured scheduler delivery table in `ARCHITECTURE.md` section 1a is itself a portfolio artifact: a real constraint, measured, with a design that follows from it.
