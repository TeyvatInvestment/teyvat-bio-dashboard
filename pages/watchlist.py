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

_filtered_tickers: set[str] = set()

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

    _filtered_tickers = {w["ticker"] for w in filtered}

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

        # Build latest prediction per ticker for accurate Price @ Pred
        _latest_pred: dict[str, dict] = {}
        for p in data["predictions"]:
            t = p["ticker"]
            if t not in _latest_pred or p["run_timestamp"] > _latest_pred[t]["run_timestamp"]:
                _latest_pred[t] = p

        rows = []
        for w in filtered:
            price_info = prices_map.get(w["ticker"])
            current_price = price_info["price"] if price_info else None
            _matched = _latest_pred.get(w["ticker"])
            pred_price = _matched["current_price"] if _matched else None

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
                    "Price @ Pred": f"${pred_price:.2f}" if pred_price is not None else "N/A",
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
# Execution Detail — binary decomposition + price levels for BUY picks
# -------------------------------------------------------------------
_buy_predictions = [
    p
    for p in data["predictions"]
    if p["action"] == "BUY"
    and p["risk_decision"] in ("APPROVED", "RESIZED")
    and p["ticker"] in _filtered_tickers
]
# Keep latest prediction per ticker
_latest_buy: dict[str, dict] = {}
for _p in _buy_predictions:
    _t = _p["ticker"]
    if _t not in _latest_buy or _p["run_timestamp"] > _latest_buy[_t]["run_timestamp"]:
        _latest_buy[_t] = _p

