"""Experiments — unified experiment lifecycle monitoring.

Shows all experiments (active and completed) organized by urgency.
Each experiment tracks a pipeline prediction through catalyst resolution to scoring.
"""

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

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

data = get_eval_dataset()
watchlist = data["watchlist"]
predictions = data["predictions"]
outcomes = data["outcomes"]
eval_result = data["eval_result"]
per_event = eval_result.get("per_event", [])

# Company name resolution
_all_tickers = sorted(
    {w["ticker"] for w in watchlist}
    | {p["ticker"] for p in predictions}
    | {o["ticker"] for o in outcomes}
)
_profiles = get_company_profiles(tuple(_all_tickers)) if _all_tickers else {}


def _company(ticker: str, existing: str = "") -> str:
    return existing if existing else _profiles.get(ticker, ticker)


# Verdict lookup for completed experiments (from eval scoring)
_verdict_map: dict[str, dict] = {}
for _ev in per_event:
    _verdict_map[_ev["ticker"]] = _ev

# Most recent prediction per ticker (for execution detail)
_latest_pred: dict[str, dict] = {}
for _p in sorted(predictions, key=lambda x: x["run_timestamp"], reverse=True):
    if _p["ticker"] not in _latest_pred:
        _latest_pred[_p["ticker"]] = _p

# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.title("Experiments")

if not watchlist:
    st.info("No experiments yet. Run the pipeline to generate predictions.")
    st.stop()

# --- Summary metrics ---
_n_total = len(watchlist)
_n_attention = sum(1 for w in watchlist if w["status"] in ("OVERDUE", "DUE_SOON"))
_n_active = sum(1 for w in watchlist if w["status"] in ("UPCOMING", "UNKNOWN"))
_n_completed = sum(1 for w in watchlist if w["status"] == "RECORDED")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total", _n_total)
c2.metric("Needs Attention", _n_attention)
c3.metric("Active", _n_active)
c4.metric("Completed", _n_completed)

# --- Sidebar filters ---
with st.sidebar:
    st.header("Filters")
    _all_statuses = sorted({w["status"] for w in watchlist})
    _status_labels = {
        "OVERDUE": "Overdue",
        "DUE_SOON": "Due Soon",
        "UPCOMING": "Upcoming",
        "RECORDED": "Completed",
        "UNKNOWN": "Unknown",
    }
    _sel_statuses = st.multiselect(
        "Status",
        _all_statuses,
        default=_all_statuses,
        format_func=lambda s: _status_labels.get(s, s),
    )
    _all_actions = sorted({w["action"] for w in watchlist})
    _sel_actions = st.multiselect("Action", _all_actions, default=_all_actions)

# --- Batch fetch live prices ---
_price_tickers = tuple(sorted({w["ticker"] for w in watchlist}))
_prices = get_current_prices(_price_tickers) if _price_tickers else {}

# --- Build & sort experiment list ---
_STATUS_ORDER = {"OVERDUE": 0, "DUE_SOON": 1, "UPCOMING": 2, "UNKNOWN": 3, "RECORDED": 4}

filtered = [
    w
    for w in watchlist
    if w["status"] in _sel_statuses and w["action"] in _sel_actions
]
filtered.sort(
    key=lambda w: (_STATUS_ORDER.get(w["status"], 99), w.get("days_until") or 9999)
)

if not filtered:
    st.warning("No experiments match the current filters.")
    st.stop()

# --- Experiment table ---
_STATUS_DISPLAY = {
    "OVERDUE": "OVERDUE",
    "DUE_SOON": "DUE SOON",
    "UPCOMING": "UPCOMING",
    "RECORDED": "COMPLETED",
    "UNKNOWN": "UNKNOWN",
}

