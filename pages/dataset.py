"""Dataset — coverage summary, unpaired items, and auto-cycle history."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from data_loader import get_company_profiles, get_cycle_runs, get_detections, get_eval_dataset

data = get_eval_dataset()

# Company name resolution
_all_tickers = sorted(
    {p["ticker"] for p in data["predictions"]}
    | {o["ticker"] for o in data["outcomes"]}
)
_profiles = get_company_profiles(tuple(_all_tickers)) if _all_tickers else {}


def _company_name(ticker: str, existing: str = "") -> str:
    return existing if existing else _profiles.get(ticker, ticker)


st.title("Dataset")
st.subheader("Dataset Coverage")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Outcomes", len(data["outcomes"]))
col2.metric("Predictions", len(data["predictions"]))
col3.metric("Paired", data["n_paired"])
col4.metric("Unpaired Predictions", data["n_unpaired_predictions"])

# --- Outcomes table ---
if data["outcomes"]:
    with st.expander(f"Recorded Outcomes ({len(data['outcomes'])})", expanded=False):
        outcome_rows = []
        for o in data["outcomes"]:
            source = "Auto" if o.get("auto_detected") else "Manual"
            confidence = o.get("detection_confidence", "")
            source_label = f"{source} ({confidence})" if confidence else source

            outcome_rows.append(
                {
                    "Ticker": o["ticker"],
                    "Company": _company_name(o["ticker"], o.get("company_name", "")),
                    "Event": o["event_type"],
                    "Date": o["event_date"],
                    "Outcome": o["outcome"],
                    "Source": source_label,
                    "Price Before (T-1)": f"${o['price_before']:.2f}"
                    if o.get("price_before") is not None
                    else "N/A",
                    "Price After (T+1)": f"${o['price_after']:.2f}"
                    if o.get("price_after") is not None
                    else "N/A",
                    "Return": f"{o['price_change_pct']:+.0%}"
                    if o.get("price_change_pct") is not None
                    else "N/A",
                }
            )
        st.dataframe(
            pd.DataFrame(outcome_rows), width="stretch", hide_index=True
        )

# --- Predictions awaiting outcome ---
outcome_keys = {(o["ticker"], o.get("event_date")) for o in data["outcomes"]}
outcome_tickers = {o["ticker"] for o in data["outcomes"]}
unpaired_preds = [
    p
    for p in data["predictions"]
    if (p["ticker"], p.get("catalyst_date")) not in outcome_keys
    and not (p.get("catalyst_date") is None and p["ticker"] in outcome_tickers)
]
if unpaired_preds:
    with st.expander(f"Awaiting Outcomes ({len(unpaired_preds)})", expanded=True):
        pred_rows = []
        for p in unpaired_preds:
            pred_rows.append(
                {
                    "Ticker": p["ticker"],
                    "Action": p["action"],
                    "Catalyst": p.get("next_catalyst", ""),
                    "Catalyst Date": p.get("catalyst_date") or "N/A",
                    "Science PTS": f"{p['science_pts']:.0%}",
                    "Market PTS": f"{p['market_pts']:.0%}",
                    "PTS Gap": f"{p['pts_gap']:+.2f}",
                    "Conviction": p["net_conviction"],
                    "Run": p["run_timestamp"][:10],
                }
            )
        st.dataframe(
            pd.DataFrame(pred_rows), width="stretch", hide_index=True
        )

# --- Unpaired outcomes ---
n_unpaired_outcomes = data["n_unpaired_outcomes"]
if n_unpaired_outcomes > 0:
    st.warning(
        f"{n_unpaired_outcomes} outcome(s) have no matching prediction. "
        "Run the pipeline to generate predictions for them."
    )

# --- Prediction timeline scatter ---
preds_with_dates = [p for p in data["predictions"] if p.get("catalyst_date")]
if preds_with_dates:
    st.subheader("Prediction Timeline")
    chart_data = pd.DataFrame(
        [
            {
                "Run Date": p["run_timestamp"][:10],
                "Catalyst Date": p["catalyst_date"],
                "Ticker": p["ticker"],
                "Action": p["action"],
            }
            for p in preds_with_dates
        ]
    )
    chart_data["Run Date"] = pd.to_datetime(chart_data["Run Date"])
    chart_data["Catalyst Date"] = pd.to_datetime(chart_data["Catalyst Date"])
    st.scatter_chart(chart_data, x="Run Date", y="Catalyst Date", color="Action", size=80)

# -------------------------------------------------------------------
# Auto-Cycle History (Phase 2)
# -------------------------------------------------------------------
st.divider()
st.subheader("Auto-Cycle History")

cycle_runs = get_cycle_runs(limit=10)
if cycle_runs:
    with st.expander(f"Recent Cycle Runs ({len(cycle_runs)})", expanded=True):
        cycle_rows = []
        for run in cycle_runs:
            started = run.get("started_at", "")[:19].replace("T", " ")
            duration = ""
            if run.get("completed_at") and run.get("started_at"):
                try:
                    t0 = datetime.fromisoformat(run["started_at"])
                    t1 = datetime.fromisoformat(run["completed_at"])
                    secs = (t1 - t0).total_seconds()
                    duration = f"{secs:.0f}s"
                except (ValueError, TypeError):
                    pass

            cycle_rows.append(
                {
                    "Time": started,
                    "Status": run.get("status", ""),
                    "Eligible": run.get("eligible_count", 0),
                    "Detected": run.get("detected_count", 0),
                    "Recorded": run.get("auto_recorded_count", 0),
                    "Flagged": run.get("flagged_count", 0),
                    "No Signal": run.get("no_signal_count", 0),
                    "Threshold": run.get("threshold", "HIGH"),
                    "Dry Run": "Yes" if run.get("dry_run") else "",
                    "Duration": duration,
                }
            )
        st.dataframe(
            pd.DataFrame(cycle_rows), width="stretch", hide_index=True
        )

        # Summary metrics
        total_runs = len(cycle_runs)
        total_recorded = sum(r.get("auto_recorded_count", 0) for r in cycle_runs)
        total_flagged = sum(r.get("flagged_count", 0) for r in cycle_runs)
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Runs", total_runs)
        m2.metric("Total Auto-Recorded", total_recorded)
        m3.metric("Total Flagged", total_flagged)
else:
    st.info(
        "No auto-cycle runs yet. "
        "The daily cron job will populate this after the first run."
    )

# --- Recent Detections ---
detections = get_detections(limit=30)
if detections:
    with st.expander(f"Recent Detections ({len(detections)})", expanded=False):
        # Filter controls
        det_statuses = sorted({d.get("status", "") for d in detections})
        if len(det_statuses) > 1:
            selected_det_status = st.multiselect(
                "Detection Status",
                det_statuses,
                default=det_statuses,
                key="det_status_filter",
            )
        else:
            selected_det_status = det_statuses

        det_rows = []
        for d in detections:
            if d.get("status") not in selected_det_status:
                continue

            status = d.get("status", "")
            status_icon = {
                "auto_recorded": "Auto",
                "flagged": "Flagged",
                "no_signal": "No Signal",
                "detected": "Detected",
                "approved": "Approved",
                "dismissed": "Dismissed",
            }.get(status, status)

            confidence = d.get("confidence") or ""
            sources = ", ".join(d.get("sources", []))
            evidence_list = d.get("evidence", [])
            evidence = evidence_list[0][:80] if evidence_list else ""

            det_rows.append(
                {
                    "Ticker": d.get("ticker", ""),
                    "Outcome": d.get("outcome") or "-",
                    "Confidence": confidence,
                    "Status": status_icon,
                    "Sources": sources,
                    "Evidence": evidence,
                    "Date": (d.get("created_at") or "")[:10],
                }
            )
        if det_rows:
            st.dataframe(
                pd.DataFrame(det_rows), width="stretch", hide_index=True
            )
        else:
            st.info("No detections match the selected filters.")
