# DATA SOURCES

> **TerraView24** : *Damage done by humans, measured against the norm*
>
> Part of the TerraView24 doc set. See `ARCHITECTURE.md` for the system overview.

Every source here has a free access tier. Budget for this project is zero.

> **Verification status: keyless endpoints re verified 2026-11-06 (Phase 0a). Everything else verified 2026-11-05, during the first build.** Every endpoint below was checked by live request where a keyless path exists and by current official documentation otherwise. Values marked **[verified]** were observed directly. Values marked **[documented]** come from official docs but could not be exercised without a key. Values marked **[unresolved]** are contradictory or unconfirmed and must be settled before code depends on them.

### Phase 0a re verification, 2026-11-06

Unchanged, confirmed by live request: FIRMS no key (`HTTP 400`, `Invalid MAP_KEY.`), GFW catalogue
(`HTTP 200`, **exactly 382 datasets**, all eight named datasets present), GFW `/query` without a key
(`HTTP 403`, documented message), Protected Planet v3 without a token (`HTTP 401`), OpenAQ v3 without a
key (`HTTP 401`), IUCN v4 without a token (`HTTP 403`, `{"error":"Forbidden"}`), MPC (**139
collections**, keyless STAC search returning live items, keyless SAS token, `jrc-gsw` carrying
`occurrence`, `recurrence`, `seasonality`, `transitions`, `change`, `extent`), USGS FDSNWS
(`HTTP 200`, API `2.8.4`), GDACS (`HTTP 200`, `FeatureCollection`, 120,233 bytes).

**Four things differ from what this file recorded.** All four are in the GDELT and GFW sections below,
marked `[re verified 2026-11-06]`. None of them changes a decision already taken. In summary:

1. The GDELT DOC 2.0 API is **not** uniformly `429`. It served `HTTP 200` on 2 of 5 requests paced 6
   seconds apart. The bulk GKG decision is unaffected, because it rested on the runtime budget, not on
   the API being wholly unreachable.
2. **GKG slices lag the `lastupdate.txt` manifest by roughly 45 to 60 minutes.** The manifest lists a
   slice before the object is readable. This one has a direct design consequence for `confirm.yml`.
3. GKG slice size varies between about 2.7 and 5.3 MB, not a flat 5.4 MB.
4. The GFW `/query` `403` arrives after two redirects, so a client that does not follow redirects sees
   `307`.

---

## Verification summary

| Source | Status | Key | Headline change since this doc was written |
|---|---|---|---|
| NASA FIRMS | Live | Yes, self service | **Suomi NPP ceased 2026-11-02. Primary sensor must change.** |
| VIIRS Nightfire (EOG) | Live | Registration plus signed licence | Now a signed one year academic agreement |
| GFW GLAD / RADD | Live | Yes, `x-api-key` | Auth flow confirmed, three step. Catalogue is keyless |
| WDPA / Protected Planet | Live | Yes for API, no for bulk | Second keyless route found via GFW data API |
| OpenAQ | Live | Yes, `X-API-Key` | v2 retired, v3 only. 60 req/min, 2000 req/hour |
| Sentinel-5P | Live | **No, via MPC** | **Unattended route exists. The Phase 4 auth blocker is gone** |
| Global Fishing Watch | Live | Yes, token | Limits generous at 50k/day. "AIS gap" renamed "AIS off" |
| JRC Global Surface Water | Live | **No, via MPC** | Keyless, all baseline bands present |
| GDELT DOC 2.0 | Live but throttled | No | **1 request per 5 seconds. Returned 429 on every attempt** |
| IUCN Red List | Live | Yes, Bearer | **v3 is defunct. v4 only** |
| USGS earthquakes | Live | No | No change |
| GDACS | Live | No | No change |
| Microsoft Planetary Computer | Live | No | Hub retired 2024, data and STAC APIs remain |
| Google Earth Engine | Live | Cloud project plus questionnaire | Noncommercial quota tiers took effect 2026-04-27 |

Two findings changed the plan: the Suomi NPP cessation (Family A sensor and baseline) and the GDELT throttle (the confirmation layer for every family). **Both have been decided**, and the decisions are recorded in place below. The rule for this file: when a decision is taken, write it into the section it affects so nobody has to find it in a conversation.

---

## Family A: Thermal

### NASA FIRMS (primary backbone)
- **Gives:** active fire and thermal anomaly detections from MODIS and VIIRS.
- **Resolution:** VIIRS at roughly 375m, MODIS at roughly 1km.
- **Cadence:** multiple passes daily, near real time products typically available within a few hours.
- **Access [verified]:** free MAP_KEY, **self service and immediate** at `https://firms.modaps.eosdis.nasa.gov/api/map_key/`. This doc previously described the key as "issued by email request", which understates how easy it now is: you submit an email address and the key comes back directly. Remaining transactions can be checked with the "Check status" option on the same page.
- **Endpoint [documented]:**
  ```
  /api/area/csv/[MAP_KEY]/[SOURCE]/[W,S,E,N | world]/[DAY_RANGE]
  /api/area/csv/[MAP_KEY]/[SOURCE]/[W,S,E,N | world]/[DAY_RANGE]/[YYYY-MM-DD]
  ```
  Area accepts a bounding box as `west,south,east,north`, or the literal `world`. It does **not** accept named `north=` / `south=` parameters. Maximum extent is `-180,-90,180,90`.
