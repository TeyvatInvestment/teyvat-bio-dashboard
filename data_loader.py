"""Data loader — reads eval data from Supabase.

Deployed on Streamlit Community Cloud, this app reads ONLY from Supabase.
Credentials come from st.secrets (configured in the Community Cloud dashboard).
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict
from datetime import date, timedelta

import httpx
import streamlit as st
from supabase import create_client

from models import CatalystOutcome, EvalDataset, PipelinePrediction
from scorer import EvalResult, score_predictions
from watchlist import build_watchlist

logger = logging.getLogger(__name__)


def _get_supabase_client():
    """Create a Supabase sync client from st.secrets."""
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["service_role_key"]
    return create_client(url, key)


def _row_to_outcome(row: dict) -> CatalystOutcome:
    return CatalystOutcome(
        ticker=row["ticker"],
        company_name=row["company_name"],
        event_type=row["event_type"],
        event_date=row["event_date"],
        outcome=row["outcome"],
        price_before=row["price_before"],
        price_after=row["price_after"],
        price_change_pct=row["price_change_pct"],
        price_30d_after=row.get("price_30d_after"),
        notes=row.get("notes"),
    )


def _row_to_prediction(row: dict) -> PipelinePrediction:
    return PipelinePrediction(
        ticker=row["ticker"],
        company_name=row.get("company_name", ""),
        run_id=row["run_id"],
        run_timestamp=row["run_timestamp"],
        snapshot_ref=row.get("snapshot_ref"),
        science_pts=row["science_pts"],
        development_stage=row["development_stage"],
        evidence_quality=row["evidence_quality"],
        next_catalyst=row.get("next_catalyst", ""),
        catalyst_date=row.get("catalyst_date"),
        market_pts=row["market_pts"],
        rnpv_per_share=row["rnpv_per_share"],
        success_price=row.get("success_price"),
        failure_price=row.get("failure_price"),
        current_price=row["current_price"],
        upside_pct=row["upside_pct"],
        pts_gap=row["pts_gap"],
        action=row["action"],
        net_conviction=row["net_conviction"],
        bull_conviction=row["bull_conviction"],
        bear_conviction=row["bear_conviction"],
        proposed_size_pct=row["proposed_size_pct"],
        risk_decision=row["risk_decision"],
        approved_size_pct=row["approved_size_pct"],
        violated_rules=row.get("violated_rules", []),
        entry_price_limit=row.get("entry_price_limit"),
        stop_loss_price=row.get("stop_loss_price"),
        execution_plan=row.get("execution_plan"),
        data_quality_score=row["data_quality_score"],
        data_warnings=row.get("data_warnings", []),
        trace_path=row.get("trace_path"),
    )


@st.cache_data
def get_eval_dataset() -> dict:
    """Load and cache the full eval dataset from Supabase.

    Returns a dict with all Pydantic/dataclass objects converted to dicts
    for Streamlit serialization.
    """
    client = _get_supabase_client()

    # Load outcomes
    resp = client.table("eval_outcomes").select("*").order("event_date").execute()
    outcomes = [_row_to_outcome(r) for r in resp.data]

    # Load predictions
    resp = client.table("eval_predictions").select("*").order("run_timestamp").execute()
    predictions = [_row_to_prediction(r) for r in resp.data]

    # Score and build watchlist
    dataset = EvalDataset(outcomes=outcomes, predictions=predictions)
    wl = build_watchlist(predictions, outcomes)
    eval_result = score_predictions(dataset)

    return {
        "outcomes": [o.model_dump(mode="json") for o in outcomes],
        "predictions": [p.model_dump(mode="json") for p in predictions],
        "watchlist": [w.model_dump(mode="json") for w in wl],
        "eval_result": asdict(eval_result),
        "n_paired": len(dataset.paired()),
        "n_unpaired_outcomes": len(dataset.unpaired_outcomes),
        "n_unpaired_predictions": len(dataset.unpaired_predictions),
    }


@st.cache_data(ttl=300)
def get_reports(ticker: str | None = None) -> list[dict]:
    """Load report metadata from eval_reports table."""
    client = _get_supabase_client()
    query = client.table("eval_reports").select("*").order("report_timestamp", desc=True)
    if ticker:
        query = query.eq("ticker", ticker.upper())
    resp = query.execute()
    return resp.data


@st.cache_data(ttl=3600)
def get_report_content(storage_path: str) -> str:
    """Download a report's Markdown content from the reports storage bucket."""
    client = _get_supabase_client()
    content = client.storage.from_("reports").download(storage_path)
    return content.decode("utf-8")


