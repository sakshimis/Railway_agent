"""Server-side adapter for an authorized, normalized live railway data provider.

No provider credentials are bundled. A provider-specific response mapper may be
needed after the provider shares its API documentation.
"""
from __future__ import annotations

import json
import math
import os
import re
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


class LiveServiceUnavailable(Exception):
    """The live feed is not configured or cannot be reached."""


def configured() -> bool:
    return bool(os.getenv("RAILWAY_LIVE_API_URL") and os.getenv("RAILWAY_LIVE_API_TOKEN"))


def search_live(origin: str, destination: str, travel_date: str, travel_class: str = "") -> dict:
    """Fetch current route data through a server-side authorized provider gateway.

    Expected provider response: {"trains": [{"train_no", "name", "class",
    "fare_rupees", "availability", "departure", "arrival"}], "as_of": ISO8601}.
    Fields omitted by a provider remain unknown; they are never filled from
    historical data and presented as live.
    """
    endpoint = os.getenv("RAILWAY_LIVE_API_URL", "").strip()
    token = os.getenv("RAILWAY_LIVE_API_TOKEN", "").strip()
    if not endpoint or not token:
        raise LiveServiceUnavailable("Live fares and seats are not connected yet.")
    parsed_url = urlsplit(endpoint)
    if parsed_url.scheme != "https" or not parsed_url.netloc or parsed_url.username or parsed_url.password:
        raise LiveServiceUnavailable("The live provider URL must be HTTPS.")
    origin, destination = origin.strip().upper(), destination.strip().upper()
    if not all(re.fullmatch(r"[A-Z0-9]{2,8}", code) for code in (origin, destination)):
        raise ValueError("Enter valid origin and destination station codes.")
    if origin == destination:
        raise ValueError("Choose different origin and destination stations.")
    try:
        date.fromisoformat(travel_date)
    except ValueError as exc:
        raise ValueError("Enter a valid journey date.") from exc
    travel_class = travel_class.strip().upper()
    if travel_class not in {"", "SL", "3A", "2A", "1A", "CC", "2S"}:
        raise ValueError("Choose a listed travel class.")
    query = urlencode({"origin": origin, "destination": destination, "date": travel_date,
                       "class": travel_class})
    separator = "&" if parsed_url.query else "?"
    request = Request(endpoint + separator + query,
                      headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=8) as response:
            raw = response.read(1_000_001)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise LiveServiceUnavailable("The live data provider is unavailable. Try again later.") from exc
    if len(raw) > 1_000_000:
        raise LiveServiceUnavailable("The live provider response was too large.")
    try:
        provider = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise LiveServiceUnavailable("The live provider returned invalid data.") from exc
    if not isinstance(provider, dict) or not isinstance(provider.get("trains"), list):
        raise LiveServiceUnavailable("The live provider response needs a train-data adapter.")
    trains = []
    for row in provider["trains"][:100]:
        if not isinstance(row, dict) or not str(row.get("train_no", "")).strip():
            continue
        fare = row.get("fare_rupees")
        if isinstance(fare, bool) or (fare is not None and
                                      (not isinstance(fare, (int, float)) or not math.isfinite(fare) or fare < 0)):
            fare = None
        trains.append({
            "train_no": str(row["train_no"])[:16],
            "name": str(row.get("name") or "Train")[:120],
            "class": str(row.get("class") or "")[:8],
            "fare_rupees": fare,
            "availability": str(row.get("availability") or "Unknown")[:80],
            "departure": str(row.get("departure") or "")[:32],
            "arrival": str(row.get("arrival") or "")[:32],
        })
    return {"origin": origin, "destination": destination, "travel_date": travel_date,
            "as_of": str(provider.get("as_of") or "Unknown"), "trains": trains,
            "source": "authorized live provider"}
