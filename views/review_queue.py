"""Review Queue — confirm or dismiss auto-detected catalyst outcomes.

The auto-cycle daemon detects outcomes but flags uncertain ones for human review.
This page shows flagged detections with evidence and provides confirm/dismiss actions.
"""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from data_loader import (
    confirm_detection,
    dismiss_detection,
    get_detections,
    get_eval_dataset,
    record_outcome_from_ui,
)

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

_flagged_raw = get_detections(status="flagged")

# Deduplicate by (ticker, event_type, catalyst_date) — keep most recent
_seen_keys: set[tuple[str, str, str]] = set()
_flagged: list[dict] = []
for _det in sorted(
    _flagged_raw, key=lambda d: d.get("created_at", ""), reverse=True
):
    _key = (
        _det.get("ticker", ""),
        _det.get("event_type", ""),
        _det.get("catalyst_date", ""),
    )
    if _key not in _seen_keys:
        _seen_keys.add(_key)
        _flagged.append(_det)

# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.title("Review Queue")

if not _flagged:
    st.info(
        "No flagged detections. The auto-cycle daemon will flag uncertain "
        "outcomes here for your review."
    )
    st.stop()

st.subheader(f"Flagged Detections ({len(_flagged)})")
st.caption(
    "The auto-cycle detected these outcomes but couldn't confirm with "
    "HIGH confidence. Review the evidence and confirm or dismiss."
)

# Show success from previous confirmation
if st.session_state.get("_review_record_success"):
    st.success(st.session_state.pop("_review_record_success"))
    for _rw in st.session_state.pop("_review_record_warnings", []):
        st.warning(_rw)

_outcome_colors = {
    "APPROVED": "green",
    "CRL": "red",
    "FAILED": "red",
    "MET_ENDPOINT": "green",
    "DELAYED": "orange",
}
_outcomes_list = ["APPROVED", "CRL", "MET_ENDPOINT", "FAILED", "DELAYED"]
_event_types_list = ["PDUFA", "Phase3_Readout", "AdCom", "NDA", "EarningsReadout"]

