/**
 * Tests for the page's honest state logic. No browser, no network.
 *
 * These are claim tests. Each one guards a sentence the page says about itself,
 * and the ones that matter most are the two ways the Phase 0 verdict could lie:
 * crediting a manual write as unassisted, and describing an hourly cadence when
 * nothing hourly is armed.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  cadenceStatement,
  classifyLastWrite,
  formatAge,
  formatDuration,
  phaseZeroSatisfied,
  staleness,
  triggerStatement,
  unassistedWrites,
} from "../src/data/freshness.ts";
import type { Heartbeat } from "../src/data/types.ts";

const NOW = new Date("2026-11-06T09:05:00Z");

function heartbeat(overrides: Partial<Heartbeat> = {}): Heartbeat {
  return {
    run_number: 48,
    written_at: "2026-11-06T09:00:11Z",
    source_commit: "0215a5bad276",
    triggered_by: "workflow_dispatch",
    dispatch_source: "external-timer",
    dispatch_scheduled_for: "2026-11-06T09:00:00Z",
    dispatch_lag_seconds: 11,
    expected_cadence_minutes: 60,
    stale_after_minutes: 150,
    trigger_mode: "external_timer",
    writes_by_trigger: { schedule: 1, external_timer: 42, manual: 5 },
    first_unassisted_write: "2026-11-05T23:34:22Z",
    last_unassisted_write: "2026-11-06T09:00:11Z",
    ...overrides,
  };
}

describe("unassistedWrites, derived and never stored", () => {
  it("sums schedule and external timer", () => {
    assert.equal(unassistedWrites(heartbeat()), 43);
  });

  it("excludes manual writes", () => {
    const h = heartbeat({
      writes_by_trigger: { schedule: 0, external_timer: 0, manual: 17 },
    });
    assert.equal(unassistedWrites(h), 0);
  });

  it("tolerates a missing key rather than producing NaN", () => {
    // A NaN would render as "NaN" on the page, which is worse than a wrong
    // number because it looks like a crash rather than a data problem.
    const h = heartbeat({
      writes_by_trigger: { schedule: 2 } as Heartbeat["writes_by_trigger"],
    });
    assert.equal(unassistedWrites(h), 2);
  });
});

describe("the Phase 0 verdict", () => {
  it("passes once a schedule write exists", () => {
    const h = heartbeat({
      writes_by_trigger: { schedule: 1, external_timer: 0, manual: 0 },
    });
    assert.equal(phaseZeroSatisfied(h), true);
  });

  it("passes once an external timer write exists", () => {
    const h = heartbeat({
      writes_by_trigger: { schedule: 0, external_timer: 1, manual: 0 },
    });
    assert.equal(phaseZeroSatisfied(h), true);
  });

  it("does NOT pass on manual writes alone, however many there are", () => {
    // The criterion must not be relaxed to make it pass. A manual dispatch is
    // a human pressing a button.
    const h = heartbeat({
      writes_by_trigger: { schedule: 0, external_timer: 0, manual: 99 },
    });
    assert.equal(phaseZeroSatisfied(h), false);
  });

  it("does not pass on a fresh install with no writes", () => {
    const h = heartbeat({
      writes_by_trigger: { schedule: 0, external_timer: 0, manual: 0 },
    });
    assert.equal(phaseZeroSatisfied(h), false);
  });
});

describe("classifyLastWrite mirrors the pipeline mapping", () => {
  it("classifies a schedule event", () => {
    assert.equal(classifyLastWrite(heartbeat({ triggered_by: "schedule" })), "schedule");
  });

  it("classifies the hyphenated external timer claim", () => {
    assert.equal(classifyLastWrite(heartbeat()), "external_timer");
  });

  it("classifies the underscored spelling as manual, failing closed", () => {
    // The input value is hyphenated; the counter key is not. If the page
    // accepted the counter key as an input value, a typo in the Worker would
    // read as an unassisted write on the page while the pipeline counted it as
    // manual, and the two would disagree.
    const h = heartbeat({ dispatch_source: "external_timer" });
    assert.equal(classifyLastWrite(h), "manual");
  });

  it("classifies a manual or absent source as manual", () => {
    assert.equal(classifyLastWrite(heartbeat({ dispatch_source: "manual" })), "manual");
    assert.equal(classifyLastWrite(heartbeat({ dispatch_source: null })), "manual");
  });
});

describe("staleness", () => {
  it("is not stale well inside the threshold", () => {
    const result = staleness(heartbeat(), NOW);
    assert.equal(result.isStale, false);
    assert.equal(result.message, null);
  });

  it("is stale past the threshold and says so in plain words", () => {
    const h = heartbeat({ written_at: "2026-11-04T02:11:00Z" });
    const result = staleness(h, NOW);
    assert.equal(result.isStale, true);
    assert.match(result.message!, /older than expected/);
    assert.match(result.message!, /may have stopped/);
  });

  it("takes the threshold from the payload, not from the frontend", () => {
    // The pipeline owns the staleness decision because it knows which trigger
    // is armed. Same age, different declared threshold, different verdict.
    const written = "2026-11-06T06:00:00Z"; // 185 minutes before NOW
    assert.equal(staleness(heartbeat({ written_at: written }), NOW).isStale, true);
    assert.equal(
      staleness(heartbeat({ written_at: written, stale_after_minutes: 660 }), NOW).isStale,
      false,
    );
  });

  it("reports the age even when fresh, for the data age line", () => {
    const result = staleness(heartbeat(), NOW);
    assert.ok(result.ageMinutes > 4 && result.ageMinutes < 5);
  });
});

describe("cadenceStatement", () => {
  it("describes the external timer cadence when one is armed", () => {
    const text = cadenceStatement(heartbeat());
    assert.match(text, /external timer/);
    assert.match(text, /60 minutes/);
  });

  it("describes GitHub's measured cadence when no timer is armed", () => {
    // Saying "hourly" here would claim a freshness the system has no mechanism
    // to deliver, which is the dishonesty this whole field exists to prevent.
    const h = heartbeat({
      trigger_mode: "schedule_only",
      expected_cadence_minutes: 300,
      stale_after_minutes: 660,
    });
    const text = cadenceStatement(h);
    assert.match(text, /GitHub's own scheduler/);
    assert.match(text, /median delay of 4\.7 hours/);
    assert.match(text, /No external timer is armed/);
  });

  it("never uses the words real time", () => {
    for (const mode of ["external_timer", "schedule_only"] as const) {
      const text = cadenceStatement(heartbeat({ trigger_mode: mode })).toLowerCase();
      assert.ok(!text.includes("real time"), mode);
      assert.ok(!text.includes("realtime"), mode);
    }
  });
});

describe("triggerStatement", () => {
  it("labels the dispatch source as a claim, not as proof", () => {
    // GitHub cannot tell the Worker from a person running curl: the sender is
    // the same token owner. The page must not imply otherwise.
    const text = triggerStatement(heartbeat());
    assert.match(text, /claiming to be/);
    assert.match(text, /is a claim/);
    assert.match(text, /11s/);
  });

  it("does not claim a timer for a scheduled run", () => {
    const text = triggerStatement(heartbeat({ triggered_by: "schedule" }));
    assert.match(text, /GitHub's scheduler/);
    assert.ok(!text.includes("claim"));
  });

  it("says plainly when a run was dispatched manually", () => {
    const h = heartbeat({ dispatch_source: "manual", dispatch_lag_seconds: null });
    assert.match(triggerStatement(h), /dispatched manually/);
  });

  it("omits the lag when there is none to report", () => {
    const h = heartbeat({ triggered_by: "schedule", dispatch_lag_seconds: null });
    assert.ok(!triggerStatement(h).includes("took"));
  });
});

describe("formatDuration", () => {
  const cases: Array<[number, string]> = [
    [0, "less than a minute"],
    [0.4, "less than a minute"],
    [1, "1 minute"],
    [45, "45 minutes"],
    [89, "89 minutes"],
    [120, "2 hours"],
    [300, "5 hours"],
    [285, "4.8 hours"],
    [2880, "2 days"],
    [10080, "7 days"],
  ];

  for (const [minutes, expected] of cases) {
    it(`${minutes} minutes reads as ${expected}`, () => {
      assert.equal(formatDuration(minutes), expected);
    });
  }

  it("never renders a negative duration", () => {
    // Clock skew between the runner and the browser can make written_at look
    // like the future. "minus 3 minutes ago" reads as a bug.
    assert.equal(formatDuration(-10), "less than a minute");
  });
});

describe("formatAge", () => {
  it("renders an age relative to now", () => {
    assert.equal(formatAge("2026-11-06T08:05:00Z", NOW), "60 minutes ago");
  });

  it("handles a future timestamp without rendering a negative", () => {
    assert.equal(formatAge("2026-11-06T09:08:00Z", NOW), "less than a minute ago");
  });
});
