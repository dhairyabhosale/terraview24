/**
 * Cron parsing and matching. No network.
 *
 * The two cases worth writing tests for at all are the day union rule and
 * Sunday as 0. Both are quirks rather than logic, both are easy to implement
 * plausibly and wrongly, and both fail in the same way: the schedule silently
 * does not fire, which under a 4.68 hour scheduler baseline is almost
 * impossible to distinguish from platform flakiness.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { CronParseError, isDue, matches, parseCron } from "../src/cron.ts";

const utc = (iso: string) => new Date(`${iso}Z`);

describe("parseCron", () => {
  it("parses a wildcard field", () => {
    const cron = parseCron("* * * * *");
    assert.equal(cron.minute.values.length, 60);
    assert.equal(cron.hour.values.length, 24);
    assert.equal(cron.minute.isWildcard, true);
  });

  it("parses the schedules this project actually uses", () => {
    assert.deepEqual(parseCron("0 * * * *").minute.values, [0]);
    assert.deepEqual(parseCron("30 * * * *").minute.values, [30]);
    assert.deepEqual(parseCron("0 */6 * * *").hour.values, [0, 6, 12, 18]);
    assert.deepEqual(parseCron("0 4 * * 1").dayOfWeek.values, [1]);
    assert.deepEqual(parseCron("*/5 * * * *").minute.values.slice(0, 4), [0, 5, 10, 15]);
  });

  it("parses lists, ranges and stepped ranges", () => {
    assert.deepEqual(parseCron("1,15,30 * * * *").minute.values, [1, 15, 30]);
    assert.deepEqual(parseCron("0 1-5 * * *").hour.values, [1, 2, 3, 4, 5]);
    assert.deepEqual(parseCron("0-20/5 * * * *").minute.values, [0, 5, 10, 15, 20]);
    assert.deepEqual(parseCron("7,37 * * * *").minute.values, [7, 37]);
  });

  it("records which fields were wildcards, because the day rule needs it", () => {
    const cron = parseCron("0 0 1 * 1");
    assert.equal(cron.dayOfMonth.isWildcard, false);
    assert.equal(cron.dayOfWeek.isWildcard, false);
    assert.equal(cron.month.isWildcard, true);
  });

  describe("rejects malformed expressions", () => {
    const bad = [
      ["too few fields", "0 * * *"],
      ["too many fields", "0 * * * * *"],
      ["minute out of range", "60 * * * *"],
      ["hour out of range", "0 24 * * *"],
      ["day of month zero", "0 0 0 * *"],
      ["month out of range", "0 0 1 13 *"],
      ["day of week out of range", "0 0 * * 8"],
      ["non integer", "abc * * * *"],
      ["descending range", "0 5-1 * * *"],
      ["zero step", "*/0 * * * *"],
      ["empty list element", "1,,2 * * * *"],
    ] as const;

    for (const [label, expression] of bad) {
      it(label, () => {
        assert.throws(() => parseCron(expression), CronParseError, expression);
      });
    }
  });
});

describe("the day of month and day of week union rule", () => {
  // When BOTH are restricted, cron fires when EITHER matches. Implementing
  // this as an AND is the plausible wrong answer, and it drops most firings.
  const cron = parseCron("0 0 1 * 1"); // 1st of the month, OR any Monday

  it("fires on the 1st even when it is not a Monday", () => {
    // 2026-12-01 is a Tuesday.
    assert.equal(utc("2026-12-01T00:00:00").getUTCDay(), 2);
    assert.equal(matches(cron, utc("2026-12-01T00:00:00")), true);
  });

  it("fires on a Monday even when it is not the 1st", () => {
    // 2026-11-09 is a Monday.
    assert.equal(utc("2026-11-09T00:00:00").getUTCDay(), 1);
    assert.equal(matches(cron, utc("2026-11-09T00:00:00")), true);
  });

  it("does not fire on a day that is neither", () => {
    // 2026-11-10 is a Tuesday and not the 1st.
    assert.equal(matches(cron, utc("2026-11-10T00:00:00")), false);
  });

  it("uses AND semantics when one of the two fields is a wildcard", () => {
    // Monday only. The 1st of a month that is not a Monday must not fire.
    const mondayOnly = parseCron("0 4 * * 1");
    assert.equal(matches(mondayOnly, utc("2026-11-09T04:00:00")), true);
    assert.equal(matches(mondayOnly, utc("2026-12-01T04:00:00")), false);

    // 1st only. A Monday that is not the 1st must not fire.
    const firstOnly = parseCron("0 4 1 * *");
    assert.equal(matches(firstOnly, utc("2026-12-01T04:00:00")), true);
    assert.equal(matches(firstOnly, utc("2026-11-09T04:00:00")), false);
  });
});

