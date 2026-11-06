# ARCHITECTURE

> **TerraView24** : *Damage done by humans, measured against the norm*
>
> One name everywhere: display title, repo, package, Vercel project and production host are all `terraview24`. The rule and the reason are in section 10.

A 3D globe that surfaces human caused environmental events, detected statistically from satellite and sensor data, then corroborated and confirmed against independent sources before any narrative claim is made.

The core discipline of this project: **the globe never asserts more than the pipeline can defend.** A pin is a statistical object with a provenance chain, not a headline. The same discipline applies to the page's claims about itself: it states its own data age, and it does not use the words "real time" or "live" for anything it has not measured.

Items marked **[measured, attempt 1]** were observed directly during the first build in November 2026. Treat them as strong evidence, and re-measure the cheap ones in Phase 0.

---

## 1. System shape

There is no application server and no database. The system is three decoupled tiers connected only by static JSON files, plus one small trigger component (section 1a) that exists because GitHub's own scheduler cannot be relied on.

```
┌──────────────────────────────────────────────────────────────┐
│  TIER 0  OFFLINE BASELINE (run once, by hand, committed)     │
│  Multi year historical archives  ->  per cell seasonal norms │
│  Output: pipeline/baselines/*.parquet  (never recomputed     │
│  by CI; regenerated manually, maybe twice a year)            │
└──────────────────────────────────────────────────────────────┘
                              │  committed input
                              v
┌──────────────────────────────────────────────────────────────┐
│  TRIGGER  (section 1a)                                       │
│  Cloudflare Worker, one cron every 5 min, decides what is    │
│  due and calls workflow_dispatch. GitHub `schedule` stays    │
│  in every workflow as a slow fallback.                       │
└──────────────────────────────────────────────────────────────┘
                              │  starts runs
                              v
┌──────────────────────────────────────────────────────────────┐
│  TIER 1  PIPELINE (GitHub Actions, free tier)                │
│  ingest -> cluster -> score vs baseline -> classify ->       │
│  promote state -> confirm vs news -> emit JSON               │
│  Writes to the orphan `data` branch. Never touches `main`.   │
└──────────────────────────────────────────────────────────────┘
                              │  raw.githubusercontent
                              v
┌──────────────────────────────────────────────────────────────┐
│  TIER 2  STATIC FRONTEND (Vercel)                            │
│  Vite + React + CesiumJS + GSAP. Fetches JSON at runtime.    │
│  Zero secrets in the bundle. Pure static deploy.             │
└──────────────────────────────────────────────────────────────┘
```

### Why this shape

Anomaly detection needs a multi year baseline and API keys. Neither can live in a browser. GitHub Actions supplies a runtime with secret storage at no cost, and the `data` branch supplies a CDN backed read path. The frontend stays a pure static deploy, which is what Vercel's free tier is good at.

**Rules that keep this working:**

- The pipeline never writes to `main`. It writes to an orphan branch named `data`, so pipeline commits never pollute source history. Pushes to `data` must also **not** trigger Vercel builds, which they do by default. See section 9.
- The frontend fetches `data` branch JSON at runtime. It does **not** import it at build time. A data refresh must not require a redeploy.
- Tier 0 artifacts are committed to `main` under `pipeline/baselines/`. They are large but static. They are inputs to CI, never outputs of it.
- **Every time window keys off data timestamps, never run times.** A run can start hours late or not at all (section 1a). "The last 15 minutes" must mean the last 15 minutes of data, not of wall clock since the previous run.

---

## 1a. Trigger layer

### What was measured [measured, attempt 1]

GitHub's `schedule` event is best effort. It was measured against a control account and against this project.

| Observation | Result |
|---|---|
| Control: a profile repo with two 12 hour crons, 68.5 days | 272 of 274 windows produced a run (99.3 percent). Delay: min 2.86 h, **median 4.68 h**, max 9.36 h |
| Where the delay sits | `run_started_at` equalled `created_at` on every sampled run. GitHub creates the run late. It is not a runner queue, so nothing in a repo can shorten it |
| This project, `7,37 * * * *` | 19 windows, 1 run. **5.3 percent delivery** |
| This project, `*/15 * * * *` | 51 windows, 2 runs. **3.9 percent delivery** |
| This project, `0 */6 * * *` | 2 windows, 1 run, created 5.27 h late |
| Pattern | Roughly one scheduled run per 4 to 5 hours, whatever the cron expression says. High frequency crons are not delayed, they are mostly not delivered |
| Externally triggered `repository_dispatch` | POST to run `created_at`: 2.4 s, 3.8 s, 2.9 s. POST to the commit on `data`: 8 to 13 s |
| Configuration | Actions enabled, all workflows `active`, public repo, default branch correct. Nothing was misconfigured, and no amount of re registration changed it |

