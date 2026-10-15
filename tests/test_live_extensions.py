"""Offline tests for live_providers.py and outcomes.py (no network, no API key)."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import live_providers
import outcomes
from live_railway import LiveServiceUnavailable


class FakeResponse(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *args): self.close()


def fake_urlopen(payload):
    return lambda request, timeout=8: FakeResponse(json.dumps(payload).encode())


RAPID_ENV = {"RAPIDAPI_KEY": "test-key", "RAPIDAPI_HOST": "example.p.rapidapi.com",
             "RAILWAY_LIVE_API_URL": "", "RAILWAY_LIVE_API_TOKEN": "",
             "RAPIDAPI_PATH_PNR": "/getPNRStatus/{pnrNumber}",
             "RAPIDAPI_PATH_LIVE": "/liveTrainStatus",
             "RAPIDAPI_PATH_BETWEEN": "/trainBetweenStations",
             "RAPIDAPI_PATH_SEATS": "/checkSeatAvailability"}


def env(**extra):
    base = {k: v for k, v in RAPID_ENV.items() if v}
    return mock.patch.dict(os.environ, {**base, **extra}, clear=False)


class LiveProviderTests(unittest.TestCase):
    def setUp(self):
        live_providers._CACHE.clear()
        live_providers._last_call = 0.0
        for k in [k for k in RAPID_ENV if k.startswith("RAPIDAPI_PATH")]:
            os.environ.pop(k, None)

    def test_unconfigured_is_unavailable(self):
        with mock.patch.dict(os.environ, {k: "" for k in RAPID_ENV}):
            self.assertFalse(live_providers.configured())
            with self.assertRaises(LiveServiceUnavailable):
                live_providers.live_train_status("12951")

    def test_unconfigured_returns_unavailable_before_validation(self):
        with mock.patch.dict(os.environ, {k: "" for k in RAPID_ENV}):
            for call in (lambda: live_providers.search_live("", "", "bad"),
                         lambda: live_providers.search_live_pnr("x"),
                         lambda: live_providers.search_live_seats("", "bad", "")):
                with self.assertRaises(LiveServiceUnavailable):
                    call()

    def test_route_search_is_normalized_and_has_no_invented_fare(self):
        payload = {"status": True, "data": [
            {"train_number": "12951", "train_name": "Rajdhani", "from_std": "16:35", "to_sta": "08:32",
             "class_type": ["1A", "2A", "3A"]},
            {"train_number": "11077", "train_name": "Jhelum", "from_std": "17:20", "to_sta": "15:10",
             "class_type": ["SL", "3A"]}]}
        with env(), mock.patch.object(live_providers, "urlopen", fake_urlopen(payload)):
            result = live_providers.search_live("pune", "ndls", "2026-10-20", "SL")
        self.assertEqual([t["train_no"] for t in result["trains"]], ["11077"])
        self.assertIsNone(result["trains"][0]["fare_rupees"])
        self.assertIn("unofficial", result["source"])

    def test_live_status_rejects_absurd_delay(self):
        payload = {"data": {"current_station_code": "BPL", "delay": 99999}}
        with env(), mock.patch.object(live_providers, "urlopen", fake_urlopen(payload)):
            self.assertIsNone(live_providers.live_train_status("12951")["delay_minutes"])

    def test_provider_error_flag_becomes_unavailable(self):
        with env(), mock.patch.object(live_providers, "urlopen", fake_urlopen({"status": False, "message": "bad"})):
            with self.assertRaises(LiveServiceUnavailable):
                live_providers.search_live_pnr("1234567890")

    def test_pnr_only_does_not_claim_live_fares_or_seats(self):
        with mock.patch.dict(os.environ, {"RAPIDAPI_KEY": "test-key",
                                          "RAPIDAPI_HOST": "example.p.rapidapi.com",
                                          "RAPIDAPI_PATH_BETWEEN": "",
                                          "RAPIDAPI_PATH_SEATS": "",
                                          "RAILWAY_LIVE_API_URL": "",
                                          "RAILWAY_LIVE_API_TOKEN": ""}):
            self.assertTrue(live_providers.pnr_configured())
            self.assertFalse(live_providers.configured())
            with self.assertRaises(LiveServiceUnavailable):
                live_providers.search_live("PUNE", "NDLS", "2026-10-20")

    def test_failed_pnr_body_is_not_displayed_as_live_status(self):
        response = {"success": False, "message": "FLUSHED PNR / PNR NOT YET GENERATED"}
        with env(), mock.patch.object(live_providers, "urlopen", fake_urlopen(response)):
            with self.assertRaisesRegex(LiveServiceUnavailable, "FLUSHED PNR"):
                live_providers.search_live_pnr("1234567890")

    def test_successful_pnr_is_normalized_and_key_stays_server_side(self):
        payload = {"success": True, "data": {"pnrNumber": "8148735219",
                   "trainNumber": "12951", "trainName": "Example Express",
                   "passengerStatus": [{"currentStatus": "CNF", "bookingStatus": "WL/2"}]}}
        seen = []
        def capture(request, timeout=8):
            seen.append(request)
            return FakeResponse(json.dumps(payload).encode())
        with env(), mock.patch.object(live_providers, "urlopen", capture):
            result = live_providers.search_live_pnr("8148735219")
        self.assertEqual(result["status"], "CNF")
        self.assertEqual(result["booking_status"], "WL/2")
        self.assertEqual(seen[0].get_header("X-rapidapi-key"), "test-key")
        self.assertNotIn("test-key", json.dumps(result))

    def test_input_validation(self):
        with env():
            with self.assertRaises(ValueError):
                live_providers.search_live_pnr("12345")
            with self.assertRaises(ValueError):
                live_providers.search_live_seats("12951", "2026-10-20", "XX", "PUNE", "NDLS")

    def test_path_parameter_is_placed_in_url(self):
        seen = []
        def capture(request, timeout=8):
            seen.append(request.full_url)
            return FakeResponse(b'{"data": {"TrainNo": "12951"}}')
        with env(RAPIDAPI_PATH_PNR="/getPNRStatus/{pnrNumber}"), \
             mock.patch.object(live_providers, "urlopen", capture):
            live_providers.search_live_pnr("8148735219")
        self.assertEqual(seen[0], "https://example.p.rapidapi.com/getPNRStatus/8148735219")

    def test_responses_are_cached(self):
        calls = []
        def counting(request, timeout=8):
            calls.append(request.full_url)
            return FakeResponse(json.dumps({"data": {"current_station_code": "BPL", "delay": 12}}).encode())
        with env(), mock.patch.object(live_providers, "urlopen", counting):
            live_providers.live_train_status("12951")
            live_providers.live_train_status("12951")
        self.assertEqual(len(calls), 1)


class OutcomeMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.log = mock.patch.object(outcomes, "LOG", Path(self.tmp.name) / "o.jsonl")
        self.log.start()

    def tearDown(self):
        self.log.stop()
        self.tmp.cleanup()

    def test_collecting_state_before_enough_samples(self):
        outcomes.record("12951", "BPL", 20, 25, 30.0, "test")
        self.assertTrue(outcomes.summary(24.66)["status"].startswith("collecting"))

    def test_same_train_station_day_logged_once(self):
        outcomes.record("12951", "BPL", 20, 25, 30.0, "test")
        self.assertIn("skipped", outcomes.record("12951", "BPL", 20, 40, 30.0, "test"))

    def test_degradation_raises_alert(self):
        for i in range(35):
            outcomes.record(str(10000 + i), "BPL", 10, 90, 30.0, "test")
        report = outcomes.summary(24.66)
        self.assertEqual(report["status"], "attention")
        self.assertTrue(any(a["area"] == "live model performance" for a in report["alerts"]))
        self.assertTrue(any(a["area"] == "data drift" for a in report["alerts"]))

    def test_reconcile_skips_bad_provider_rows(self):
        statuses = {"1": {"current_station": "BPL", "delay_minutes": 30, "source": "t"},
                    "2": {"current_station": "", "delay_minutes": None}}
        rows = outcomes.reconcile(["1", "2"], fetch_status=lambda n: statuses[n],
                                  estimate=lambda n, s: {"minutes": 25}, global_mean=30.0)
        self.assertEqual(rows[0]["predicted"], 25)
        self.assertIn("error", rows[1])


if __name__ == "__main__":
    unittest.main()