rows = []
for w in filtered:
    tk = w["ticker"]
    pi = _prices.get(tk)
    live = pi["price"] if pi else None
    pred_price = w.get("current_price_at_pred")

    since_pred = None
    if live and pred_price and pred_price > 0:
        since_pred = (live - pred_price) / pred_price

    # Result column for completed experiments
    result = ""
    verdict = _verdict_map.get(tk)
    if verdict:
        outcome = verdict["outcome"]
        ret = verdict["price_change_pct"]
        if verdict.get("hit") is True:
            result = f"HIT: {outcome} ({ret:+.0%})"
        elif verdict.get("hit") is False:
            result = f"MISS: {outcome} ({ret:+.0%})"
        elif verdict.get("avoided") is True:
            result = f"AVOIDED: {outcome} ({ret:+.0%})"
        elif verdict.get("avoided") is False:
            result = f"MISSED OPP: {outcome} ({ret:+.0%})"
        else:
            result = f"{outcome} ({ret:+.0%})"

    rows.append(
        {
            "Status": _STATUS_DISPLAY.get(w["status"], w["status"]),
            "Ticker": tk,
            "Company": _company(tk, w.get("company_name", "")),
            "Analyzed": w.get("run_timestamp", "")[:16].replace("T", " "),
            "Action": w["action"],
            "Catalyst": w["catalyst_date"] or "TBD",
            "Days": str(w["days_until"]) if w.get("days_until") is not None else "",
            "PTS Gap": f"{w['pts_gap']:+.2f}",
            "Conv": w["net_conviction"],
            "Price@Pred": f"${pred_price:.2f}" if pred_price else "",
            "Current": f"${live:.2f}" if live else "",
            "Since Pred": f"{since_pred:+.1%}" if since_pred is not None else "",
            "Result": result,
        }
    )

st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
st.caption(
    f"Prices from FMP. "
    f"Refreshed: {st.session_state['last_refreshed'].strftime('%H:%M')}. "
    f"Click Refresh Data in sidebar to update."
)


# ===================================================================
# Experiment Detail
# ===================================================================
st.divider()
st.subheader("Experiment Detail")

# Build labels for selectbox
_detail_labels: dict[str, dict] = {}
for _w in filtered:
    _tk = _w["ticker"]
    _co = _company(_tk, _w.get("company_name", ""))
    _st_short = _STATUS_DISPLAY.get(_w["status"], _w["status"])
    _label = f"{_tk} \u2014 {_co} ({_st_short})"
    _detail_labels[_label] = _w

_selected = st.selectbox("Select experiment", list(_detail_labels.keys()))
_exp = _detail_labels[_selected]
_tk = _exp["ticker"]
_pred = _latest_pred.get(_tk)
_verdict = _verdict_map.get(_tk)

# Live price context
_pi = _prices.get(_tk)
_live = _pi["price"] if _pi else None
_ref = _live or (_pred["current_price"] if _pred else None)

# --- Verdict (for completed experiments) ---
if _verdict:
    st.markdown("#### Result")
    _v1, _v2, _v3, _v4 = st.columns(4)
    _v1.metric("Outcome", _verdict["outcome"])
    _v2.metric("Return", f"{_verdict['price_change_pct']:+.1%}")

    if _verdict.get("hit") is True:
        _v3.metric("Verdict", "HIT")
    elif _verdict.get("hit") is False:
        _v3.metric("Verdict", "MISS")
    elif _verdict.get("avoided") is True:
        _v3.metric("Verdict", "AVOIDED")
    elif _verdict.get("avoided") is False:
        _v3.metric("Verdict", "MISSED OPP")
    else:
        _v3.metric("Verdict", "N/A")

    _v4.metric("Runs Scored", _verdict["n_runs"])

