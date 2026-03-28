"""Watchlist builder — track predictions awaiting catalyst resolution.

Standalone copy — no imports from the research pipeline.
"""

from __future__ import annotations

from datetime import date

from models import CatalystOutcome, PipelinePrediction, WatchlistEntry, experiments_match


def build_watchlist(
    predictions: list[PipelinePrediction],
    outcomes: list[CatalystOutcome],
    today: date | None = None,
) -> list[WatchlistEntry]:
    """Build a watchlist sorted by urgency: OVERDUE > DUE_SOON > UPCOMING > RECORDED."""
    if today is None:
        today = date.today()

    entries: list[WatchlistEntry] = []
    for pred in predictions:
        ticker = pred.ticker
        has_outcome = any(
            experiments_match(pred.ticker, pred.catalyst_type, o.ticker, o.event_type)
            for o in outcomes
        )

        if has_outcome:
            status = "RECORDED"
            days_until = None
        elif pred.catalyst_date is None:
            status = "UNKNOWN"
            days_until = None
        else:
            days_until = (pred.catalyst_date - today).days
            if days_until < 0:
                status = "OVERDUE"
            elif days_until <= 7:
                status = "DUE_SOON"
            else:
                status = "UPCOMING"

        entries.append(
            WatchlistEntry(
                ticker=ticker,
                company_name=pred.company_name,
                action=pred.action,
                catalyst_date=pred.catalyst_date,
                catalyst_type=pred.catalyst_type,
                pts_gap=pred.pts_gap,
                net_conviction=pred.net_conviction,
                science_pts=pred.science_pts,
                market_pts=pred.market_pts,
                run_date=pred.run_timestamp.date(),
                status=status,
                days_until=days_until,
                success_price=pred.success_price,
                failure_price=pred.failure_price,
                rnpv_per_share=pred.rnpv_per_share,
                current_price_at_pred=pred.current_price,
            )
        )

    status_order = {"OVERDUE": 0, "DUE_SOON": 1, "UPCOMING": 2, "UNKNOWN": 3, "RECORDED": 4}
    entries.sort(key=lambda e: (status_order.get(e.status, 5), e.days_until or 999))

    return entries
