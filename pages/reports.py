"""Reports — shared research reports."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from data_loader import get_company_profiles, get_report_content, get_reports

st.title("Reports")

reports = get_reports()

if not reports:
    st.info("No reports uploaded yet. Run `bioresearch analyze TICKER` to generate and share.")
else:
    # Company name resolution for report tickers
    _report_tickers = sorted({r["ticker"] for r in reports})
    _profiles = get_company_profiles(tuple(_report_tickers)) if _report_tickers else {}

    def _company_name(ticker: str, existing: str = "") -> str:
        return existing if existing else _profiles.get(ticker, ticker)

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
                "Company": _company_name(r["ticker"], r.get("company_name", "")),
                "Action": r.get("action", "N/A"),
                "Conviction": r.get("net_conviction", "N/A"),
                "PTS Gap": f"{r['pts_gap']:+.2f}" if r.get("pts_gap") is not None else "N/A",
                "Risk": r.get("risk_decision", "N/A"),
                "Quality": f"{r['data_quality']:.2f}" if r.get("data_quality") is not None else "N/A",
                "Date": r["report_timestamp"][:10],
                "Size": f"{r.get('file_size_bytes', 0) / 1024:.0f} KB",
            }
        )

    st.dataframe(pd.DataFrame(report_rows), width="stretch", hide_index=True)

    # --- Report viewer ---
    st.divider()
    report_options = {
        f"{r['ticker']} \u2014 {r['report_timestamp'][:10]} ({r.get('action', 'N/A')})": r["storage_path"]
        for i, r in enumerate(reports)
    }
    # If there are still collisions (same ticker+date+action), deduplicate with index
    if len(report_options) < len(reports):
        report_options = {
            f"{r['ticker']} \u2014 {r['report_timestamp'][:10]} #{i+1}": r["storage_path"]
            for i, r in enumerate(reports)
        }
    selected_label = st.selectbox("Select report to view", list(report_options.keys()))

    if selected_label:
        storage_path = report_options[selected_label]
        try:
            content = get_report_content(storage_path)
            ticker_label = selected_label.split(" \u2014")[0]
            st.download_button(
                label="Download Report",
                data=content,
                file_name=f"{ticker_label}_report.md",
                mime="text/markdown",
            )
            with st.expander("Full Report", expanded=True):
                st.markdown(content)
        except Exception as exc:
            st.error(f"Failed to load report: {exc}")
