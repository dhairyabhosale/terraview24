/**
 * Dispatching workflows via the GitHub REST API.
 *
 * POST /repos/{owner}/{repo}/actions/workflows/{workflow_file}/dispatches
 *
 * Why `workflow_dispatch` and not `repository_dispatch`: per GitHub's
 * documentation, `workflow_dispatch` needs only Actions: write on a fine
 * grained token, while `repository_dispatch` needs Contents: write, which also
 * permits pushing code. The narrower token is worth the slightly more awkward
 * endpoint. See ARCHITECTURE.md section 1a.
 *
 * Every dispatch is logged, including failures, so that "dispatched but never
 * ran" is visible and separable from GitHub scheduler flakiness. Attempt 1's
 * hardest diagnosis was precisely this ambiguity, and it is unresolvable
 * without a record from the dispatching side.
 */

export type DispatchTarget = {
  workflowFile: string;
  /** Minute the timer believes it fired for. The checkable half of the claim. */
  scheduledFor: Date;
};

export type DispatchResult = {
  workflowFile: string;
  ok: boolean;
  status: number;
  scheduledFor: string;
  /** Milliseconds the POST itself took. Not the run creation lag. */
  durationMs: number;
  error?: string;
};

export type DispatchConfig = {
  owner: string;
  repo: string;
  ref: string;
  token: string;
  /**
   * The `source` input value. Published as `dispatch_source` and treated as a
   * CLAIM, never as proof: GitHub cannot tell this Worker from a person running
   * curl, because the sender is the same token owner.
   */
  source: string;
  fetchImpl?: typeof fetch;
};

export const USER_AGENT = "terraview24-trigger-worker";

export function dispatchUrl(owner: string, repo: string, workflowFile: string): string {
  return `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflowFile}/dispatches`;
}

/** ISO 8601 UTC, to the second. The workflow parses this back. */
export function isoSeconds(date: Date): string {
  return `${date.toISOString().slice(0, 19)}Z`;
}

export async function dispatchWorkflow(
  target: DispatchTarget,
  config: DispatchConfig,
): Promise<DispatchResult> {
  const doFetch = config.fetchImpl ?? fetch;
  const startedAt = Date.now();
  const scheduledFor = isoSeconds(target.scheduledFor);

  try {
    const response = await doFetch(
      dispatchUrl(config.owner, config.repo, target.workflowFile),
      {
        method: "POST",
        headers: {
          Accept: "application/vnd.github+json",
          Authorization: `Bearer ${config.token}`,
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": USER_AGENT,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          ref: config.ref,
          inputs: {
            source: config.source,
            scheduled_for: scheduledFor,
          },
        }),
      },
    );

    const durationMs = Date.now() - startedAt;

    // A successful dispatch is 204 No Content. Anything else is worth keeping
    // the body of, because the common failures are all diagnosable from it:
    //   401  the token expired. It lasts 90 days and expiry is silent.
    //   404  the workflow file does not declare workflow_dispatch, or the
    //        token cannot see the repo.
    //   422  the ref does not exist, or an input was rejected.
    if (response.status === 204) {
      return {
        workflowFile: target.workflowFile,
        ok: true,
        status: response.status,
        scheduledFor,
        durationMs,
      };
    }

    let body = "";
    try {
      body = (await response.text()).slice(0, 400);
    } catch {
      body = "(body unreadable)";
    }

    return {
      workflowFile: target.workflowFile,
      ok: false,
      status: response.status,
      scheduledFor,
      durationMs,
      error: `${response.status}: ${body}${explain(response.status)}`,
    };
  } catch (cause) {
    return {
      workflowFile: target.workflowFile,
      ok: false,
      status: 0,
      scheduledFor,
      durationMs: Date.now() - startedAt,
      error: `transport failure: ${cause instanceof Error ? cause.message : String(cause)}`,
    };
  }
}

function explain(status: number): string {
  switch (status) {
    case 401:
    case 403:
      return (
        " | The fine grained token has probably expired. It lasts 90 days and " +
        "expiry is silent: every dispatch returns 401 and the pipeline falls back " +
        "to GitHub's own cadence of roughly one run per 4 to 5 hours, which looks " +
        "like a slightly stale page rather than an outage. Mint a new token with " +
        "Actions: write on this repo only and run `wrangler secret put GITHUB_TOKEN`."
      );
    case 404:
      return (
        " | Either the workflow file does not declare `on: workflow_dispatch`, or " +
        "it is not present on the default branch, or the token cannot see this repo."
      );
    case 422:
      return " | The ref does not exist, or an input was rejected.";
    default:
      return "";
  }
}
