"""Offline passenger services for the railway case-study demonstration.

Every record is synthetic. Functions return evidence and limitations with results.
"""
from __future__ import annotations

import csv
import json
import math
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"


def read_json(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def read_csv(name: str) -> list[dict]:
    with (DATA / name).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def parse_clock(value: str, period: str | None = None) -> time:
    parts = value.split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) == 2 else 0
    if minute > 59 or hour > 23:
        raise ValueError("Invalid time.")
    if period:
        if not 1 <= hour <= 12:
            raise ValueError("Use a 1–12 hour time with AM or PM.")
        hour = (hour % 12) + (12 if period.upper() == "PM" else 0)
    return time(hour, minute)


def parse_request(text: str, today: date | None = None) -> dict:
    """Extract the constrained language supported by this transparent demo."""
    today = today or date.today()
    route = re.search(
        r"\bfrom\s+([a-z][a-z ]*?)\s+to\s+([a-z][a-z ]*?)"
        r"(?=\s+(?:today|tomorrow|on|under|below|within|before|in|by|with|fastest|quickest|cheapest)\b|[,.!?]|$)",
        text, re.I,
    )
    if not route:
        raise ValueError("Include a route such as 'from Pune to Delhi'.")
    explicit = re.search(r"\bon\s+(\d{4}-\d{2}-\d{2})\b", text, re.I)
    if explicit:
        travel_date = date.fromisoformat(explicit.group(1))
    elif re.search(r"\btomorrow\b", text, re.I):
        travel_date = today + timedelta(days=1)
    else:
        travel_date = today
    if travel_date < today:
        raise ValueError("The journey date cannot be in the past.")
    budget = re.search(r"\b(?:under|below|within)\s*(?:₹|rs\.?\s*)?([\d,]+)(?![\d,]|\s*(?:hours?|hrs?)\b)", text, re.I)
    deadline = re.search(r"\b(?:before|by)\s+(\d{1,2}(?::\d{2})?)\s*(AM|PM)?\b", text, re.I)
    klass = re.search(r"\b(sleeper|3ac|2ac|1ac|chair car|chair|cc|2s|second sitting)\b", text, re.I)
    duration = re.search(r"\b(?:within|under|max(?:imum)?)\s+(\d{1,2})\s*(?:hours?|hrs?)\b", text, re.I)
    if re.search(r"\b(?:fastest|quickest)\b", text, re.I):
        preference = "fastest"
    elif re.search(r"\b(?:balanced|smart|recommended|best)\b", text, re.I):
        preference = "balanced"
    else:
        preference = "cheapest"
    norm_class = None
    if klass:
        raw_k = klass.group(1).lower()
        class_map = {"chair": "CHAIR CAR", "cc": "CHAIR CAR", "second sitting": "2S", "sleeper": "SLEEPER"}
        norm_class = class_map.get(raw_k, raw_k.upper())
    return {
        "origin": route.group(1).strip().title(),
        "destination": route.group(2).strip().title(),
        "date": travel_date.isoformat(),
        "budget": int(budget.group(1).replace(",", "")) if budget else None,
        "arrive_before": parse_clock(deadline.group(1), deadline.group(2)).strftime("%H:%M") if deadline else None,
        "class": norm_class,
        "maximum_duration_hours": int(duration.group(1)) if duration else None,
        "preference": preference,
        "original_text": text,
    }


