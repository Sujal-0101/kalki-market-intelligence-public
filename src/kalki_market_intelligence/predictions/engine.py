"""Deterministic outcome jobs and evaluation reports."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal, localcontext
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from kalki_market_intelligence.predictions.calibration import summarize_binary_outcomes
from kalki_market_intelligence.predictions.contracts import (
    EvaluationReport,
    EvaluationRule,
    JobStatus,
    ObservationOrigin,
    OutcomeAssessment,
    OutcomeEvaluationInput,
    OutcomeJob,
    OutcomeRecord,
    PredictionRecord,
)
from kalki_market_intelligence.quantitative.algorithms import CALCULATION_CONTEXT


class OutcomeEvaluator:
    """Calculate declared-horizon returns without changing the prediction."""

    def job_for(
        self,
        prediction: PredictionRecord,
        observed_at: datetime,
        existing_outcomes: tuple[OutcomeRecord, ...] = (),
    ) -> OutcomeJob:
        outcome = next(
            (
                item
                for item in reversed(existing_outcomes)
                if item.prediction_id == prediction.prediction_id
            ),
            None,
        )
        if outcome is not None:
            status = JobStatus.COMPLETED
            explanation = "An appended outcome already records this prediction evaluation."
        elif observed_at.date() < prediction.evaluation_due_on:
            status = JobStatus.NOT_DUE
            explanation = "The prediction has not reached its declared horizon."
        else:
            status = JobStatus.READY
            explanation = "The prediction reached its declared horizon and is ready for inputs."
        return OutcomeJob(
            prediction_id=prediction.prediction_id,
            evaluation_due_on=prediction.evaluation_due_on,
            observed_at=observed_at,
            status=status,
            outcome_id=outcome.outcome_id if outcome else None,
            explanation=explanation,
        )

    def evaluate(self, inputs: OutcomeEvaluationInput) -> OutcomeRecord:
        observations = (
            inputs.asset_start,
            inputs.asset_end,
            inputs.benchmark_start,
            inputs.benchmark_end,
        )
        complete = all(item is not None for item in observations)
        hashes = tuple(
            sha256(item.model_dump_json().encode()).hexdigest()
            for item in observations
            if item is not None
        )
        action_hashes = tuple(
            sha256(item.model_dump_json().encode()).hexdigest() for item in inputs.corporate_actions
        )
        identifier = uuid5(
            NAMESPACE_URL,
            f"kalki-outcome:{inputs.prediction.prediction_id}:{inputs.evaluated_at.isoformat()}:{','.join(hashes)}",
        )
        if not complete:
            limitations = (*inputs.limitations, "Complete horizon observations were unavailable.")
            return OutcomeRecord(
                outcome_id=identifier,
                prediction_id=inputs.prediction.prediction_id,
                appended_at=inputs.evaluated_at,
                evaluated_at=inputs.evaluated_at,
                knowledge_cutoff_at=inputs.knowledge_cutoff_at,
                security_status=inputs.security_status,
                asset_return=None,
                benchmark_return=None,
                benchmark_relative_return=None,
                assessment=OutcomeAssessment.UNAVAILABLE,
                evaluation_rule=inputs.prediction.evaluation_rule,
                observation_hashes=hashes,
                corporate_action_ids=tuple(item.action_id for item in inputs.corporate_actions),
                corporate_action_hashes=action_hashes,
                limitations=limitations,
                observation_origin=inputs.observation_origin,
            )
        asset_start, asset_end, benchmark_start, benchmark_end = observations
        assert asset_start and asset_end and benchmark_start and benchmark_end
        include_cash = (
            inputs.prediction.evaluation_rule is EvaluationRule.TOTAL_RETURN_AND_BENCHMARK
        )
        with localcontext(CALCULATION_CONTEXT):
            asset_cash = asset_end.cash_distributions_per_share if include_cash else Decimal(0)
            benchmark_cash = (
                benchmark_end.cash_distributions_per_share if include_cash else Decimal(0)
            )
            asset_return = (asset_end.price + asset_cash) / asset_start.price - 1
            benchmark_return = (benchmark_end.price + benchmark_cash) / benchmark_start.price - 1
            relative = asset_return - benchmark_return
        assessment = (
            OutcomeAssessment.POSITIVE_ABSOLUTE_AND_RELATIVE
            if asset_return > 0 and relative > 0
            else OutcomeAssessment.POSITIVE_ABSOLUTE_ONLY
            if asset_return > 0
            else OutcomeAssessment.NON_POSITIVE
        )
        return OutcomeRecord(
            outcome_id=identifier,
            prediction_id=inputs.prediction.prediction_id,
            appended_at=inputs.evaluated_at,
            evaluated_at=inputs.evaluated_at,
            knowledge_cutoff_at=inputs.knowledge_cutoff_at,
            security_status=inputs.security_status,
            asset_return=asset_return,
            benchmark_return=benchmark_return,
            benchmark_relative_return=relative,
            assessment=assessment,
            evaluation_rule=inputs.prediction.evaluation_rule,
            observation_hashes=hashes,
            corporate_action_ids=tuple(item.action_id for item in inputs.corporate_actions),
            corporate_action_hashes=action_hashes,
            limitations=inputs.limitations,
            observation_origin=inputs.observation_origin,
        )

    def report(
        self,
        predictions: tuple[PredictionRecord, ...],
        outcomes: tuple[OutcomeRecord, ...],
        generated_at: datetime,
    ) -> EvaluationReport:
        prediction_ids = {item.prediction_id for item in predictions}
        selected: dict[object, OutcomeRecord] = {}
        for outcome in outcomes:
            if outcome.prediction_id not in prediction_ids:
                raise ValueError("evaluation report contains an outcome for an unknown prediction")
            current = selected.get(outcome.prediction_id)
            if current is None or outcome.appended_at > current.appended_at:
                selected[outcome.prediction_id] = outcome
        values = tuple(selected.values())
        available = tuple(item for item in values if item.asset_return is not None)
        # Reconstructed observations remain visible in counts, but must never
        # be blended into forward performance or calibration statistics.
        forward_available = tuple(
            item for item in available if item.observation_origin is ObservationOrigin.FORWARD
        )
        mean_asset = self._mean(tuple(item.asset_return for item in forward_available))
        mean_relative = self._mean(
            tuple(item.benchmark_relative_return for item in forward_available)
        )
        return EvaluationReport(
            generated_at=generated_at,
            knowledge_cutoff_at=generated_at,
            prediction_count=len(predictions),
            evaluated_count=len(values),
            unavailable_count=sum(
                item.assessment is OutcomeAssessment.UNAVAILABLE for item in values
            ),
            status_counts=dict(Counter(item.security_status for item in values)),
            assessment_counts=dict(Counter(item.assessment for item in values)),
            mean_asset_return=mean_asset,
            mean_benchmark_relative_return=mean_relative,
            limitations=(
                "Descriptive outcomes only; the sample is not a calibrated performance claim.",
                "Latest appended outcome per prediction is included.",
            ),
            inference_status="descriptive_only" if len(forward_available) >= 30 else "inconclusive",
            forward_observation_count=sum(
                item.observation_origin.value == "forward" for item in values
            ),
            reconstructed_observation_count=sum(
                item.observation_origin.value == "reconstructed" for item in values
            ),
            calibration=summarize_binary_outcomes(
                sum(
                    item.assessment is OutcomeAssessment.POSITIVE_ABSOLUTE_AND_RELATIVE
                    for item in forward_available
                ),
                len(forward_available),
            ),
        )

    @staticmethod
    def _mean(values: tuple[Decimal | None, ...]) -> Decimal | None:
        present = tuple(value for value in values if value is not None)
        if not present:
            return None
        with localcontext(CALCULATION_CONTEXT):
            return sum(present, Decimal(0)) / Decimal(len(present))
