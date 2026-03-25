"""Portfolio — holdings, P&L, exposure charts, and performance tracking."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from data_loader import (
    get_all_portfolio_snapshots,
    get_current_prices,
    get_portfolio_list,
    get_portfolio_snapshots,
    get_portfolio_state,
    get_portfolio_trades,
)

st.title("Portfolio")

# ---------------------------------------------------------------------------
# Portfolio list
# ---------------------------------------------------------------------------
portfolios = get_portfolio_list()

if not portfolios:
    st.info(
        "No portfolios found. Create one with:\n\n"
        "```\nbioresearch portfolio create --name default --nav 300000\n```\n\n"
        "Then run the DDL in `scripts/portfolio_schema.sql` on Supabase."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Portfolio selector
# ---------------------------------------------------------------------------
portfolio_options = {
    f"{p['portfolio_label']} ({p['portfolio_id']}) — ${p['nav']:,.0f}": p["portfolio_id"]
    for p in portfolios
}
selected_label = st.selectbox("Portfolio", list(portfolio_options.keys()))
selected_id = portfolio_options[selected_label]

state = get_portfolio_state(selected_id)
if not state:
    st.error(f"Could not load portfolio '{selected_id}'.")
    st.stop()

# ---------------------------------------------------------------------------
# Summary KPIs
# ---------------------------------------------------------------------------
k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("NAV", f"${state['nav']:,.0f}", f"{state['return_pct']:+.1%}")
k2.metric("Cash", f"${state['cash']:,.0f}")
k3.metric("Invested", f"${state['positions_value']:,.0f}")
drawdown = state["drawdown_pct"]
k4.metric("Drawdown", f"{drawdown:.1%}" if drawdown < 0 else "0.0%")
k5.metric("Realized P&L", f"${state['total_realized_pnl']:,.0f}")
k6.metric("Positions", str(state["num_positions"]))

# ---------------------------------------------------------------------------
# Holdings table with live prices
# ---------------------------------------------------------------------------
st.subheader("Holdings")
positions = state["positions"]

if not positions:
    st.info("No positions. Pipeline BUY signals will appear here after execution.")
else:
    # Batch-fetch live prices in one FMP call
    tickers = tuple(sorted(p["ticker"] for p in positions))
    live_prices = get_current_prices(tickers)

    rows = []
    for p in positions:
        live_info = live_prices.get(p["ticker"])
        live_price = live_info["price"] if live_info else p["current_price"]
        cost_basis = p["shares"] * p["avg_cost"]
        mkt_val = p["shares"] * live_price
        pnl = mkt_val - cost_basis
        pnl_pct = pnl / cost_basis if cost_basis > 0 else 0.0

        days_held = 0
        if p.get("entry_date"):
            try:
                days_held = (date.today() - date.fromisoformat(str(p["entry_date"]))).days
            except (ValueError, TypeError):
                pass

        pending = len([o for o in p.get("pending_orders", []) if o.get("status") == "PENDING"])

        rows.append({
            "Ticker": p["ticker"],
            "Shares": f"{p['shares']:.0f}",
            "Avg Cost": f"${p['avg_cost']:.2f}",
            "Price": f"${live_price:.2f}",
            "Value": f"${mkt_val:,.0f}",
            "P&L": f"${pnl:,.0f}",
            "P&L %": f"{pnl_pct:+.1%}",
            "Weight": f"{p['weight_pct']:.1f}%",
            "MoA": (p["moa"] or "")[:18],
            "Catalyst": str(p["catalyst_date"]) if p.get("catalyst_date") else "",
            "Stop": f"${p['stop_loss_price']:.2f}" if p.get("stop_loss_price") else "",
            "Days": str(days_held),
            "Pending": str(pending) if pending else "",
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, use_container_width=True)

    st.caption(
        f"Prices from FMP. "
        f"Last refresh: {st.session_state.get('last_refreshed', 'N/A')}. "
        f"Refresh via sidebar button."
    )

# ---------------------------------------------------------------------------
# Two columns: MoA Exposure + Portfolio Stats
# ---------------------------------------------------------------------------
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("MoA Exposure")
    moa_data = state.get("moa_exposure", {})
    if moa_data:
        moa_df = pd.DataFrame(
            [{"MoA": k, "% NAV": round(v, 1)}
             for k, v in sorted(moa_data.items(), key=lambda x: -x[1])]
        )
        st.bar_chart(moa_df, x="MoA", y="% NAV")
    else:
        st.info("No positions to show exposure.")

with col_right:
    st.subheader("Stats")
    stats_rows = [
        ("Initial NAV", f"${state['initial_nav']:,.0f}"),
        ("High Water Mark", f"${state['high_water_mark']:,.0f}"),
        ("Total Return", f"{state['return_pct']:+.2%}"),
        ("Transaction Costs", f"${state['total_transaction_costs']:,.0f}"),
        ("Inception", str(state.get("inception_date", "N/A"))),
    ]
    stats_df = pd.DataFrame(stats_rows, columns=["Metric", "Value"])
    st.dataframe(stats_df, hide_index=True, use_container_width=True)

# ---------------------------------------------------------------------------
# NAV over time (single portfolio)
# ---------------------------------------------------------------------------
st.subheader("NAV Over Time")
snapshots = get_portfolio_snapshots(selected_id)

if snapshots:
    snap_df = pd.DataFrame(snapshots)
    snap_df["snapshot_date"] = pd.to_datetime(snap_df["snapshot_date"])
    snap_df["nav"] = snap_df["nav"].astype(float)

    st.line_chart(snap_df, x="snapshot_date", y="nav")

    # Drawdown sub-chart
    if "drawdown_from_hwm_pct" in snap_df.columns:
        snap_df["drawdown_from_hwm_pct"] = snap_df["drawdown_from_hwm_pct"].astype(float)
        with st.expander("Drawdown from HWM"):
            st.area_chart(snap_df, x="snapshot_date", y="drawdown_from_hwm_pct")
else:
    st.info("No daily snapshots yet. Run `bioresearch portfolio monitor` to record snapshots.")

# ---------------------------------------------------------------------------
# Multi-portfolio NAV overlay
# ---------------------------------------------------------------------------
if len(portfolios) > 1:
    st.subheader("Multi-Portfolio Comparison")
    all_snapshots = get_all_portfolio_snapshots()

    if all_snapshots:
        # Build label lookup
        label_map = {p["portfolio_id"]: p["portfolio_label"] for p in portfolios}

        overlay_rows = []
        for pid, snaps in all_snapshots.items():
            label = label_map.get(pid, pid)
            for s in snaps:
                overlay_rows.append({
                    "date": s["snapshot_date"],
                    "NAV": float(s["nav"]),
                    "portfolio": label,
                })

        if overlay_rows:
            overlay_df = pd.DataFrame(overlay_rows)
            overlay_df["date"] = pd.to_datetime(overlay_df["date"])
            pivot = overlay_df.pivot(index="date", columns="portfolio", values="NAV")
            st.line_chart(pivot)

            # Summary comparison table
            comp_rows = []
            for p in portfolios:
                comp_rows.append({
                    "Portfolio": p["portfolio_label"],
                    "NAV": f"${p['nav']:,.0f}",
                    "Return": f"{p['return_pct']:+.1%}",
                    "Positions": p["num_positions"],
                    "Realized P&L": f"${p['total_realized_pnl']:,.0f}",
                    "Costs": f"${p['total_transaction_costs']:,.0f}",
                })
            st.dataframe(pd.DataFrame(comp_rows), hide_index=True, use_container_width=True)
        else:
            st.info("No snapshots across portfolios yet.")
    else:
        st.info("No snapshots across portfolios yet.")

# ---------------------------------------------------------------------------
# Recent trades
# ---------------------------------------------------------------------------
st.subheader("Recent Trades")
trades = get_portfolio_trades(selected_id)

if trades:
    trade_rows = []
    for t in trades[:50]:
        pnl_str = ""
        if t.get("realized_pnl") is not None:
            pnl_str = f"${float(t['realized_pnl']):,.0f}"

        trade_rows.append({
            "Time": (t.get("created_at") or "")[:16].replace("T", " "),
            "Ticker": t["ticker"],
            "Side": t["side"],
            "Type": t.get("trade_type", ""),
            "Shares": f"{float(t['shares']):.0f}",
            "Fill": f"${float(t['price']):.2f}",
            "Market": f"${float(t['market_price']):.2f}",
            "Value": f"${float(t['value']):,.0f}",
            "Cost": f"${float(t.get('transaction_cost', 0)):.2f}",
            "P&L": pnl_str,
        })

    trade_df = pd.DataFrame(trade_rows)
    st.dataframe(trade_df, hide_index=True, use_container_width=True)

    if len(trades) > 50:
        st.caption(f"Showing 50 of {len(trades)} trades.")
else:
    st.info("No trades recorded yet.")