for _det in _flagged:
    _d_ticker = _det.get("ticker", "?")
    _d_outcome = _det.get("outcome", "?")
    _d_confidence = _det.get("confidence", "?")
    _d_event_type = _det.get("event_type", "PDUFA")
    _d_catalyst_date = _det.get("catalyst_date")
    _d_press_release_date = _det.get("press_release_date")
    _d_company = _det.get("company_name", "")
    _d_sources = _det.get("sources", [])
    _d_evidence = _det.get("evidence", [])
    _d_created = _det.get("created_at", "")
    _d_color = _outcome_colors.get(_d_outcome, "gray")

    with st.expander(
        f":{_d_color}[{_d_outcome}] **{_d_ticker}** \u2014 "
        f"{_d_company or _d_ticker} "
        f"({_d_event_type}, {_d_confidence} confidence)",
        expanded=True,
    ):
        _d_col_info, _d_col_action = st.columns([3, 2])

        with _d_col_info:
            st.markdown(f"**Catalyst Date:** {_d_catalyst_date or 'N/A'}")
            if _d_press_release_date and _d_press_release_date != _d_catalyst_date:
                st.markdown(f"**Press Release Date:** {_d_press_release_date}")
            st.markdown(
                f"**Sources:** "
                f"{', '.join(_d_sources) if _d_sources else 'N/A'}"
            )
            if _d_evidence:
                st.markdown("**Evidence:**")
                for _ev in _d_evidence[:5]:
                    st.markdown(f"- {_ev}")

            # Pre-populated prices from auto-cycle
            _d_price_before = _det.get("price_before")
            _d_price_event = _det.get("price_event_day")
            _d_price_after = _det.get("price_after")
            _d_price_7d = _det.get("price_7d_after")
            _d_price_14d = _det.get("price_14d_after")
            _d_price_30d = _det.get("price_30d_after")
            _d_price_chg = _det.get("price_change_pct")

            if _d_price_before is not None:
                st.markdown("**Prices (auto-fetched):**")
                _price_parts = [f"T-1: ${_d_price_before:.2f}"]
                if _d_price_event is not None:
                    _price_parts.append(f"T=0: ${_d_price_event:.2f}")
                if _d_price_after is not None:
                    _price_parts.append(f"T+1: ${_d_price_after:.2f}")
                if _d_price_7d is not None:
                    _price_parts.append(f"T+7: ${_d_price_7d:.2f}")
                if _d_price_14d is not None:
                    _price_parts.append(f"T+14: ${_d_price_14d:.2f}")
                if _d_price_30d is not None:
                    _price_parts.append(f"T+30: ${_d_price_30d:.2f}")
                st.markdown(" \u00b7 ".join(_price_parts))
                if _d_price_chg is not None:
                    _chg_color = "green" if _d_price_chg >= 0 else "red"
                    st.markdown(
                        f"**Return:** :{_chg_color}[{_d_price_chg:+.1%}]"
                    )
                # Show price warnings if any
                _d_price_warns = _det.get("price_warnings")
                if _d_price_warns:
                    for _pw in _d_price_warns:
                        st.caption(f"Warning: {_pw}")

            st.caption(
                f"Detected: {_d_created[:19] if _d_created else 'N/A'}"
            )

        with _d_col_action:
            _fk = f"rq_{_d_ticker}_{_det.get('id', _d_created)}"
            with st.form(_fk):
                _d_def_out = (
                    _outcomes_list.index(_d_outcome)
                    if _d_outcome in _outcomes_list
                    else 0
                )
                _rq_outcome = st.selectbox(
                    "Outcome",
                    _outcomes_list,
                    index=_d_def_out,
                    key=f"o_{_fk}",
                )
                _d_def_et = (
                    _event_types_list.index(_d_event_type)
                    if _d_event_type in _event_types_list
                    else 0
                )
                _rq_etype = st.selectbox(
                    "Event Type",
                    _event_types_list,
                    index=_d_def_et,
                    key=f"et_{_fk}",
                )
                # Prefer press_release_date (actual event) over
                # catalyst_date (scheduled) — mirrors auto-record logic
                _rq_raw_date = _d_press_release_date or _d_catalyst_date
                try:
                    _rq_def_date = date.fromisoformat(str(_rq_raw_date))
                except (ValueError, TypeError):
                    _rq_def_date = date.today()
                _rq_date = st.date_input(
                    "Event Date",
                    value=_rq_def_date,
                    key=f"d_{_fk}",
                )
                _rq_pb = st.number_input(
                    "Price Before (T-1)",
                    min_value=0.0,
                    value=float(_d_price_before) if _d_price_before else 0.0,
                    step=0.01,
                    format="%.2f",
                    key=f"pb_{_fk}",
                )
                _rq_pa = st.number_input(
                    "Price After (T+1)",
                    min_value=0.0,
                    value=float(_d_price_after) if _d_price_after else 0.0,
                    step=0.01,
                    format="%.2f",
                    key=f"pa_{_fk}",
                )
                _btn_col1, _btn_col2 = st.columns(2)
                with _btn_col1:
                    _do_confirm = st.form_submit_button(
                        "Confirm & Record",
                        type="primary",
                    )
                with _btn_col2:
                    _do_dismiss = st.form_submit_button("Dismiss")

                if _do_confirm:
                    _reviewer = st.session_state.get("name", "unknown")
                    with st.spinner("Recording..."):
                        try:
                            # Build overrides dict if user changed anything
                            _overrides = {}
                            if _rq_outcome != _d_outcome:
                                _overrides["outcome"] = _rq_outcome
                            if _rq_etype != _d_event_type:
                                _overrides["event_type"] = _rq_etype
                            if _rq_date.isoformat() != str(_d_catalyst_date):
                                _overrides["catalyst_date"] = _rq_date.isoformat()
                            if _rq_pb > 0 and _rq_pb != (_d_price_before or 0):
                                _overrides["price_before"] = _rq_pb
                            if _rq_pa > 0 and _rq_pa != (_d_price_after or 0):
                                _overrides["price_after"] = _rq_pa

                            _rq_result = record_outcome_from_ui(
                                ticker=_d_ticker,
                                event_type=_rq_etype,
                                event_date=_rq_date,
                                outcome=_rq_outcome,
                                company_name=_d_company or None,
                                notes=(
                                    f"Confirmed by {_reviewer} "
                                    f"(auto-detected {_d_confidence})"
                                ),
                                price_before_override=(
                                    _rq_pb if _rq_pb > 0 else None
                                ),
                                price_after_override=(
                                    _rq_pa if _rq_pa > 0 else None
                                ),
                                price_event_day=_d_price_event,
                                price_7d_after=_d_price_7d,
                                price_14d_after=_d_price_14d,
                                price_30d_after=_d_price_30d,
                            )
                            confirm_detection(
                                _det["id"],
                                reviewed_by=_reviewer,
                                overrides=_overrides if _overrides else None,
                            )
                            _rq_od = _rq_result["outcome"]
                            _rq_pct = _rq_od["price_change_pct"]
                            st.session_state["_review_record_success"] = (
                                f"Recorded: {_d_ticker} {_rq_etype} on "
                                f"{_rq_date} \u2192 {_rq_outcome} "
                                f"(return: {_rq_pct:+.1%})"
                            )
                            st.session_state["_review_record_warnings"] = (
                                _rq_result["warnings"]
                            )
                            get_eval_dataset.clear()
                            get_detections.clear()
                            st.session_state["last_refreshed"] = datetime.now()
                            st.rerun()
                        except Exception as _rq_err:
                            st.error(f"Failed: {_rq_err}")

                if _do_dismiss:
                    _reviewer = st.session_state.get("name", "unknown")
                    dismiss_detection(_det["id"], reviewed_by=_reviewer)
                    get_detections.clear()
                    st.rerun()

        # Audit trail
        _d_audit = _det.get("audit_log") or []
        if _d_audit:
            st.markdown("---")
            st.caption("**Audit Trail**")
            for _a in _d_audit:
                _a_action = _a.get("action", "?")
                _a_by = _a.get("by", "system")
                _a_at = _a.get("at", "")[:19].replace("T", " ")
                _a_icons = {
                    "detected": "Detected",
                    "confirmed": "Confirmed",
                    "dismissed": "Dismissed",
                    "modified": "Modified",
                }
                _a_prefix = _a_icons.get(_a_action, _a_action)
                _a_line = f"**{_a_prefix}** by {_a_by} at {_a_at}"
                _a_changes = _a.get("changes") or _a.get("overrides")
                if _a_changes:
                    _change_parts = []
                    for _ck, _cv in _a_changes.items():
                        if isinstance(_cv, dict):
                            _change_parts.append(
                                f"{_ck}: {_cv.get('old')} \u2192 {_cv.get('new')}"
                            )
                        else:
                            _change_parts.append(f"{_ck}: {_cv}")
                    _a_line += f" ({', '.join(_change_parts)})"
                st.caption(_a_line)
