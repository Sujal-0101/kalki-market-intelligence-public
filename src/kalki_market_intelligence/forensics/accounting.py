"""Closed deterministic accounting, auditor, and compliance evidence contracts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from html.parser import HTMLParser
from typing import Final, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from pydantic import Field, HttpUrl, model_validator

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

ACCOUNTING_PARSER_VERSION: Final[Literal["sec-accounting-compliance-v1"]] = (
    "sec-accounting-compliance-v1"
)
MAXIMUM_ACCOUNTING_HTML_BYTES = 2_000_000
MAXIMUM_ACCOUNTING_EVIDENCE = 16
MAXIMUM_ACCOUNTING_EVIDENCE_CHARACTERS = 900
MAXIMUM_TOTAL_ACCOUNTING_EVIDENCE_CHARACTERS = 9_000
_ACCOUNTING_NAMESPACE = UUID("41000000-0000-4000-8000-000000000042")


class AccountingParseError(ValueError):
    """Primary-source accounting evidence cannot enter the closed contract."""


class AccountingForm(StrEnum):
    FORM_8_K = "8-K"
    FORM_8_K_A = "8-K/A"
    NT_10_K = "NT 10-K"
    NT_10_Q = "NT 10-Q"
    FORM_10_K = "10-K"
    FORM_10_K_A = "10-K/A"
    FORM_10_Q = "10-Q"
    FORM_10_Q_A = "10-Q/A"


class AccountingEventType(StrEnum):
    LISTING_COMPLIANCE = "LISTING_COMPLIANCE"
    AUDITOR_CHANGE = "AUDITOR_CHANGE"
    NON_RELIANCE_RESTATEMENT = "NON_RELIANCE_RESTATEMENT"
    LATE_FILING = "LATE_FILING"
    GOING_CONCERN = "GOING_CONCERN"
    INTERNAL_CONTROLS = "INTERNAL_CONTROLS"
    SIGNIFICANT_ACCOUNTING = "SIGNIFICANT_ACCOUNTING"


class AccountingEvidenceSignal(StrEnum):
    """Literal disclosure signals; none is a fraud or directional conclusion."""

    ITEM_3_01_NOTICE = "ITEM_3_01_NOTICE"
    LISTING_NONCOMPLIANCE_LANGUAGE = "LISTING_NONCOMPLIANCE_LANGUAGE"
    DELISTING_LANGUAGE = "DELISTING_LANGUAGE"
    REGAINED_COMPLIANCE_LANGUAGE = "REGAINED_COMPLIANCE_LANGUAGE"
    TRANSFER_OF_LISTING_LANGUAGE = "TRANSFER_OF_LISTING_LANGUAGE"
    ITEM_4_01_NOTICE = "ITEM_4_01_NOTICE"
    AUDITOR_DISMISSAL_LANGUAGE = "AUDITOR_DISMISSAL_LANGUAGE"
    AUDITOR_RESIGNATION_LANGUAGE = "AUDITOR_RESIGNATION_LANGUAGE"
    AUDITOR_ENGAGEMENT_LANGUAGE = "AUDITOR_ENGAGEMENT_LANGUAGE"
    AUDITOR_DISAGREEMENT_LANGUAGE = "AUDITOR_DISAGREEMENT_LANGUAGE"
    REPORTABLE_EVENT_LANGUAGE = "REPORTABLE_EVENT_LANGUAGE"
    ITEM_4_02_NON_RELIANCE = "ITEM_4_02_NON_RELIANCE"
    RESTATEMENT_LANGUAGE = "RESTATEMENT_LANGUAGE"
    LATE_FILING_NOTICE = "LATE_FILING_NOTICE"
    GOING_CONCERN_LANGUAGE = "GOING_CONCERN_LANGUAGE"
    MATERIAL_WEAKNESS_LANGUAGE = "MATERIAL_WEAKNESS_LANGUAGE"
    CONTROL_INEFFECTIVENESS_LANGUAGE = "CONTROL_INEFFECTIVENESS_LANGUAGE"
    CONTROL_CHANGE_LANGUAGE = "CONTROL_CHANGE_LANGUAGE"
    REMEDIATION_LANGUAGE = "REMEDIATION_LANGUAGE"
    ACCOUNTING_ERROR_OR_POLICY_LANGUAGE = "ACCOUNTING_ERROR_OR_POLICY_LANGUAGE"


class AccountingComparisonDisposition(StrEnum):
    NEW_DISCLOSURE = "NEW_DISCLOSURE"
    REPEATED_DISCLOSURE = "REPEATED_DISCLOSURE"
    CHANGED_DISCLOSURE = "CHANGED_DISCLOSURE"
    PRIOR_COMPARISON_UNAVAILABLE = "PRIOR_COMPARISON_UNAVAILABLE"


_EVENT_BY_SIGNAL: dict[AccountingEvidenceSignal, AccountingEventType] = {
    AccountingEvidenceSignal.ITEM_3_01_NOTICE: AccountingEventType.LISTING_COMPLIANCE,
    AccountingEvidenceSignal.LISTING_NONCOMPLIANCE_LANGUAGE: (
        AccountingEventType.LISTING_COMPLIANCE
    ),
    AccountingEvidenceSignal.DELISTING_LANGUAGE: AccountingEventType.LISTING_COMPLIANCE,
    AccountingEvidenceSignal.REGAINED_COMPLIANCE_LANGUAGE: (AccountingEventType.LISTING_COMPLIANCE),
    AccountingEvidenceSignal.TRANSFER_OF_LISTING_LANGUAGE: (AccountingEventType.LISTING_COMPLIANCE),
    AccountingEvidenceSignal.ITEM_4_01_NOTICE: AccountingEventType.AUDITOR_CHANGE,
    AccountingEvidenceSignal.AUDITOR_DISMISSAL_LANGUAGE: AccountingEventType.AUDITOR_CHANGE,
    AccountingEvidenceSignal.AUDITOR_RESIGNATION_LANGUAGE: AccountingEventType.AUDITOR_CHANGE,
    AccountingEvidenceSignal.AUDITOR_ENGAGEMENT_LANGUAGE: AccountingEventType.AUDITOR_CHANGE,
    AccountingEvidenceSignal.AUDITOR_DISAGREEMENT_LANGUAGE: AccountingEventType.AUDITOR_CHANGE,
    AccountingEvidenceSignal.REPORTABLE_EVENT_LANGUAGE: AccountingEventType.AUDITOR_CHANGE,
    AccountingEvidenceSignal.ITEM_4_02_NON_RELIANCE: (AccountingEventType.NON_RELIANCE_RESTATEMENT),
    AccountingEvidenceSignal.RESTATEMENT_LANGUAGE: (AccountingEventType.NON_RELIANCE_RESTATEMENT),
    AccountingEvidenceSignal.LATE_FILING_NOTICE: AccountingEventType.LATE_FILING,
    AccountingEvidenceSignal.GOING_CONCERN_LANGUAGE: AccountingEventType.GOING_CONCERN,
    AccountingEvidenceSignal.MATERIAL_WEAKNESS_LANGUAGE: AccountingEventType.INTERNAL_CONTROLS,
    AccountingEvidenceSignal.CONTROL_INEFFECTIVENESS_LANGUAGE: (
        AccountingEventType.INTERNAL_CONTROLS
    ),
    AccountingEvidenceSignal.CONTROL_CHANGE_LANGUAGE: AccountingEventType.INTERNAL_CONTROLS,
    AccountingEvidenceSignal.REMEDIATION_LANGUAGE: AccountingEventType.INTERNAL_CONTROLS,
    AccountingEvidenceSignal.ACCOUNTING_ERROR_OR_POLICY_LANGUAGE: (
        AccountingEventType.SIGNIFICANT_ACCOUNTING
    ),
}


class AccountingEvidenceExcerpt(ContractModel):
    evidence_id: UUID
    signals: tuple[AccountingEvidenceSignal, ...] = Field(min_length=1, max_length=8)
    item_number: str | None = Field(default=None, pattern=r"^[34][.]0[12]$")
    locator: ShortText
    text: NonEmptyText = Field(max_length=MAXIMUM_ACCOUNTING_EVIDENCE_CHARACTERS)
    text_sha256: Sha256Hex
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)

    @model_validator(mode="after")
    def exact_text_and_identity_reconcile(self) -> AccountingEvidenceExcerpt:
        if self.signals != tuple(sorted(set(self.signals), key=str)):
            raise ValueError("accounting evidence signals must be sorted and unique")
        if self.end_offset - self.start_offset != len(self.text):
            raise ValueError("accounting evidence offsets must match exact text length")
        if hashlib.sha256(self.text.encode()).hexdigest() != self.text_sha256:
            raise ValueError("accounting evidence hash does not match exact text")
        if self.locator != f"normalized-visible-text:{self.start_offset}-{self.end_offset}":
            raise ValueError("accounting evidence locator does not match offsets")
        return self


class AccountingEvidenceBundle(ContractModel):
    source_content_sha256: Sha256Hex
    visible_text_sha256: Sha256Hex
    evidence: tuple[AccountingEvidenceExcerpt, ...] = Field(
        default=(), max_length=MAXIMUM_ACCOUNTING_EVIDENCE
    )
    extractor_version: Literal["sec-accounting-compliance-v1"] = ACCOUNTING_PARSER_VERSION

    @model_validator(mode="after")
    def evidence_is_unique_and_bounded(self) -> AccountingEvidenceBundle:
        identities = tuple(item.evidence_id for item in self.evidence)
        if len(identities) != len(set(identities)):
            raise ValueError("accounting evidence IDs must be unique")
        positions = tuple((item.start_offset, item.end_offset) for item in self.evidence)
        if positions != tuple(sorted(positions)):
            raise ValueError("accounting evidence must use deterministic source order")
        for item in self.evidence:
            expected_evidence_id = uuid5(
                _ACCOUNTING_NAMESPACE,
                (
                    f"{self.source_content_sha256}:{item.start_offset}:{item.end_offset}:"
                    f"{','.join(item.signals)}"
                ),
            )
            if item.evidence_id != expected_evidence_id:
                raise ValueError("accounting evidence identity does not reconcile")
        if sum(len(item.text) for item in self.evidence) > (
            MAXIMUM_TOTAL_ACCOUNTING_EVIDENCE_CHARACTERS
        ):
            raise ValueError("accounting evidence exceeds the aggregate text boundary")
        return self


class AccountingEvent(ContractModel):
    event_id: UUID
    event_type: AccountingEventType
    signals: tuple[AccountingEvidenceSignal, ...] = Field(min_length=1, max_length=16)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=16)
    event_fingerprint: Sha256Hex
    comparison: AccountingComparisonDisposition
    prior_accession_number: AccessionNumber | None = None
    prior_event_id: UUID | None = None
    prior_event_fingerprint: Sha256Hex | None = None

    @model_validator(mode="after")
    def comparison_lineage_is_complete(self) -> AccountingEvent:
        if self.signals != tuple(sorted(set(self.signals), key=str)):
            raise ValueError("accounting event signals must be sorted and unique")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("accounting event evidence IDs must be unique")
        prior = (
            self.prior_accession_number,
            self.prior_event_id,
            self.prior_event_fingerprint,
        )
        requires_prior = self.comparison in {
            AccountingComparisonDisposition.REPEATED_DISCLOSURE,
            AccountingComparisonDisposition.CHANGED_DISCLOSURE,
        }
        if requires_prior != all(item is not None for item in prior):
            raise ValueError("accounting comparison must have complete prior lineage or none")
        if not requires_prior and any(item is not None for item in prior):
            raise ValueError("new or unavailable comparison cannot retain prior lineage")
        if (
            self.comparison is AccountingComparisonDisposition.REPEATED_DISCLOSURE
            and self.prior_event_fingerprint != self.event_fingerprint
        ):
            raise ValueError("repeated accounting disclosure requires the same fingerprint")
        if (
            self.comparison is AccountingComparisonDisposition.CHANGED_DISCLOSURE
            and self.prior_event_fingerprint == self.event_fingerprint
        ):
            raise ValueError("changed accounting disclosure requires a changed fingerprint")
        return self


class AccountingFilingReceipt(ContractModel):
    receipt_id: UUID
    accession_number: AccessionNumber
    issuer_cik: Cik
    issuer_name: ShortText
    form: AccountingForm
    source_url: HttpUrl
    source_content_sha256: Sha256Hex
    accepted_at: UtcDatetime
    retrieved_at: UtcDatetime
    prior_search_complete: bool
    evidence_bundle: AccountingEvidenceBundle
    events: tuple[AccountingEvent, ...] = Field(default=(), max_length=7)
    parser_version: Literal["sec-accounting-compliance-v1"] = ACCOUNTING_PARSER_VERSION

    @model_validator(mode="after")
    def source_events_and_identity_reconcile(self) -> AccountingFilingReceipt:
        if self.retrieved_at < self.accepted_at:
            raise ValueError("accounting retrieval cannot precede SEC acceptance")
        if self.evidence_bundle.source_content_sha256 != self.source_content_sha256:
            raise ValueError("accounting evidence and filing source hashes must match")
        _validate_primary_source_url(
            str(self.source_url),
            cik=self.issuer_cik,
            accession_number=self.accession_number,
        )
        expected_receipt_id = uuid5(
            _ACCOUNTING_NAMESPACE,
            f"{self.accession_number}:{self.source_content_sha256}:{self.parser_version}",
        )
        if self.receipt_id != expected_receipt_id:
            raise ValueError("accounting receipt identity does not reconcile")
        if tuple(item.event_type for item in self.events) != tuple(
            sorted((item.event_type for item in self.events), key=str)
        ):
            raise ValueError("accounting events must use deterministic type order")
        if len({item.event_type for item in self.events}) != len(self.events):
            raise ValueError("accounting receipt cannot repeat an event type")
        evidence_by_id = {item.evidence_id: item for item in self.evidence_bundle.evidence}
        for event in self.events:
            if not set(event.evidence_ids).issubset(evidence_by_id):
                raise ValueError("accounting event references absent exact evidence")
            evidence = tuple(evidence_by_id[item] for item in event.evidence_ids)
            if evidence != tuple(sorted(evidence, key=lambda item: item.start_offset)):
                raise ValueError("accounting event evidence must use deterministic source order")
            if event.signals != _event_signals(event.event_type, evidence):
                raise ValueError("accounting event signals do not reconcile to evidence")
            if event.event_fingerprint != _event_fingerprint(event.event_type, evidence):
                raise ValueError("accounting event fingerprint does not reconcile")
            expected_event_id = uuid5(
                _ACCOUNTING_NAMESPACE,
                f"{self.source_content_sha256}:{event.event_type}:{event.event_fingerprint}",
            )
            if event.event_id != expected_event_id:
                raise ValueError("accounting event identity does not reconcile")
            if (
                event.comparison is AccountingComparisonDisposition.NEW_DISCLOSURE
                and not self.prior_search_complete
            ):
                raise ValueError("new accounting disclosure requires a complete prior search")
        return self


class AccountingTier0Receipt(ContractModel):
    """Model-free routing for exact accounting/compliance disclosure context."""

    accession_number: AccessionNumber
    source_content_sha256: Sha256Hex
    event_types: tuple[AccountingEventType, ...] = Field(min_length=1, max_length=7)
    decision: TierDecision
    routing_version: Literal["accounting-tier0-v1"] = "accounting-tier0-v1"

    @model_validator(mode="after")
    def routing_is_closed_and_model_free(self) -> AccountingTier0Receipt:
        if self.event_types != tuple(sorted(set(self.event_types), key=str)):
            raise ValueError("accounting routing event types must be sorted and unique")
        if (
            self.decision.tier is not AnalysisTier.TIER_0
            or self.decision.outcome is not TierOutcome.RETAIN
            or self.decision.reason is not EscalationReason.ACCOUNTING_COMPLIANCE_CONTEXT
            or self.decision.requires_model
            or self.decision.forensic_signals
        ):
            raise ValueError("accounting routing must remain model-free Tier-0 context")
        return self


def normalize_accounting_form(value: str) -> AccountingForm:
    """Normalize only the explicitly supported Phase 41 SEC form names."""

    normalized = " ".join(value.strip().upper().split())
    try:
        return AccountingForm(normalized)
    except ValueError as error:
        raise AccountingParseError(f"unsupported accounting form metadata: {normalized}") from error


def choose_accounting_tier(receipt: AccountingFilingReceipt) -> AccountingTier0Receipt:
    """Retain exact disclosure context without fraud, direction, or model work."""

    if not receipt.events:
        raise ValueError("accounting routing requires at least one exact event")
    event_types = tuple(sorted({item.event_type for item in receipt.events}, key=str))
    referenced = {evidence_id for event in receipt.events for evidence_id in event.evidence_ids}
    evidence = tuple(
        item for item in receipt.evidence_bundle.evidence if item.evidence_id in referenced
    )
    return AccountingTier0Receipt(
        accession_number=receipt.accession_number,
        source_content_sha256=receipt.source_content_sha256,
        event_types=event_types,
        decision=TierDecision(
            tier=AnalysisTier.TIER_0,
            outcome=TierOutcome.RETAIN,
            reason=EscalationReason.ACCOUNTING_COMPLIANCE_CONTEXT,
            requires_model=False,
            explanation=(
                "Exact accounting, auditor, or compliance disclosure context is retained "
                "without fraud or directional interpretation."
            ),
            estimated_context_chars=sum(len(item.text) for item in evidence),
            evidence_ids=tuple(item.evidence_id for item in evidence),
        ),
    )


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {
            "script",
            "style",
            "svg",
            "noscript",
            "template",
            "xbrl",
            "ix:header",
        }:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {
            "script",
            "style",
            "svg",
            "noscript",
            "template",
            "xbrl",
            "ix:header",
        }:
            self._ignored_depth = max(0, self._ignored_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)


_ITEM_RE = re.compile(r"\bITEM\s+([1-9][.]\d{2})\b", re.IGNORECASE)
_SIGNAL_PATTERNS: tuple[tuple[AccountingEvidenceSignal, re.Pattern[str]], ...] = (
    (
        AccountingEvidenceSignal.LISTING_NONCOMPLIANCE_LANGUAGE,
        re.compile(
            r"\b(?:not in compliance|does not comply|non-compliance|deficienc(?:y|ies))\b", re.I
        ),
    ),
    (AccountingEvidenceSignal.DELISTING_LANGUAGE, re.compile(r"\bdelist(?:ing|ed)?\b", re.I)),
    (
        AccountingEvidenceSignal.REGAINED_COMPLIANCE_LANGUAGE,
        re.compile(r"\b(?:regained compliance|has determined that .{0,240}? complies)\b", re.I),
    ),
    (
        AccountingEvidenceSignal.TRANSFER_OF_LISTING_LANGUAGE,
        re.compile(r"\btransfer(?:red|ring)? (?:of |its )?listing\b", re.I),
    ),
    (
        AccountingEvidenceSignal.AUDITOR_DISMISSAL_LANGUAGE,
        re.compile(
            r"\b(?:dismissed|terminated)\b.{0,160}\b(?:accountant|auditor|accounting firm)\b", re.I
        ),
    ),
    (
        AccountingEvidenceSignal.AUDITOR_RESIGNATION_LANGUAGE,
        re.compile(
            r"\b(?:accountant|auditor|accounting firm)\b.{0,160}\bresigned\b|"
            r"\bresigned\b.{0,160}\b(?:accountant|auditor|accounting firm)\b",
            re.I,
        ),
    ),
    (
        AccountingEvidenceSignal.AUDITOR_ENGAGEMENT_LANGUAGE,
        re.compile(
            r"\b(?:engaged|appointed)\b.{0,180}\b(?:accountant|auditor|accounting firm)\b", re.I
        ),
    ),
    (
        AccountingEvidenceSignal.AUDITOR_DISAGREEMENT_LANGUAGE,
        re.compile(
            r"\bdisagreements?\b.{0,220}\b(?:accounting|auditing|financial statement|disclosure)\b",
            re.I,
        ),
    ),
    (
        AccountingEvidenceSignal.REPORTABLE_EVENT_LANGUAGE,
        re.compile(r"\breportable events?\b", re.I),
    ),
    (
        AccountingEvidenceSignal.RESTATEMENT_LANGUAGE,
        re.compile(r"\brestat(?:e|ed|ement|ements|ing)\b", re.I),
    ),
    (
        AccountingEvidenceSignal.GOING_CONCERN_LANGUAGE,
        re.compile(
            r"\bsubstantial doubt\b.{0,220}\b(?:continue|going concern)\b|"
            r"\bability to continue as a going concern\b|"
            r"\bgoing concern uncertainty\b",
            re.I,
        ),
    ),
    (
        AccountingEvidenceSignal.MATERIAL_WEAKNESS_LANGUAGE,
        re.compile(r"\bmaterial weakness(?:es)?\b", re.I),
    ),
    (
        AccountingEvidenceSignal.CONTROL_INEFFECTIVENESS_LANGUAGE,
        re.compile(
            r"\b(?:disclosure controls(?: and procedures)?|"
            r"internal control(?: over financial reporting)?)\b.{0,220}"
            r"\b(?:not effective|ineffective|were not effective|was not effective)\b",
            re.I,
        ),
    ),
    (
        AccountingEvidenceSignal.CONTROL_CHANGE_LANGUAGE,
        re.compile(
            r"\b(?:"
            r"(?:we|management|the company) (?:made|implemented|completed|identified)"
            r".{0,80}\bchanges? (?:to|in)|"
            r"changes? (?:were|was) made (?:to|in)|"
            r"there (?:has|have) been (?!no\b).{0,40}\bchanges? in|"
            r"there (?:was|were) (?!no\b).{0,40}\bchanges? in"
            r") (?:the company's |our )?internal controls?"
            r"(?: over financial reporting)?\b",
            re.I,
        ),
    ),
    (
        AccountingEvidenceSignal.REMEDIATION_LANGUAGE,
        re.compile(r"\b(?:remediat(?:e|ed|ion|ing)|corrective action)\b", re.I),
    ),
    (
        AccountingEvidenceSignal.ACCOUNTING_ERROR_OR_POLICY_LANGUAGE,
        re.compile(
            r"\b(?:accounting errors?|error in accounting|accounting misstatements?|"
            r"change in accounting (?:principle|estimate)|"
            r"correction of (?:an |the )?accounting (?:error|misstatement))\b",
            re.I,
        ),
    ),
)


def normalized_accounting_visible_text(body: bytes) -> str:
    """Normalize visible primary-document text while excluding executable/header markup."""

    if not body or len(body) > MAXIMUM_ACCOUNTING_HTML_BYTES:
        raise AccountingParseError("accounting primary document is empty or oversized")
    parser = _VisibleTextParser()
    try:
        parser.feed(body.decode("utf-8", errors="replace"))
        parser.close()
    except (TypeError, ValueError) as error:
        raise AccountingParseError("accounting primary document could not be parsed") from error
    visible = " ".join(parser.parts)
    normalized = " ".join(visible.replace("\x00", " ").split())
    if not normalized:
        raise AccountingParseError("accounting primary document has no visible text")
    return normalized


def extract_accounting_evidence(
    body: bytes,
    *,
    form: AccountingForm,
) -> AccountingEvidenceBundle:
    """Extract literal supported evidence without assigning fraud or direction."""

    visible = normalized_accounting_visible_text(body)
    source_sha256 = hashlib.sha256(body).hexdigest()
    candidates: dict[tuple[int, int, str | None], set[AccountingEvidenceSignal]] = {}
    for region_start, region_end, item_number, base_signal in _regions(visible, form):
        if base_signal is not None:
            start, end = _evidence_window(
                visible,
                hit_start=region_start,
                hit_end=min(region_end, region_start + 32),
                region_start=region_start,
                region_end=region_end,
            )
            candidates.setdefault((start, end, item_number), set()).add(base_signal)
        for signal, pattern in _SIGNAL_PATTERNS:
            if not _signal_allowed(signal, form=form, item_number=item_number):
                continue
            match = pattern.search(visible, region_start, region_end)
            if match is None:
                continue
            start, end = _evidence_window(
                visible,
                hit_start=match.start(),
                hit_end=match.end(),
                region_start=region_start,
                region_end=region_end,
            )
            candidates.setdefault((start, end, item_number), set()).add(signal)

    evidence: list[AccountingEvidenceExcerpt] = []
    retained_characters = 0
    for (start, end, item_number), signals in sorted(candidates.items()):
        text = visible[start:end]
        if retained_characters + len(text) > MAXIMUM_TOTAL_ACCOUNTING_EVIDENCE_CHARACTERS:
            continue
        ordered_signals = tuple(sorted(signals, key=str))
        evidence_id = uuid5(
            _ACCOUNTING_NAMESPACE,
            f"{source_sha256}:{start}:{end}:{','.join(ordered_signals)}",
        )
        evidence.append(
            AccountingEvidenceExcerpt(
                evidence_id=evidence_id,
                signals=ordered_signals,
                item_number=item_number,
                locator=f"normalized-visible-text:{start}-{end}",
                text=text,
                text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                start_offset=start,
                end_offset=end,
            )
        )
        retained_characters += len(text)
        if len(evidence) == MAXIMUM_ACCOUNTING_EVIDENCE:
            break
    return AccountingEvidenceBundle(
        source_content_sha256=source_sha256,
        visible_text_sha256=hashlib.sha256(visible.encode()).hexdigest(),
        evidence=tuple(evidence),
    )


def build_accounting_filing_receipt(
    *,
    accession_number: str,
    issuer_cik: str,
    issuer_name: str,
    form: AccountingForm,
    source_url: str,
    body: bytes,
    accepted_at: datetime,
    retrieved_at: datetime,
    prior_receipts: tuple[AccountingFilingReceipt, ...] = (),
    prior_search_complete: bool,
) -> AccountingFilingReceipt:
    """Build a source-bound receipt and conservative exact prior comparison."""

    bundle = extract_accounting_evidence(body, form=form)
    normalized_issuer_cik = issuer_cik.zfill(10) if issuer_cik.isdigit() else issuer_cik
    grouped: dict[AccountingEventType, list[AccountingEvidenceExcerpt]] = {}
    for excerpt in bundle.evidence:
        for event_type in {_EVENT_BY_SIGNAL[item] for item in excerpt.signals}:
            grouped.setdefault(event_type, []).append(excerpt)

    prior = tuple(
        receipt
        for receipt in prior_receipts
        if receipt.issuer_cik == normalized_issuer_cik
        and receipt.accepted_at < accepted_at
        and receipt.retrieved_at <= retrieved_at
        and receipt.parser_version == ACCOUNTING_PARSER_VERSION
    )
    events: list[AccountingEvent] = []
    for event_type in sorted(grouped, key=str):
        event_evidence = tuple(sorted(grouped[event_type], key=lambda item: item.start_offset))
        fingerprint = _event_fingerprint(event_type, event_evidence)
        prior_events = tuple(
            (receipt, event)
            for receipt in prior
            for event in receipt.events
            if event.event_type is event_type
        )
        exact = tuple(item for item in prior_events if item[1].event_fingerprint == fingerprint)
        selected = max(exact or prior_events, key=lambda item: item[0].accepted_at, default=None)
        if selected is not None:
            comparison = (
                AccountingComparisonDisposition.REPEATED_DISCLOSURE
                if exact
                else AccountingComparisonDisposition.CHANGED_DISCLOSURE
            )
            prior_accession_number = selected[0].accession_number
            prior_event_id = selected[1].event_id
            prior_event_fingerprint = selected[1].event_fingerprint
        else:
            comparison = (
                AccountingComparisonDisposition.NEW_DISCLOSURE
                if prior_search_complete
                else AccountingComparisonDisposition.PRIOR_COMPARISON_UNAVAILABLE
            )
            prior_accession_number = None
            prior_event_id = None
            prior_event_fingerprint = None
        events.append(
            AccountingEvent(
                event_id=uuid5(
                    _ACCOUNTING_NAMESPACE,
                    f"{bundle.source_content_sha256}:{event_type}:{fingerprint}",
                ),
                event_type=event_type,
                signals=_event_signals(event_type, event_evidence),
                evidence_ids=tuple(item.evidence_id for item in event_evidence),
                event_fingerprint=fingerprint,
                comparison=comparison,
                prior_accession_number=prior_accession_number,
                prior_event_id=prior_event_id,
                prior_event_fingerprint=prior_event_fingerprint,
            )
        )
    return AccountingFilingReceipt(
        receipt_id=uuid5(
            _ACCOUNTING_NAMESPACE,
            f"{accession_number}:{bundle.source_content_sha256}:{ACCOUNTING_PARSER_VERSION}",
        ),
        accession_number=accession_number,
        issuer_cik=normalized_issuer_cik,
        issuer_name=issuer_name,
        form=form,
        source_url=HttpUrl(source_url),
        source_content_sha256=bundle.source_content_sha256,
        accepted_at=accepted_at,
        retrieved_at=retrieved_at,
        prior_search_complete=prior_search_complete,
        evidence_bundle=bundle,
        events=tuple(events),
    )


def _regions(
    visible: str,
    form: AccountingForm,
) -> tuple[tuple[int, int, str | None, AccountingEvidenceSignal | None], ...]:
    if form in {AccountingForm.FORM_8_K, AccountingForm.FORM_8_K_A}:
        matches = tuple(_ITEM_RE.finditer(visible))
        by_number: dict[str, tuple[int, int]] = {}
        for index, match in enumerate(matches):
            item_number = match.group(1)
            if item_number not in {"3.01", "4.01", "4.02"}:
                continue
            end = matches[index + 1].start() if index + 1 < len(matches) else len(visible)
            current = by_number.get(item_number)
            if current is None or end - match.start() > current[1] - current[0]:
                by_number[item_number] = (match.start(), end)
        base = {
            "3.01": AccountingEvidenceSignal.ITEM_3_01_NOTICE,
            "4.01": AccountingEvidenceSignal.ITEM_4_01_NOTICE,
            "4.02": AccountingEvidenceSignal.ITEM_4_02_NON_RELIANCE,
        }
        return tuple(
            (start, end, item_number, base[item_number])
            for item_number, (start, end) in sorted(by_number.items())
        )
    if form in {AccountingForm.NT_10_K, AccountingForm.NT_10_Q}:
        late = re.search(
            r"\b(?:unable to file|could not be filed|not timely file)\b", visible, re.I
        )
        if late is None:
            return ()
        return (
            (
                max(0, late.start() - 400),
                len(visible),
                None,
                AccountingEvidenceSignal.LATE_FILING_NOTICE,
            ),
        )
    return ((0, len(visible), None, None),)


def _signal_allowed(
    signal: AccountingEvidenceSignal,
    *,
    form: AccountingForm,
    item_number: str | None,
) -> bool:
    event_type = _EVENT_BY_SIGNAL[signal]
    if item_number == "3.01":
        return event_type is AccountingEventType.LISTING_COMPLIANCE
    if item_number == "4.01":
        return event_type is AccountingEventType.AUDITOR_CHANGE
    if item_number == "4.02":
        return event_type in {
            AccountingEventType.NON_RELIANCE_RESTATEMENT,
            AccountingEventType.INTERNAL_CONTROLS,
            AccountingEventType.SIGNIFICANT_ACCOUNTING,
        }
    if form in {AccountingForm.NT_10_K, AccountingForm.NT_10_Q}:
        return event_type in {
            AccountingEventType.LATE_FILING,
            AccountingEventType.GOING_CONCERN,
            AccountingEventType.INTERNAL_CONTROLS,
            AccountingEventType.SIGNIFICANT_ACCOUNTING,
        }
    return event_type in {
        AccountingEventType.GOING_CONCERN,
        AccountingEventType.INTERNAL_CONTROLS,
        AccountingEventType.SIGNIFICANT_ACCOUNTING,
    }


def _evidence_window(
    visible: str,
    *,
    hit_start: int,
    hit_end: int,
    region_start: int,
    region_end: int,
) -> tuple[int, int]:
    lower = max(region_start, hit_start - 220)
    sentence = max(visible.rfind(". ", lower, hit_start), visible.rfind("; ", lower, hit_start))
    start = sentence + 2 if sentence >= lower else lower
    upper = min(region_end, hit_end + 650)
    sentence_end = visible.find(". ", hit_end, upper)
    end = sentence_end + 1 if sentence_end >= 0 else upper
    if end - start > MAXIMUM_ACCOUNTING_EVIDENCE_CHARACTERS:
        end = start + MAXIMUM_ACCOUNTING_EVIDENCE_CHARACTERS
        final_space = visible.rfind(" ", start, end)
        if final_space > start:
            end = final_space
    while start < end and visible[start].isspace():
        start += 1
    while end > start and visible[end - 1].isspace():
        end -= 1
    return start, end


def _event_signals(
    event_type: AccountingEventType,
    evidence: Iterable[AccountingEvidenceExcerpt],
) -> tuple[AccountingEvidenceSignal, ...]:
    return tuple(
        sorted(
            {
                signal
                for item in evidence
                for signal in item.signals
                if _EVENT_BY_SIGNAL[signal] is event_type
            },
            key=str,
        )
    )


def _event_fingerprint(
    event_type: AccountingEventType,
    evidence: Iterable[AccountingEvidenceExcerpt],
) -> str:
    selected = tuple(evidence)
    payload = {
        "event_type": event_type.value,
        "signals": [item.value for item in _event_signals(event_type, selected)],
        "evidence_text_sha256s": sorted(
            hashlib.sha256(item.text.casefold().encode()).hexdigest() for item in selected
        ),
        "parser_version": ACCOUNTING_PARSER_VERSION,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _validate_primary_source_url(url: str, *, cik: str, accession_number: str) -> None:
    parsed = urlsplit(url)
    expected_prefix = f"/Archives/edgar/data/{int(cik)}/{accession_number.replace('-', '')}/"
    document_name = parsed.path.removeprefix(expected_prefix)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.sec.gov"
        or parsed.port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith(expected_prefix)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*[.](?:htm|html)", document_name, re.I) is None
    ):
        raise ValueError("accounting source URL is not the matching SEC primary document")
