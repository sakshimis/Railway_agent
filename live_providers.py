"""Provider router for live railway data.

Order of preference:
1. The existing authorized normalized gateway in live_railway.py
   (RAILWAY_LIVE_API_URL + RAILWAY_LIVE_API_TOKEN).
2. A RapidAPI-hosted Indian Railways provider, for ACADEMIC DEMO use only
   (RAPIDAPI_KEY + RAPIDAPI_HOST). These providers are third-party and unofficial.
3. Nothing configured -> LiveServiceUnavailable (the app's existing 503 behaviour).

Endpoint paths differ between RapidAPI providers. Set them with environment variables:
  RAPIDAPI_PATH_BETWEEN, RAPIDAPI_PATH_PNR, RAPIDAPI_PATH_SEATS, RAPIDAPI_PATH_LIVE
A path may contain placeholders, e.g. /getPNRStatus/{pnrNumber}; they are filled from the
request values and the remaining values are sent as the query string.
Credentials stay on the Python server and are never sent to the browser.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from datetime import date, datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import live_railway
from live_railway import LiveServiceUnavailable

CLASSES = {"SL", "3A", "2A", "1A", "CC", "2S"}
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_RATE_LOCK = threading.Lock()
_last_call = 0.0
TTL_SECONDS = {"between": 3600, "pnr": 300, "seats": 600, "live": 120, "schedule": 3600, "fare": 600}
DEFAULT_PATHS = {  # PNR, schedule and fare paths are confirmed from user screenshots
    "between": "",
    "pnr": "/getPNRStatus/{pnrNumber}",
    "seats": "",
    "live": "",
    "schedule": "/schedule/{trainNo}",
    "fare": "/fare",
}


# ---------------------------------------------------------------- routing
def rapid_configured() -> bool:
    return bool(os.getenv("RAPIDAPI_KEY") and os.getenv("RAPIDAPI_HOST"))


def configured() -> bool:
    """Whether route fares/seats can be requested; PNR has its own capability."""
    return live_railway.configured() or (rapid_configured() and bool(os.getenv("RAPIDAPI_PATH_BETWEEN")))


def pnr_configured() -> bool:
    return live_railway.configured() or rapid_configured()


def schedule_configured() -> bool:
    return rapid_configured()


def fare_configured() -> bool:
    return rapid_configured()


def provider_name() -> str:
    if live_railway.configured():
        return "authorized live provider"
    if rapid_configured():
        return "third-party RapidAPI provider (academic demo, unofficial)"
    return "not connected"


def search_live(origin: str, destination: str, travel_date: str, travel_class: str = "") -> dict:
    if live_railway.configured():
        return live_railway.search_live(origin, destination, travel_date, travel_class)
    if not (rapid_configured() and os.getenv("RAPIDAPI_PATH_BETWEEN")):
        raise LiveServiceUnavailable("Live fares and seats are not connected yet.")
    origin, destination = _station(origin), _station(destination)
    if origin == destination:
        raise ValueError("Choose different origin and destination stations.")
    _journey_date(travel_date)
    travel_class = _klass(travel_class, allow_blank=True)
    data = _rapid("between", {"fromStationCode": origin, "toStationCode": destination,
                               "dateOfJourney": travel_date})
    trains = []
    for row in _rows(data)[:100]:
        number = _pick(row, "train_number", "trainNumber", "train_no", "trainNo", "number")
        if not number:
            continue
        classes = _pick(row, "class_type", "classes", "avlClasses", "class") or []
        if travel_class and isinstance(classes, list) and classes and travel_class not in classes:
            continue
        trains.append({
            "train_no": str(number)[:16],
            "name": str(_pick(row, "train_name", "trainName", "name") or "Train")[:120],
            "class": travel_class or (", ".join(classes)[:40] if isinstance(classes, list) else str(classes)[:40]),
            "fare_rupees": None,  # route search does not return a verified fare; use seat check
            "availability": "Check seats",
            "departure": str(_pick(row, "from_std", "departureTime", "departure", "from_time") or "")[:32],
            "arrival": str(_pick(row, "to_sta", "arrivalTime", "arrival", "to_time") or "")[:32],
        })
    return {"origin": origin, "destination": destination, "travel_date": travel_date,
            "as_of": _now(), "trains": trains, "source": provider_name()}


def search_live_pnr(pnr: str) -> dict:
    if live_railway.configured():
        return live_railway.search_live_pnr(pnr)
    if not rapid_configured():
        raise LiveServiceUnavailable("Live PNR enquiry is not connected yet.")
    pnr = str(pnr).strip()
    if not re.fullmatch(r"\d{10}", pnr):
        raise ValueError("Enter a valid 10-digit PNR number.")
    data = _rapid("pnr", {"pnrNumber": pnr})
    body = _body(data)
    passengers = body.get("PassengerStatus") or body.get("passengers") or body.get("passengerList") or body.get("passengerStatus") or []
    first = passengers[0] if isinstance(passengers, list) and passengers and isinstance(passengers[0], dict) else {}
    status = (_pick(first, "CurrentStatus", "currentStatus", "current_status", "currentStatusDetails")
              or _pick(body, "status", "currentStatus", "current_status"))
    train_no = _pick(body, "TrainNo", "trainNumber", "train_no", "trainNo")
    if not status and not train_no:
        raise LiveServiceUnavailable("The PNR provider returned no usable status for this number.")
    chart = _pick(body, "ChartPrepared", "chartStatus", "chart_prepared")
    return {
        "pnr": pnr,
        "train_no": str(train_no or "")[:16],
        "train_name": str(_pick(body, "TrainName", "trainName", "train_name") or "")[:120],
        "journey_date": str(_pick(body, "Doj", "dateOfJourney", "journey_date") or "")[:32],
        "class": str(_pick(body, "Class", "journeyClass", "class") or "")[:8],
        "status": str(status or "Status not provided")[:60],
        "booking_status": str(_pick(first, "BookingStatus", "bookingStatus", "bookingStatusDetails") or "")[:60],
        "chart_prepared": chart is True or str(chart).strip().lower() in {"true", "yes", "prepared"},
        "as_of": _now(),
        "source": provider_name(),
    }


def search_live_schedule(train_no: str) -> dict:
    """Look up the provider's current published timetable for one train number."""
    if not rapid_configured():
        raise LiveServiceUnavailable("Train schedule lookup is not connected yet.")
    train_no = _train(train_no)
    data = _rapid("schedule", {"trainNo": train_no})
    body = data.get("data", data)
    if isinstance(body, list):
        rows, details = body, {}
    elif isinstance(body, dict):
        details = body
        rows = next((body[k] for k in ("route", "stations", "schedule", "stops", "stationList")
                     if isinstance(body.get(k), list)), None)
        if rows is None and isinstance(body.get("data"), dict):
            nested = body["data"]
            rows = next((nested[k] for k in ("route", "stations", "schedule", "stops", "stationList")
                         if isinstance(nested.get(k), list)), None)
            details = nested
    else:
        rows, details = None, {}
    if not isinstance(rows, list):
        raise LiveServiceUnavailable("The schedule provider returned an unfamiliar format; mapping is needed.")
    stops = []
    for row in rows[:200]:
        if not isinstance(row, dict):
            continue
        code = _pick(row, "stationCode", "station_code", "stationNo", "code", "station")
        name = _pick(row, "stationName", "station_name", "name")
        if not code and not name:
            continue
        stops.append({
            "station_code": str(code or "")[:12],
            "station_name": str(name or "")[:100],
            "arrival": str(_pick(row, "arrivalTime", "arrival_time", "arrival", "sta") or "")[:32],
            "departure": str(_pick(row, "departureTime", "departure_time", "departure", "std") or "")[:32],
            "day": str(_pick(row, "day", "dayCount", "day_number", "dayNumber") or "")[:8],
        })
    if not stops:
        raise LiveServiceUnavailable("The provider returned no usable station stops for this train.")
    return {"train_no": train_no,
            "train_name": str(_pick(details, "trainName", "train_name", "name") or "")[:120],
            "stops": stops, "as_of": _now(), "source": provider_name(),
            "notice": "Provider timetable enquiry; running days and service on a chosen date are not verified."}


