# Five-minute project demonstration

1. **Login (30 seconds).** Start `app.py`, open http://127.0.0.1:8765, and sign in as `user`. Explain that the server checks roles and that the administrator area is separate.
2. **Journey search (90 seconds).** Search from `PUNE` to `NDLS`. Compare the observed historical fare, class, timetable and delay evidence. Explain that the catalog is an October 2023 snapshot and current seats and prices are unknown. Change sorting or filter by budget/class to show the planner behavior.
3. **Support (30 seconds).** Ask a supported refund or PNR demo question. Ask an unrelated question and show that the assistant abstains when it has no grounded answer.
4. **Admin governance (60 seconds).** Log in as `admin`. Show imported data counts, quarantined rows, the time-separated delay test (MAE 24.66 minutes versus 35.06 minutes for the global baseline), model coverage and audit events.
5. **Agent scenario (60 seconds).** In Scenario lab, enter `I want to travel from Pune to Delhi tomorrow under 1500 before 10:00 AM`. Use a 90-minute delay for fictional Train A; the supervisor rejects it for the arrival deadline and selects a rescue option. Change the delay to 30 minutes to demonstrate a different decision. This scenario is synthetic.
6. **Close (30 seconds).** State the boundary: the prototype has no official live fare, seat, PNR, payment or booking integration. Point to `REQUIREMENTS.md` for the gap analysis.

## Questions to be ready for

- **Is it an LLM?** No. Narrow natural-language parsing, statistical baselines, deterministic ranking and supervised decision checks are used. Agentic refers to coordinating steps toward a goal.
- **Where is machine learning?** The historical delay model and class-specific fare estimator are fitted from Kaggle data. Search and fraud rules are deterministic; confirmation and future-fare controls are synthetic demonstrations.
- **How was delay evaluated?** Training uses 2025-02 through 2025-12; testing uses 2026-01 through 2026-02. The reported MAE is 24.66 minutes on a sampled held-out test set.
- **Why no live booking?** Authorized operational and booking credentials are not available. Saving a sample itinerary is not a purchase.