def validate_train(train: dict) -> list[str]:
    required = ("id", "name", "origin", "destination", "departure", "arrival",
                "arrival_day_offset", "class", "fare", "seats", "wl_position", "demand_index")
    issues = [f"missing {key}" for key in required if key not in train]
    if issues:
        return issues
    try:
        parse_clock(train["departure"])
        parse_clock(train["arrival"])
        for key in ("id", "name", "origin", "destination", "class"):
            if not isinstance(train[key], str) or not train[key].strip():
                issues.append(f"invalid {key}")
        if (isinstance(train["fare"], bool) or not isinstance(train["fare"], (int, float))
                or not math.isfinite(train["fare"]) or train["fare"] < 0):
            issues.append("invalid fare")
        if not isinstance(train["arrival_day_offset"], int) or train["arrival_day_offset"] < 0:
            issues.append("invalid arrival day")
        if not isinstance(train["seats"], int) or train["seats"] < 0:
            issues.append("invalid seat count")
        if not isinstance(train["wl_position"], int) or train["wl_position"] < 0:
            issues.append("invalid WL position")
        if (not isinstance(train["demand_index"], (int, float))
                or not 0 <= train["demand_index"] <= 1):
            issues.append("invalid demand index")
    except (ValueError, TypeError, AttributeError):
        issues.append("invalid schedule or numeric field")
    return issues


def delay_prediction(train_id: str) -> dict:
    values = []
    invalid_observations = 0
    for row in read_csv("delay_history.csv"):
        if row.get("train_id") != train_id:
            continue
        try:
            value = int(row["delay_minutes"])
            if not 0 <= value <= 600:
                raise ValueError("out of range")
            values.append(value)
        except (ValueError, KeyError, TypeError):
            invalid_observations += 1
    if not values:
        return {"minutes": None, "examples": 0, "invalid_observations": invalid_observations,
                "mae_minutes": None, "method": "unavailable"}
    average = round(sum(values) / len(values))
    method = "historical mean, synthetic examples"
    registry_path = ROOT / "runtime" / "model_registry.json"
    if registry_path.exists():
        active = json.loads(registry_path.read_text(encoding="utf-8"))
        promoted_means = active.get("active_delay_means") or {}
        if train_id in promoted_means:
            average = promoted_means[train_id]
            method = f"approved candidate {active['active']['delay']}, synthetic examples"
    if len(values) > 1:
        errors = [abs(actual - (sum(values) - actual) / (len(values) - 1)) for actual in values]
        mae = round(sum(errors) / len(errors), 1)
    else:
        mae = None
    return {"minutes": average, "examples": len(values), "invalid_observations": invalid_observations,
            "mae_minutes": mae,
            "method": method}


def confirmation_prediction(wl_position: int, days_before: int, travel_class: str) -> dict:
    """Weighted neighbor estimate with Beta(1,1) smoothing on synthetic labels."""
    if wl_position < 0 or days_before < 0:
        raise ValueError("WL position and days before travel must be nonnegative.")
    rows = read_csv("confirmation_history.csv")
    weighted_success = 0.0
    total_weight = 0.0
    for row in rows:
        if row["class"].upper() != travel_class.upper():
            continue
        distance = abs(int(row["wl_position"]) - wl_position) / 10
        distance += abs(int(row["days_before"]) - days_before) / 14
        weight = math.exp(-distance)
        total_weight += weight
        weighted_success += weight * int(row["confirmed"])
    probability = (1 + weighted_success) / (2 + total_weight)
    estimate = "CONFIRMED" if probability >= 0.7 else "RAC" if probability >= 0.4 else "WL"
    return {
        "confirmation_probability": round(probability, 3),
        "estimated_final_status": estimate,
        "confidence": "limited" if total_weight < 5 else "moderate",
        "nearby_example_weight": round(total_weight, 2),
        "explanation": "Similar WL positions and booking lead times in synthetic history; not a guarantee.",
        "model_version": "weighted-neighbors-demo-v1",
    }


