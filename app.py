"""BioResearch Eval Dashboard — Streamlit application with authentication.

Deployed on Streamlit Community Cloud. Reads from Supabase.
Protected by streamlit-authenticator (cookie-based sessions).

Tabs:
  1. Watchlist — predictions with urgency status and live prices
  2. Scorecard — 6 core eval metrics and per-event breakdown
  3. Dataset  — coverage summary and unpaired items
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st
import streamlit_authenticator as stauth

from data_loader import get_current_price, get_eval_dataset, get_report_content, get_reports

# ---------------------------------------------------------------------------
# Page config (must be first st call)
# ---------------------------------------------------------------------------
st.set_page_config(page_title="BioResearch Eval", page_icon=":pill:", layout="wide")

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
authenticator = stauth.Authenticate(
    dict(st.secrets["credentials"]),
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
with st.sidebar:
    st.write(f"Welcome, **{st.session_state['name']}**")
    authenticator.logout("Logout")

st.title("BioResearch Eval Dashboard")

# ---------------------------------------------------------------------------
# Load data (cached 5 min)
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

            rows = []
            for w in filtered:
                price_info = get_current_price(w["ticker"])
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
                        "Days Until": w["days_until"] if w["days_until"] is not None else "N/A",
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
            st.dataframe(df, use_container_width=True, hide_index=True)

            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            st.caption(
                f"Current prices fetched from yfinance (cached 10 min). "
                f"Last refresh: {now}. "
                f"Prediction prices captured at each run's timestamp."
            )

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Tracked", len(filtered))
            overdue = sum(1 for w in filtered if w["status"] == "OVERDUE")
            col2.metric("Overdue", overdue)
            due_soon = sum(1 for w in filtered if w["status"] == "DUE_SOON")
            col3.metric("Due Soon", due_soon)
            buys = sum(1 for w in filtered if w["action"] == "BUY")
            col4.metric("BUY Signals", buys)

# ===========================================================================
# Tab 2: Scorecard
# ===========================================================================
with tab_scorecard:
    eval_result = data["eval_result"]
    n_paired = data["n_paired"]

    if n_paired == 0:
        st.info(
            "No paired events yet. Record outcomes with "
            "`bioresearch eval record TICKER --event-date DATE --outcome OUTCOME --event-type TYPE`."
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
                pd.DataFrame(event_rows), use_container_width=True, hide_index=True
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
                    pd.DataFrame(type_rows), use_container_width=True, hide_index=True
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
                    pd.DataFrame(conv_rows), use_container_width=True, hide_index=True
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
                pd.DataFrame(outcome_rows), use_container_width=True, hide_index=True
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
                pd.DataFrame(pred_rows), use_container_width=True, hide_index=True
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

        st.dataframe(pd.DataFrame(report_rows), use_container_width=True, hide_index=True)

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
