/**
 * The Phase 0 page: an honest state display.
 *
 * This is NOT the globe. The globe is Phase 1, built against fixtures per
 * INTERACTION_SPEC section 12. What this page has to do is prove the
 * architecture end to end and then report its own state truthfully, which is
 * the Phase 0 exit criterion: a number changes here because a job wrote it with
 * no human involved.
 *
 * Every string in this file is bounded by what the data supports. In
 * particular: "Run" is never "Scheduled run", the dispatch source is labelled a
 * claim, and the words "real time" do not appear.
 */

import { useEffect, useState } from "react";

import {
  DATA_BRANCH,
  DATA_OWNER,
  DATA_REPO,
  DataFetchError,
  dataSourceIsExplicit,
  dataUrl,
  fetchHeartbeat,
} from "../data/fetch.ts";
import {
  RAW_EDGE_CACHE_FLOOR_SECONDS,
  cadenceStatement,
  classifyLastWrite,
  formatAge,
  phaseZeroSatisfied,
  staleness,
  triggerStatement,
  unassistedWrites,
} from "../data/freshness.ts";
import type { Heartbeat } from "../data/types.ts";

/**
 * Poll interval. Longer than the 300 second edge cache floor would be pointless
 * precision; much shorter just burns requests against a cache that will not
 * move. 60 seconds means the page notices a change within roughly one cache
 * window of it becoming visible.
 */
const POLL_MS = 60_000;

type LoadState =
  | { status: "loading" }
  | { status: "ready"; heartbeat: Heartbeat }
  | { status: "error"; error: DataFetchError };

export function StatusPanel() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const heartbeat = await fetchHeartbeat();
        if (!cancelled) setState({ status: "ready", heartbeat });
      } catch (error) {
        if (!cancelled) {
          setState({
            status: "error",
            error:
              error instanceof DataFetchError
                ? error
                : new DataFetchError(String(error), "heartbeat.json"),
          });
        }
      }
      if (!cancelled) setNow(new Date());
    };

    void load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return (
    <main className="page">
      <header>
        <h1>TerraView24</h1>
        <p className="tagline">Damage done by humans, measured against the norm</p>
      </header>

      <section className="phase-note">
        <p>
          This is the Phase 0 page. It exists to prove the pipeline writes to a
          static data branch and that this deployed page reads it, before any
          detection work begins. The globe, the anomaly scoring and the event
          lifecycle are later phases.
        </p>
      </section>

      {state.status === "loading" && <p className="muted">Loading the heartbeat...</p>}

      {state.status === "error" && <ErrorBlock error={state.error} />}

      {state.status === "ready" && <Heartbeatview heartbeat={state.heartbeat} now={now} />}

      <Provenance />
    </main>
  );
}

