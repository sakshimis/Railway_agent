# Data provenance and limitations

The checked-in `data/historical_catalog.sqlite` contains train, station, timetable and fare fields derived from the following public dataset. It contains no passenger identities, bookings or PNRs. The source publisher labels the dataset Apache 2.0; check the source page again before redistribution or a public release.

| Use | Source | Source-reported license | Limitation |
|---|---|---|---|
| Historical timetable and fare catalog | [Indian Railways Schedule-Prices-Availability Data](https://www.kaggle.com/datasets/bhavyarajdev/indian-railways-schedule-prices-availability-data) | Apache 2.0 | October 2023 snapshot. Fares do not cover every train/station pair. Availability is not current. |
| Aggregated historical delay model | [Indian Railways - Delay Dataset](https://www.kaggle.com/datasets/rxydenxd/indian-railways-delay-dataset) | MIT | Publisher-reported 2025–26 observations; real-world provenance has not been independently verified. The raw dataset is not included. |
| Confirmation dataset review only | [Indian Railway Ticket Confirmation](https://www.kaggle.com/datasets/aaryananil/indian-railway-ticket-confirmation) | MIT | Synthetic; excluded from passenger prediction because usable wait-list outcomes did not support validation. |

`import_kaggle.py` rebuilds the historical catalog and models from downloaded source ZIPs. `data/kaggle_report.json` records imported counts and exclusions. The small `trains.json`, `pnr.json`, refund, policy and sample-history files are synthetic demonstrations. The project does not supply current Indian Railways prices, seats, PNRs, bookings or an official API key.

Do not commit the `runtime/` directory from a running copy: it contains password hashes, audit events and user-generated demo state.
