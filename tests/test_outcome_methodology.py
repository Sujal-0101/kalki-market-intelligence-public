"""Pre-registered outcome methodology remains explicit and bounded."""

from kalki_market_intelligence.predictions import ObservationOrigin, OutcomeMethodologyManifest
from kalki_market_intelligence.predictions.contracts import EvaluationRule


def test_methodology_manifest_separates_origins_and_benchmark_rule() -> None:
    manifest = OutcomeMethodologyManifest(
        horizon_days=30,
        evaluation_rule=EvaluationRule.PRICE_RETURN_AND_BENCHMARK,
    )
    assert manifest.methodology_version == "outcome-method-v1"
    assert manifest.benchmark_required
    assert ObservationOrigin.FORWARD in manifest.observation_origins