@st.cache_data(ttl=300)
def get_current_prices(tickers: tuple[str, ...]) -> dict[str, dict | None]:
    """Fetch current prices for multiple tickers via FMP batch quote.

    Uses a single API call for all tickers: /v3/quote/AAPL,MSFT,...
    Returns {ticker: {"price": float, "prev_close": float} | None}.
    """
    api_key = st.secrets["fmp"]["api_key"]

    try:
        symbols = ",".join(tickers)
        resp = httpx.get(
            f"https://financialmodelingprep.com/api/v3/quote/{symbols}",
            params={"apikey": api_key},
            timeout=10,
        )
        data = resp.json()
    except Exception:
        return {t: None for t in tickers}

    results: dict[str, dict | None] = {t: None for t in tickers}
    if isinstance(data, list):
        for q in data:
            symbol = q.get("symbol", "")
            results[symbol] = {
                "price": round(float(q.get("price", 0)), 2),
                "prev_close": round(float(q.get("previousClose", 0)), 2),
            }
    return results


@st.cache_data(ttl=86400)  # Cache for 1 day
def get_company_profiles(tickers: tuple[str, ...]) -> dict[str, str]:
    """Fetch company names from FMP profile endpoint.

    Returns {ticker: company_name} mapping. Cached for 1 day.
    """
    api_key = st.secrets["fmp"]["api_key"]

    try:
        symbols = ",".join(tickers)
        resp = httpx.get(
            f"https://financialmodelingprep.com/api/v3/profile/{symbols}",
            params={"apikey": api_key},
            timeout=10,
        )
        data = resp.json()
    except Exception:
        logger.warning("Failed to fetch FMP company profiles")
        return {}

    results: dict[str, str] = {}
    if isinstance(data, list):
        for profile in data:
            symbol = profile.get("symbol", "")
            name = profile.get("companyName", "")
            if symbol and name:
                results[symbol] = name
    return results


# ---------------------------------------------------------------------------
# Write helpers — outcome recording from the dashboard
# ---------------------------------------------------------------------------

VALID_OUTCOMES = frozenset({"APPROVED", "CRL", "MET_ENDPOINT", "FAILED", "DELAYED"})
VALID_EVENT_TYPES = frozenset({"PDUFA", "Phase3_Readout", "AdCom", "NDA", "EarningsReadout"})


def _fetch_event_prices(ticker: str, event_date: date) -> dict:
    """Fetch T-1 and T+1 closing prices using FMP historical price API.

    Queries a 10-day window around the event date to handle weekends/holidays.
    Returns {"price_before": float|None, "price_after": float|None, "warnings": list[str]}.
    """
    api_key = st.secrets["fmp"]["api_key"]
    from_date = event_date - timedelta(days=10)
    to_date = event_date + timedelta(days=10)

    try:
        resp = httpx.get(
            f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}",
            params={
                "apikey": api_key,
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
            },
            timeout=10,
        )
        data = resp.json()
    except Exception as exc:
        return {
            "price_before": None,
            "price_after": None,
            "warnings": [f"FMP price fetch failed: {exc}"],
        }

    historicals = data.get("historical", [])
    warnings: list[str] = []
    price_before = None
    price_after = None

    sorted_bars = sorted(historicals, key=lambda b: b["date"])

    # T-1: last trading day strictly before event_date
    for bar in reversed(sorted_bars):
        bar_date = date.fromisoformat(bar["date"])
        if bar_date < event_date:
            price_before = bar["close"]
            break

    # T+1: first trading day strictly after event_date
    for bar in sorted_bars:
        bar_date = date.fromisoformat(bar["date"])
        if bar_date > event_date:
            price_after = bar["close"]
            break

    if price_before is None:
        warnings.append(f"No T-1 price found for {ticker} before {event_date}")
    if price_after is None:
        warnings.append(f"No T+1 price found for {ticker} after {event_date}")

    return {"price_before": price_before, "price_after": price_after, "warnings": warnings}