- **Rate limit [documented]:** 5000 transactions per 10 minute interval per MAP_KEY. A multi day request counts as multiple transactions, roughly one per day of data requested. NASA raises the limit case by case on request.
- **DAY_RANGE [unresolved]:** the API page states a valid range of 1 to 5 in its parameter table and then gives a worked example using 7. Confirm the real ceiling with a key in hand before building the ingest loop around it. Assume 5 until proven otherwise.
- **Behaviour without a key [verified]:** `HTTP 400`, body `Invalid MAP_KEY.`
- **Key fields:** `latitude`, `longitude`, `bright_ti4`, `bright_ti5`, `frp` (fire radiative power), `scan`, `track`, `acq_date`, `acq_time`, `satellite`, `confidence`, `daynight`.

#### CRITICAL: Suomi NPP ceased three days before this verification [verified]

**NASA stopped producing new Suomi NPP products at 13:00 UTC on 2026-11-02.** This doc and `DETECTION_SPEC.md` both implicitly assume VIIRS S-NPP as the backbone sensor. That assumption is now dead. NOAA's parallel notice gives 2026-11-01 13:00 UTC; the one day discrepancy is announcement wording, not two separate events.

What stops: S-NPP active fire, its FIRMS email alerts, VIIRS and OMPS reflectance imagery, Black Marble, and the burned area and aerosol index products derived from S-NPP.

What continues: **NOAA-20 (JPSS-1) and NOAA-21 (JPSS-2) VIIRS**, which NASA describes as an identical sensor at identical 375m resolution, flying in the same orbital plane roughly 50 minutes apart. The historical S-NPP archive remains downloadable.

**Current valid `SOURCE` values [documented]:**

| Source | Status |
|---|---|
| `VIIRS_NOAA20_NRT`, `VIIRS_NOAA20_SP` | Use. Primary. |
| `VIIRS_NOAA21_NRT`, `VIIRS_NOAA21_SP` | Use. Second sensor for corroboration. |
| `MODIS_NRT`, `MODIS_SP` | Use with a caveat, see below. |
| `VIIRS_SNPP_NRT`, `VIIRS_SNPP_SP` | **Dead for new data.** Archive only. |
| `LANDSAT_NRT` | US and Canada only. Not useful globally. |

**Archive coverage, which is what determines whether the Tier 0 baseline is buildable [verified]:**

| Product | Archive start | Archive end | Years available |
|---|---|---|---|
| MODIS Collection 6.1 (1km) | 2000-11-01 | present | 26 |
| VIIRS S-NPP (375m) | 2012-01-20 | 2026-11-02 | 14, closed |
| **VIIRS NOAA-20 (375m)** | **2018-04-01** | **present** | **8.6** |
| VIIRS NOAA-21 (375m) | 2023-03-01 | present | 3.7 |
| Landsat (30m) | 2022-06-20 | present | 4.4, regional |

**The mandatory baseline survives this.** `DETECTION_SPEC.md` section 2 requires a minimum of 5 complete years ending at least one month before present. NOAA-20 has 8.6 years, so a 5 year baseline over calendar years 2020 to 2024, or 2021 to 2025, is fully buildable from NOAA-20 alone.

**Decision taken:** the baseline is built on **NOAA-20**, calendar years **2021 to 2025**, a closed window, so the sensor the baseline encodes is the same sensor being scored against it. Do not mix S-NPP history into a NOAA-20 baseline without a cross sensor calibration step: that is unasked for work, and it would weaken the sigma score rather than strengthen it. NOAA-21 (3.7 years) is too short to carry its own 5 year baseline and should be used as a corroborating sensor only.

- **Pitfalls:**
  - `frp` is the single most informative field for classification. Do not drop it.
  - Low confidence detections are a large fraction of the feed. Filter, but record how many you filtered; the ratio is itself a quality signal.
  - Sun glint and hot desert surfaces produce recurring false positives in fixed locations. The baseline absorbs these naturally, which is one reason the baseline is mandatory.
  - MODIS and VIIRS will both see the same fire. Cross sensor agreement is a corroboration signal, so do **not** deduplicate across sensors at ingest. Deduplicate at the clustering stage and keep the sensor count.
  - **New pitfall, sensor independence [verified]:** NOAA-20 and NOAA-21 share an orbital plane, are about 50 minutes apart, and run an identical instrument. `sensor_count >= 2` from that pair is weaker evidence than the `CORROBORATED` gate in `DETECTION_SPEC.md` section 6 assumes, because the two observations share orbit, instrument design and processing chain. MODIS Terra and Aqua remain the genuinely independent cross check. **Decision taken:** NOAA-20 plus NOAA-21 agreement is recorded as `same_plane_persistence`, never as independent corroboration, and every event carries a typed `corroboration_type`. See `ARCHITECTURE.md` section 5a and `DETECTION_SPEC.md` section 6.
  - **New pitfall, MODIS is also ending [documented, dates conflict]:** NASA plans end of science operations for Terra around January to February 2027, and for Aqua somewhere between August 2026 and September 2027 depending on which NASA page you read. MODIS is therefore a time limited corroboration source, not a permanent one, and no follow on instrument in the Terra morning crossing orbit exists in current or planned NASA missions. The independent cross sensor check degrades during the life of this project. **Decision taken:** the degraded mode is defined now, in the same commit as the `CORROBORATED` gate, and the panel states it. See `DETECTION_SPEC.md` section 6.
- **Archive access route for Tier 0 [verified]:** the archive download service at `https://firms.modaps.eosdis.nasa.gov/download/` covers data older than the last 7 days and serves shapefile, CSV or JSON. It is **asynchronous**: authenticate with Earthdata Login or an emailed code, submit the request, then receive download instructions by email. That is fine for Tier 0, which is manual and run roughly twice a year, and unusable from CI, which is exactly how `ARCHITECTURE.md` already specifies it. NRT records are replaced by science quality (SP) records after about a 5 month lag, so a baseline built from history is SP throughout while the live feed is NRT. Record that discontinuity on the event, since it is a real difference between the norm and the observation being scored against it.

