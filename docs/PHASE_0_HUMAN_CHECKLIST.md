# PHASE 0: ACTIONS ONLY THE HUMAN CAN DO

> Part of the TerraView doc set. Order follows `ROADMAP.md`, "Human actions in Phase 0".
>
> `terraview24` below is the single project name, pending the decision in step 0. Once decided it is
> substituted everywhere: display title, GitHub repo, `package.json`, Vercel project, production host.

**How to read this.** Each step gives the command or click path, what to observe, and what to send back.
Where a CLI command exists it is listed first, because a command's output is evidence and a dashboard
read back is not (ground rule 12). Click paths were written against the GitHub, Vercel and Cloudflare
UIs as of this agent's knowledge cutoff (May 2026) and those UIs drift, so if a label does not match,
prefer the CLI route and tell me what you actually saw.

**Do not paste any token or secret into the chat.** Tokens go only into the prompt of the command that
consumes them. If one is ever pasted into chat, treat it as compromised and revoke it.

---

## Step 0. The name. SETTLED, 2026-11-06

**Decision: the name is `terraview24`.** Display title TerraView24, repo
`dhairyabhosale/terraview24`, `package.json` name `terraview24`, Vercel project `terraview24`,
production host `terraview24.vercel.app`. One name, five places. The doc set has been updated to match.

Nothing is required from you in this step. It is recorded here because the reasoning is the evidence
for a name that differs from the documented default, and because step 3.4 is still the test that
confirms it.

`terraview24.vercel.app` was probed on 2026-11-06 and returned `x-vercel-error: DEPLOYMENT_NOT_FOUND`
with a 107 byte body, matching a known free control exactly. `github.com/dhairyabhosale/terraview24` is
free, and `terraview24` is a valid `package.json` name.

### Why not `terraview`, the documented default

Measured by live request on 2026-11-06:

| Host | Result | Reading |
|---|---|---|
| `terraview.vercel.app` | `HTTP 404`, `x-vercel-error: NOT_FOUND`, 79 bytes | **Taken.** A deployment is assigned to this host |
| `terrawatch.vercel.app` | `HTTP 200` | **Taken, and serving a live site** |
| control, random subdomain | `HTTP 404`, `x-vercel-error: DEPLOYMENT_NOT_FOUND`, 107 bytes | Free |
| `terraview-earth`, `terraview-app`, `terraview-globe`, `terraviewearth`, `terranorm`, `terraviewhq`, `viewterra`, `terraview-io` | all `DEPLOYMENT_NOT_FOUND` | Free |

`github.com/dhairyabhosale/<candidate>` was free for every candidate above, including `terraview`
itself, so the constraint was the Vercel host alone. `terraview.vercel.app` is most likely held by the
discarded first attempt, and `AGENT_PROMPT.md` notes that a deleted project's host can take a while to
free up. Reclaiming it was offered and `terraview24` was chosen instead, which avoids waiting on a
release of unknown duration.

**What the probe does and does not prove.** `DEPLOYMENT_NOT_FOUND` proves no deployment is currently
assigned to that host. It does not prove that no Vercel project anywhere holds the name without a
production deployment. The authoritative test is step 3.4 below, assigning the host and seeing it
attach with no suffix. Until 3.4 passes, the name is probable and not confirmed.

**Vercel scope, settled:** personal Hobby scope. Deployment Protection on team scopes returns
`HTTP 302` to a sign in page on alias hosts (`ARCHITECTURE.md` section 9), and this project needs a
publicly reachable production host.

**Trigger layer, settled:** build the Cloudflare Worker, which is the `ARCHITECTURE.md` section 1a
default. Steps 4, 5 and 6 below are therefore live and not optional.

---

## Step 1. Create the empty public GitHub repo. DONE 2026-11-06

**Done by the agent**, because `gh` was already authenticated as `dhairyabhosale`. Nothing needed from
you. API response:

```
full_name:      dhairyabhosale/terraview24
visibility:     public
default_branch: main
size:           0
created_at:     2026-11-06T05:41:51Z
```

