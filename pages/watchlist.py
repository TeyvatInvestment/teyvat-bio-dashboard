"""Watchlist — predictions with urgency status and live prices."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

from data_loader import (
    get_company_profiles,
    get_current_prices,
    get_eval_dataset,
    record_outcome_from_ui,
)

data = get_eval_dataset()
watchlist = data["watchlist"]

# Company name resolution
_all_tickers = sorted(
    {w["ticker"] for w in watchlist}
    | {p["ticker"] for p in data["predictions"]}
    | {o["ticker"] for o in data["outcomes"]}
)
_profiles = get_company_profiles(tuple(_all_tickers)) if _all_tickers else {}


def _company_name(ticker: str, existing: str = "") -> str:
    return existing if existing else _profiles.get(ticker, ticker)


st.title("Watchlist")

if not watchlist:
    st.info("No predictions captured yet. Run the pipeline to generate predictions.")
else:
    # --- Sidebar filters ---
    with st.sidebar:
        st.header("Filters")
        all_statuses = sorted({w["status"] for w in watchlist})
        selected_statuses = st.multiselect("Status", all_statuses, default=all_statuses)
        all_actions = sorted({w["action"] for w in watchlist})
        selected_actions = st.multiselect("Action", all_actions, default=all_actions)
        min_conviction = st.slider("Min Conviction", 1, 10, 1)

    # --- Filter ---
    filtered = [
        w
        for w in watchlist
        if w["status"] in selected_statuses
        and w["action"] in selected_actions
        and w["net_conviction"] >= min_conviction
    ]

    if not filtered:
        st.warning("No entries match the current filters.")
    else:
        STATUS_LABELS = {
            "OVERDUE": "OVERDUE",
            "DUE_SOON": "DUE SOON",
            "UPCOMING": "UPCOMING",
            "RECORDED": "RECORDED",
            "UNKNOWN": "UNKNOWN",
        }

        # Batch fetch all prices in one API call
        all_tickers = tuple(sorted({w["ticker"] for w in filtered}))
        prices_map = get_current_prices(all_tickers)

        rows = []
        for w in filtered:
            price_info = prices_map.get(w["ticker"])
            current_price = price_info["price"] if price_info else None
            pred_price = None

            for p in data["predictions"]:
                if p["ticker"] == w["ticker"]:
                    pred_price = p["current_price"]
                    break

            price_delta = None
            if current_price is not None and pred_price is not None and pred_price > 0:
                price_delta = (current_price - pred_price) / pred_price

            rows.append(
                {
                    "Status": STATUS_LABELS.get(w["status"], w["status"]),
                    "Ticker": w["ticker"],
                    "Company": _company_name(w["ticker"], w.get("company_name", "")),
                    "Action": w["action"],
                    "Catalyst Date": w["catalyst_date"] or "N/A",
                    "Days Until": str(w["days_until"]) if w["days_until"] is not None else "N/A",
                    "PTS Gap": f"{w['pts_gap']:+.2f}",
                    "Sci PTS": f"{w['science_pts']:.0%}",
                    "Mkt PTS": f"{w['market_pts']:.0%}",
                    "Conviction": w["net_conviction"],
                    "Success Price": f"${w['success_price']:.2f}" if w.get("success_price") else "N/A",
                    "Failure Price": f"${w['failure_price']:.2f}" if w.get("failure_price") else "N/A",
                    "rNPV Price": f"${w['rnpv_per_share']:.2f}" if w.get("rnpv_per_share") else "N/A",
                    "Price @ Pred": f"${pred_price:.2f}" if pred_price else "N/A",
                    "Current Price": f"${current_price:.2f}" if current_price else "N/A",
                    "Price Change": f"{price_delta:+.1%}"
                    if price_delta is not None
                    else "N/A",
                    "Run Date": w["run_date"],
                }
            )

        df = pd.DataFrame(rows)
        st.dataframe(df, width="stretch", hide_index=True)

        st.caption(
            f"Prices fetched from FMP. "
            f"Last refresh: {st.session_state['last_refreshed'].strftime('%Y-%m-%d %H:%M')}. "
            f"Use the Refresh Data button in the sidebar to update."
        )

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Tracked", len(filtered))
        overdue = sum(1 for w in filtered if w["status"] == "OVERDUE")
        col2.metric("Overdue", overdue)
        due_soon = sum(1 for w in filtered if w["status"] == "DUE_SOON")
        col3.metric("Due Soon", due_soon)
        buys = sum(1 for w in filtered if w["action"] == "BUY")
        col4.metric("BUY Signals", buys)

# -------------------------------------------------------------------
# Record Outcome — pair predictions with actual catalyst results
# -------------------------------------------------------------------
st.divider()
st.subheader("Record Outcome")

# Show success/error from previous submission (persisted via session_state)
if st.session_state.get("_record_success"):
    st.success(st.session_state.pop("_record_success"))
    for w in st.session_state.pop("_record_warnings", []):
        st.warning(w)

OUTCOMES_LIST = ["APPROVED", "CRL", "MET_ENDPOINT", "FAILED", "DELAYED"]
EVENT_TYPES_LIST = ["PDUFA", "Phase3_Readout", "AdCom", "NDA", "EarningsReadout"]

# Pre-fill options from OVERDUE watchlist entries
overdue_entries = [w for w in watchlist if w["status"] == "OVERDUE"]
prefill_options: dict[str, dict | None] = {"-- Manual entry --": None}
for entry in overdue_entries:
    company = _company_name(entry["ticker"], entry.get("company_name", ""))
    label = f"{entry['ticker']} \u2014 {company} (catalyst: {entry['catalyst_date'] or 'N/A'})"
    prefill_options[label] = entry

if overdue_entries:
    selected_label = st.selectbox(
        "Pre-fill from OVERDUE watchlist",
        list(prefill_options.keys()),
        help="Select an overdue entry to pre-fill the form, or choose manual entry.",
    )
    prefill = prefill_options[selected_label]
else:
    prefill = None

# Compute form defaults from prefill
default_ticker = prefill["ticker"] if prefill else ""
default_company = _company_name(prefill["ticker"], prefill.get("company_name", "")) if prefill else ""
if prefill and prefill.get("catalyst_date"):
    try:
        default_date = date.fromisoformat(str(prefill["catalyst_date"]))
    except (ValueError, TypeError):
        default_date = date.today()
else:
    default_date = date.today()

with st.form("record_outcome_form", clear_on_submit=True):
    col_left, col_right = st.columns(2)

    with col_left:
        rec_ticker = st.text_input("Ticker", value=default_ticker)
        rec_date = st.date_input("Event Date", value=default_date)
        rec_outcome = st.selectbox("Outcome", OUTCOMES_LIST)

    with col_right:
        rec_company = st.text_input(
            "Company Name",
            value=default_company,
            help="Optional. Auto-resolved from predictions if empty.",
        )
        rec_event_type = st.selectbox("Event Type", EVENT_TYPES_LIST)
        rec_notes = st.text_input("Notes (optional)")

    with st.expander("Manual Price Overrides"):
        st.caption(
            "Leave at 0 to auto-fetch from FMP. "
            "Set positive values to override."
        )
        price_col1, price_col2 = st.columns(2)
        rec_price_before = price_col1.number_input(
            "Price Before (T\u22121)", min_value=0.0, value=0.0,
            step=0.01, format="%.2f",
        )
        rec_price_after = price_col2.number_input(
            "Price After (T+1)", min_value=0.0, value=0.0,
            step=0.01, format="%.2f",
        )

    submitted = st.form_submit_button("Record Outcome", type="primary")

    if submitted:
        if not rec_ticker.strip():
            st.error("Ticker is required.")
        else:
            with st.spinner("Fetching prices and recording outcome..."):
                try:
                    result = record_outcome_from_ui(
                        ticker=rec_ticker.strip().upper(),
                        event_type=rec_event_type,
                        event_date=rec_date,
                        outcome=rec_outcome,
                        company_name=rec_company.strip() or None,
                        notes=rec_notes.strip() or None,
                        price_before_override=(
                            rec_price_before if rec_price_before > 0 else None
                        ),
                        price_after_override=(
                            rec_price_after if rec_price_after > 0 else None
                        ),
                    )
                    outcome_data = result["outcome"]
                    pct = outcome_data["price_change_pct"]
                    st.session_state["_record_success"] = (
                        f"Recorded: {outcome_data['ticker']} "
                        f"{outcome_data['event_type']} on "
                        f"{outcome_data['event_date']} "
                        f"\u2192 {outcome_data['outcome']} "
                        f"(return: {pct:+.1%})"
                    )
                    st.session_state["_record_warnings"] = result["warnings"]
                    st.cache_data.clear()
                    st.session_state["last_refreshed"] = datetime.now()
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to record: {e}")
