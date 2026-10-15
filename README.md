# Railway AI case-study prototype

> Educational prototype with historical and synthetic data. It is not a live railway service. See [the case-study checklist](REQUIREMENTS.md), [data sources](DATA_SOURCES.md), and [GitHub publishing steps](GITHUB_SETUP.md).

For submission, follow [SUBMISSION_GUIDE.md](SUBMISSION_GUIDE.md) and present with [DEMO_SCRIPT.md](DEMO_SCRIPT.md). Source repository: https://github.com/sakshimis/Railway_agent.

This local Python web app separates passenger and administrator roles. Passenger route search uses a public Kaggle **historical snapshot**, while the admin area holds synthetic agent scenarios, model demonstrations, governance and audit. It is an educational prototype, not a live railway booking service.

`db/postgres_schema.sql` is a proposed PostgreSQL schema for the next development stage. The running app still uses its bundled SQLite catalog and local runtime files; no PostgreSQL migration has been performed.

## Start on Windows

1. Open PowerShell in this folder.
2. Create a local environment once: `python -m venv .venv` (Python 3.12 or later).
3. Create accounts once: `.\.venv\Scripts\python.exe app.py --init-users`. Choose separate strong passwords for `user` and `admin`.
4. Start: `.\.venv\Scripts\python.exe app.py` (or double-click `start_windows.cmd`).
5. Open `http://127.0.0.1:8765`.

No third-party Python package is required to run the app. The bundled historical catalog and delay model are generated from Kaggle datasets. Passenger pages never show a live seat status or claim that 2023 fares are current.

## What is in each page

- **Journey planner (passenger):** station code/name search or a simple route sentence, travel class, maximum historical fare, maximum scheduled duration and sort. Station suggestions cover all 3,766 timetable station codes. Results show observed 2023 fares where available. When a route lacks a fare record, the app gives class-specific **estimated 2023 fares** from a held-out-tested distance model. It does not know which classes a particular train offers. Recorded-fare and timetable-only trains are sorted in one visible list, with each fare source labeled. Without a chosen class, fare order uses Sleeper (SL). The top match follows the selected sort, with other trains expandable. Passengers can rate the usefulness of the first result; this voluntary feedback is reported separately to admins and does not prove recommendation accuracy. A travel date and each result's train and station codes help you check the current fare and seats on the linked official Indian Railways enquiry pages. Those official results stay on the official site and are not imported into this app. Try `PUNE` to `NDLS` for one recorded-fare train and one timetable-only train, or `PUNE` to `RTM` for estimates. There is no booking action.
- **Passenger support:** sample PNR/refund records and limited English/Hindi answers. These are synthetic and cannot answer live account questions.
- **Model lab (admin):** clearly synthetic confirmation and fare scenario controls, with technical explanations restricted to admins.
- **Governance (admin):** Kaggle source counts, model test error, quality exclusions, audit, and a separate synthetic lifecycle exercise.
- **Scenario lab (admin):** natural-language journey rescue and supervisor decision trail on fictional trains.

## Rebuild imported data

Get the public ZIPs from the sources linked in [REQUIREMENTS.md](REQUIREMENTS.md). Then run:

`python import_kaggle.py PRICE_ZIP DELAY_ZIP CONFIRMATION_ZIP`

The delay import reads a 1 GB CSV from the ZIP and may take several minutes. It trains on records through December 2025 and tests on January–February 2026. The fare catalog is an indexed SQLite file. The fare estimator holds out entire train numbers for evaluation. Raw Kaggle ZIPs are not bundled; derived records and model summaries are included. See `data/kaggle_report.json` for exact counts and limitations.

## Verify

`python -m unittest discover -s tests -v`

See [REQUIREMENTS.md](REQUIREMENTS.md) for an honest case-study checklist and [INTERVIEW_GUIDE.md](INTERVIEW_GUIDE.md) for a student explanation. No ticket purchase, live PNR, live seat status or current fare API is connected.

Local login limits five failed attempts per account and client within 15 minutes. The admin dashboard reports recent p95 request latency against a 1,000 ms local target. These controls are demonstrations, not production authentication or service-level guarantees.

## Why the database cannot show every fare

The Kaggle files are snapshots with different coverage: the timetable includes station pairs for which the fare file has no price row. The distance model fills those gaps only as a research estimate; it cannot verify a train's offered class, current fare, seat availability or service on a selected date. A live in-app feed would require an authorized railway data integration. Until one is available, use the official enquiry links for real travel decisions.
