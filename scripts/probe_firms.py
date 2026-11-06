"""Probe the FIRMS API to settle three open questions. Runs inside Actions.

Reads FIRMS_MAP_KEY from the environment. **Never prints the key, never prints
a URL that contains it.** The key sits in the URL path for this API, so every
request is described by its parameters rather than by its address, and the
response body is scrubbed before printing in case the service ever echoes it.

Questions:

1. **DAY_RANGE ceiling.** The API page states a valid range of 1 to 5 in its
   parameter table and then gives a worked example using 7. `DATA_SOURCES.md`
   records this as `[unresolved]` and says to assume 5 until proven otherwise.

2. **Does VIIRS_NOAA20_SP exist?** `DATA_SOURCES.md` lists it as a valid
   SOURCE and the whole Tier 0 baseline rests on it. But the FIRMS archive
   readme says, flatly, "the standard quality data is not yet available from
   FIRMS for NOAA-20 and NOAA-21", which would contradict that.

3. **What `version` string does each source return?** NASA defines a bare
   collection number as Standard Processing and a suffix (URT, RT, NRT) as
   real time. That string is the authoritative marker of which product we hold.

Usage: python scripts/probe_firms.py
"""

from __future__ import annotations

import os
import sys

import httpx

BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

# Small bbox over central Africa, which burns reliably year round, so a valid
# request returns a non trivial number of rows and an empty result is a signal
# rather than a coincidence. west,south,east,north
BBOX = "18,4,26,10"

KEY = os.environ.get("FIRMS_MAP_KEY", "")


def scrub(text: str) -> str:
    """Remove the key from anything before it is printed.

    GitHub masks registered secrets in logs already. This is the second line of
    defence, because a masked log is a property of the platform and this
    function is a property of the code.
    """
    if KEY and len(KEY) > 6:
        text = text.replace(KEY, "<MAP_KEY>")
    return text


def get(source: str, day_range: int, date: str | None = None) -> httpx.Response:
    url = f"{BASE}/{KEY}/{source}/{BBOX}/{day_range}"
    if date:
        url += f"/{date}"
    with httpx.Client(timeout=90.0, follow_redirects=True) as client:
        return client.get(url)


def describe(response: httpx.Response) -> tuple[int, str]:
    """Return (data_row_count, summary). Negative count means not CSV."""
    body = response.text
    if response.status_code != 200:
        return -1, scrub(body.strip()[:200])
    first = body.split("\n", 1)[0].strip()
    if not first.startswith("latitude"):
        return -1, "not a CSV header: " + scrub(first[:160])
    rows = [ln for ln in body.splitlines()[1:] if ln.strip()]
    versions = sorted({ln.split(",")[10] for ln in rows if len(ln.split(",")) > 10})
    dates = sorted({ln.split(",")[5] for ln in rows if len(ln.split(",")) > 5})
    span = f"{dates[0]}..{dates[-1]} ({len(dates)}d)" if dates else "no rows"
    return len(rows), f"versions={versions} dates={span}"


def main() -> int:
    if not KEY:
        print("FIRMS_MAP_KEY is not set in the environment", file=sys.stderr)
        return 2
    print(f"key loaded, length {len(KEY)}, value never printed\n")

    # ---------------------------------------------------------------
    print("=" * 72)
    print("QUESTION 1: the DAY_RANGE ceiling")
    print("=" * 72)
    print(f"{'DAY_RANGE':>10}  {'status':>6}  {'rows':>8}  detail")
    ceiling = None
    for dr in range(1, 11):
        try:
            r = get("VIIRS_NOAA20_NRT", dr)
        except httpx.HTTPError as exc:
            print(f"{dr:>10}  {'ERR':>6}  {'-':>8}  {type(exc).__name__}")
            continue
        count, detail = describe(r)
        print(f"{dr:>10}  {r.status_code:>6}  {count:>8}  {detail}")
        if r.status_code == 200 and count >= 0:
            ceiling = dr
    print(f"\nhighest DAY_RANGE accepted: {ceiling}")

    # ---------------------------------------------------------------
    print()
    print("=" * 72)
    print("QUESTION 2 and 3: does VIIRS_NOAA20_SP exist, and what version?")
    print("=" * 72)
    for source in (
        "VIIRS_NOAA20_NRT",
        "VIIRS_NOAA20_SP",
        "VIIRS_NOAA21_NRT",
        "MODIS_NRT",
        "MODIS_SP",
    ):
        try:
            r = get(source, 1)
        except httpx.HTTPError as exc:
            print(f"  {source:<20} ERR   {type(exc).__name__}")
            continue
        count, detail = describe(r)
        print(f"  {source:<20} {r.status_code}   rows={count:<7} {detail}")

    # A 2021 date, which is the Tier 0 window. If SP covers it the baseline
    # source is confirmed; if only NRT answers, the window is NRT throughout.
    print()
    print("  Same question against a 2021 date, the Tier 0 window:")
    for source in ("VIIRS_NOAA20_SP", "VIIRS_NOAA20_NRT"):
        try:
            r = get(source, 1, "2021-07-01")
        except httpx.HTTPError as exc:
            print(f"  {source:<20} ERR   {type(exc).__name__}")
            continue
        count, detail = describe(r)
        print(f"  {source:<20} {r.status_code}   rows={count:<7} {detail}")

    # ---------------------------------------------------------------
    print()
    print("=" * 72)
    print("Column schema actually returned by the API")
    print("=" * 72)
    r = get("VIIRS_NOAA20_NRT", 1)
    if r.status_code == 200:
        header = r.text.split("\n", 1)[0].strip()
        print("  API header    :", header)
    print("  archive header: latitude,longitude,brightness,scan,track,acq_date,"
          "acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight,type")
    print("\n  (DATA_SOURCES.md documents bright_ti4 and bright_ti5 as the VIIRS")
    print("   field names. The 2021 archive delivered brightness and bright_t31.")
    print("   This comparison shows whether the API and the archive agree.)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
