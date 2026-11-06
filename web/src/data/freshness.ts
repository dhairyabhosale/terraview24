/**
 * The page's honest state display.
 *
 * Pure functions, deliberately. Every claim the page makes about itself is
 * decided here, so each one can be tested without a browser. The chrome is part
 * of the claim discipline, not decoration: a stale globe that admits it is
 * stale is trustworthy, and one that silently shows week old data is not.
 *
 * See INTERACTION_SPEC.md section 13 and ARCHITECTURE.md section 7.
 */

import type { Heartbeat, TriggerKind } from "./types.ts";

/** Trigger kinds that mean "no human involved". The Phase 0 exit criterion. */
export const UNASSISTED_TRIGGERS: TriggerKind[] = ["schedule", "external_timer"];

/**
 * `raw.githubusercontent.com` enforces a 300 second edge cache floor and
 * nothing bypasses it, not even a never before seen query string: a `?t=`
 * value still returned a cache HIT, so the edge keys on the path alone.
 *
 * Consequence stated plainly on the page: a write appears within roughly 5 to 6
 * minutes, not instantly. Do not write a comment anywhere implying otherwise.
 */
export const RAW_EDGE_CACHE_FLOOR_SECONDS = 300;

/**
 * Derived, NEVER stored. The pipeline stores `writes_by_trigger` and this is
 * computed from it, by the same rule the pipeline logs.
 */
export function unassistedWrites(heartbeat: Heartbeat): number {
  return UNASSISTED_TRIGGERS.reduce(
    (total, kind) => total + (heartbeat.writes_by_trigger[kind] ?? 0),
    0,
  );
}

/**
 * Has Phase 0 been satisfied?
 *
 * A number changed on a deployed page because a job wrote it with no human
 * involved. A `schedule` or external timer write counts. A manual dispatch does
 * not. This must not be relaxed to make the criterion pass.
 */
export function phaseZeroSatisfied(heartbeat: Heartbeat): boolean {
  return unassistedWrites(heartbeat) > 0;
}

export type Staleness = {
  ageMinutes: number;
  isStale: boolean;
  /** Plain words for the page. Null when the data is as fresh as it should be. */
  message: string | null;
};

/**
 * Is the data older than the pipeline itself says it should be?
 *
 * The threshold comes from the payload, never from the frontend. The pipeline
 * owns the staleness decision because the pipeline knows which trigger is
 * armed; the page only reports it.
 */
export function staleness(heartbeat: Heartbeat, now: Date): Staleness {
  const writtenAt = new Date(heartbeat.written_at);
  const ageMinutes = (now.getTime() - writtenAt.getTime()) / 60_000;
  const isStale = ageMinutes > heartbeat.stale_after_minutes;

  if (!isStale) {
    return { ageMinutes, isStale, message: null };
  }

  return {
    ageMinutes,
    isStale,
    message:
      `Data is older than expected. The update job may have stopped. ` +
      `Last write was ${formatDuration(ageMinutes)} ago, and this feed expects ` +
      `a write every ${formatDuration(heartbeat.expected_cadence_minutes)}.`,
  };
}

/**
 * How the page describes its own update cadence.
 *
 * Before the external timer exists, the only thing starting runs is GitHub's
 * own scheduler, measured at a 4.68 hour median delay and 3.9 to 5.3 percent
 * delivery for high frequency crons. Saying "hourly" in that state would claim
 * a freshness the system has no mechanism to deliver.
 *
 * The word "real time" does not appear here and must not: it stays off the page
 * until a latency has actually been measured.
 */
export function cadenceStatement(heartbeat: Heartbeat): string {
  const every = formatDuration(heartbeat.expected_cadence_minutes);

  if (heartbeat.trigger_mode === "schedule_only") {
    return (
      `Updates rely on GitHub's own scheduler, which was measured at roughly one ` +
      `run every ${every} with a median delay of 4.7 hours. No external timer is armed.`
    );
  }
  return `Updates are attempted every ${every} by an external timer.`;
}

/**
 * How the page describes the last trigger.
 *
 * `dispatch_source` is a claim and is labelled as one. `dispatch_lag_seconds`
 * is the checkable part, so it is shown whenever it exists.
 */
export function triggerStatement(heartbeat: Heartbeat): string {
  if (heartbeat.triggered_by === "schedule") {
    return "Last run started by GitHub's scheduler.";
  }

  if (heartbeat.triggered_by === "workflow_dispatch") {
    const claimed = heartbeat.dispatch_source ?? "unspecified";
    const lag =
      heartbeat.dispatch_lag_seconds === null
        ? ""
        : ` Dispatch to write took ${heartbeat.dispatch_lag_seconds}s.`;

    if (claimed === "external-timer") {
      return (
        `Last run dispatched by something claiming to be the external timer.` +
        `${lag} The source is a claim: GitHub cannot distinguish the timer from a ` +
        `person with the same token.`
      );
    }
    return `Last run dispatched manually (reported source: ${claimed}).${lag}`;
  }

  return `Last run started by ${heartbeat.triggered_by}.`;
}

/** Which counter this write incremented. Mirrors the pipeline's single mapping. */
export function classifyLastWrite(heartbeat: Heartbeat): TriggerKind {
  if (heartbeat.triggered_by === "schedule") return "schedule";
  if (
    heartbeat.triggered_by === "workflow_dispatch" &&
    (heartbeat.dispatch_source ?? "").trim() === "external-timer"
  ) {
    return "external_timer";
  }
  return "manual";
}

/** Human readable duration from minutes. Used in several messages. */
export function formatDuration(minutes: number): string {
  const rounded = Math.max(0, Math.round(minutes));

  if (rounded < 1) return "less than a minute";
  if (rounded === 1) return "1 minute";
  if (rounded < 90) return `${rounded} minutes`;

  const hours = rounded / 60;
  if (hours < 48) {
    const shown = hours < 10 ? hours.toFixed(1).replace(/\.0$/, "") : Math.round(hours);
    return `${shown} hours`;
  }

  return `${Math.round(hours / 24)} days`;
}

/** Age of the data itself, for the "data age" line. */
export function formatAge(iso: string, now: Date): string {
  const minutes = (now.getTime() - new Date(iso).getTime()) / 60_000;
  return `${formatDuration(minutes)} ago`;
}