**The lesson that cost hours:** a quiet 90 minute observation window meant nothing against a 4.7 hour median. Any scheduler diagnosis uses a **time based** stopping rule: do not call it a fault before roughly 10 hours of silence, which is past the worst observed delay. Do not change one cron expression after another hoping for a different result.

### The design

An external timer calls `workflow_dispatch`, which is the path measured as fast. GitHub `schedule` stays in every workflow as a fallback, because a late run beats no run.

- **Component:** one Cloudflare Worker in `infra/trigger-worker/`, free tier. It has **one** cron trigger every 5 minutes and decides in code which of the project's cadences are due. The schedule is therefore versioned, testable code and not six dashboard entries.
- **Endpoint:** `POST /repos/{owner}/{repo}/actions/workflows/{workflow_file}/dispatches` with a `ref` and an `inputs` object. One POST per due workflow file. Each workflow declares `on: workflow_dispatch` with a `source` input.
- **Why `workflow_dispatch` and not `repository_dispatch`:** per GitHub's documentation, `workflow_dispatch` needs only **Actions: write** on a fine grained token, while `repository_dispatch` needs **Contents: write**, which also permits pushing code. Prefer the narrower token. Re measure the POST to `created_at` lag in Phase 0 to confirm it matches the `repository_dispatch` numbers above.
- **No public button.** The Worker's `fetch` handler must not dispatch anything, and `workers_dev = false` so no public URL exists. A URL that can fire the pipeline is a public button for running it.
- **Tests, no network:** cron parsing, the day of month and day of week union rule, Sunday as 0, and an alignment test that reads the workflow files and asserts every cadence the Worker can fire has a matching `workflow_dispatch` workflow. Include one test that asserts a guard fails where it should, so the suite cannot pass vacuously.
- **Gating:** the Worker's schedule lists only workflows that are currently armed. Do not create skipped runs every few minutes for pipelines that are off.

### The token

| Property | Value |
|---|---|
| Type | Fine grained personal access token |
| Repository access | This repo only |
| Permission | Actions: write, nothing else |
| Expiry | 90 days, with a calendar reminder set **before leaving the token page** |
| Storage | Worker secret (`wrangler secret put GITHUB_TOKEN`). Never in the repo, never in the client bundle |
| Failure mode | On expiry every dispatch returns 401 and the pipeline silently falls back to one run per 4 to 5 hours, which looks like a slightly stale page, not an outage. See the staleness check below |

Add a branch protection ruleset on `main` that blocks force pushes and requires linear history. It must not apply to `data`, which the pipeline writes constantly. Create the ruleset **before** the token exists.

### Honesty and monitoring

- GitHub cannot tell the Worker from a person running `curl`, since the sender is the same token owner. `dispatch_source` is therefore published as a **claim**. The checkable part is `dispatch_scheduled_for` against the run's actual start, published as `dispatch_lag_seconds`. See `DATA_CONTRACTS.md`.
- **Staleness check on the page.** The page compares the age of the last write against the cadence the payload declares and says plainly when the data is older than it should be. A calendar reminder is not a control. It is a hope.
- **Disclosure.** The project has one credential and one always on component. The honest claim is "no application server and no database", not "zero servers". Say so in the README.
- **Simpler fallback, acceptable.** If the external timer is not wanted, drop the Worker and token entirely and accept GitHub's cadence of roughly one run per 4 to 5 hours. The page must then state that cadence, and "real time" stays off the page, which it should be anyway. Decide this once, at Phase 0, with the human.

---

## 2. Stack

### Pipeline (Python 3.11)

| Concern | Choice | Note |
|---|---|---|
| Dataframes | `pandas`, `pyarrow` | Parquet for baselines, JSON for emitted output |
| Geometry | `shapely`, `geopandas` | Spatial joins, protected area and species range intersection |
| Spatial index | `scipy.spatial.cKDTree` | Required; naive pairwise clustering will not finish |
| Clustering | `scikit-learn` DBSCAN / HDBSCAN | Space and time radius, see DETECTION_SPEC |
| Classification | `scikit-learn` gradient boosting | Thermal and forest loss family classifiers |
| HTTP | `httpx` with retry and backoff | All sources are flaky; assume failure |
| Workflow lint | `actionlint` | Local pre commit and a CI job. Parsing YAML is not validating it (section 9) |

### Trigger

| Concern | Choice | Note |
|---|---|---|
| Timer | Cloudflare Worker, cron trigger | Free tier, `wrangler` CLI, `workers_dev = false` |
| Tests | Plain Node or Python, no network | See section 1a |

### Frontend

