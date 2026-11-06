/**
 * Worker behaviour, alignment with the workflow files, and the safety rules.
 * No network: `fetch` is stubbed throughout.
 *
 * The alignment test is the one ARCHITECTURE.md section 1a specifically asks
 * for. Without it, the Worker can POST to a workflow that does not accept
 * dispatches, GitHub answers 404, and the only symptom is that the pipeline
 * quietly stops. That failure is indistinguishable from the scheduler
 * flakiness this whole component exists to work around, which is exactly why
 * it has to be caught in a test instead of in production.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";

import { parseCron } from "../src/cron.ts";
import { USER_AGENT, dispatchUrl, isoSeconds } from "../src/dispatch.ts";
import worker, {
  DEFAULTS,
  DISPATCH_SOURCE,
  WORKER_INTERVAL_MINUTES,
  dueWorkflows,
  runScheduled,
  type Env,
} from "../src/index.ts";
import { armedWorkflows, schedule } from "../src/schedule.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..", "..", "..");
const WORKFLOW_DIR = join(REPO_ROOT, ".github", "workflows");

const utc = (iso: string) => new Date(`${iso}Z`);

function readWorkflow(file: string): string {
  return readFileSync(join(WORKFLOW_DIR, file), "utf8");
}

function stubFetch(
  responses: Array<{ status: number; body?: string }>,
): { impl: typeof fetch; calls: Array<{ url: string; init: RequestInit }> } {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  let index = 0;
  const impl = (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init: init ?? {} });
    const next = responses[Math.min(index, responses.length - 1)];
    index += 1;
    return new Response(next.body ?? null, { status: next.status });
  }) as unknown as typeof fetch;
  return { impl, calls };
}

// ---------------------------------------------------------------------------
// Alignment: every cadence the Worker can fire has a matching workflow
// ---------------------------------------------------------------------------

describe("alignment with the workflow files", () => {
  it("has at least one armed workflow, so the checks below are not vacuous", () => {
    assert.ok(armedWorkflows().length >= 1);
  });

  it("every workflow the Worker can fire exists on disk", () => {
    for (const entry of armedWorkflows()) {
      assert.doesNotThrow(
        () => readWorkflow(entry.file),
        `${entry.file} is armed in trigger-schedule.json but does not exist. ` +
          `The Worker would POST to it and get a 404.`,
      );
    }
  });

  it("every workflow the Worker can fire declares workflow_dispatch", () => {
    for (const entry of armedWorkflows()) {
      const text = readWorkflow(entry.file);
      assert.match(
        text,
        /workflow_dispatch:/,
        `${entry.file} has no workflow_dispatch trigger, so the fast path cannot work`,
      );
    }
  });

  it("every workflow the Worker can fire accepts the source and scheduled_for inputs", () => {
    for (const entry of armedWorkflows()) {
      const text = readWorkflow(entry.file);
      assert.match(text, /^\s+source:/m, `${entry.file} missing source input`);
      assert.match(
        text,
        /^\s+scheduled_for:/m,
        `${entry.file} missing scheduled_for input, so dispatch_lag_seconds cannot ` +
          `be computed and dispatch_source would be an unfalsifiable claim`,
      );
    }
  });

  it("every cron in the schedule parses", () => {
    for (const entry of schedule.workflows) {
      assert.doesNotThrow(() => parseCron(entry.cron), `${entry.file}: ${entry.cron}`);
    }
  });

  it("the Worker interval matches the single cron trigger in wrangler.toml", () => {
    // The due window is derived from WORKER_INTERVAL_MINUTES. If wrangler fires
    // less often than the window, firings are missed; more often, they double.
    const toml = readFileSync(join(HERE, "..", "wrangler.toml"), "utf8");
    const match = toml.match(/crons\s*=\s*\[\s*"([^"]+)"\s*\]/);
    assert.ok(match, "wrangler.toml must declare exactly one cron trigger");

    const cron = parseCron(match![1]);
    const step = cron.minute.values[1] - cron.minute.values[0];
    assert.equal(
      step,
      WORKER_INTERVAL_MINUTES,
      `wrangler.toml fires every ${step} min but the code assumes ${WORKER_INTERVAL_MINUTES}`,
    );
    assert.equal(cron.minute.values.length, 60 / WORKER_INTERVAL_MINUTES);
  });

  it("declares exactly one cron trigger, not one per cadence", () => {
    const toml = readFileSync(join(HERE, "..", "wrangler.toml"), "utf8");
    const crons = toml.match(/crons\s*=\s*\[([^\]]*)\]/);
    assert.ok(crons);
    const entries = crons![1].split(",").filter((s) => s.trim().length > 0);
    assert.equal(entries.length, 1, "the schedule lives in code, not in the dashboard");
  });
});

// ---------------------------------------------------------------------------
// Gating: unarmed workflows are never dispatched
// ---------------------------------------------------------------------------

describe("gating", () => {
  it("only heartbeat is armed in Phase 0", () => {
    assert.deepEqual(
      armedWorkflows().map((e) => e.file),
      ["heartbeat.yml"],
    );
  });

  it("never dispatches an unarmed workflow, even when its cron is due", () => {
    // ingest-thermal is "0 */6 * * *", so midnight is its cron time. It must
    // still not be dispatched: creating skipped runs every few minutes for a
    // switched off pipeline buries the runs that matter in the Actions tab.
    const thermal = schedule.workflows.find((e) => e.file === "ingest-thermal.yml");
    assert.ok(thermal);
    assert.equal(thermal!.armed, false);

    const due = dueWorkflows(utc("2026-11-06T00:00:00"));
    assert.ok(!due.some((e) => e.file === "ingest-thermal.yml"));
  });

  it("every unarmed workflow names a gate variable", () => {
    for (const entry of schedule.workflows) {
      if (entry.armed) continue;
      assert.ok(
        entry.gate_variable,
        `${entry.file} is unarmed but names no gate variable, so arming it would be ` +
          `an undocumented edit rather than a variable change`,
      );
    }
  });
});