describe("Sunday is 0, and also 7", () => {
  it("treats 0 as Sunday", () => {
    // 2026-11-08 is a Sunday.
    assert.equal(utc("2026-11-08T00:00:00").getUTCDay(), 0);
    assert.equal(matches(parseCron("0 0 * * 0"), utc("2026-11-08T00:00:00")), true);
  });

  it("treats 7 as Sunday too, rather than rejecting it", () => {
    const cron = parseCron("0 0 * * 7");
    assert.deepEqual(cron.dayOfWeek.values, [0]);
    assert.equal(matches(cron, utc("2026-11-08T00:00:00")), true);
  });

  it("normalises 7 inside a range so Sunday is not silently dropped", () => {
    // A weekend expression. Without normalisation this would match nothing on
    // Sunday, and the fault would look like platform flakiness.
    const cron = parseCron("0 0 * * 6,7");
    assert.deepEqual(cron.dayOfWeek.values, [0, 6]);
    assert.equal(matches(cron, utc("2026-11-07T00:00:00")), true); // Saturday
    assert.equal(matches(cron, utc("2026-11-08T00:00:00")), true); // Sunday
    assert.equal(matches(cron, utc("2026-11-09T00:00:00")), false); // Monday
  });
});

describe("isDue over the Worker's 5 minute window", () => {
  const hourly = parseCron("0 * * * *");

  it("catches an hourly cron from anywhere inside the window", () => {
    // This is the whole reason the window exists. A 5 minute timer checking
    // only its own minute would match minute 0 and miss everything else, so an
    // hourly schedule would fire only when the tick landed exactly on :00.
    for (const minute of [0, 1, 2, 3, 4]) {
      const now = utc(`2026-11-06T09:0${minute}:30`);
      assert.equal(isDue(hourly, now, 5), true, `minute ${minute}`);
    }
  });

  it("does not fire outside the window", () => {
    assert.equal(isDue(hourly, utc("2026-11-06T09:05:00"), 5), false);
    assert.equal(isDue(hourly, utc("2026-11-06T09:30:00"), 5), false);
  });

  it("does not double fire across consecutive windows", () => {
    // Half open (now - window, now]. Consecutive 5 minute ticks must produce
    // exactly one firing for an hourly cron, not two and not zero.
    const ticks = [
      "2026-11-06T09:00:00",
      "2026-11-06T09:05:00",
      "2026-11-06T09:10:00",
      "2026-11-06T09:15:00",
    ];
    const fired = ticks.filter((t) => isDue(hourly, utc(t), 5));
    assert.deepEqual(fired, ["2026-11-06T09:00:00"]);
  });

  it("covers every minute of an hour exactly once across 12 ticks", () => {
    let fired = 0;
    for (let i = 0; i < 12; i += 1) {
      const now = new Date(utc("2026-11-06T09:00:00").getTime() + i * 5 * 60_000);
      if (isDue(hourly, now, 5)) fired += 1;
    }
    assert.equal(fired, 1, "an hourly cron must fire exactly once per hour");
  });

  it("ignores seconds, so a drifted invocation still matches", () => {
    assert.equal(isDue(hourly, utc("2026-11-06T09:02:47"), 5), true);
  });

  it("rejects a nonsensical window rather than silently never firing", () => {
    assert.throws(() => isDue(hourly, utc("2026-11-06T09:00:00"), 0), CronParseError);
  });

  it("handles a window that crosses an hour boundary", () => {
    // Tick at 10:02 must still see the 10:00 firing.
    assert.equal(isDue(hourly, utc("2026-11-06T10:02:00"), 5), true);
    // A cron at :58 must be seen by a tick at 11:00, crossing the hour back.
    const at58 = parseCron("58 * * * *");
    assert.equal(isDue(at58, utc("2026-11-06T11:00:00"), 5), true);
  });

  it("handles a window that crosses a day boundary", () => {
    const daily = parseCron("0 0 * * *");
    assert.equal(isDue(daily, utc("2026-11-06T00:02:00"), 5), true);
    const at2358 = parseCron("58 23 * * *");
    assert.equal(isDue(at2358, utc("2026-11-07T00:01:00"), 5), true);
  });
});
