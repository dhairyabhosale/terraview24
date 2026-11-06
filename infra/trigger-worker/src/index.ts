/**
 * terraview24 trigger Worker.
 *
 * GitHub's `schedule` event is best effort, and it was measured rather than
 * assumed. Against a control repository over 68.5 days it delivered 99.3
 * percent of windows but with a 4.68 hour MEDIAN delay. Against this project it
 * delivered 3.9 to 5.3 percent of windows for high frequency crons. The delay
 * sits in run creation, not in a runner queue, so nothing inside a repository
 * can shorten it. See ARCHITECTURE.md section 1a.
 *
 * So an external timer calls `workflow_dispatch`, which was measured at 2.4 to
 * 3.8 seconds from POST to run creation. GitHub `schedule` stays in every
 * workflow as a fallback, because a late run beats no run.
 *
 * ONE cron trigger, every 5 minutes. Which cadences are due is decided here, in
 * code, so the schedule is versioned and testable instead of being six entries
 * in a dashboard.
 */

import { isDue, parseCron } from "./cron.ts";
import {
  type DispatchResult,
  dispatchWorkflow,
  isoSeconds,
} from "./dispatch.ts";
import { armedWorkflows, schedule } from "./schedule.ts";

export type Env = {
  /**
   * Fine grained PAT, Actions: write on this repo only, 90 day expiry.
   * Stored with `wrangler secret put GITHUB_TOKEN`. Never in the repository,
   * never in a client bundle.
   */
  GITHUB_TOKEN?: string;
  GITHUB_OWNER?: string;
  GITHUB_REPO?: string;
  GITHUB_REF?: string;
};

/** Must equal the single cron trigger in wrangler.toml. */
export const WORKER_INTERVAL_MINUTES = 5;

/**
 * The `source` input value. Deliberately hyphenated, and deliberately NOT the
 * same spelling as the `external_timer` counter key in heartbeat.json: the
 * pipeline maps one to the other in exactly one place, and an unrecognised
 * value counts as `manual`, so a typo here fails closed rather than inventing
 * an unassisted write.
 */
export const DISPATCH_SOURCE = "external-timer";

export const DEFAULTS = {
  owner: "dhairyabhosale",
  repo: "terraview24",
  ref: "main",
} as const;

export function dueWorkflows(now: Date, intervalMinutes = WORKER_INTERVAL_MINUTES) {
  return armedWorkflows(schedule).filter((entry) =>
    isDue(parseCron(entry.cron), now, intervalMinutes),
  );
}

export async function runScheduled(
  now: Date,
  env: Env,
  fetchImpl?: typeof fetch,
): Promise<DispatchResult[]> {
  if (!env.GITHUB_TOKEN) {
    // Expected on the very first deploy, before `wrangler secret put` has run.
    // Logged rather than thrown: a Worker that throws on every tick produces an
    // error rate that hides the real failure when one arrives.
    console.warn(
      "[trigger] GITHUB_TOKEN is not set. No dispatch attempted. " +
        "Run: wrangler secret put GITHUB_TOKEN",
    );
    return [];
  }

  const due = dueWorkflows(now);

  // Logged on every tick, including quiet ones. A tick that records "nothing
  // due" is what distinguishes a Worker that is running and idle from a Worker
  // that has stopped, and that distinction took hours to establish on
  // attempt 1.
  console.log(
    `[trigger] tick ${isoSeconds(now)} armed=${armedWorkflows(schedule).length} due=${due.length}` +
      (due.length ? ` -> ${due.map((d) => d.file).join(", ")}` : ""),
  );

  const results: DispatchResult[] = [];
  for (const entry of due) {
    const result = await dispatchWorkflow(
      { workflowFile: entry.file, scheduledFor: now },
      {
        owner: env.GITHUB_OWNER ?? DEFAULTS.owner,
        repo: env.GITHUB_REPO ?? DEFAULTS.repo,
        ref: env.GITHUB_REF ?? DEFAULTS.ref,
        token: env.GITHUB_TOKEN,
        source: DISPATCH_SOURCE,
        fetchImpl,
      },
    );
    results.push(result);

    if (result.ok) {
      console.log(
        `[trigger] dispatched ${result.workflowFile} scheduled_for=${result.scheduledFor} ` +
          `post_ms=${result.durationMs}`,
      );
    } else {
      console.error(
        `[trigger] FAILED ${result.workflowFile} scheduled_for=${result.scheduledFor} ` +
          `post_ms=${result.durationMs} ${result.error}`,
      );
    }
  }

  return results;
}

export default {
  async scheduled(event: { scheduledTime: number }, env: Env): Promise<void> {
    await runScheduled(new Date(event.scheduledTime), env);
  },

  /**
   * The fetch handler MUST NOT dispatch anything.
   *
   * A URL that can fire the pipeline is a public button for running it.
   * `workers_dev = false` in wrangler.toml means no public URL exists at all,
   * and this handler is the second line of defence in case a route is ever
   * added by accident. It is intentionally inert.
   */
  async fetch(): Promise<Response> {
    return new Response(
      "This Worker is a timer. It has no HTTP interface by design: a URL that " +
        "can fire the pipeline is a public button for running it.\n",
      { status: 404, headers: { "content-type": "text/plain; charset=utf-8" } },
    );
  },
};
