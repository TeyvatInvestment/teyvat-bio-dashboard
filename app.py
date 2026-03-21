"""BioResearch Eval Dashboard — Streamlit application with authentication.

Deployed on Streamlit Community Cloud. Reads from Supabase.
Protected by streamlit-authenticator (cookie-based sessions).

Tabs:
  1. Watchlist — predictions with urgency status and live prices
  2. Scorecard — 6 core eval metrics and per-event breakdown
  3. Dataset  — coverage summary and unpaired items
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st
import streamlit_authenticator as stauth

from data_loader import (
    get_current_prices,
    get_eval_dataset,
    get_report_content,
    get_reports,
    record_outcome_from_ui,
)

# ---------------------------------------------------------------------------
# Page config (must be first st call)
# ---------------------------------------------------------------------------
st.set_page_config(page_title="BioResearch Eval", page_icon=":pill:", layout="wide")

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def _to_plain_dict(obj):
    """Recursively convert st.secrets AttrDict to plain mutable dicts/lists."""
    if hasattr(obj, "items"):
        return {k: _to_plain_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain_dict(v) for v in obj]
    return obj

# streamlit-authenticator mutates failed_login_attempts/logged_in fields,
# but st.secrets is read-only. Recursively convert to plain mutable dicts.
credentials = _to_plain_dict(st.secrets["credentials"])

authenticator = stauth.Authenticate(
    credentials,
    st.secrets["cookie"]["name"],
    st.secrets["cookie"]["key"],
    st.secrets["cookie"]["expiry_days"],
    auto_hash=False,
)

authenticator.login()

if st.session_state["authentication_status"] is False:
    st.error("Username/password is incorrect")
    st.stop()

if st.session_state["authentication_status"] is None:
    st.warning("Please enter your username and password")
    st.stop()

# ---------------------------------------------------------------------------
# Authenticated — show dashboard
# ---------------------------------------------------------------------------

# Track last refresh time
if "last_refreshed" not in st.session_state:
    st.session_state["last_refreshed"] = datetime.now()

with st.sidebar:
    st.write(f"Welcome, **{st.session_state['name']}**")
    authenticator.logout("Logout")
    st.divider()
    if st.button("Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.session_state["last_refreshed"] = datetime.now()
        st.rerun()
    st.caption(f"Last refreshed: {st.session_state['last_refreshed'].strftime('%Y-%m-%d %H:%M:%S')}")

st.title("BioResearch Eval Dashboard")

# ---------------------------------------------------------------------------
# Load data (cached indefinitely until manual refresh)
# ---------------------------------------------------------------------------
data = get_eval_dataset()

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_watchlist, tab_scorecard, tab_dataset, tab_reports = st.tabs(
    ["Watchlist", "Scorecard", "Dataset", "Reports"]
)

# ===========================================================================
# Tab 1: Watchlist
# ===========================================================================
with tab_watchlist:
    watchlist = data["watchlist"]

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
                        "Company": w.get("company_name", "") or w["ticker"],
                        "Action": w["action"],
                        "Catalyst Date": w["catalyst_date"] or "N/A",
                        "Days Until": str(w["days_until"]) if w["days_until"] is not None else "N/A",
                        "PTS Gap": f"{w['pts_gap']:+.2f}",
                        "Sci PTS": f"{w['science_pts']:.0%}",
                        "Mkt PTS": f"{w['market_pts']:.0%}",
                        "Conviction": w["net_conviction"],
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
        company = entry.get("company_name") or entry["ticker"]
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
    default_company = (prefill.get("company_name") or "") if prefill else ""
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

# ===========================================================================
# Tab 2: Scorecard
# ===========================================================================
with tab_scorecard:
    eval_result = data["eval_result"]
    n_paired = data["n_paired"]

    if n_paired == 0:
        st.info(
            "No paired events yet. Record outcomes using the form in the "
            "Watchlist tab, or via the CLI (`bioresearch eval record`)."
        )
    else:
        st.subheader(f"Core Metrics ({n_paired} paired events)")

        row1 = st.columns(3)
        row2 = st.columns(3)

        def _fmt_pct(v: float | None) -> str:
            return f"{v:.0%}" if v is not None else "N/A"

        def _fmt_float(v: float | None, decimals: int = 3) -> str:
            return f"{v:.{decimals}f}" if v is not None else "N/A"

        row1[0].metric(
            "Hit Rate",
            _fmt_pct(eval_result.get("hit_rate")),
            help="% of BUY recommendations with positive return",
        )
        row1[1].metric(
            "Avoidance Rate",
            _fmt_pct(eval_result.get("avoidance_rate")),
            help="% of PASS/MONITOR that avoided >20% loss",
        )
        row1[2].metric(
            "PTS Brier Score",
            _fmt_float(eval_result.get("pts_brier_score")),
            help="Lower = better calibrated (0.25 = random)",
        )

        row2[0].metric(
            "PTS Gap Spearman rho",
            _fmt_float(eval_result.get("pts_gap_spearman_rho")),
            help="Correlation between PTS gap and realized returns",
        )
        row2[1].metric(
            "rNPV Error",
            _fmt_pct(eval_result.get("rnpv_mean_error_pct")),
            help="Mean |rNPV - realized| / price_before",
        )
        row2[2].metric(
            "Risk Mgr Save Rate",
            _fmt_pct(eval_result.get("risk_manager_save_rate")),
            help="% of REJECTED avoiding >30% loss",
        )

        # --- Per-event breakdown ---
        st.subheader("Per-Event Breakdown")
        per_event = eval_result.get("per_event", [])
        if per_event:
            event_rows = []
            for e in per_event:
                if e.get("hit") is True:
                    verdict = "HIT"
                elif e.get("hit") is False:
                    verdict = "MISS"
                elif e.get("avoided") is True:
                    verdict = "AVOIDED"
                elif e.get("avoided") is False:
                    verdict = "MISSED OPP"
                else:
                    verdict = "N/A"

                event_rows.append(
                    {
                        "Ticker": e["ticker"],
                        "Event": e["event_type"],
                        "Outcome": e["outcome"],
                        "Return": f"{e['price_change_pct']:+.0%}",
                        "Action": e["action"],
                        "PTS Gap": f"{e['mean_pts_gap']:+.2f}",
                        "rNPV": f"${e['mean_rnpv']:.2f}",
                        "Conviction": f"{e['mean_conviction']:.1f}",
                        "Runs": e["n_runs"],
                        "Verdict": verdict,
                    }
                )
            st.dataframe(
                pd.DataFrame(event_rows), width="stretch", hide_index=True
            )

        # --- Stratified metrics ---
        stratified = eval_result.get("stratified")
        if stratified:
            st.subheader("Stratified Breakdown")

            by_type = stratified.get("by_event_type", [])
            if by_type:
                st.caption("By Event Type")
                type_rows = []
                for b in by_type:
                    type_rows.append(
                        {
                            "Event Type": b["bucket_name"],
                            "Events": b["n_events"],
                            "Hit Rate": _fmt_pct(b.get("hit_rate")),
                            "Avoidance": _fmt_pct(b.get("avoidance_rate")),
                            "Mean PTS Gap": f"{b['mean_pts_gap']:+.2f}",
                            "Mean Return": f"{b['mean_return']:+.0%}",
                        }
                    )
                st.dataframe(
                    pd.DataFrame(type_rows), width="stretch", hide_index=True
                )

            by_conv = stratified.get("by_conviction", [])
            if by_conv:
                st.caption("By Conviction Level")
                conv_rows = []
                for b in by_conv:
                    conv_rows.append(
                        {
                            "Conviction": b["bucket_name"],
                            "Events": b["n_events"],
                            "Hit Rate": _fmt_pct(b.get("hit_rate")),
                            "Avoidance": _fmt_pct(b.get("avoidance_rate")),
                            "Mean PTS Gap": f"{b['mean_pts_gap']:+.2f}",
                            "Mean Return": f"{b['mean_return']:+.0%}",
                        }
                    )
                st.dataframe(
                    pd.DataFrame(conv_rows), width="stretch", hide_index=True
                )

# ===========================================================================
# Tab 3: Dataset
# ===========================================================================
with tab_dataset:
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
                        "Company": o["company_name"],
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

# ===========================================================================
# Tab 4: Reports
# ===========================================================================
with tab_reports:
    st.subheader("Shared Research Reports")

    reports = get_reports()

    if not reports:
        st.info("No reports uploaded yet. Run `bioresearch analyze TICKER` to generate and share.")
    else:
        # --- Filter by ticker ---
        all_tickers = sorted({r["ticker"] for r in reports})
        selected_ticker = st.selectbox("Filter by ticker", ["All"] + all_tickers)
        if selected_ticker != "All":
            reports = [r for r in reports if r["ticker"] == selected_ticker]

        # --- Report list ---
        report_rows = []
        for r in reports:
            report_rows.append(
                {
                    "Ticker": r["ticker"],
                    "Company": r.get("company_name", ""),
                    "Action": r.get("action", "N/A"),
                    "Conviction": r.get("net_conviction", "N/A"),
                    "PTS Gap": f"{r['pts_gap']:+.2f}" if r.get("pts_gap") is not None else "N/A",
                    "Risk": r.get("risk_decision", "N/A"),
                    "Quality": f"{r['data_quality']:.2f}" if r.get("data_quality") else "N/A",
                    "Date": r["report_timestamp"][:10],
                    "Size": f"{r.get('file_size_bytes', 0) / 1024:.0f} KB",
                }
            )

        st.dataframe(pd.DataFrame(report_rows), width="stretch", hide_index=True)

        # --- Report viewer ---
        st.divider()
        report_options = {
            f"{r['ticker']} — {r['report_timestamp'][:10]}": r["storage_path"] for r in reports
        }
        selected_label = st.selectbox("Select report to view", list(report_options.keys()))

        if selected_label:
            storage_path = report_options[selected_label]
            try:
                content = get_report_content(storage_path)
                with st.expander("Full Report", expanded=True):
                    st.markdown(content)
            except Exception as exc:
                st.error(f"Failed to load report: {exc}")