def record_outcome_from_ui(
    ticker: str,
    event_type: str,
    event_date: date,
    outcome: str,
    company_name: str | None = None,
    notes: str | None = None,
    price_before_override: float | None = None,
    price_after_override: float | None = None,
) -> dict:
    """Record a catalyst outcome to Supabase with auto-fetched FMP prices.

    Validates inputs, checks for duplicates, resolves company_name from
    predictions if not provided, fetches T-1/T+1 prices via FMP historical
    API, and inserts the outcome row into eval_outcomes.

    Returns dict with ``outcome`` (row data) and ``warnings`` (list[str]).
    Raises ValueError on validation/duplicate/price errors.
    """
    ticker = ticker.upper()

    if not re.match(r'^[A-Z]{1,10}$', ticker):
        raise ValueError(f"Invalid ticker format: '{ticker}'. Must be 1-10 uppercase letters.")
    if company_name and len(company_name) > 200:
        raise ValueError("Company name must be under 200 characters.")
    if notes and len(notes) > 2000:
        raise ValueError("Notes must be under 2000 characters.")

    if outcome not in VALID_OUTCOMES:
        raise ValueError(
            f"Invalid outcome '{outcome}'. Must be one of: {', '.join(sorted(VALID_OUTCOMES))}"
        )
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(
            f"Invalid event_type '{event_type}'. "
            f"Must be one of: {', '.join(sorted(VALID_EVENT_TYPES))}"
        )

    client = _get_supabase_client()

    # Check for duplicates
    resp = (
        client.table("eval_outcomes")
        .select("id")
        .eq("ticker", ticker)
        .eq("event_type", event_type)
        .eq("event_date", event_date.isoformat())
        .limit(1)
        .execute()
    )
    if resp.data:
        raise ValueError(f"Outcome already exists: {ticker} {event_type} on {event_date}")

    # Resolve company_name from predictions if not provided, then FMP
    if not company_name:
        resp = (
            client.table("eval_predictions")
            .select("company_name")
            .eq("ticker", ticker)
            .neq("company_name", "")
            .limit(1)
            .execute()
        )
        if resp.data:
            company_name = resp.data[0]["company_name"]
        else:
            profiles = get_company_profiles((ticker,))
            company_name = profiles.get(ticker, ticker)

    # Fetch prices from FMP
    warnings: list[str] = []
    prices = _fetch_event_prices(ticker, event_date)
    warnings.extend(prices["warnings"])

    price_before = (
        price_before_override if price_before_override is not None else prices["price_before"]
    )
    price_after = (
        price_after_override if price_after_override is not None else prices["price_after"]
    )

    if price_before is None:
        raise ValueError(
            f"Could not determine price_before for {ticker} on {event_date}. "
            "Use manual price override."
        )
    if price_after is None:
        raise ValueError(
            f"Could not determine price_after for {ticker} on {event_date}. "
            "Use manual price override."
        )
    if price_before <= 0:
        raise ValueError(f"price_before must be positive (got {price_before}).")
    if price_after < 0:
        raise ValueError(f"price_after must be non-negative (got {price_after}).")

    price_change_pct = (price_after - price_before) / price_before

    # Build row and insert
    row: dict = {
        "ticker": ticker,
        "company_name": company_name,
        "event_type": event_type,
        "event_date": event_date.isoformat(),
        "outcome": outcome,
        "price_before": round(price_before, 2),
        "price_after": round(price_after, 2),
        "price_change_pct": round(price_change_pct, 4),
    }
    if notes:
        row["notes"] = notes

    client.table("eval_outcomes").insert(row).execute()
    logger.info("Outcome recorded: %s %s %s → %s", ticker, event_type, event_date, outcome)

    return {"outcome": row, "warnings": warnings}


