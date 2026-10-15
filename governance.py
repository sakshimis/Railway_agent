"""Local governance and audit controls for the synthetic railway demo."""
from __future__ import annotations

import hashlib
import json
import math
import threading
from datetime import datetime, timezone
from pathlib import Path

from railway import DATA, delay_prediction, read_csv, read_json, validate_train
from historical import report as kaggle_report

ROOT = Path(__file__).parent
AUDIT = ROOT / "runtime" / "audit.jsonl"
REGISTRY = ROOT / "runtime" / "model_registry.json"
LOCK = threading.Lock()


def _default_registry() -> dict:
    return {
        "active": {"delay": "historical-mean-demo-v1", "confirmation": "weighted-neighbors-demo-v1",
                   "fare": "fare-scenario-demo-v1", "fraud": "fraud-rules-demo-v1"},
        "candidate": None,
        "previous_delay_version": None,
        "active_delay_means": None,
        "previous_delay_means": None,
        "notice": "Local simulated registry. No production model is deployed.",
    }


def registry() -> dict:
    if not REGISTRY.exists():
        return _default_registry()
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _save_registry(value: dict) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(value, indent=2), encoding="utf-8")


def audit(event: str, payload: dict, latency_ms: int | None = None) -> None:
    """Append a small record. Raw chat messages and PNRs are not stored."""
    safe = {key: value for key, value in payload.items()
            if key not in {"original_text", "question", "pnr", "payment_details"}}
    if "request" in safe and isinstance(safe["request"], dict):
        safe["request"] = {k: v for k, v in safe["request"].items() if k != "original_text"}
    record = {"at": datetime.now(timezone.utc).isoformat(), "event": event,
              "payload": safe, "latency_ms": latency_ms}
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    with LOCK:
        with AUDIT.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def recent_audit(limit: int = 20) -> list[dict]:
    if not AUDIT.exists():
        return []
    lines = AUDIT.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines[-limit:] if line.strip()]


def governance_report() -> dict:
    trains = read_json("trains.json")
    history = read_csv("delay_history.csv")
    confirmation = read_csv("confirmation_history.csv")
    alerts: list[dict] = []
    models = []
    for train in trains:
        issues = validate_train(train)
        if issues:
            alerts.append({"severity": "high", "area": "data quality", "subject": train.get("name", "?"),
                           "reason": "; ".join(issues), "action": "quarantine the record"})
            continue
        stats = delay_prediction(train["id"])
        model = {"train": train["name"], "id": train["id"], **stats}
        models.append(model)
        if stats["invalid_observations"]:
            alerts.append({"severity": "high", "area": "data quality", "subject": train["name"],
                           "reason": f"{stats['invalid_observations']} invalid delay observations quarantined",
                           "action": "repair source data before using it for retraining"})
        if stats["examples"] < 5:
            alerts.append({"severity": "medium", "area": "model coverage", "subject": train["name"],
                           "reason": f"only {stats['examples']} delay examples",
                           "action": "collect validated observations before retraining"})
        if stats["mae_minutes"] is not None and stats["mae_minutes"] > 20:
            alerts.append({"severity": "high", "area": "model performance", "subject": train["name"],
                           "reason": f"leave-one-out error {stats['mae_minutes']} minutes",
                           "action": "investigate route changes and evaluate a candidate model"})
        values = []
        for row in history:
            if row.get("train_id") != train["id"]:
                continue
            try:
                value = int(row["delay_minutes"])
                if 0 <= value <= 600:
                    values.append(value)
            except (ValueError, KeyError, TypeError):
                pass
        if len(values) >= 6:
            midpoint = len(values) // 2
            shift = abs(sum(values[:midpoint]) / midpoint
                        - sum(values[midpoint:]) / (len(values) - midpoint))
            if shift > 30:
                alerts.append({"severity": "high", "area": "data drift", "subject": train["name"],
                               "reason": f"recent-versus-earlier average shift {shift:.1f} minutes",
                               "action": "check disruptions and refresh the delay model"})

    class_counts: dict[str, int] = {}
    for row in confirmation:
        class_counts[row["class"]] = class_counts.get(row["class"], 0) + 1
    for klass, count in class_counts.items():
        if count < 5:
            alerts.append({"severity": "medium", "area": "coverage disparity", "subject": klass,
                           "reason": f"only {count} confirmation examples",
                           "action": "collect more labels and evaluate errors by class"})
    events = recent_audit(100)
    latencies = [event["latency_ms"] for event in events if event.get("latency_ms") is not None]
    avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else None
    p95_latency = sorted(latencies)[math.ceil(.95 * len(latencies)) - 1] if latencies else None
    latency_slo_ms = 1000
    if len(latencies) >= 20 and p95_latency > latency_slo_ms:
        alerts.append({"severity": "medium", "area": "request latency", "subject": "local API",
                       "reason": f"recent p95 {p95_latency} ms exceeds {latency_slo_ms} ms target",
                       "action": "profile slow endpoints and review data-access costs"})
    abstentions = sum(1 for event in events if event["event"] == "support_abstained")
    feedback = [event["payload"].get("helpful") for event in events if event["event"] == "recommendation_feedback"]
    historical_feedback = [event["payload"].get("helpful") for event in events
                           if event["event"] == "historical_recommendation_feedback"]
    return {
        "status": "attention" if alerts else "healthy",
        "alerts": alerts,
        "delay_models": models,
        "confirmation_coverage_by_class": class_counts,
        "support_abstentions_in_recent_audit": abstentions,
        "recommendation_feedback": {"responses": len(feedback), "helpful": sum(value is True for value in feedback)},
        "historical_recommendation_feedback": {
            "responses": len(historical_feedback),
            "helpful": sum(value is True for value in historical_feedback),
            "sample": "most recent 100 audit events; voluntary feedback, not recommendation accuracy",
        },
        "recent_average_latency_ms": avg_latency,
        "recent_p95_latency_ms": p95_latency,
        "latency_sample_count": len(latencies),
        "latency_slo_ms": latency_slo_ms,
        "registry": registry(),
        "root_cause_summary": (
            "The main limits are sparse synthetic labels and, where flagged, unstable delay history."
            if alerts else "No demo threshold is currently exceeded."
        ),
        "policy": {
            "retrain": "Create and validate a candidate; promotion requires administrator approval.",
            "booking": "Never book or charge without a user-approved official integration.",
            "fairness": "Class coverage is reported; demographic fairness cannot be assessed without consented data.",
        },
        "data_notice": "Demo governance alerts and lifecycle controls use synthetic records. Kaggle source counts and the time-split delay test are separate historical-data evidence.",
        "kaggle_evidence": kaggle_report(),
    }


