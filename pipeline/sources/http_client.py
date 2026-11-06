"""The one HTTP client every source module uses.

Two non negotiable behaviours, both learned from a live source rather than from
documentation:

1. REDIRECTS ARE FOLLOWED. The GFW data API answers
   /dataset/<id>/latest/query with 307, twice, before the real status arrives:
   `latest` resolves to a pinned version and `/query` resolves to `/query/json`.
   A client with redirect following off sees 307 and an empty body, so it cannot
   tell "missing API key" from "endpoint moved" from "service down". Measured
   2026-11-06, DATA_SOURCES.md Family B.

2. FAILURE IS ASSUMED. Every source in this project is flaky. Retry with
   exponential backoff on transport errors and on the retryable status codes,
   and never retry a 4xx that will stay a 4xx.

httpx defaults `follow_redirects` to False, which is a sane library default and
the wrong default here. This module exists so that choice is made once, with the
reason attached, instead of being forgotten at one of a dozen call sites.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# Retrying these is worth it. 429 is included because several sources throttle
# by pacing rather than by quota, so a wait genuinely helps.
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

# Retrying these is pointless: the answer will not change without a credential
# or a code change, and retrying turns a clear error into a slow one.
TERMINAL_STATUS = frozenset({400, 401, 403, 404, 405, 422})

MAX_ATTEMPTS = 4
BACKOFF_BASE_SECONDS = 1.5
JITTER_SECONDS = 0.75

USER_AGENT = "terraview24-pipeline/0.1 (+https://github.com/dhairyabhosale/terraview24)"


def build_client(**kwargs: object) -> httpx.Client:
    """An httpx.Client with this project's defaults.

    `follow_redirects=True` is the load bearing argument. See the module
    docstring before changing it.
    """
    params: dict[str, object] = {
        "follow_redirects": True,
        "timeout": DEFAULT_TIMEOUT,
        "headers": {"User-Agent": USER_AGENT},
    }
    params.update(kwargs)
    return httpx.Client(**params)  # type: ignore[arg-type]


class UnhandledRedirectError(RuntimeError):
    """Raised when a redirect status reaches the caller.

    If this is ever raised, redirect following has been disabled somewhere. It
    is a configuration bug, not a source problem, and it is worth its own
    exception type so it cannot be mistaken for an upstream failure.
    """


def get(
    client: httpx.Client,
    url: str,
    *,
    max_attempts: int = MAX_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs: object,
) -> httpx.Response:
    """GET with retry, backoff and jitter. Redirects are already resolved."""
    return _request(client, "GET", url, max_attempts=max_attempts, sleep=sleep, **kwargs)


def _request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    max_attempts: int,
    sleep: Callable[[float], None],
    **kwargs: object,
) -> httpx.Response:
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = client.request(method, url, **kwargs)  # type: ignore[arg-type]
        except httpx.TransportError as exc:
            last_error = exc
            if attempt == max_attempts:
                raise
            sleep(_backoff(attempt))
            continue

        if response.is_redirect:
            # Only reachable if follow_redirects was turned off. Fail loudly:
            # a silent 307 is the exact failure this module was written to stop.
            raise UnhandledRedirectError(
                f"{method} {url} returned {response.status_code} and the redirect was not "
                f"followed. Location: {response.headers.get('location')!r}. "
                f"Use build_client(), which sets follow_redirects=True."
            )

        if response.status_code in TERMINAL_STATUS:
            return response

        if response.status_code in RETRYABLE_STATUS and attempt < max_attempts:
            sleep(_backoff(attempt))
            continue

        return response

    # Unreachable: the loop either returns or raises. Kept so a future edit
    # that changes the control flow fails here rather than returning None.
    raise RuntimeError(f"{method} {url} exhausted attempts") from last_error


def _backoff(attempt: int) -> float:
    """Exponential, with jitter so concurrent runs do not retry in lockstep."""
    return BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, JITTER_SECONDS)
