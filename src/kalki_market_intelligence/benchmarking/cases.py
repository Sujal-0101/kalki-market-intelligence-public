"""Synthetic, deterministic qualitative-research benchmark cases."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from kalki_market_intelligence.contracts.common import ContractModel, ShortText


class ContractEventAnswer(ContractModel):
    """Structured extraction from a synthetic contract announcement."""

    issuer: ShortText
    event_type: Literal["contract_award"]
    counterparty: ShortText
    contract_value_cad_millions: float
    term_months: int
    profit_margin_disclosed: bool


class ContradictionAnswer(ContractModel):
    """Structured comparison of an original and corrected synthetic source."""

    source_a_revenue_cad_millions: float
    source_b_revenue_cad_millions: float
    contradiction_present: bool
    authoritative_source: Literal["A", "B"]
    revenue_to_use_cad_millions: float


class RiskAnswer(ContractModel):
    """Structured risk classification from a synthetic disclosure."""

    customer_concentration_risk: bool
    refinancing_risk: bool
    letter_of_intent_is_binding: bool
    revenue_is_guaranteed: bool


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """A prompt, response contract, and deterministic expected values."""

    name: str
    prompt: str
    response_model: type[ContractModel]
    expected: Mapping[str, object]


BENCHMARK_CASES = (
    BenchmarkCase(
        name="contract_event_extraction",
        prompt=(
            "The following source is synthetic test data, not a real announcement. "
            "Northstar Sensors Inc. announced that City Transit Authority awarded it a "
            "CAD 12.5 million equipment contract with a 36-month term. The announcement "
            "did not disclose the contract's profit margin. Extract only stated facts."
        ),
        response_model=ContractEventAnswer,
        expected={
            "issuer": "Northstar Sensors Inc.",
            "event_type": "contract_award",
            "counterparty": "City Transit Authority",
            "contract_value_cad_millions": 12.5,
            "term_months": 36,
            "profit_margin_disclosed": False,
        },
    ),
    BenchmarkCase(
        name="contradiction_detection",
        prompt=(
            "Compare two synthetic sources. Source A says fiscal Q2 revenue was CAD 18.0 "
            "million. Source B is a later correction that says fiscal Q2 revenue was CAD "
            "21.0 million and explicitly supersedes Source A. Identify the contradiction "
            "and which value should be used. Do not infer anything unstated."
        ),
        response_model=ContradictionAnswer,
        expected={
            "source_a_revenue_cad_millions": 18.0,
            "source_b_revenue_cad_millions": 21.0,
            "contradiction_present": True,
            "authoritative_source": "B",
            "revenue_to_use_cad_millions": 21.0,
        },
    ),
    BenchmarkCase(
        name="risk_classification",
        prompt=(
            "Classify only the risks stated in this synthetic disclosure: one customer "
            "provided 42% of revenue; all outstanding debt matures in nine months; and the "
            "company signed a non-binding letter of intent that does not guarantee revenue."
        ),
        response_model=RiskAnswer,
        expected={
            "customer_concentration_risk": True,
            "refinancing_risk": True,
            "letter_of_intent_is_binding": False,
            "revenue_is_guaranteed": False,
        },
    ),
)