https://github.com/dhairyabhosale/terraview24

---

## Step 1a. Grant `gh` the `workflow` scope. NEEDED FROM YOU

This step was missing from the original `ROADMAP.md` list. It was found by reading the token's scopes
before attempting the first push rather than after it.

The authenticated token carries `gist, read:org, repo`. **It does not carry `workflow`.** GitHub
refuses any push from an OAuth token that creates or updates a file under `.github/workflows/`, so
without this scope the entire scaffold cannot be pushed, and the failure arrives as a rejected push
rather than as anything resembling a permissions screen.

```bash
gh auth refresh -h github.com -s workflow
```

It opens a browser and asks you to authorize the additional scope. Then confirm:

```bash
gh auth status
curl -s -D - -o /dev/null -H "Authorization: token $(gh auth token)" https://api.github.com/user | grep -i x-oauth-scopes
```

I expect `workflow` to appear in the scope list. Tell me when it does and I will push.

---

## Step 1b. Reference, if you ever create the repo by hand

Kept because the repo may need recreating. Do this only after the name is settled, so the repo is
never created under a name we then abandon.

**Public is not cosmetic.** On a public repo, branch rulesets (step 2) are available at no cost and
GitHub Actions on standard runners is unmetered. On a private repo both of those change.

**CLI route, preferred.** Authenticate once, then I can create the repo and the ruleset myself and show
you the API response as evidence:

```bash
gh auth login
# Choose: GitHub.com, HTTPS, authenticate in browser, and accept the default scopes
gh auth status
```

Then either let me run the next command, or run it yourself:

```bash
gh repo create dhairyabhosale/terraview24 --public \
  --description "A 3D globe surfacing human caused environmental events, detected statistically against a multi year baseline"
```

**Click path alternative.** https://github.com/new

1. Owner: `dhairyabhosale`
2. Repository name: `terraview24`
3. Visibility: **Public**
4. Leave "Add a README file" **unticked**, and .gitignore and licence both at **None**.
   The repo must be genuinely empty so the first push from this machine is the first commit.
5. "Create repository"

**Observe and send back:**

```bash
gh repo view dhairyabhosale/terraview24 --json name,visibility,isEmpty,defaultBranchRef
```

I expect `"visibility": "public"` and `"isEmpty": true`.

---

## Step 2. Branch protection ruleset on `main`. DONE 2026-11-06

**Done by the agent**, before any token exists, as the ordering requires. API response:

```
id:          26673963
name:        main-protection
target:      branch
enforcement: active
conditions:  ref_name.include = ["~DEFAULT_BRANCH"], exclude = []
rules:       deletion, non_fast_forward, required_linear_history
```

`~DEFAULT_BRANCH` means it targets `main` and nothing else, so `data` is untouched and the pipeline can
write to it freely.

**Still outstanding, and deliberately so:** the ruleset has been *created* and read back, which per
ground rule 12 is not evidence that it *works*. I will prove it by attempting a force push to `main`
(must be rejected) and a normal push to `data` (must be allowed), and report both. You also asked to
look at it once in the UI: Settings, Rules, Rulesets, `main-protection`.

---

## Step 2a. Reference, if you ever create the ruleset by hand

Order matters: `ROADMAP.md` puts this ahead of the token deliberately, so no window exists in which a
token can reach an unprotected `main`.

**It must target `main` only.** The pipeline writes to `data` constantly. A ruleset that catches `data`
will block every pipeline write, and it will present as a workflow failure rather than as a settings
mistake.

**CLI route, preferred.** I can run this once `gh auth login` is done:

```bash
gh api --method POST /repos/dhairyabhosale/terraview24/rulesets --input ruleset.json
```

with `ruleset.json` holding:

```json
{
  "name": "main-protection",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] } },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "required_linear_history" }
  ]
}
```

`non_fast_forward` is GitHub's name for "block force pushes". `~DEFAULT_BRANCH` targets `main` and
nothing else, which is why it is used in place of a literal pattern.

**Click path alternative.** Repo, Settings, Rules, Rulesets, "New ruleset", "New branch ruleset"

