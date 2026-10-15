"""Rebuild the historical catalog and evaluated delay model from public Kaggle ZIPs.

Usage: python import_kaggle.py PRICE_ZIP DELAY_ZIP CONFIRMATION_ZIP
The source archives are intentionally kept outside the distributable app.
"""
from __future__ import annotations

import ast
import csv
import io
import json
import math
import sqlite3
import sys
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).parent / "data"


def rows(archive: str, member: str):
    with zipfile.ZipFile(archive) as source, source.open(member) as stream:
        yield from csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig", newline=""))


def clean_clock(value):
    if not value or value == "--":
        return None
    try:
        return datetime.strptime(value, "%H:%M").strftime("%H:%M")
    except ValueError:
        return None


def add_schedule_stops(archive, catalog=DATA / "historical_catalog.sqlite"):
    """Index every scheduled stop, including routes absent from the fare file."""
    db = sqlite3.connect(catalog)
    db.execute("DROP TABLE IF EXISTS schedule_stops")
    db.execute("CREATE TABLE schedule_stops (train_no TEXT, train_name TEXT, seq INTEGER, code TEXT, name TEXT, arrival TEXT, departure TEXT, day_count INTEGER, distance_km INTEGER, PRIMARY KEY(train_no,seq))")
    batch = []
    for row in rows(archive, "schedules.csv"):
        try:
            stops = ast.literal_eval(row["stationList"])
            for seq, stop in enumerate(stops):
                batch.append((row["trainNumber"], row["trainName"], seq, stop["stationCode"],
                              stop["stationName"], clean_clock(stop.get("arrivalTime")),
                              clean_clock(stop.get("departureTime")), int(stop["dayCount"]),
                              int(float(stop["distance"]))))
        except (ValueError, SyntaxError, KeyError, TypeError):
            continue
        if len(batch) >= 5000:
            db.executemany("INSERT OR REPLACE INTO schedule_stops VALUES (?,?,?,?,?,?,?,?,?)", batch)
            batch.clear()
    db.executemany("INSERT OR REPLACE INTO schedule_stops VALUES (?,?,?,?,?,?,?,?,?)", batch)
    db.execute("CREATE INDEX IF NOT EXISTS schedule_code_idx ON schedule_stops(code,train_no,seq)")
    count = db.execute("SELECT COUNT(*) FROM schedule_stops").fetchone()[0]
    db.commit()
    db.close()
    return count