def search_provider_fare(origin: str, destination: str, travel_class: str,
                         adults: int = 1, children: int = 0, quota: str = "GN") -> dict:
    """Get per-train indicative fares for a route/class (no travel date in API)."""
    if not rapid_configured():
        raise LiveServiceUnavailable("Provider fare enquiry is not connected yet.")
    origin, destination = _station(origin), _station(destination)
    if origin == destination:
        raise ValueError("Choose different origin and destination stations.")
    travel_class = _klass(travel_class)
    if type(adults) is not int or not 1 <= adults <= 6 or type(children) is not int or not 0 <= children <= 6:
        raise ValueError("Choose 1–6 adults and 0–6 children.")
    quota = str(quota).strip().upper()
    if quota not in {"GN", "TQ"}:
        raise ValueError("Choose General (GN) or Tatkal (TQ) quota.")
    data = _rapid("fare", {"adults": adults, "from": origin, "to": destination,
                            "class": travel_class, "children": children, "quota": quota})
    body = data.get("data", data)
    if not isinstance(body, dict):
        raise LiveServiceUnavailable("The fare provider returned an unfamiliar format; mapping is needed.")
    rows = body.get("trains")
    if not isinstance(rows, list):
        raise LiveServiceUnavailable("The fare provider returned an unfamiliar train list; mapping is needed.")
    options = []
    for train in rows[:500]:
        if not isinstance(train, dict):
            continue
        train_no = str(train.get("train_no") or "").strip()
        if not re.fullmatch(r"\d{4,6}", train_no):
            continue
        for item in train.get("fares", []) if isinstance(train.get("fares"), list) else []:
            if not isinstance(item, dict) or str(item.get("class", "")).upper() != travel_class:
                continue
            fare = _parse_rupees(item.get("total_fare"))
            if fare is None or not math.isfinite(fare) or not 0 < fare < 1_000_000:
                continue
            options.append({"train_no": train_no,
                            "train_name": str(train.get("train_name") or "")[:100],
                            "type": str(train.get("type") or "")[:40],
                            "fare_rupees": round(fare, 2),
                            "dynamic_fare": item.get("dynamic_fare") is True})
    options.sort(key=lambda row: (row["fare_rupees"], row["train_no"]))
    return {"origin": origin, "destination": destination, "class": travel_class,
            "adults": adults, "children": children, "quota": quota,
            "trains": options, "count": len(options), "as_of": _now(), "source": provider_name(),
            "provider_note": str(body.get("note") or "")[:400],
            "notice": "Indicative provider fares by train. The request has no travel date; dynamic-fare amounts are base fares, not live ticket prices. Verify before booking."}


