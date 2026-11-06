# PHASE 1: ACTIONS ONLY THE HUMAN CAN DO

> **TerraView24** : *Damage done by humans, measured against the norm*
>
> Browser steps only. Anything I can do from a terminal is not in this list.
> Order matters: step 1 is slow and asynchronous, and nothing else waits on it.

**A note on the click paths.** These were written against each site as of this agent's knowledge
cutoff (May 2026), and these particular sites change their wording more often than GitHub or Vercel
do. Where a label does not match what you see, tell me what you actually saw rather than guessing,
and I will correct this file. Anywhere I am genuinely unsure, I have said so inline rather than
inventing a confident path.

---

## Step 1. The FIRMS archive request. DO THIS FIRST

This is the slowest item in the entire project. It is asynchronous, the results arrive by email, and
**nothing else in Phase 1 depends on it**, so every hour it sits unsubmitted is an hour lost at the
end. It is also **not blocked by decision D1**: the archive is raw detections, and the keying choice
only matters later, when the notebook aggregates them.

### 1a. Create an Earthdata Login account, if you do not have one

The archive download service authenticates against NASA Earthdata.

1. Go to **https://urs.earthdata.nasa.gov/users/new**
2. Fill in username, email, password, and the required profile fields (NASA asks for country and a
   study or work area; any accurate answer is fine).
3. Accept the terms, submit, then **verify the email** NASA sends. The account is not usable until
   you do.

Send me the **username only**. Never the password.

### 1b. Submit the archive request, one year first as a probe

Go to **https://firms.modaps.eosdis.nasa.gov/download/**

Sign in with Earthdata Login when prompted. (The page also offers an emailed-code route if you would
rather not use Earthdata; either works, but Earthdata is less fiddly for repeat requests.)

Then build the request:

| Field | What to choose | Why exactly this |
|---|---|---|
| **Area** | World / global extent (`-180, -90, 180, 90`) | The baseline is global. A regional baseline would make the globe show anomalies only where we happened to look |
| **Date range** | **2021-01-01 to 2021-12-31** for this first request | One year, as a probe. See below |
| **Source / sensor** | **VIIRS NOAA-20 (JPSS-1), Standard Processing (SP)** | Not S-NPP, which stopped producing new products on 2026-11-02. Not NRT, because the baseline must be science quality throughout |
| **Format** | **CSV** | The notebook reads CSV. Shapefile carries geometry we do not need and is far larger |

Submit, then wait for the email with download instructions.

**Why one year first rather than all five.** I do not know this service's request size limits, and I
cannot find out without submitting a request, which only you can do. A global year of VIIRS NOAA-20 is
on the order of 10 to 20 million detections, so five years is plausibly 50 to 100 million rows and
several gigabytes of CSV. That may be fine, may be silently truncated, or may be rejected. Submitting
2021 alone tells us the turnaround time, the delivered row count and the file size, and those three
numbers decide how to request the rest. Submitting all five blind risks waiting days to discover a
truncation.

**What to send me when the email arrives:**

- how long it took from submission to the email arriving
- the download link or links (these are not secret)
- the file size, and the row count if the email states one

I will verify the delivered data covers the full year and the full globe before you request 2022
through 2025.

### 1c. The remaining four years, after I confirm 2021 looks right

Same form, same settings, one request per year: **2022**, **2023**, **2024**, **2025**.

Five calendar years, 2021 to 2025, a **closed window**. Closed means reproducible: it does not move as
new data lands, so a sigma computed today and the same sigma recomputed in March agree. Do not extend
it to "present" however tempting, and do not substitute 2020 to 2024 without telling me, because
`baseline_version` encodes the window and every event carries it.

---

## Step 2. The FIRMS MAP_KEY, if you have not already got one

Flagged in Phase 0 as step 7.1, so you may have done this. If not, it takes about two minutes and the
Phase 1 ingest cannot run without it.

1. Go to **https://firms.modaps.eosdis.nasa.gov/api/map_key/**
2. Enter your email address in the form and submit.
3. The key comes back directly on the page (self service and immediate, not an email request).

### 2a. Add it to GitHub as a repository secret

Browser path, since you asked for click paths rather than commands:

1. **https://github.com/dhairyabhosale/terraview24/settings/secrets/actions**
2. Click **"New repository secret"**
3. Name: `FIRMS_MAP_KEY` (exactly, case sensitive)
4. Secret: paste the key
5. Click **"Add secret"**

**Do not paste the key into this chat.** Tell me only that it is set, and I will confirm the secret
exists by name (GitHub exposes names, never values).

Once it exists I can settle the open `DAY_RANGE` question, which the API documentation contradicts
itself on: the parameter table says a valid range of 1 to 5 while the worked example on the same page
uses 7. I will determine the real ceiling by request and record it.

---

## Step 3. Decide D1, the unit of comparison

Not a browser step, but it blocks `score.py` and the Tier 0 aggregation, so it belongs in this list.

Read **`docs/DECISION_D1.md`**. It sets out three options, recommends Option B with the reasoning,
and spells out what each one does to the `baseline_quality` thresholds. Tick a box and tell me.

The short version: score the **cell's trailing 28 day total** against a baseline of trailing 28 day
totals keyed `(h3_r5, week_of_year)`, so the observed value and the norm are the same quantity. The
alternative that keeps calendar months leaves the detector systematically blind for the first week of
every month.

Nothing stops while this is open except the aggregation step itself.

---

## Step 4. Start the VIIRS Nightfire licence now, although it is Phase 2

It gates the `gas_flaring` training labels, which gate the Family A classifier. It is **a signed
agreement with a human turnaround time**, so starting it now costs you about ten minutes and buys
weeks later. Both `DATA_SOURCES.md` and `ROADMAP.md` say to start it during Phase 1 for this reason.

1. Go to **https://eogdata.mines.edu/products/vnf/**
2. Register for an account (registration is now mandatory; EOG describes it as a security change).
3. Request the **no cost one year academic licence agreement**. It is a document that must be signed
   and returned, not a click-through.
4. Sign and return it.

Tell me the date you submitted it, so that if the classifier work arrives before the licence does, we
can see whether it is actually late or merely slower than hoped.

Use **V4.0**, operational since 2025-07-01, and prefer its NOAA-20 and NOAA-21 streams for consistency
with the chosen FIRMS backbone. I will handle that in code; it is here so the request you submit
covers the right product.

---

## Step 5. Arming the thermal family, when the pipeline is ready

**Not yet, and not without you saying so.** I will not arm anything until you do.

When the ingest, clustering, scoring and emit path are built and tested, I will ask. Arming is two
repository variables, and the browser path is:

1. **https://github.com/dhairyabhosale/terraview24/settings/variables/actions**
2. **"New repository variable"**, name `PIPELINE_ENABLED`, value `true`
3. **"New repository variable"**, name `ENABLE_THERMAL`, value `true`

One family at a time, deliberately. With a single family armed, any change in behaviour has one
candidate explanation rather than four.

---

## Order, and what blocks what

| Step | Do when | Blocks |
|---|---|---|
| 1a, 1b Earthdata and the 2021 probe | **Now** | The Tier 0 baseline, and therefore every sigma |
| 2 FIRMS MAP_KEY | Now, two minutes | Live ingest, and the `DAY_RANGE` question |
| 3 Decide D1 | Now, after reading the brief | The aggregation step and `score.py` |
| 4 Nightfire licence | Now, because of the turnaround | Phase 2 classifier only |
| 1c The remaining four years | After I confirm the 2021 delivery | Completing the baseline |
| 5 Arming | When I ask, not before | Live detections |

Steps 1a, 1b, 2, 3 and 4 are independent of each other. You can do all five in one sitting, and none
of them waits on me.

---

## What I will be doing meanwhile

None of this needs you:

- FIRMS ingestion on NOAA-20, with NOAA-21 and MODIS for corroboration, with retry and backoff
- DBSCAN clustering over scaled space and time, with the time scaling constant tuned against known
  multi day fires
- The registry, cross run event matching, and the frozen `event_id`
- Corroboration with typed independence, and the MODIS degraded mode defined in the same commit
- The emit layer, and the merge of per family files
- Frontend steps 1 through 6 of `INTERACTION_SPEC` section 12, built against the fixtures

I will not write `score.py` until D1 is settled, and I will not build the Tier 0 aggregation until the
archive arrives.
