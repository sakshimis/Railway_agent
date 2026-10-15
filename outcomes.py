"""Live outcome monitoring for the Kaggle delay model (closes the predict -> observe -> evaluate loop).

For each watched train, fetch its live running status, look up what the delay model
predicted for the same train at the same station, and store the pair. The governance
page then reports live MAE against the global-mean baseline and the offline test MAE,
plus a bias/shift signal. Nothing here retrains automatically: an alert asks an admin
to evaluate a candidate, which keeps the existing approval gate in governance.py.

Run once a day (or more) while trains are running:
    python outcomes.py 12951 12127 11077
or put train numbers one per line in runtime/watch_trains.txt and run python outcomes.py
"""
from __future__ import annotations

import json
import sys
import threading
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
LOG = ROOT / "runtime" / "delay_outcomes.jsonl"
WATCHLIST = ROOT / "runtime" / "watch_trains.txt"
LOCK = threading.Lock()
MIN_SAMPLES = 30
DEGRADATION_FACTOR = 1.5   # alert when live MAE > 1.5 x offline test MAE
SHIFT_MINUTES = 15         # alert when mean observed delay moves this far from training mean


def record(train_no: str, station_code: str, predicted: float | None, actual: int,
           global_mean: float | None, source: str) -> dict:
    row = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "service_date": date.today().isoformat(), "train_no": str(train_no),
           "station_code": str(station_code).upper(), "predicted": predicted,
           "actual": int(actual), "baseline": global_mean, "source": source}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOCK:
        if _already_logged(row):
            return {**row, "skipped": "already observed today"}
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
    return row


def reconcile(train_numbers: list[str], fetch_status=None, estimate=None, global_mean=None) -> list[dict]:
    """Observe live delays and pair them with model estimates. Dependencies are injectable for tests."""
    if fetch_status is None:
        from live_providers import live_train_status as fetch_status
    if estimate is None or global_mean is None:
        from historical import delay_estimate, delay_model
        estimate = estimate or delay_estimate
        global_mean = global_mean if global_mean is not None else delay_model().get("global_mean")
    results = []
    for number in train_numbers:
        try:
            status = fetch_status(number)
        except Exception as exc:  # one failed train must not stop the run
            results.append({"train_no": number, "error": str(exc)})
            continue
        if status.get("delay_minutes") is None or not status.get("current_station"):
            results.append({"train_no": number, "error": "provider gave no delay/station"})
            continue
        predicted = estimate(number, status["current_station"]).get("minutes")
        results.append(record(number, status["current_station"], predicted,
                              status["delay_minutes"], global_mean, status.get("source", "")))
    return results


def summary(offline_test_mae: float | None = None) -> dict:
    rows = _rows()
    paired = [r for r in rows if r.get("predicted") is not None]
    report = {"observations": len(rows), "paired_with_model": len(paired), "alerts": [],
              "method": "live running delay vs historical model estimate at the same train and station",
              "notice": "Observed through a third-party live feed; a small, non-random sample of watched trains."}
    if not paired:
        report["status"] = "collecting data"
        return report
    mae = sum(abs(r["predicted"] - r["actual"]) for r in paired) / len(paired)
    base = [r for r in paired if r.get("baseline") is not None]
    base_mae = sum(abs(r["baseline"] - r["actual"]) for r in base) / len(base) if base else None
    bias = sum(r["predicted"] - r["actual"] for r in paired) / len(paired)
    mean_actual = sum(r["actual"] for r in paired) / len(paired)
    train_mean = base[0]["baseline"] if base else None
    report.update({
        "live_mae_minutes": round(mae, 2),
        "live_global_baseline_mae_minutes": round(base_mae, 2) if base_mae is not None else None,
        "offline_test_mae_minutes": offline_test_mae,
        "mean_bias_minutes": round(bias, 2),
        "mean_observed_delay": round(mean_actual, 2),
        "training_mean_delay": train_mean,
        "by_train": _by_train(paired),
    })
    enough = len(paired) >= MIN_SAMPLES
    if enough and offline_test_mae and mae > DEGRADATION_FACTOR * offline_test_mae:
        report["alerts"].append({"severity": "high", "area": "live model performance",
                                 "reason": f"live MAE {mae:.1f} min exceeds {DEGRADATION_FACTOR}x offline test MAE {offline_test_mae}",
                                 "action": "evaluate a retraining candidate; promotion still needs admin approval"})
    if enough and base_mae is not None and mae >= base_mae:
        report["alerts"].append({"severity": "medium", "area": "live model value",
                                 "reason": "model no better than the global mean on live observations",
                                 "action": "check route changes, season and station mapping"})
    if enough and train_mean is not None and abs(mean_actual - train_mean) > SHIFT_MINUTES:
        report["alerts"].append({"severity": "medium", "area": "data drift",
                                 "reason": f"mean observed delay {mean_actual:.1f} vs training mean {train_mean:.1f}",
                                 "action": "investigate seasonal effects (fog, monsoon) or disruptions"})
    report["status"] = ("attention" if report["alerts"] else
                        "healthy" if enough else f"collecting data ({len(paired)}/{MIN_SAMPLES})")
    return report


def _by_train(paired: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for r in paired:
        groups.setdefault(r["train_no"], []).append(r)
    return sorted(({"train_no": k, "n": len(v),
                    "mae_minutes": round(sum(abs(r["predicted"] - r["actual"]) for r in v) / len(v), 1)}
                   for k, v in groups.items()), key=lambda x: -x["mae_minutes"])[:10]


def _rows() -> list[dict]:
    if not LOG.exists():
        return []
    out = []
    for line in LOG.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _already_logged(row: dict) -> bool:
    return any(r["train_no"] == row["train_no"] and r["station_code"] == row["station_code"]
               and r["service_date"] == row["service_date"] for r in _rows())


def main() -> None:
    trains = sys.argv[1:]
    if not trains and WATCHLIST.exists():
        trains = [t.strip() for t in WATCHLIST.read_text(encoding="utf-8").splitlines()
                  if t.strip().isdigit()]
    if not trains:
        raise SystemExit("Give train numbers, e.g. python outcomes.py 12951 12127")
    for row in reconcile(trains):
        print(json.dumps(row))


if __name__ == "__main__":
    main()