### VIIRS Nightfire (for `gas_flaring`)
- **Gives:** high temperature point sources detected at night, specifically tuned for flaring.
- **Access [documented]:** published by the Earth Observation Group (Payne Institute, Colorado School of Mines) at `https://eogdata.mines.edu/products/vnf/`. Free download of bulk files, not a live API. **Changed: registration is now mandatory**, which EOG describes as a security change, and the academic route is a **no cost one year licence agreement that must be signed and returned**. Non profit use is a separate annual subscription agreement.
- **Version [documented]:** V4.0 has been operational since 2025-07-01 across S-NPP, NOAA-20 and NOAA-21. Daily repositories for V3.5, V3.0 and V2.1 remain published, alongside the annual global gas flare analysis. Use V4.0, and prefer its NOAA-20 and NOAA-21 streams for consistency with the chosen FIRMS backbone.
- **Use:** training labels for the Family A classifier. Flares are the stationary, permanent, aseasonal class.
- **New consideration:** the signed licence is a human step with a turnaround time. It gates Phase 2, not Phase 1. Start it early so it is not the thing holding up the classifier.

---

## Family B: Forest loss

### Global Forest Watch: GLAD and RADD alerts
- **Gives:** forest disturbance alerts. GLAD is optical (Landsat and Sentinel-2 based), RADD is radar (Sentinel-1) and therefore cloud penetrating, which matters enormously in the tropics.
- **Resolution:** 10m to 30m depending on product.
- **Cadence:** weekly to near weekly. Slower than thermal. Schedule separately.
- **Host [verified]:** `https://data-api.globalforestwatch.org`. The older `api.resourcewatch.org` route is not the one to code against.
- **Auth flow [verified], three steps:** this doc said "confirm the current auth flow; it has changed." It has. These endpoints were read from the live OpenAPI spec:
  ```
  POST   /auth/sign-up                      create an account
  POST   /auth/token                        exchange credentials for a bearer token
  POST   /auth/apikey                       create a long lived API key
  GET    /auth/apikeys                      list your keys
  GET    /auth/apikey/{api_key}             inspect a key
  GET    /auth/apikey/{api_key}/validate
  DELETE /auth/apikey/{api_key}
  ```
  The bearer token exists only to mint the API key. The pipeline then sends the key in an **`x-api-key`** header. Store the key, not the account password, in GitHub secrets.
- **Key lifetime [documented]:** one year per community documentation, not stated in the OpenAPI spec. Set a calendar reminder, because a silently expired key will present exactly like a dead source.
- **What is keyless [verified]:** the dataset catalogue. `GET /datasets` returned `HTTP 200` with **382 datasets**. Useful for discovery, and for a CI smoke test that needs no secret.
- **What needs the key [verified]:** `/query`. Without it, `HTTP 403`, body `Request is missing valid API key.`
- **`[re verified 2026-11-06]` the `403` arrives after two redirects.** `/dataset/wur_radd_alerts/latest/query` returns `307` to `/dataset/wur_radd_alerts/v20261101/query/json`, and the `403` comes from the final hop. `latest` resolves to a pinned version and `/query` resolves to `/query/json`. An HTTP client with redirect following disabled will see `307` and no error body, so enable redirect following on this host and assert on the final status, not the first.
- **Relevant pixel level datasets [verified present in catalogue]:**
  `umd_glad_landsat_alerts`, `umd_glad_sentinel2_alerts`, `umd_glad_dist_alerts`, `wur_radd_alerts`, `gfw_integrated_alerts`, `gfw_integrated_dist_alerts`, each with a matching `_coverage` dataset giving the valid observation mask.
- **RADD freshness [verified, refined 2026-11-06]:** latest version is still `v20261101`, now five days old. The observed version tail is `v20260412`, `v20260705`, `v20261011`, `v20261018`, `v20261026`, `v20261101`, so the earlier claim of "roughly weekly since `v20260412`" is wrong: there are multi month gaps after `v20260412` and `v20260705`, and weekly cadence only begins around `v20261011`. Treat the release cadence as irregular, which strengthens rather than weakens the rule below. Pin a version explicitly rather than tracking `latest`, or a reprocessing will silently rewrite your history.
- **Bonus routes found [verified]:** `wdpa_protected_areas` and `jrc_surface_water_transitions_1984_2020` are also hosted here, giving a second access path for two sources listed separately below.
- **Rate limits [unresolved]:** not stated in the OpenAPI spec or the help pages. Implement backoff and discover them politely rather than assuming there are none.
- **Pitfalls:**
  - Alerts are pixels, not events. Clustering is mandatory and the cluster *shape* is the classifier's main feature.
  - Cloud cover creates long gaps in GLAD. RADD fills them. Use both and treat agreement as corroboration.
  - Alert confidence tiers exist. Use them as a feature, not a hard filter.
  - Prefer GLAD and RADD separately over `gfw_integrated_alerts` for the corroboration logic specifically: an integrated product has already collapsed the independent agreement you are trying to measure. Use the integrated layer for coverage, not for the `CORROBORATED` gate.

