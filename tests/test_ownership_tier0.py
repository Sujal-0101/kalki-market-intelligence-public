"""Conservative deterministic routing for SEC ownership context."""

from datetime import UTC, datetime

from kalki_market_intelligence.forensics import (
    AnalysisTier,
    OwnershipEventContext,
    TierOutcome,
    choose_ownership_tier,
)
from kalki_market_intelligence.providers.sec.ownership import (
    OwnershipFilingReceipt,
    OwnershipForm,
    parse_ownership_xml,
)

NOW = datetime(2026, 8, 29, tzinfo=UTC)


def _parse(body: str) -> OwnershipFilingReceipt:
    return parse_ownership_xml(
        body.encode(),
        accession_number="0001437749-26-029167",
        source_url="https://www.sec.gov/Archives/edgar/data/1/primary_doc.xml",
        accepted_at=NOW,
        retrieved_at=NOW,
    )


def test_insider_sale_is_retained_as_context_without_direction_or_model_work() -> None:
    filing = _parse(
        """<ownershipDocument><documentType>4</documentType>
        <periodOfReport>2026-08-26</periodOfReport><issuer><issuerCik>0001001385</issuerCik>
        <issuerName>NWPX Infrastructure, Inc.</issuerName></issuer><nonDerivativeTable>
        <nonDerivativeTransaction><securityTitle><value>Common Stock</value></securityTitle>
        <transactionDate><value>2026-08-26</value></transactionDate><transactionCoding>
        <transactionCode>S</transactionCode></transactionCoding><transactionAmounts>
        <transactionShares><value>4500</value></transactionShares>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
        </transactionAmounts></nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>"""
    )

    routed = choose_ownership_tier(filing)
    assert routed.event_context is OwnershipEventContext.INSIDER_OWNERSHIP_DISCLOSURE
    assert routed.decision.tier is AnalysisTier.TIER_0
    assert routed.decision.outcome is TierOutcome.RETAIN
    assert not routed.decision.requires_model
    assert "directional" in routed.decision.explanation


def test_form144_is_retained_as_a_planned_sale_notice_without_model_work() -> None:
    filing = _parse(
        """<edgarSubmission><headerData><submissionType>144</submissionType></headerData>
        <formData><issuerInfo><issuerCik>0001001250</issuerCik><issuerName>Issuer</issuerName>
        <nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>Seller</nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>
        </issuerInfo><securitiesInformation><securitiesClassTitle>Common</securitiesClassTitle>
        <noOfUnitsSold>10</noOfUnitsSold><approxSaleDate>08/28/2026</approxSaleDate>
        </securitiesInformation></formData></edgarSubmission>"""
    )

    routed = choose_ownership_tier(filing)
    assert routed.event_context is OwnershipEventContext.PLANNED_SALE_NOTICE
    assert routed.decision.tier is AnalysisTier.TIER_0
    assert not routed.decision.requires_model


def test_disclosed_13d_purpose_and_13g_transition_receive_bounded_review() -> None:
    filing = _parse(
        """<edgarSubmission><headerData><submissionType>SCHEDULE 13D</submissionType></headerData>
        <formData><coverPageHeader><dateOfEvent>04/08/2026</dateOfEvent><issuerInfo>
        <issuerCIK>0001000694</issuerCIK><issuerName>NOVAVAX, INC.</issuerName></issuerInfo>
        </coverPageHeader><reportingPersons><reportingPersonInfo>
        <reportingPersonName>Reporting Person</reportingPersonName>
        <aggregateAmountOwned>100</aggregateAmountOwned>
        </reportingPersonInfo></reportingPersons><items1To7><item4>
        <transactionPurpose>Exact disclosed control-purpose text.</transactionPurpose>
        </item4></items1To7></formData></edgarSubmission>"""
    )

    routed = choose_ownership_tier(filing, previous_schedule_form=OwnershipForm.SCHEDULE_13G_A)
    assert routed.event_context is OwnershipEventContext.SCHEDULE_TRANSITION
    assert routed.decision.tier is AnalysisTier.TIER_2
    assert routed.decision.outcome is TierOutcome.ESCALATE
    assert routed.decision.requires_model