# --- Binary Decomposition ---
if (
    _pred
    and _pred.get("success_price")
    and _pred.get("failure_price")
    and _ref
    and _ref > 0
):
    _success = _pred["success_price"]
    _failure = _pred["failure_price"]
    _sci_pts = _pred["science_pts"]
    _plan = _pred.get("execution_plan")

    _spread = _success - _failure
    _mip = (
        max(0.0, min(1.0, (_ref - _failure) / _spread)) if _spread > 0 else 0.5
    )
    _fv = _sci_pts * _success + (1 - _sci_pts) * _failure
    _fv_up = (_fv - _ref) / _ref
    _up = (_success - _ref) / _ref
    _down = (_failure - _ref) / _ref
    _rr = _up / abs(_down) if _down != 0 else 0.0

    st.markdown("#### Binary Event Decomposition")

    _hdr_left, _hdr_right = st.columns(2)
    with _hdr_right:
        if _live and _pred["current_price"] and _pred["current_price"] > 0:
            _delta = (_live - _pred["current_price"]) / _pred["current_price"]
            st.metric(
                "Live Price", f"${_live:.2f}", f"{_delta:+.1%} since prediction"
            )

    _m1, _m2, _m3, _m4 = st.columns(4)
    _m1.metric("Fair Value", f"${_fv:.2f}", f"{_fv_up:+.1%}")
    _m2.metric("Risk/Reward", f"{_rr:.1f}x")
    _m3.metric("Science PTS", f"{_sci_pts:.0%}")
    _m4.metric("Market-Implied Prob", f"{_mip:.0%}", f"{(_sci_pts - _mip):+.0%} gap")

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
        "  \u2192  ".join(f"**{lbl}** \\${px:.2f}" for px, lbl in _points)
    )

    # Price levels from execution plan
    if _plan and _plan.get("price_levels"):
        st.markdown("##### Price Levels")
        _lvl_rows = []
        for lvl in _plan["price_levels"]:
            _lp = lvl["price"]
            _dist = (_lp - _ref) / _ref if _ref > 0 else 0
            _lvl_rows.append(
                {
                    "Action": lvl["action"],
                    "Price": f"${_lp:.2f}",
                    "Distance": f"{_dist:+.1%}",
                    "Size": f"{lvl['size_pct_of_position']:.0f}%",
                    "Rationale": lvl["rationale"],
                }
            )
        st.dataframe(pd.DataFrame(_lvl_rows), width="stretch", hide_index=True)

    # Scenario actions
    if _plan and _plan.get("scenario_actions"):
        st.markdown("##### Scenario Playbook")
        _sc_rows = []
        for sc in _plan["scenario_actions"]:
            _sc_rows.append(
                {
                    "Trigger": sc["trigger"],
                    "Prob": f"{sc['probability']:.0%}",
                    "Action": sc["action"],
                    "Target": f"${sc['target_price']:.2f}",
                    "Rationale": sc["rationale"],
                }
            )
        st.dataframe(pd.DataFrame(_sc_rows), width="stretch", hide_index=True)

    # Risk & Sizing
    st.markdown("##### Risk & Sizing")
    _r1, _r2, _r3, _r4 = st.columns(4)
    _r1.metric("Approved Size", f"{_pred['approved_size_pct']:.1f}% NAV")
    _r3.metric("Conviction", f"{_pred['net_conviction']}/10")

    if _plan:
        _stop_type = _plan.get("stop_loss_type", "N/A")
        _r2.metric("Stop Type", _stop_type)
        _max_loss = _plan.get("max_loss_pct_of_nav")
        _r4.metric(
            "Max Loss (% NAV)",
            f"{_max_loss:.2%}" if _max_loss is not None else "N/A",
        )

        _tl, _tr = st.columns(2)
        with _tl:
            _rev = _plan.get("review_date")
            st.markdown(f"**Review Date:** {_rev or 'N/A'}")
            _ts = str(_plan.get("time_stop_action", "N/A"))
            _ts_esc = _ts.replace("$", "\\$").replace("*", "\\*").replace("_", "\\_")
            st.markdown(f"**Time Stop:** {_ts_esc}")
        with _tr:
            _hedge = _plan.get("hedge_recommendation")
            if _hedge:
                _h = str(_hedge).replace("$", "\\$").replace("*", "\\*").replace("_", "\\_")
                st.markdown(f"**Hedge:** {_h}")
            _sr = str(_plan.get("sizing_rationale", "N/A"))
            _sr_esc = _sr.replace("$", "\\$").replace("*", "\\*").replace("_", "\\_")
            st.markdown(f"**Sizing Rationale:** {_sr_esc}")
    elif _pred.get("stop_loss_price") and _pred.get("entry_price_limit"):
        _ml = (
            _pred["approved_size_pct"]
            / 100
            * (_pred["entry_price_limit"] - _pred["stop_loss_price"])
            / _pred["entry_price_limit"]
        )
        _r2.metric("Stop Type", "N/A")
        _r4.metric("Max Loss (% NAV)", f"{_ml:.2%}")
    else:
        _r2.metric("Stop Type", "N/A")
        _r4.metric("Max Loss (% NAV)", "N/A")

