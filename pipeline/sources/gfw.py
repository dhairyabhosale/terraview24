"""Global Forest Watch data API: GLAD and RADD alerts, WDPA, JRC surface water.

Auth, verified 2026-11-05 and re verified 2026-11-06:
  - The dataset catalogue is KEYLESS. GET /datasets returns 200 with 382
    datasets. Useful for discovery and for a CI smoke test needing no secret.
  - /query needs an `x-api-key` header. Without it the answer is 403, but only
    after two redirects. See `query_url` below.

Store the API key, not the account password, in GitHub secrets. The three step
auth flow (sign-up, token, apikey) is a human step; the pipeline only ever uses
the resulting long lived key.

Key lifetime is one year per community documentation and is not stated in the
OpenAPI spec, so a silently expired key presents exactly like a dead source.
That is what `describe_auth_failure` is for.
"""

from __future__ import annotations

import httpx

from pipeline.sources.http_client import build_client, get

BASE_URL = "https://data-api.globalforestwatch.org"

# Pin the version explicitly. Tracking `latest` means a reprocessing silently
# rewrites history underneath a baseline, and RADD releases are irregular:
# observed tail v20260412, v20260705, v20261011, v20261018, v20261026,
# v20261101. "Roughly weekly" is only true from v20261011 onward.
RADD_VERSION = "v20261101"

PIXEL_DATASETS = (
    "umd_glad_landsat_alerts",
    "umd_glad_sentinel2_alerts",
    "umd_glad_dist_alerts",
    "wur_radd_alerts",
    "gfw_integrated_alerts",
    "gfw_integrated_dist_alerts",
)


def catalogue_url() -> str:
    """The keyless dataset catalogue."""
    return f"{BASE_URL}/datasets"


def query_url(dataset: str, version: str) -> str:
    """A fully resolved query URL, with no redirect left to follow.

    Measured 2026-11-06: `/dataset/<id>/latest/query` returns 307 to
    `/dataset/<id>/<version>/query/json`, in two hops. Requesting the resolved
    form directly is better than relying on redirect following, because it
    makes the pinned version visible at the call site. The client follows
    redirects anyway, as a second line of defence.

    Passing `latest` as `version` is accepted but discouraged: see RADD_VERSION.
    """
    return f"{BASE_URL}/dataset/{dataset}/{version}/query/json"


def fetch_catalogue(client: httpx.Client | None = None) -> list[dict]:
    """Dataset catalogue. Keyless, so this doubles as a no secret smoke test."""
    owns_client = client is None
    client = client or build_client()
    try:
        response = get(client, catalogue_url())
        response.raise_for_status()
        payload = response.json()
        return payload.get("data", payload)
    finally:
        if owns_client:
            client.close()


def describe_auth_failure(response: httpx.Response) -> str | None:
    """Turn a GFW auth failure into a sentence a human can act on.

    None when the response is not an auth failure. A GFW key lasts about a year
    and expiry looks identical to an outage from the pipeline's point of view,
    so the distinction is worth stating explicitly in the logs.
    """
    if response.status_code != 403:
        return None
    return (
        "GFW data API returned 403. Either GFW_API_KEY is absent from the "
        "environment, or it has expired: keys last about one year and GFW does "
        "not warn before expiry. Mint a new one via POST /auth/apikey and "
        "replace the GitHub secret. The dataset catalogue is keyless, so if "
        f"{catalogue_url()} still returns 200 the service is up and this is a "
        "credential problem, not an outage."
    )
