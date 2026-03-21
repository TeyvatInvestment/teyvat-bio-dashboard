"""Eval scorer — compare pipeline predictions against catalyst outcomes.

Computes 6 core metrics:
1. Hit Rate — % of BUY recommendations with positive returns
2. Avoidance Rate — % of PASS/MONITOR that avoided >20% losses
3. PTS Calibration — Brier score for science PTS vs binary outcome
4. PTS Gap Signal — Spearman correlation between pts_gap and realized return
5. rNPV Accuracy — mean absolute error of rNPV vs realized price
6. Risk Manager Value — % of rejections that avoided >30% losses

Standalone copy — no imports from the research pipeline.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from models import CatalystOutcome, EvalDataset, PipelinePrediction


@dataclass
class BucketMetrics:
    bucket_name: str
    n_events: int = 0
    hit_rate: float | None = None
    avoidance_rate: float | None = None
    mean_pts_gap: float = 0.0
    mean_return: float = 0.0


@dataclass
class StratifiedMetrics:
    by_event_type: list[BucketMetrics] = field(default_factory=list)
    by_conviction: list[BucketMetrics] = field(default_factory=list)
    by_data_quality: list[BucketMetrics] = field(default_factory=list)


@dataclass
class EventEvalDetail:
    ticker: str
    event_type: str
    outcome: str
    price_change_pct: float
    mean_science_pts: float
    mean_market_pts: float
    mean_pts_gap: float
    mean_rnpv: float
    mean_conviction: float
    action: str
    risk_decision: str
    n_runs: int
    science_pts_std: float
    rnpv_std: float
    conviction_std: float
    hit: bool | None
    avoided: bool | None


@dataclass
class EvalResult:
    n_events: int = 0
    n_predictions: int = 0
    n_paired: int = 0
    hit_rate: float | None = None
    avoidance_rate: float | None = None
    pts_brier_score: float | None = None
    pts_gap_spearman_rho: float | None = None
    pts_gap_p_value: float | None = None
    rnpv_mean_error_pct: float | None = None
    risk_manager_save_rate: float | None = None
    conviction_return_corr: float | None = None
    mean_data_quality: float = 0.0
    per_event: list[EventEvalDetail] = field(default_factory=list)
    stratified: StratifiedMetrics | None = None
    n_outcomes_without_predictions: int = 0
    n_predictions_without_outcomes: int = 0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return math.sqrt(variance)


def _majority(values: list[str]) -> str:
    counts: dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return max(counts, key=lambda k: (counts[k], k))


def _spearman_rank_correlation(x: list[float], y: list[float]) -> tuple[float, float]:
    n = len(x)
    if n < 3:
        return 0.0, 1.0

    def _rank(values: list[float]) -> list[float]:
        indexed = sorted(enumerate(values), key=lambda t: t[1])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n - 1 and indexed[j + 1][1] == indexed[j][1]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[indexed[k][0]] = avg_rank
            i = j + 1
        return ranks

    rx = _rank(x)
    ry = _rank(y)
    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n
    cov = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
    std_rx = math.sqrt(sum((r - mean_rx) ** 2 for r in rx))
    std_ry = math.sqrt(sum((r - mean_ry) ** 2 for r in ry))

    if std_rx == 0 or std_ry == 0:
        return 0.0, 1.0

    rho = cov / (std_rx * std_ry)

    if abs(rho) >= 1.0:
        p_value = 0.0
    else:
        t_stat = rho * math.sqrt((n - 2) / (1 - rho * rho))
        p_value = 2 * _normal_sf(abs(t_stat))

    return rho, p_value


def _normal_sf(x: float) -> float:
    if x < 0:
        return 1.0 - _normal_sf(-x)
    p = 0.2316419
    b1, b2, b3, b4, b5 = 0.319381530, -0.356563782, 1.781477937, -1.821255978, 1.330274429
    t = 1.0 / (1.0 + p * x)
    pdf = math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)
    return pdf * t * (b1 + t * (b2 + t * (b3 + t * (b4 + t * b5))))


def _evaluate_event(
    outcome: CatalystOutcome,
    predictions: list[PipelinePrediction],
) -> EventEvalDetail:
    pts_values = [p.science_pts for p in predictions]
    mkt_values = [p.market_pts for p in predictions]
    gap_values = [p.pts_gap for p in predictions]
    rnpv_values = [p.rnpv_per_share for p in predictions]
    conv_values = [float(p.net_conviction) for p in predictions]
    actions = [p.action for p in predictions]
    risk_decisions = [p.risk_decision for p in predictions]

    n = len(predictions)
    majority_action = _majority(actions)
    majority_risk = _majority(risk_decisions)

    hit = None
    avoided = None
    if majority_action == "BUY":
        hit = outcome.price_change_pct > 0
    else:
        avoided = outcome.price_change_pct < -0.20

    return EventEvalDetail(
        ticker=outcome.ticker,
        event_type=outcome.event_type,
        outcome=outcome.outcome,
        price_change_pct=outcome.price_change_pct,
        mean_science_pts=sum(pts_values) / n,
        mean_market_pts=sum(mkt_values) / n,
        mean_pts_gap=sum(gap_values) / n,
        mean_rnpv=sum(rnpv_values) / n,
        mean_conviction=sum(conv_values) / n,
        action=majority_action,
        risk_decision=majority_risk,
        n_runs=n,
        science_pts_std=_std(pts_values),
        rnpv_std=_std(rnpv_values),
        conviction_std=_std(conv_values),
        hit=hit,
        avoided=avoided,
    )


def _compute_bucket(name: str, details: list[EventEvalDetail]) -> BucketMetrics:
    if not details:
        return BucketMetrics(bucket_name=name)

    buy_events = [d for d in details if d.action == "BUY"]
    pass_events = [d for d in details if d.action in ("PASS", "MONITOR")]

    hit_rate = None
    if buy_events:
        hits = sum(1 for d in buy_events if d.hit is True)
        hit_rate = hits / len(buy_events)

    avoidance_rate = None
    if pass_events:
        avoided = sum(1 for d in pass_events if d.avoided is True)
        avoidance_rate = avoided / len(pass_events)

    mean_gap = sum(d.mean_pts_gap for d in details) / len(details)
    mean_ret = sum(d.price_change_pct for d in details) / len(details)

    return BucketMetrics(
        bucket_name=name,
        n_events=len(details),
        hit_rate=hit_rate,
        avoidance_rate=avoidance_rate,
        mean_pts_gap=mean_gap,
        mean_return=mean_ret,
    )


def _compute_stratified_metrics(details: list[EventEvalDetail]) -> StratifiedMetrics:
    by_type: dict[str, list[EventEvalDetail]] = {}
    for d in details:
        by_type.setdefault(d.event_type, []).append(d)
    type_buckets = [_compute_bucket(et, evts) for et, evts in sorted(by_type.items())]

    conv_groups: dict[str, list[EventEvalDetail]] = {
        "low (1-3)": [],
        "medium (4-6)": [],
        "high (7-10)": [],
    }
    for d in details:
        c = d.mean_conviction
        if c <= 3:
            conv_groups["low (1-3)"].append(d)
        elif c <= 6:
            conv_groups["medium (4-6)"].append(d)
        else:
            conv_groups["high (7-10)"].append(d)
    conv_buckets = [_compute_bucket(name, evts) for name, evts in conv_groups.items() if evts]

    return StratifiedMetrics(
        by_event_type=type_buckets,
        by_conviction=conv_buckets,
        by_data_quality=[],
    )


def score_predictions(dataset: EvalDataset) -> EvalResult:
    """Score all predictions against outcomes, computing the 6 core metrics."""
    pairs = dataset.paired()

    result = EvalResult(
        n_events=len(dataset.outcomes),
        n_predictions=len(dataset.predictions),
        n_paired=len(pairs),
        n_outcomes_without_predictions=len(dataset.unpaired_outcomes),
        n_predictions_without_outcomes=len(dataset.unpaired_predictions),
    )

    if not pairs:
        return result

    details = []
    for outcome, preds in pairs:
        detail = _evaluate_event(outcome, preds)
        details.append(detail)
    result.per_event = details

    all_dq = [p.data_quality_score for p in dataset.predictions]
    result.mean_data_quality = sum(all_dq) / len(all_dq) if all_dq else 0.0

    # Metric 1: Hit Rate
    buy_events = [d for d in details if d.action == "BUY"]
    if buy_events:
        hits = sum(1 for d in buy_events if d.hit is True)
        result.hit_rate = hits / len(buy_events)

    # Metric 2: Avoidance Rate
    pass_events = [d for d in details if d.action in ("PASS", "MONITOR")]
    if pass_events:
        avoided = sum(1 for d in pass_events if d.avoided is True)
        result.avoidance_rate = avoided / len(pass_events)

    # Metric 3: PTS Calibration (Brier Score)
    success_outcomes = {"APPROVED", "MET_ENDPOINT"}
    brier_terms = []
    for detail in details:
        actual = 1.0 if detail.outcome in success_outcomes else 0.0
        brier_terms.append((detail.mean_science_pts - actual) ** 2)
    result.pts_brier_score = sum(brier_terms) / len(brier_terms)

    # Metric 4: PTS Gap Signal (Spearman)
    gaps = [d.mean_pts_gap for d in details]
    returns = [d.price_change_pct for d in details]
    rho, p_val = _spearman_rank_correlation(gaps, returns)
    result.pts_gap_spearman_rho = rho
    result.pts_gap_p_value = p_val

    # Metric 5: rNPV Accuracy
    rnpv_errors = []
    for detail, (outcome, _) in zip(details, pairs):
        if outcome.price_before > 0:
            error = abs(detail.mean_rnpv - outcome.price_after) / outcome.price_before
            rnpv_errors.append(error)
    if rnpv_errors:
        result.rnpv_mean_error_pct = sum(rnpv_errors) / len(rnpv_errors)

    # Metric 6: Risk Manager Save Rate
    rejected_events = [d for d in details if d.risk_decision == "REJECTED"]
    if rejected_events:
        saves = sum(1 for d in rejected_events if d.price_change_pct < -0.30)
        result.risk_manager_save_rate = saves / len(rejected_events)

    # Supplementary: Conviction-Return Correlation
    convictions = [d.mean_conviction for d in details]
    abs_returns = [abs(d.price_change_pct) for d in details]
    conv_rho, _ = _spearman_rank_correlation(convictions, abs_returns)
    result.conviction_return_corr = conv_rho

    # Stratified Metrics
    if len(details) >= 2:
        result.stratified = _compute_stratified_metrics(details)

    return result