| Concern | Choice | Note |
|---|---|---|
| Build | Vite + TypeScript | Run `tsc` and `vite build` both. `tsc` catches config errors `vite build` passes over |
| Shell | React 18 | React owns the DOM panel only, never the canvas |
| Globe | **CesiumJS** (raw, not `resium`) | Camera control needs direct imperative access |
| Animation | **GSAP** timelines | Single timeline per transition, see INTERACTION_SPEC |
| State | Zustand | Holds the interaction state machine and loaded event sets |
| Imagery | OSM or Cesium's token free providers | Avoid an ion token dependency |

**Why raw Cesium and not resium:** every transition in INTERACTION_SPEC manipulates `camera.flyTo`, `frustum.xOffset` and post process stages imperatively, on a GSAP timeline. A declarative wrapper fights this. React renders the panel and the chrome; Cesium owns the canvas and nothing in React re renders it.

---

## 3. Repository layout

```
terraview24/
├── .gitattributes                    # forces LF, see section 9
├── .gitignore
├── .env.example
├── README.md
├── requirements.txt
├── vercel.json                       # build config for main
├── .github/
│   └── workflows/
│       ├── heartbeat.yml             # Phase 0 proof, not gated
│       ├── lint-workflows.yml        # actionlint on any workflow change
│       ├── ingest-thermal.yml        # every 6h
│       ├── ingest-weekly.yml         # forest loss, weekly
│       ├── ingest-atmospheric.yml    # daily
│       ├── ingest-marine.yml         # daily
│       └── confirm.yml               # GDELT bulk GKG confirmation, own workflow
├── infra/
│   └── trigger-worker/               # Cloudflare Worker, tests, README for the human deploy
├── fixtures/                         # DATA_CONTRACTS fixtures, including the awkward cases
├── pipeline/
│   ├── version.py
│   ├── sources/                      # one module per API, returns normalised records
│   │   ├── firms.py
│   │   ├── gfw.py
│   │   ├── openaq.py
│   │   ├── gdelt.py                  # bulk GKG reader, not the DOC API
│   │   └── ...
│   ├── detect/
│   │   ├── constants.py              # every threshold as a named constant
│   │   ├── cluster.py                # DBSCAN over space + time
│   │   ├── score.py                  # sigma score against baseline
│   │   ├── classify_thermal.py
│   │   └── classify_forestloss.py
│   ├── enrich/
│   │   ├── spatial_join.py           # protected areas, species ranges
│   │   └── confirm.py                # local relevance filter over the GKG index
│   ├── state/
│   │   └── promote.py                # SUSPECTED -> CORROBORATED -> CONFIRMED / UNREPORTED
│   ├── emit/
│   │   ├── writer.py                 # produces the DATA_CONTRACTS payloads
│   │   ├── merge.py                  # rebuilds live.json and meta.json from per family files
│   │   └── push.py                   # fetch, rebase and retry push to the data branch
│   ├── baselines/                    # TIER 0 OUTPUT, committed, do not regenerate in CI
│   │   ├── README.md                 # window, sensor, why S-NPP is excluded
│   │   ├── thermal_h3r5_monthly.parquet
│   │   └── forestloss_h3r5_monthly.parquet
│   └── store/
│       └── registry.py               # reads/writes the per family event registry
├── notebooks/
│   ├── 01_build_thermal_baseline.ipynb
│   ├── 02_label_thermal_classes.ipynb
│   └── 03_validate_detections.ipynb
├── web/
│   ├── src/
│   │   ├── globe/
│   │   │   ├── viewer.ts             # Cesium init, imagery, lighting
│   │   │   ├── pins.ts               # BillboardCollection, not Entities
│   │   │   ├── layers.ts             # polygons, heatmaps, surface fields
│   │   │   ├── camera.ts             # flyTo, frustum offset, return-to-idle
│   │   │   ├── rotation.ts           # idle spin + 3s resume timer
│   │   │   └── picking.ts            # hemisphere gate + pick handler
│   │   ├── state/
│   │   │   └── machine.ts            # IDLE / FLYING_IN / PANEL_OPEN / FLYING_OUT
│   │   ├── panel/                    # React infographic panel
│   │   ├── data/
│   │   │   ├── fetch.ts              # data branch client, cache notes
│   │   │   └── types.ts              # generated from DATA_CONTRACTS
│   │   └── main.tsx
│   └── public/
├── scripts/
│   └── get-actionlint.sh             # pins and downloads actionlint, used locally and in CI
└── docs/
    ├── AGENT_PROMPT.md
    ├── ARCHITECTURE.md
    ├── DATA_SOURCES.md
    ├── DETECTION_SPEC.md
    ├── DATA_CONTRACTS.md
    ├── INTERACTION_SPEC.md
    ├── ROADMAP.md
    └── PHASE_0_HUMAN_CHECKLIST.md
```

The `data` branch is an orphan. It carries `heartbeat.json`, the payloads from `DATA_CONTRACTS.md`, a README, and its own `vercel.json` (section 9).

---

## 4. Event taxonomy

