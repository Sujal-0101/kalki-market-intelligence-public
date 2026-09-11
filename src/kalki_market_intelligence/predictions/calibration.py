"""Small-sample-safe descriptive calibration summaries."""

from __future__ import annotations

from math import sqrt
from typing import Literal

from pydantic import Field

from kalki_market_intelligence.contracts.common import ContractModel


class CalibrationReport(ContractModel):
    sample_size: int = Field(ge=0)
    positive_count: int = Field(ge=0)
    positive_rate: float = Field(ge=0, le=1)
    wilson_lower: float = Field(ge=0, le=1)
    wilson_upper: float = Field(ge=0, le=1)
    status: Literal["inconclusive", "descriptive"]


def summarize_binary_outcomes(positive_count: int, sample_size: int) -> CalibrationReport:
    """Return a Wilson interval and never imply significance for small samples."""

    if sample_size < 0 or positive_count < 0 or positive_count > sample_size:
        raise ValueError("outcome counts must be bounded and ordered")
    if sample_size == 0:
        return CalibrationReport(
            sample_size=0,
            positive_count=0,
            positive_rate=0,
            wilson_lower=0,
            wilson_upper=0,
            status="inconclusive",
        )
    rate = positive_count / sample_size
    z = 1.96
    denominator = 1 + z * z / sample_size
    center = (rate + z * z / (2 * sample_size)) / denominator
    margin = z * sqrt(rate * (1 - rate) / sample_size + z * z / (4 * sample_size**2)) / denominator
    return CalibrationReport(
        sample_size=sample_size,
        positive_count=positive_count,
        positive_rate=rate,
        wilson_lower=max(0.0, center - margin),
        wilson_upper=min(1.0, center + margin),
        status="descriptive" if sample_size >= 30 else "inconclusive",
    )