def _find_fare_value(body: dict, depth: int = 0):
    """Find a total fare in common wrappers without using base-fare components."""
    if depth > 3:
        return None
    direct = _pick(body, "totalFare", "total_fare", "totalAmount", "total_amount",
                   "fareAmount", "ticketFare", "fare_rupees", "fare", "amount")
    if direct is not None and not isinstance(direct, (dict, list)):
        return direct
    for key in ("fare", "fareDetails", "fare_details", "fareBreakup", "fare_breakup",
                "pricing", "price", "result", "data"):
        nested = body.get(key)
        if isinstance(nested, dict):
            found = _find_fare_value(nested, depth + 1)
            if found is not None:
                return found
    return None


def _parse_rupees(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.fullmatch(r"\s*(?:₹|Rs\.?|INR)?\s*([\d,]+(?:\.\d{1,2})?)\s*",
                         str(value), re.IGNORECASE)
    return float(match.group(1).replace(",", "")) if match else None


def search_live_seats(train_no: str, travel_date: str, travel_class: str,
                      origin: str = "", destination: str = "") -> dict:
    if live_railway.configured():
        return live_railway.search_live_seats(train_no, travel_date, travel_class, origin, destination)
    if not (rapid_configured() and os.getenv("RAPIDAPI_PATH_SEATS")):
        raise LiveServiceUnavailable("Live seat availability is not connected yet.")
    train_no = _train(train_no)
    _journey_date(travel_date)
    travel_class = _klass(travel_class)
    if not (origin and destination):
        raise ValueError("Origin and destination are required for seat availability.")
    data = _rapid("seats", {"trainNo": train_no, "fromStationCode": _station(origin),
                             "toStationCode": _station(destination), "date": travel_date,
                             "classType": travel_class, "quota": "GN"})
    rows = _rows(data)
    row = rows[0] if rows else _body(data)
    fare = _pick(row, "total_fare", "totalFare", "fare", "fare_rupees")
    try:
        fare = float(fare) if fare not in (None, "") else None
        if fare is not None and not 0 <= fare < 100000:
            fare = None
    except (TypeError, ValueError):
        fare = None
    return {"train_no": train_no, "travel_date": travel_date, "class": travel_class,
            "availability": str(_pick(row, "current_status", "availablityStatus", "availability",
                                      "status") or "Unknown")[:80],
            "fare_rupees": fare, "as_of": _now(), "source": provider_name()}


def live_train_status(train_no: str, start_day: str = "") -> dict:
    """Current running status. Only a third-party provider is wired for this today."""
    if not (rapid_configured() and os.getenv("RAPIDAPI_PATH_LIVE")):
        raise LiveServiceUnavailable("Live running status is not connected yet.")
    train_no = _train(train_no)
    params = {"trainNo": train_no}
    if start_day:
        params["startDay"] = start_day
    body = _body(_rapid("live", params))
    delay = _pick(body, "delay", "delay_minutes", "late_mins", "delayInMinutes")
    try:
        delay = int(float(delay)) if delay not in (None, "") else None
        if delay is not None and not -60 <= delay <= 1440:
            delay = None
    except (TypeError, ValueError):
        delay = None
    return {
        "train_no": train_no,
        "current_station": str(_pick(body, "current_station_code", "currentStationCode",
                                     "current_station", "lastStation") or "")[:16],
        "current_station_name": str(_pick(body, "current_station_name", "currentStationName") or "")[:80],
        "delay_minutes": delay,
        "status_message": str(_pick(body, "status_as_of", "statusMessage", "message") or "")[:160],
        "as_of": _now(),
        "source": provider_name(),
    }


# ---------------------------------------------------------------- internals
def _rapid(kind: str, params: dict) -> dict:
    global _last_call
    key, host = os.getenv("RAPIDAPI_KEY", "").strip(), os.getenv("RAPIDAPI_HOST", "").strip()
    if not (key and host):
        raise LiveServiceUnavailable("Live railway data is not connected yet.")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", host):
        raise LiveServiceUnavailable("RAPIDAPI_HOST must be a bare host name.")
    path = os.getenv(f"RAPIDAPI_PATH_{kind.upper()}", DEFAULT_PATHS[kind])
    if not path:
        raise LiveServiceUnavailable(f"This provider has no configured {kind} endpoint.")
    if not path.startswith("/") or "//" in path or "?" in path or "#" in path:
        raise LiveServiceUnavailable("Provider paths must be simple absolute paths starting with '/'.")
    query = dict(params)
    for name in re.findall(r"{(\w+)}", path):
        if name not in query:
            raise LiveServiceUnavailable(f"Provider path needs '{name}', which this request does not supply.")
        path = path.replace("{" + name + "}", quote(str(query.pop(name)), safe=""))
    url = f"https://{host}{path}" + (f"?{urlencode(query)}" if query else "")
    with _CACHE_LOCK:
        hit = _CACHE.get(url)
        if hit and time.time() - hit[0] < TTL_SECONDS[kind]:
            return hit[1]
    with _RATE_LOCK:  # free tiers are small: at most one call per second
        wait = 1.0 - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
    request = Request(url, headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": host,
                                    "Accept": "application/json"})
    try:
        timeout = min(max(float(os.getenv("RAPIDAPI_TIMEOUT", "25")), 3), 60)
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(1_000_001)
    except HTTPError as exc:
        if exc.code == 429:
            raise LiveServiceUnavailable("Live data quota reached. Try again later.") from exc
        if exc.code in (401, 403):
            raise LiveServiceUnavailable("Live provider rejected the key or subscription.") from exc
        raise LiveServiceUnavailable("The live data provider is unavailable. Try again later.") from exc
    except TimeoutError as exc:
        raise LiveServiceUnavailable("The live provider took too long to answer. Try again, "
                                     "or raise RAPIDAPI_TIMEOUT.") from exc
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise LiveServiceUnavailable("The live provider took too long to answer. Try again, "
                                         "or raise RAPIDAPI_TIMEOUT.") from exc
        raise LiveServiceUnavailable("The live data provider is unavailable. Try again later.") from exc
    if len(raw) > 1_000_000:
        raise LiveServiceUnavailable("The live provider response was too large.")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise LiveServiceUnavailable("The live provider returned invalid data.") from exc
    if not isinstance(data, dict):
        raise LiveServiceUnavailable("The live provider response needs an adapter.")
    if data.get("status") is False or data.get("success") is False:
        raise LiveServiceUnavailable(str(data.get("message") or "The provider rejected the request.")[:160])
    with _CACHE_LOCK:
        _CACHE[url] = (time.time(), data)
    return data


def _body(data: dict) -> dict:
    inner = data.get("data", data)
    return inner if isinstance(inner, dict) else {}


def _rows(data: dict) -> list[dict]:
    inner = data.get("data", data)
    if isinstance(inner, dict):
        inner = inner.get("trains") or inner.get("trainList") or inner.get("data") or []
    return [row for row in inner if isinstance(row, dict)] if isinstance(inner, list) else []


def _pick(row: dict, *keys):
    for key in keys:
        if isinstance(row, dict) and row.get(key) not in (None, ""):
            return row[key]
    return None


def _station(code: str) -> str:
    code = str(code).strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{2,8}", code):
        raise ValueError("Enter valid origin and destination station codes.")
    return code


def _train(number: str) -> str:
    number = str(number).strip()
    if not (number.isdigit() and len(number) <= 6):
        raise ValueError("Enter a valid train number.")
    return number


def _klass(value: str, allow_blank: bool = False) -> str:
    value = str(value).strip().upper()
    if (allow_blank and not value) or value in CLASSES:
        return value
    raise ValueError("Choose a valid travel class (SL, 3A, 2A, 1A, CC, 2S).")


def _journey_date(value: str) -> None:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Enter a valid journey date.") from exc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