Twelve event types in five pipeline families, plus one reference layer. Grouping by family is deliberate: types inside a family share ingestion, clustering and baseline code, and differ only in classifier output.

### Family A: Thermal (FIRMS / VIIRS)
1. `forest_fire`
2. `crop_residue_burning`
3. `gas_flaring` *(detection class only, see note)*

Backbone sensor is **VIIRS NOAA-20**. Suomi NPP stopped producing new products on 2026-11-02, so it is archive only and is excluded from the baseline (rationale in `DETECTION_SPEC.md` section 2).

### Family B: Forest loss (GLAD / RADD)
4. `deforestation`
5. `mining_activity`
6. `urban_expansion_protected`

### Family C: Atmospheric (Sentinel-5P + OpenAQ)
7. `air_quality_exceedance`
8. `pollution_plume` *(rendered as surface field, not a pin)*

### Family D: Independent single source
9. `illegal_fishing` (Global Fishing Watch AIS)
10. `water_contamination` (Sentinel-2/3 indices) **deferred, Phase 4**

### Family E: Topological change (Sentinel-2 water masks, Phase 4)

Two subtypes under a shared parent type `topological_change`. Both are **surface water boundary problems**, solved with the same NDWI thresholding and multi date differencing code. That shared method is why these two and not others.

11. `river_course_change` : channel migration and flow blockage from damming or diversion
12. `coastal_erosion` : shoreline retreat and advance

#### What was cut from this family, and why

Two subtypes were scoped out after assessment. Recorded here rather than silently dropped, per ground rule 9.

**`land_subsidence`: not implementable at zero budget.** It needs Sentinel-1 InSAR time series (PSInSAR or SBAS) over SLC products. That is the heaviest computation in the entire project by a wide margin, it will not run in a GitHub Actions free tier, and processing it offline is weeks of specialist work. The one free pre processed route, the European Ground Motion Service, covers Europe only, and a Europe only layer on a global globe is worse than no layer because it misrepresents where subsidence occurs.

This reverses an earlier recommendation. It was originally selected on the argument that it shared InSAR infrastructure with `excavation_terrain_change`. Once that subtype was also cut, the shared infrastructure argument collapsed and nothing was left supporting it.

**`excavation_terrain_change`: redundant, not impossible.** Its implementable form is Sentinel-2 bare earth spectral change detection, which is substantially what `mining_activity` in Family B already does from GLAD and RADD alerts. The version that would add something genuinely new, vertical elevation change from InSAR coherence loss, has the same cost problem as subsidence.

**Its intent is preserved**, not lost: `mining_activity` carries the excavation case. Add a `bare_earth_expansion_rate` feature to the Family B classifier from Sentinel-2, which captures excavation driven terrain change through the pipeline that already exists.

This leaves twelve types across five families.

### Reference layer (not detected, not a pin)
- `species_range`: IUCN Red List status, population trend, threats, conservation actions. Rendered as translucent polygons with its own visual language and its own toggle, so it is never mistaken for pipeline output.

**Note on `gas_flaring`:** it exists primarily to harden the Family A classifier. Flares are stationary, permanent and aseasonal, which forces the model to learn real discriminating features rather than trivially separating wildfire from crop burning. Keep it as a class even if it is deprioritised as a displayed headline event.

---

## 5. The four stage event lifecycle

This is the project's central claim mechanism. Implemented in `pipeline/state/promote.py`.

| Stage | Gate | Pin rendering | Claim made |
|---|---|---|---|
| `SUSPECTED` | Statistical only. Cluster exceeds regional seasonal baseline by >= 3 sigma, or passes the absolute floors where no baseline can score it. | Dim, pulsing, small. Point primitive, not an interactive billboard. | None. Displays the statistic only. |
| `CORROBORATED` | A second **independent** signal agrees. Independence is typed by `corroboration_type`: see section 5a. | Brighter, interactive billboard. | "Something real is here." |
| `CONFIRMED` | Scoped news matching, run locally over the GDELT bulk GKG index, returns matching coverage within the bbox and time window. | Full colour, full panel with sources. | Typed event with narrative. |
| `UNREPORTED` | Reached `CORROBORATED`, aged past the confirmation window, never matched coverage, and the news index covered the window. | Distinct colour. **This is the headline finding.** | "Satellites saw this. Media did not." |

`UNREPORTED` is the project's original contribution. A live map of environmental damage that was detected but never reported is a finding, not a visualisation of someone else's feed. Lead with it. ("Live" here is a description of the idea. The page itself states how old its data is.)

**Claim discipline.** A confirmed pin reads:

> VIIRS detected sustained anomalous thermal activity, 4.2 sigma above the regional October norm, corroborated across three passes. Matching coverage found.

It does **not** read "forest destruction here." The restraint is what makes a reviewer trust the rest of the system.

