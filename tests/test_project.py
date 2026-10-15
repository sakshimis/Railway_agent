import unittest
import io
import json
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from railway import (
    confirmation_prediction, evaluate_confirmation_model, fare_prediction,
    fraud_assessment, parse_request, plan_journey, pnr_status, refund_status,
    support_answer,
)
from governance import governance_report, retraining_candidate
from app import Handler
from historical import (search as historical_search, report as kaggle_report,
                        resolve_station, station_details, stations, train_on_route)
import auth
import live_railway


TODAY = date(2026, 10, 14)
QUERY = "I want to travel from Pune to Delhi tomorrow under 1500 before 10:00 AM"


class RailwayDemoTests(unittest.TestCase):
    def test_live_feed_requires_authorized_configuration(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(live_railway.configured())
            with self.assertRaises(live_railway.LiveServiceUnavailable):
                live_railway.search_live("PUNE", "NDLS", "2026-10-20", "SL")

    def test_live_feed_adapter_keeps_token_on_server(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): return None
            def read(self, _limit):
                return json.dumps({"as_of": "2026-10-15T10:00:00+05:30", "trains": [{
                    "train_no": "12345", "name": "Example", "class": "SL",
                    "fare_rupees": 750, "availability": "AVAILABLE",
                    "departure": "18:30", "arrival": "09:40"
                }]}).encode()
        settings = {"RAILWAY_LIVE_API_URL": "https://provider.example/api/trains",
                    "RAILWAY_LIVE_API_TOKEN": "test-secret"}
        with patch.dict("os.environ", settings), patch("live_railway.urlopen", return_value=Response()) as send:
            result = live_railway.search_live("pune", "ndls", "2026-10-20", "SL")
        self.assertEqual(result["trains"][0]["fare_rupees"], 750)
        self.assertEqual(result["trains"][0]["availability"], "AVAILABLE")
        request = send.call_args.args[0]
        self.assertIn("origin=PUNE", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer test-secret")
        self.assertNotIn("test-secret", json.dumps(result))

    def test_request_parsing_and_date(self):
        parsed = parse_request(QUERY, TODAY)
        self.assertEqual(parsed["origin"], "Pune")
        self.assertEqual(parsed["destination"], "Delhi")
        self.assertEqual(parsed["date"], "2026-10-15")
        self.assertEqual(parsed["arrive_before"], "10:00")
        self.assertEqual(parsed["budget"], 1500)

    def test_delay_changes_rescue_recommendation(self):
        default = plan_journey(QUERY, today=TODAY)
        faster = plan_journey(QUERY, {"delay_overrides": {"DEMO-A": 30}}, today=TODAY)
        self.assertEqual(default["selected"]["train_id"], "DEMO-D")
        self.assertEqual(faster["selected"]["train_id"], "DEMO-A")
        self.assertTrue(any(
            "deadline" in " ".join(item["reasons"])
            for item in default["decisions"] if item["train_id"] == "DEMO-A"
        ))

    def test_budget_and_same_day_deadline(self):
        result = plan_journey("from Mumbai to Pune on 2026-10-20 under 600 before 10:00 AM", today=TODAY)
        self.assertEqual(result["selected"]["train_id"], "DEMO-MP")
        tight = plan_journey("from Mumbai to Pune on 2026-10-20 under 500", today=TODAY)
        self.assertIsNone(tight["selected"])

    def test_duration_preference_and_refund_demo(self):
        fast = plan_journey("from Pune to Delhi tomorrow fastest", today=TODAY)
        self.assertEqual(fast["selected"]["train_id"], "DEMO-B")
        short = plan_journey("from Pune to Delhi tomorrow within 15 hours under 1500", today=TODAY)
        self.assertEqual(short["selected"]["train_id"], "DEMO-D")
        self.assertEqual(refund_status("DEMO-R1001")["status"], "processing")

    def test_confirmation_and_fare_evidence(self):
        result = confirmation_prediction(4, 7, "SLEEPER")
        self.assertTrue(0 <= result["confirmation_probability"] <= 1)
        self.assertIn(result["estimated_final_status"], {"CONFIRMED", "RAC", "WL"})
        self.assertIn("synthetic", result["explanation"])

    def test_support_abstains_and_pnr_is_demo(self):
        self.assertFalse(support_answer("What is the moon made of?")["grounded"])
        self.assertEqual(pnr_status("1234567890")["status"], "RAC")
        with self.assertRaises(ValueError):
            pnr_status("123")

    def test_fraud_score_is_review_only(self):
        high = fraud_assessment({
            "bookings_last_10_minutes": 9,
            "failed_logins_last_hour": 4,
            "payment_mismatch": True,
        })
        self.assertEqual(high["level"], "high")
        self.assertEqual(high["action"], "human review")

    def test_governance_detects_sparse_models_and_evaluates_candidate(self):
        report = governance_report()
        self.assertTrue(any(alert["area"] == "model coverage" for alert in report["alerts"]))
        slow_events = [{"event": "historical_route_searched", "payload": {}, "latency_ms": 1500}
                       for _ in range(20)]
        with patch("governance.recent_audit", return_value=slow_events):
            slow_report = governance_report()
        self.assertEqual(slow_report["recent_p95_latency_ms"], 1500)
        self.assertTrue(any(alert["area"] == "request latency" for alert in slow_report["alerts"]))
        with patch("governance._save_registry"), patch("governance.audit"):
            candidate = retraining_candidate()
            self.assertIn(candidate["status"], {"awaiting admin approval", "rejected by evaluation"})
            self.assertIn("candidate_holdout_mae", candidate)

    def test_http_handler_plan_and_governance_without_network(self):
        def call(path, body=None):
            handler = object.__new__(Handler)
            handler.path = path
            handler.headers = {"Cookie": ""}
            handler.wfile = io.BytesIO()
            status = []
            handler.send_response = lambda code: status.append(code)
            handler.send_header = lambda *_: None
            handler.end_headers = lambda: None
            if body is None:
                handler.do_GET()
            else:
                raw = json.dumps(body).encode("utf-8")
                handler.headers = {"Content-Length": str(len(raw))}
                handler.rfile = io.BytesIO(raw)
                handler.do_POST()
            return status[0], json.loads(handler.wfile.getvalue())

        with patch("app.audit"), patch("app.session_role", return_value="user"):
            with patch("app.live_configured", return_value=False):
                status, live_status = call("/api/live-status")
                self.assertEqual((status, live_status["connected"]), (200, False))
            with patch.dict("os.environ", {}, clear=True):
                status, live_result = call("/api/live-search", {
                    "origin": "PUNE", "destination": "NDLS", "travel_date": "2026-10-20"})
                self.assertEqual(status, 503)
                self.assertIn("not connected", live_result["error"])
            status, result = call("/api/plan", {"query": QUERY})
            self.assertEqual(status, 403)
            status, result = call("/api/historical-search", {"origin": "PUNE", "destination": "NDLS"})
            self.assertEqual(status, 200)
            self.assertIn("historical", result["notice"].lower())
            self.assertNotIn("decisions", result)
            status, natural = call("/api/historical-search", {"query": "from Pune to Delhi under 1500 sleeper"})
            self.assertEqual(status, 200)
            self.assertTrue(all(fare["class"] == "SL" and fare["fare"] <= 1500
                                for option in natural["options"] for fare in option["fares"]))
            status, sorted_natural = call("/api/historical-search", {
                "query": "from Pune to RTM", "sort": "departure"})
            self.assertEqual(status, 200)
            self.assertEqual(sorted_natural["sort_used"], "departure")
            self.assertEqual(sorted_natural["schedule_only"][0]["train_no"], "22193")
            status, duration_limited = call("/api/historical-search", {
                "query": "from Pune to Delhi", "max_duration_hours": "27"})
            self.assertEqual(status, 200)
            self.assertEqual(duration_limited["matching_trains"], 0)
            self.assertEqual(duration_limited["schedule_only_count"], 1)
            self.assertEqual(duration_limited["schedule_only"][0]["train_no"], "22685")
            status, report = call("/api/governance")
            self.assertEqual(status, 403)
            status, feedback = call("/api/historical-feedback", {
                "train_no": "11077", "origin_code": "PUNE",
                "destination_code": "NDLS", "helpful": True})
            self.assertEqual((status, feedback["status"]), (200, "feedback recorded"))
            status, feedback = call("/api/historical-feedback", {
                "train_no": "11077", "origin_code": "NDLS",
                "destination_code": "PUNE", "helpful": True})
            self.assertEqual(status, 400)
            status, report = call("/api/audit")
            self.assertEqual(status, 403)
            status, report = call("/api/fraud", {})
            self.assertEqual(status, 403)
            status, refund = call("/api/refund", {"reference": "DEMO-R1001"})
            self.assertEqual((status, refund["status"]), (200, "processing"))
            status, support = call("/api/support", {"question": "How does a refund work?"})
            self.assertEqual(status, 200)
            self.assertNotIn("grounded", support)
            self.assertNotIn("source", support)
            status, result = call("/api/itinerary", {"query": QUERY, "train_id": "DEMO-D", "approved": False})
            self.assertEqual(status, 403)
            with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
                with patch("app.ITINERARIES", Path(folder) / "itineraries.jsonl"):
                    status, result = call("/api/itinerary", {"query": QUERY, "train_id": "DEMO-D", "approved": True})
                    self.assertEqual(status, 200)
                    self.assertIn("no ticket or payment", result["status"])
        with patch("app.session_role", return_value="admin"):
            status, report = call("/api/governance")
            self.assertEqual(status, 200)
            self.assertIn("alerts", report)
            self.assertIn("kaggle_evidence", report)

    def test_historical_data_is_labeled_and_seats_unknown(self):
        report = kaggle_report()
        self.assertGreater(report["fare_catalog"]["unique_fare_records"], 100000)
        result = historical_search("Pune", "New Delhi")
        self.assertGreater(result["matching_trains"], 0)
        self.assertEqual(result["matching_trains"], 1)
        self.assertEqual(result["matching_class_fares"], 3)
        self.assertIn("unknown", result["notice"].lower())
        self.assertNotIn("seats", result["options"][0])
        timetable_only = historical_search("PUNE", "RTM")
        self.assertEqual(timetable_only["matching_trains"], 0)
        self.assertEqual(timetable_only["schedule_only_count"], 9)
        self.assertNotIn("fare", timetable_only["schedule_only"][0])
        self.assertTrue(all(option["fare_estimates"] for option in timetable_only["schedule_only"]))
        top_by_sort = {sort: historical_search("PUNE", "RTM", sort=sort)["schedule_only"][0]["train_no"]
                       for sort in ("fare", "duration", "departure")}
        self.assertEqual(len(set(top_by_sort.values())), 3)
        sleeper = historical_search("PUNE", "RTM", travel_class="SL")
        self.assertTrue(all([fare["class"] for fare in item["fare_estimates"]] == ["SL"]
                            for item in sleeper["schedule_only"]))
        self.assertEqual(resolve_station("AADR"), "AADR")
        self.assertTrue(any(item["code"] == "AADR" for item in stations("AADR")))
        self.assertTrue(train_on_route("22685", "PUNE", "NDLS"))
        self.assertFalse(train_on_route("22685", "NDLS", "PUNE"))

    def test_password_hash_and_session_expiry(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            account_file = Path(folder) / "accounts.json"
            salt = bytes.fromhex("01" * 16)
            account_file.write_text(json.dumps({"user": {
                "salt": salt.hex(), "hash": auth._digest("a long demo password", salt)}}))
            with patch.object(auth, "ACCOUNTS", account_file):
                self.assertIsNone(auth.login("user", "wrong"))
                token = auth.login("user", "a long demo password")
                self.assertEqual(auth.session_role(f"railway_session={token}"), "user")
                auth.logout(f"railway_session={token}")
                self.assertIsNone(auth.session_role(f"railway_session={token}"))

    def test_login_failed_attempt_limit(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            account_file = Path(folder) / "accounts.json"
            salt = bytes.fromhex("02" * 16)
            account_file.write_text(json.dumps({"user": {
                "salt": salt.hex(), "hash": auth._digest("a long demo password", salt)}}))
            with patch.object(auth, "ACCOUNTS", account_file), patch.object(auth, "FAILURES", {}):
                for _ in range(auth.MAX_LOGIN_FAILURES):
                    self.assertIsNone(auth.login("user", "wrong", "test-client"))
                with self.assertRaises(auth.LoginRateLimited):
                    auth.login("user", "a long demo password", "test-client")
                self.assertIsNotNone(auth.login("user", "a long demo password", "other-client"))

    def test_multi_agent_orchestration_and_rescue_trail(self):
        result = plan_journey(QUERY, today=TODAY)
        self.assertIn("orchestration_trail", result)
        self.assertEqual(len(result["orchestration_trail"]), 5)
        agents = [step["agent"] for step in result["orchestration_trail"]]
        self.assertEqual(agents, ["TravelPlannerAgent", "PredictionAgent", "SupervisorAgent", "RescueAgent", "GovernanceAgent"])
        self.assertIsNotNone(result["disruption_rescue"])
        self.assertEqual(result["disruption_rescue"]["rescue_train"], "Demo Pune Delhi D")
        self.assertIn("Demo Pune Delhi A", result["disruption_rescue"]["disrupted_trains"])

    def test_balanced_recommendation_and_station_details(self):
        balanced = historical_search("PUNE", "RTM", sort="balanced")
        self.assertEqual(balanced["sort_used"], "balanced")
        self.assertTrue(all("balanced_score" in item for item in balanced["schedule_only"]))
        details = station_details("PUNE")
        self.assertEqual(details["code"], "PUNE")
        self.assertGreater(details["timetable_stops_passing_through"], 50)
        self.assertEqual(resolve_station("hyderabad"), "HYB")
        self.assertEqual(resolve_station("patna"), "PNBE")
        self.assertEqual(resolve_station("ahmedabad"), "ADI")

    def test_confirmation_brier_score_and_calibration(self):
        eval_result = evaluate_confirmation_model()
        self.assertGreater(eval_result["samples"], 0)
        self.assertIsNotNone(eval_result["brier_score"])
        self.assertTrue(0 <= eval_result["brier_score"] <= 1)
        self.assertIn("1-5", eval_result["calibration_by_wl_bucket"])

    def test_expanded_support_policies_and_abstention_tracking(self):
        tatkal = support_answer("What are the Tatkal booking timings?")
        self.assertTrue(tatkal["grounded"])
        self.assertIn("10:00 AM", tatkal["answer"])
        tatkal_hi = support_answer("तत्काल टिकट नियम", language="hi")
        self.assertTrue(tatkal_hi["grounded"])
        rac = support_answer("Explain RAC berth rules")
        self.assertTrue(rac["grounded"])
        self.assertIn("shared", rac["answer"].lower())
        luggage = support_answer("What is the free luggage allowance for 3AC?")
        self.assertTrue(luggage["grounded"])
        self.assertIn("40", luggage["answer"])
        senior = support_answer("Is there a senior citizen concession?")
        self.assertTrue(senior["grounded"])
        unknown = support_answer("What is the temperature on Jupiter?")
        self.assertFalse(unknown["grounded"])
        self.assertIn("abstained", unknown["governance_alert"])

    def test_bot_velocity_and_fraud_triage(self):
        bot = fraud_assessment({
            "bookings_last_10_minutes": 6,
            "failed_logins_last_hour": 1,
            "payment_mismatch": False,
            "queries_last_minute": 45,
            "booking_speed_seconds": 1.2,
        })
        self.assertEqual(bot["level"], "high")
        self.assertTrue(any("scraper" in signal for signal in bot["signals"]))
        self.assertTrue(any("sub-3-second" in signal for signal in bot["signals"]))

    def test_live_pnr_and_seats_adapters(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(live_railway.LiveServiceUnavailable):
                live_railway.search_live_pnr("1234567890")
            with self.assertRaises(live_railway.LiveServiceUnavailable):
                live_railway.search_live_seats("12345", "2026-10-20", "SL")
        class MockPnrResponse:
            def __enter__(self): return self
            def __exit__(self, *_): return None
            def read(self, _limit):
                return json.dumps({
                    "pnr": "1234567890", "train_no": "12345", "train_name": "Test Express",
                    "status": "CONFIRMED", "chart_prepared": True, "as_of": "2026-10-15T12:00:00+05:30"
                }).encode()
        with patch.dict("os.environ", {"RAILWAY_LIVE_API_URL": "https://provider.example/live", "RAILWAY_LIVE_API_TOKEN": "secret"}), \
             patch("live_railway.urlopen", return_value=MockPnrResponse()):
            pnr_res = live_railway.search_live_pnr("1234567890")
            self.assertEqual(pnr_res["status"], "CONFIRMED")
            self.assertTrue(pnr_res["chart_prepared"])

    def test_security_headers_and_extended_endpoints(self):
        def call(path, body=None):
            handler = object.__new__(Handler)
            handler.path = path
            handler.headers = {"Cookie": ""}
            handler.wfile = io.BytesIO()
            headers_sent = {}
            status = []
            handler.send_response = lambda code: status.append(code)
            handler.send_header = lambda k, v: headers_sent.setdefault(k, v)
            handler.end_headers = lambda: None
            if body is None:
                handler.do_GET()
            else:
                raw = json.dumps(body).encode("utf-8")
                handler.headers = {"Content-Length": str(len(raw))}
                handler.rfile = io.BytesIO(raw)
                handler.do_POST()
            return status[0], json.loads(handler.wfile.getvalue()), headers_sent

        with patch("app.session_role", return_value="user"), patch("app.audit"):
            status, res, headers = call("/api/station-details?code=PUNE")
            self.assertEqual(status, 200)
            self.assertEqual(res["code"], "PUNE")
            self.assertEqual(headers.get("X-Frame-Options"), "DENY")
            self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
            self.assertIn("Content-Security-Policy", headers)
            with patch.dict("os.environ", {}, clear=True):
                status, res, _ = call("/api/live-pnr", {"pnr": "1234567890"})
                self.assertEqual(status, 503)
                status, res, _ = call("/api/live-seats", {"train_no": "12345", "travel_date": "2026-10-20", "class": "SL"})
                self.assertEqual(status, 503)
                status, res, _ = call("/api/provider-fare", {"origin": "NDLS", "destination": "KYN", "class": "3A"})
                self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