def evaluate_confirmation_model() -> dict:
    """Evaluate synthetic confirmation model using Brier score and bucketed calibration."""
    rows = read_csv("confirmation_history.csv")
    if not rows:
        return {"samples": 0, "brier_score": None, "calibration_by_wl_bucket": {}}
    brier_sum = 0.0
    buckets = {"1-5": {"pred_sum": 0.0, "actual_sum": 0, "n": 0},
               "6-15": {"pred_sum": 0.0, "actual_sum": 0, "n": 0},
               "16+": {"pred_sum": 0.0, "actual_sum": 0, "n": 0}}
    for row in rows:
        try:
            wl = int(row["wl_position"])
            days = int(row["days_before"])
            actual = int(row["confirmed"])
            klass = row["class"]
            pred = confirmation_prediction(wl, days, klass)["confirmation_probability"]
            brier_sum += (pred - actual) ** 2
            b_key = "1-5" if wl <= 5 else "6-15" if wl <= 15 else "16+"
            buckets[b_key]["pred_sum"] += pred
            buckets[b_key]["actual_sum"] += actual
            buckets[b_key]["n"] += 1
        except Exception:
            continue
    total_n = len(rows)
    brier = round(brier_sum / total_n, 4) if total_n else None
    calibration = {}
    for key, data in buckets.items():
        if data["n"] > 0:
            calibration[key] = {
                "sample_count": data["n"],
                "avg_predicted_probability": round(data["pred_sum"] / data["n"], 3),
                "empirical_confirmation_rate": round(data["actual_sum"] / data["n"], 3),
            }
    return {
        "samples": total_n,
        "brier_score": brier,
        "calibration_by_wl_bucket": calibration,
        "synthetic_notice": "Evaluated on synthetic confirmation history; real IRCTC chart outcomes not connected.",
    }


def fare_prediction(train: dict, days_before: int) -> dict:
    if days_before < 0:
        raise ValueError("Days before departure cannot be negative.")
    demand = train["demand_index"]
    change = 0.04 + demand * 0.12 + (0.04 if days_before < 7 else 0)
    predicted = round(train["fare"] * (1 + change))
    trajectory = {
        "30_days_prior": round(train["fare"] * (1 + demand * 0.05)),
        "15_days_prior": round(train["fare"] * (1 + demand * 0.10)),
        "7_days_prior": round(train["fare"] * (1 + demand * 0.14)),
        "1_day_prior": round(train["fare"] * (1 + demand * 0.20 + 0.06)),
    }
    return {
        "current_fare": train["fare"],
        "illustrative_later_fare": predicted,
        "demand_level": "high" if demand >= 0.75 else "moderate" if demand >= 0.4 else "low",
        "booking_window": "Book soon if the itinerary is suitable" if demand >= 0.65 else "Compare again before booking",
        "illustrative_fare_trajectory": trajectory,
        "explanation": "Synthetic demand-based scenario; this is not an actual quoted fare.",
        "model_version": "fare-scenario-demo-v1",
    }


def station_congestion(station: str, hour: int) -> dict:
    trains = read_json("trains.json")
    nearby = sum(
        1 for train in trains
        if train["origin"].casefold() == station.casefold()
        and abs(int(train["departure"].split(":")[0]) - hour) <= 1
    )
    level = "high" if nearby >= 4 else "medium" if nearby >= 2 else "low"
    return {"station": station, "level": level, "scheduled_departures_near_hour": nearby,
            "explanation": "Illustrative count of sample departures, not live station crowding."}