### 5a. Corroboration independence

NOAA-20 and NOAA-21 share an orbital plane, fly about 50 minutes apart, and run an identical instrument with a shared processing chain. Their agreement is persistence, not independence. Every corroboration carries a typed field:

| `corroboration_type` | Meaning |
|---|---|
| `independent_cross_sensor` | A genuinely different instrument agrees, for example MODIS Terra or Aqua |
| `adjacent_layer` | A different physical measurement agrees, for example an OpenAQ exceedance or a Family C anomaly over the same bbox |
| `same_plane_persistence` | NOAA-20 and NOAA-21 agreement, or repeated NOAA-20 passes |
| `single_sensor` | Nothing beyond the first sensor |

`CORROBORATED` requires `independent_cross_sensor` or `adjacent_layer`. The panel shows the type verbatim, never a bare sensor count.

**MODIS is ending.** NASA plans end of science operations for Terra around January to February 2027 and for Aqua between August 2026 and September 2027 (NASA pages disagree). No follow on exists in Terra's morning orbit. The fallback is defined now, in the same commit as the gate: when no MODIS data is arriving, the gate accepts `same_plane_persistence` with `pass_count >= 3`, sets `corroboration_degraded: true`, and the panel says that independent cross sensor checking is no longer available. The system states what it can no longer verify. It does not relabel weaker evidence as corroborated.

---

## 6. State persistence without a database

Events must survive across pipeline runs to be promoted through stages. There is no database, so the registry is a file on the `data` branch.

**One registry per family**, at `registry/<family>.json`, each holding that family's live events keyed
by a stable `event_id`. The split is required by section 9a: two workflows must never write the same
file, because the concurrency control is an optimistic git rebase and not a lock.

The id is `<family_prefix>_<h3_r5>_<first_detection_date>`, and **the `h3_r5` component is frozen at
first detection and never recomputed.** A spreading fire's centroid will cross an H3 cell boundary, and
a recomputed id would break the frontend's cache key. The current cell lives in a separate mutable
field, `h3_r5_current`, and the two are allowed to diverge. Each run, for its own family only:

1. Reads `registry/<family>.json` from the `data` branch.
2. Matches new clusters against existing registry entries by spatial and temporal overlap.
3. Appends new observations to matched events, creating new entries for unmatched clusters.
4. Re evaluates promotion gates for every live event.
5. Expires events past their type's TTL to `archive/YYYY-MM.json`.
6. Writes `registry/<family>.json` and its own `events/live.<family>.json` and `meta.<family>.json`.
7. Rebuilds the merged `events/live.json` and `meta.json` from every per family file present.
8. Pushes with fetch, rebase and retry (section 9a).

**Superseded, 2026-11-06.** This section previously said concurrency was not a concern because every
writing workflow shared one group, `data-branch-write`, with `cancel-in-progress: false`. That design
would silently drop dispatches, because a concurrency group holds only one pending run. **See section
9a for the behaviour and the replacement design:** per workflow groups, per family output files
including per family registries, and a fetch, rebase and retry push. Concurrency is controlled at the
git layer, not by a lock.

**Counters.** Keep one authoritative counter and derive every other count from it. Two stored counters that can disagree is a bug that already happened once. See `heartbeat.json` in `DATA_CONTRACTS.md`.

---

## 7. Frontend data loading

The frontend fetches these payload classes, described in full in `DATA_CONTRACTS.md`:

- `heartbeat.json`: when the last write happened and what caused it. Drives the staleness message.
- `events/live.json`: the interactive pin set. **Hard cap 3000 features.** Ranked by severity and recency.
- `layers/<name>.json`: surface fields and polygons (plumes, species ranges, protected areas).
- `events/detail/<event_id>.json`: lazy loaded full detail, fetched on pin click, not on page load.

**Read path facts [measured, attempt 1]:**

| | `raw.githubusercontent.com` | `cdn.jsdelivr.net` |
|---|---|---|
| `Cache-Control` | `max-age=300` | `max-age=604800, s-maxage=43200` |
| Browser cache | 5 minutes | **7 days** |
| Edge cache | 5 minutes | **12 hours** |

- **Use `raw`.** On jsDelivr a value written hourly would look dead for up to half a day.
- **Query string cache busting does not work on `raw`.** A never before requested `?t=` value still returned a cache `HIT`, so the edge keys on the path. Freshness comes only from `cache: 'no-store'`, which affects the browser and nothing else. **The edge floor is 300 seconds** and nothing bypasses it. Do not write a code comment implying otherwise.
- **Diagnosis order when a number will not move:** first ask whether it is simply not late yet (section 1a). Then check `origin/data` for a new commit. Then `curl` the raw URL. Then compare the browser against `curl`.
- **Latency is measured, then published.** The end to end figure from satellite acquisition to page render is measured once the pipeline runs and shown on the page. Satellite product lag dwarfs scheduling lag, and the page claims no latency until one exists.