function Heartbeatview({ heartbeat, now }: { heartbeat: Heartbeat; now: Date }) {
  const unassisted = unassistedWrites(heartbeat);
  const passed = phaseZeroSatisfied(heartbeat);
  const stale = staleness(heartbeat, now);
  const lastWriteKind = classifyLastWrite(heartbeat);

  return (
    <>
      {/* The exit criterion. This flips to its pass state by itself, the first
          time the derived count exceeds zero. Nobody edits it. */}
      <section className={passed ? "verdict pass" : "verdict pending"}>
        <h2>{passed ? "Phase 0 criterion met" : "Phase 0 criterion not yet met"}</h2>
        <p>
          {passed ? (
            <>
              A job has written to this page with no human involved{" "}
              <strong>
                {unassisted} {unassisted === 1 ? "time" : "times"}
              </strong>
              . First unassisted write:{" "}
              <time dateTime={heartbeat.first_unassisted_write ?? undefined}>
                {heartbeat.first_unassisted_write}
              </time>
              .
            </>
          ) : (
            <>
              Every write so far was started by a human. A manual dispatch does not
              satisfy the criterion, so this panel will keep saying so until a
              scheduled or externally timed run writes on its own.
            </>
          )}
        </p>
      </section>

      {stale.isStale && (
        <section className="warning">
          <h2>Stale</h2>
          <p>{stale.message}</p>
        </section>
      )}

      <section className="numbers">
        <Figure
          /* GitHub's run counter across ALL triggers. Never label this
             "scheduled runs": it is not a count of scheduled runs, and the
             previous attempt's page made exactly that mistake. */
          label="Run"
          value={String(heartbeat.run_number)}
          note="GitHub's run counter, across every trigger type"
        />
        <Figure
          label="Unassisted writes"
          value={String(unassisted)}
          note="Derived from writes_by_trigger: schedule plus external timer. Not stored."
        />
        <Figure
          label="Data age"
          value={formatAge(heartbeat.written_at, now)}
          note={`Expected a write every ${heartbeat.expected_cadence_minutes} minutes`}
        />
        <Figure
          label="Last write counted as"
          value={lastWriteKind}
          note="Anything unrecognised counts as manual, so the criterion fails closed"
        />
      </section>

      <section className="detail">
        <h2>What started the last run</h2>
        <p>{triggerStatement(heartbeat)}</p>
        <p>{cadenceStatement(heartbeat)}</p>

        <h2>The one authoritative counter</h2>
        <table>
          <thead>
            <tr>
              <th scope="col">Trigger</th>
              <th scope="col">Writes</th>
              <th scope="col">Counts as unassisted</th>
            </tr>
          </thead>
          <tbody>
            {(["schedule", "external_timer", "manual"] as const).map((kind) => (
              <tr key={kind}>
                <td>
                  <code>{kind}</code>
                </td>
                <td>{heartbeat.writes_by_trigger[kind] ?? 0}</td>
                <td>{kind === "manual" ? "no" : "yes"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted">
          One stored counter, everything else derived. Two counters that can
          disagree is a bug this project has already had once.
        </p>

        <h2>Source commit</h2>
        <p>
          <code>{heartbeat.source_commit}</code>, written{" "}
          <time dateTime={heartbeat.written_at}>{heartbeat.written_at}</time>
        </p>
      </section>
    </>
  );
}

function Figure({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note: string;
}) {
  return (
    <div className="figure">
      <span className="figure-label">{label}</span>
      <span className="figure-value">{value}</span>
      <span className="figure-note">{note}</span>
    </div>
  );
}

function ErrorBlock({ error }: { error: DataFetchError }) {
  const isMissing = error.status === 404;
  return (
    <section className="warning">
      <h2>{isMissing ? "No heartbeat yet" : "Could not load the heartbeat"}</h2>
      <p>{error.message}</p>
      <p className="muted">
        Tried <code>{dataUrl(error.path)}</code>
      </p>
      {isMissing && (
        <p className="muted">
          This is the expected state before the first pipeline run. The page is
          working; the data is not there yet.
        </p>
      )}
    </section>
  );
}

function Provenance() {
  return (
    <footer>
      <h2>How this page gets its numbers</h2>
      <ul>
        <li>
          A scheduled GitHub Actions job writes static JSON to the orphan{" "}
          <code>{DATA_BRANCH}</code> branch of{" "}
          <code>
            {DATA_OWNER}/{DATA_REPO}
          </code>
          . This page fetches it at runtime. There is no application server and no
          database.
        </li>
        <li>
          One credential and one always on component: a free Cloudflare Worker
          that calls the dispatch API, and one GitHub token scoped to Actions
          write on this repository alone. Not "zero servers".
        </li>
        <li>
          No secret reaches this page. The repository coordinates above are public
          by design.
          {!dataSourceIsExplicit && (
            <>
              {" "}
              <strong>
                Note: the data source environment variables were not set at build
                time, so these are built in defaults.
              </strong>
            </>
          )}
        </li>
        <li>
          Changes take up to about {RAW_EDGE_CACHE_FLOOR_SECONDS / 60} minutes to
          appear. The read path enforces a {RAW_EDGE_CACHE_FLOOR_SECONDS} second
          edge cache floor and nothing bypasses it, so this page is never showing
          you the current second.
        </li>
        <li>
          No end to end latency is claimed anywhere on this page, because none has
          been measured yet.
        </li>
      </ul>
    </footer>
  );
}
