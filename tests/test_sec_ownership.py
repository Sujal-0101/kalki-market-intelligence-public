"""Primary-source SEC insider and beneficial-ownership parsing."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import HttpUrl

from kalki_market_intelligence.providers.sec.client import (
    SecFetchedDocument,
    SecFetchedPrimaryDocument,
)
from kalki_market_intelligence.providers.sec.contracts import SecFilingRecord
from kalki_market_intelligence.providers.sec.ownership import (
    ActivistControlIntentStatus,
    OwnershipFilingReceipt,
    OwnershipForm,
    OwnershipNature,
    OwnershipParseError,
    ScheduleTransition,
    SecOwnershipIngestionService,
    classify_schedule_transition,
    ownership_filing_from_submissions,
    parse_ownership_xml,
)

NOW = datetime(2026, 8, 29, tzinfo=UTC)


def parse(body: str, accession: str = "0001437749-26-029167") -> OwnershipFilingReceipt:
    return parse_ownership_xml(
        body.encode(),
        accession_number=accession,
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1001385/"
            f"{accession.replace('-', '')}/primary_doc.xml"
        ),
        accepted_at=NOW,
        retrieved_at=NOW,
    )


def test_real_form4_excerpt_preserves_code_sale_context_and_post_transaction_ownership() -> None:
    # Public SEC Form 4 accession 0001437749-26-029167, retrieved 2026-08-29.
    receipt = parse(
        """<ownershipDocument>
        <documentType>4</documentType><periodOfReport>2026-08-26</periodOfReport>
        <issuer><issuerCik>0001001385</issuerCik><issuerName>NWPX Infrastructure, Inc.</issuerName>
        <issuerTradingSymbol>NWPX</issuerTradingSymbol></issuer>
        <reportingOwner><reportingOwnerId><rptOwnerCik>0001922394</rptOwnerCik>
        <rptOwnerName>Wray Michael</rptOwnerName></reportingOwnerId>
        <reportingOwnerRelationship><isOfficer>1</isOfficer>
        <officerTitle>Executive Vice President</officerTitle></reportingOwnerRelationship>
        </reportingOwner><nonDerivativeTable><nonDerivativeTransaction>
        <securityTitle><value>Common Stock</value></securityTitle>
        <transactionDate><value>2026-08-26</value></transactionDate><transactionCoding>
        <transactionCode>S</transactionCode></transactionCoding><transactionAmounts>
        <transactionShares><value>4500</value></transactionShares>
        <transactionPricePerShare><value>110.9413</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
        </transactionAmounts><postTransactionAmounts><sharesOwnedFollowingTransaction><value>23886</value>
        </sharesOwnedFollowingTransaction></postTransactionAmounts><ownershipNature>
        <directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
        </nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>"""
    )

    assert receipt.form is OwnershipForm.FORM_4
    assert receipt.issuer_cik == "0001001385"
    assert receipt.reporting_owners[0].relationship is not None
    assert receipt.reporting_owners[0].relationship.is_officer
    transaction = receipt.insider_transactions[0]
    assert transaction.transaction_code == "S"
    assert transaction.shares == Decimal("4500")
    assert transaction.price_per_share == Decimal("110.9413")
    assert transaction.acquired_or_disposed == "D"
    assert transaction.shares_owned_after == Decimal("23886")
    assert transaction.ownership_nature is OwnershipNature.DIRECT


@pytest.mark.parametrize("form", ["3", "5"])
def test_section16_forms_without_transactions_remain_truthful_empty_records(form: str) -> None:
    receipt = parse(
        f"""<ownershipDocument><documentType>{form}</documentType>
        <periodOfReport>2026-08-24</periodOfReport><issuer><issuerCik>0001069878</issuerCik>
        <issuerName>TREX CO INC</issuerName><issuerTradingSymbol>TREX</issuerTradingSymbol></issuer>
        <reportingOwner><reportingOwnerId><rptOwnerCik>0002152353</rptOwnerCik>
        <rptOwnerName>Taylor Brian J.</rptOwnerName></reportingOwnerId></reportingOwner>
        </ownershipDocument>"""
    )
    assert receipt.form.value == form
    assert receipt.insider_transactions == ()


def test_real_form144_excerpt_is_a_planned_sale_not_a_completed_transaction() -> None:
    # Public SEC Form 144 accession 0001950047-26-008827, retrieved 2026-08-29.
    receipt = parse(
        """<edgarSubmission xmlns="http://www.sec.gov/edgar/ownership"><headerData>
        <submissionType>144</submissionType></headerData><formData><issuerInfo>
        <issuerCik>0001001250</issuerCik><issuerName>THE ESTEE LAUDER COMPANIES INC.</issuerName>
        <nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>RASHIDA LA LANDE
        </nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold><relationshipsToIssuer>
        <relationshipToIssuer>Officer</relationshipToIssuer></relationshipsToIssuer>
        </issuerInfo><securitiesInformation><securitiesClassTitle>Common</securitiesClassTitle>
        <noOfUnitsSold>7766</noOfUnitsSold><aggregateMarketValue>802344.29</aggregateMarketValue>
        <noOfUnitsOutstanding>247291223</noOfUnitsOutstanding><approxSaleDate>08/28/2026</approxSaleDate>
        <securitiesExchangeName>NYSE</securitiesExchangeName></securitiesInformation></formData></edgarSubmission>""",
        "0001950047-26-008827",
    )

    assert receipt.form is OwnershipForm.FORM_144
    assert receipt.insider_transactions == ()
    assert receipt.form_144_notice is not None
    assert receipt.form_144_notice.units_to_be_sold == Decimal("7766")
    assert receipt.form_144_notice.approximate_sale_date.isoformat() == "2026-08-28"


def test_real_schedule13g_excerpt_retains_percentage_and_power_context() -> None:
    # Public SEC Schedule 13G accession 0002100119-26-000625, retrieved 2026-08-29.
    receipt = parse(
        """<edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13g"><schemaVersion>X0202</schemaVersion>
        <headerData><submissionType>SCHEDULE 13G</submissionType></headerData><formData>
        <coverPageHeader><eventDateRequiresFilingThisStatement>03/31/2026</eventDateRequiresFilingThisStatement>
        <issuerInfo><issuerCik>0001000228</issuerCik><issuerName>Henry Schein Inc</issuerName>
        </issuerInfo>
        </coverPageHeader><coverPageHeaderReportingPersonDetails>
        <reportingPersonName>Vanguard Capital Management</reportingPersonName>
        <reportingPersonBeneficiallyOwnedNumberOfShares><soleVotingPower>879493</soleVotingPower>
        <sharedVotingPower>0</sharedVotingPower><soleDispositivePower>7302660</soleDispositivePower>
        <sharedDispositivePower>0</sharedDispositivePower></reportingPersonBeneficiallyOwnedNumberOfShares>
        <reportingPersonBeneficiallyOwnedAggregateNumberOfShares>7302660</reportingPersonBeneficiallyOwnedAggregateNumberOfShares>
        <classPercent>6.36</classPercent><typeOfReportingPerson>IA</typeOfReportingPerson>
        </coverPageHeaderReportingPersonDetails></formData></edgarSubmission>""",
        "0002100119-26-000625",
    )

    assert receipt.form is OwnershipForm.SCHEDULE_13G
    owner = receipt.beneficial_owners[0]
    assert owner.aggregate_shares_owned == Decimal("7302660")
    assert owner.percent_of_class == Decimal("6.36")
    assert owner.reporting_person_types == ("IA",)
    assert receipt.disclosed_transaction_purpose is None
    assert receipt.activist_control_intent_status is ActivistControlIntentStatus.NOT_APPLICABLE


def test_real_schedule13d_amendment_preserves_exact_item4_text_for_review() -> None:
    # Public SEC Schedule 13D/A accession 0001398344-26-006235, retrieved 2026-08-29.
    receipt = parse(
        """<edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13D"><headerData>
        <submissionType>SCHEDULE 13D/A</submissionType></headerData><formData><coverPageHeader>
        <amendmentNo>6</amendmentNo><dateOfEvent>04/08/2026</dateOfEvent><issuerInfo>
        <issuerCIK>0001000694</issuerCIK><issuerName>NOVAVAX, INC.</issuerName></issuerInfo>
        </coverPageHeader><reportingPersons><reportingPersonInfo>
        <reportingPersonCIK>0001383838</reportingPersonCIK>
        <reportingPersonName>Shah Capital Management</reportingPersonName>
        <soleVotingPower>0.00</soleVotingPower><sharedVotingPower>14719738.00</sharedVotingPower>
        <soleDispositivePower>0.00</soleDispositivePower>
        <sharedDispositivePower>14719738.00</sharedDispositivePower>
        <aggregateAmountOwned>14719738.00</aggregateAmountOwned>
        <percentOfClass>9.03</percentOfClass><typeOfReportingPerson>IA</typeOfReportingPerson>
        </reportingPersonInfo></reportingPersons><items1To7><item4><transactionPurpose>
        On April 8, 2026, the Reporting Persons sent a letter to the board of directors
        declaring a notice of intention to vote against Board Nominees and Executive Compensation.
        </transactionPurpose></item4></items1To7></formData></edgarSubmission>""",
        "0001398344-26-006235",
    )

    assert receipt.form is OwnershipForm.SCHEDULE_13D_A
    assert receipt.amendment_number == 6
    assert receipt.beneficial_owners[0].percent_of_class == Decimal("9.03")
    assert receipt.disclosed_transaction_purpose == (
        "On April 8, 2026, the Reporting Persons sent a letter to the board of directors "
        "declaring a notice of intention to vote against Board Nominees and Executive Compensation."
    )
    assert (
        receipt.activist_control_intent_status
        is ActivistControlIntentStatus.DISCLOSED_TEXT_REQUIRES_REVIEW
    )


def test_schedule_transitions_are_explicit_without_inventing_activist_intent() -> None:
    assert (
        classify_schedule_transition(OwnershipForm.SCHEDULE_13G_A, OwnershipForm.SCHEDULE_13D)
        is ScheduleTransition.THIRTEEN_G_TO_THIRTEEN_D
    )
    assert (
        classify_schedule_transition(OwnershipForm.SCHEDULE_13D, OwnershipForm.SCHEDULE_13G)
        is ScheduleTransition.THIRTEEN_D_TO_THIRTEEN_G
    )
    assert (
        classify_schedule_transition(None, OwnershipForm.SCHEDULE_13D)
        is ScheduleTransition.INITIAL_13D
    )


def test_parser_rejects_entities_oversize_invalid_numbers_and_unsupported_forms() -> None:
    with pytest.raises(OwnershipParseError, match="declarations"):
        parse("<!DOCTYPE x [<!ENTITY y 'z'>]><ownershipDocument>&y;</ownershipDocument>")
    with pytest.raises(OwnershipParseError, match="numeric"):
        parse(
            """<ownershipDocument><documentType>4</documentType><periodOfReport>2026-08-26</periodOfReport>
            <issuer><issuerCik>0001001385</issuerCik><issuerName>Issuer</issuerName></issuer>
            <nonDerivativeTable><nonDerivativeTransaction><securityTitle><value>Common</value></securityTitle>
            <transactionDate><value>2026-08-26</value></transactionDate><transactionCoding><transactionCode>S</transactionCode></transactionCoding>
            <transactionAmounts><transactionShares><value>not-a-number</value></transactionShares>
            <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts>
            </nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>"""
        )
    with pytest.raises(OwnershipParseError, match="unsupported"):
        parse("<ownershipDocument><documentType>8-K</documentType></ownershipDocument>")


def test_ingestion_binds_fetched_document_to_validated_sec_metadata() -> None:
    body = b"""<ownershipDocument><documentType>3</documentType>
    <periodOfReport>2026-08-24</periodOfReport><issuer><issuerCik>0001069878</issuerCik>
    <issuerName>TREX CO INC</issuerName></issuer></ownershipDocument>"""
    source_url = "https://www.sec.gov/Archives/edgar/data/1069878/000106987826000077/form3.xml"
    document = SecFetchedPrimaryDocument(
        cik="0001069878",
        accession_number="0001069878-26-000077",
        document_name="form3.xml",
        url=source_url,
        status_code=200,
        headers={"content-type": "text/xml"},
        body=body,
        content_sha256=hashlib.sha256(body).hexdigest(),
        retrieved_at=NOW,
    )

    class Client:
        def fetch_primary_document(
            self,
            *,
            cik: str | int,
            accession_number: str,
            document_name: str,
        ) -> SecFetchedPrimaryDocument:
            assert (cik, accession_number, document_name) == (
                "0001069878",
                "0001069878-26-000077",
                "form3.xml",
            )
            return document

    filing = SecFilingRecord(
        record_id="1" * 64,
        cik="0001069878",
        accession_number="0001069878-26-000077",
        form="3",
        filing_date=NOW.date(),
        report_date=NOW.date(),
        accepted_at=NOW,
        available_at=NOW,
        retrieved_at=NOW,
        file_number=None,
        primary_document="form3.xml",
        primary_document_description=None,
        filing_url=HttpUrl(source_url),
        source_content_sha256="2" * 64,
    )

    receipt = SecOwnershipIngestionService(Client()).ingest(filing)
    assert receipt.accession_number == filing.accession_number
    assert str(receipt.source_url) == source_url
    assert receipt.source_content_sha256 == document.content_sha256


def test_ownership_metadata_isolates_requested_safe_xsl_path_from_unrelated_rows() -> None:
    payload = {
        "cik": "0000008858",
        "filings": {
            "recent": {
                "accessionNumber": ["0000008858-25-000001", "0000008858-26-000085"],
                "filingDate": ["2025-01-01", "2026-08-28"],
                "reportDate": ["", "2026-08-26"],
                "acceptanceDateTime": [
                    "2025-01-01T12:00:00Z",
                    "2026-08-28T16:07:01Z",
                ],
                "form": ["8-K", "4"],
                "fileNumber": ["", ""],
                "primaryDocument": ["unrelated path.htm", "xslF345X06/form4.xml"],
                "primaryDocDescription": ["", "FORM 4"],
            }
        },
    }
    body = json.dumps(payload).encode()
    document = SecFetchedDocument(
        endpoint="submissions",
        cik="0000008858",
        url="https://data.sec.gov/submissions/CIK0000008858.json",
        status_code=200,
        headers={"content-type": "application/json"},
        body=body,
        content_sha256=hashlib.sha256(body).hexdigest(),
        retrieved_at=NOW,
    )

    filing = ownership_filing_from_submissions(
        document,
        accession_number="0000008858-26-000085",
    )

    assert filing is not None
    assert filing.primary_document == "form4.xml"
    assert str(filing.filing_url).endswith("/8858/000000885826000085/form4.xml")


def test_ingestion_rejects_document_form_or_issuer_mismatch() -> None:
    body = b"""<ownershipDocument><documentType>5</documentType>
    <periodOfReport>2026-08-24</periodOfReport><issuer><issuerCik>0001069878</issuerCik>
    <issuerName>TREX CO INC</issuerName></issuer></ownershipDocument>"""
    source_url = "https://www.sec.gov/Archives/edgar/data/1069878/000106987826000077/form3.xml"
    document = SecFetchedPrimaryDocument(
        cik="0001069878",
        accession_number="0001069878-26-000077",
        document_name="form3.xml",
        url=source_url,
        status_code=200,
        headers={"content-type": "text/xml"},
        body=body,
        content_sha256=hashlib.sha256(body).hexdigest(),
        retrieved_at=NOW,
    )

    class Client:
        def fetch_primary_document(
            self,
            *,
            cik: str | int,
            accession_number: str,
            document_name: str,
        ) -> SecFetchedPrimaryDocument:
            return document

    filing = SecFilingRecord(
        record_id="1" * 64,
        cik="0001069878",
        accession_number="0001069878-26-000077",
        form="3",
        filing_date=NOW.date(),
        report_date=NOW.date(),
        accepted_at=NOW,
        available_at=NOW,
        retrieved_at=NOW,
        file_number=None,
        primary_document="form3.xml",
        primary_document_description=None,
        filing_url=HttpUrl(source_url),
        source_content_sha256="2" * 64,
    )

    with pytest.raises(OwnershipParseError, match="form does not match"):
        SecOwnershipIngestionService(Client()).ingest(filing)