**Performance rules, non negotiable:**

- Never render raw detections. Cluster in the pipeline. A globe that stutters reads as amateur no matter how good the model underneath is.
- Use `BillboardCollection`, not individual `Entity` objects. Entities are convenient and will not survive a few thousand pins.
- `SUSPECTED` tier renders as a `PointPrimitiveCollection` or heatmap. Only `CORROBORATED` and above become interactive billboards.
- Detail payloads are fetched on demand, never bundled into the initial load.

---

## 8. Secrets and cost

Every pipeline secret lives in GitHub repo secrets and is read only inside Actions. The trigger token lives only as a Cloudflare Worker secret. Nothing reaches the client bundle. If the frontend ever needs a key, the design is wrong.

Budget is zero. Every source in `DATA_SOURCES.md` has a free access tier.

**Correction, 2026-11-06: Actions minutes are not the constraint here.** Earlier text in this section
named GitHub Actions free minutes as the real budget limit. That is **false for a public repository**,
where Actions on standard GitHub hosted runners is unmetered. `terraview24` is public, so minutes are
free and no run budget is being consumed.

Keep runs short anyway, for three reasons that are actually true:

1. **Wall clock latency.** Every minute of runtime is a minute added to the satellite acquisition to
   page render figure that `meta.json` publishes. The page claims that number, so the number matters.
2. **The 6 hour job cap.** A single job is killed at 6 hours regardless of plan. A thermal run that
   creeps toward that is one bad day of API latency away from producing nothing.
3. **A private repo later.** If this repo is ever made private, metered minutes apply immediately and
   retroactively change the economics. Designing for short runs now means that switch is free.

Targets stay as `DATA_SOURCES.md` records them (thermal under 5 minutes, and so on), with dependency
caching. The other real constraint is unchanged: `data` branch size. Expire aggressively to
`archive/`, or the branch becomes a slow clone.

**Credentials on disk.** `vercel link` writes `.env.local` containing a `VERCEL_OIDC_TOKEN`. Confirm it is gitignored with `git check-ignore` and that no token string appears in any tracked file. The command also appends duplicate `.vercel` and `.env*` lines to `.gitignore` and can introduce CRLF line endings. Keep those entries as one commented block so a second `vercel link` does not stack another copy.

---

## 9. Platform behaviours, measured

Each of these cost real time in the first attempt. They are recorded here so nobody rediscovers them.

| Behaviour | Consequence | Rule |
|---|---|---|
| A YAML key with only a comment under it parses as null. `env:` followed by a comment is `env: null` | PyYAML accepts it, **GitHub Actions rejects it**. The workflow failed on every push with only "workflow file issue" | Run `actionlint`, not a YAML parser. It catches this exactly. Add it as a CI job that runs on any change under `.github/workflows` |
| An invalid workflow file cannot be scheduled | A cron on a broken file never registers, which muddies any scheduler diagnosis | Check the Actions tab after the **first** push, not only after deliberate runs |
| CRLF in a workflow file with a heredoc | Bash compares the terminator against `PY\r` and never finds the end. Fails opaquely on a runner you cannot inspect | `.gitattributes` forcing LF, and verify committed workflow files are CR free |
| Vercel builds **every** branch, including `data` | Every heartbeat write produced a failed build, about 96 per day at the Phase 1 cadence, burying real failures | Commit a `vercel.json` with `git.deploymentEnabled: false` **onto the `data` branch itself**. Vercel reads `vercel.json` from the branch being deployed, not the default branch. Verified by observation: the next write produced no deployment at all |
| **Re verified on this project 2026-11-06, by observation** | A pipeline write landed on `data` (commit `056979d`, `heartbeat.json` created). The deployment list was **unchanged**: still exactly the two production deployments that existed beforehand, and `vercel ls --meta githubCommitRef=data` returned **no deployments at all** | The `vercel.json` on the `data` branch works. Equally important, a push to `main` DID produce a deployment 36 seconds later, so the suppression is specific to `data` and has not disabled git integration wholesale. Both halves had to be checked: only one of them failing is silent |
| `actions/checkout@v4` targets the deprecated Node 20 | Annotation on every run | Use `actions/checkout@v5` |
| `ubuntu-latest` began migrating to Ubuntu 26 on 2026-10-19 | A scoring pipeline whose OS image moves underneath it is not reproducible | Pin `ubuntu-24.04`. Record the pin and review it before that image leaves support |
| A job level `if` that evaluates false provisions no runner | A gated workflow costs no minutes, though it still creates a skipped run record | Gate every ingest workflow with a master variable `PIPELINE_ENABLED` **and** one variable per family, for example `ENABLE_THERMAL`. Arm one family at a time |
| `actions/checkout` with `ref: data` fails if `data` does not exist | The first run fails | Push `data` before the first run |
| On an **empty** repo, the first branch pushed becomes the **default branch** | `data` was pushed first (correctly, per the rule above) and GitHub made it the default. The `main` ruleset targets `~DEFAULT_BRANCH`, so the protection silently followed: **`data` became protected and `main` became unprotected**, the exact inverse of the intent. Nothing errored | Push `main` first, or `PATCH /repos/{owner}/{repo} -f default_branch=main` straight after. Then verify per branch with `GET /repos/{o}/{r}/rules/branches/{branch}`, which must list three rules for `main` and an empty array for `data`. Measured 2026-11-06 |
| Vercel git integration needs the Vercel GitHub App installed on the repo | The CLI cannot do this. Without it, pushes to `main` do not deploy | Human step. Grant access to this repo only |
| **Re measured 2026-11-06: `vercel git connect` succeeded from the CLI** | The GitHub App was already installed account wide from earlier projects, so no browser step was needed. The first attempt's failure was the App not being authorized, not a CLI limitation | Try `vercel git connect --yes` first. Only fall back to the browser if it actually fails |
| **Vercel no longer allows a personal account as a deployment scope** | `vercel project ls --scope <user>` returns "You cannot set your Personal Account as the scope." The Phase 0 decision to prefer a Hobby scope over a team scope, taken to avoid Deployment Protection, is therefore not available | Use the team scope and verify the production host is public by observation. Measured 2026-11-06 |
| **Deployment Protection, measured on this project 2026-11-06** | Bare production host `terraview24.vercel.app` returned **`HTTP 200`** unauthenticated. The team scoped alias `terraview24-db-workplace.vercel.app` returned **`302`** to `vercel.com/sso-api`, and the immutable deployment URL also returned **`302`** | Confirms the existing rule: **share only the bare production host.** Protection covers alias and deployment URLs but not the production domain, so no setting needed changing |
| Vercel Deployment Protection | Team scoped alias hosts return 302 to sign in | Share only the production host. Check it in a private window |
| A TypeScript project reference cannot point at a composite project with `noEmit` | `tsc` fails where `vite build` passes | Run both |

