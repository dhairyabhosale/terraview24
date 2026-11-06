# The `data` branch

This is an **orphan branch**. It shares no history with `main` and it holds no
source code. The pipeline writes static JSON here; a static frontend reads it
over the CDN. There is no application server and no database.

Do not merge this branch into anything. Do not branch from it.

## Why the pipeline writes to a branch and not to `main`

Pipeline commits would otherwise bury the source history. At the Phase 1
cadence this branch receives dozens of commits a day, and `git log` on `main`
has to stay readable.

## Why `vercel.json` is committed here

**Vercel builds every branch by default, including this one.** On the first
attempt that produced a failed build for every single heartbeat write, roughly
96 per day, which buried the real failures among the noise.

Vercel reads `vercel.json` **from the branch being deployed**, not from the
default branch, so disabling deployments for this branch requires the file to
exist on this branch. That is the only reason a frontend config file lives on a
data branch.

## What lives here

```
heartbeat.json              when the last write happened and what caused it
events/live.json            merged pin set, hard cap 3000 features
events/live.<family>.json   per family, written by exactly one workflow
events/detail/<id>.json     lazy loaded, fetched on pin click only
registry/<family>.json      pipeline internal, one per family
meta.json                   merged run status, counts, freshness
meta.<family>.json          per family
layers/                     polygons and surface fields
archive/YYYY-MM.json        expired events
```

Schemas are in `docs/DATA_CONTRACTS.md` on `main`. That file is the only
coupling between the pipeline and the frontend.

## Why files are split per family

Each writing workflow owns its own files and touches nothing else. Concurrency
is handled by an optimistic fetch, rebase and retry push rather than a lock,
because a GitHub Actions concurrency group holds only one pending run and a
shared group would silently drop dispatches. Two workflows writing one file
would turn every overlapping run into a rebase conflict.

`live.json` and `meta.json` are derived: they are rebuilt from whichever per
family files exist, as the last step of every write. The frontend reads only the
merged files.

See `docs/ARCHITECTURE.md` section 9a on `main`.

## Reading it

```
https://raw.githubusercontent.com/dhairyabhosale/terraview24/data/heartbeat.json
```

Use `raw.githubusercontent.com`, not jsDelivr: jsDelivr caches for 7 days in the
browser and 12 hours at the edge, so an hourly value would look dead for up to
half a day.

`raw` enforces a **300 second edge cache floor** and nothing bypasses it. A
never before requested query string still returns a cache HIT, because the edge
keys on the path. So a write becomes visible within roughly 5 to 6 minutes, not
instantly. That is the platform, not a fault.