def plan_journey(text: str, scenario: dict | None = None, today: date | None = None) -> dict:
    request = parse_request(text, today)
    journey_date = date.fromisoformat(request["date"])
    trains = read_json("trains.json")
    route_trains = [
        train for train in trains
        if train.get("origin", "").casefold() == request["origin"].casefold()
        and train.get("destination", "").casefold() == request["destination"].casefold()
        and isinstance(train.get("arrival_day_offset"), int)
    ]
    deadline_offset = min((train["arrival_day_offset"] for train in route_trains), default=1)
    arrival_deadline = (
        datetime.combine(journey_date + timedelta(days=deadline_offset), parse_clock(request["arrive_before"]))
        if request["arrive_before"] else None
    )
    scenario = scenario or {}
    overrides = scenario.get("delay_overrides", {})
    if not isinstance(overrides, dict):
        raise ValueError("delay_overrides must be an object.")
    for value in overrides.values():
        if not isinstance(value, int) or not 0 <= value <= 600:
            raise ValueError("Delay overrides must be whole minutes between 0 and 600.")

    decisions, approved, alerts = [], [], []
    for train in trains:
        issues = validate_train(train)
        if issues:
            decisions.append({"train": train.get("name", "unknown"), "status": "blocked",
                              "reasons": issues, "supervisor": "data-quality block"})
            continue
        if (train["origin"].casefold(), train["destination"].casefold()) != (
            request["origin"].casefold(), request["destination"].casefold()
        ):
            continue
        delay = delay_prediction(train["id"])
        assumed_delay = overrides.get(train["id"], delay["minutes"] if delay["minutes"] is not None else 0)
        departure = datetime.combine(journey_date, parse_clock(train["departure"]))
        scheduled = datetime.combine(
            journey_date + timedelta(days=train["arrival_day_offset"]), parse_clock(train["arrival"])
        )
        expected = scheduled + timedelta(minutes=assumed_delay)
        journey_minutes = round((scheduled - departure).total_seconds() / 60)
        reasons = []
        if request["budget"] is not None and train["fare"] > request["budget"]:
            reasons.append("over budget")
        if request["class"] and train["class"].upper() != request["class"]:
            reasons.append("class mismatch")
        if arrival_deadline and expected >= arrival_deadline:
            reasons.append("expected arrival misses deadline")
        if expected <= departure:
            reasons.append("arrival before departure")
        if request["maximum_duration_hours"] is not None and journey_minutes > request["maximum_duration_hours"] * 60:
            reasons.append("journey exceeds duration limit")
        if delay["examples"] < 5:
            alerts.append(f"{train['name']}: only {delay['examples']} delay examples")
        if delay["mae_minutes"] is not None and delay["mae_minutes"] > 20:
            alerts.append(f"{train['name']}: historical delay error {delay['mae_minutes']} minutes")
        confirmation = (
            {"confirmation_probability": 1.0, "estimated_final_status": "AVAILABLE",
             "confidence": "seat status is synthetic"}
            if train["seats"] > 0 else
            confirmation_prediction(train["wl_position"], (journey_date - (today or date.today())).days,
                                    train["class"])
        )
        record = {
            "train_id": train["id"], "train": train["name"], "class": train["class"],
            "fare": train["fare"], "seats": train["seats"], "wl_position": train["wl_position"],
            "departure": departure.isoformat(timespec="minutes"),
            "scheduled_arrival": scheduled.isoformat(timespec="minutes"),
            "expected_arrival": expected.isoformat(timespec="minutes"),
            "assumed_delay_minutes": assumed_delay,
            "journey_duration_minutes": journey_minutes,
            "delay_source": "what-if override" if train["id"] in overrides else delay["method"],
            "delay_evidence": delay,
            "confirmation": confirmation,
            "fare_outlook": fare_prediction(train, max(0, (journey_date - (today or date.today())).days)),
        }
        if reasons:
            decisions.append({"train": train["name"], "train_id": train["id"],
                              "status": "rejected", "reasons": reasons})
        else:
            # The supervisor repeats critical constraints independently of the ranking step.
            supervisor_issues = []
            if train["fare"] < 0 or (request["budget"] is not None and train["fare"] > request["budget"]):
                supervisor_issues.append("fare violates policy")
            if arrival_deadline and expected >= arrival_deadline:
                supervisor_issues.append("arrival violates deadline")
            if supervisor_issues:
                decisions.append({"train": train["name"], "train_id": train["id"],
                                  "status": "blocked", "reasons": supervisor_issues})
            else:
                decisions.append({"train": train["name"], "train_id": train["id"],
                                  "status": "approved", "reasons": ["constraints verified"]})
                approved.append(record)

    if request["preference"] == "fastest":
        approved.sort(key=lambda item: (item["journey_duration_minutes"], item["fare"]))
    elif request["preference"] == "balanced":
        min_f = min((item["fare"] for item in approved), default=1)
        max_f = max((item["fare"] for item in approved), default=1)
        min_d = min((item["journey_duration_minutes"] for item in approved), default=1)
        max_d = max((item["journey_duration_minutes"] for item in approved), default=1)
        for item in approved:
            fn = (item["fare"] - min_f) / (max_f - min_f) if max_f > min_f else 0.0
            dn = (item["journey_duration_minutes"] - min_d) / (max_d - min_d) if max_d > min_d else 0.0
            deln = min(1.0, max(0.0, item["assumed_delay_minutes"] / 60.0))
            item["balanced_score"] = round(0.45 * fn + 0.35 * dn + 0.20 * deln, 3)
        approved.sort(key=lambda item: (item["balanced_score"], item["journey_duration_minutes"]))
    else:
        approved.sort(key=lambda item: (item["fare"], item["journey_duration_minutes"]))
    selected = approved[0] if approved else None
    cheaper_rejected = [
        item for item in decisions if item["status"] == "rejected"
        and any("deadline" in reason for reason in item["reasons"])
        and next((t["fare"] for t in trains if t["id"] == item["train_id"]), math.inf)
        < (selected["fare"] if selected else math.inf)
    ]
    reason = None
    if selected:
        reason = ("A cheaper train may miss your arrival deadline; this option meets it."
                  if cheaper_rejected else
                  "Shortest journey among suitable options." if request["preference"] == "fastest" else
                  "Optimal balance of fare, journey time, and historical punctuality." if request["preference"] == "balanced" else
                  "Lowest fare among suitable options.")
    passenger_alerts = []
    if selected and selected["assumed_delay_minutes"] >= 60:
        passenger_alerts.append("This sample train may arrive at least one hour late. Check live running status before travel.")
    if selected and selected["delay_source"] == "what-if override":
        passenger_alerts.append("Arrival time includes a delay you simulated, not a live railway update.")

    rescue_info = None
    if cheaper_rejected and selected:
        disrupted_names = [
            d["train"] for d in decisions
            if d["status"] in {"rejected", "blocked"} and any("deadline" in r for r in d["reasons"])
        ]
        rescue_info = {
            "disrupted_trains": disrupted_names,
            "rescue_train": selected["train"],
            "reason": f"Disrupted option(s) ({', '.join(disrupted_names)}) miss arrival deadline due to simulated/predicted delay. Agent selected {selected['train']} as rescue recommendation.",
            "strategy": "arrival_deadline_compliance",
        }

    orchestration_trail = [
        {"agent": "TravelPlannerAgent", "action": f"Parsed query: {request['origin']} -> {request['destination']} on {request['date']}", "status": "completed"},
        {"agent": "PredictionAgent", "action": f"Enriched {len(route_trains)} candidate trains with delay, confirmation and fare outlook", "status": "completed"},
        {"agent": "SupervisorAgent", "action": f"Verified constraints: {len(approved)} approved, {len(decisions) - len(approved)} blocked/rejected", "status": "completed"},
        {"agent": "RescueAgent", "action": rescue_info["reason"] if rescue_info else "No disruption rescue triggered; primary candidate meets constraints", "status": "active" if rescue_info else "standby"},
        {"agent": "GovernanceAgent", "action": f"Applied safety boundaries and generated {len(alerts)} governance alerts", "status": "completed"},
    ]

    return {
        "request": request, "selected": selected, "alternatives": approved[1:],
        "decisions": decisions, "recommendation_reason": reason,
        "station_congestion": station_congestion(
            request["origin"],
            int(selected["departure"].split("T")[1].split(":")[0]) if selected else 18,
        ),
        "governance_alerts": sorted(set(alerts)),
        "passenger_alerts": passenger_alerts,
        "disruption_rescue": rescue_info,
        "orchestration_trail": orchestration_trail,
        "agent_architecture": "Multi-agent: PlannerAgent -> PredictionAgent -> SupervisorAgent -> RescueAgent -> GovernanceAgent",
        "booking": {"status": "approval required", "action": "preview only; no ticket is purchased"},
        "data_notice": "All railway records, labels, PNRs, and delays are synthetic demonstration data.",
    }