if _latest_buy:
    st.divider()
    st.subheader("Execution Detail")

    _buy_tickers = sorted(_latest_buy.keys())
    _ticker_labels = {
        f"{t} — {_company_name(t, _latest_buy[t].get('company_name', ''))}": t
        for t in _buy_tickers
    }
    _selected_label = st.selectbox(
        "Select position", list(_ticker_labels.keys()), key="exec_ticker"
    )
    _sel_ticker = _ticker_labels[_selected_label]
    _pred = _latest_buy[_sel_ticker]

    # Live price
    _exec_prices = get_current_prices((_sel_ticker,))
    _price_info = _exec_prices.get(_sel_ticker)
    _live = _price_info["price"] if _price_info else None
    _pred_price = _pred["current_price"]
    _ref = _live or _pred_price

    _success = _pred.get("success_price")
    _failure = _pred.get("failure_price")
    _sci_pts = _pred["science_pts"]
    _plan = _pred.get("execution_plan")

    # Header with live price
    _hdr_left, _hdr_right = st.columns(2)
    with _hdr_left:
        st.markdown("#### Binary Event Decomposition")
    with _hdr_right:
        if _live and _pred_price and _pred_price > 0:
            _delta = (_live - _pred_price) / _pred_price
            st.metric("Live Price", f"${_live:.2f}", f"{_delta:+.1%} since prediction")

    if _success and _failure and _ref and _ref > 0:
        # Compute decomposition
        _spread = _success - _failure
        _mip = max(0.0, min(1.0, (_ref - _failure) / _spread)) if _spread > 0 else 0.5
        _fv = _sci_pts * _success + (1 - _sci_pts) * _failure
        _fv_up = (_fv - _ref) / _ref
        _up = (_success - _ref) / _ref
        _down = (_failure - _ref) / _ref
        _rr = _up / abs(_down) if _down != 0 else 0.0

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Fair Value", f"${_fv:.2f}", f"{_fv_up:+.1%}")
        m2.metric("Risk/Reward", f"{_rr:.1f}x")
        m3.metric("Science PTS", f"{_sci_pts:.0%}")
        m4.metric("Market-Implied Prob", f"{_mip:.0%}", f"{(_sci_pts - _mip):+.0%} gap")

        # Price map
        _points = [
            (_failure, "Fail"),
            (_ref, "Now"),
            (_fv, "FV"),
            (_success, "Success"),
        ]
        if _pred.get("stop_loss_price"):
            _points.append((_pred["stop_loss_price"], "Stop"))
        if _pred.get("entry_price_limit"):
            _points.append((_pred["entry_price_limit"], "Entry"))
        _points.sort(key=lambda x: x[0])
        st.markdown(
            "  →  ".join(f"**{lbl}** ${px:.2f}" for px, lbl in _points)
        )

        # Price levels from full execution plan
        if _plan and _plan.get("price_levels"):
            st.markdown("##### Price Levels")
            _lvl_rows = []
            for lvl in _plan["price_levels"]:
                _lvl_price = lvl["price"]
                _dist = (_lvl_price - _ref) / _ref if _ref > 0 else 0
                _lvl_rows.append({
                    "Action": lvl["action"],
                    "Price": f"${_lvl_price:.2f}",
                    "Distance": f"{_dist:+.1%}",
                    "Size (% pos)": f"{lvl['size_pct_of_position']:.0f}%",
                    "Rationale": lvl["rationale"],
                })
            st.dataframe(
                pd.DataFrame(_lvl_rows), width="stretch", hide_index=True
            )

        # Scenario actions from full execution plan
        if _plan and _plan.get("scenario_actions"):
            st.markdown("##### Scenario Playbook")
            _sc_rows = []
            for sc in _plan["scenario_actions"]:
                _sc_rows.append({
                    "Trigger": sc["trigger"],
                    "Prob": f"{sc['probability']:.0%}",
                    "Action": sc["action"],
                    "Target": f"${sc['target_price']:.2f}",
                    "Rationale": sc["rationale"],
                })
            st.dataframe(
                pd.DataFrame(_sc_rows), width="stretch", hide_index=True
            )

        # Risk summary
        st.markdown("##### Risk & Sizing")
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Approved Size", f"{_pred['approved_size_pct']:.1f}% NAV")
        r3.metric("Conviction", f"{_pred['net_conviction']}/10")

        if _plan:
            _stop_type = _plan.get("stop_loss_type", "N/A")
            r2.metric("Stop Type", _stop_type)
            _max_loss = _plan.get("max_loss_pct_of_nav")
            r4.metric(
                "Max Loss (% NAV)",
                f"{_max_loss:.2%}" if _max_loss is not None else "N/A",
            )
        elif _pred.get("stop_loss_price") and _pred.get("entry_price_limit"):
            _ml = (
                _pred["approved_size_pct"]
                / 100
                * (_pred["entry_price_limit"] - _pred["stop_loss_price"])
                / _pred["entry_price_limit"]
            )
            r2.metric("Stop Type", "N/A")
            r4.metric("Max Loss (% NAV)", f"{_ml:.2%}")
        else:
            r2.metric("Stop Type", "N/A")
            r4.metric("Max Loss (% NAV)", "N/A")

        # Time management from full execution plan
        if _plan:
            _time_left, _time_right = st.columns(2)
            with _time_left:
                _rev = _plan.get("review_date")
                st.markdown(f"**Review Date:** {_rev or 'N/A'}")
                _ts = str(_plan.get('time_stop_action', 'N/A'))
                st.markdown(f"**Time Stop:** {_ts.replace('$', '\\$').replace('*', '\\*').replace('_', '\\_')}")
            with _time_right:
                _hedge = _plan.get("hedge_recommendation")
                if _hedge:
                    _h = str(_hedge).replace('$', '\\$').replace('*', '\\*').replace('_', '\\_')
                    st.markdown(f"**Hedge:** {_h}")
                _sr = str(_plan.get('sizing_rationale', 'N/A'))
                st.markdown(f"**Sizing Rationale:** {_sr.replace('$', '\\$').replace('*', '\\*').replace('_', '\\_')}")
    else:
        st.info(
            "Binary decomposition not available for this prediction. "
            "Older runs may not include success/failure prices."
        )

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
                    get_eval_dataset.clear()
                    st.session_state["last_refreshed"] = datetime.now()
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to record: {e}")
