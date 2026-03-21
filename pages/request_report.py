"""Request Report — submit a research report request.

Requires a ``report_requests`` table in Supabase:

    create table report_requests (
        id bigint generated always as identity primary key,
        ticker text not null,
        company_name text not null default '',
        requested_by text not null,
        request_type text not null default 'full_analysis',
        priority text not null default 'normal',
        notes text,
        status text not null default 'pending',
        created_at timestamptz not null default now()
    );
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from data_loader import get_report_requests, submit_report_request

st.title("Request Report")

# Show success from previous submission
if st.session_state.get("_request_success"):
    st.success(st.session_state.pop("_request_success"))

# ---------------------------------------------------------------------------
# Request form
# ---------------------------------------------------------------------------
st.subheader("Submit Request")

REQUEST_TYPES = ["Full Analysis", "Quick Update", "Deep Dive"]
PRIORITIES = ["Normal", "High", "Urgent"]

with st.form("request_report_form", clear_on_submit=True):
    col_left, col_right = st.columns(2)

    with col_left:
        req_ticker = st.text_input("Ticker", help="e.g. MRNA, REGN")
        req_type = st.selectbox("Request Type", REQUEST_TYPES)

    with col_right:
        req_priority = st.selectbox("Priority", PRIORITIES)
        req_notes = st.text_area(
            "Notes (optional)",
            help="Context or specific questions for the analysis.",
        )

    submitted = st.form_submit_button("Submit Request", type="primary")

    if submitted:
        if not req_ticker.strip():
            st.error("Ticker is required.")
        else:
            try:
                submit_report_request(
                    ticker=req_ticker.strip().upper(),
                    requested_by=st.session_state.get("username", "unknown"),
                    request_type=req_type.lower().replace(" ", "_"),
                    priority=req_priority.lower(),
                    notes=req_notes.strip() or None,
                )
                st.session_state["_request_success"] = (
                    f"Report request submitted for {req_ticker.strip().upper()}"
                )
                st.cache_data.clear()
                st.session_state["last_refreshed"] = datetime.now()
                st.rerun()
            except Exception as e:
                st.error(f"Failed to submit request: {e}")

# ---------------------------------------------------------------------------
# Existing requests
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Existing Requests")

requests = get_report_requests()

if not requests:
    st.info("No report requests yet. Use the form above to submit one.")
else:
    status_filter = st.multiselect(
        "Filter by status",
        ["pending", "in_progress", "completed", "cancelled"],
        default=["pending", "in_progress"],
    )

    filtered = [r for r in requests if r.get("status") in status_filter]

    if filtered:
        rows = []
        for r in filtered:
            status_raw = r.get("status", "pending")
            rows.append(
                {
                    "ID": r["id"],
                    "Status": status_raw.replace("_", " ").title(),
                    "Ticker": r["ticker"],
                    "Company": r.get("company_name") or r["ticker"],
                    "Type": r["request_type"].replace("_", " ").title(),
                    "Priority": r["priority"].title(),
                    "Requested By": r["requested_by"],
                    "Notes": r.get("notes") or "",
                    "Date": r["created_at"][:10],
                }
            )

        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.info("No requests match the selected filters.")
