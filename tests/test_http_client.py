"""Tests for redirect handling and retry. No network.

The GFW redirect case is the one that matters: a client with redirect following
disabled sees 307 with an empty body on /query, which is indistinguishable from
several unrelated faults. These tests use httpx.MockTransport so the behaviour
is pinned without touching the live API.
"""

from __future__ import annotations

import httpx
import pytest

from pipeline.sources import gfw
from pipeline.sources.http_client import (
    MAX_ATTEMPTS,
    UnhandledRedirectError,
    build_client,
    get,
)


def noop_sleep(_seconds: float) -> None:
    """Swallow backoff so the suite stays fast and deterministic."""


# ---------------------------------------------------------------------------
# The GFW 307 case
# ---------------------------------------------------------------------------


def test_gfw_query_307_chain_is_followed_to_the_real_403():
    """The measured GFW behaviour: two redirects, then the real status.

    This is the test that fails if redirect following is ever turned off. It
    asserts on the FINAL status and body, not the first response.
    """
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path.endswith("/latest/query"):
            return httpx.Response(
                307,
                headers={
                    "location": "/dataset/wur_radd_alerts/v20261101/query"
                },
            )
        if request.url.path.endswith("/v20261101/query"):
            return httpx.Response(
                307,
                headers={
                    "location": "/dataset/wur_radd_alerts/v20261101/query/json"
                },
            )
        return httpx.Response(
            403,
            json={
                "status": "failed",
                "message": "Request is missing valid API key.",
            },
        )

    client = build_client(
        transport=httpx.MockTransport(handler),
        base_url="https://data-api.globalforestwatch.org",
    )
    response = get(client, "/dataset/wur_radd_alerts/latest/query", sleep=noop_sleep)

    assert len(seen) == 3, f"expected two redirects to be followed, saw {seen}"
    assert response.status_code == 403
    assert "missing valid API key" in response.json()["message"]


def test_an_unfollowed_redirect_raises_rather_than_returning_307():
    """Negative control: prove the guard fires.

    If someone constructs a client with follow_redirects=False, the failure must
    be loud and name the cause. A silently returned 307 is the bug this module
    exists to prevent, so the suite must contain a case where that path raises.
    """

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(307, headers={"location": "/elsewhere"})

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://example.invalid",
        follow_redirects=False,
    )
    with pytest.raises(UnhandledRedirectError, match="follow_redirects=True"):
        get(client, "/dataset/x/latest/query", sleep=noop_sleep)


def test_build_client_follows_redirects_by_default():
    """The default is the whole point, so assert it directly."""
    with build_client() as client:
        assert client.follow_redirects is True


def test_query_url_is_already_resolved_and_pins_the_version():
    url = gfw.query_url("wur_radd_alerts", gfw.RADD_VERSION)
    assert url.endswith("/dataset/wur_radd_alerts/v20261101/query/json")
    assert "latest" not in url


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------


def test_retryable_status_is_retried_then_succeeds():
    attempts = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    client = build_client(
        transport=httpx.MockTransport(handler), base_url="https://example.invalid"
    )
    response = get(client, "/x", sleep=noop_sleep)
    assert response.status_code == 200
    assert attempts["n"] == 3


def test_terminal_status_is_not_retried():
    """Retrying a 403 turns a clear error into a slow one."""
    attempts = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(403, json={"message": "nope"})

    client = build_client(
        transport=httpx.MockTransport(handler), base_url="https://example.invalid"
    )
    response = get(client, "/x", sleep=noop_sleep)
    assert response.status_code == 403
    assert attempts["n"] == 1, "a 403 must not be retried"


def test_retries_are_bounded():
    attempts = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(503)

    client = build_client(
        transport=httpx.MockTransport(handler), base_url="https://example.invalid"
    )
    response = get(client, "/x", sleep=noop_sleep)
    assert response.status_code == 503
    assert attempts["n"] == MAX_ATTEMPTS


def test_transport_errors_are_retried_then_raised():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        raise httpx.ConnectError("boom", request=request)

    client = build_client(
        transport=httpx.MockTransport(handler), base_url="https://example.invalid"
    )
    with pytest.raises(httpx.ConnectError):
        get(client, "/x", sleep=noop_sleep)
    assert attempts["n"] == MAX_ATTEMPTS


# ---------------------------------------------------------------------------
# GFW auth diagnosis
# ---------------------------------------------------------------------------


def test_auth_failure_message_distinguishes_credential_from_outage():
    message = gfw.describe_auth_failure(httpx.Response(403))
    assert message is not None
    assert "expired" in message
    assert "keyless" in message


def test_auth_failure_message_is_none_for_a_healthy_response():
    assert gfw.describe_auth_failure(httpx.Response(200)) is None
