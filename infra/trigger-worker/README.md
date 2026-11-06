# terraview24 trigger Worker

A Cloudflare Worker with one cron trigger. Every 5 minutes it works out which
pipeline workflows are due and calls GitHub's `workflow_dispatch` API.

**This document is written for the person deploying it.** You do not need to
read the TypeScript to deploy it safely, but you do need to check two things in
the output, and they are in step 4 below.

---

## Why this exists at all

GitHub Actions has a `schedule` trigger. It would be simpler to use it. It was
measured, and it is not good enough:

| What was measured | Result |
|---|---|
| Control repo, two 12 hour crons, 68.5 days | 272 of 274 windows ran (99.3 percent), but the delay was min 2.86 h, **median 4.68 h**, max 9.36 h |
| This project, `7,37 * * * *` | 19 windows, 1 run. **5.3 percent delivery** |
| This project, `*/15 * * * *` | 51 windows, 2 runs. **3.9 percent delivery** |
| Where the delay sits | `run_started_at` equalled `created_at` on every sampled run, so GitHub creates the run late. It is not a runner queue, and nothing inside a repository can shorten it |
| An externally triggered dispatch | POST to run creation: **2.4 s, 3.8 s, 2.9 s** |

High frequency crons are not delayed so much as mostly not delivered. The
pattern was roughly one scheduled run every 4 to 5 hours whatever the cron
expression said.

So: an external timer calls the fast path. `schedule` stays in every workflow as
a fallback, because a late run beats no run.

Full detail in `docs/ARCHITECTURE.md` section 1a.

---

## What it costs

Nothing. Cloudflare's free plan includes cron triggers. One invocation every 5
minutes is 288 per day against a free allowance of 100,000 requests per day.

No domain and no payment card are required to create the account.

---

## Deploying it

You need the fine grained GitHub token from step 4 of
`docs/PHASE_0_HUMAN_CHECKLIST.md` first: this repo only, **Actions: write**,
nothing else, 90 day expiry.

### 1. Create a free Cloudflare account

https://dash.cloudflare.com/sign-up , then verify the email.

### 2. Log in from the CLI

```bash
cd infra/trigger-worker
npx wrangler login
```

A browser opens. Click "Allow". `wrangler` is not installed globally on
purpose, hence `npx`: it pins to the version in `package.json`.

### 3. Deploy, then set the secret

```bash
npx wrangler deploy
npx wrangler secret put GITHUB_TOKEN
```

Paste the token at the prompt and press Enter. It is not echoed.

> ### STOP if a wrangler command ever prints a `github_pat_` string
>
> A fine grained token starts with `github_pat_`. `wrangler secret put` never
> echoes the value and never prints it back. So if you see a `github_pat_`
> string anywhere in a wrangler command's output, or in your shell history, or
> in a terminal scrollback you are about to share, **the token went into the
> wrong field**: most likely into the secret NAME rather than its value, or
> into a `[vars]` entry, or onto the command line as an argument.
>
> What to do, in this order:
>
> 1. **Revoke the token immediately** at
>    https://github.com/settings/personal-access-tokens . Do not try to work out
>    whether it was really exposed first. Revoking costs two minutes; a leaked
>    token with Actions write can run arbitrary workflows in the repository.
> 2. Delete the wrongly created secret or var:
>    `npx wrangler secret delete <NAME>`, and remove any `[vars]` entry from
>    `wrangler.toml` if one was added.
> 3. Mint a replacement (this repo only, Actions: Read and write, 90 days) and
>    set it again with `npx wrangler secret put GITHUB_TOKEN`, letting the
>    prompt take the value. Never pass a secret as a command line argument: it
>    lands in shell history and in process listings.
> 4. Confirm the secret list shows exactly one entry named `GITHUB_TOKEN` and
>    no value: `npx wrangler secret list`.
>
> The name matters as much as the value. The Worker reads `env.GITHUB_TOKEN`
> and nothing else, so a secret stored under any other name leaves the Worker
> with no token at all. It then logs a warning and dispatches nothing, which
> presents as a silently stale page rather than an error.

**The order is deliberate.** Deploying before the secret exists means the first
few cron firings find no token. That is harmless: the Worker logs a warning and
dispatches nothing, rather than throwing. It is also a useful negative test, so
if you see that warning in the logs, the Worker is running correctly.

Secrets apply immediately. There is no need to redeploy after setting one.

### 4. Check two things in the deploy output

This is the part that matters.