### World Database on Protected Areas (WDPA)
- **Gives:** protected area boundary polygons worldwide.
- **Access, route 1 [documented]:** bulk download from Protected Planet, free for non commercial use, monthly release.
- **Access, route 2 [verified]:** the Protected Planet REST API at `https://api.protectedplanet.net/v3` **requires a token**. Without one: `HTTP 401`, body `Unauthorized. Invalid or expired token.` Tokens are free on request.
- **Access, route 3 [verified]:** `wdpa_protected_areas` via the GFW data API, which the pipeline already authenticates against. One fewer credential to manage.
- **Recommendation:** use the bulk download for the Tier 0 static spatial join, since that join runs against a committed file and needs no API at all. The API is only worth the credential if monthly refresh inside CI turns out to matter.
- **Use:** static reference. Spatially join every Family B cluster against it. A deforestation cluster inside a protected area is `urban_expansion_protected` or a far more severe `deforestation`, depending on built up signature.

---

## Family C: Atmospheric

### OpenAQ
- **Gives:** ground station air quality measurements, global, many pollutants.
- **Access [verified]:** **v3 only, v2 is retired.** Base URL `https://api.openaq.org/v3`. The key goes in an **`X-API-Key`** header. Register at `https://explore.openaq.org/register`. Without a key: `HTTP 401`, body `Unauthorized. A valid API key must be provided in the X-API-Key header.`
- **Rate limits [documented]:** the free "general use" tier is **60 requests per minute and 2000 requests per hour** per key. No daily cap is published. Higher limits are custom priced, which this project will not be using.
- **Budget implication:** 2000 requests per hour is comfortable for a daily workflow, but the station list is large. Page through `/v3/locations` once, cache the station index as a committed static file, and only poll measurements for stations near live events. Do not re enumerate the world every run.
- **Use:** two jobs. First, `air_quality_exceedance` events directly. Second, and more valuable, **validating the satellite layer against physical sensors.** A satellite NO2 anomaly that agrees with a nearby ground station is corroborated. This cross validation is the kind of rigour that separates a serious project from a pretty one. Do not skip it.
- **Pitfall:** station coverage is wildly uneven. Dense in Europe and North America, sparse elsewhere. Never present station density as pollution density.

### Sentinel-5P (TROPOMI)
- **Gives:** NO2, SO2, CO, methane and aerosol column densities.

**This doc called this "the awkward one" and said both free routes need browser based auth. That is no longer accurate.** There are two unattended routes, and one of them needs no credential at all.

**Route A, Microsoft Planetary Computer, keyless [verified]:**
- STAC search at `https://planetarycomputer.microsoft.com/api/stac/v1/search` returned `HTTP 200` with no credential. Collection id `sentinel-5p-l2-netcdf`. A query over 2026-10-28 to 2026-11-04 returned live items, for example `S5P_L2_SO2____20261103T234732_20261103T235232_46940`.
- Asset access is signed through a **keyless** SAS token endpoint: `GET /api/sas/v1/token/sentinel-5p-l2-netcdf` returned `HTTP 200` with a token valid for roughly 45 minutes.
- Anonymous access is rate limited but needs no account, no OAuth and no stored secret, which makes it the most CI friendly route in this entire document.
- MPC status [documented]: the interactive **Hub** was retired on 2024-06-06, but Microsoft stated the **data and APIs remain available and unchanged**. Verified live on 2026-11-05 with 139 collections.

**Route B, Copernicus Data Space Ecosystem, OAuth2 client credentials [documented]:**
- CDSE supports the **client credentials** grant, which is machine to machine and needs no browser. The earlier concern applies to the interactive portal, not to the API.
- Costs of this route: access tokens live roughly 10 minutes, so cache and refresh rather than minting per request or you will hit `HTTP 429` on the token endpoint itself. The **client secret expires every 90 days** and there is no API to rotate it, so this route imposes a manual quarterly secret rotation. A general account is limited to 4 concurrent connections.

**Recommendation:** make MPC the primary Sentinel-5P route and keep CDSE as the documented fallback. **This unblocks Sentinel-5P from its Phase 4 auth problem.** The deferral in `ROADMAP.md` becomes a sequencing choice under ground rule 7 (depth over breadth) rather than a technical blocker, which is a better reason to defer and should be recorded as the actual one. Do not start it before Phase 1 exits.
- **Rendering note:** this is a *field*, not a point. Render as a translucent surface overlay. A pin for a pollution plume breaks the visual metaphor.

---

## Family D: Independent

### Global Fishing Watch
- **Gives:** AIS derived vessel tracks and fishing effort.
- **Access [documented]:** API **v3**. Tokens from `https://globalfishingwatch.org/our-apis/tokens`, free, non commercial only, **up to 5 tokens per user**.
- **Licence [documented]:** CC BY-NC 4.0, attribution required in a specified form. GFW reserves the right to suspend access at any time without notice, which is worth knowing before the project depends on it.
- **Rate limits [documented], and they are generous:** **50,000 requests per day and 1,500,000 per month**, enforced per user across all of that user's tokens rather than per token. Breach returns `HTTP 429`; a daily breach blocks requests for 24 hours and a monthly breach blocks them for 30 consecutive days. Tokens are not deleted on breach. Those are hard blocks of punishing duration, so cap request volume defensively in code rather than relying on staying under by luck.
- **Available APIs [documented]:** `Vessels` (identity resolution by MMSI, IMO or name), `Events` (encounters and potential transshipment), `4Wings` (apparent fishing effort, and dark vessel detection), `Insights` (fused vessel risk indicators), plus a bulk CSV and JSON download.
- **Naming change that affects the detector spec [documented]:** what this doc calls an "AIS gap" is now surfaced as an **"AIS off" event under the `Insights` API**, not as a standalone gap endpoint. The detection target is unchanged, but the endpoint and field names used in `DETECTION_SPEC.md` will need to follow GFW's current vocabulary.
- **Detection target:** vessels that go dark (AIS gap) inside or adjacent to a marine protected area, then reappear. Clean anomaly problem, real stakes.
- **Pitfall:** AIS gaps have innocent causes including equipment failure and satellite coverage holes. Gap duration, location relative to MPA boundary, and vessel behaviour before and after the gap are the discriminating features. Do not call a gap "illegal fishing" on gap alone; this is exactly what the `SUSPECTED` stage is for.