def retraining_candidate() -> dict:
    """Fit recent averages; evaluate against the last observation per train."""
    rows = read_csv("delay_history.csv")
    grouped: dict[str, list[int]] = {}
    for row in rows:
        try:
            value = int(row["delay_minutes"])
            if not 0 <= value <= 600:
                continue
            grouped.setdefault(row["train_id"], []).append(value)
        except (ValueError, KeyError, TypeError):
            continue
    if any(len(values) < 4 for values in grouped.values()):
        return {"status": "deferred", "reason": "At least four examples per train are required to hold one out."}
    results = []
    for train_id, values in grouped.items():
        training, actual = values[:-1], values[-1]
        baseline = sum(training) / len(training)
        recent = sum(training[-3:]) / min(3, len(training))
        results.append({"train_id": train_id, "baseline_error": abs(actual - baseline),
                        "candidate_error": abs(actual - recent), "candidate_mean": round(recent)})
    baseline_mae = round(sum(row["baseline_error"] for row in results) / len(results), 2)
    candidate_mae = round(sum(row["candidate_error"] for row in results) / len(results), 2)
    version_hash = hashlib.sha256(json.dumps(results, sort_keys=True).encode()).hexdigest()[:8]
    candidate = {"version": f"recent-mean-demo-{version_hash}",
                 "baseline_holdout_mae": baseline_mae, "candidate_holdout_mae": candidate_mae,
                 "per_train": results,
                 "eligible_for_approval": candidate_mae < baseline_mae,
                 "status": "awaiting admin approval" if candidate_mae < baseline_mae else "rejected by evaluation"}
    value = registry()
    value["candidate"] = candidate
    _save_registry(value)
    audit("retraining_candidate_evaluated", {"version": candidate["version"], "status": candidate["status"]})
    return candidate


def promote_candidate(role: str, approved: bool) -> dict:
    if role != "admin" or approved is not True:
        raise PermissionError("Administrator role and explicit approval are required.")
    value = registry()
    candidate = value.get("candidate")
    if not candidate or not candidate.get("eligible_for_approval"):
        raise ValueError("There is no validated candidate eligible for promotion.")
    value["previous_delay_version"] = value["active"]["delay"]
    value["previous_delay_means"] = value.get("active_delay_means")
    value["active"]["delay"] = candidate["version"]
    value["active_delay_means"] = {
        row["train_id"]: row["candidate_mean"] for row in candidate["per_train"]
    }
    value["candidate"] = None
    _save_registry(value)
    audit("model_promoted", {"version": value["active"]["delay"]})
    return value


def rollback_delay(role: str, approved: bool) -> dict:
    if role != "admin" or approved is not True:
        raise PermissionError("Administrator role and explicit approval are required.")
    value = registry()
    previous = value.get("previous_delay_version")
    if not previous:
        raise ValueError("No previous delay model version is available.")
    value["active"]["delay"], value["previous_delay_version"] = previous, value["active"]["delay"]
    value["active_delay_means"], value["previous_delay_means"] = (
        value.get("previous_delay_means"), value.get("active_delay_means")
    )
    _save_registry(value)
    audit("model_rolled_back", {"version": previous})
    return value
