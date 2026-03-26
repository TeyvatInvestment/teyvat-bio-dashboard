"""Review Queue — approve or dismiss auto-detected catalyst outcomes."""

from __future__ import annotations

from datetime import date

import streamlit as st

from data_loader import (
    approve_detection,
    dismiss_detection,
    get_detections,
    record_outcome_from_ui,
)

st.title("Review Queue")
st.caption(
    "Low-confidence auto-detected outcomes awaiting human review. "
    "Approve to record as an official outcome, or dismiss to discard."
)

# Load flagged detections
all_detections = get_detections()
flagged = [d for d in all_detections if d["status"] == "flagged"]

if not flagged:
    st.info("No detections pending review. All clear!")
    st.stop()

st.metric("Pending Review", len(flagged))
st.divider()

for detection in flagged:
    det_id = detection["id"]
    ticker = detection.get("ticker", "???")
    company = detection.get("company_name", ticker)
    event_type = detection.get("event_type", "Unknown")
    catalyst_date = detection.get("catalyst_date")
    outcome = detection.get("outcome", "Unknown")
    confidence = detection.get("confidence", "LOW")
    sources = detection.get("sources", [])
    evidence = detection.get("evidence", [])
    created_at = detection.get("created_at", "")

    # Color-code by outcome
    outcome_colors = {
        "APPROVED": ":green[APPROVED]",
        "CRL": ":red[CRL]",
        "MET_ENDPOINT": ":green[MET_ENDPOINT]",
        "FAILED": ":red[FAILED]",
        "DELAYED": ":orange[DELAYED]",
    }
    outcome_display = outcome_colors.get(outcome, outcome)

    with st.container(border=True):
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            st.markdown(f"### {ticker}")
            st.caption(company)
        with col2:
            st.markdown(f"**{event_type}** | {outcome_display}")
            st.caption(f"Catalyst: {catalyst_date or 'Unknown'}")
        with col3:
            st.markdown(f"Confidence: **{confidence}**")
            st.caption(f"Sources: {', '.join(sources) if sources else 'N/A'}")

        # Evidence
        if evidence:
            with st.expander("Evidence"):
                for e in evidence:
                    st.markdown(f"- {e}")

        # Action buttons
        col_approve, col_dismiss, col_spacer = st.columns([1, 1, 3])

        with col_approve:
            if st.button("Approve", key=f"approve_{det_id}", type="primary"):
                # For future events, we can't fetch prices yet
                event_date_parsed = (
                    date.fromisoformat(catalyst_date) if catalyst_date else None
                )
                is_future = (
                    event_date_parsed and event_date_parsed > date.today()
                )

                if is_future:
                    st.warning(
                        f"Catalyst date {catalyst_date} is in the future. "
                        "Cannot fetch prices yet. Recording will be available "
                        "after the event date."
                    )
                    # Still mark detection as approved for tracking
                    approve_detection(det_id)
                    get_detections.clear()
                    st.success(
                        f"Marked {ticker} detection as approved. "
                        "Record the outcome after the event date."
                    )
                    st.rerun()
                else:
                    try:
                        result = record_outcome_from_ui(
                            ticker=ticker,
                            event_type=event_type,
                            event_date=event_date_parsed,
                            outcome=outcome,
                            company_name=company,
                            notes=(
                                f"Auto-detected ({confidence}). "
                                f"Sources: {', '.join(sources)}. "
                                f"Approved via dashboard review."
                            ),
                        )
                        approve_detection(det_id)
                        get_detections.clear()
                        warnings = result.get("warnings", [])
                        if warnings:
                            st.warning(
                                "Recorded with warnings: "
                                + "; ".join(warnings)
                            )
                        else:
                            st.success(
                                f"Recorded {ticker} {event_type} "
                                f"→ {outcome}"
                            )
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))

        with col_dismiss:
            if st.button("Dismiss", key=f"dismiss_{det_id}"):
                dismiss_detection(det_id)
                get_detections.clear()
                st.rerun()
