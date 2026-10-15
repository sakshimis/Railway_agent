"""Read-only search of Kaggle historical fare and schedule snapshots."""
from __future__ import annotations

import json
import sqlite3
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data"
CATALOG = DATA / "historical_catalog.sqlite"
ALIASES = {"pune": "PUNE", "delhi": "NDLS", "new delhi": "NDLS", "ratlam": "RTM",
           "mumbai": "CSMT", "mumbai csmt": "CSMT", "kolkata": "HWH",
           "chennai": "MAS", "bengaluru": "SBC", "bangalore": "SBC"}


def connection():
    if not CATALOG.exists():
        raise ValueError("Historical catalog has not been imported. Run import_kaggle.py first.")
    db = sqlite3.connect(CATALOG)
    db.row_factory = sqlite3.Row
    return db


def resolve_station(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Enter both origin and destination stations.")
    alias = ALIASES.get(value.casefold())
    if alias:
        return alias
    with connection() as db:
        exact = db.execute("SELECT origin_code FROM trains WHERE origin_code = ? LIMIT 1", (value.upper(),)).fetchone()
        if exact:
            return exact[0]
        exact = db.execute("SELECT origin_code FROM trains WHERE origin = ? COLLATE NOCASE LIMIT 1", (value,)).fetchone()
        if exact:
            return exact[0]
        exact = db.execute("SELECT code FROM schedule_stops WHERE code = ? LIMIT 1", (value.upper(),)).fetchone()
        if exact:
            return exact[0]
        exact = db.execute("SELECT code FROM schedule_stops WHERE name = ? COLLATE NOCASE LIMIT 1", (value,)).fetchone()
        if exact:
            return exact[0]
    raise ValueError(f"Station '{value}' is not in the historical catalog. Try a station code such as PUNE or NDLS.")


def stations(query: str) -> list[dict]:
    query = query.strip()
    if len(query) < 2:
        return []
    with connection() as db:
        rows = db.execute("SELECT code, MIN(name) AS name FROM schedule_stops WHERE code LIKE ? OR name LIKE ? GROUP BY code ORDER BY code LIMIT 15",
                          (query.upper() + "%", "%" + query.upper() + "%")).fetchall()
    return [dict(row) for row in rows]


def train_on_route(train_no: str, origin_code: str, destination_code: str) -> bool:
    """Confirm that a feedback target exists in the historical catalog."""
    if not (train_no.isdigit() and len(train_no) <= 6):
        return False
    if not (origin_code.isalnum() and destination_code.isalnum()
            and len(origin_code) <= 8 and len(destination_code) <= 8):
        return False
    start, end = origin_code.upper(), destination_code.upper()
    with connection() as db:
        fare = db.execute(
            "SELECT 1 FROM trains WHERE train_no=? AND origin_code=? AND destination_code=? LIMIT 1",
            (train_no, start, end),
        ).fetchone()
        if fare:
            return True
        timetable = db.execute("""
            SELECT 1 FROM schedule_stops a
            JOIN schedule_stops b ON a.train_no=b.train_no AND a.seq<b.seq
            WHERE a.train_no=? AND a.code=? AND b.code=? LIMIT 1
        """, (train_no, start, end)).fetchone()
        return timetable is not None


@lru_cache(maxsize=1)
def delay_model() -> dict:
    path = DATA / "delay_model.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


@lru_cache(maxsize=1)
def fare_model() -> dict:
    path = DATA / "fare_model.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def fare_estimates(distance_km: int, selected_class: str = "") -> list[dict]:
    classes = fare_model().get("classes", {})
    chosen = [selected_class] if selected_class else ["SL", "3A", "2A", "1A", "2S", "CC"]
    return [{"class": klass,
             "fare": round(max(1, classes[klass]["intercept"] + classes[klass]["per_km"] * distance_km)),
             "test_mae_rupees": classes[klass]["test_mae_rupees"], "estimated": True}
            for klass in chosen if klass in classes]


def delay_estimate(train_no: str, station_code: str) -> dict:
    model = delay_model()
    if not model:
        return {"minutes": None, "observations": 0}
    train_sum, train_n = model["train"].get(train_no, [0, 0])
    pair_sum, pair_n = model["pair"].get(train_no + "|" + station_code, [0, 0])
    prior = (train_sum + 50 * model["global_mean"]) / (train_n + 50)
    value = (pair_sum + 12 * prior) / (pair_n + 12)
    return {"minutes": round(value), "observations": pair_n}


def search(origin: str, destination: str, travel_class: str = "", max_fare: int | None = None,
           sort: str = "fare", max_duration_minutes: int | None = None) -> dict:
    start = resolve_station(origin)
    end = resolve_station(destination)
    if start == end:
        raise ValueError("Origin and destination must differ.")
    if max_fare is not None and not 0 < max_fare < 1000000:
        raise ValueError("Budget must be a positive rupee amount.")
    if sort not in {"fare", "duration", "departure"}:
        raise ValueError("Unknown sort option.")
    if max_duration_minutes is not None and not 0 < max_duration_minutes <= 7 * 1440:
        raise ValueError("Maximum journey duration must be between 1 minute and 7 days.")
    with connection() as db:
        records = db.execute("SELECT * FROM trains WHERE origin_code=? AND destination_code=? AND departure IS NOT NULL AND arrival IS NOT NULL",
                             (start, end)).fetchall()
    options = []
    for row in records:
        item = dict(row)
        if travel_class and item["class"].upper() != travel_class.upper():
            continue
        if max_fare is not None and item["fare"] > max_fare:
            continue
        dep_hour, dep_min = map(int, item["departure"].split(":"))
        arr_hour, arr_min = map(int, item["arrival"].split(":"))
        duration = item["day_offset"] * 1440 + arr_hour * 60 + arr_min - dep_hour * 60 - dep_min
        if duration <= 0 or duration > 7 * 1440:
            continue
        if max_duration_minutes is not None and duration > max_duration_minutes:
            continue
        item["duration_minutes"] = duration
        item["delay_history"] = delay_estimate(item["train_no"], end)
        item.pop("snapshot", None)
        options.append(item)
    grouped = {}
    for item in options:
        train_no = item["train_no"]
        if train_no not in grouped:
            grouped[train_no] = {key: item[key] for key in (
                "train_no", "name", "origin_code", "destination_code", "origin", "destination",
                "departure", "arrival", "day_offset", "duration_minutes", "delay_history")}
            grouped[train_no]["fares"] = []
        grouped[train_no]["fares"].append({"class": item["class"], "fare": item["fare"]})
    trains = list(grouped.values())
    for item in trains:
        item["fares"].sort(key=lambda fare: fare["fare"])
    trains.sort(key=lambda item: (item["fares"][0]["fare"], item["duration_minutes"]) if sort == "fare"
                else (item["duration_minutes"], item["fares"][0]["fare"]) if sort == "duration"
                else (item["departure"], item["fares"][0]["fare"]))
    # The schedule file covers routes for which the fare file has no direct pair.
    with connection() as db:
        schedule_rows = db.execute("""
            SELECT a.train_no, a.train_name AS name, a.name AS origin, b.name AS destination,
                   a.departure, b.arrival, b.day_count - a.day_count AS day_offset,
                   b.distance_km - a.distance_km AS distance_km
            FROM schedule_stops a JOIN schedule_stops b ON a.train_no = b.train_no AND a.seq < b.seq
            WHERE a.code = ? AND b.code = ? AND a.departure IS NOT NULL AND b.arrival IS NOT NULL
        """, (start, end)).fetchall()
    schedule_only = []
    priced_train_numbers = {item["train_no"] for item in trains}
    seen_schedule_numbers = set()
    for row in schedule_rows:
        item = dict(row)
        if item["train_no"] in priced_train_numbers or item["train_no"] in seen_schedule_numbers:
            continue
        duration = item["day_offset"] * 1440
        duration += int(item["arrival"][:2]) * 60 + int(item["arrival"][3:])
        duration -= int(item["departure"][:2]) * 60 + int(item["departure"][3:])
        if not 0 < duration <= 7 * 1440:
            continue
        if max_duration_minutes is not None and duration > max_duration_minutes:
            continue
        if not 0 < item["distance_km"] <= 4000:
            continue
        item["duration_minutes"] = duration
        item["origin_code"] = start
        item["destination_code"] = end
        item["delay_history"] = delay_estimate(item["train_no"], end)
        item["fare_estimates"] = fare_estimates(item["distance_km"], travel_class)
        ranking_class = travel_class or "SL"
        item["ranking_estimated_fare"] = next((fare["fare"] for fare in item["fare_estimates"]
                                                if fare["class"] == ranking_class), None)
        schedule_only.append(item)
        seen_schedule_numbers.add(item["train_no"])
    schedule_only.sort(key=lambda item: (item["ranking_estimated_fare"] or float("inf"), item["duration_minutes"], item["departure"])
                       if sort == "fare" else (item["duration_minutes"], item["departure"])
                       if sort == "duration" else (item["departure"], item["duration_minutes"]))
    return {"origin_code": start, "destination_code": end, "matching_trains": len(trains),
            "matching_class_fares": len(options), "options": trains[:30], "snapshot": "October 2023",
            "schedule_only_count": len(schedule_only), "schedule_only": schedule_only[:30],
            "sort_used": sort, "class_filter": travel_class, "budget_limit": max_fare,
            "max_duration_minutes": max_duration_minutes,
            "notice": "Historical Kaggle fare and timetable snapshot. Current ticket prices, running days, seats and availability for your travel date are unknown. Verify with an official railway service before booking."}


def report() -> dict:
    path = DATA / "kaggle_report.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"status": "not imported"}