1. Ruleset Name: `main-protection`
2. Enforcement status: **Active**
3. Target branches: "Add target", then **"Include default branch"**.
   Do **not** choose "All branches", and do **not** add `data`.
4. Under Rules, tick exactly these three: **Restrict deletions**, **Block force pushes**,
   **Require linear history**.
5. Leave **"Require a pull request before merging" unticked.** I push scaffold commits directly to
   `main`; requiring a PR turns every commit into a human action.
6. Leave "Restrict creations" unticked, or creating the `data` branch will be blocked.
7. "Create"

**Observe and send back:**

```bash
gh api /repos/dhairyabhosale/terraview24/rulesets
```

I expect one active ruleset whose conditions name the default branch only.

---

## Step 3. Vercel: GitHub App, project, env vars, host

**3.1 Log in to the CLI.** Browser step, cannot be automated:

```bash
vercel login
vercel whoami
```

Vercel CLI 59.9.1 is already installed on this machine.

**3.2 Install the Vercel GitHub App, this repo only.** The CLI cannot do this
(`ARCHITECTURE.md` section 9). Without it, pushes to `main` do not deploy.

Click path: https://vercel.com/dashboard, "Add New...", "Project", then under
"Import Git Repository" click "Adjust GitHub App Permissions" (or "Configure GitHub App" or
"Install GitHub App", depending on whether you have used Vercel with GitHub before). On the GitHub
page that opens:

1. Choose **"Only select repositories"**. Do not grant "All repositories".
2. Select `terraview24`.
3. "Install" or "Save".

**3.3 Create the project.** Back in Vercel's import screen, import `terraview24`, then:

1. Project Name: exactly `terraview24`. Vercel derives the host from this, so a typo here becomes the host.
2. Framework Preset: **Vite**
3. **Leave "Root Directory" empty.** The app lives in `web/`, and the root `vercel.json` I commit
   carries `installCommand`, `buildCommand` and `outputDirectory`. Keeping build config in a
   committed file rather than a dashboard field means it is versioned and reviewable.
4. Do not deploy yet if the screen lets you add env vars first. Add them per 3.3b, then deploy.
   If it deploys immediately, that is fine: the first build will fail or produce a page with no data
   source, and 3.3b plus a redeploy fixes it. Expect that and do not treat it as a fault.

**3.3b Environment variables.** Project Settings, Environment Variables. Add both, ticking
**Production, Preview and Development** for each:

| Name | Value |
|---|---|
| `VITE_DATA_OWNER` | `dhairyabhosale` |
| `VITE_DATA_REPO` | `terraview24` |

These are `VITE_` prefixed, so they are baked into the client bundle at **build** time, not read at
runtime. Two consequences: they are not secrets (they are public repo coordinates, which is correct and
by design, see `ARCHITECTURE.md` section 8), and changing one later needs a redeploy, not just a
refresh.

**3.4 Confirm the host, which is the real step 0 test.** Project Settings, Domains.

- **Pass:** `terraview24.vercel.app` is listed and assigned, with no suffix.
- **Fail:** the assigned host carries a suffix, for example `terraview24-a1b2c3.vercel.app` or
  `terraview24-dhairyabhosale.vercel.app` as the only entry. That means the bare name was taken after all.
  **Stop and tell me.** Do not proceed: this is the exact failure `ARCHITECTURE.md` section 10 exists
  to prevent, and it is cheap now and an outage later.

Vercel also assigns extra alias hosts (branch and scope aliases) alongside the bare one. Those are
expected. What matters is that the bare `terraview24.vercel.app` is present.

**3.5 Confirm the production host is publicly reachable.** Project Settings, Deployment Protection.
Ensure the **production** host is not behind Vercel Authentication. Then verify by observation, which
is the part that counts:

1. Open `https://terraview24.vercel.app` in a **private or incognito window**, signed out of Vercel.
2. It must render, not redirect to a Vercel sign in page.

Share only the production host, never a team scoped alias.

**Send back:** the exact contents of the Domains list, and the result of the private window check.