# ---------------------------------------------------------------------------
# Auto-cycle observability (Phase 2)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def get_cycle_runs(limit: int = 20) -> list[dict]:
    """Load recent auto-cycle runs from eval_cycle_runs table."""
    try:
        client = _get_supabase_client()
        resp = (
            client.table("eval_cycle_runs")
            .select("*")
            .order("started_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data
    except Exception:
        logger.debug("eval_cycle_runs table not available")
        return []


@st.cache_data(ttl=300)
def get_detections(
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Load detection records from eval_detections table."""
    try:
        client = _get_supabase_client()
        query = (
            client.table("eval_detections")
            .select("*")
            .order("created_at", desc=True)
        )
        if status:
            query = query.eq("status", status)
        resp = query.limit(limit).execute()
        return resp.data
    except Exception:
        logger.debug("eval_detections table not available")
        return []


# ---------------------------------------------------------------------------
# Detection review actions
# ---------------------------------------------------------------------------


def approve_detection(detection_id: int) -> None:
    """Mark a detection as approved (status → 'approved')."""
    client = _get_supabase_client()
    client.table("eval_detections").update(
        {"status": "approved"}
    ).eq("id", detection_id).execute()


def dismiss_detection(detection_id: int) -> None:
    """Mark a detection as dismissed (status → 'dismissed')."""
    client = _get_supabase_client()
    client.table("eval_detections").update(
        {"status": "dismissed"}
    ).eq("id", detection_id).execute()


# ---------------------------------------------------------------------------
# Report requests
# ---------------------------------------------------------------------------

VALID_REQUEST_TYPES = frozenset({"full_analysis", "quick_update", "deep_dive"})
VALID_PRIORITIES = frozenset({"normal", "high", "urgent"})


@st.cache_data(ttl=60)
def get_report_requests() -> list[dict]:
    """Load report requests from the report_requests table."""
    client = _get_supabase_client()
    resp = (
        client.table("report_requests")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return resp.data


# ---------------------------------------------------------------------------
# Portfolio data (reads from portfolio_state, portfolio_trades, portfolio_snapshots)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=60)
def get_portfolio_list() -> list[dict]:
    """List all portfolios with computed summary stats.

    Reads ``portfolio_state`` table and computes NAV from ``cash + positions``
    since NAV is a derived property (not stored as a column).
    """
    try:
        client = _get_supabase_client()
        resp = client.table("portfolio_state").select("*").order("portfolio_id").execute()
    except Exception:
        logger.debug("portfolio_state table not available")
        return []

    results = []
    for row in resp.data or []:
        positions = row.get("positions", {})
        if not isinstance(positions, dict):
            positions = {}
        positions_value = sum(
            float(p.get("market_value", 0)) for p in positions.values()
        )
        cash = float(row.get("cash", 0))
        initial_nav = float(row.get("initial_nav", 0))
        nav = cash + positions_value
        ret = (nav - initial_nav) / initial_nav if initial_nav > 0 else 0.0

        results.append({
            "portfolio_id": row["portfolio_id"],
            "portfolio_label": row.get("portfolio_label", ""),
            "nav": nav,
            "cash": cash,
            "initial_nav": initial_nav,
            "positions_value": positions_value,
            "num_positions": len(positions),
            "return_pct": ret,
            "high_water_mark": float(row.get("high_water_mark", 0)),
            "total_realized_pnl": float(row.get("total_realized_pnl", 0)),
            "total_transaction_costs": float(row.get("total_transaction_costs", 0)),
        })
    return results


@st.cache_data(ttl=60)
def get_portfolio_state(portfolio_id: str) -> dict | None:
    """Load full portfolio state including flattened positions list.

    Positions are stored as JSONB ``{ticker: {fields...}}`` in Supabase.
    This function flattens them into a list for easy DataFrame rendering.
    """
    try:
        client = _get_supabase_client()
        resp = (
            client.table("portfolio_state")
            .select("*")
            .eq("portfolio_id", portfolio_id)
            .execute()
        )
    except Exception:
        logger.debug("portfolio_state table not available")
        return None

    if not resp.data:
        return None

    row = resp.data[0]
    positions = row.get("positions", {})
    if not isinstance(positions, dict):
        positions = {}

    # Flatten JSONB positions into a list of dicts
    positions_list = []
    for ticker, pos in sorted(positions.items()):
        if not isinstance(pos, dict):
            continue
        positions_list.append({
            "ticker": ticker,
            "shares": float(pos.get("shares", 0)),
            "avg_cost": float(pos.get("avg_cost", 0)),
            "current_price": float(pos.get("current_price", 0)),
            "market_value": float(pos.get("market_value", 0)),
            "unrealized_pnl": float(pos.get("unrealized_pnl", 0)),
            "unrealized_pnl_pct": float(pos.get("unrealized_pnl_pct", 0)),
            "weight_pct": float(pos.get("weight_pct", 0)),
            "moa": pos.get("moa", ""),
            "catalyst_date": pos.get("catalyst_date"),
            "stop_loss_price": float(pos.get("stop_loss_price", 0)),
            "stop_loss_type": pos.get("stop_loss_type", "HARD"),
            "entry_date": pos.get("entry_date"),
            "entry_reason": pos.get("entry_reason", ""),
            "review_date": pos.get("review_date"),
            "pending_orders": pos.get("pending_orders", []),
            "take_profit_levels": pos.get("take_profit_levels", []),
            "entry_spread_bps": float(pos.get("entry_spread_bps", 30)),
            "entry_impact_bps": float(pos.get("entry_impact_bps", 10)),
        })

    cash = float(row.get("cash", 0))
    positions_value = sum(p["market_value"] for p in positions_list)
    nav = cash + positions_value
    initial_nav = float(row.get("initial_nav", 0))
    hwm = float(row.get("high_water_mark", nav))

    # MoA exposure breakdown
    moa_exposure: dict[str, float] = {}
    for p in positions_list:
        moa = p["moa"] or "Unknown"
        moa_exposure[moa] = moa_exposure.get(moa, 0) + (
            p["market_value"] / nav * 100 if nav > 0 else 0
        )

    return {
        "portfolio_id": row["portfolio_id"],
        "portfolio_label": row.get("portfolio_label", ""),
        "inception_date": row.get("inception_date"),
        "initial_nav": initial_nav,
        "nav": nav,
        "cash": cash,
        "positions_value": positions_value,
        "num_positions": len(positions_list),
        "high_water_mark": hwm,
        "total_realized_pnl": float(row.get("total_realized_pnl", 0)),
        "total_transaction_costs": float(row.get("total_transaction_costs", 0)),
        "return_pct": (nav - initial_nav) / initial_nav if initial_nav > 0 else 0.0,
        "drawdown_pct": (nav - hwm) / hwm if hwm > 0 else 0.0,
        "positions": positions_list,
        "moa_exposure": moa_exposure,
    }


@st.cache_data(ttl=60)
def get_portfolio_trades(portfolio_id: str, limit: int = 100) -> list[dict]:
    """Load trade history for a portfolio, most recent first."""
    try:
        client = _get_supabase_client()
        resp = (
            client.table("portfolio_trades")
            .select("*")
            .eq("portfolio_id", portfolio_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception:
        logger.debug("portfolio_trades table not available")
        return []


@st.cache_data(ttl=300)
def get_portfolio_snapshots(portfolio_id: str) -> list[dict]:
    """Load daily NAV snapshots for a single portfolio (chronological)."""
    try:
        client = _get_supabase_client()
        resp = (
            client.table("portfolio_snapshots")
            .select("*")
            .eq("portfolio_id", portfolio_id)
            .order("snapshot_date", desc=False)
            .execute()
        )
        return resp.data or []
    except Exception:
        logger.debug("portfolio_snapshots table not available")
        return []


@st.cache_data(ttl=300)
def get_all_portfolio_snapshots() -> dict[str, list[dict]]:
    """Load snapshots for ALL portfolios (for multi-portfolio NAV overlay).

    Returns ``{portfolio_id: [snapshot_dicts...]}`` grouped by portfolio.
    """
    try:
        client = _get_supabase_client()
        resp = (
            client.table("portfolio_snapshots")
            .select("*")
            .order("snapshot_date", desc=False)
            .execute()
        )
    except Exception:
        logger.debug("portfolio_snapshots table not available")
        return {}

    result: dict[str, list[dict]] = {}
    for row in resp.data or []:
        pid = row.get("portfolio_id", "default")
        result.setdefault(pid, []).append(row)
    return result


# ---------------------------------------------------------------------------
# Report requests
# ---------------------------------------------------------------------------


def submit_report_request(
    ticker: str,
    requested_by: str,
    request_type: str = "full_analysis",
    priority: str = "normal",
    notes: str | None = None,
) -> dict:
    """Insert a new report request into Supabase.

    Returns the inserted row data.
    Raises ValueError on invalid inputs or duplicate pending requests.
    """
    ticker = ticker.upper()

    if not re.match(r'^[A-Z]{1,10}$', ticker):
        raise ValueError(f"Invalid ticker format: '{ticker}'. Must be 1-10 uppercase letters.")
    if notes and len(notes) > 2000:
        raise ValueError("Notes must be under 2000 characters.")

    if request_type not in VALID_REQUEST_TYPES:
        raise ValueError(
            f"Invalid request_type '{request_type}'. "
            f"Must be one of: {', '.join(sorted(VALID_REQUEST_TYPES))}"
        )
    if priority not in VALID_PRIORITIES:
        raise ValueError(
            f"Invalid priority '{priority}'. "
            f"Must be one of: {', '.join(sorted(VALID_PRIORITIES))}"
        )

    client = _get_supabase_client()

    # Check for duplicate pending request
    resp = (
        client.table("report_requests")
        .select("id")
        .eq("ticker", ticker)
        .eq("status", "pending")
        .limit(1)
        .execute()
    )
    if resp.data:
        raise ValueError(f"A pending request already exists for {ticker}")

    # Resolve company name via FMP
    profiles = get_company_profiles((ticker,))
    company_name = profiles.get(ticker, ticker)

    row: dict = {
        "ticker": ticker,
        "company_name": company_name,
        "requested_by": requested_by,
        "request_type": request_type,
        "priority": priority,
        "status": "pending",
    }
    if notes:
        row["notes"] = notes

    resp = client.table("report_requests").insert(row).execute()
    logger.info("Report request submitted: %s by %s", ticker, requested_by)

    return resp.data[0] if resp.data else row
