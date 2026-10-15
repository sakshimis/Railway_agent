const $ = (id) => document.getElementById(id);
let currentRole = null;
const tomorrow = new Date();
tomorrow.setDate(tomorrow.getDate() + 1);
$("travel-date").value = `${tomorrow.getFullYear()}-${String(tomorrow.getMonth() + 1).padStart(2, "0")}-${String(tomorrow.getDate()).padStart(2, "0")}`;
const el = (tag, className, value) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = String(value);
  return node;
};
async function api(path, body) {
  const options = body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body)
  };
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 404 && ["/api/historical-search", "/api/live-status", "/api/live-search", "/api/live-pnr", "/api/live-schedule"].includes(path))
      throw new Error("The page was updated but the server is still running old code. Stop the server with Ctrl+C, then start it again.");
    throw new Error(result.error || "Request failed");
  }
  return result;
}
function error(target, err) { target.replaceChildren(el("div", "callout rejected", err.message)); }
function line(target, label, value) {
  const row = el("div", "decision");
  row.append(el("strong", "", label + ": "), document.createTextNode(String(value)));
  target.append(row);
}
async function refreshCapabilities() {
  try {
    const status = await api("/api/live-status");
    $("pnr-availability").textContent = status.pnr_connected
      ? `Connected to ${status.provider}. Status depends on the provider response; this is a third-party service.`
      : "Live PNR is not configured on this server yet. You can still try the fictional sample below.";
    $("schedule-availability").textContent = status.schedule_connected
      ? `Provider timetable lookup connected through ${status.provider}.`
      : "Train schedule lookup is not configured on this server yet.";
  } catch (err) {
    $("pnr-availability").textContent = "Could not check the PNR provider connection.";
    $("schedule-availability").textContent = "Could not check the schedule provider connection.";
  }
}
async function loadLive(origin, destination) {
  const target = $("live-result");
  target.replaceChildren();
  try {
    const status = await api("/api/live-status");
    if (!status.connected) {
      target.append(el("p", "hint", "Current fares and seats are not connected. Historical results are shown below."));
      return;
    }
    target.append(el("div", "card", "Loading current fares and seats…"));
    const result = await api("/api/live-search", {
      origin, destination, travel_date: $("travel-date").value,
      class: $("travel-class").value
    });
    target.replaceChildren();
    const summary = el("div", "card");
    summary.append(el("h3", "", `Current fares and seats · ${result.travel_date}`));
    summary.append(el("p", "hint", `Provider updated: ${result.as_of}`));
    if (!result.trains.length) summary.append(el("p", "", "No current trains returned for this route and date."));
    target.append(summary);
    result.trains.forEach((train) => {
      const card = el("div", "card train-card");
      card.append(el("h3", "", `${train.train_no} · ${train.name}`));
      line(card, "Class", train.class || "Unknown");
      line(card, "Current fare", train.fare_rupees == null ? "Unknown" : `₹${train.fare_rupees}`);
      line(card, "Seat status", train.availability);
      if (train.departure) line(card, "Departure", train.departure);
      if (train.arrival) line(card, "Arrival", train.arrival);
      target.append(card);
    });
  } catch (err) {
    target.replaceChildren(el("p", "hint", err.message));
  }
}
function simpleResult(target, object) {
  target.replaceChildren();
  for (const [key, value] of Object.entries(object)) {
    if (value === null || typeof value === "object") continue;
    line(target, key.replaceAll("_", " "), value);
  }
}
function showSession(role) {
  currentRole = role;
  $("login-screen").hidden = Boolean(role);
  $("workspace").hidden = !role;
  $("logout").hidden = !role;
  $("signed-in").textContent = role === "admin" ? "Administrator" : "Passenger";
  document.querySelectorAll(".admin-only").forEach((item) => { item.hidden = role !== "admin"; });
  if (role) { loadTrains(); refreshCapabilities(); }
}
$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const result = await api("/api/login", {username: $("username").value, password: $("password").value});
    $("password").value = "";
    showSession(result.role);
    $("login-result").replaceChildren();
  } catch (err) { error($("login-result"), err); }
});
$("logout").addEventListener("click", async () => {
  await api("/api/logout", {});
  showSession(null);
  $("plan-result").replaceChildren();
  document.querySelectorAll(".tab,.panel").forEach((item) => item.classList.remove("active"));
  document.querySelector('[data-tab="planner"]').classList.add("active");
  $("planner").classList.add("active");
});
api("/api/session").then((result) => showSession(result.role)).catch(() => showSession(null));
document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => {
  if (button.classList.contains("admin-only") && currentRole !== "admin") return;
  document.querySelectorAll(".tab,.panel").forEach((item) => item.classList.remove("active"));
  button.classList.add("active");
  $(button.dataset.tab).classList.add("active");
  if (button.dataset.tab === "governance") { loadGovernance(); loadAudit(); }
}));
$("history-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const target = $("history-result");
  $("live-result").replaceChildren();
  target.replaceChildren(el("div", "card", "Searching historical records…"));
  try {
    const result = await api("/api/historical-search", {
      query: $("quick-query").value,
      origin: $("origin").value, destination: $("destination").value,
      class: $("travel-class").value, max_fare: $("max-fare").value,
      max_duration_hours: $("max-duration").value,
      sort: $("sort").value
    });
    loadLive(result.origin_code, result.destination_code);
    target.replaceChildren();
    const summary = el("div", "card");
    summary.append(el("h3", "", `${result.origin_code} → ${result.destination_code}`));
    const totalTrains = result.matching_trains + result.schedule_only_count;
    summary.append(el("p", "", `${totalTrains} train${totalTrains === 1 ? "" : "s"} found · Sorted by ${$("sort").selectedOptions[0].textContent.toLowerCase()}.`));
    if (result.schedule_only_count)
      summary.append(el("p", "hint", `Some fares are estimates because recorded prices are unavailable. Check current fares and seats before booking.`));
    if (totalTrains === 1)
      summary.append(el("p", "callout", "Only one train matches this route and these filters, so every sort choice shows the same train."));
    target.append(summary);
    const ranked = [
      ...result.options.map((item) => ({item, estimated: false})),
      ...result.schedule_only.map((item) => ({item, estimated: true}))
    ];
    const rankingClass = result.class_filter || "SL";
    const rankFare = ({item, estimated}) => estimated ? item.ranking_estimated_fare :
      item.fares.find((fare) => fare.class === rankingClass)?.fare;
    ranked.sort((a, b) => result.sort_used === "duration"
      ? a.item.duration_minutes - b.item.duration_minutes || a.item.departure.localeCompare(b.item.departure)
      : result.sort_used === "departure"
        ? a.item.departure.localeCompare(b.item.departure) || a.item.duration_minutes - b.item.duration_minutes
        : result.sort_used === "balanced"
          ? (a.item.balanced_score ?? Infinity) - (b.item.balanced_score ?? Infinity) || a.item.duration_minutes - b.item.duration_minutes
          : (rankFare(a) ?? Infinity) - (rankFare(b) ?? Infinity) || a.item.duration_minutes - b.item.duration_minutes);
    const sortReason = result.sort_used === "duration" ? "Shortest scheduled journey" :
      result.sort_used === "departure" ? "Earliest departure" :
      result.sort_used === "balanced" ? "Balanced best value (fare, duration & delay)" :
      `Lowest ${rankingClass} recorded or estimated fare`;
    const trainCard = ({item, estimated}, featured = false) => {
      const card = el("div", featured ? "card train-card recommendation" : "card train-card");
      if (featured) card.append(el("div", "eyebrow", `FIRST BY ${sortReason.toUpperCase()} · ${estimated ? "ESTIMATED PRICE" : "RECORDED PRICE"}`));
      card.append(el("h3", "", `${item.train_no} · ${item.name}`));
      card.append(el("p", "hint", estimated ? "Timetable match; class availability and fares are unverified." : "Recorded October 2023 class fares for this station pair."));
      const fares = el("div", "fare-options");
      if (estimated) item.fare_estimates.forEach((fare) => fares.append(el("span", "fare-option", `Estimated ${fare.class} ₹${fare.fare}`)));
      else item.fares.forEach((fare) => fares.append(el("span", "fare-option", `${fare.class} · ₹${fare.fare} recorded`)));
      card.append(fares);
      line(card, "Route", `${item.origin} → ${item.destination}`);
      line(card, "Snapshot schedule", `${item.departure} → ${item.arrival}${item.day_offset ? ` (+${item.day_offset} day)` : ""}`);
      line(card, "Scheduled duration", `${Math.floor(item.duration_minutes / 60)} h ${item.duration_minutes % 60} min`);
      if (estimated) line(card, "Timetable distance", `${item.distance_km} km`);
      if (item.delay_history.observations >= 20) line(card, "Historical average arrival delay", `${item.delay_history.minutes} min (2025–26; ${item.delay_history.observations} observations)`);
      if (featured) {
        const feedback = el("div", "row");
        feedback.append(el("span", "hint", "Was this first result useful?"));
        for (const [label, helpful] of [["Yes", true], ["No", false]]) {
          const button = el("button", "secondary", label);
          button.type = "button";
          button.addEventListener("click", async () => {
            for (const control of feedback.querySelectorAll("button")) control.disabled = true;
            try {
              await api("/api/historical-feedback", {
                train_no: item.train_no, origin_code: result.origin_code,
                destination_code: result.destination_code, helpful
              });
              feedback.replaceChildren(el("span", "hint", "Thank you. Your feedback was recorded."));
            } catch (err) { error(feedback, err); }
          });
          feedback.append(button);
        }
        card.append(feedback);
      }
      return card;
    };
    if (ranked.length) target.append(trainCard(ranked[0], true));
    if (ranked.length > 1) {
      const more = el("details", "other-trains");
      more.append(el("summary", "", `Show ${ranked.length - 1} other train${ranked.length === 2 ? "" : "s"} in this order`));
      ranked.slice(1).forEach((item) => more.append(trainCard(item)));
      target.append(more);
    }
    if (!result.options.length && !result.schedule_only.length)
      target.append(el("div", "callout", "No matching fare or timetable records for this route in the snapshot. Try another station."));
  } catch (err) { error(target, err); }
});
let stationTimer;
for (const id of ["origin", "destination"]) {
  $(id).addEventListener("input", () => {
    clearTimeout(stationTimer);
    stationTimer = setTimeout(async () => {
      try {
        const response = await fetch(`/api/stations?q=${encodeURIComponent($(id).value)}`);
        const values = await response.json();
        $("station-list").replaceChildren();
        values.forEach((station) => {
          const option = document.createElement("option");
          option.value = station.code;
          option.label = station.name;
          $("station-list").append(option);
        });
      } catch (_) { /* The route form displays a useful error if the catalog is unavailable. */ }
    }, 200);
  });
}
$("plan-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const target = $("plan-result");
  target.replaceChildren(el("div", "card", "Planning…"));
  try {
    const delay = Number($("delay").value);
    const planInput = {query: $("query").value, scenario: {delay_overrides: {"DEMO-A": delay}}};
    const result = await api("/api/plan", planInput);
    target.replaceChildren();
    const selected = el("div", "card recommendation");
    selected.append(el("div", "eyebrow", "SUGGESTED TRAIN"));
    selected.append(el("h3", "", result.selected ? result.selected.train : "No suitable train"));
    if (result.selected) {
      selected.append(el("div", "metric", "₹" + result.selected.fare));
      line(selected, "Departure", result.selected.departure.replace("T", " "));
      line(selected, "Journey duration", `${Math.floor(result.selected.journey_duration_minutes / 60)} h ${result.selected.journey_duration_minutes % 60} min`);
      line(selected, "Expected arrival", result.selected.expected_arrival.replace("T", " "));
      line(selected, "Seat status", result.selected.seat_status);
      line(selected, "Why", result.recommendation_reason);
    }
    selected.append(el("p", "hint", result.data_notice));
    (result.passenger_alerts || []).forEach((alert) => selected.append(el("p", "callout", alert)));
    if (result.selected) {
      const approval = el("label", "check");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      approval.append(checkbox, document.createTextNode(" I reviewed this sample itinerary"));
      const save = el("button", "secondary", "Save sample itinerary");
      save.type = "button";
      const saved = el("div", "mini-result");
      save.addEventListener("click", async () => {
        try {
          const value = await api("/api/itinerary", {...planInput, train_id: result.selected.train_id, approved: checkbox.checked});
          saved.replaceChildren(el("div", "callout", `${value.reference}: ${value.status}. No ticket was booked.`));
        } catch (err) { error(saved, err); }
      });
      selected.append(approval, save, saved);
      const feedback = el("div", "row");
      feedback.append(el("span", "hint", "Was this suggestion useful?"));
      for (const [label, helpful] of [["Yes", true], ["No", false]]) {
        const button = el("button", "secondary", label);
        button.type = "button";
        button.addEventListener("click", async () => {
          try {
            await api("/api/feedback", {train_id: result.selected.train_id, helpful});
            feedback.replaceChildren(el("span", "hint", "Thank you. Your feedback was recorded."));
          } catch (err) { error(feedback, err); }
        });
        feedback.append(button);
      }
      selected.append(feedback);
    }
    target.append(selected);
    if (result.disruption_rescue) {
      const rescueBox = el("div", "card");
      rescueBox.style.marginTop = "16px";
      rescueBox.style.borderLeft = "5px solid #d97706";
      rescueBox.append(el("div", "eyebrow", "DISRUPTION RESCUE AGENT ACTIVE"));
      rescueBox.append(el("h3", "", `Rescue Recommendation: ${result.disruption_rescue.rescue_train}`));
      rescueBox.append(el("p", "", result.disruption_rescue.reason));
      line(rescueBox, "Disrupted option(s)", result.disruption_rescue.disrupted_trains.join(", "));
      target.append(rescueBox);
    }
    if (result.alternatives.length) {
      const alternatives = el("div", "card");
      alternatives.style.marginTop = "16px";
      alternatives.append(el("h3", "", "Other suitable trains"));
      result.alternatives.forEach((item) => line(alternatives, item.train, `₹${item.fare} · ${item.departure.replace("T", " ")}`));
      target.append(alternatives);
    }
    if (currentRole !== "admin") return;
    if (Array.isArray(result.orchestration_trail)) {
      const agentBox = el("div", "card");
      agentBox.style.marginTop = "16px";
      agentBox.append(el("div", "eyebrow", "MULTI-AGENT ORCHESTRATION PIPELINE"));
      agentBox.append(el("h3", "", "Autonomous agent execution trace"));
      result.orchestration_trail.forEach((step) => {
        const row = el("div", "decision");
        row.append(el("strong", "", step.agent + " (" + step.status + "): "));
        row.append(document.createTextNode(step.action));
        agentBox.append(row);
      });
      target.append(agentBox);
    }
    const detail = el("div", "card");
    detail.style.marginTop = "16px";
    detail.append(el("h3", "", "Decision trail"));
    result.decisions.forEach((decision) => {
      const row = el("div", "decision");
      row.append(el("span", decision.status, decision.status.toUpperCase() + "  "));
      row.append(document.createTextNode(decision.train + " — " + decision.reasons.join("; ")));
      detail.append(row);
    });
    const alerts = el("p", "hint", result.governance_alerts.length ?
      "Governance: " + result.governance_alerts.join(" | ") :
      "No demo governance alert for these trains.");
    detail.append(alerts);
    target.append(detail);
  } catch (err) { error(target, err); }
});
$("confirmation-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const value = await api("/api/confirmation", {
      wl_position: Number($("wl").value), days_before: Number($("days").value),
      class: $("class").value
    });
    simpleResult($("confirmation-result"), value);
  } catch (err) { error($("confirmation-result"), err); }
});
$("fare-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const value = await api("/api/fare", {
      train_id: $("fare-train").value, days_before: Number($("fare-days").value)
    });
    simpleResult($("fare-result"), value);
  } catch (err) { error($("fare-result"), err); }
});
$("support-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    simpleResult($("support-result"), await api("/api/support", {
      question: $("support-question").value, language: $("language").value
    }));
  } catch (err) { error($("support-result"), err); }
});
$("pnr-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const target = $("pnr-result");
  target.replaceChildren(el("div", "callout", "Checking the connected PNR provider…"));
  try { simpleResult(target, await api("/api/live-pnr", {pnr: $("pnr").value})); }
  catch (err) { error($("pnr-result"), err); }
});
$("schedule-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const target = $("schedule-result");
  target.replaceChildren(el("div", "callout", "Checking the provider timetable…"));
  try {
    const result = await api("/api/live-schedule", {train_no: $("schedule-train").value});
    target.replaceChildren();
    target.append(el("h3", "", `${result.train_no} ${result.train_name}`.trim()));
    target.append(el("p", "hint", `${result.stops.length} stops · ${result.notice}`));
    const wrapper = el("div", "schedule-table-wrap");
    const table = el("table", "schedule-table");
    const head = el("thead");
    const labels = el("tr");
    ["Station", "Arrives", "Departs", "Day"].forEach((label) => labels.append(el("th", "", label)));
    head.append(labels);
    const body = el("tbody");
    result.stops.forEach((stop) => {
      const row = el("tr");
      [stop.station_name ? `${stop.station_name} (${stop.station_code})` : stop.station_code,
       stop.arrival || "—", stop.departure || "—", stop.day || "—"]
        .forEach((value) => row.append(el("td", "", value)));
      body.append(row);
    });
    table.append(head, body);
    wrapper.append(table);
    target.append(wrapper, el("p", "subtle", `Source: ${result.source}; checked ${result.as_of}`));
  } catch (err) { error(target, err); }
});
for (const [id, pnr] of [["sample-pnr-one", "1234567890"], ["sample-pnr-two", "9876543210"]]) {
  $(id).addEventListener("click", async () => {
    try { simpleResult($("sample-pnr-result"), await api("/api/pnr", {pnr})); }
    catch (err) { error($("sample-pnr-result"), err); }
  });
}
$("refund-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try { simpleResult($("refund-result"), await api("/api/refund", {reference: $("refund-reference").value})); }
  catch (err) { error($("refund-result"), err); }
});
$("fraud-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const value = await api("/api/fraud", {
      bookings_last_10_minutes: Number($("bookings").value),
      failed_logins_last_hour: Number($("failed").value),
      payment_mismatch: $("mismatch").checked
    });
    simpleResult($("fraud-result"), value);
    line($("fraud-result"), "signals", value.signals.join(", ") || "none");
  } catch (err) { error($("fraud-result"), err); }
});
async function loadGovernance() {
  const target = $("governance-result");
  try {
    const report = await api("/api/governance");
    target.replaceChildren();
    line(target, "Status", report.status);
    line(target, "Active delay model", report.registry.active.delay);
    if (report.support_metrics) {
      line(target, "Support hallucination control",
        `${report.support_metrics.grounded_answers} answered / ${report.support_metrics.abstained_queries} abstained (${(report.support_metrics.abstention_rate * 100).toFixed(1)}% abstention rate)`);
    } else {
      line(target, "Recent support abstentions", report.support_abstentions_in_recent_audit);
    }
    if (report.confirmation_model_evaluation) {
      line(target, "Confirmation test Brier score", report.confirmation_model_evaluation.brier_score ?? "N/A");
    }
    line(target, "Synthetic recommendation feedback", `${report.recommendation_feedback.helpful} useful / ${report.recommendation_feedback.responses} responses`);
    line(target, "Historical search feedback", `${report.historical_recommendation_feedback.helpful} useful / ${report.historical_recommendation_feedback.responses} responses (recent audit sample)`);
    line(target, "Average latency", report.recent_average_latency_ms === null ?
      "No events yet" : report.recent_average_latency_ms + " ms");
    line(target, "Recent p95 latency", report.recent_p95_latency_ms === null ?
      "No events yet" : `${report.recent_p95_latency_ms} ms / ${report.latency_slo_ms} ms target (${report.latency_sample_count} samples)`);
    report.alerts.forEach((alert) => {
      const box = el("div", "callout");
      box.append(el("strong", "", alert.area + " · " + alert.subject));
      box.append(el("div", "", alert.reason));
      box.append(el("div", "hint", "Suggested action: " + alert.action));
      target.append(box);
    });
    line(target, "Root cause summary", report.root_cause_summary);
    const data = $("data-report");
    data.replaceChildren();
    if (Array.isArray(report.registered_models)) {
      const modelCard = el("div", "evidence-block");
      modelCard.append(el("h4", "", "Autonomous AI Model Registry"));
      report.registered_models.forEach((m) => {
        const item = el("div", "decision");
        item.append(el("strong", "", m.name + ": "));
        item.append(document.createTextNode(`${m.type} · Status: ${m.status}`));
        modelCard.append(item);
      });
      data.append(modelCard);
    }
    const evidence = report.kaggle_evidence || {};
    for (const [label, section] of Object.entries(evidence)) {
      const card = el("div", "evidence-block");
      card.append(el("h4", "", label.replaceAll("_", " ")));
      for (const [field, value] of Object.entries(section)) line(card, field.replaceAll("_", " "), value);
      data.append(card);
    }
  } catch (err) { error(target, err); }
}
async function loadAudit() {
  const target = $("audit-result");
  try {
    const events = await api("/api/audit");
    target.replaceChildren();
    events.slice().reverse().forEach((event) => {
      target.append(el("div", "audit-row", event.at + " · " + event.event +
        (event.latency_ms === null ? "" : " · " + event.latency_ms + " ms")));
      if (event.event === "journey_planned" && Array.isArray(event.payload?.decisions)) {
        const detail = el("div", "card");
        detail.append(el("strong", "", "Planner decision trail"));
        event.payload.decisions.forEach((decision) =>
          line(detail, decision.train, `${decision.status}: ${decision.reasons.join("; ")}`));
        target.append(detail);
      }
    });
    if (!events.length) target.textContent = "No audit events yet.";
  } catch (err) { error(target, err); }
}
$("refresh-governance").addEventListener("click", loadGovernance);
$("refresh-audit").addEventListener("click", loadAudit);
async function lifecycle(path) {
  const target = $("lifecycle-result");
  try {
    const value = await api(path, {
      approved: $("approve").checked
    });
    target.replaceChildren();
    line(target, "Result", value.status || "completed");
    if (value.reason) line(target, "Reason", value.reason);
    if (value.version) line(target, "Candidate version", value.version);
    if (value.baseline_holdout_mae !== undefined)
      line(target, "Baseline / candidate MAE",
        value.baseline_holdout_mae + " / " + value.candidate_holdout_mae + " min");
    if (value.active) line(target, "Active delay model", value.active.delay);
    loadGovernance(); loadAudit();
  } catch (err) { error(target, err); }
}
$("candidate").addEventListener("click", () => lifecycle("/api/governance/candidate"));
$("promote").addEventListener("click", () => lifecycle("/api/governance/promote"));
$("rollback").addEventListener("click", () => lifecycle("/api/governance/rollback"));
async function loadTrains() {
  const trains = await api("/api/trains");
  $("fare-train").replaceChildren();
  trains.forEach((train) => {
    const option = el("option", "", train.name + " · ₹" + train.fare);
    option.value = train.id;
    $("fare-train").append(option);
  });
}
