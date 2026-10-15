# Railway AI: case-study submission

An end-to-end **local demonstration** of the *AI-Powered Intelligent Railway Travel & Autonomous AI Governance Platform* case study. It includes a passenger journey planner, separate user/admin login, historical data processing, delay and fare estimates, agent decision traces, and an administrator governance dashboard. See the [requirement-by-requirement status](REQUIREMENTS.md) and [data sources](DATA_SOURCES.md).

## Placement submission

The placement notice asks students to submit the **GitHub repository link** through the Google Form when it is shared, by **16 October 2026, 10:00 AM**. Repository: https://github.com/sakshimis/Railway_agent. The repository link is the requested submission item; the local demo URL below works only on the computer running the app. Use [DEMO_SCRIPT.md](DEMO_SCRIPT.md) for a walkthrough and [SUBMISSION_GUIDE.md](SUBMISSION_GUIDE.md) for setup and presentation notes.

**Scope and limitations:** This is an educational prototype, not an operational railway service. Search results use historical Kaggle snapshots and model estimates. The live API endpoints are integration points, but there is no authorized live provider connected, so current fares, seats and PNR cannot be returned. Booking/payment, live disruption alerts, real confirmation outcomes and production-scale governance are not implemented. The PostgreSQL schema is a proposed design; the running app uses SQLite and local files. Do not use the demo to make real travel or booking decisions.

This local Python web app separates passenger and administrator roles. Passenger route search uses a public Kaggle **historical snapshot**, while the admin area holds synthetic agent scenarios, model demonstrations, governance and audit. It is an educational prototype, not a live railway booking service.

The passenger planner has an in-app live fare/seat API endpoint, but no authorized provider credentials are configured. It reports live data as unavailable until a provider is connected. See [LIVE_API_SETUP.md](LIVE_API_SETUP.md). No external fare or seat links are shown to passengers.

`db/postgres_schema.sql` is a proposed PostgreSQL schema for the next development stage. The running app still uses its bundled SQLite catalog and local runtime files; no PostgreSQL migration has been performed.

## Start on Windows

1. Open PowerShell in this folder.
2. Create a local environment once: `python -m venv .venv` (Python 3.12 or later).
3. Create accounts once: `.\.venv\Scripts\python.exe app.py --init-users`. Choose separate strong passwords for `user` and `admin`.
4. Start: `.\.venv\Scripts\python.exe app.py` (or double-click `start_windows.cmd`).
5. Open `http://127.0.0.1:8765`.

No third-party Python package is required to run the app. The bundled historical catalog and delay model are generated from Kaggle datasets. Without an authorized provider, passenger pages do not show live seat status or claim that 2023 fares are current.

## What is in each page

- **Journey planner (passenger):** station code/name search or a simple route sentence, travel class, maximum historical fare, maximum scheduled duration, and 4 sort modes (Lowest fare, Shortest journey, Earliest departure, and Best value / balanced recommendation balancing fare, duration and delay risk). Station suggestions cover all 3,766 timetable station codes with aliases for major Indian railway hubs. Results show observed 2023 fares where available. When a route lacks a fare record, the app gives class-specific **estimated 2023 fares** from a held-out-tested distance model. It does not know which classes a particular train offers. Recorded-fare and timetable-only trains are sorted in one visible list, with each fare source labeled. Without a chosen class, fare order uses Sleeper (SL). The top match follows the selected sort, with other trains expandable. Passengers can rate the usefulness of the first result; this voluntary feedback is reported separately to admins and does not prove recommendation accuracy. A travel date is sent to the in-app live-data adapter, which currently reports unavailable because no authorized provider is connected. Try `PUNE` to `NDLS` for one recorded-fare train and one timetable-only train, or `PUNE` to `RTM` for estimates. There is no booking action.
- **Passenger support:** sample PNR/refund records and grounded English/Hindi answers across 6 core policy domains (refunds, cancellations, Tatkal timings and rules, RAC berth entitlement, luggage allowances, and senior citizen concessions). Strictly abstains on ungrounded questions to prevent hallucinations.
- **Model lab (admin):** clearly synthetic confirmation and fare scenario controls with probabilistic Brier score and calibration analysis across WL buckets, plus dynamic flexi-fare lead-time pricing trajectories, with technical explanations restricted to admins.
- **Governance (admin):** Model inventory registry, Kaggle source counts, delay model test error (24.66 min MAE), quality exclusions, support hallucination tracking, confirmation calibration, audit, and a separate synthetic lifecycle exercise.
- **Scenario lab (admin):** Multi-agent orchestration pipeline (`TravelPlannerAgent` -> `PredictionAgent` -> `SupervisorAgent` -> `RescueAgent` -> `GovernanceAgent`) with natural-language journey rescue and supervisor decision trail on fictional trains.

## Rebuild imported data

Get the public ZIPs from the sources linked in [REQUIREMENTS.md](REQUIREMENTS.md). Then run:

`python import_kaggle.py PRICE_ZIP DELAY_ZIP CONFIRMATION_ZIP`

The delay import reads a 1 GB CSV from the ZIP and may take several minutes. It trains on records through December 2025 and tests on January–February 2026. The fare catalog is an indexed SQLite file. The fare estimator holds out entire train numbers for evaluation. Raw Kaggle ZIPs are not bundled; derived records and model summaries are included. See `data/kaggle_report.json` for exact counts and limitations.

## Verify

`python -m unittest discover -s tests -v`

See [REQUIREMENTS.md](REQUIREMENTS.md) for an honest case-study checklist and [INTERVIEW_GUIDE.md](INTERVIEW_GUIDE.md) for a student explanation. No ticket purchase, live PNR, live seat status or current fare API is connected.

Local login limits five failed attempts per account and client within 15 minutes. The admin dashboard reports recent p95 request latency against a 1,000 ms local target. These controls are demonstrations, not production authentication or service-level guarantees.

## Why the database cannot show every fare

The Kaggle files are snapshots with different coverage: the timetable includes station pairs for which the fare file has no price row. The distance model fills those gaps only as a research estimate; it cannot verify a train's offered class, current fare, seat availability or service on a selected date. A live in-app feed would require an authorized railway data integration. For real travel decisions, verify details through an official railway service.