elif _pred:
    st.info(
        "Binary decomposition not available for this prediction. "
        "Older runs may not include success/failure prices."
    )


# ===================================================================
# Record Outcome
# ===================================================================
st.divider()
st.subheader("Record Outcome")

# Show success from previous submission
if st.session_state.get("_record_success"):
    st.success(st.session_state.pop("_record_success"))
    for _rw in st.session_state.pop("_record_warnings", []):
        st.warning(_rw)

OUTCOMES_LIST = ["APPROVED", "CRL", "MET_ENDPOINT", "FAILED", "DELAYED"]
EVENT_TYPES_LIST = ["PDUFA", "Phase3_Readout", "AdCom", "NDA", "EarningsReadout"]

# Pre-fill options from OVERDUE entries
_overdue = [w for w in watchlist if w["status"] == "OVERDUE"]
_prefill_opts: dict[str, dict | None] = {"\u2014 Manual entry \u2014": None}
for _ow in _overdue:
    _ow_co = _company(_ow["ticker"], _ow.get("company_name", ""))
    _ow_label = (
        f"{_ow['ticker']} \u2014 {_ow_co} (catalyst: {_ow['catalyst_date'] or 'N/A'})"
    )
    _prefill_opts[_ow_label] = _ow

if _overdue:
    _sel_prefill = st.selectbox(
        "Pre-fill from overdue experiments",
        list(_prefill_opts.keys()),
        help="Select an overdue entry to pre-fill the form.",
    )
    _prefill = _prefill_opts[_sel_prefill]
else:
    _prefill = None

_def_ticker = _prefill["ticker"] if _prefill else ""
_def_company = (
    _company(_prefill["ticker"], _prefill.get("company_name", ""))
    if _prefill
    else ""
)
if _prefill and _prefill.get("catalyst_date"):
    try:
        _def_date = date.fromisoformat(str(_prefill["catalyst_date"]))
    except (ValueError, TypeError):
        _def_date = date.today()
else:
    _def_date = date.today()

with st.form("record_outcome_form", clear_on_submit=True):
    _fl, _fr = st.columns(2)

    with _fl:
        _rec_ticker = st.text_input("Ticker", value=_def_ticker)
        _rec_date = st.date_input("Event Date", value=_def_date)
        _rec_outcome = st.selectbox("Outcome", OUTCOMES_LIST)

    with _fr:
        _rec_company = st.text_input(
            "Company Name",
            value=_def_company,
            help="Optional. Auto-resolved from predictions if empty.",
        )
        _rec_etype = st.selectbox("Event Type", EVENT_TYPES_LIST)
        _rec_notes = st.text_input("Notes (optional)")

    with st.expander("Manual Price Overrides"):
        st.caption("Leave at 0 to auto-fetch from FMP. Set positive values to override.")
        _pc1, _pc2 = st.columns(2)
        _rec_pb = _pc1.number_input(
            "Price Before (T\u22121)",
            min_value=0.0,
            value=0.0,
            step=0.01,
            format="%.2f",
        )
        _rec_pa = _pc2.number_input(
            "Price After (T+1)",
            min_value=0.0,
            value=0.0,
            step=0.01,
            format="%.2f",
        )

    _submitted = st.form_submit_button("Record Outcome", type="primary")

    if _submitted:
        if not _rec_ticker.strip():
            st.error("Ticker is required.")
        else:
            with st.spinner("Fetching prices and recording outcome..."):
                try:
                    _result = record_outcome_from_ui(
                        ticker=_rec_ticker.strip().upper(),
                        event_type=_rec_etype,
                        event_date=_rec_date,
                        outcome=_rec_outcome,
                        company_name=_rec_company.strip() or None,
                        notes=_rec_notes.strip() or None,
                        price_before_override=(
                            _rec_pb if _rec_pb > 0 else None
                        ),
                        price_after_override=(
                            _rec_pa if _rec_pa > 0 else None
                        ),
                    )
                    _od = _result["outcome"]
                    _pct = _od["price_change_pct"]
                    st.session_state["_record_success"] = (
                        f"Recorded: {_od['ticker']} {_od['event_type']} on "
                        f"{_od['event_date']} \u2192 {_od['outcome']} "
                        f"(return: {_pct:+.1%})"
                    )
                    st.session_state["_record_warnings"] = _result["warnings"]
                    get_eval_dataset.clear()
                    st.session_state["last_refreshed"] = datetime.now()
                    st.rerun()
                except Exception as _e:
                    st.error(f"Failed to record: {_e}")