A passing parse, a status read back from a settings page and a green build are not evidence that a fix worked. **After every fix, observe the effect it was meant to have**, and record the observation.

---

## 9a. Concurrency: one shared group would drop dispatches

Section 6 originally specified a single concurrency group, `data-branch-write`, with
`cancel-in-progress: false`, on every workflow that writes. That is wrong, and it is wrong in a way
that would have been extremely hard to diagnose.

**The platform behaviour:** GitHub holds **at most one pending run per concurrency group.** With
`cancel-in-progress: false`, a run that arrives while another is in progress waits as pending, which is
the intent. But if a third arrives while one is already pending, **the previously pending run is
cancelled**, not queued behind it. The group is a slot of depth one, not a queue.

**Why that is dangerous here rather than merely wasteful.** The external timer fires every 5 minutes.
Under one shared group, several armed workflows plus any overlap means dispatches get cancelled. A
cancelled pending run looks, from the outside, exactly like the scheduler flakiness that this document
spent hours measuring in section 1a. We would be re diagnosing a solved problem, with our own
architecture as the cause.

### The design

Decided 2026-11-06. Replaces the single shared group.

1. **Each workflow gets its own concurrency group**, keyed by workflow name, so a workflow only ever
   dedupes against itself. A thermal run never cancels a confirm run.
2. **Each family owns its own output files, including its own registry.** Two workflows never edit the
   same file, so there is nothing for a shared lock to protect.
3. **The push step fetches, rebases and retries, with jitter.** Two different workflows can therefore
   both write to `data` in the same window without a lock. This is the actual concurrency control:
   optimistic, at the git layer, where the conflict really lives.
4. **`live.json` and `meta.json` are merged from the per family files as the last step of each write.**
   They are derived artifacts, so a merge is always well defined and the last writer produces a
   correct union rather than clobbering a peer.
5. **The Worker logs every dispatch it sends.** This makes "dispatched but never ran" visible and
   separable from scheduler flakiness, which is the diagnostic that section 1a lacked.

Only `heartbeat` is armed in Phase 0, so this cannot affect the Phase 0 exit. The design is recorded
and implemented now so that Phase 1 does not inherit a known trap.

### Measurement, to be filled in

| Observation | Result |
|---|---|
| Pending run cancelled when a third arrives on one group | **Measured 2026-11-06. CONFIRMED.** See below |
| Per workflow groups: concurrent writes to `data` from two workflows | Unit tested against real git repositories. Not yet observed in production, because only one workflow is armed |
| Rebase and retry push: conflicts, retries, jitter adequacy | Not yet measured in production. Every heartbeat push so far: `attempts=1 rebases=0 rejections=0` |
| Worker and GitHub `schedule` firing for the same window | **Observed 2026-11-06, no collision.** See below |