### Sentinel-1 (oil spills) and Sentinel-2/3 (water quality) **deferred**
- Both need per scene imagery processing, which is a materially heavier pipeline than everything above.
- Water contamination is thematically excellent and practically hard: separating pollution from natural algal blooms, rainfall sediment and seasonal variation is the whole difficulty.
- **Phase 4.** Deferred, not dropped. See ground rule 9 in `AGENT_PROMPT.md`.
- **Access note [verified]:** both are keyless via MPC, with `sentinel-1-grd` and `sentinel-2-l2a` confirmed present in the collection list. The deferral is about processing cost, not access. Recording that distinction so the access question does not get re litigated later.

---

## Family E: Topological change (Phase 4)

Two subtypes, both surface water boundary problems sharing one NDWI differencing implementation. Two further subtypes were assessed and cut; see `ARCHITECTURE.md` section 4 for the reasoning.

### `river_course_change`
- **Primary:** JRC Global Surface Water (Pekel et al.), which provides monthly and yearly water occurrence history going back decades. This is the single best starting point and it saves you from building a water mask from scratch.
- **Access [verified], and it is better than expected:** JRC GSW is keyless via MPC as collection `jrc-gsw`. An item query returned `HTTP 200` with assets `occurrence`, `recurrence`, `seasonality`, `transitions`, `change`, `extent`, plus `tilejson` and `rendered_preview`. The `occurrence` and `seasonality` bands are exactly the baseline that separates seasonal flooding from permanent change, available with no credential at all. `jrc_surface_water_transitions_1984_2020` is also reachable through the GFW data API as a second route.
- **Live detection:** Sentinel-2 NDWI water masks differenced against the JRC occurrence baseline. Sentinel-1 for cloud penetration in monsoon regions. Both keyless via MPC.
- **Human causation signal:** a new permanent water body upstream of a channel that has lost flow is the damming signature. Look for the pair, not either alone.
- **Pitfall:** seasonal flooding will dominate the raw signal. The JRC occurrence baseline is what separates seasonal from permanent, which is the same baseline logic as everywhere else in this project.

### `coastal_erosion`
- **Primary:** Sentinel-2 shoreline extraction via NDWI thresholding, multi date comparison.
- **Baseline reference [verified, with a correction to this doc]:** the two datasets named here previously do not hold up equally well.
  - **Deltares Aqua Monitor:** the original 2016 era global land and water conversion tool (30m, 30 year span), openly licensed with code published. No 2026 shoreline specific product release was found, and the shoreline viewer is a legacy app. Treat it as historical reference, not a live dependency.
  - **USGS National Shoreline Change:** updated 2026-05-22, compiling long term rates of change from USGS publications spanning 2000 to 2025 (DOI `10.5066/P14MTEZ3`). **United States only**, so it fails the same global coverage test that removed `land_subsidence` in `ARCHITECTURE.md` section 4. Useful for validating the detector against a trusted reference in one region, not as the global baseline.
  - **Better options found, both global [documented]:** the **Global Coastal Transect System** (Deltares and TU Delft, Calkoen et al. 2025) provides over 11 million cross shore transects at 100m alongshore spacing with cloud optimised access and a Python library (`coastpy`), and **CoastSat** publishes Landsat derived shoreline change time series from 1984 to 2024 with FES2022 tide model integration already applied. The CoastSat tide integration is directly relevant to the mandatory correction below, since it means someone has already solved the hardest part.
  - **Decision needed before Phase 4 starts**, not now. Recorded here so the choice is made from the current landscape rather than the 2016 one.
- **Mandatory correction:** tide stage. A shoreline position measured at different tide states will show metres of spurious change. Either normalise by tide model or restrict comparisons to similar tide states. Without this the detector is noise.
- **Human causation:** attribution is genuinely contested here. Coastal erosion has strong natural drivers. Be conservative, and prefer sites with adjacent construction, port works or sand mining signatures before typing it as human caused.

### Excavation driven terrain change

Not a Family E subtype. Handled inside Family B `mining_activity` via a `bare_earth_expansion_rate` feature derived from Sentinel-2, which reuses the forest loss pipeline rather than building a second one. See `ARCHITECTURE.md` section 4.

---

## When a source fails

Per ground rule 10 in `AGENT_PROMPT.md`: a dead or paywalled source is a research task, not a reason to drop the capability.

Check these alternative access routes before concluding a product is unavailable. Several of them mirror the same underlying data through a different path:

| Route | Covers | Status, verified 2026-11-05 |
|---|---|---|
| Google Earth Engine | Sentinel, Landsat, MODIS, JRC water, land cover | Live, free for noncommercial, but now gated. See below |
| Copernicus Data Space Ecosystem | All Sentinel products, the official EU route | Live. OAuth2 client credentials work unattended. 90 day secret rotation |
| NASA Earthdata / LAADS DAAC | MODIS, VIIRS, FIRMS archives | Live. Earthdata Login required. Asynchronous for archive orders |
| **Microsoft Planetary Computer** | Sentinel, Landsat, JRC GSW, MODIS, STAC API | **Live and keyless. 139 collections. The best CI route found** |
| AWS Open Data Registry | Sentinel-1 and 2, Landsat, often the fastest bulk route | Not individually exercised. Known good, requester pays on some buckets |
| Zenodo / Figshare | Published derived datasets from papers | Live. Confirmed as the route to the Global Coastal Transect System |