// ---------------------------------------------------------------------------
// Due calculation
// ---------------------------------------------------------------------------

describe("dueWorkflows", () => {
  it("returns heartbeat on the hour", () => {
    const due = dueWorkflows(utc("2026-11-06T09:00:00"));
    assert.deepEqual(due.map((e) => e.file), ["heartbeat.yml"]);
  });

  it("returns heartbeat anywhere in the five minute window after the hour", () => {
    for (const minute of ["00", "01", "02", "03", "04"]) {
      const due = dueWorkflows(utc(`2026-11-06T09:${minute}:00`));
      assert.equal(due.length, 1, `minute ${minute}`);
    }
  });

  it("returns nothing mid hour", () => {
    assert.deepEqual(dueWorkflows(utc("2026-11-06T09:30:00")), []);
    assert.deepEqual(dueWorkflows(utc("2026-11-06T09:47:00")), []);
  });

  it("fires heartbeat exactly once per hour across a full day of ticks", () => {
    let fired = 0;
    const start = utc("2026-11-06T00:00:00").getTime();
    for (let i = 0; i < (24 * 60) / WORKER_INTERVAL_MINUTES; i += 1) {
      const now = new Date(start + i * WORKER_INTERVAL_MINUTES * 60_000);
      fired += dueWorkflows(now).length;
    }
    assert.equal(fired, 24, "hourly heartbeat over 24 hours");
  });
});

// ---------------------------------------------------------------------------
// Dispatch
// ---------------------------------------------------------------------------

describe("dispatch", () => {
  const env: Env = { GITHUB_TOKEN: "test-token" };

  it("posts to the workflow_dispatch endpoint with the right shape", async () => {
    const { impl, calls } = stubFetch([{ status: 204 }]);
    const results = await runScheduled(utc("2026-11-06T09:00:00"), env, impl);

    assert.equal(results.length, 1);
    assert.equal(results[0].ok, true);
    assert.equal(calls.length, 1);
    assert.equal(
      calls[0].url,
      dispatchUrl(DEFAULTS.owner, DEFAULTS.repo, "heartbeat.yml"),
    );

    assert.equal(calls[0].init.method, "POST");
    const headers = calls[0].init.headers as Record<string, string>;
    assert.equal(headers.Authorization, "Bearer test-token");
    assert.equal(headers["X-GitHub-Api-Version"], "2022-11-28");
    assert.equal(headers["User-Agent"], USER_AGENT);

    const body = JSON.parse(calls[0].init.body as string);
    assert.equal(body.ref, DEFAULTS.ref);
    assert.equal(body.inputs.source, DISPATCH_SOURCE);
    assert.equal(body.inputs.scheduled_for, "2026-11-06T09:00:00Z");
  });

  it("sends the hyphenated source value, which the pipeline maps to a counter key", () => {
    // The pipeline counts anything it does not recognise as `manual`, so this
    // spelling is load bearing: a typo here would fail closed and the Phase 0
    // criterion would never register an unassisted write.
    assert.equal(DISPATCH_SOURCE, "external-timer");
  });

  it("dispatches nothing when nothing is due", async () => {
    const { impl, calls } = stubFetch([{ status: 204 }]);
    const results = await runScheduled(utc("2026-11-06T09:30:00"), env, impl);
    assert.deepEqual(results, []);
    assert.equal(calls.length, 0);
  });

  it("dispatches nothing and does not throw when the token is absent", async () => {
    // Expected between `wrangler deploy` and `wrangler secret put`. A Worker
    // that throws every 5 minutes produces an error rate that hides the real
    // failure when one arrives.
    const { impl, calls } = stubFetch([{ status: 204 }]);
    const results = await runScheduled(utc("2026-11-06T09:00:00"), {}, impl);
    assert.deepEqual(results, []);
    assert.equal(calls.length, 0);
  });

  it("reports a 401 as a failure and explains the silent token expiry", async () => {
    const { impl } = stubFetch([{ status: 401, body: '{"message":"Bad credentials"}' }]);
    const results = await runScheduled(utc("2026-11-06T09:00:00"), env, impl);

    assert.equal(results[0].ok, false);
    assert.equal(results[0].status, 401);
    assert.match(results[0].error!, /expired/);
    assert.match(results[0].error!, /wrangler secret put GITHUB_TOKEN/);
  });

  it("explains a 404 as a missing workflow_dispatch rather than a dead repo", async () => {
    const { impl } = stubFetch([{ status: 404, body: '{"message":"Not Found"}' }]);
    const results = await runScheduled(utc("2026-11-06T09:00:00"), env, impl);
    assert.match(results[0].error!, /workflow_dispatch/);
  });

  it("survives a transport failure without throwing", async () => {
    const impl = (async () => {
      throw new TypeError("network unreachable");
    }) as unknown as typeof fetch;
    const results = await runScheduled(utc("2026-11-06T09:00:00"), env, impl);
    assert.equal(results[0].ok, false);
    assert.equal(results[0].status, 0);
    assert.match(results[0].error!, /transport failure/);
  });

  it("records a duration for every attempt, so a slow POST is visible", async () => {
    const { impl } = stubFetch([{ status: 204 }]);
    const results = await runScheduled(utc("2026-11-06T09:00:00"), env, impl);
    assert.equal(typeof results[0].durationMs, "number");
    assert.ok(results[0].durationMs >= 0);
  });

  it("honours owner, repo and ref overrides from the environment", async () => {
    const { impl, calls } = stubFetch([{ status: 204 }]);
    await runScheduled(utc("2026-11-06T09:00:00"), {
      GITHUB_TOKEN: "t",
      GITHUB_OWNER: "someone",
      GITHUB_REPO: "elsewhere",
      GITHUB_REF: "trunk",
    }, impl);
    assert.equal(calls[0].url, dispatchUrl("someone", "elsewhere", "heartbeat.yml"));
    assert.equal(JSON.parse(calls[0].init.body as string).ref, "trunk");
  });
});

