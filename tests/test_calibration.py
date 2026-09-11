"""Descriptive calibration remains honest for small samples."""

import pytest

from kalki_market_intelligence.predictions import summarize_binary_outcomes


def test_small_sample_is_inconclusive_with_bounded_interval() -> None:
    report = summarize_binary_outcomes(2, 5)
    assert report.status == "inconclusive"
    assert 0 <= report.wilson_lower <= report.positive_rate <= report.wilson_upper <= 1


def test_invalid_counts_are_rejected() -> None:
    with pytest.raises(ValueError):
        summarize_binary_outcomes(4, 3)
