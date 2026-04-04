"""BioResearch Eval Dashboard — Streamlit multi-page application.

Deployed on Streamlit Community Cloud. Reads from Supabase.
Protected by streamlit-authenticator (cookie-based sessions).

Pages:
  Monitoring:
    1. Experiments     — experiment lifecycle tracking (active + completed)
    2. Scorecard       — aggregate eval metrics and per-event breakdown
  Portfolio:
    3. Portfolio       — paper portfolio holdings, P&L, exposure, NAV tracking
  Data & Reports:
    4. Reports         — shared research reports
    5. Dataset         — raw data, auto-cycle history, detections
  Workflow:
    6. Review Queue    — confirm or dismiss auto-detected outcomes
    7. Request Report  — submit a research report request
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st
import streamlit_authenticator as stauth

from cookie_patch import patch_cookie_model

patch_cookie_model()  # Must run before Authenticate() — replaces iframe cookie with native JS

from data_loader import (
    get_all_portfolio_snapshots,
    get_current_prices,
    get_detection_map,
    get_detections,
    get_eval_dataset,
    fetch_monitoring_prices,
    get_outcome_price_evolution,
    get_portfolio_comparison_metrics,
    get_portfolio_list,
    get_portfolio_snapshots,
    get_portfolio_state,
    get_portfolio_trades,
    get_report_requests,
    get_reports,
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
    login_sleep_time=0,  # No sleep needed — native cookie read is instant
)

authenticator.login()

if st.session_state["authentication_status"] is False:
    st.error("Username/password is incorrect")
    st.stop()

if st.session_state["authentication_status"] is None:
    st.warning("Please enter your username and password")
    st.stop()

# ---------------------------------------------------------------------------
# Authenticated — shared sidebar + navigation
# ---------------------------------------------------------------------------

# Track last refresh time
if "last_refreshed" not in st.session_state:
    st.session_state["last_refreshed"] = datetime.now()

with st.sidebar:
    st.write(f"Welcome, **{st.session_state['name']}**")
    authenticator.logout("Logout")
    st.divider()
    if st.button("Refresh Data", width="stretch"):
        get_eval_dataset.clear()
        get_current_prices.clear()
        get_reports.clear()
        get_report_requests.clear()
        get_detections.clear()
        get_detection_map.clear()
        fetch_monitoring_prices.clear()
        get_portfolio_list.clear()
        get_portfolio_state.clear()
        get_portfolio_trades.clear()
        get_portfolio_snapshots.clear()
        get_all_portfolio_snapshots.clear()
        get_portfolio_comparison_metrics.clear()
        get_outcome_price_evolution.clear()
        st.session_state["last_refreshed"] = datetime.now()
        st.rerun()
    st.caption(f"Last refreshed: {st.session_state['last_refreshed'].strftime('%Y-%m-%d %H:%M:%S')}")

# ---------------------------------------------------------------------------
# Multi-page navigation
# ---------------------------------------------------------------------------
pg = st.navigation(
    {
        "Monitoring": [
            st.Page("views/experiments.py", title="Experiments", icon=":material/science:", default=True),
            st.Page("views/scorecard.py", title="Scorecard", icon=":material/assessment:"),
        ],
        "Portfolio": [
            st.Page("views/portfolio.py", title="Portfolio", icon=":material/account_balance:"),
        ],
        "Data & Reports": [
            st.Page("views/reports.py", title="Reports", icon=":material/description:"),
            st.Page("views/dataset.py", title="Dataset", icon=":material/database:"),
        ],
        "Workflow": [
            st.Page("views/review_queue.py", title="Review Queue", icon=":material/checklist:"),
            st.Page("views/request_report.py", title="Request Report", icon=":material/add_circle:"),
        ],
    }
)

pg.run()