- **The cron trigger is listed**, showing `*/5 * * * *`.
- **No `workers.dev` address appears.** `wrangler.toml` sets
  `workers_dev = false`, because a URL that can fire the pipeline is a public
  button for running it. If you see a `*.workers.dev` URL, stop and say so.

Dashboard cross check, if you want one: Cloudflare dashboard, Workers, open
`terraview24-trigger`, then Settings. Triggers shows the cron; Domains and
Routes shows none.

### 5. Watch it work

```bash
npx wrangler tail
```

Every tick logs, including the quiet ones:

```
[trigger] tick 2026-11-06T09:00:00Z armed=1 due=1 -> heartbeat.yml
[trigger] dispatched heartbeat.yml scheduled_for=2026-11-06T09:00:00Z post_ms=412
[trigger] tick 2026-11-06T09:05:00Z armed=1 due=0
```

**A quiet tick is logged on purpose.** "Running and idle" and "stopped" look
identical from the outside otherwise, and telling those apart was the single
hardest diagnosis of the first attempt.

---

## What to do when it stops working

### Every dispatch returns 401

The token expired. It lasts 90 days and **expiry is silent**: the pipeline falls
back to GitHub's own cadence of roughly one run per 4 to 5 hours, which looks
like a slightly stale page rather than an outage. The page's staleness message
is the thing that will actually tell you.

Mint a new token (checklist step 4) and run `npx wrangler secret put
GITHUB_TOKEN` again. Nothing else needs redeploying.

### Every dispatch returns 404

Either the workflow file does not declare `on: workflow_dispatch`, or it is not
present on the default branch, or the token cannot see the repository. The error
message says so. `npm test` catches the first cause before deployment.

### Nothing is happening at all

Check in this order, and **do not conclude there is a fault too early**. The
stopping rule is time based, not window based: GitHub's median scheduled delay
was 4.68 hours and the worst observed was 9.36 hours, so **roughly 10 hours of
silence** is the threshold for calling a scheduler fault. Ninety quiet minutes
proves nothing. Change one thing at a time.

1. `npx wrangler tail` and wait for a tick. If ticks appear, the Worker is alive.
2. If ticks appear but no dispatch, check whether anything is actually due. Only
   armed workflows are dispatched, and in Phase 0 that is `heartbeat.yml` alone,
   hourly.
3. If dispatches succeed but no run appears, that is a GitHub side problem and
   the Worker log is your evidence. This is exactly the "dispatched but never
   ran" case the logging exists to make visible.
4. The page is expected to lag a write by about 5 to 6 minutes:
   `raw.githubusercontent.com` enforces a 300 second edge cache floor and
   nothing bypasses it, not even an unused query string.

---

## Changing the schedule

`trigger-schedule.json` at the repository root is the single source of truth,
read by this Worker, by the heartbeat payload and by the alignment tests. Edit
that file, not `wrangler.toml` and not the code.

To arm a pipeline family, set `armed: true` there, set the two repository
variables, and redeploy the Worker:

```bash
gh variable set PIPELINE_ENABLED --body true
gh variable set ENABLE_THERMAL --body true
npx wrangler deploy
```

Arm one family at a time. That is a deliberate constraint, not caution for its
own sake: it keeps the cause of any change in behaviour down to one candidate.

---

## Tests

```bash
npm test
```

No network, no credentials, no Cloudflare account needed. Run before every
deploy.

They cover the two cron quirks that are easy to implement plausibly and wrongly
(the day of month and day of week union rule, and Sunday being 0 as well as 7),
the alignment between this Worker and the workflow files on disk, that unarmed
workflows are never dispatched, that the fetch handler cannot dispatch anything,
and that no token shaped literal appears in any source file.

The suite also contains deliberate negative controls, cases asserting that a
guard fails where it should, so that it cannot pass by checking nothing.

---

## Not wanting to run this at all is a valid choice

If you would rather not have a Cloudflare account and a GitHub token, delete
this directory and accept GitHub's cadence of roughly one run per 4 to 5 hours.
The pipeline still works: `schedule` is in every workflow.

Two things then have to be true. The page must state that cadence honestly,
which it does automatically: with `EXTERNAL_TIMER_ARMED` unset, the heartbeat
declares the measured 5 hour cadence rather than an hourly one. And "real time"
stays off the page, which it should be anyway until a latency has been measured.

This trade is recorded in `docs/ARCHITECTURE.md` section 1a as an acceptable
simplification, not a degradation.
