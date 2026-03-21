"""Dataset — coverage summary and unpaired items."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from data_loader import get_company_profiles, get_eval_dataset

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
            outcome_rows.append(
                {
                    "Ticker": o["ticker"],
                    "Company": _company_name(o["ticker"], o.get("company_name", "")),
                    "Event": o["event_type"],
                    "Date": o["event_date"],
                    "Outcome": o["outcome"],
                    "Price Before (T-1)": f"${o['price_before']:.2f}",
                    "Price After (T+1)": f"${o['price_after']:.2f}",
                    "Return": f"{o['price_change_pct']:+.0%}",
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
                    "Catalyst Date": p.get("catalyst_date", "N/A"),
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