def pnr_status(pnr: str) -> dict:
    if not re.fullmatch(r"\d{10}", pnr):
        raise ValueError("Enter a 10-digit PNR.")
    record = read_json("pnr.json").get(pnr)
    if not record:
        return {"status": "not in demo data", "message": "Use an official railway service for real PNR status."}
    return {**record, "data_notice": "Synthetic demonstration PNR; not a live status."}


def refund_status(reference: str) -> dict:
    if not re.fullmatch(r"DEMO-R\d{4}", reference.upper()):
        raise ValueError("Enter a sample refund reference like DEMO-R1001.")
    record = read_json("refunds.json").get(reference.upper())
    if not record:
        return {"status": "not in demo data", "message": "Use the official booking service for a real refund."}
    return {**record, "data_notice": "Synthetic refund status; no real payment is connected."}


def support_answer(question: str, language: str = "en") -> dict:
    lower = question.casefold()
    pnr = re.search(r"\b\d{10}\b", question)
    if pnr:
        result = pnr_status(pnr.group())
        return {"answer": f"Demo PNR status: {result.get('status')}. {result.get('message', '')}".strip(),
                "source": "synthetic PNR dataset", "grounded": True}
    policies = read_json("policies.json")
    key = None
    if any(w in lower for w in ("refund", "रिफंड")):
        key = "refund"
    elif any(w in lower for w in ("cancel", "रद्द")):
        key = "cancellation"
    elif any(w in lower for w in ("tatkal", "तत्काल")):
        key = "tatkal"
    elif any(w in lower for w in ("rac", "आरएसी")):
        key = "rac"
    elif any(w in lower for w in ("luggage", "सामान", "baggage")):
        key = "luggage"
    elif any(w in lower for w in ("senior", "वरिष्ठ", "concession", "रियायत")):
        key = "senior_citizen"

    if key and key in policies:
        item = policies[key]
        answer = item["hi"] if language.lower().startswith("hi") else item["en"]
        return {"answer": answer, "source": item["source"], "grounded": True,
                "policy_topic": key,
                "notice": "Demo policy summary. Verify current rules with the official operator."}
    return {"answer": "I cannot verify that answer from the connected demo sources. Please use an official railway service.",
            "source": None, "grounded": False, "governance_alert": "unsupported question; abstained"}


