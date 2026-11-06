/**
 * The Worker's view of trigger-schedule.json.
 *
 * The schedule is imported from the repository root, so the Worker, the
 * workflows, the heartbeat payload and the alignment test all read the SAME
 * file. Two copies of a cadence is how they drift, and a drifted cadence
 * produces a page that states a freshness it has no mechanism to deliver.
 */

import rawSchedule from "../../../trigger-schedule.json" with { type: "json" };

export type ScheduleEntry = {
  file: string;
  name: string;
  cron: string;
  cadence_minutes: number;
  stale_after_minutes: number;
  armed: boolean;
  gate_variable: string | null;
  writes_family: string | null;
  note: string;
};

export type Schedule = {
  schedule_version: number;
  schedule_only_cadence_minutes: number;
  schedule_only_stale_after_minutes: number;
  workflows: ScheduleEntry[];
};

export const schedule = rawSchedule as unknown as Schedule;

/**
 * Only armed workflows are candidates for dispatch.
 *
 * ARCHITECTURE.md section 9a: do not create skipped runs every few minutes for
 * pipelines that are switched off. A gated workflow costs no runner minutes,
 * but it still creates a skipped run record, and a few hundred of those a day
 * buries the runs that matter in the Actions tab. The Actions tab is a
 * diagnostic surface, and filling it with noise has a real cost.
 */
export function armedWorkflows(source: Schedule = schedule): ScheduleEntry[] {
  return source.workflows.filter((entry) => entry.armed);
}