def build_catalog(archive):
    schedules = {}
    station_names = {}
    for row in rows(archive, "schedules.csv"):
        try:
            stops = ast.literal_eval(row["stationList"])
            if not isinstance(stops, list):
                continue
            for stop in stops:
                station_names[stop["stationCode"]] = stop["stationName"]
            schedules[row["trainNumber"]] = (row["trainName"], stops)
        except (ValueError, SyntaxError, KeyError, TypeError):
            continue
    path = DATA / "historical_catalog.sqlite"
    path.unlink(missing_ok=True)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE trains (train_no TEXT, name TEXT, origin_code TEXT, destination_code TEXT, origin TEXT, destination TEXT, class TEXT, fare INTEGER, distance INTEGER, departure TEXT, arrival TEXT, day_offset INTEGER, snapshot TEXT, PRIMARY KEY(train_no, origin_code, destination_code, class))")
    seen = valid = scheduled = 0
    batch = []
    for row in rows(archive, "price_data.csv"):
        seen += 1
        try:
            fare = int(round(float(row["totalFare"])))
            distance = int(round(float(row["distance"])))
            if not 0 < fare < 100000 or not 0 < distance < 10000:
                continue
            train_no = row["trainNumber"]
            origin_code = row["fromStnCode"]
            destination_code = row["toStnCode"]
            name, stops = schedules.get(train_no, (f"Train {train_no}", []))
            start = next((i for i, s in enumerate(stops) if s.get("stationCode") == origin_code), None)
            end = next((i for i, s in enumerate(stops) if start is not None and i > start and s.get("stationCode") == destination_code), None)
            departure = clean_clock(stops[start].get("departureTime")) if start is not None else None
            arrival = clean_clock(stops[end].get("arrivalTime")) if end is not None else None
            offset = int(stops[end].get("dayCount", "1")) - int(stops[start].get("dayCount", "1")) if end is not None else None
            if departure and arrival and offset is not None and 0 <= offset <= 7:
                scheduled += 1
            else:
                departure = arrival = offset = None
            batch.append((train_no, name, origin_code, destination_code,
                          station_names.get(origin_code, origin_code), station_names.get(destination_code, destination_code),
                          row["classCode"], fare, distance, departure, arrival, offset, row["timeStamp"][:10]))
            valid += 1
            if len(batch) == 5000:
                db.executemany("INSERT OR REPLACE INTO trains VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
                batch.clear()
        except (ValueError, TypeError, KeyError, IndexError):
            continue
    db.executemany("INSERT OR REPLACE INTO trains VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
    db.execute("CREATE INDEX route_idx ON trains(origin_code,destination_code)")
    count = db.execute("SELECT COUNT(*) FROM trains").fetchone()[0]
    db.commit()
    db.close()
    stop_count = add_schedule_stops(archive, path)
    return {"source_rows": seen, "valid_fare_rows": valid, "unique_fare_records": count,
            "rows_with_schedule_before_dedup": scheduled, "station_codes": len(station_names),
            "indexed_schedule_stops": stop_count,
            "snapshot": "October 2023", "source": "bhavyarajdev/indian-railways-schedule-prices-availability-data"}


def build_delay(archive):
    # Source dates are kept separate: earlier months train, later months test.
    train = defaultdict(lambda: [0, 0])
    pair = defaultdict(lambda: [0, 0])
    global_sum = global_n = 0
    test_abs = base_abs = test_n = test_seen = 0
    held_out = []
    seen = invalid = missing = 0
    for row in rows(archive, "combined_delay.csv"):
        seen += 1
        try:
            value = int(row["delay"])
            if not 0 <= value <= 600:
                invalid += 1
                continue
        except (ValueError, TypeError):
            missing += 1
            continue
        key = (row["train_no"], row["station_name"])
        if row["date"][:7] >= "2026-01":
            test_seen += 1
            if test_seen % 25 == 0:
                held_out.append((key, value))
        elif row["date"][:7] <= "2025-12":
            train[key[0]][0] += value
            train[key[0]][1] += 1
            pair[key][0] += value
            pair[key][1] += 1
            global_sum += value
            global_n += 1
    for key, value in held_out:
        train_sum, train_n = train.get(key[0], [0, 0])
        pair_sum, pair_n = pair.get(key, [0, 0])
        prior = (train_sum + 50 * (global_sum / global_n)) / (train_n + 50)
        pred = (pair_sum + 12 * prior) / (pair_n + 12)
        test_abs += abs(value - pred)
        base_abs += abs(value - global_sum / global_n)
        test_n += 1
    model = {"global_mean": round(global_sum / global_n, 3),
             "train": {k: [v[0], v[1]] for k, v in train.items()},
             "pair": {"|".join(k): [v[0], v[1]] for k, v in pair.items()}}
    (DATA / "delay_model.json").write_text(json.dumps(model, separators=(",", ":")), encoding="utf-8")
    return {"source_rows": seen, "training_rows": global_n, "test_rows": test_seen,
            "evaluated_test_sample_rows": test_n, "test_sampling": "every 25th valid test row",
            "missing_delay_rows": missing, "invalid_delay_rows": invalid,
            "train_station_pairs": len(pair), "trains": len(train),
            "test_mae_minutes": round(test_abs / test_n, 2),
            "global_baseline_mae_minutes": round(base_abs / test_n, 2),
            "training_period": "2025-02 through 2025-12", "test_period": "2026-01 through 2026-02",
            "source": "rxydenxd/indian-railways-delay-dataset"}


def assess_confirmation(archive):
    counts = defaultdict(lambda: [0, 0])
    seen = used = duplicate_status = confirmed_waitlist = 0
    for row in rows(archive, "Railway Ticket Confirmation.csv"):
        seen += 1
        if row["Current Status"].casefold() == row["Confirmation Status"].casefold():
            duplicate_status += 1
        if not row["Waitlist Position"].strip():
            continue
        try:
            pos = int(row["Waitlist Position"].upper().removeprefix("WL"))
            lead = (datetime.fromisoformat(row["Date of Journey"]) - datetime.fromisoformat(row["Booking Date"])).days
            label = int(row["Confirmation Status"].casefold() == "confirmed")
        except (ValueError, TypeError):
            continue
        if not 0 <= pos <= 500 or not 0 <= lead <= 365:
            continue
        used += 1
        confirmed_waitlist += label
        counts[(row["Class of Travel"], pos // 10, lead // 14)][0] += label
        counts[(row["Class of Travel"], pos // 10, lead // 14)][1] += 1
    return {"source_rows": seen, "usable_waitlist_rows": used, "confirmed_waitlist_rows": confirmed_waitlist,
            "current_status_equals_target_rows": duplicate_status,
            "synthetic": True, "source": "aaryananil/indian-railway-ticket-confirmation",
            "decision": "excluded from passenger prediction; synthetic outcomes and current status strongly reveals the target"}


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    DATA.mkdir(exist_ok=True)
    report = {"fare_catalog": build_catalog(sys.argv[1]),
              "delay_model": build_delay(sys.argv[2]),
              "confirmation_dataset_review": assess_confirmation(sys.argv[3])}
    (DATA / "kaggle_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    from train_fare_model import main as train_fare_model
    train_fare_model()
    print((DATA / "kaggle_report.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
