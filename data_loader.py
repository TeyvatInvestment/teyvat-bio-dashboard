"""Data loader — reads eval data from Supabase.

Deployed on Streamlit Community Cloud, this app reads ONLY from Supabase.
Credentials come from st.secrets (configured in the Community Cloud dashboard).
"""

from __future__ import annotations

import logging
from dataclasses import asdict

import streamlit as st
from supabase import create_client

from models import CatalystOutcome, EvalDataset, PipelinePrediction
from scorer import EvalResult, score_predictions
from watchlist import build_watchlist

logger = logging.getLogger(__name__)


def _get_supabase_client():
    """Create a Supabase sync client from st.secrets."""
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["service_key"]
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
        data_quality_score=row["data_quality_score"],
        data_warnings=row.get("data_warnings", []),
        trace_path=row.get("trace_path"),
    )


@st.cache_data(ttl=300)
def get_eval_dataset() -> dict:
    """Load and cache the full eval dataset from Supabase (5 min TTL).

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
    """Load report metadata from eval_reports table (5 min TTL)."""
    client = _get_supabase_client()
    query = client.table("eval_reports").select("*").order("report_timestamp", desc=True)
    if ticker:
        query = query.eq("ticker", ticker.upper())
    resp = query.execute()
    return resp.data


def get_report_content(storage_path: str) -> str:
    """Download a report's Markdown content from the reports storage bucket."""
    client = _get_supabase_client()
    content = client.storage.from_("reports").download(storage_path)
    return content.decode("utf-8")


@st.cache_data(ttl=600)
def get_current_prices(tickers: tuple[str, ...]) -> dict[str, dict | None]:
    """Fetch current prices for multiple tickers via FMP batch quote (cached 10 min).

    Uses a single API call for all tickers: /v3/quote/AAPL,MSFT,...
    Returns {ticker: {"price": float, "prev_close": float} | None}.
    """
    import asyncio

    import httpx

    api_key = st.secrets["fmp"]["api_key"]

    async def _fetch() -> dict[str, dict | None]:
        async with httpx.AsyncClient(timeout=10) as client:
            # FMP supports comma-separated tickers in a single request
            symbols = ",".join(tickers)
            resp = await client.get(
                f"https://financialmodelingprep.com/api/v3/quote/{symbols}",
                params={"apikey": api_key},
            )
            data = resp.json()

        results: dict[str, dict | None] = {t: None for t in tickers}
        if isinstance(data, list):
            for q in data:
                symbol = q.get("symbol", "")
                results[symbol] = {
                    "price": round(float(q.get("price", 0)), 2),
                    "prev_close": round(float(q.get("previousClose", 0)), 2),
                }
        return results

    try:
        return asyncio.run(_fetch())
    except Exception:
        return {t: None for t in tickers}
