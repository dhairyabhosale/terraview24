/**
 * A small, exact cron matcher.
 *
 * The Worker has ONE cron trigger, every 5 minutes, and decides in code which
 * of the project's cadences are due. That means the schedule is versioned,
 * reviewable, testable code rather than six entries in a dashboard that nobody
 * can diff. See ARCHITECTURE.md section 1a.
 *
 * Supports the five field form used by GitHub Actions:
 *
 *     minute hour day-of-month month day-of-week
 *
 * with `*`, lists (`1,15`), ranges (`1-5`) and steps (`*\/15`, `1-20/2`).
 *
 * Two details that are easy to get wrong, and are tested explicitly:
 *
 * 1. THE DAY UNION RULE. When BOTH day-of-month and day-of-week are
 *    restricted, cron runs the job when EITHER matches, not when both do. This
 *    is a genuine quirk of cron rather than a bug, and implementing it as an
 *    AND silently drops most firings of any expression that uses both fields.
 *
 * 2. SUNDAY IS 0. It is also accepted as 7, because both spellings are in
 *    common use and a schedule that silently never fires on Sunday is the kind
 *    of fault that takes a week to notice.
 */

export type CronField = {
  /** Every value the field matches, as a sorted array. */
  values: number[];
  /** True when the field was a bare `*`, which the day union rule needs. */
  isWildcard: boolean;
};

export type ParsedCron = {
  minute: CronField;
  hour: CronField;
  dayOfMonth: CronField;
  month: CronField;
  dayOfWeek: CronField;
};

const RANGES = {
  minute: [0, 59],
  hour: [0, 23],
  dayOfMonth: [1, 31],
  month: [1, 12],
  dayOfWeek: [0, 6],
} as const;

export class CronParseError extends Error {}

/** Parse a five field cron expression. Throws CronParseError on anything else. */
export function parseCron(expression: string): ParsedCron {
  const parts = expression.trim().split(/\s+/);
  if (parts.length !== 5) {
    throw new CronParseError(
      `expected 5 fields in cron expression, got ${parts.length}: ${expression}`,
    );
  }

  return {
    minute: parseField(parts[0], "minute"),
    hour: parseField(parts[1], "hour"),
    dayOfMonth: parseField(parts[2], "dayOfMonth"),
    month: parseField(parts[3], "month"),
    dayOfWeek: parseField(parts[4], "dayOfWeek"),
  };
}

function parseField(raw: string, name: keyof typeof RANGES): CronField {
  const [min, max] = RANGES[name];
  const isWildcard = raw === "*";
  const values = new Set<number>();

  for (const chunk of raw.split(",")) {
    if (chunk === "") {
      throw new CronParseError(`empty element in ${name} field: ${raw}`);
    }

    const [spec, stepRaw] = chunk.split("/");
    let step = 1;
    if (stepRaw !== undefined) {
      step = Number(stepRaw);
      if (!Number.isInteger(step) || step < 1) {
        throw new CronParseError(`invalid step ${stepRaw} in ${name} field: ${raw}`);
      }
    }

    let lo: number;
    let hi: number;

    if (spec === "*") {
      lo = min;
      hi = max;
    } else if (spec.includes("-")) {
      const [a, b] = spec.split("-");
      lo = normalise(a, name, raw);
      hi = normalise(b, name, raw);
      if (lo > hi) {
        throw new CronParseError(`descending range ${spec} in ${name} field: ${raw}`);
      }
    } else {
      lo = normalise(spec, name, raw);
      hi = stepRaw === undefined ? lo : max;
    }

    for (let v = lo; v <= hi; v += step) {
      values.add(v);
    }
  }

  if (values.size === 0) {
    throw new CronParseError(`${name} field matched nothing: ${raw}`);
  }

  return { values: [...values].sort((a, b) => a - b), isWildcard };
}

function normalise(token: string, name: keyof typeof RANGES, raw: string): number {
  const value = Number(token);
  if (!Number.isInteger(value)) {
    throw new CronParseError(`non integer ${token} in ${name} field: ${raw}`);
  }

  // Sunday is 0, and 7 means Sunday too. Accepting only one spelling produces
  // a schedule that quietly never fires on one day of the week.
  if (name === "dayOfWeek" && value === 7) {
    return 0;
  }

  const [min, max] = RANGES[name];
  if (value < min || value > max) {
    throw new CronParseError(
      `${token} is out of range for ${name} (${min} to ${max}): ${raw}`,
    );
  }
  return value;
}

/**
 * Does `date` (interpreted in UTC) satisfy this cron expression?
 *
 * GitHub Actions cron is always UTC, and so is this.
 */
export function matches(cron: ParsedCron, date: Date): boolean {
  if (!cron.minute.values.includes(date.getUTCMinutes())) return false;
  if (!cron.hour.values.includes(date.getUTCHours())) return false;
  if (!cron.month.values.includes(date.getUTCMonth() + 1)) return false;

  const domMatches = cron.dayOfMonth.values.includes(date.getUTCDate());
  const dowMatches = cron.dayOfWeek.values.includes(date.getUTCDay());

  // The day union rule. Both restricted means OR; otherwise the restricted one
  // governs and the wildcard one is satisfied by definition.
  if (!cron.dayOfMonth.isWildcard && !cron.dayOfWeek.isWildcard) {
    return domMatches || dowMatches;
  }
  return domMatches && dowMatches;
}

/**
 * Was this cron due at any point in the window ending at `now`?
 *
 * The Worker fires every 5 minutes, and a cron is specified to the minute, so
 * checking only the current minute would miss almost everything: an hourly
 * `0 * * * *` only matches minute 0, and the Worker's own invocation can drift
 * by seconds or be delayed. Scanning the window is what makes a 5 minute timer
 * able to honour minute precision schedules.
 *
 * The window is half open, (now - windowMinutes, now], so consecutive 5 minute
 * invocations neither double fire nor leave a gap.
 */
export function isDue(cron: ParsedCron, now: Date, windowMinutes: number): boolean {
  if (windowMinutes < 1) {
    throw new CronParseError(`windowMinutes must be at least 1, got ${windowMinutes}`);
  }

  const cursor = new Date(now.getTime());
  cursor.setUTCSeconds(0, 0);

  for (let i = 0; i < windowMinutes; i += 1) {
    if (matches(cron, cursor)) return true;
    cursor.setUTCMinutes(cursor.getUTCMinutes() - 1);
  }
  return false;
}
