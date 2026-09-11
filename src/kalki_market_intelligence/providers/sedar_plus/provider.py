"""Provider protocol and safe unavailable implementation for SEDAR+."""

from __future__ import annotations

from typing import Protocol

from kalki_market_intelligence.providers.sedar_plus.contracts import (
    CanadianProfileId,
    LicensedDisclosureEnvelope,
)


class SedarPlusAutomationUnavailable(RuntimeError):
    """No authorized automated SEDAR+ source has been configured."""


class SedarPlusProvider(Protocol):
    """Future adapter implemented only under a reviewed written authorization."""

    def fetch_disclosures(
        self, profile_id: CanadianProfileId
    ) -> tuple[LicensedDisclosureEnvelope, ...]: ...


class UnavailableSedarPlusProvider:
    """Fail closed instead of calling the automation-restricted public website."""

    reason = (
        "SEDAR+ public-site automation and database construction are not authorized; "
        "configure a separately reviewed licensed distribution or approved ad-hoc source"
    )

    def fetch_disclosures(
        self, profile_id: CanadianProfileId
    ) -> tuple[LicensedDisclosureEnvelope, ...]:
        raise SedarPlusAutomationUnavailable(self.reason)
