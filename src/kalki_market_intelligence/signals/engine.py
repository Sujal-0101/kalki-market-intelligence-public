"""Deterministic Phase 8 rules for evidence-backed research signals."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from hashlib import sha256

from kalki_market_intelligence.analysis.contracts import (
    AnalystContradiction,
    AnalystFinding,
    ContradictionStatus,
    FindingCategory,
    ValidatedAnalysis,
)
from kalki_market_intelligence.contracts.common import ContractModel
from kalki_market_intelligence.contracts.evidence import SourceClass
from kalki_market_intelligence.quantitative.contracts import MetricResult
from kalki_market_intelligence.signals.contracts import (
    RESEARCH_DISCLAIMER,
    RULESET_VERSION,
    HeuristicScore,
    MissingInput,
    MissingSeverity,
    RiskProfile,
    RuleTrace,
    ScoreDimension,
    SignalLabel,
    SignalRequest,
    SignalResult,
)


class SignalEngine:
    """Apply a fixed, versioned ordinal ruleset without model arithmetic."""

    def evaluate(self, request: SignalRequest) -> SignalResult:
        metrics = {metric.metric_name: metric for metric in request.metrics}
        traces: list[RuleTrace] = []
        missing = self._missing_inputs(request, set(metrics))
        traces.extend(self._opportunity_traces(request, metrics))
        traces.extend(self._risk_traces(request, metrics))
        traces.extend(self._confidence_traces(request, set(metrics)))

        scores = {dimension: self._score(traces, dimension) for dimension in ScoreDimension}
        critical_missing = any(item.severity is MissingSeverity.CRITICAL for item in missing)
        label = self._label(
            scores[ScoreDimension.OPPORTUNITY],
            scores[ScoreDimension.RISK],
            scores[ScoreDimension.RESEARCH_CONFIDENCE],
            critical_missing,
        )
        profile = self._risk_profile(
            label,
            scores[ScoreDimension.OPPORTUNITY],
            scores[ScoreDimension.RISK],
            scores[ScoreDimension.RESEARCH_CONFIDENCE],
        )
        fingerprint = sha256(
            (RULESET_VERSION + "\n" + request.model_dump_json()).encode()
        ).hexdigest()
        return SignalResult(
            signal_fingerprint=fingerprint,
            research_subject_id=request.research_subject_id,
            as_of_date=request.as_of_date,
            knowledge_cutoff_at=request.knowledge_cutoff_at,
            horizon_days=request.horizon_days,
            opportunity=HeuristicScore(points=scores[ScoreDimension.OPPORTUNITY]),
            risk=HeuristicScore(points=scores[ScoreDimension.RISK]),
            research_confidence=HeuristicScore(points=scores[ScoreDimension.RESEARCH_CONFIDENCE]),
            label=label,
            risk_profile=profile,
            traces=tuple(traces),
            missing_inputs=tuple(missing),
            disclaimer=RESEARCH_DISCLAIMER,
        )

    @staticmethod
    def _score(traces: Iterable[RuleTrace], dimension: ScoreDimension) -> int:
        return min(100, max(0, sum(item.points for item in traces if item.dimension is dimension)))

    @staticmethod
    def _value(metric: MetricResult) -> Decimal:
        points = metric.points
        candidates = [point.value for point in points if point.component == "value"]
        return candidates[-1] if candidates else points[-1].value

    @staticmethod
    def _hash(contract: ContractModel) -> str:
        return sha256(contract.model_dump_json().encode()).hexdigest()

    def _metric_trace(
        self,
        *,
        metric: MetricResult,
        rule_id: str,
        dimension: ScoreDimension,
        points: int,
        explanation: str,
    ) -> RuleTrace:
        return RuleTrace(
            rule_id=rule_id,
            dimension=dimension,
            points=points,
            explanation=explanation,
            metric_names=(metric.metric_name,),
            input_hashes=(self._hash(metric),),
        )

    def _opportunity_traces(
        self, request: SignalRequest, metrics: dict[str, MetricResult]
    ) -> list[RuleTrace]:
        definitions = (
            ("cumulative_price_return", "opportunity.price_return", self._return_points),
            ("benchmark_relative_return", "opportunity.relative_return", self._relative_points),
            ("period_over_period_growth", "opportunity.growth", self._growth_points),
            ("gross_margin", "opportunity.margin", self._margin_points),
            ("price_to_earnings_ratio", "opportunity.valuation", self._valuation_points),
            ("relative_strength_index", "opportunity.rsi", self._rsi_points),
        )
        traces: list[RuleTrace] = []
        for name, rule_id, scorer in definitions:
            metric = metrics.get(name)
            if metric is None:
                continue
            value = self._value(metric)
            points = scorer(value)
            traces.append(
                self._metric_trace(
                    metric=metric,
                    rule_id=rule_id,
                    dimension=ScoreDimension.OPPORTUNITY,
                    points=points,
                    explanation=f"{name} mapped to {points} ordinal opportunity points.",
                )
            )
        qualifying = []
        for analysis in request.analyses:
            for finding in analysis.report.findings:
                if finding.category in {FindingCategory.CATALYST, FindingCategory.BULL_CASE}:
                    qualifying.append((analysis, finding))
        for index, (analysis, finding) in enumerate(qualifying[:2], start=1):
            evidence_ids = tuple(citation.evidence_id for citation in finding.citations)
            traces.append(
                RuleTrace(
                    rule_id=f"opportunity.qualitative.{index}",
                    dimension=ScoreDimension.OPPORTUNITY,
                    points=5,
                    explanation=(
                        "A validated catalyst or bull-case finding adds five ordinal points."
                    ),
                    analysis_roles=(analysis.report.role,),
                    evidence_ids=evidence_ids,
                    input_hashes=(self._hash(analysis),),
                )
            )
        if not traces:
            traces.append(self._zero_trace(ScoreDimension.OPPORTUNITY, "opportunity.no_inputs"))
        return traces

    def _risk_traces(
        self, request: SignalRequest, metrics: dict[str, MetricResult]
    ) -> list[RuleTrace]:
        definitions = (
            ("annualized_historical_volatility", "risk.volatility", self._volatility_points),
            ("maximum_drawdown", "risk.drawdown", self._drawdown_points),
            ("debt_to_equity_ratio", "risk.leverage", self._leverage_points),
        )
        traces: list[RuleTrace] = []
        for name, rule_id, scorer in definitions:
            metric = metrics.get(name)
            if metric is None:
                continue
            points = scorer(self._value(metric))
            traces.append(
                self._metric_trace(
                    metric=metric,
                    rule_id=rule_id,
                    dimension=ScoreDimension.RISK,
                    points=points,
                    explanation=f"{name} mapped to {points} ordinal risk points.",
                )
            )
        risky: list[tuple[ValidatedAnalysis, AnalystFinding]] = []
        contradictions: list[tuple[ValidatedAnalysis, AnalystContradiction]] = []
        for analysis in request.analyses:
            risky.extend(
                (analysis, finding)
                for finding in analysis.report.findings
                if finding.category in {FindingCategory.RISK, FindingCategory.BEAR_CASE}
            )
            contradictions.extend((analysis, item) for item in analysis.report.contradictions)
        for index, (analysis, finding) in enumerate(risky[:3], start=1):
            traces.append(
                RuleTrace(
                    rule_id=f"risk.qualitative.{index}",
                    dimension=ScoreDimension.RISK,
                    points=10,
                    explanation=(
                        "A validated risk or bear-case finding adds ten ordinal risk points."
                    ),
                    analysis_roles=(analysis.report.role,),
                    evidence_ids=tuple(c.evidence_id for c in finding.citations),
                    input_hashes=(self._hash(analysis),),
                )
            )
        for index, (analysis, contradiction) in enumerate(contradictions, start=1):
            unresolved = contradiction.status in {
                ContradictionStatus.CONFIRMED,
                ContradictionStatus.UNRESOLVED,
            }
            points = 15 if unresolved else 3
            traces.append(
                RuleTrace(
                    rule_id=f"risk.contradiction.{index}",
                    dimension=ScoreDimension.RISK,
                    points=points,
                    explanation=(
                        f"A {contradiction.status} contradiction adds {points} ordinal risk points."
                    ),
                    analysis_roles=(analysis.report.role,),
                    evidence_ids=tuple(c.evidence_id for c in contradiction.citations),
                    input_hashes=(self._hash(analysis),),
                )
            )
        if not traces:
            traces.append(self._zero_trace(ScoreDimension.RISK, "risk.no_inputs"))
        return traces

    def _confidence_traces(self, request: SignalRequest, names: set[str]) -> list[RuleTrace]:
        coverage = (
            ("confidence.momentum", {"cumulative_price_return"}, 10),
            ("confidence.benchmark", {"benchmark_relative_return"}, 10),
            (
                "confidence.fundamentals",
                {"period_over_period_growth", "gross_margin", "debt_to_equity_ratio"},
                10,
            ),
            ("confidence.valuation", {"price_to_earnings_ratio"}, 10),
        )
        traces = [
            RuleTrace(
                rule_id=rule_id,
                dimension=ScoreDimension.RESEARCH_CONFIDENCE,
                points=points,
                explanation=f"Required input coverage adds {points} research-confidence points.",
                metric_names=tuple(sorted(required & names)),
                input_hashes=tuple(
                    self._hash(metric)
                    for metric in request.metrics
                    if metric.metric_name in required
                ),
            )
            for rule_id, required, points in coverage
            if required & names
        ]
        risk_names = {"annualized_historical_volatility", "maximum_drawdown"} & names
        if risk_names:
            points = 15 if len(risk_names) == 2 else 8
            traces.append(
                RuleTrace(
                    rule_id="confidence.risk_coverage",
                    dimension=ScoreDimension.RESEARCH_CONFIDENCE,
                    points=points,
                    explanation=f"Risk-metric coverage adds {points} research-confidence points.",
                    metric_names=tuple(sorted(risk_names)),
                    input_hashes=tuple(
                        self._hash(metric)
                        for metric in request.metrics
                        if metric.metric_name in risk_names
                    ),
                )
            )
        if request.analyses:
            traces.append(
                RuleTrace(
                    rule_id="confidence.validated_analysis",
                    dimension=ScoreDimension.RESEARCH_CONFIDENCE,
                    points=15,
                    explanation=(
                        "Validated qualitative analysis adds fifteen research-confidence points."
                    ),
                    analysis_roles=tuple(item.report.role for item in request.analyses),
                    input_hashes=tuple(self._hash(item) for item in request.analyses),
                )
            )
        cited = {
            citation.evidence_id
            for analysis in request.analyses
            for finding in analysis.report.findings
            for citation in finding.citations
        } | {
            citation.evidence_id
            for analysis in request.analyses
            for contradiction in analysis.report.contradictions
            for citation in contradiction.citations
        }
        evidence_by_id = {item.evidence_id: item for item in request.evidence}
        source_weights = {
            SourceClass.SEC: 4,
            SourceClass.SEDAR_PLUS: 4,
            SourceClass.GOVERNMENT_REGULATORY: 4,
            SourceClass.COMPANY_IR: 3,
            SourceClass.OFFICIAL_RELEASE: 3,
            SourceClass.REPUTABLE_NEWS: 2,
            SourceClass.DISCOVERY_ONLY: 0,
        }
        evidence_points = min(
            20, sum(source_weights[evidence_by_id[item].source_class] for item in cited)
        )
        if cited:
            traces.append(
                RuleTrace(
                    rule_id="confidence.cited_sources",
                    dimension=ScoreDimension.RESEARCH_CONFIDENCE,
                    points=evidence_points,
                    explanation=(
                        f"Cited-source authority adds {evidence_points} research-confidence points."
                    ),
                    evidence_ids=tuple(sorted(cited, key=str)),
                    input_hashes=tuple(
                        self._hash(evidence_by_id[item]) for item in sorted(cited, key=str)
                    ),
                )
            )
        role_points = min(10, len(request.analyses) * 3)
        if request.analyses:
            traces.append(
                RuleTrace(
                    rule_id="confidence.role_diversity",
                    dimension=ScoreDimension.RESEARCH_CONFIDENCE,
                    points=role_points,
                    explanation=(
                        f"Distinct analyst roles add {role_points} research-confidence points."
                    ),
                    analysis_roles=tuple(item.report.role for item in request.analyses),
                    input_hashes=tuple(self._hash(item) for item in request.analyses),
                )
            )
        unresolved = [
            contradiction
            for analysis in request.analyses
            for contradiction in analysis.report.contradictions
            if contradiction.status
            in {ContradictionStatus.CONFIRMED, ContradictionStatus.UNRESOLVED}
        ]
        if unresolved:
            traces.append(
                RuleTrace(
                    rule_id="confidence.unresolved_contradiction",
                    dimension=ScoreDimension.RESEARCH_CONFIDENCE,
                    points=-15,
                    explanation=(
                        "Unresolved contradictory evidence removes fifteen "
                        "research-confidence points."
                    ),
                    evidence_ids=tuple(
                        citation.evidence_id for item in unresolved for citation in item.citations
                    ),
                )
            )
        if not traces:
            traces.append(
                self._zero_trace(ScoreDimension.RESEARCH_CONFIDENCE, "confidence.no_inputs")
            )
        return traces

    @staticmethod
    def _zero_trace(dimension: ScoreDimension, rule_id: str) -> RuleTrace:
        return RuleTrace(
            rule_id=rule_id,
            dimension=dimension,
            points=0,
            explanation="No qualifying inputs contributed ordinal points.",
        )

    @staticmethod
    def _missing_inputs(request: SignalRequest, names: set[str]) -> list[MissingInput]:
        checks = (
            ("momentum", {"cumulative_price_return"}, MissingSeverity.CRITICAL),
            ("benchmark", {"benchmark_relative_return"}, MissingSeverity.REDUCES_CONFIDENCE),
            (
                "fundamentals",
                {"period_over_period_growth", "gross_margin", "debt_to_equity_ratio"},
                MissingSeverity.REDUCES_CONFIDENCE,
            ),
            ("valuation", {"price_to_earnings_ratio"}, MissingSeverity.REDUCES_CONFIDENCE),
            (
                "risk_metrics",
                {"annualized_historical_volatility", "maximum_drawdown"},
                MissingSeverity.CRITICAL,
            ),
        )
        missing = [
            MissingInput(
                slot=slot,
                severity=severity,
                explanation=f"No qualifying {slot.replace('_', ' ')} input was supplied.",
            )
            for slot, alternatives, severity in checks
            if not (alternatives & names)
        ]
        if not request.analyses:
            missing.append(
                MissingInput(
                    slot="qualitative_analysis",
                    severity=MissingSeverity.CRITICAL,
                    explanation="No validated qualitative analysis was supplied.",
                )
            )
        cited = any(
            finding.citations
            for analysis in request.analyses
            for finding in analysis.report.findings
        ) or any(
            contradiction.citations
            for analysis in request.analyses
            for contradiction in analysis.report.contradictions
        )
        if not cited:
            missing.append(
                MissingInput(
                    slot="cited_evidence",
                    severity=MissingSeverity.CRITICAL,
                    explanation="No validated finding cites retrieved evidence.",
                )
            )
        return missing

    @staticmethod
    def _label(opportunity: int, risk: int, confidence: int, critical_missing: bool) -> SignalLabel:
        if critical_missing or confidence < 55:
            return SignalLabel.INSUFFICIENT_EVIDENCE
        if opportunity >= 70 and risk <= 35 and confidence >= 70:
            return SignalLabel.STRONG_OPPORTUNITY
        if opportunity >= 55 and risk > 60:
            return SignalLabel.SPECULATIVE_OPPORTUNITY
        if opportunity >= 55:
            return SignalLabel.MODERATE_OPPORTUNITY
        return SignalLabel.WEAK_OPPORTUNITY

    @staticmethod
    def _risk_profile(
        label: SignalLabel, opportunity: int, risk: int, confidence: int
    ) -> RiskProfile:
        if label is SignalLabel.INSUFFICIENT_EVIDENCE:
            return RiskProfile.UNCLASSIFIED
        if risk <= 35 and confidence >= 70:
            return RiskProfile.CONSERVATIVE
        if risk > 60 and opportunity >= 55:
            return RiskProfile.AGGRESSIVE_SPECULATIVE
        if risk > 35:
            return RiskProfile.ELEVATED_RISK
        return RiskProfile.BALANCED

    @staticmethod
    def _return_points(value: Decimal) -> int:
        return (
            0
            if value < 0
            else 5
            if value < Decimal("0.05")
            else 12
            if value < Decimal("0.15")
            else 18
            if value < Decimal("0.30")
            else 20
        )

    @staticmethod
    def _relative_points(value: Decimal) -> int:
        return (
            0
            if value < 0
            else 5
            if value < Decimal("0.05")
            else 10
            if value < Decimal("0.15")
            else 15
        )

    @staticmethod
    def _growth_points(value: Decimal) -> int:
        return (
            0
            if value < 0
            else 5
            if value < Decimal("0.10")
            else 10
            if value < Decimal("0.25")
            else 15
        )

    @staticmethod
    def _margin_points(value: Decimal) -> int:
        return (
            0
            if value < 0
            else 3
            if value < Decimal("0.20")
            else 6
            if value < Decimal("0.40")
            else 10
        )

    @staticmethod
    def _valuation_points(value: Decimal) -> int:
        return 10 if value <= 15 else 7 if value <= 25 else 4 if value <= 40 else 1

    @staticmethod
    def _rsi_points(value: Decimal) -> int:
        return (
            5
            if Decimal("40") <= value <= Decimal("70")
            else 3
            if Decimal("30") <= value <= Decimal("80")
            else 0
        )

    @staticmethod
    def _volatility_points(value: Decimal) -> int:
        return (
            5
            if value < Decimal("0.25")
            else 12
            if value < Decimal("0.45")
            else 20
            if value < Decimal("0.70")
            else 25
        )

    @staticmethod
    def _drawdown_points(value: Decimal) -> int:
        value = abs(value)
        return (
            5
            if value < Decimal("0.15")
            else 12
            if value < Decimal("0.30")
            else 20
            if value < Decimal("0.50")
            else 25
        )

    @staticmethod
    def _leverage_points(value: Decimal) -> int:
        return 3 if value < Decimal("0.5") else 8 if value < 1 else 14 if value < 2 else 20