### Microsoft Planetary Computer is the headline result of this verification pass

MPC was listed as one option among six. It verified as the strongest, because it is the only route that needs **no credential whatsoever** for both search and asset access:

- STAC search: keyless, `HTTP 200`.
- Asset signing: keyless, via `/api/sas/v1/token/{collection}`, tokens valid roughly 45 minutes.
- Carries `sentinel-5p-l2-netcdf`, `sentinel-2-l2a`, `sentinel-1-grd`, `jrc-gsw`, `modis-14A1-061` and `modis-14A2-061`, which between them cover Family C, Family E and a MODIS active fire fallback.
- The Hub retirement in June 2024 did not affect the data or the APIs, which Microsoft stated explicitly and which this verification confirms.

Anonymous access is rate limited and MPC is a single point of dependency, so keep CDSE documented as the fallback for Sentinel products. But for a zero budget project where every stored secret is a maintenance liability, a keyless route is worth a great deal.

### Google Earth Engine access has tightened [documented]

Earth Engine remains free for noncommercial use, but three gates have appeared since this doc was written:

1. **Since 2024-11-13**, all users including noncommercial ones must access the platform through a Google Cloud project.
2. **Since 2025-09-26**, every noncommercial project must have completed a questionnaire in the Cloud console. Google reviews each one because it grants unpaid compute.
3. **Since 2026-04-27**, noncommercial projects select a quota tier, defaulting to Community if nothing is chosen.

| Tier | Monthly compute | Eligibility |
|---|---|---|
| Community | 150 EECU hours | Any verified noncommercial project. The default |
| Contributor | 1000 EECU hours | Verified noncommercial project with an active billing account attached (no Earth Engine charges) |
| Partner | 100,000 EECU hours | Separate application, manual review of several weeks, must relate to climate mitigation, adaptation or protection |

Quotas are per project, reset monthly, and do not carry over. Exhausting one puts the project into restricted mode with reduced concurrency rather than failing outright. Service accounts work but the project behind them must be registered.

**Assessment:** the Community tier at 150 EECU hours per month is probably adequate for Family E, since NDWI differencing over targeted areas of interest is not expensive. The registration questionnaire and the mandatory Cloud project are the real cost, and both are one off. Given that MPC covers the same products keylessly, Earth Engine is now the second choice for this project rather than the first, which reverses the suggestion in the previous version of this file. Keep it in reserve for anything requiring server side reduction over long time series, which is the one thing MPC cannot do for you.

**Record the substitution and its tradeoffs in this file whenever one is made.**

---

## Confirmation layer

### GDELT DOC 2.0
- **Gives:** global news article index with geographic and temporal query support.
- **Access [verified]:** free, no key, endpoint live at `https://api.gdeltproject.org/api/v2/doc/doc`.
- **Use:** stage 3 confirmation only. Query scoped to the event bounding box and detection window.

#### CRITICAL: GDELT is throttled far harder than this doc assumes [verified]

**`[re verified 2026-11-06]` this claim was too strong.** Paced 6 seconds apart from a residential IP,
the DOC API served `HTTP 200` on **2 of 5** requests (`200, 429, 200, 429, 429`). An earlier run the
same morning gave `429, 429, 200`. So the endpoint is partly usable, not wholly unreachable, and
**problem 2 below (throttling by source IP) is not supported by this observation** and should be
treated as an open possibility rather than a finding. Problem 1 is untouched and is the load bearing
one: at a nominal ceiling of one request per 5 seconds, and an observed success rate near 40 percent,
confirming 3000 events serially is still hours, which fits no runtime budget. **The bulk GKG decision
stands and is not reopened.** This note exists so the evidence behind it is accurate, per ground rule 13.

Original observation, 2026-11-05:

**Three attempts on 2026-11-05, spaced minutes apart, all returned `HTTP 429.`** The response body states the policy directly:

> Please limit requests to one every 5 seconds or contact [the maintainer] for larger queries. All high-traffic users should switch to our ngrams dataset.

Two separate problems here.

**Problem 1, the documented ceiling.** One request per 5 seconds is 720 requests per hour. the original design in `DETECTION_SPEC.md` section 6 specified one GDELT query per event bbox per run, and `DATA_CONTRACTS.md` caps the live set at 3000 features. Confirming 3000 events serially at one request per 5 seconds takes **about 4.2 hours** of near pure waiting. `ARCHITECTURE.md` section 8 asks for workflow runtimes in minutes and names GitHub Actions free minutes as the real budget constraint. The per event query design does not fit inside that budget.

**Problem 2, worse.** Every attempt returned 429 even at well below one request per 5 seconds, which suggests throttling by source IP address rather than purely by request spacing. GitHub Actions runners use shared IP ranges that are heavily used. The per event query route may be substantially unavailable from CI regardless of how politely the pipeline paces itself. This was not reproducible enough in one session to call proven, but it is a serious risk and it points the same direction as problem 1.

**Alternative route verified working: GDELT bulk files.**
- `https://data.gdeltproject.org/gdeltv2/lastupdate.txt` returned `HTTP 200` with the current 15 minute manifest listing three files: `export.CSV.zip` (events), `mentions.CSV.zip`, and `gkg.csv.zip` (Global Knowledge Graph).
- The GKG file was fetched successfully (`HTTP 206` on a range request, `application/zip`, roughly 5.4 MB per 15 minute slice).

#### `[re verified 2026-11-06]` GKG objects lag the manifest, and this changes `confirm.yml`

