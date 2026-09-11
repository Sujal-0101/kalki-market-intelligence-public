"""Deterministic explainable research-signal rules."""

from kalki_market_intelligence.signals.convergence import (
    ConvergenceObservation,
    ConvergenceResult,
    ObservationDirection,
    assess_convergence,
)
from kalki_market_intelligence.signals.engine import SignalEngine

__all__ = [
    "ConvergenceObservation",
    "ConvergenceResult",
    "ObservationDirection",
    "assess_convergence",
    "SignalEngine",
]