---

## Step 4. Fine grained token, Actions write only, 90 days

Only after step 2 is active.

Click path: https://github.com/settings/personal-access-tokens/new
(or Settings, Developer settings, Personal access tokens, Fine-grained tokens, "Generate new token")

1. Token name: `terraview24-trigger-dispatch`
2. Resource owner: `dhairyabhosale`
3. Expiration: **Custom**, then **90 days** from today. Write the exact date down now.
4. Repository access: **"Only select repositories"**, then select `terraview24` and nothing else.
5. Permissions, Repository permissions: set **Actions** to **"Read and write"**. Nothing else.
   "Metadata: Read-only" will be added automatically and is mandatory; that is expected and is not
   extra privilege. The whole point of `workflow_dispatch` over `repository_dispatch` is that this
   token cannot push code (`ARCHITECTURE.md` section 1a).
6. "Generate token", then copy it. GitHub shows it once.
7. **Before leaving the page**, create a calendar reminder for the expiry date, titled something like
   "`terraview24` trigger token expires, rotate it". `ARCHITECTURE.md` is blunt about why: on expiry every
   dispatch returns 401 and the pipeline silently falls back to roughly one run per 4 to 5 hours,
   which looks like a slightly stale page rather than an outage. A reminder is the only thing standing
   between that and a month of quietly wrong data. Set it a week early.

Keep the token in your clipboard or a password manager for step 5. **Do not paste it into this chat.**

---

## Step 5. Cloudflare account and Worker deploy

Only after I have built and tested `infra/trigger-worker/`, which is part 0c. I will tell you when it
is ready, and its README will repeat these commands.

**5.1 Create a free Cloudflare account.** https://dash.cloudflare.com/sign-up
Email and password, then verify the email. **No domain and no payment card are required.** Cron
Triggers are on the free plan. Our cadence is one invocation every 5 minutes, which is 288 per day
against a free allowance of 100,000 requests per day.

**5.2 Deploy.** From the repo root:

```bash
cd infra/trigger-worker
npx wrangler login
npx wrangler deploy
npx wrangler secret put GITHUB_TOKEN
```

`wrangler login` opens a browser, where you click "Allow". `wrangler secret put` prompts for the value:
paste the step 4 token there and press Enter.

`wrangler` is not installed on this machine, hence `npx`. Order note: deploying before the secret
exists means the first few cron firings get `HTTP 401` from GitHub. That is harmless, and it is in fact
a useful negative test, so do not be alarmed by it. Secrets apply immediately with no redeploy needed.

**5.3 Confirm two things in the `wrangler deploy` output**, per `ROADMAP.md` step 5:

- The **cron trigger** is listed, showing `*/5 * * * *`.
- **No `workers.dev` address** appears. `wrangler.toml` sets `workers_dev = false`, because a public
  URL that can fire the pipeline is a public button for running it (`ARCHITECTURE.md` section 1a).
  If you see a `*.workers.dev` URL in the output, stop and tell me.

Dashboard cross check: Cloudflare dashboard, "Compute (Workers)" or "Workers & Pages", open the
Worker, then Settings. Triggers shows the cron schedule; Domains and Routes shows none.

**Send back:** the full `wrangler deploy` output, with nothing redacted except any token (there should
not be one in it).

---

## Step 6. Watch three consecutive Worker triggered writes

This is your sign off, not mine. I will measure the dispatch to `created_at` lag three times and report
the numbers (part 0c), but `ROADMAP.md` asks you to watch three consecutive Worker triggered writes
land before trusting the trigger.

What to look at, once I tell you the page is live:

1. `https://terraview24.vercel.app` and watch the "Run" number and the last trigger change on their own.
2. The raw payload, which is the source of truth behind the page:
   `https://raw.githubusercontent.com/dhairyabhosale/terraview24/data/heartbeat.json`

What good looks like: `triggered_by` is `workflow_dispatch`, `dispatch_source` is `external-timer`,
and `dispatch_lag_seconds` is in the single digits to low tens. The measured `repository_dispatch`
baseline from attempt 1 was 2.4 to 3.8 seconds from POST to run creation, and 8 to 13 seconds from POST
to the commit landing on `data`.