The bulk route works, but **`lastupdate.txt` is not a statement that the GKG slice it names is
readable yet.** Measured at 05:31Z on 2026-11-06:

| Slice timestamp | GKG `.gkg.csv.zip` | Age at test |
|---|---|---|
| 05:30Z (the manifest's newest) | `HTTP 404` | 1 min |
| 05:15Z | `HTTP 404` | 16 min |
| 05:00Z | `HTTP 404` | 31 min |
| 04:45Z | `HTTP 404` | 46 min |
| **04:30Z** | **`HTTP 200`, 3,455,171 bytes** | 61 min |

The 05:30Z slice was retried three times over a minute and stayed `404`. Meanwhile
`20261106053000.export.CSV.zip` (`HTTP 200`, 55,327 bytes) and `.mentions.CSV.zip` (`HTTP 200`, 77,222
bytes) from the **same** manifest line were readable immediately. Case variants of the GKG name were
tested and all `404`, so this is not a naming issue. Older slices are fine: 04:30Z, and the
2026-11-05 and 2026-10-01 noon slices, all returned `200`.

**So GKG publication lags its own timestamp by roughly 45 to 60 minutes, while `export` and `mentions`
do not.**

**Design consequences for `confirm.yml`, Phase 3:**

1. Do not ingest the newest slice named by `lastupdate.txt`. Offset the ingest window by at least 90
   minutes behind wall clock to be safely clear of the observed lag.
2. A `404` on a recent slice is **expected and is not an error.** It must not fail the run. Retry it on
   a later run, which the timestamp derived file names already make possible.
3. This is exactly why `index_coverage_fraction` exists (`DETECTION_SPEC.md` section 6). A naive
   implementation that treated the manifest as ground truth would record full coverage over a window it
   had actually failed to read, and then assert `UNREPORTED` over it. That is a false headline finding
   produced by an unhandled `404`, which is the worst failure this project could ship.

**What this measurement does not establish.** It is one observation window, on one morning, from one
residential IP. It cannot distinguish a steady structural lag from a transient GDELT backlog on
2026-11-06. Re measure at the start of Phase 3 before fixing the 90 minute offset, and use a time based
stopping rule per ground rule 11.

**Slice size, corrected:** observed slices ranged from 2,728,270 bytes (2.6 MB) to 5,333,191 bytes
(5.1 MB). The "roughly 5.4 MB" figure is the top of the range, not the typical value. Budget bandwidth
on about 3.5 MB per slice, and note that 15 minute slices over a 7 day thermal confirmation window is
roughly 672 slices, so size assumptions compound.

**Scheme:** `http://` URLs in the manifest return `301` to `https://data.gdeltproject.org:443/...`.
Request `https://` directly, or follow redirects. Do not request `http://` and treat the `301` as a
failure.
- Served from Google's CDN, not the throttled API host. No rate limit was encountered.

**Substitution, per ground rule 10. Decision taken: approved for Phase 3.** Replace per event API queries with a bulk GKG ingest: download the 15 minute GKG slices for the confirmation window, filter locally on GKG's own geographic fields plus the topical term list, and match against event bounding boxes in the pipeline rather than at the API.

| | Per event DOC 2.0 query | Bulk GKG ingest |
|---|---|---|
| What you get | Article list per bbox, ready made | Full global article index with extracted locations and themes |
| Rate limit | 1 request per 5 seconds, plus probable IP throttling | None encountered |
| Runtime for 3000 events | About 4.2 hours | One download per 15 minute slice, then local filtering |
| Resolution lost | None | None. GKG is the richer record |
| What you lose | Nothing | GDELT's own relevance ranking. You now own the relevance filter |
| What you gain | Nothing | Reproducibility. The filter is code in the repo, not a remote black box |
| Cost | Fits no runtime budget | Bandwidth and some CPU, both cheap on a runner |

The substitution arguably **improves** the project's claim discipline. `DETECTION_SPEC.md` section 6 already demands that the relevance strategy be recorded and reproducible, and `DATA_CONTRACTS.md` requires `query_strategy` on every event so a negative result is inspectable. A filter implemented in the repo satisfies that better than a remote API's undocumented ranking, which matters specifically because the `UNREPORTED` stage is an assertion about a negative result. "No matching coverage was found by this query strategy in this index" is a much stronger statement when the query strategy is readable code.

Cost of the substitution: writing the relevance filter is real work that the API was doing for free, and the `query_strategy` version string must be bumped whenever that filter changes or the historical `UNREPORTED` determinations stop being comparable.

**Implement in Phase 3, not before.** The approval carries four conditions: (1) the relevance filter is readable code in the repo with its own tests; (2) every determination is stamped with a `query_strategy_version`, and a change to the filter bumps it and marks earlier determinations not comparable; (3) confirmation is its own workflow, `confirm.yml`, on its own cadence; (4) ingest coverage of the confirmation window is recorded, so `UNREPORTED` is only asserted over a window the index actually covered. GKG slice file names are timestamp derived, so a late or missed run can backfill. The 15 minute manifest cadence is a data cadence, not a promise that a run happens every 15 minutes (see the scheduling section below). Full design in `DETECTION_SPEC.md` section 6.

- **Critical framing, unchanged and now better supported:** GDELT is **not** a detection source and must never place a pin. Media coverage volume is a measure of media attention, not event frequency. A fire in Greece gets hundreds of articles; an equivalent fire in Siberia gets a handful. If you plotted coverage you would be plotting Western media attention.
- That asymmetry is not a bug to hide. It is the mechanism that makes the `UNREPORTED` stage meaningful, and you should say so explicitly in the project write up.

---

## Reference layer

### IUCN Red List
- **Gives:** conservation status, population trend, threat classification, conservation actions, assessment narrative.
- **Access [verified]:** **API v3 is defunct. v4 only.** Base URL `https://api.iucnredlist.org/api/v4`, documentation at `https://api.iucnredlist.org/api-docs`. Authentication is a **Bearer token in the `Authorization` header**, not the v3 style `token` query parameter. Without a token: `HTTP 403`, body `{"error":"Forbidden"}`. Any code sample or tutorial predating this change will not work, and there are many still circulating.
- **Range polygons [documented]:** a separate download portal (`iucnredlist.org/resources/spatial-data-download`), not the API. Esri shapefile format. Over 155,800 of roughly 175,900 assessed species have spatial data, which is over 88 percent. Data Deficient species are generally unmapped, and subspecies, varieties and subpopulations are mapped within the parent species, which matters for the Sumatran tiger example in `DATA_CONTRACTS.md`: it may arrive as part of `Panthera tigris` rather than as its own polygon. Free for non commercial use.
- **Render as polygons, never pins.** A species occupies a region. A pin at the centroid of a tiger's range is meaningless.
- **Do not plot live or precise occurrence coordinates for threatened species.** Conservation databases deliberately fuzz or withhold location data for exactly this reason, and publishing it creates a real poaching risk. Range polygons from the Red List are the safe and correct choice.
- **Analytical payoff:** intersect range polygons with Family B clusters. A deforestation alert inside a critically endangered species range is a far stronger finding than either fact alone, and it is a genuine spatial join rather than decoration. This is what turns a reference layer into an analytical input.

### USGS Earthquakes and GDACS
- Both open, both no key, both useful as context layers. **Both verified live and keyless on 2026-11-05:**
  - USGS FDSNWS: `https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson`, `HTTP 200`, API version 2.8.4, GeoJSON out of the box.
  - GDACS: `https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH`, `HTTP 200`, GeoJSON FeatureCollection, roughly 120 KB for the current orange and red alert list.
- **Neither is a human caused event.** Keep them out of the primary event set or the project's thesis blurs. Optional background context only.

---

## Scheduling summary

These are the cadences the **external timer** fires, per `ARCHITECTURE.md` section 1a. GitHub's own `schedule` stays in each workflow as a slow fallback only. GitHub cron was measured at 3.9 to 5.3 percent delivery for high frequency expressions, with a 4.7 hour median delay, so the cron expressions below are intentions and not guarantees.

| Workflow | Sources | Cadence | Target runtime |
|---|---|---|---|
| `heartbeat` | none (Phase 0 proof, then the freshness signal) | hourly | under 1 min |
| `ingest-thermal` | FIRMS (NOAA-20 primary, NOAA-21 and MODIS for corroboration) | every 6 hours | under 5 min |
| `ingest-weekly` | GLAD, RADD (pin dataset versions) | weekly | under 15 min |
| `ingest-atmospheric` | OpenAQ (plus Sentinel-5P via MPC later) | daily | under 10 min |
| `ingest-marine` | Global Fishing Watch | daily | under 10 min |
| `confirm` | GDELT bulk GKG, local relevance filter | every 15 minutes of data, run as often as is useful | under 10 min |

Keep runtimes tight. GitHub Actions free minutes are the real budget constraint. Cache the pip environment. Every ingest workflow is gated by `PIPELINE_ENABLED` plus one variable for its family, and the timer only fires armed workflows.

**Note on the confirmation step:** it is its own workflow on its own cadence, not a step inside an ingest run, so that a throttled or slow news index cannot delay detection. Because runs can be late, `confirm` must key everything off data timestamps and record which GKG slices it actually ingested.

---

## Credentials required, summary for secret setup

| Secret | Where it lives | Source | How obtained | Expires |
|---|---|---|---|---|
| `GITHUB_TOKEN` (trigger) | **Cloudflare Worker secret only** | GitHub fine grained PAT | This repo only, **Actions: write**, nothing else | **90 days**, set a calendar reminder |
| `FIRMS_MAP_KEY` | GitHub secret | NASA FIRMS | Self service, immediate | Not stated |
| `GFW_API_KEY` | GitHub secret | Global Forest Watch | Three step: sign up, token, apikey | One year [documented] |
| `OPENAQ_API_KEY` | GitHub secret | OpenAQ | Self service registration | Not stated |
| `GFW_FISHING_TOKEN` | GitHub secret | Global Fishing Watch | Request via tokens page | Not stated. Max 5 per user |
| `IUCN_API_TOKEN` | GitHub secret | IUCN Red List | Request, v4 Bearer token | Not stated |
| `PROTECTED_PLANET_TOKEN` | GitHub secret | Protected Planet | Request. Optional, see route 3 | Not stated |
| `CDSE_CLIENT_ID` / `CDSE_CLIENT_SECRET` | GitHub secret | Copernicus | Optional fallback only | **90 days** |

Also on the human's side, not secrets in the usual sense: a free Cloudflare account, the Vercel GitHub App authorization, and a signed VIIRS Nightfire licence for Phase 2 (start it during Phase 1, it has a turnaround time).

No credential at all is needed for: Microsoft Planetary Computer, GDELT (either route), USGS, GDACS, and the GFW dataset catalogue. Earth Engine needs a registered Cloud project rather than a secret in the usual sense.

**Local credential to know about:** `vercel link` writes `.env.local` containing a `VERCEL_OIDC_TOKEN`. It must stay gitignored. See `ARCHITECTURE.md` section 8.

Nothing in this table ever reaches the client bundle. See `ARCHITECTURE.md` section 8.
