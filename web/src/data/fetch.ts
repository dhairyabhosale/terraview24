/**
 * The data branch client.
 *
 * Reads static JSON from `raw.githubusercontent.com` at RUNTIME. Never at build
 * time: a data refresh must not require a redeploy.
 *
 * Why `raw` and not jsDelivr, measured on attempt 1:
 *
 *   |               | raw.githubusercontent.com | cdn.jsdelivr.net          |
 *   |---------------|---------------------------|---------------------------|
 *   | Cache-Control | max-age=300               | max-age=604800, s=43200   |
 *   | Browser cache | 5 minutes                 | 7 days                    |
 *   | Edge cache    | 5 minutes                 | 12 hours                  |
 *
 * On jsDelivr a value written hourly would look dead for up to half a day.
 *
 * And the part that matters for expectations: **query string cache busting does
 * not work on raw.** A never before requested `?t=` value still returned a
 * cache HIT, so the edge keys on the path. `cache: "no-store"` affects the
 * browser and nothing else. The 300 second edge floor is a floor, and nothing
 * bypasses it.
 *
 * There are no credentials in this file and there never will be. If the
 * frontend needs a key, the design is wrong (ARCHITECTURE.md section 8).
 */

import type { Heartbeat, LiveEvents, Meta } from "./types.ts";

/**
 * Repository coordinates. Public, not secret: they are the address of a public
 * branch. Baked in at build time by Vite, so changing them needs a redeploy.
 *
 * The fallbacks exist because the Vercel environment variables are set by hand
 * after the project is created, so the FIRST production build may run without
 * them. A page that silently fetched `undefined/undefined` would look like a
 * dead pipeline; these fallbacks mean it works, and `dataSourceIsExplicit`
 * lets the page say out loud that it is using a default.
 */
export const DATA_OWNER = import.meta.env.VITE_DATA_OWNER ?? "dhairyabhosale";
export const DATA_REPO = import.meta.env.VITE_DATA_REPO ?? "terraview24";
export const DATA_BRANCH = "data";

/** True when both env vars were supplied, false when a fallback is in use. */
export const dataSourceIsExplicit = Boolean(
  import.meta.env.VITE_DATA_OWNER && import.meta.env.VITE_DATA_REPO,
);

export function dataUrl(path: string): string {
  return `https://raw.githubusercontent.com/${DATA_OWNER}/${DATA_REPO}/${DATA_BRANCH}/${path}`;
}

export class DataFetchError extends Error {
  constructor(
    message: string,
    readonly path: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "DataFetchError";
  }
}

async function fetchJson<T>(path: string): Promise<T> {
  let response: Response;
  try {
    // no-store defeats the BROWSER cache only. The 300 second edge floor
    // remains, so a fresh write still takes up to about 5 minutes to appear.
    response = await fetch(dataUrl(path), { cache: "no-store" });
  } catch (cause) {
    throw new DataFetchError(
      `Could not reach the data source. ${cause instanceof Error ? cause.message : ""}`.trim(),
      path,
    );
  }

  if (response.status === 404) {
    throw new DataFetchError(
      `${path} does not exist on the ${DATA_BRANCH} branch yet. ` +
        `If the pipeline has never run, this is expected.`,
      path,
      404,
    );
  }

  if (!response.ok) {
    throw new DataFetchError(
      `Data source returned ${response.status} for ${path}.`,
      path,
      response.status,
    );
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new DataFetchError(`${path} is not valid JSON.`, path, response.status);
  }
}

export const fetchHeartbeat = () => fetchJson<Heartbeat>("heartbeat.json");
export const fetchMeta = () => fetchJson<Meta>("meta.json");
export const fetchLiveEvents = () => fetchJson<LiveEvents>("events/live.json");