// ---------------------------------------------------------------------------
// The safety rules
// ---------------------------------------------------------------------------

describe("no public button", () => {
  it("the fetch handler never dispatches and returns 404", async () => {
    // A URL that can fire the pipeline is a public button for running it.
    const response = await worker.fetch();
    assert.equal(response.status, 404);
    assert.match(await response.text(), /no HTTP interface by design/);
  });

  it("wrangler.toml disables the workers.dev address", () => {
    const toml = readFileSync(join(HERE, "..", "wrangler.toml"), "utf8");
    assert.match(toml, /^workers_dev\s*=\s*false\s*$/m);
  });

  it("wrangler.toml does not declare the token as a plain var", () => {
    // A secret in [vars] is committed in plaintext. It must only ever arrive
    // through `wrangler secret put`.
    const toml = readFileSync(join(HERE, "..", "wrangler.toml"), "utf8");
    const varsBlock = toml.split("[vars]")[1] ?? "";
    assert.ok(
      !/GITHUB_TOKEN\s*=/.test(varsBlock),
      "GITHUB_TOKEN must be a Worker secret, never a committed var",
    );
  });

  it("no source file contains a token shaped literal", () => {
    for (const file of ["index.ts", "dispatch.ts", "cron.ts", "schedule.ts"]) {
      const text = readFileSync(join(HERE, "..", "src", file), "utf8");
      assert.ok(
        !/\bgh[pousr]_[A-Za-z0-9]{20,}/.test(text),
        `${file} appears to contain a GitHub token literal`,
      );
      assert.ok(
        !/\bgithub_pat_[A-Za-z0-9_]{20,}/.test(text),
        `${file} appears to contain a fine grained token literal`,
      );
    }
  });
});

// ---------------------------------------------------------------------------
// A guard that fails where it should, so the suite cannot pass vacuously
// ---------------------------------------------------------------------------

describe("negative controls", () => {
  it("isoSeconds produces the exact format the workflow parses", () => {
    assert.equal(isoSeconds(utc("2026-11-06T09:00:00")), "2026-11-06T09:00:00Z");
    // Milliseconds must be dropped: Python's fromisoformat handles them, but
    // the contract says seconds and a drifting format is a future bug.
    assert.equal(isoSeconds(new Date(Date.UTC(2026, 10, 6, 9, 0, 0, 456))), "2026-11-06T09:00:00Z");
  });

  it("the alignment check actually fails for a workflow without workflow_dispatch", () => {
    // Proves the assertion above can fail. Without this, the alignment tests
    // would still pass if readWorkflow silently returned an empty string or if
    // armedWorkflows returned nothing.
    const text = "name: bad\non:\n  schedule:\n    - cron: '0 * * * *'\n";
    assert.throws(() => assert.match(text, /workflow_dispatch:/));
  });

  it("the gate check actually fails for a workflow claiming to be armed with no file", () => {
    assert.throws(() => readWorkflow("does-not-exist.yml"));
  });
});
