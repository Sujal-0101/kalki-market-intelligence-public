"""Disabled-by-default SEDAR+ boundary for a future authorized data source."""

from kalki_market_intelligence.providers.sedar_plus.provider import (
    SedarPlusAutomationUnavailable,
    UnavailableSedarPlusProvider,
)

__all__ = ["SedarPlusAutomationUnavailable", "UnavailableSedarPlusProvider"]
