"""BioResearch Eval Dashboard — Streamlit multi-page application.

Deployed on Streamlit Community Cloud. Reads from Supabase.
Protected by streamlit-authenticator (cookie-based sessions).

Pages:
  1. Watchlist        — predictions with urgency status and live prices
  2. Scorecard        — 6 core eval metrics and per-event breakdown
  3. Dataset          — coverage summary and unpaired items
  4. Portfolio        — paper portfolio holdings, P&L, exposure, NAV tracking
  5. Reports          — shared research reports
  6. Request Report   — submit a research report request
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st
import streamlit_authenticator as stauth

from data_loader import (
    get_all_portfolio_snapshots,
    get_current_prices,
    get_eval_dataset,
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
    if st.button("Refresh Data", use_container_width=True):
        get_eval_dataset.clear()
        get_current_prices.clear()
        get_reports.clear()
        get_report_requests.clear()
        get_portfolio_list.clear()
        get_portfolio_state.clear()
        get_portfolio_trades.clear()
        get_portfolio_snapshots.clear()
        get_all_portfolio_snapshots.clear()
        st.session_state["last_refreshed"] = datetime.now()
        st.rerun()
    st.caption(f"Last refreshed: {st.session_state['last_refreshed'].strftime('%Y-%m-%d %H:%M:%S')}")

# ---------------------------------------------------------------------------
# Multi-page navigation
# ---------------------------------------------------------------------------
pg = st.navigation(
    {
        "Dashboard": [
            st.Page("views/watchlist.py", title="Watchlist", icon=":material/monitoring:", default=True),
            st.Page("views/scorecard.py", title="Scorecard", icon=":material/assessment:"),
            st.Page("views/dataset.py", title="Dataset", icon=":material/database:"),
        ],
        "Portfolio": [
            st.Page("views/portfolio.py", title="Portfolio", icon=":material/account_balance:"),
        ],
        "Research": [
            st.Page("views/reports.py", title="Reports", icon=":material/description:"),
            st.Page("views/request_report.py", title="Request Report", icon=":material/add_circle:"),
        ],
    }
)

pg.run()
