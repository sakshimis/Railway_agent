# Interview guide: Railway AI case-study prototype

## Your 90-second explanation

“I built a local railway AI case-study prototype with separate passenger and administrator access. I imported over 326,000 historical fare observations and over 38 million station-delay observations from public Kaggle datasets. Passengers search historical routes, compare class, fare and timetable, and see clearly dated delay evidence. An administrator can inspect source quality, exclusions and a time-separated delay-model test. A separate synthetic scenario lab demonstrates how an agent parses a request, filters constraints, uses a supervisor and proposes a rescue train. We reviewed a synthetic confirmation dataset but excluded it from passenger predictions because none of its usable wait-list rows had a confirmed outcome. The system has no live fares, seat status or booking integration, so it never presents historical data as current.”

## Live demo in about five minutes

1. Sign in as passenger. Search PUNE to NDLS. Show historical fare, class and timetable, and explain why seat availability is unknown.
2. Sign in as admin. Open Governance and show exact imported-row counts, exclusions, test period and delay mean absolute error against the global baseline.
3. Open Scenario lab. Run the Pune–Delhi request with 90 minutes for Demo Train A. Show that A misses 10:00 and D is chosen; change the delay to 30 minutes and show the rescue decision changing.
4. Open Model lab. Explain why the confirmation and future-fare controls are labeled synthetic and restricted to admin.
5. Ask an unsupported support question and show abstention. Show audit and the separate lifecycle approval exercise.

## Architecture: what each part is

- **Parser:** Regular expressions and date/time parsing. This is deterministic language understanding for a narrow request format, not an LLM.
- **Passenger planner:** Indexed SQLite lookup of Kaggle historical schedule/fare records. Filtering and sorting are deterministic, not machine learning.
- **Scenario planner:** A separate synthetic orchestrator that calls estimators, filters constraints, ranks feasible options and returns reasons.
- **Confirmation predictor:** A weighted-neighbor statistical estimator over synthetic labeled WL outcomes, smoothed to avoid extreme probabilities from tiny data.
- **Historical delay model:** A train/station mean shrunk toward train and global averages. Training ends in December 2025; January–February 2026 is held out for testing. It is a baseline, not a live running-status forecast.
- **Scenario delay estimator:** A synthetic historical mean with an admin what-if override.
- **Passenger fare estimator:** A class-specific linear distance model trained on October 2023 fares, tested on held-out train numbers. It fills missing historical route prices as estimates. It cannot verify whether a train offers a class or what today's fare is.
- **Admin fare scenario:** A transparent demand-based synthetic formula, not a validated future price forecast.
- **Support:** Grounded rule retrieval from a small knowledge base and synthetic PNR dataset. It abstains when no source supports an answer.
- **Fraud:** A transparent rules score for triage, never an automatic accusation or account block.
- **Supervisor and governance:** Schema checks, independent constraint checks, prediction error, drift, coverage, audit, candidate evaluation, approval gate and rollback simulation.

## Questions you should expect

### “What makes this agentic?”

It takes a user goal, breaks it into tasks, calls multiple services, compares options, checks its work, and presents an actionable recommendation. The current orchestration is deterministic. A future LLM could improve flexible language interpretation, but the safety-critical booking and governance checks should remain explicit and testable.

### “Where is the AI or machine learning?”

The Kaggle-backed delay estimate is an empirical statistical model. Passenger route search is deterministic. The admin confirmation estimate is a small synthetic instance-based model; fare and fraud are rules. Explain this honestly. An agent describes orchestration, not necessarily an LLM.

### “Why is an average delay not enough?”

It ignores time of day, station, route, weather, season and recent disruptions. It can be badly wrong after a distribution shift. I show leave-one-out error and drift warnings, and I would replace it with a time-aware model once enough real data is available.

### “How do you evaluate ticket confirmation?”

Use a time-separated test set. Report Brier score and calibration curves for probability quality, plus accuracy/recall only after choosing a decision threshold. Break results down by WL bucket, class, route and booking lead time. Do not claim that 80% probability guarantees confirmation.

### “What is model drift?”

**Data drift** means the input pattern changes, such as a new distribution of delays. **Concept drift** means the relationship between inputs and actual outcomes changes. The demo compares earlier and recent mean delays as a simple drift signal; production should use richer tests and observed labels.

### “What is a confidence score?”

It describes uncertainty or evidence quality, not certainty. The demo labels confirmation evidence “limited” when nearby examples are sparse. In production, calibrate probabilities and provide validated intervals or reliability ranges.

### “How do you prevent hallucinations?”

The support component answers only from its demo PNR and policy sources. If it cannot ground an answer, it explicitly abstains. With an LLM, add retrieval with source IDs, output validation, policy filters, and evaluation on unsupported questions.

### “How do you handle bias?”

The demo reports coverage gaps by travel class. That is **not** a demographic fairness assessment. Real fairness evaluation requires carefully governed, consented data, a defined fairness objective, and error analysis by relevant groups. Do not infer protected attributes from names or travel behavior.

### “Why have a supervisor if the planner already filters trains?”

The planner selects candidates; the supervisor independently verifies critical rules before presenting them. This catches corrupted data or an orchestration bug. The fault-injection demo in the earlier learning version showed a negative fare being blocked.

### “How does retraining work?”

The monitor identifies a problem, but sparse data should trigger data collection rather than blind retraining. The demo fits a recent-mean candidate, compares it with the baseline on held-out synthetic observations, and requires approval to promote it. A production system also needs versioned data, reproducible training, canary deployment and measured rollback triggers.

### “How do you secure it?”

The local demo binds to 127.0.0.1, limits request size, avoids storing raw support questions/PNRs in its audit log, and performs input checks. It has separate passenger and admin passwords stored as salted scrypt hashes. Server-side sessions and role checks protect the admin API; the passenger plan response omits internal governance fields. Five failed login attempts per account and client cause a temporary lockout. This is local demo authentication, not production identity management. HTTPS, durable sessions, broader rate limiting, recovery and security review are still required before deployment.

### “How would you scale to millions of users?”

Separate API, inference, data ingestion and governance services. Cache stable schedules, use queues for alerts/retraining, replicate services across zones, monitor p95/p99 latency and error rates, and test peak booking traffic. This local single-process server is only a demonstration.

### “Can it book tickets?”

No. It returns a booking preview boundary. A real booking requires an authorized official integration, fresh availability and fare, exact passenger details, and explicit user approval before submission.

## Metrics to know

| Metric | Meaning | Used for |
|---|---|---|
| MAE | Average absolute difference between predicted and actual delay | Delay quality |
| Brier score | Mean squared difference between predicted probability and 0/1 outcome | Confirmation probability quality |
| Calibration | Whether events predicted at 70% occur about 70% of the time | Trustworthy probabilities |
| Precision | Of flagged fraud cases, fraction actually fraudulent | False-alert control |
| Recall | Of actual fraud cases, fraction detected | Missed threat control |
| Drift | Change in input or outcome patterns | Model monitoring |
| p95 latency | 95% of requests are faster than this time | Service performance |
| Abstention rate | How often support refuses unsupported answers | Hallucination control |

## What to say about limitations

“The passenger catalog uses historical Kaggle records, while the scenario, confirmation and governance lifecycle controls remain synthetic. I report a time-split delay test, but cannot claim current railway accuracy without verified operational data. The next phase is official live feeds, final booking outcomes, calibrated models and production security.”

This honest explanation is stronger than calling every formula “AI.”
