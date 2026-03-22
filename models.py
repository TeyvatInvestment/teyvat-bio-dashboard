"""Standalone Pydantic models for the eval dashboard.

These are self-contained copies of the models from the main repo,
with no imports from the research pipeline codebase.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class CatalystOutcome(BaseModel):
    """A historical catalyst event with known outcome and price impact."""

    ticker: str
    company_name: str
    event_type: str
    event_date: date
    outcome: str
    price_before: float
    price_after: float
    price_change_pct: float
    price_30d_after: float | None = None
    notes: str | None = None


class PipelinePrediction(BaseModel):
    """Snapshot of pipeline output for a given ticker."""

    ticker: str
    company_name: str = ""
    run_id: str
    run_timestamp: datetime
    snapshot_ref: str | None = None

    # Bio Analyst
    science_pts: float = Field(ge=0.0, le=1.0)
    development_stage: str
    evidence_quality: int = Field(ge=1, le=10)
    next_catalyst: str = ""
    catalyst_date: date | None = None

    # Fin Analyst
    market_pts: float = Field(ge=0.0, le=1.0)
    rnpv_per_share: float
    success_price: float | None = None
    failure_price: float | None = None
    current_price: float
    upside_pct: float

    # Thesis
    pts_gap: float

    # Portfolio Manager
    action: str
    net_conviction: int = Field(ge=1, le=10)
    bull_conviction: int = Field(ge=1, le=10)
    bear_conviction: int = Field(ge=1, le=10)
    proposed_size_pct: float

    # Risk Manager
    risk_decision: str
    approved_size_pct: float
    violated_rules: list[str] = []

    # Execution Planner
    entry_price_limit: float | None = None
    stop_loss_price: float | None = None
    execution_plan: dict | None = None  # Full serialized ExecutionPlan (JSONB)

    # Quality
    data_quality_score: float
    data_warnings: list[str] = []
    trace_path: str | None = None


class EvalDataset(BaseModel):
    """Collection of outcomes and their paired predictions for scoring."""

    outcomes: list[CatalystOutcome] = []
    predictions: list[PipelinePrediction] = []

    def paired(self) -> list[tuple[CatalystOutcome, list[PipelinePrediction]]]:
        """Return outcomes paired with their matching predictions."""
        pred_by_key: dict[tuple[str, date | None], list[PipelinePrediction]] = {}
        for p in self.predictions:
            key = (p.ticker, p.catalyst_date)
            pred_by_key.setdefault(key, []).append(p)

        pairs = []
        for outcome in self.outcomes:
            preds = pred_by_key.get((outcome.ticker, outcome.event_date), [])
            if not preds:
                preds = pred_by_key.get((outcome.ticker, None), [])
            if preds:
                pairs.append((outcome, preds))
        return pairs

    @property
    def unpaired_outcomes(self) -> list[CatalystOutcome]:
        pred_keys: set[tuple[str, date | None]] = {
            (p.ticker, p.catalyst_date) for p in self.predictions
        }
        pred_tickers_no_date = {k[0] for k in pred_keys if k[1] is None}
        unpaired = []
        for o in self.outcomes:
            if (o.ticker, o.event_date) in pred_keys:
                continue
            if o.ticker in pred_tickers_no_date:
                continue
            unpaired.append(o)
        return unpaired

    @property
    def unpaired_predictions(self) -> list[PipelinePrediction]:
        outcome_keys: set[tuple[str, date]] = {
            (o.ticker, o.event_date) for o in self.outcomes
        }
        outcome_tickers = {o.ticker for o in self.outcomes}
        unpaired = []
        for p in self.predictions:
            if p.catalyst_date and (p.ticker, p.catalyst_date) in outcome_keys:
                continue
            if not p.catalyst_date and p.ticker in outcome_tickers:
                continue
            unpaired.append(p)
        return unpaired


class WatchlistEntry(BaseModel):
    """A single prediction on the watchlist with urgency status."""

    ticker: str
    company_name: str = ""
    action: str
    catalyst_date: date | None
    pts_gap: float
    net_conviction: int
    science_pts: float
    market_pts: float
    run_date: date
    status: str  # UPCOMING | DUE_SOON | OVERDUE | RECORDED | UNKNOWN
    days_until: int | None = None
    success_price: float | None = None
    failure_price: float | None = None
    rnpv_per_share: float | None = None