Record the numbers here when they exist, per ground rule 11. Do not record a reasoned expectation in
this table as though it were an observation.

#### The one pending slot claim, measured

A throwaway workflow (`concurrency-probe.yml`, since deleted) held a group for 90 seconds while three
`workflow_dispatch` calls were fired about 4 seconds apart.

| Dispatch | Run id | Created | Outcome |
|---|---|---|---|
| 1 | 42242817493 | 15:24:53Z | `success`, ran 15:24:53 to 15:26:30 |
| 2 | 42242828478 | 15:24:57Z | **`cancelled` at 15:25:05Z** |
| 3 | 42242840220 | 15:25:02Z | queued, then ran after dispatch 1 finished |

Dispatch 2 was cancelled **3 seconds after dispatch 3 was created**, having never executed. So the
claim holds exactly: **a concurrency group holds at most one pending run, and a third arrival
destroys the one already waiting.**

Two consequences worth stating precisely, because the words matter:

- **The loss is a drop, not a coalesce.** GitHub does not merge two triggers into one run that serves
  both. Dispatch 2 did no work at all. For `heartbeat` that is harmless, since every write is a full
  snapshot. For a Phase 1 ingest workflow it would be a **data gap**, and because every window keys
  off data timestamps rather than run times, the next run would not automatically backfill it.
- **This is why the single shared `data-branch-write` group was abandoned.** Under a 5 minute timer
  with several armed workflows, drops would have been routine, and a dropped run is invisible from
  inside the repository: it looks exactly like the scheduler flakiness measured in section 1a. The
  per workflow design in this section is now supported by measurement rather than by reasoning.

#### Worker and `schedule` firing for the same window

On 2026-11-06 both triggers fired for the 14:00 heartbeat window. **They did not collide**, and the
reason is worth recording so the absence of a problem is not mistaken for proof of safety:

| Trigger | Run created | Run duration |
|---|---|---|
| Worker dispatch | 14:00:23Z | about 20 s |
| GitHub `schedule` | **14:41:52Z** | about 20 s |

41.9 minutes apart, so the group was never contended. Four triggers to date have produced four runs,
with nothing dropped.

**Residual exposure.** A collision needs `schedule` delivery to land within roughly one job duration
of the Worker's slot. Heartbeat jobs last 20 to 30 seconds and `schedule` delivery is scattered over
tens of minutes, so the probability is low now. It **rises in Phase 1**, where jobs run for minutes
rather than seconds, widening the window for a collision on the same workflow. Re evaluate when the
first family is armed, and note that the available mitigation (having a `schedule` triggered run
stand down if a recent unassisted write already exists) is not yet implemented.

---

## 10. Naming

The first build ended with three names in play: a product name, a repo slug and a host. The repo slug sat in the live read path, so renaming it later meant an outage, not a rename.

Rule: choose one name before any code exists and use it for the display title, the repo, `package.json`, the Vercel project and the production host.

Vercel appends a suffix to the generated host when the name is taken, which is how an unwanted host name appears. So the name is checked in Phase 0 step 0 by actually adding the host to a project and confirming it is assigned. If it is unavailable, pick the name that is free on both GitHub and Vercel, then use that one everywhere.

### Decision taken, 2026-11-06: the name is `terraview24`

The documented default was `terraview`. **It is not available.** Measured by live request on 2026-11-06:

| Host | `x-vercel-error` | Body | Reading |
|---|---|---|---|
| `terraview.vercel.app` | `NOT_FOUND` | 79 bytes | **Taken.** A deployment is assigned to the host and 404s on `/` |
| `terrawatch.vercel.app` | none, `HTTP 200` | served a page | **Taken and live** |
| control, random subdomain | `DEPLOYMENT_NOT_FOUND` | 107 bytes | Free |
| `terraview24.vercel.app` | `DEPLOYMENT_NOT_FOUND` | 107 bytes | **Free. Chosen** |

The distinguishing evidence is the `x-vercel-error` value and the body length, nothing else. The edge
IP was initially read as part of the signature and that was wrong: it is stable per host but differs
between known free hosts too, so it carries no information about whether a host is assigned.

So: display title **TerraView24**, repo `dhairyabhosale/terraview24`, `package.json` name
`terraview24`, Vercel project `terraview24`, production host `terraview24.vercel.app`. One name, five
places, per the rule above.

**This probe proves no deployment is currently assigned. It does not prove the Vercel project name is
claimable**, since a project could hold the name without a production deployment. The authoritative
test is assigning the host in step 3 of `PHASE_0_HUMAN_CHECKLIST.md` and confirming it attaches with no
suffix. Until that passes, the name is probable and not confirmed.