# ------------------------------------------------------------------
# Price Evolution of Recorded Outcomes
# ------------------------------------------------------------------

st.divider()
st.subheader("Outcome Price Evolution")
st.caption(
    "Price change (%) from T-1 baseline across recorded outcomes. "
    "Lines grow as T+7/T+14/T+30 prices are backfilled."
)

from data_loader import get_outcome_price_evolution

price_evo = get_outcome_price_evolution()

if not price_evo:
    st.info("No outcome price data available yet. Record outcomes to see price evolution.")
else:
    # Filter options
    outcomes_list = sorted(set(e["outcome"] for e in price_evo))
    selected_outcomes = st.multiselect(
        "Filter by outcome",
        outcomes_list,
        default=outcomes_list,
        key="price_evo_outcome_filter",
    )

    filtered_evo = [e for e in price_evo if e["outcome"] in selected_outcomes]

    if filtered_evo:
        # Build chart data: each row is a time point for a specific outcome
        time_points = ["T-1", "T=0", "T+1", "T+7", "T+14", "T+30"]
        chart_rows = []
        for entry in filtered_evo:
            label = f"{entry['ticker']} ({entry['outcome']})"
            for tp in time_points:
                if tp in entry:
                    chart_rows.append({
                        "Time": tp,
                        "Change %": entry[tp],
                        "Outcome": label,
                    })

        if chart_rows:
            import altair as alt

            chart_df = pd.DataFrame(chart_rows)

            # Determine which time points are actually present, in correct order
            time_order = [t for t in time_points if t in chart_df["Time"].values]

            chart = alt.Chart(chart_df).mark_line(point=True).encode(
                x=alt.X("Time:N", sort=time_order, title=""),
                y=alt.Y("Change %:Q", title="Price Change (%)"),
                color=alt.Color("Outcome:N", title=""),
            )
            st.altair_chart(chart, width="stretch")

            # Summary table
            with st.expander("Outcome Details", expanded=False):
                detail_rows = []
                for entry in filtered_evo:
                    row = {
                        "Ticker": entry["ticker"],
                        "Date": entry["event_date"],
                        "Outcome": entry["outcome"],
                        "Type": entry["event_type"],
                        "T+1": f"{entry.get('T+1', 'N/A'):.1f}%" if isinstance(entry.get("T+1"), (int, float)) else "—",
                        "T+7": f"{entry.get('T+7', 'N/A'):.1f}%" if isinstance(entry.get("T+7"), (int, float)) else "—",
                        "T+14": f"{entry.get('T+14', 'N/A'):.1f}%" if isinstance(entry.get("T+14"), (int, float)) else "—",
                        "T+30": f"{entry.get('T+30', 'N/A'):.1f}%" if isinstance(entry.get("T+30"), (int, float)) else "—",
                    }
                    detail_rows.append(row)

                st.dataframe(pd.DataFrame(detail_rows), width="stretch", hide_index=True)
    else:
        st.info("No outcomes match the selected filters.")
