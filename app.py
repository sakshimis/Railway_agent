"""Local HTTP interface for the offline railway case-study demo."""
from __future__ import annotations

import argparse
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from auth import ACCOUNTS, LoginRateLimited, initialize_accounts, login, logout, session_role

from governance import (
    audit, governance_report, promote_candidate, recent_audit, retraining_candidate,
    rollback_delay,
)
from railway import (
    DATA, ROOT, confirmation_prediction, fare_prediction, fraud_assessment,
    plan_journey, parse_request, pnr_status, read_json, refund_status, support_answer,
)
from historical import (search as historical_search, stations as historical_stations,
                        report as kaggle_report, train_on_route)
from live_railway import LiveServiceUnavailable, configured as live_configured, search_live

WEB = ROOT / "web"
ITINERARIES = ROOT / "runtime" / "itineraries.jsonl"
ITINERARY_LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def role(self) -> str | None:
        return session_role(self.headers.get("Cookie", ""))

    def require_role(self, admin: bool = False) -> bool:
        role = self.role()
        if not role:
            self.send_json(401, {"error": "Please log in."})
            return False
        if admin and role != "admin":
            self.send_json(403, {"error": "Administrator access required."})
            return False
        return True

    def send_json(self, status: int, value: dict | list) -> None:
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/stations":
            if not self.require_role(): return
            query = parse_qs(urlparse(self.path).query).get("q", [""])[0]
            return self.send_json(200, historical_stations(query))
        if path == "/api/session":
            return self.send_json(200, {"role": self.role(), "configured": ACCOUNTS.exists()})
        if path == "/api/live-status":
            if not self.require_role(): return
            return self.send_json(200, {"connected": live_configured()})
        if path == "/api/trains":
            if not self.require_role(): return
            trains = read_json("trains.json")
            return self.send_json(200, [{"id": t["id"], "name": t["name"], "fare": t["fare"]} for t in trains])
        if path == "/api/governance":
            if not self.require_role(admin=True): return
            return self.send_json(200, governance_report())
        if path == "/api/audit":
            if not self.require_role(admin=True): return
            return self.send_json(200, recent_audit(30))
        static = {"/": ("index.html", "text/html"),
                  "/app.js": ("app.js", "text/javascript"),
                  "/styles.css": ("styles.css", "text/css")}
        if path not in static:
            return self.send_json(404, {"error": "Not found"})
        filename, mime = static[path]
        raw = (WEB / filename).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        origin = self.headers.get("Origin")
        if origin and origin != f"http://127.0.0.1:{self.server.server_port}" and origin != f"http://localhost:{self.server.server_port}":
            return self.send_json(403, {"error": "Invalid request origin."})
        admin_paths = {"/api/plan", "/api/confirmation", "/api/fare", "/api/fraud"}
        if path != "/api/login" and not self.require_role(admin=path.startswith("/api/governance") or path in admin_paths):
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 65536:
            return self.send_json(413, {"error": "Request too large"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("Request body must be a JSON object.")
            started = time.perf_counter()
            if path == "/api/login":
                token = login(str(body.get("username", "")), str(body.get("password", "")),
                              self.client_address[0] if getattr(self, "client_address", None) else "local")
                if not token:
                    return self.send_json(401, {"error": "Invalid login. Run python app.py --init-users if accounts are not configured."})
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Set-Cookie", f"railway_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800")
                self.end_headers()
                self.wfile.write(json.dumps({"role": body["username"]}).encode())
                return
            elif path == "/api/logout":
                logout(self.headers.get("Cookie", ""))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Set-Cookie", "railway_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
                self.end_headers()
                self.wfile.write(b'{"status":"logged out"}')
                return
            elif path == "/api/plan":
                result = plan_journey(str(body.get("query", "")), body.get("scenario"))
                audit("journey_planned", {
                    "request": result["request"],
                    "selected_train": result["selected"]["train_id"] if result["selected"] else None,
                    "decisions": result["decisions"],
                }, round((time.perf_counter() - started) * 1000))
                if self.role() != "admin":
                    result = passenger_plan(result)
            elif path == "/api/historical-search":
                query = str(body.get("query", "")).strip()
                if query:
                    parsed = parse_request(query)
                    mapped_class = {"SLEEPER": "SL", "3AC": "3A", "2AC": "2A", "1AC": "1A", "CHAIR CAR": "CC"}
                    origin, destination = parsed["origin"], parsed["destination"]
                    klass = str(body.get("class") or mapped_class.get(parsed["class"], parsed["class"] or ""))
                    budget = body.get("max_fare") or parsed["budget"]
                    max_duration_hours = body.get("max_duration_hours") or parsed["maximum_duration_hours"]
                    sorting = str(body.get("sort") or ("duration" if parsed["preference"] == "fastest" else "fare"))
                else:
                    origin, destination = str(body.get("origin", "")), str(body.get("destination", ""))
                    klass = str(body.get("class", ""))
                    budget = body.get("max_fare")
                    max_duration_hours = body.get("max_duration_hours")
                    sorting = str(body.get("sort", "fare"))
                duration_limit = (int(max_duration_hours) * 60
                                  if max_duration_hours not in (None, "") else None)
                result = historical_search(origin, destination, klass,
                                           int(budget) if budget not in (None, "") else None,
                                           sorting, duration_limit)
                audit("historical_route_searched", {"origin_code": result["origin_code"],
                                                     "destination_code": result["destination_code"],
                                                     "matching_trains": result["matching_trains"]},
                      round((time.perf_counter() - started) * 1000))
            elif path == "/api/live-search":
                result = search_live(str(body.get("origin", "")),
                                     str(body.get("destination", "")),
                                     str(body.get("travel_date", "")),
                                     str(body.get("class", "")))
                audit("live_route_searched", {"origin_code": result["origin"],
                                               "destination_code": result["destination"],
                                               "matching_trains": len(result["trains"])},
                      round((time.perf_counter() - started) * 1000))
            elif path == "/api/confirmation":
                result = confirmation_prediction(int(body["wl_position"]),
                                                 int(body["days_before"]),
                                                 str(body.get("class", "SLEEPER")))
                audit("confirmation_estimated", {"class": body.get("class", "SLEEPER")},
                      round((time.perf_counter() - started) * 1000))
            elif path == "/api/fare":
                train = next((item for item in read_json("trains.json")
                              if item["id"] == body.get("train_id")), None)
                if not train:
                    raise ValueError("Unknown demo train ID.")
                result = fare_prediction(train, int(body.get("days_before", 7)))
                audit("fare_scenario_estimated", {"train_id": train["id"]},
                      round((time.perf_counter() - started) * 1000))
            elif path == "/api/pnr":
                result = pnr_status(str(body.get("pnr", "")))
                audit("pnr_demo_lookup", {"status": result["status"]},
                      round((time.perf_counter() - started) * 1000))
            elif path == "/api/refund":
                result = refund_status(str(body.get("reference", "")))
                audit("refund_demo_lookup", {"status": result["status"]},
                      round((time.perf_counter() - started) * 1000))
            elif path == "/api/support":
                result = support_answer(str(body.get("question", "")),
                                        str(body.get("language", "en")))
                audit("support_answered" if result["grounded"] else "support_abstained",
                      {"grounded": result["grounded"]},
                      round((time.perf_counter() - started) * 1000))
                if self.role() != "admin":
                    result = {key: result[key] for key in ("answer", "notice") if key in result}
            elif path == "/api/fraud":
                result = fraud_assessment(body)
                audit("fraud_risk_assessed", {"risk_score": result["risk_score"],
                                               "level": result["level"]},
                      round((time.perf_counter() - started) * 1000))
            elif path == "/api/feedback":
                train_id = str(body.get("train_id", ""))
                if train_id not in {item["id"] for item in read_json("trains.json")} or type(body.get("helpful")) is not bool:
                    raise ValueError("Choose a listed train and a helpful/not helpful rating.")
                audit("recommendation_feedback", {"train_id": train_id, "helpful": body["helpful"]})
                result = {"status": "feedback recorded", "notice": "Synthetic demo feedback; no personal details stored."}
            elif path == "/api/historical-feedback":
                train_no = str(body.get("train_no", ""))
                origin_code = str(body.get("origin_code", ""))
                destination_code = str(body.get("destination_code", ""))
                if type(body.get("helpful")) is not bool or not train_on_route(train_no, origin_code, destination_code):
                    raise ValueError("Choose a train shown for this historical route and a helpful/not helpful rating.")
                audit("historical_recommendation_feedback", {
                    "train_no": train_no, "origin_code": origin_code.upper(),
                    "destination_code": destination_code.upper(), "helpful": body["helpful"]})
                result = {"status": "feedback recorded", "notice": "Anonymous project feedback; no passenger details stored."}
            elif path == "/api/itinerary":
                if body.get("approved") is not True:
                    raise PermissionError("Review and approve the sample itinerary first.")
                plan = plan_journey(str(body.get("query", "")), body.get("scenario"))
                choice = next((item for item in [plan["selected"], *plan["alternatives"]]
                               if item and item["train_id"] == body.get("train_id")), None)
                if not choice:
                    raise ValueError("The selected train is no longer a suitable demo option.")
                reference = "DEMO-" + secrets.token_hex(4).upper()
                saved = {"reference": reference, "train": choice["train"],
                         "departure": choice["departure"], "fare": choice["fare"],
                         "status": "saved itinerary only; no ticket or payment"}
                ITINERARIES.parent.mkdir(parents=True, exist_ok=True)
                with ITINERARY_LOCK:
                    with ITINERARIES.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(saved) + "\n")
                audit("itinerary_saved", {"train_id": choice["train_id"], "reference": reference})
                result = saved
            elif path == "/api/governance/candidate":
                result = retraining_candidate()
            elif path == "/api/governance/promote":
                result = promote_candidate(self.role(), body.get("approved") is True)
            elif path == "/api/governance/rollback":
                result = rollback_delay(self.role(), body.get("approved") is True)
            else:
                return self.send_json(404, {"error": "Not found"})
            return self.send_json(200, result)
        except LoginRateLimited as exc:
            self.send_json(429, {"error": str(exc)})
        except LiveServiceUnavailable as exc:
            self.send_json(503, {"error": str(exc)})
        except PermissionError as exc:
            self.send_json(403, {"error": str(exc)})
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:
            self.log_error("Unhandled error: %s", exc)
            self.send_json(500, {"error": "Internal demo error; check the server terminal."})


def passenger_plan(result: dict) -> dict:
    """Allowlist passenger fields; internal decisions never cross the API boundary."""
    def option(record: dict) -> dict:
        option = {key: record[key] for key in ("train_id", "train", "class", "fare", "departure", "scheduled_arrival", "expected_arrival", "journey_duration_minutes")}
        option["seat_status"] = record["confirmation"]["estimated_final_status"]
        return option
    return {
        "selected": option(result["selected"]) if result["selected"] else None,
        "alternatives": [option(item) for item in result["alternatives"]],
        "recommendation_reason": result["recommendation_reason"],
        "passenger_alerts": result["passenger_alerts"],
        "booking": result["booking"],
        "data_notice": result["data_notice"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline railway AI case-study demo")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--init-users", action="store_true", help="Create user and admin passwords")
    args = parser.parse_args()
    if args.init_users:
        initialize_accounts()
        return
    if not ACCOUNTS.exists():
        print("First run: python app.py --init-users", flush=True)
        return
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Railway AI demo: http://127.0.0.1:{args.port}", flush=True)
    print("Kaggle historical data plus separate synthetic demo. No live railway data. Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
