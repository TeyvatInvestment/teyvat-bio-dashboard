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
    price_event_day: float | None = None
    price_7d_after: float | None = None
    price_14d_after: float | None = None
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
    catalyst_type: str | None = None  # "PDUFA" | "Phase3_Readout" | "AdCom" | etc.

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

    # Batch tracking
    batch_id: str | None = None

    # Quality
    data_quality_score: float
    data_warnings: list[str] = []
    trace_path: str | None = None


def experiments_match(
    pred_ticker: str,
    pred_catalyst_type: str | None,
    outcome_ticker: str,
    outcome_event_type: str,
) -> bool:
    """Check if a prediction matches an outcome by experiment identity.

    Tier 1: (ticker, catalyst_type) match when prediction has catalyst_type.
    Tier 2: ticker only when prediction's catalyst_type is None (legacy data).
    No match when both have catalyst_type but they differ.
    """
    if pred_ticker != outcome_ticker:
        return False
    if pred_catalyst_type is not None:
        return pred_catalyst_type == outcome_event_type
    return True


class EvalDataset(BaseModel):
    """Collection of outcomes and their paired predictions for scoring."""

    outcomes: list[CatalystOutcome] = []
    predictions: list[PipelinePrediction] = []

    def paired(self) -> list[tuple[CatalystOutcome, list[PipelinePrediction]]]:
        """Return outcomes paired with their matching predictions.

        Uses 2-tier experiment identity matching via experiments_match().
        Predictions are shared across outcomes within the same tier.
        """
        pairs = []
        for outcome in self.outcomes:
            matched = [
                p for p in self.predictions
                if experiments_match(
                    p.ticker, p.catalyst_type, outcome.ticker, outcome.event_type
                )
            ]
            if matched:
                pairs.append((outcome, matched))
        return pairs

    @property
    def unpaired_outcomes(self) -> list[CatalystOutcome]:
        return [
            o for o in self.outcomes
            if not any(
                experiments_match(p.ticker, p.catalyst_type, o.ticker, o.event_type)
                for p in self.predictions
            )
        ]

    @property
    def unpaired_predictions(self) -> list[PipelinePrediction]:
        return [
            p for p in self.predictions
            if not any(
                experiments_match(p.ticker, p.catalyst_type, o.ticker, o.event_type)
                for o in self.outcomes
            )
        ]


class WatchlistEntry(BaseModel):
    """A single prediction on the watchlist with urgency status."""

    ticker: str
    company_name: str = ""
    action: str
    catalyst_date: date | None
    catalyst_type: str | None = None
    pts_gap: float
    net_conviction: int
    science_pts: float
    market_pts: float
    run_timestamp: datetime
    status: str  # UPCOMING | DUE_SOON | OVERDUE | RECORDED | UNKNOWN
    days_until: int | None = None
    success_price: float | None = None
    failure_price: float | None = None
    rnpv_per_share: float | None = None
    current_price_at_pred: float | None = None