**Two expectation setters, so that normal behaviour is not diagnosed as a fault:**

- The page will not update instantly. `raw.githubusercontent.com` enforces a **300 second edge cache
  floor** and nothing bypasses it, not even an unused query string (`ARCHITECTURE.md` section 7). So a
  write appears on the page within roughly 5 to 6 minutes, not immediately. That is the platform, not
  a bug.
- `dispatch_source` is a **claim**, not a proof. GitHub cannot tell the Worker from you running `curl`,
  because the sender is the same token owner. The checkable part is `dispatch_lag_seconds`.

---

## Step 7. Source credentials, as their phases begin

Not needed to finish Phase 0, with one exception called out below.

**7.1 FIRMS `MAP_KEY`. Worth doing now, takes about two minutes.**
https://firms.modaps.eosdis.nasa.gov/api/map_key/ , submit an email address, and the key comes back
directly (self service and immediate, verified in `DATA_SOURCES.md`).

Why now rather than in Phase 1: `ROADMAP.md` 0a includes "settle the FIRMS `DAY_RANGE` ceiling", which
is listed as `[unresolved]` because the API page states a valid range of 1 to 5 and then gives a worked
example using 7. That cannot be settled without a key, so the key is a Phase 0a input even though
`ROADMAP.md` human step 7 reads as though all source keys are later. See the flagged inconsistency in
my report. Once you have it, add it as a GitHub repo secret:

Repo, Settings, Secrets and variables, Actions, "New repository secret", name `FIRMS_MAP_KEY`.
Or: `gh secret set FIRMS_MAP_KEY --repo dhairyabhosale/terraview24`, which prompts for the value so it stays
out of your shell history.

**7.2 VIIRS Nightfire licence. Start early, it gates Phase 2 and has a turnaround.**
https://eogdata.mines.edu/products/vnf/ , register, then request the no cost one year academic licence
agreement, which must be signed and returned. `DATA_SOURCES.md` and `ROADMAP.md` both say to start this
during Phase 1 precisely so it is not the thing holding up the classifier. Nothing breaks if it waits,
but it is a signature and a human turnaround, so starting it costs you ten minutes and buys weeks.

**7.3 Everything else, when its phase begins.** I will ask for each one by name at the time, with the
exact route. For reference, the full list with sources and expiries is the credentials table at the end
of `DATA_SOURCES.md`: `GFW_API_KEY` (one year), `OPENAQ_API_KEY`, `GFW_FISHING_TOKEN`,
`IUCN_API_TOKEN`, `PROTECTED_PLANET_TOKEN` (optional), and `CDSE_CLIENT_ID` plus
`CDSE_CLIENT_SECRET` (90 day rotation, fallback route only).

No credential at all is needed for Microsoft Planetary Computer, GDELT, USGS, GDACS, or the GFW dataset
catalogue.

---

## What blocks what

| Step | Blocks |
|---|---|
| 0, the name | Everything. No code is written until the name is settled |
| 1, the repo | All of 0b: scaffold, `data` branch, first push |
| 2, the ruleset | Step 4, by deliberate ordering |
| 3, Vercel | The deployed page, and therefore the Phase 0 exit criterion |
| 4 and 5, token and Worker | The fast path to the exit criterion |
| 6 | Trusting the trigger, not reaching the exit |
| 7.1, FIRMS key | The `DAY_RANGE` item in 0a only. Not the exit |

**On the exit criterion.** Phase 0 exits when a number changes on a deployed page because a job wrote
it with no human involved. That needs steps 1 and 3 at minimum. With steps 4 and 5 done, it should
happen within minutes of the Worker's first firing. Without them it rests on GitHub's own `schedule`,
measured on the first attempt at 3.9 to 5.3 percent delivery for high frequency crons with a 4.68 hour
median delay, so it could take most of a day, and the stopping rule before calling a fault is roughly
10 hours of silence, not 90 minutes.
