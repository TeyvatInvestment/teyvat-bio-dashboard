"""Scorecard — 6 core eval metrics and per-event breakdown."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from data_loader import get_eval_dataset

data = get_eval_dataset()
eval_result = data["eval_result"]
n_paired = data["n_paired"]

st.title("Scorecard")

if n_paired == 0:
    st.info(
        "No paired events yet. Record outcomes using the form on the "
        "Watchlist page, or via the CLI (`bioresearch eval record`)."
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
