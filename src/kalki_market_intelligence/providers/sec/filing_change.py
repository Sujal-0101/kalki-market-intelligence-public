"""Bounded deterministic section extraction for Phase 42 filing comparisons."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from html.parser import HTMLParser
from typing import Literal, Self

from pydantic import Field, model_validator

from kalki_market_intelligence.contracts.common import ContractModel, Sha256Hex, UtcDatetime
from kalki_market_intelligence.forensics.filing_change import (
    FILING_CHANGE_EXTRACTION_VERSION,
    FilingChangeCategory,
    FilingChangeForm,
    FilingChangeSection,
    FilingChangeSnapshot,
    build_filing_change_section,
    build_filing_change_snapshot,
)
from kalki_market_intelligence.forensics.novelty import EVENT_NOVELTY_RULE_VERSION
from kalki_market_intelligence.radar.analysis_cache import (
    AmendmentEvidenceManifest,
    AmendmentSectionFingerprint,
    build_amendment_manifest,
)
from kalki_market_intelligence.radar.evidence_budget import EVIDENCE_BUDGET_VERSION

MAXIMUM_FILING_CHANGE_HTML_BYTES = 4_000_000
MAXIMUM_EXTRACTED_SECTION_CHARACTERS = 20_000
MINIMUM_EXTRACTED_SECTION_CHARACTERS = 80


class FilingChangeExtractionError(ValueError):
    """The source cannot safely produce a Phase 42 section package."""


class FilingChangeExtraction(ContractModel):
    filing_form: FilingChangeForm
    source_content_sha256: Sha256Hex
    normalized_visible_sha256: Sha256Hex
    normalized_visible_characters: int = Field(gt=0, le=50_000_000)
    sections: tuple[FilingChangeSection, ...] = Field(max_length=64)
    extraction_version: Literal["filing-change-sections-v1"] = FILING_CHANGE_EXTRACTION_VERSION

    @model_validator(mode="after")
    def sections_reconcile(self) -> Self:
        selectors = tuple(item.selector for item in self.sections)
        if selectors != tuple(sorted(set(selectors))):
            raise ValueError("extracted filing-change selectors must be canonical and unique")
        if any(item.normalized_end > self.normalized_visible_characters for item in self.sections):
            raise ValueError("extracted filing-change section exceeds the visible source")
        return self


@dataclass(frozen=True, slots=True)
class _HeadingRule:
    selector: str
    category: FilingChangeCategory
    heading: str
    pattern: re.Pattern[str]
    periodic_items: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Candidate:
    rule: _HeadingRule
    start: int
    heading_end: int
    uppercase_heading: bool


class _VisibleTextParser(HTMLParser):
    _VOID_TAGS = frozenset(
        {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source"}
    )
    _IGNORED_TAGS = frozenset({"script", "style", "svg", "ix:header"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[tuple[str, bool]] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        folded = tag.casefold()
        attributes = {key.casefold(): value for key, value in attrs}
        style = (attributes.get("style") or "").replace(" ", "").casefold()
        parent_hidden = self._stack[-1][1] if self._stack else False
        hidden = (
            parent_hidden
            or folded in self._IGNORED_TAGS
            or any(
                (
                    "hidden" in attributes,
                    (attributes.get("aria-hidden") or "").casefold() == "true",
                    "display:none" in style,
                    "visibility:hidden" in style,
                )
            )
        )
        if folded not in self._VOID_TAGS:
            self._stack.append((folded, hidden))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        return

    def handle_endtag(self, tag: str) -> None:
        folded = tag.casefold()
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == folded:
                del self._stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if not self._stack or not self._stack[-1][1]:
            self.parts.append(data)


_HEADING_RULES = (
    _HeadingRule(
        "liquidity",
        FilingChangeCategory.LIQUIDITY,
        "Liquidity and capital resources",
        re.compile(r"\b(?:Liquidity and Capital Resources|LIQUIDITY AND CAPITAL RESOURCES)\b"),
    ),
    _HeadingRule(
        "risks",
        FilingChangeCategory.RISKS,
        "Risk factors",
        re.compile(r"\b(?:Risk Factors|RISK FACTORS)\b"),
        ("1A",),
    ),
    _HeadingRule(
        "going-concern",
        FilingChangeCategory.GOING_CONCERN,
        "Going concern",
        re.compile(r"\b(?:Going Concern(?: Assessment)?|GOING CONCERN(?: ASSESSMENT)?)\b"),
    ),
    _HeadingRule(
        "debt.debt",
        FilingChangeCategory.DEBT,
        "Debt",
        re.compile(r"\b(?:Debt(?: Financing)?|DEBT(?: FINANCING)?)\b"),
    ),
    _HeadingRule(
        "debt.credit-facilities",
        FilingChangeCategory.DEBT,
        "Credit facilities",
        re.compile(r"\b(?:Credit Facilities|CREDIT FACILITIES)\b"),
    ),
    _HeadingRule(
        "debt.borrowings",
        FilingChangeCategory.DEBT,
        "Borrowings",
        re.compile(r"\b(?:Borrowings|BORROWINGS)\b"),
    ),
    _HeadingRule(
        "issuance.use-of-proceeds",
        FilingChangeCategory.ISSUANCE,
        "Use of proceeds",
        re.compile(r"\b(?:Use of Proceeds|USE OF PROCEEDS)\b"),
    ),
    _HeadingRule(
        "issuance.dilution",
        FilingChangeCategory.ISSUANCE,
        "Dilution",
        re.compile(r"\b(?:Dilution|DILUTION)\b"),
    ),
    _HeadingRule(
        "issuance.securities",
        FilingChangeCategory.ISSUANCE,
        "Description of securities",
        re.compile(
            r"\b(?:Description of (?:Capital Stock|Securities)|"
            r"DESCRIPTION OF (?:CAPITAL STOCK|SECURITIES))\b"
        ),
    ),
    _HeadingRule(
        "issuance.unregistered-sales",
        FilingChangeCategory.ISSUANCE,
        "Recent sales of unregistered securities",
        re.compile(
            r"\b(?:Recent Sales of Unregistered (?:Equity )?Securities|"
            r"RECENT SALES OF UNREGISTERED (?:EQUITY )?SECURITIES)\b"
        ),
    ),
    _HeadingRule(
        "litigation",
        FilingChangeCategory.LITIGATION,
        "Legal proceedings",
        re.compile(r"\b(?:Legal Proceedings|LEGAL PROCEEDINGS)\b"),
        ("1", "3"),
    ),
    _HeadingRule(
        "controls.procedures",
        FilingChangeCategory.CONTROLS,
        "Controls and procedures",
        re.compile(r"\b(?:Controls and Procedures|CONTROLS AND PROCEDURES)\b"),
        ("4", "9A"),
    ),
    _HeadingRule(
        "controls.internal-control",
        FilingChangeCategory.CONTROLS,
        "Internal control over financial reporting",
        re.compile(
            r"\b(?:Internal Control over Financial Reporting|"
            r"INTERNAL CONTROL OVER FINANCIAL REPORTING)\b"
        ),
    ),
    _HeadingRule(
        "outlook",
        FilingChangeCategory.OUTLOOK,
        "Outlook",
        re.compile(
            r"\b(?:Outlook|OUTLOOK|Business Outlook|BUSINESS OUTLOOK|"
            r"Known Trends and Uncertainties|KNOWN TRENDS AND UNCERTAINTIES)\b"
        ),
    ),
)
_PERIODIC_FORMS = {
    FilingChangeForm.FORM_10_K,
    FilingChangeForm.FORM_10_K_AMENDMENT,
    FilingChangeForm.FORM_10_Q,
    FilingChangeForm.FORM_10_Q_AMENDMENT,
}
_GENERIC_BOUNDARY_RE = re.compile(
    r"\b(?:ITEM|Item)\s+\d{1,2}[A-C]?\.?\s+[A-Z]|"
    r"\bSIGNATURES\b|"
    r"(?<![\w.])\d{1,2}\.\s+[A-Z][A-Za-z][A-Za-z &’'\-/]{2,80}"
)


def extract_filing_change_sections(
    body: bytes, *, filing_form: FilingChangeForm
) -> FilingChangeExtraction:
    """Extract the first substantive section for each closed canonical heading selector."""

    if not body:
        raise FilingChangeExtractionError("filing-change source is empty")
    if len(body) > MAXIMUM_FILING_CHANGE_HTML_BYTES:
        raise FilingChangeExtractionError("filing-change source exceeds the parser boundary")
    visible = _normalized_visible_text(body)
    if not visible:
        raise FilingChangeExtractionError("filing-change source has no visible text")
    candidates = _heading_candidates(visible, filing_form)
    all_boundaries = sorted(
        {
            *(item.start for item in candidates),
            *(match.start() for match in _GENERIC_BOUNDARY_RE.finditer(visible)),
            len(visible),
        }
    )
    selected: list[FilingChangeSection] = []
    for rule in _HEADING_RULES:
        rule_sections: list[tuple[FilingChangeSection, bool]] = []
        for candidate in candidates:
            if candidate.rule is not rule:
                continue
            end = next(
                (boundary for boundary in all_boundaries if boundary > candidate.heading_end),
                len(visible),
            )
            end = min(end, candidate.start + MAXIMUM_EXTRACTED_SECTION_CHARACTERS)
            start, end = _trim_range(visible, candidate.start, end)
            if end - start < MINIMUM_EXTRACTED_SECTION_CHARACTERS:
                continue
            text = visible[start:end]
            if _looks_like_table_of_contents(text):
                continue
            rule_sections.append(
                (
                    build_filing_change_section(
                        selector=rule.selector,
                        heading=rule.heading,
                        category=rule.category,
                        text=text,
                        normalized_start=start,
                    ),
                    candidate.uppercase_heading,
                )
            )
        if rule_sections:
            preferred = rule_sections
            if filing_form not in _PERIODIC_FORMS and any(item[1] for item in rule_sections):
                preferred = [item for item in rule_sections if item[1]]
            selected.append(
                min(
                    preferred,
                    key=lambda item: (item[0].normalized_start, -len(item[0].text)),
                )[0]
            )
    return FilingChangeExtraction(
        filing_form=filing_form,
        source_content_sha256=sha256(body).hexdigest(),
        normalized_visible_sha256=sha256(visible.encode()).hexdigest(),
        normalized_visible_characters=len(visible),
        sections=tuple(sorted(selected, key=lambda item: item.selector)),
    )


def normalized_filing_change_visible_text(body: bytes) -> str:
    """Expose the exact normalized corpus used by section offsets and tests."""

    return _normalized_visible_text(body)


def build_snapshot_from_filing_change_extraction(
    extraction: FilingChangeExtraction,
    *,
    accession_number: str,
    cik: str,
    filed_at: UtcDatetime,
    available_at: UtcDatetime,
    retrieved_at: UtcDatetime,
    source_url: str,
) -> FilingChangeSnapshot:
    """Bind a validated extraction directly to one authoritative SEC snapshot."""

    if not extraction.sections:
        raise FilingChangeExtractionError("filing-change extraction has no supported sections")
    return build_filing_change_snapshot(
        accession_number=accession_number,
        cik=cik,
        filing_form=extraction.filing_form,
        filed_at=filed_at,
        available_at=available_at,
        retrieved_at=retrieved_at,
        source_url=source_url,
        source_content_sha256=extraction.source_content_sha256,
        normalized_visible_sha256=extraction.normalized_visible_sha256,
        sections=extraction.sections,
    )


def build_amendment_manifest_from_filing_change_snapshot(
    snapshot: FilingChangeSnapshot,
    *,
    event_novelty_ruleset_version: Literal["event-novelty-v1"] = EVENT_NOVELTY_RULE_VERSION,
    evidence_budget_version: Literal["1.0.0"] = EVIDENCE_BUDGET_VERSION,
) -> AmendmentEvidenceManifest:
    """Project exact Phase 42 section identities into the conservative delta gate."""

    return build_amendment_manifest(
        accession_number=snapshot.accession_number,
        cik=snapshot.cik,
        filing_form=snapshot.filing_form.value,
        source_content_sha256=snapshot.source_content_sha256,
        available_at=snapshot.available_at,
        retrieved_at=snapshot.retrieved_at,
        sections=tuple(
            AmendmentSectionFingerprint(
                selector=section.selector,
                evidence_sha256=section.text_sha256,
                evidence_characters=len(section.text),
            )
            for section in snapshot.sections
        ),
        event_novelty_ruleset_version=event_novelty_ruleset_version,
        evidence_budget_version=evidence_budget_version,
        extraction_ruleset_version=snapshot.extraction_version,
    )


def _normalized_visible_text(body: bytes) -> str:
    parser = _VisibleTextParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    parser.close()
    return " ".join(" ".join(parser.parts).replace("\x00", " ").split())


def _heading_candidates(text: str, filing_form: FilingChangeForm) -> tuple[_Candidate, ...]:
    periodic = filing_form in _PERIODIC_FORMS
    candidates: list[_Candidate] = []
    for rule in _HEADING_RULES:
        for match in rule.pattern.finditer(text):
            if (
                periodic
                and rule.periodic_items
                and not _has_periodic_item_context(text, match.start(), rule.periodic_items)
            ):
                continue
            heading_text = match.group(0)
            candidates.append(
                _Candidate(
                    rule,
                    match.start(),
                    match.end(),
                    heading_text.upper() == heading_text,
                )
            )
    return tuple(sorted(candidates, key=lambda item: (item.start, item.rule.selector)))


def _has_periodic_item_context(text: str, start: int, item_numbers: tuple[str, ...]) -> bool:
    prefix = text[max(0, start - 48) : start]
    item_pattern = "|".join(re.escape(item) for item in item_numbers)
    return re.search(rf"(?:ITEM|Item)\s+(?:{item_pattern})\.?\s*$", prefix) is not None


def _trim_range(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _looks_like_table_of_contents(text: str) -> bool:
    sample = text[:600]
    item_references = len(re.findall(r"\b(?:ITEM|Item)\s+\d", sample))
    page_references = len(re.findall(r"\b\d{1,3}\s+(?:ITEM|Item|PART|Part)\b", sample))
    prospectus_page_references = len(re.findall(r"\b(?:S-|F-)?\d{1,3}\b", sample))
    uppercase_headings = len(re.findall(r"\b[A-Z][A-Z &’'\-/]{4,}\b", sample))
    return (
        item_references >= 3
        or page_references >= 2
        or (prospectus_page_references >= 3 and uppercase_headings >= 2)
    )