def fraud_assessment(events: dict) -> dict:
    """Illustrative risk triage; never makes an accusation or blocks an account."""
    attempts = int(events.get("bookings_last_10_minutes", 0))
    failed = int(events.get("failed_logins_last_hour", 0))
    mismatch = bool(events.get("payment_mismatch", False))
    query_velocity = int(events.get("queries_last_minute", 0))
    booking_speed = float(events.get("booking_speed_seconds", 30))
    if attempts < 0 or failed < 0 or query_velocity < 0 or booking_speed < 0:
        raise ValueError("Counts cannot be negative.")
    reasons = []
    score = min(45, attempts * 5) + min(25, failed * 5) + (30 if mismatch else 0)
    if attempts >= 5:
        reasons.append("high booking frequency")
    if failed >= 3:
        reasons.append("repeated failed logins")
    if mismatch:
        reasons.append("payment information mismatch")
    if query_velocity >= 30:
        score += 20
        reasons.append("abnormal search query velocity (potential scraper bot)")
    if booking_speed < 3 and attempts >= 1:
        score += 25
        reasons.append("sub-3-second automated form completion (potential script/bot)")
    total_score = min(100, score)
    level = "high" if total_score >= 70 else "medium" if total_score >= 35 else "low"
    action = "human review" if total_score >= 70 else "challenge_verification" if total_score >= 35 else "monitor"
    return {
        "risk_score": total_score,
        "level": level,
        "signals": reasons,
        "action": action,
        "explanation": "Transparent demo rule score; not a finding of fraud.",
        "model_version": "fraud-rules-demo-v2",
    }
