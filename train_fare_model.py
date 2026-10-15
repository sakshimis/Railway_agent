"""Fit and evaluate class-specific historical fare estimates from the Kaggle catalog.

The holdout is split by train number, so records from a test train are never used
to fit its estimate. Run after import_kaggle.py.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).parent / "data"


def test_train(train_no: str) -> bool:
    return int(hashlib.md5(train_no.encode()).hexdigest()[:4], 16) % 5 == 0


def fit(rows):
    n = len(rows)
    sx = sum(x for x, _ in rows)
    sy = sum(y for _, y in rows)
    sxx = sum(x * x for x, _ in rows)
    sxy = sum(x * y for x, y in rows)
    slope = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    return [(sy - slope * sx) / n, slope]


def main():
    with sqlite3.connect(DATA / "historical_catalog.sqlite") as db:
        data = db.execute("SELECT train_no, class, distance, fare FROM trains WHERE distance BETWEEN 10 AND 4000 AND fare BETWEEN 20 AND 10000").fetchall()
    train = defaultdict(list)
    test = defaultdict(list)
    for number, klass, distance, fare in data:
        (test if test_train(number) else train)[klass].append((distance, fare))
    classes = {}
    for klass, observations in train.items():
        coefficients = fit(observations)
        held_out = test[klass]
        errors = [abs(actual - max(1, coefficients[0] + coefficients[1] * distance))
                  for distance, actual in held_out]
        classes[klass] = {"intercept": round(coefficients[0], 6),
                          "per_km": round(coefficients[1], 6),
                          "training_rows": len(observations),
                          "test_rows": len(held_out),
                          "test_mae_rupees": round(sum(errors) / len(errors), 2)}
    model = {"method": "class-specific linear historical fare estimate",
             "classes": classes, "split": "20% of train numbers held out by stable hash",
             "training_rows": sum(len(v) for v in train.values()),
             "test_rows": sum(len(v) for v in test.values()),
             "source_period": "October 2023",
             "warning": "Estimates are not quoted fares. Class availability and current price are not verified."}
    (DATA / "fare_model.json").write_text(json.dumps(model, indent=2), encoding="utf-8")
    report_path = DATA / "kaggle_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["fare_estimator"] = model
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(model, indent=2))


if __name__ == "__main__":
    main()
