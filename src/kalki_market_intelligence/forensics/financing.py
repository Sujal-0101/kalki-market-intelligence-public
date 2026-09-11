"""Closed primary-source contracts for financing and dilution intelligence."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from html.parser import HTMLParser
from typing import Annotated, Self
from uuid import UUID, uuid5

from pydantic import Field, HttpUrl, StringConstraints, model_validator

from kalki_market_intelligence.contracts.common import (
    ContractModel,
    NonEmptyText,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)
from kalki_market_intelligence.forensics.tiers import (
    AnalysisTier,
    EscalationReason,
    TierDecision,
    TierOutcome,
)
from kalki_market_intelligence.providers.sec.contracts import AccessionNumber, Cik


class FinancingParseError(ValueError):
    """A financing filing cannot enter the closed contract without guessing."""


MAXIMUM_FINANCING_HTML_BYTES = 8_000_000
MAXIMUM_FINANCING_EVIDENCE = 16
MAXIMUM_EVIDENCE_CHARACTERS = 720
MAXIMUM_TOTAL_EVIDENCE_CHARACTERS = 8_000
FINANCING_EVIDENCE_EXTRACTOR_VERSION = "sec-financing-evidence-v1"
_FINANCING_EVIDENCE_NAMESPACE = UUID("41000000-0000-4000-8000-000000000041")


class FinancingForm(StrEnum):
    S_1 = "S-1"
    S_1_A = "S-1/A"
    S_3 = "S-3"
    S_3_A = "S-3/A"
    FORM_424B1 = "424B1"
    FORM_424B2 = "424B2"
    FORM_424B3 = "424B3"
    FORM_424B4 = "424B4"
    FORM_424B5 = "424B5"
    FORM_424B7 = "424B7"
    FORM_8_K = "8-K"
    FORM_8_K_A = "8-K/A"


class FinancingInstrument(StrEnum):
    SHELF_REGISTRATION = "SHELF_REGISTRATION"
    RESALE_REGISTRATION = "RESALE_REGISTRATION"
    ATM_PROGRAM = "ATM_PROGRAM"
    PUBLIC_OFFERING = "PUBLIC_OFFERING"
    PIPE = "PIPE"
    CONVERTIBLE_DEBT = "CONVERTIBLE_DEBT"
    PREFERRED_EQUITY = "PREFERRED_EQUITY"
    WARRANT = "WARRANT"
    WARRANT_REPRICING = "WARRANT_REPRICING"
    WARRANT_EXERCISE_INDUCEMENT = "WARRANT_EXERCISE_INDUCEMENT"
    EQUITY_LINE = "EQUITY_LINE"
    DEBT = "DEBT"


class FinancingEventContext(StrEnum):
    REGISTRATION_CAPACITY = "REGISTRATION_CAPACITY"
    EQUITY_FINANCING = "EQUITY_FINANCING"
    DEBT_FINANCING = "DEBT_FINANCING"
    MULTI_INSTRUMENT = "MULTI_INSTRUMENT"


class FinancingEventStatus(StrEnum):
    REGISTERED = "REGISTERED"
    PROPOSED = "PROPOSED"
    PRICED = "PRICED"
    CLOSED = "CLOSED"
    AVAILABLE = "AVAILABLE"
    AMENDED = "AMENDED"
    TERMINATED = "TERMINATED"
    UNKNOWN = "UNKNOWN"


class MoneyBasis(StrEnum):
    MAXIMUM_AGGREGATE_OFFERING = "MAXIMUM_AGGREGATE_OFFERING"
    GROSS_PROCEEDS = "GROSS_PROCEEDS"
    NET_PROCEEDS = "NET_PROCEEDS"
    PRINCIPAL = "PRINCIPAL"
    COMMITMENT = "COMMITMENT"
    AGGREGATE_SALE_PRICE = "AGGREGATE_SALE_PRICE"


class IssuerProceedsStatus(StrEnum):
    REPORTED = "REPORTED"
    NONE_TO_ISSUER = "NONE_TO_ISSUER"
    UNKNOWN = "UNKNOWN"


class ReportedAmountStatus(StrEnum):
    REPORTED = "REPORTED"
    EXPECTED = "EXPECTED"
    ESTIMATED = "ESTIMATED"


class FinancingEvidenceSignal(StrEnum):
    """Closed textual signals; these are evidence candidates, not financing conclusions."""

    REGISTRATION_RESALE = "REGISTRATION_RESALE"
    ATM_PROGRAM = "ATM_PROGRAM"
    OFFERING_CAPACITY = "OFFERING_CAPACITY"
    ACTUAL_SALES_DISCLOSED = "ACTUAL_SALES_DISCLOSED"
    PUBLIC_OFFERING = "PUBLIC_OFFERING"
    OFFERING_PRICE = "OFFERING_PRICE"
    PRIVATE_PLACEMENT = "PRIVATE_PLACEMENT"
    CONVERTIBLE_DEBT = "CONVERTIBLE_DEBT"
    PREFERRED_EQUITY = "PREFERRED_EQUITY"
    WARRANT = "WARRANT"
    WARRANT_REPRICING = "WARRANT_REPRICING"
    EXERCISE_INDUCEMENT = "EXERCISE_INDUCEMENT"
    EQUITY_LINE = "EQUITY_LINE"
    DEBT_OFFERING = "DEBT_OFFERING"
    MATURITY = "MATURITY"
    PROCEEDS_LANGUAGE = "PROCEEDS_LANGUAGE"
    ISSUABLE_SECURITIES = "ISSUABLE_SECURITIES"


class FinancingEvidenceExcerpt(ContractModel):
    """One bounded exact excerpt from normalized visible primary-document text."""

    evidence_id: UUID
    signals: tuple[FinancingEvidenceSignal, ...] = Field(min_length=1, max_length=6)
    locator: ShortText
    text: NonEmptyText = Field(max_length=MAXIMUM_EVIDENCE_CHARACTERS)
    text_sha256: Sha256Hex
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)

    @model_validator(mode="after")
    def evidence_identity_is_closed(self) -> Self:
        if self.signals != tuple(sorted(set(self.signals), key=str)):
            raise ValueError("financing evidence signals must be sorted and unique")
        if self.end_offset <= self.start_offset:
            raise ValueError("financing evidence offsets are invalid")
        if self.end_offset - self.start_offset != len(self.text):
            raise ValueError("financing evidence offsets must match the exact text length")
        if hashlib.sha256(self.text.encode("utf-8")).hexdigest() != self.text_sha256:
            raise ValueError("financing evidence text hash does not match")
        expected_locator = f"normalized-visible-text:{self.start_offset}-{self.end_offset}"
        if self.locator != expected_locator:
            raise ValueError("financing evidence locator does not match its offsets")
        return self


class FinancingEvidenceBundle(ContractModel):
    """Bounded extraction output tied to both source bytes and normalized visible text."""

    source_content_sha256: Sha256Hex
    visible_text_sha256: Sha256Hex
    evidence: tuple[FinancingEvidenceExcerpt, ...] = Field(
        default=(), max_length=MAXIMUM_FINANCING_EVIDENCE
    )
    extractor_version: str = FINANCING_EVIDENCE_EXTRACTOR_VERSION

    @model_validator(mode="after")
    def evidence_is_unique_and_bounded(self) -> Self:
        evidence_ids = tuple(item.evidence_id for item in self.evidence)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("financing evidence IDs must be unique")
        if sum(len(item.text) for item in self.evidence) > MAXIMUM_TOTAL_EVIDENCE_CHARACTERS:
            raise ValueError("financing evidence exceeds the aggregate text boundary")
        return self


type CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class ReportedMoney(ContractModel):
    amount: Decimal = Field(ge=0)
    currency: CurrencyCode
    basis: MoneyBasis
    amount_status: ReportedAmountStatus = ReportedAmountStatus.REPORTED


class FinancingTerm(ContractModel):
    """One reported instrument; absent values remain UNKNOWN through ``None``."""

    instrument: FinancingInstrument
    status: FinancingEventStatus
    money: tuple[ReportedMoney, ...] = Field(default=(), max_length=5)
    offered_shares: Decimal | None = Field(default=None, ge=0)
    issuable_shares: Decimal | None = Field(default=None, ge=0)
    sold_shares: Decimal | None = Field(default=None, ge=0)
    price_per_share: Decimal | None = Field(default=None, ge=0)
    conversion_price: Decimal | None = Field(default=None, ge=0)
    exercise_price: Decimal | None = Field(default=None, ge=0)
    previous_exercise_price: Decimal | None = Field(default=None, ge=0)
    interest_rate_percent: Decimal | None = Field(default=None, ge=0, le=100)
    announced_on: date | None = None
    closing_on: date | None = None
    maturity_on: date | None = None
    covenant_text: tuple[NonEmptyText, ...] = Field(default=(), max_length=8)
    issuer_proceeds_status: IssuerProceedsStatus = IssuerProceedsStatus.UNKNOWN
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def term_semantics_are_closed(self) -> FinancingTerm:
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("financing evidence IDs must be unique")
        money_bases = tuple(item.basis for item in self.money)
        if len(set(money_bases)) != len(money_bases):
            raise ValueError("a financing term cannot repeat a money basis")
        proceeds_bases = {MoneyBasis.GROSS_PROCEEDS, MoneyBasis.NET_PROCEEDS}
        has_reported_proceeds = bool(set(money_bases) & proceeds_bases)
        if self.issuer_proceeds_status is IssuerProceedsStatus.REPORTED:
            if not has_reported_proceeds:
                raise ValueError("reported issuer proceeds require a proceeds amount")
        elif has_reported_proceeds:
            raise ValueError("a proceeds amount requires reported issuer proceeds status")
        warrant_instruments = {
            FinancingInstrument.WARRANT,
            FinancingInstrument.WARRANT_REPRICING,
            FinancingInstrument.WARRANT_EXERCISE_INDUCEMENT,
        }
        if self.exercise_price is not None and self.instrument not in warrant_instruments:
            raise ValueError("only a warrant event may report an exercise price")
        if (
            self.previous_exercise_price is not None
            and self.instrument is not FinancingInstrument.WARRANT_REPRICING
        ):
            raise ValueError("only a warrant repricing may report a previous exercise price")
        if self.conversion_price is not None and self.instrument not in {
            FinancingInstrument.CONVERTIBLE_DEBT,
            FinancingInstrument.PREFERRED_EQUITY,
        }:
            raise ValueError("conversion price requires a convertible instrument")
        if self.maturity_on is not None and self.instrument not in {
            FinancingInstrument.CONVERTIBLE_DEBT,
            FinancingInstrument.DEBT,
        }:
            raise ValueError("maturity requires a debt instrument")
        if self.interest_rate_percent is not None and self.instrument not in {
            FinancingInstrument.CONVERTIBLE_DEBT,
            FinancingInstrument.DEBT,
        }:
            raise ValueError("interest rate requires a debt instrument")
        if self.closing_on is not None and self.announced_on is not None:
            if self.closing_on < self.announced_on:
                raise ValueError("financing close cannot precede its announcement")
        return self


class FinancingFilingReceipt(ContractModel):
    accession_number: AccessionNumber
    issuer_cik: Cik
    issuer_name: ShortText
    form: FinancingForm
    terms: tuple[FinancingTerm, ...] = Field(min_length=1, max_length=32)
    evidence_bundle: FinancingEvidenceBundle
    source_url: HttpUrl
    source_content_sha256: Sha256Hex
    accepted_at: UtcDatetime
    retrieved_at: UtcDatetime
    parser_version: str = "sec-financing-v1"

    @model_validator(mode="after")
    def source_and_terms_are_consistent(self) -> FinancingFilingReceipt:
        if self.retrieved_at < self.accepted_at:
            raise ValueError("financing retrieval cannot precede SEC acceptance")
        if self.evidence_bundle.source_content_sha256 != self.source_content_sha256:
            raise ValueError("financing extraction source hash does not match the filing")
        evidence = tuple(evidence_id for term in self.terms for evidence_id in term.evidence_ids)
        if len(set(evidence)) != len(evidence):
            raise ValueError("financing terms cannot reuse an evidence ID")
        extracted_ids = {item.evidence_id for item in self.evidence_bundle.evidence}
        if not set(evidence).issubset(extracted_ids):
            raise ValueError("financing terms must reference extracted evidence IDs")
        parsed_terms = parse_financing_terms(self.evidence_bundle)
        for term in self.terms:
            if (
                term.instrument
                in {
                    FinancingInstrument.RESALE_REGISTRATION,
                    FinancingInstrument.ATM_PROGRAM,
                    FinancingInstrument.PUBLIC_OFFERING,
                    FinancingInstrument.PIPE,
                    FinancingInstrument.CONVERTIBLE_DEBT,
                    FinancingInstrument.PREFERRED_EQUITY,
                    FinancingInstrument.WARRANT,
                    FinancingInstrument.WARRANT_REPRICING,
                    FinancingInstrument.WARRANT_EXERCISE_INDUCEMENT,
                    FinancingInstrument.EQUITY_LINE,
                    FinancingInstrument.DEBT,
                }
                and term not in parsed_terms
            ):
                raise ValueError("financing terms must match deterministic evidence parsing")
        return self


class FinancingTier0Receipt(ContractModel):
    accession_number: AccessionNumber
    source_content_sha256: Sha256Hex
    event_context: FinancingEventContext
    instruments: tuple[FinancingInstrument, ...] = Field(min_length=1, max_length=12)
    decision: TierDecision
    routing_version: str = "financing-tier0-v1"


def normalize_financing_form(value: str) -> FinancingForm:
    """Normalize only the explicitly supported SEC financing form names."""

    normalized = value.strip().upper()
    try:
        return FinancingForm(normalized)
    except ValueError as error:
        raise FinancingParseError(f"unsupported financing form metadata: {normalized}") from error


_SIGNAL_PHRASES: dict[FinancingEvidenceSignal, tuple[str, ...]] = {
    FinancingEvidenceSignal.REGISTRATION_RESALE: (
        "registering the resale shares for resale",
        "resale by the selling stockholders",
        "proposed resale or other disposition",
    ),
    FinancingEvidenceSignal.ATM_PROGRAM: (
        "at-the-market offering",
        "atm facility",
        "as sales agent",
    ),
    FinancingEvidenceSignal.OFFERING_CAPACITY: (
        "maximum aggregate offering price",
        "aggregate offering price of up to",
    ),
    FinancingEvidenceSignal.ACTUAL_SALES_DISCLOSED: (
        "we have sold",
        "previously sold pursuant to the sales agreement",
    ),
    FinancingEvidenceSignal.PUBLIC_OFFERING: (
        "public offering price",
        "best-efforts basis",
    ),
    FinancingEvidenceSignal.OFFERING_PRICE: (
        "public offering price of",
        "offering price per share",
    ),
    FinancingEvidenceSignal.PRIVATE_PLACEMENT: (
        "private placement",
        "securities purchase agreement",
    ),
    FinancingEvidenceSignal.CONVERTIBLE_DEBT: (
        "convertible promissory note",
        "convertible note",
    ),
    FinancingEvidenceSignal.PREFERRED_EQUITY: (
        "convertible preferred stock",
        "preferred shares",
    ),
    FinancingEvidenceSignal.WARRANT: (
        "pre-funded warrant",
        "purchase warrant",
        "exercise price",
    ),
    FinancingEvidenceSignal.WARRANT_REPRICING: (
        "warrant amendments amend the exercise price",
        "reduced exercise price period",
    ),
    FinancingEvidenceSignal.EXERCISE_INDUCEMENT: (
        "warrant exercise inducement",
        "inducement letter",
        "warrants to purchase up to",
        "comprised of new",
    ),
    FinancingEvidenceSignal.EQUITY_LINE: (
        "equity purchase agreement",
        "right, but not the obligation",
        "terminated effective as of",
    ),
    FinancingEvidenceSignal.DEBT_OFFERING: (
        "aggregate principal amount",
        "senior notes due",
    ),
    FinancingEvidenceSignal.MATURITY: (
        "will mature on",
        "matures on",
        "maturity to a date",
    ),
    FinancingEvidenceSignal.PROCEEDS_LANGUAGE: (
        "gross proceeds",
        "net proceeds",
        "will not receive any proceeds",
    ),
    FinancingEvidenceSignal.ISSUABLE_SECURITIES: (
        "issuable upon conversion",
        "issuable upon exercise",
    ),
}


class _FinancingVisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style", "svg", "noscript", "xbrl", "ix:header"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "svg", "noscript", "xbrl", "ix:header"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)


@dataclass(frozen=True, slots=True)
class _SignalHit:
    position: int
    signal: FinancingEvidenceSignal
    phrase: str


def extract_financing_evidence(body: bytes) -> FinancingEvidenceBundle:
    """Extract bounded financing-language windows without interpreting amounts or status."""

    if not body or len(body) > MAXIMUM_FINANCING_HTML_BYTES:
        raise FinancingParseError("financing HTML is empty or exceeds the size boundary")
    parser = _FinancingVisibleTextParser()
    try:
        parser.feed(body.decode("utf-8", errors="replace"))
        parser.close()
    except (ValueError, TypeError) as error:
        raise FinancingParseError("financing HTML could not be parsed safely") from error
    visible_text = " ".join(" ".join(parser.parts).replace("\x00", " ").split())
    if not visible_text:
        raise FinancingParseError("financing HTML has no visible text")

    lowered = visible_text.casefold()
    hits = _find_signal_hits(lowered)
    source_hash = hashlib.sha256(body).hexdigest()
    excerpts: list[FinancingEvidenceExcerpt] = []
    used_characters = 0
    for hit in _prioritize_signal_hits(hits):
        start, end = _whole_word_evidence_window(visible_text, hit.position)
        overlapping = next(
            (
                index
                for index, item in enumerate(excerpts)
                if start < item.end_offset and end > item.start_offset
            ),
            None,
        )
        if overlapping is not None:
            item = excerpts[overlapping]
            if hit.phrase in item.text.casefold():
                signals = tuple(sorted({*item.signals, hit.signal}, key=str))
                excerpts[overlapping] = item.model_copy(update={"signals": signals})
                continue
        text = visible_text[start:end]
        if used_characters + len(text) > MAXIMUM_TOTAL_EVIDENCE_CHARACTERS:
            continue
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        evidence_id = uuid5(
            _FINANCING_EVIDENCE_NAMESPACE,
            f"{source_hash}:{start}:{end}:{text_hash}",
        )
        excerpts.append(
            FinancingEvidenceExcerpt(
                evidence_id=evidence_id,
                signals=(hit.signal,),
                locator=f"normalized-visible-text:{start}-{end}",
                text=text,
                text_sha256=text_hash,
                start_offset=start,
                end_offset=end,
            )
        )
        used_characters += len(text)
        if len(excerpts) >= MAXIMUM_FINANCING_EVIDENCE:
            break
    excerpts.sort(key=lambda item: (item.start_offset, str(item.evidence_id)))
    return FinancingEvidenceBundle(
        source_content_sha256=source_hash,
        visible_text_sha256=hashlib.sha256(visible_text.encode("utf-8")).hexdigest(),
        evidence=tuple(excerpts),
    )


_NUMBER_TEXT = r"(?:0|[1-9][0-9]{0,2}(?:,[0-9]{3})*)(?:\.[0-9]+)?"
_RESALE_SHARES_PATTERN = re.compile(
    rf"proposed resale or other disposition.{{0,240}}?of up to (?P<shares>{_NUMBER_TEXT}) shares",
    re.IGNORECASE,
)
_ATM_CAPACITY_AMENDMENT_PATTERN = re.compile(
    rf"reduce the maximum aggregate offering price.{{0,180}}?"
    rf"from \$(?P<previous>{_NUMBER_TEXT}) to \$(?P<current>{_NUMBER_TEXT})",
    re.IGNORECASE,
)
_ATM_ACTUAL_SALES_PATTERN = re.compile(
    rf"we have sold (?P<shares>{_NUMBER_TEXT}) ADSs having an aggregate offering price "
    rf"of approximately \$(?P<amount>{_NUMBER_TEXT})",
    re.IGNORECASE,
)
_PRICED_PUBLIC_OFFERING_PATTERN = re.compile(
    rf"\bis offering(?: on a best-efforts basis)? up to (?P<shares>{_NUMBER_TEXT}) "
    rf"(?:Class [A-Z] )?(?:Ordinary|Common) Shares.{{0,220}}?"
    rf"at a public offering price of \$(?P<price>{_NUMBER_TEXT}) per "
    rf"(?:Class [A-Z] )?(?:Ordinary|Common) Share",
    re.IGNORECASE,
)
_PIPE_COMMON_STOCK_PATTERN = re.compile(
    rf"agreed to sell.{{0,180}}?in a private placement.{{0,180}}?"
    rf"an aggregate of (?P<shares>{_NUMBER_TEXT}) shares.{{0,180}}?"
    rf"at an offering price of \$(?P<price>{_NUMBER_TEXT}) per Share",
    re.IGNORECASE,
)
_PIPE_EXPECTED_GROSS_PATTERN = re.compile(
    rf"gross proceeds of the Private Placement are expected to be approximately "
    rf"\$(?P<amount>{_NUMBER_TEXT}) (?P<scale>million|billion)",
    re.IGNORECASE,
)
_CONVERTIBLE_NOTE_PATTERN = re.compile(
    rf"issued.{{0,120}}?a senior secured convertible promissory note in the original "
    rf"principal amount of \$(?P<principal>{_NUMBER_TEXT})",
    re.IGNORECASE,
)
_CONVERTIBLE_INTEREST_PATTERN = re.compile(
    rf"Convertible Note.{{0,260}}?bears interest at an annual rate of "
    rf"(?P<rate>{_NUMBER_TEXT})%",
    re.IGNORECASE,
)
_CONVERTIBLE_MATURITY_PATTERN = re.compile(
    r"Convertible Note matures on (?P<date>[A-Z][a-z]+ [0-9]{1,2}, [0-9]{4})",
    re.IGNORECASE,
)
_PREFERRED_EQUITY_PATTERN = re.compile(
    rf"agreed to sell.{{0,120}}?\(i\) (?P<shares>{_NUMBER_TEXT}) shares of "
    rf"Series A 10% Convertible Preferred Stock for aggregate gross proceeds of "
    rf"\$(?P<gross>{_NUMBER_TEXT})",
    re.IGNORECASE,
)
_PRIVATE_PLACEMENT_WARRANT_PATTERN = re.compile(
    rf"in a concurrent private placement.{{0,120}}?we are issuing unregistered warrants "
    rf"to purchase up to (?P<shares>{_NUMBER_TEXT}) Common Shares.{{0,160}}?"
    rf"exercise price of \$(?P<price>{_NUMBER_TEXT}) per share",
    re.IGNORECASE,
)
_WARRANT_REPRICING_PATTERN = re.compile(
    rf"previously amended to establish a reduced exercise price period.{{0,180}}?"
    rf"exercise price was amended to \$(?P<previous>{_NUMBER_TEXT}) per Warrant share."
    rf".{{0,100}}?amend the exercise price to \$(?P<current>{_NUMBER_TEXT}) per Warrant share",
    re.IGNORECASE,
)
_EXERCISE_INDUCEMENT_PATTERN = re.compile(
    rf"agreed to exercise the Existing Warrants for cash at a reduced exercise price of "
    rf"\$(?P<reduced>{_NUMBER_TEXT}) per share",
    re.IGNORECASE,
)
_EXERCISE_INDUCEMENT_NEW_SHARES_PATTERN = re.compile(
    rf"new (?:Class [A-Z] )?warrants to purchase up to (?P<shares>{_NUMBER_TEXT}) shares",
    re.IGNORECASE,
)
_EXERCISE_INDUCEMENT_NEW_PRICE_PATTERN = re.compile(
    rf"exercise price thereof is \$(?P<price>{_NUMBER_TEXT}) per share",
    re.IGNORECASE,
)
_EXERCISE_INDUCEMENT_GROSS_PATTERN = re.compile(
    rf"If all of the Existing Warrants are exercised in full.{{0,140}}?will receive "
    rf"aggregate gross proceeds of approximately \$(?P<amount>{_NUMBER_TEXT}) "
    rf"(?P<scale>million|billion)",
    re.IGNORECASE,
)
_CONVERTIBLE_COVENANT_PATTERN = re.compile(
    r"Convertible Note includes (?P<covenants>customary affirmative and negative covenants)",
    re.IGNORECASE,
)
_EQUITY_LINE_COMMITMENT_PATTERN = re.compile(
    rf"Equity Purchase Agreement provided the Company the right, but not the obligation, "
    rf"to direct the Investor to purchase up to \$(?P<amount>{_NUMBER_TEXT})",
    re.IGNORECASE,
)
_DEBT_OFFERING_PATTERN = re.compile(
    rf"closed its previously announced notes offering.{{0,80}}?of \$(?P<principal>{_NUMBER_TEXT}) "
    rf"(?P<scale>million|billion) aggregate principal amount of its "
    rf"(?P<rate>{_NUMBER_TEXT})% senior notes due (?P<due_year>[0-9]{{4}})",
    re.IGNORECASE,
)
_DEBT_MATURITY_PATTERN = re.compile(
    r"Notes will mature on (?P<date>[A-Z][a-z]+ [0-9]{1,2}, [0-9]{4})",
    re.IGNORECASE,
)


def parse_shelf_atm_terms(bundle: FinancingEvidenceBundle) -> tuple[FinancingTerm, ...]:
    """Parse only explicitly supported resale and amended-ATM contexts from evidence."""

    terms: list[FinancingTerm] = []
    resale_match = _unique_evidence_match(bundle, _RESALE_SHARES_PATTERN)
    no_proceeds = _evidence_containing(bundle, "will not receive any proceeds")
    if resale_match is not None and no_proceeds is not None:
        resale_evidence, match = resale_match
        terms.append(
            FinancingTerm(
                instrument=FinancingInstrument.RESALE_REGISTRATION,
                status=FinancingEventStatus.REGISTERED,
                offered_shares=_reported_decimal(match.group("shares")),
                issuer_proceeds_status=IssuerProceedsStatus.NONE_TO_ISSUER,
                evidence_ids=tuple(
                    dict.fromkeys((resale_evidence.evidence_id, no_proceeds.evidence_id))
                ),
            )
        )

    capacity_match = _unique_evidence_match(bundle, _ATM_CAPACITY_AMENDMENT_PATTERN)
    actual_sales_match = _unique_evidence_match(bundle, _ATM_ACTUAL_SALES_PATTERN)
    atm_evidence = _evidence_with_signal(bundle, FinancingEvidenceSignal.ATM_PROGRAM)
    if capacity_match is not None and atm_evidence is not None:
        capacity_evidence, capacity = capacity_match
        money = [
            ReportedMoney(
                amount=_reported_decimal(capacity.group("current")),
                currency="USD",
                basis=MoneyBasis.MAXIMUM_AGGREGATE_OFFERING,
            )
        ]
        sold_shares: Decimal | None = None
        evidence_ids = [atm_evidence.evidence_id, capacity_evidence.evidence_id]
        if actual_sales_match is not None:
            sales_evidence, sales = actual_sales_match
            sold_shares = _reported_decimal(sales.group("shares"))
            money.append(
                ReportedMoney(
                    amount=_reported_decimal(sales.group("amount")),
                    currency="USD",
                    basis=MoneyBasis.AGGREGATE_SALE_PRICE,
                )
            )
            evidence_ids.append(sales_evidence.evidence_id)
        terms.append(
            FinancingTerm(
                instrument=FinancingInstrument.ATM_PROGRAM,
                status=FinancingEventStatus.AMENDED,
                money=tuple(money),
                sold_shares=sold_shares,
                issuer_proceeds_status=IssuerProceedsStatus.UNKNOWN,
                evidence_ids=tuple(dict.fromkeys(evidence_ids)),
            )
        )
    return tuple(terms)


def parse_public_offering_terms(bundle: FinancingEvidenceBundle) -> tuple[FinancingTerm, ...]:
    """Parse a priced issuer share offering without inferring sales, proceeds, or dilution."""

    offering_match = _unique_evidence_match(bundle, _PRICED_PUBLIC_OFFERING_PATTERN)
    offering_evidence = _evidence_with_signal(bundle, FinancingEvidenceSignal.PUBLIC_OFFERING)
    price_evidence = _evidence_with_signal(bundle, FinancingEvidenceSignal.OFFERING_PRICE)
    if offering_match is None or offering_evidence is None or price_evidence is None:
        return ()
    matched_evidence, match = offering_match
    return (
        FinancingTerm(
            instrument=FinancingInstrument.PUBLIC_OFFERING,
            status=FinancingEventStatus.PRICED,
            offered_shares=_reported_decimal(match.group("shares")),
            price_per_share=_reported_decimal(match.group("price")),
            issuer_proceeds_status=IssuerProceedsStatus.UNKNOWN,
            evidence_ids=tuple(
                dict.fromkeys(
                    (
                        matched_evidence.evidence_id,
                        offering_evidence.evidence_id,
                        price_evidence.evidence_id,
                    )
                )
            ),
        ),
    )


def parse_private_placement_terms(bundle: FinancingEvidenceBundle) -> tuple[FinancingTerm, ...]:
    """Parse a priced common-stock PIPE while preserving expected proceeds as expected."""

    placement_match = _unique_evidence_match(bundle, _PIPE_COMMON_STOCK_PATTERN)
    placement_evidence = _evidence_with_signal(bundle, FinancingEvidenceSignal.PRIVATE_PLACEMENT)
    if placement_match is None or placement_evidence is None:
        return ()
    matched_evidence, match = placement_match
    money: tuple[ReportedMoney, ...] = ()
    evidence_ids = [matched_evidence.evidence_id, placement_evidence.evidence_id]
    proceeds_match = _unique_evidence_match(bundle, _PIPE_EXPECTED_GROSS_PATTERN)
    if proceeds_match is not None:
        proceeds_evidence, proceeds = proceeds_match
        money = (
            ReportedMoney(
                amount=_reported_scaled_decimal(proceeds.group("amount"), proceeds.group("scale")),
                currency="USD",
                basis=MoneyBasis.GROSS_PROCEEDS,
                amount_status=ReportedAmountStatus.EXPECTED,
            ),
        )
        evidence_ids.append(proceeds_evidence.evidence_id)
    return (
        FinancingTerm(
            instrument=FinancingInstrument.PIPE,
            status=FinancingEventStatus.PRICED,
            money=money,
            offered_shares=_reported_decimal(match.group("shares")),
            price_per_share=_reported_decimal(match.group("price")),
            issuer_proceeds_status=(
                IssuerProceedsStatus.REPORTED if money else IssuerProceedsStatus.UNKNOWN
            ),
            evidence_ids=tuple(dict.fromkeys(evidence_ids)),
        ),
    )


def parse_convertible_preferred_warrant_terms(
    bundle: FinancingEvidenceBundle,
) -> tuple[FinancingTerm, ...]:
    """Parse only the exact bounded convertible, preferred, and warrant forms supported."""

    terms: list[FinancingTerm] = []
    convertible_match = _unique_evidence_match(bundle, _CONVERTIBLE_NOTE_PATTERN)
    maturity_match = _unique_evidence_match(bundle, _CONVERTIBLE_MATURITY_PATTERN)
    interest_match = _unique_evidence_match(bundle, _CONVERTIBLE_INTEREST_PATTERN)
    covenant_match = _unique_evidence_match(bundle, _CONVERTIBLE_COVENANT_PATTERN)
    if convertible_match is not None:
        evidence, match = convertible_match
        evidence_ids = [evidence.evidence_id]
        maturity_on: date | None = None
        interest_rate: Decimal | None = None
        covenant_text: tuple[str, ...] = ()
        if maturity_match is not None:
            maturity_evidence, maturity = maturity_match
            maturity_on = _reported_date(maturity.group("date"))
            evidence_ids.append(maturity_evidence.evidence_id)
        if interest_match is not None:
            interest_evidence, interest = interest_match
            interest_rate = _reported_decimal(interest.group("rate"))
            evidence_ids.append(interest_evidence.evidence_id)
        if covenant_match is not None:
            covenant_evidence, covenant = covenant_match
            covenant_text = (covenant.group("covenants"),)
            evidence_ids.append(covenant_evidence.evidence_id)
        terms.append(
            FinancingTerm(
                instrument=FinancingInstrument.CONVERTIBLE_DEBT,
                status=FinancingEventStatus.CLOSED,
                money=(
                    ReportedMoney(
                        amount=_reported_decimal(match.group("principal")),
                        currency="USD",
                        basis=MoneyBasis.PRINCIPAL,
                    ),
                ),
                interest_rate_percent=interest_rate,
                maturity_on=maturity_on,
                covenant_text=covenant_text,
                evidence_ids=tuple(dict.fromkeys(evidence_ids)),
            )
        )

    preferred_match = _unique_evidence_match(bundle, _PREFERRED_EQUITY_PATTERN)
    if preferred_match is not None:
        evidence, match = preferred_match
        terms.append(
            FinancingTerm(
                instrument=FinancingInstrument.PREFERRED_EQUITY,
                status=FinancingEventStatus.PROPOSED,
                money=(
                    ReportedMoney(
                        amount=_reported_decimal(match.group("gross")),
                        currency="USD",
                        basis=MoneyBasis.GROSS_PROCEEDS,
                    ),
                ),
                offered_shares=_reported_decimal(match.group("shares")),
                issuer_proceeds_status=IssuerProceedsStatus.REPORTED,
                evidence_ids=(evidence.evidence_id,),
            )
        )

    warrant_match = _unique_evidence_match(bundle, _PRIVATE_PLACEMENT_WARRANT_PATTERN)
    if warrant_match is not None:
        evidence, match = warrant_match
        terms.append(
            FinancingTerm(
                instrument=FinancingInstrument.WARRANT,
                status=FinancingEventStatus.PRICED,
                issuable_shares=_reported_decimal(match.group("shares")),
                exercise_price=_reported_decimal(match.group("price")),
                evidence_ids=(evidence.evidence_id,),
            )
        )
    return tuple(terms)


def parse_warrant_change_terms(bundle: FinancingEvidenceBundle) -> tuple[FinancingTerm, ...]:
    """Parse exact warrant repricing and proposed exercise-inducement disclosures."""

    terms: list[FinancingTerm] = []
    repricing_match = _unique_evidence_match(bundle, _WARRANT_REPRICING_PATTERN)
    if repricing_match is not None:
        evidence, match = repricing_match
        terms.append(
            FinancingTerm(
                instrument=FinancingInstrument.WARRANT_REPRICING,
                status=FinancingEventStatus.AMENDED,
                previous_exercise_price=_reported_decimal(match.group("previous")),
                exercise_price=_reported_decimal(match.group("current")),
                evidence_ids=(evidence.evidence_id,),
            )
        )

    inducement_match = _unique_evidence_match(bundle, _EXERCISE_INDUCEMENT_PATTERN)
    new_shares_match = _unique_evidence_match(bundle, _EXERCISE_INDUCEMENT_NEW_SHARES_PATTERN)
    new_price_match = _unique_evidence_match(bundle, _EXERCISE_INDUCEMENT_NEW_PRICE_PATTERN)
    if (
        inducement_match is not None
        and new_shares_match is not None
        and new_price_match is not None
    ):
        evidence, match = inducement_match
        shares_evidence, shares = new_shares_match
        price_evidence, price = new_price_match
        money: tuple[ReportedMoney, ...] = ()
        evidence_ids = [
            evidence.evidence_id,
            shares_evidence.evidence_id,
            price_evidence.evidence_id,
        ]
        gross_match = _unique_evidence_match(bundle, _EXERCISE_INDUCEMENT_GROSS_PATTERN)
        if gross_match is not None:
            gross_evidence, gross = gross_match
            money = (
                ReportedMoney(
                    amount=_reported_scaled_decimal(gross.group("amount"), gross.group("scale")),
                    currency="USD",
                    basis=MoneyBasis.GROSS_PROCEEDS,
                    amount_status=ReportedAmountStatus.EXPECTED,
                ),
            )
            evidence_ids.append(gross_evidence.evidence_id)
        terms.append(
            FinancingTerm(
                instrument=FinancingInstrument.WARRANT_EXERCISE_INDUCEMENT,
                status=FinancingEventStatus.PROPOSED,
                money=money,
                issuable_shares=_reported_decimal(shares.group("shares")),
                price_per_share=_reported_decimal(match.group("reduced")),
                exercise_price=_reported_decimal(price.group("price")),
                issuer_proceeds_status=(
                    IssuerProceedsStatus.REPORTED if money else IssuerProceedsStatus.UNKNOWN
                ),
                evidence_ids=tuple(dict.fromkeys(evidence_ids)),
            )
        )
    return tuple(terms)


def parse_equity_line_terms(bundle: FinancingEvidenceBundle) -> tuple[FinancingTerm, ...]:
    """Parse a disclosed equity-line commitment only when its termination is explicit."""

    commitment_match = _unique_evidence_match(bundle, _EQUITY_LINE_COMMITMENT_PATTERN)
    termination_evidence = _evidence_containing(
        bundle, "Equity Purchase Agreement terminated effective as of"
    )
    if commitment_match is None or termination_evidence is None:
        return ()
    evidence, match = commitment_match
    return (
        FinancingTerm(
            instrument=FinancingInstrument.EQUITY_LINE,
            status=FinancingEventStatus.TERMINATED,
            money=(
                ReportedMoney(
                    amount=_reported_decimal(match.group("amount")),
                    currency="USD",
                    basis=MoneyBasis.COMMITMENT,
                ),
            ),
            evidence_ids=tuple(
                dict.fromkeys((evidence.evidence_id, termination_evidence.evidence_id))
            ),
        ),
    )


def parse_debt_terms(bundle: FinancingEvidenceBundle) -> tuple[FinancingTerm, ...]:
    """Parse a closed fixed-rate notes offering with an exact stated maturity."""

    offering_match = _unique_evidence_match(bundle, _DEBT_OFFERING_PATTERN)
    maturity_match = _unique_evidence_match(bundle, _DEBT_MATURITY_PATTERN)
    if offering_match is None or maturity_match is None:
        return ()
    offering_evidence, offering = offering_match
    maturity_evidence, maturity = maturity_match
    if maturity.group("date").endswith(offering.group("due_year")) is False:
        raise FinancingParseError("debt due year conflicts with its exact maturity date")
    return (
        FinancingTerm(
            instrument=FinancingInstrument.DEBT,
            status=FinancingEventStatus.CLOSED,
            money=(
                ReportedMoney(
                    amount=_reported_scaled_decimal(
                        offering.group("principal"), offering.group("scale")
                    ),
                    currency="USD",
                    basis=MoneyBasis.PRINCIPAL,
                ),
            ),
            interest_rate_percent=_reported_decimal(offering.group("rate")),
            maturity_on=_reported_date(maturity.group("date")),
            evidence_ids=tuple(
                dict.fromkeys((offering_evidence.evidence_id, maturity_evidence.evidence_id))
            ),
        ),
    )


def parse_financing_terms(bundle: FinancingEvidenceBundle) -> tuple[FinancingTerm, ...]:
    """Return every deterministically supported term in stable instrument order."""

    return (
        *parse_shelf_atm_terms(bundle),
        *parse_public_offering_terms(bundle),
        *parse_private_placement_terms(bundle),
        *parse_convertible_preferred_warrant_terms(bundle),
        *parse_warrant_change_terms(bundle),
        *parse_equity_line_terms(bundle),
        *parse_debt_terms(bundle),
    )


def choose_financing_tier(receipt: FinancingFilingReceipt) -> FinancingTier0Receipt:
    """Retain exact financing context without adding direction or model work."""

    instruments = tuple(sorted({term.instrument for term in receipt.terms}, key=str))
    categories: set[FinancingEventContext] = set()
    for instrument in instruments:
        if instrument in {
            FinancingInstrument.SHELF_REGISTRATION,
            FinancingInstrument.RESALE_REGISTRATION,
        }:
            categories.add(FinancingEventContext.REGISTRATION_CAPACITY)
        elif instrument in {
            FinancingInstrument.CONVERTIBLE_DEBT,
            FinancingInstrument.DEBT,
        }:
            categories.add(FinancingEventContext.DEBT_FINANCING)
        else:
            categories.add(FinancingEventContext.EQUITY_FINANCING)
    event_context = (
        next(iter(categories)) if len(categories) == 1 else FinancingEventContext.MULTI_INSTRUMENT
    )
    return FinancingTier0Receipt(
        accession_number=receipt.accession_number,
        source_content_sha256=receipt.source_content_sha256,
        event_context=event_context,
        instruments=instruments,
        decision=TierDecision(
            tier=AnalysisTier.TIER_0,
            outcome=TierOutcome.RETAIN,
            reason=EscalationReason.FINANCING_CONTEXT,
            requires_model=False,
            explanation="Exact financing terms are retained without directional interpretation.",
            estimated_context_chars=0,
        ),
    )


def _unique_evidence_match(
    bundle: FinancingEvidenceBundle, pattern: re.Pattern[str]
) -> tuple[FinancingEvidenceExcerpt, re.Match[str]] | None:
    matches = tuple(
        (evidence, match)
        for evidence in bundle.evidence
        if (match := pattern.search(evidence.text)) is not None
    )
    if not matches:
        return None
    distinct_values = {match.groups() for _, match in matches}
    if len(distinct_values) != 1:
        raise FinancingParseError("conflicting repeated financing amounts")
    return matches[0]


def _evidence_containing(
    bundle: FinancingEvidenceBundle, phrase: str
) -> FinancingEvidenceExcerpt | None:
    matches = tuple(item for item in bundle.evidence if phrase.casefold() in item.text.casefold())
    if len(matches) > 1:
        return matches[0]
    return matches[0] if matches else None


def _evidence_with_signal(
    bundle: FinancingEvidenceBundle, signal: FinancingEvidenceSignal
) -> FinancingEvidenceExcerpt | None:
    matches = tuple(item for item in bundle.evidence if signal in item.signals)
    return matches[0] if matches else None


def _reported_decimal(value: str) -> Decimal:
    return Decimal(value.replace(",", ""))


def _reported_scaled_decimal(value: str, scale: str) -> Decimal:
    multiplier = {"million": Decimal("1000000"), "billion": Decimal("1000000000")}
    try:
        return _reported_decimal(value) * multiplier[scale.casefold()]
    except KeyError as error:
        raise FinancingParseError("unsupported reported money scale") from error


def _reported_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%B %d, %Y").date()
    except ValueError as error:
        raise FinancingParseError("invalid reported financing date") from error


def _find_signal_hits(lowered: str) -> tuple[_SignalHit, ...]:
    hits: list[_SignalHit] = []
    for signal, phrases in _SIGNAL_PHRASES.items():
        for phrase in phrases:
            offset = 0
            while (position := lowered.find(phrase, offset)) >= 0:
                hits.append(_SignalHit(position=position, signal=signal, phrase=phrase))
                offset = position + len(phrase)
    return tuple(sorted(hits, key=lambda item: (item.position, str(item.signal))))


def _prioritize_signal_hits(hits: tuple[_SignalHit, ...]) -> tuple[_SignalHit, ...]:
    first_by_signal: dict[FinancingEvidenceSignal, _SignalHit] = {}
    for hit in hits:
        first_by_signal.setdefault(hit.signal, hit)
    prioritized: list[_SignalHit] = []
    for signal in FinancingEvidenceSignal:
        if signal in first_by_signal:
            prioritized.append(first_by_signal[signal])
    prioritized.extend(hits)
    return tuple(dict.fromkeys(prioritized))


def _whole_word_evidence_window(text: str, position: int) -> tuple[int, int]:
    rough_start = max(0, position - MAXIMUM_EVIDENCE_CHARACTERS // 2)
    rough_end = min(len(text), position + MAXIMUM_EVIDENCE_CHARACTERS // 2)
    start = rough_start
    end = rough_end
    if rough_start:
        boundary = text.find(" ", rough_start, position)
        if boundary >= 0:
            start = boundary + 1
    if rough_end < len(text):
        boundary = text.rfind(" ", position, rough_end)
        if boundary > position:
            end = boundary
    return start, end
