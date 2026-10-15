# Case-study implementation status

Source: *AI-Powered Intelligent Railway Travel & Autonomous AI Governance Platform*, 7-page student case study. A working demonstration is not a production railway service.

| Case-study requirement | Status | What the project does | Remaining work |
|---|---|---|---|
| Large railway data foundation | Implemented for offline research | Imports 326,643 fare rows and 38,428,703 delay rows from two public Kaggle datasets; validates, indexes and documents exclusions | Verify publisher provenance and acquire official operational feeds |
| Journey planner and recommendations | Partial | Passenger route search covers historical routes, classes, budgets, maximum scheduled duration and sorting; timetable-only matches are shown when fare data is missing; anonymous usefulness feedback is collected for the first result; admin simulation demonstrates constrained recommendations and rescue | Current schedules, travel-date service days, availability, preference learning, validated ranking evaluation |
| Delay prediction and disruption response | Partial | Train/station historical delay averages with time-separated test; admin what-if rescue simulation | Real-time train positions, disruptions, calibrated uncertainty, proactive alerts |
| WL/RAC confirmation | Demonstration only | Admin synthetic prototype; reviewed a 30,000-row synthetic Kaggle dataset | Real booking and final-chart outcomes; among 10,053 usable wait-list rows in Kaggle, zero were labeled confirmed, so it was excluded from passenger predictions |
| Fare prediction and demand | Historical estimate only | Observed October 2023 fares are searchable; missing route fares receive class-specific distance estimates tested on held-out trains | Estimate error remains material, train class availability is unverified, and multiple dated snapshots/demand labels are needed for future-fare prediction; current quotes require an official feed |
| Seat availability | Not implemented with live data | Unknown is stated on passenger pages | Official live availability integration |
| Customer support | Demonstration only | English/Hindi bounded policy answers; sample PNR/refund; abstains outside known topics | Official current policy, PNR and refund services; measured multilingual quality |
| Booking approval and transactions | Partial | Explicit approval before saving a synthetic itinerary; no purchase | Official booking and payment tools with consent, confirmation and failure handling |
| Multi-agent orchestration | Partial simulation | Separate planner, prediction, supervisor and governance functions | Independent agents with tool contracts, handoffs and end-to-end evaluation |
| Fraud/bot detection | Demonstration only | Admin-only rule-based triage and human-review recommendation | Real event stream, labels, investigation workflow and false-positive evaluation |
| Autonomous AI governance | Partial | Admin source/quality/coverage/MAE report, voluntary recommendation feedback, recent p95 latency threshold; synthetic model audit, candidate approval and rollback demonstration | All-model real-time drift, bias, hallucination, resource monitoring, validated root cause and deployment automation |
| Security, privacy, scale | Partial local demo | Separate hashed-password accounts, server-side roles, bounded input, failed-login rate limit, local audit | HTTPS, durable sessions, broader rate limits, privacy program, load testing, resilience, compliance review |

## Data sources and limits

- [Indian Railways Schedule-Prices-Availability Data](https://www.kaggle.com/datasets/bhavyarajdev/indian-railways-schedule-prices-availability-data), Apache 2.0, publisher-reported October 2023 snapshot. The app uses schedule and fare fields. It intentionally does **not** display 2023 availability as current seats.
- [Indian Railways - Delay Dataset](https://www.kaggle.com/datasets/rxydenxd/indian-railways-delay-dataset), MIT, publisher-reported station-level scraped observations from February 2025 to February 2026. The publisher's real-world provenance has not been independently verified.
- [Indian Railway Ticket Confirmation](https://www.kaggle.com/datasets/aaryananil/indian-railway-ticket-confirmation), MIT, explicitly synthetic. Reviewed, but not used for passenger predictions: none of 10,053 usable wait-list rows had a confirmed final outcome. The `Current Status` field also reveals much of the target, so using it would risk leakage.

Exact imported and test counts, exclusions and delay test error are in `data/kaggle_report.json` and displayed in the admin governance page. Running `import_kaggle.py` with the three original ZIP files rebuilds the catalog and model.
