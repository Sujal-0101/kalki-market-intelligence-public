"""Closed, deterministic form-aware evidence selection before local inference."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from html.parser import HTMLParser
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator

from kalki_market_intelligence.contracts.common import ContractModel, Sha256Hex

EVIDENCE_BUDGET_VERSION: Literal["1.0.0"] = "1.0.0"
WINDOW_CHARACTERS = 560
MAXIMUM_WINDOWS = 6
MAXIMUM_EVIDENCE_CHARACTERS = 3_600
BoundedSectionLabel = Annotated[str, Field(min_length=1, max_length=255)]
BoundedMaterialTerm = Annotated[str, Field(min_length=1, max_length=64)]


class EvidenceFormFamily(StrEnum):
    CURRENT_REPORT = "current_report"
    PERIODIC_REPORT = "periodic_report"
    FALLBACK = "fallback"


class EvidenceSectionKind(StrEnum):
    MATERIAL_AGREEMENT = "material_agreement"
    FINANCING = "financing"
    FINANCIAL_RESULTS = "financial_results"
    LIQUIDITY_AND_MD_AND_A = "liquidity_and_md_and_a"
    RISK_FACTORS = "risk_factors"
    GOING_CONCERN = "going_concern"
    ACCOUNTING_AND_AUDITOR = "accounting_and_auditor"
    CONTROLS = "controls"
    MANAGEMENT = "management"
    LISTING_AND_REGULATORY = "listing_and_regulatory"
    LEGAL = "legal"
    OTHER_MATERIAL = "other_material"
    FALLBACK_KEYWORD = "fallback_keyword"


class EvidenceSelectionReason(StrEnum):
    MATERIAL_TERM = "material_term"
    CHANGED_SECTION = "changed_section"
    RELEVANT_SECTION = "relevant_section"
    FALLBACK_KEYWORD = "fallback_keyword"


class EvidenceBudgetWindow(ContractModel):
    """One exact range in normalized visible source text."""

    evidence_id: UUID
    section_label: str = Field(min_length=1, max_length=255)
    section_kind: EvidenceSectionKind
    reason: EvidenceSelectionReason
    item_number: str | None = Field(default=None, pattern=r"^\d\.\d{2}$")
    normalized_start: int = Field(ge=0, le=50_000_000)
    normalized_end: int = Field(gt=0, le=50_000_000)
    text_sha256: Sha256Hex
    text_characters: int = Field(gt=0, le=WINDOW_CHARACTERS)

    @model_validator(mode="after")
    def range_matches_size(self) -> EvidenceBudgetWindow:
        if self.normalized_end <= self.normalized_start:
            raise ValueError("evidence window end must follow its start")
        if self.normalized_end - self.normalized_start != self.text_characters:
            raise ValueError("evidence window range must match its text size")
        return self


class EvidenceBudgetReceipt(ContractModel):
    """Content-free selection lineage and size measurements."""

    filing_form: str = Field(min_length=1, max_length=32)
    form_family: EvidenceFormFamily
    selected_document_type: str | None = Field(default=None, min_length=1, max_length=32)
    selected_document_types: tuple[str, ...] = Field(default=(), max_length=64)
    source_content_sha256: Sha256Hex
    normalized_visible_sha256: Sha256Hex
    baseline_excerpt_sha256: Sha256Hex
    selected_excerpt_sha256: Sha256Hex
    baseline_characters: int = Field(ge=0, le=MAXIMUM_EVIDENCE_CHARACTERS)
    selected_characters: int = Field(ge=0, le=MAXIMUM_EVIDENCE_CHARACTERS)
    baseline_estimated_tokens: int = Field(ge=0, le=100_000)
    selected_estimated_tokens: int = Field(ge=0, le=100_000)
    actual_prompt_tokens: int | None = Field(default=None, ge=0, le=1_000_000)
    changed_section_names: tuple[BoundedSectionLabel, ...] = Field(default=(), max_length=64)
    required_baseline_terms: tuple[BoundedMaterialTerm, ...] = Field(default=(), max_length=32)
    retained_baseline_terms: tuple[BoundedMaterialTerm, ...] = Field(default=(), max_length=32)
    post_filter_excerpt_sha256: Sha256Hex | None = None
    post_filter_characters: int | None = Field(default=None, ge=0, le=MAXIMUM_EVIDENCE_CHARACTERS)
    post_filter_estimated_tokens: int | None = Field(default=None, ge=0, le=100_000)
    excluded_event_quote_sha256s: tuple[Sha256Hex, ...] = Field(default=(), max_length=16)
    selected_windows: tuple[EvidenceBudgetWindow, ...] = Field(max_length=MAXIMUM_WINDOWS)
    budget_version: Literal["1.0.0"] = EVIDENCE_BUDGET_VERSION

    @model_validator(mode="after")
    def selected_hash_and_windows_are_consistent(self) -> EvidenceBudgetReceipt:
        if self.form_family is EvidenceFormFamily.FALLBACK and self.selected_windows:
            raise ValueError("fallback evidence cannot claim form-aware windows")
        if self.form_family is not EvidenceFormFamily.FALLBACK and bool(
            self.selected_characters
        ) != bool(self.selected_windows):
            raise ValueError("selected characters and windows must be present together")
        if self.baseline_estimated_tokens != _estimated_tokens_for_size(
            self.baseline_characters
        ) or self.selected_estimated_tokens != _estimated_tokens_for_size(self.selected_characters):
            raise ValueError("estimated token counts must reconcile to character counts")
        if self.selected_windows:
            expected_characters = sum(item.text_characters for item in self.selected_windows)
            expected_characters += 7 * (len(self.selected_windows) - 1)
            if self.selected_characters != expected_characters:
                raise ValueError("selected characters must reconcile to exact windows")
            if any(
                current.normalized_start < previous.normalized_end
                for previous, current in zip(
                    self.selected_windows, self.selected_windows[1:], strict=False
                )
            ):
                raise ValueError("selected windows must be ordered and non-overlapping")
        if not set(self.retained_baseline_terms).issubset(self.required_baseline_terms):
            raise ValueError("retained baseline terms must come from the required closed set")
        post_filter_values = (
            self.post_filter_excerpt_sha256,
            self.post_filter_characters,
            self.post_filter_estimated_tokens,
        )
        if any(item is not None for item in post_filter_values) != all(
            item is not None for item in post_filter_values
        ):
            raise ValueError("post-selection filter measurements must be present together")
        if bool(self.excluded_event_quote_sha256s) != all(
            item is not None for item in post_filter_values
        ):
            raise ValueError("post-selection filter measurements require excluded quote hashes")
        if (
            self.post_filter_characters is not None
            and self.post_filter_estimated_tokens
            != _estimated_tokens_for_size(self.post_filter_characters)
        ):
            raise ValueError("post-filter token estimate must reconcile to characters")
        return self


@dataclass(frozen=True, slots=True)
class FormAwareEvidence:
    """Selected exact evidence plus its content-free deterministic receipt."""

    text: str
    receipt: EvidenceBudgetReceipt


@dataclass(frozen=True, slots=True)
class _Section:
    start: int
    end: int
    label: str
    kind: EvidenceSectionKind
    priority: int
    item_number: str | None = None


@dataclass(frozen=True, slots=True)
class _Window:
    start: int
    end: int
    section: _Section
    reason: EvidenceSelectionReason
    hit_priority: int
    boilerplate_penalty: int = 0


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style", "svg", "ix:header"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "svg", "ix:header"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)


_CURRENT_ITEM_KINDS: dict[str, tuple[EvidenceSectionKind, int]] = {
    "1.01": (EvidenceSectionKind.MATERIAL_AGREEMENT, 0),
    "1.02": (EvidenceSectionKind.MATERIAL_AGREEMENT, 0),
    "2.01": (EvidenceSectionKind.MATERIAL_AGREEMENT, 0),
    "2.02": (EvidenceSectionKind.FINANCIAL_RESULTS, 1),
    "2.03": (EvidenceSectionKind.FINANCING, 0),
    "2.04": (EvidenceSectionKind.FINANCING, 0),
    "2.05": (EvidenceSectionKind.MANAGEMENT, 1),
    "3.01": (EvidenceSectionKind.LISTING_AND_REGULATORY, 0),
    "3.02": (EvidenceSectionKind.FINANCING, 0),
    "3.03": (EvidenceSectionKind.FINANCING, 1),
    "4.01": (EvidenceSectionKind.ACCOUNTING_AND_AUDITOR, 0),
    "4.02": (EvidenceSectionKind.ACCOUNTING_AND_AUDITOR, 0),
    "5.02": (EvidenceSectionKind.MANAGEMENT, 0),
    "5.03": (EvidenceSectionKind.OTHER_MATERIAL, 2),
    "5.07": (EvidenceSectionKind.OTHER_MATERIAL, 2),
    "7.01": (EvidenceSectionKind.OTHER_MATERIAL, 3),
    "8.01": (EvidenceSectionKind.OTHER_MATERIAL, 2),
    "9.01": (EvidenceSectionKind.FINANCIAL_RESULTS, 4),
}
_CURRENT_ITEM_RE = re.compile(r"\bITEM\s+(\d\.\d{2})\b", re.IGNORECASE)
_PERIODIC_ITEM_BOUNDARY_RE = re.compile(
    r"\bITEM\s+(?:\d{1,2}[A-C]?)\.?\s+|\bSIGNATURES\b", re.IGNORECASE
)
_PERIODIC_SECTION_RE = re.compile(
    r"\bITEM\s+(?:\d{1,2}[A-C]?)\.?\s+(?P<label>"
    r"management(?:['’]s|s)? discussion and analysis|risk factors|"
    r"controls and procedures|financial statements and supplementary data|"
    r"financial statements|legal proceedings|defaults upon senior securities|"
    r"unregistered sales of equity securities)\b",
    re.IGNORECASE,
)

_PERIODIC_HEADINGS: tuple[tuple[re.Pattern[str], EvidenceSectionKind, int, str], ...] = (
    (
        re.compile(r"\bmanagement(?:['’]s|s)? discussion and analysis\b", re.IGNORECASE),
        EvidenceSectionKind.LIQUIDITY_AND_MD_AND_A,
        0,
        "Management discussion and analysis",
    ),
    (
        re.compile(r"\brisk factors\b", re.IGNORECASE),
        EvidenceSectionKind.RISK_FACTORS,
        0,
        "Risk factors",
    ),
    (
        re.compile(r"\bcontrols and procedures\b", re.IGNORECASE),
        EvidenceSectionKind.CONTROLS,
        0,
        "Controls and procedures",
    ),
    (
        re.compile(r"\bfinancial statements and supplementary data\b", re.IGNORECASE),
        EvidenceSectionKind.FINANCIAL_RESULTS,
        2,
        "Financial statements and supplementary data",
    ),
    (
        re.compile(r"\bfinancial statements\b", re.IGNORECASE),
        EvidenceSectionKind.FINANCIAL_RESULTS,
        3,
        "Financial statements",
    ),
    (
        re.compile(r"\blegal proceedings\b", re.IGNORECASE),
        EvidenceSectionKind.LEGAL,
        1,
        "Legal proceedings",
    ),
    (
        re.compile(r"\bdefaults upon senior securities\b", re.IGNORECASE),
        EvidenceSectionKind.FINANCING,
        0,
        "Defaults upon senior securities",
    ),
    (
        re.compile(r"\bunregistered sales of equity securities\b", re.IGNORECASE),
        EvidenceSectionKind.FINANCING,
        1,
        "Unregistered sales of equity securities",
    ),
)

_MATERIAL_PATTERNS: tuple[tuple[re.Pattern[str], EvidenceSectionKind, int], ...] = (
    (
        re.compile(r"\bgoing concern\b|\bsubstantial doubt\b", re.IGNORECASE),
        EvidenceSectionKind.GOING_CONCERN,
        0,
    ),
    (
        re.compile(
            r"\b(?:independent registered public accounting firm|auditor|accountant)\b"
            r"|\bnon-reliance\b|\brestatement\b",
            re.IGNORECASE,
        ),
        EvidenceSectionKind.ACCOUNTING_AND_AUDITOR,
        0,
    ),
    (
        re.compile(
            r"\bmaterial weakness\b|"
            r"\b(?:disclosure controls(?: and procedures)?|internal control(?: over financial "
            r"reporting)?)\b.{0,220}\b(?:are|were|is|was) (?:in)?effective\b",
            re.IGNORECASE,
        ),
        EvidenceSectionKind.CONTROLS,
        0,
    ),
    (
        re.compile(r"\bdisclosure controls\b|\binternal control\b", re.IGNORECASE),
        EvidenceSectionKind.CONTROLS,
        1,
    ),
    (
        re.compile(
            r"\b(?:delist(?:ing|ed)?|listing deficiency|noncompliance|subpoena|"
            r"investigation|regulatory)\b",
            re.IGNORECASE,
        ),
        EvidenceSectionKind.LISTING_AND_REGULATORY,
        0,
    ),
    (
        re.compile(
            r"\b(?:appointed|resigned|terminated|chief executive officer|"
            r"chief financial officer|director)\b",
            re.IGNORECASE,
        ),
        EvidenceSectionKind.MANAGEMENT,
        1,
    ),
    (
        re.compile(
            r"\b(?:agreement|contract|award|partnership|acquisition|disposition|merger)\b",
            re.IGNORECASE,
        ),
        EvidenceSectionKind.MATERIAL_AGREEMENT,
        1,
    ),
    (
        re.compile(
            r"\b(?:offering|shelf|at-the-market|pipe|convertible|preferred|warrant|"
            r"equity line|credit facility|debt|covenant|maturity|default|dilution)\b",
            re.IGNORECASE,
        ),
        EvidenceSectionKind.FINANCING,
        1,
    ),
    (
        re.compile(
            r"\b(?:liquidity|cash flows?|revenue|net loss|impairment|restructuring|bankruptcy)\b",
            re.IGNORECASE,
        ),
        EvidenceSectionKind.LIQUIDITY_AND_MD_AND_A,
        2,
    ),
)

_BOILERPLATE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bforward-looking statements?\b",
        r"\bincorporated(?: herein)? by reference\b",
        r"\bexhibit index\b",
        r"\bpursuant to the requirements of the securities exchange act\b",
    )
)

_REPEATED_BOILERPLATE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bforward-looking statements?\b",
        r"\bincorporated(?: herein)? by reference\b",
        r"\bexhibit index\b",
        r"\bpursuant to the requirements of the securities exchange act\b",
        r"\bi have disclosed, based on our most recent evaluation\b",
        r"\bwhether (?:any|the) .*financial statements?.*(?:error corrections?|restatements?)\b",
        r"\bexpected\b(?:.{0,1800}\bexpected\b){2}",
        r"\bloss per common share\b.*\bno dilution\b.*\bpotential dilution\b",
    )
)


def normalized_visible_text(body: bytes) -> str:
    """Return deterministic visible text used by all receipt offsets."""

    decoded = body.decode("utf-8", errors="replace")
    parser = _VisibleTextParser()
    parser.feed(decoded)
    visible = " ".join(parser.parts) if parser.parts else decoded
    return " ".join(visible.replace("\x00", " ").split())


def select_form_aware_evidence(
    body: bytes,
    *,
    filing_form: str,
    baseline_text: str,
    changed_section_names: tuple[str, ...] = (),
    required_baseline_terms: tuple[str, ...] = (),
) -> FormAwareEvidence:
    """Select bounded exact windows for 8-K and 10-K/Q; otherwise retain baseline."""

    selected_body, selected_document_type, selected_document_types = _select_form_documents(
        body, filing_form
    )
    normalized = normalized_visible_text(selected_body)
    source_hash = sha256(body).hexdigest()
    normalized_hash = sha256(normalized.encode()).hexdigest()
    baseline_hash = sha256(baseline_text.encode()).hexdigest()
    family = _form_family(filing_form)
    sections = _sections(normalized, family)
    windows = (
        ()
        if family is EvidenceFormFamily.FALLBACK
        else (
            *_required_term_windows(normalized, sections, required_baseline_terms),
            *_candidate_windows(normalized, sections, changed_section_names),
        )
    )
    selected = _select_windows(normalized, windows)
    if not selected:
        text = baseline_text
        receipt_windows: tuple[EvidenceBudgetWindow, ...] = ()
        family = EvidenceFormFamily.FALLBACK
    else:
        text = "\n\n[…]\n\n".join(normalized[item.start : item.end] for item in selected)
        text = text[:MAXIMUM_EVIDENCE_CHARACTERS].strip()
        receipt_windows = tuple(_receipt_window(source_hash, normalized, item) for item in selected)
    receipt = EvidenceBudgetReceipt(
        filing_form=filing_form,
        form_family=family,
        selected_document_type=selected_document_type,
        selected_document_types=selected_document_types,
        source_content_sha256=source_hash,
        normalized_visible_sha256=normalized_hash,
        baseline_excerpt_sha256=baseline_hash,
        selected_excerpt_sha256=sha256(text.encode()).hexdigest(),
        baseline_characters=len(baseline_text),
        selected_characters=len(text),
        baseline_estimated_tokens=_estimated_tokens(baseline_text),
        selected_estimated_tokens=_estimated_tokens(text),
        changed_section_names=tuple(dict.fromkeys(changed_section_names)),
        required_baseline_terms=tuple(dict.fromkeys(required_baseline_terms)),
        retained_baseline_terms=tuple(
            term
            for term in dict.fromkeys(required_baseline_terms)
            if term.casefold() in text.casefold()
        ),
        selected_windows=receipt_windows,
    )
    return FormAwareEvidence(text=text, receipt=receipt)


def _form_family(filing_form: str) -> EvidenceFormFamily:
    normalized = filing_form.upper().removesuffix("/A")
    if normalized == "8-K":
        return EvidenceFormFamily.CURRENT_REPORT
    if normalized in {"10-Q", "10-K"}:
        return EvidenceFormFamily.PERIODIC_REPORT
    return EvidenceFormFamily.FALLBACK


_SUBMISSION_DOCUMENT_RE = re.compile(rb"<DOCUMENT>(.*?)</DOCUMENT>", re.IGNORECASE | re.DOTALL)
_SUBMISSION_TYPE_RE = re.compile(rb"<TYPE>\s*([^\r\n<]+)", re.IGNORECASE)
_SUBMISSION_TEXT_RE = re.compile(rb"<TEXT>(.*)</TEXT>", re.IGNORECASE | re.DOTALL)


def _select_form_documents(
    body: bytes, filing_form: str
) -> tuple[bytes, str | None, tuple[str, ...]]:
    """Select the exact form plus bounded authoritative 8-K exhibits."""

    expected = filing_form.upper().strip()
    family = _form_family(filing_form)
    selected: list[bytes] = []
    selected_types: list[str] = []
    primary_type: str | None = None
    for document_match in _SUBMISSION_DOCUMENT_RE.finditer(body):
        document = document_match.group(1)
        type_match = _SUBMISSION_TYPE_RE.search(document)
        if type_match is None:
            continue
        document_type = type_match.group(1).decode("ascii", errors="ignore").strip().upper()
        is_primary = document_type == expected
        is_current_report_exhibit = family is EvidenceFormFamily.CURRENT_REPORT and (
            document_type.startswith("EX-99") or document_type.startswith("EX-10")
        )
        if not is_primary and not is_current_report_exhibit:
            continue
        text_match = _SUBMISSION_TEXT_RE.search(document)
        selected.append(text_match.group(1) if text_match is not None else document)
        selected_types.append(document_type)
        if is_primary:
            primary_type = document_type
    if primary_type is None:
        return body, None, ()
    primary_index = selected_types.index(primary_type)
    # Put exhibits before the primary form in the derived corpus. That makes the
    # final 8-K item boundary stop at the form's own end rather than absorbing an
    # unrelated exhibit; required baseline terms may still reserve exact exhibit text.
    ordered_bodies = tuple(
        item for index, item in enumerate(selected) if index != primary_index
    ) + (selected[primary_index],)
    ordered_types = tuple(
        item for index, item in enumerate(selected_types) if index != primary_index
    ) + (primary_type,)
    return b"\n".join(ordered_bodies), primary_type, ordered_types


def _sections(text: str, family: EvidenceFormFamily) -> tuple[_Section, ...]:
    if family is EvidenceFormFamily.CURRENT_REPORT:
        matches = tuple(_CURRENT_ITEM_RE.finditer(text))
        current_sections: list[_Section] = []
        for index, match in enumerate(matches):
            item_number = match.group(1)
            current_config = _CURRENT_ITEM_KINDS.get(item_number)
            if current_config is None:
                continue
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            kind, priority = current_config
            current_sections.append(
                _Section(match.start(), end, f"8-K Item {item_number}", kind, priority, item_number)
            )
        return tuple(current_sections)
    if family is EvidenceFormFamily.PERIODIC_REPORT:
        explicit_matches = tuple(_PERIODIC_SECTION_RE.finditer(text))
        if explicit_matches:
            periodic_sections: list[_Section] = []
            item_boundaries = tuple(_PERIODIC_ITEM_BOUNDARY_RE.finditer(text))
            for match in explicit_matches:
                label_text = match.group("label")
                periodic_config = next(
                    (
                        (kind, priority, label)
                        for pattern, kind, priority, label in _PERIODIC_HEADINGS
                        if pattern.fullmatch(label_text) is not None
                    ),
                    None,
                )
                if periodic_config is None:
                    continue
                following = next(
                    (
                        boundary.start()
                        for boundary in item_boundaries
                        if boundary.start() > match.start()
                    ),
                    len(text),
                )
                signature = re.search(r"\bSIGNATURES\b", text[match.end() : following], re.I)
                end = match.end() + signature.start() if signature is not None else following
                kind, priority, label = periodic_config
                periodic_sections.append(_Section(match.start(), end, label, kind, priority))
            return tuple(periodic_sections)
        found: list[tuple[int, EvidenceSectionKind, int, str]] = []
        for pattern, kind, priority, label in _PERIODIC_HEADINGS:
            found.extend((match.start(), kind, priority, label) for match in pattern.finditer(text))
        found.sort(key=lambda item: (item[0], item[2], item[3]))
        found_by_start: dict[int, tuple[int, EvidenceSectionKind, int, str]] = {}
        for item in found:
            found_by_start.setdefault(item[0], item)
        found = list(found_by_start.values())
        boundaries = sorted(
            {
                *(item[0] for item in found),
                *(match.start() for match in _PERIODIC_ITEM_BOUNDARY_RE.finditer(text)),
                len(text),
            }
        )
        # Repeated table-of-contents headings are retained as separate candidates;
        # material-language scoring below naturally deprioritizes empty references.
        return tuple(
            _Section(
                start,
                next(boundary for boundary in boundaries if boundary > start),
                label,
                kind,
                priority,
            )
            for start, kind, priority, label in found
        )
    return ()


def _candidate_windows(
    text: str,
    sections: tuple[_Section, ...],
    changed_section_names: tuple[str, ...],
) -> tuple[_Window, ...]:
    changed = {" ".join(item.casefold().split()) for item in changed_section_names}
    candidates: list[_Window] = []
    for section in sections:
        section_text = text[section.start : section.end]
        if section.item_number is None and _looks_like_table_of_contents(section_text):
            continue
        material_hits: list[tuple[int, int, EvidenceSectionKind]] = []
        for pattern, kind, hit_priority in _MATERIAL_PATTERNS:
            material_hits.extend(
                (section.start + match.start(), hit_priority, kind)
                for match in pattern.finditer(section_text)
            )
        for position, hit_priority, kind in material_hits:
            enriched = _Section(
                section.start,
                section.end,
                section.label,
                kind if hit_priority == 0 else section.kind,
                section.priority,
                section.item_number,
            )
            start, end = _material_sentence_window(text, position, section.start, section.end)
            candidate_text = text[start:end]
            if _looks_like_table_of_contents(candidate_text):
                continue
            if _low_information_section_penalty(candidate_text):
                continue
            boilerplate_penalty = _boilerplate_penalty(candidate_text)
            candidates.append(
                _Window(
                    start,
                    end,
                    enriched,
                    EvidenceSelectionReason.MATERIAL_TERM,
                    hit_priority,
                    boilerplate_penalty,
                )
            )
        section_changed = any(name in section.label.casefold() for name in changed)
        if section_changed:
            start, end = _whole_word_window(text, section.start, section.start, section.end)
            candidates.append(
                _Window(start, end, section, EvidenceSelectionReason.CHANGED_SECTION, 0)
            )
        if not material_hits and not _is_boilerplate_only(section_text):
            start, end = _whole_word_window(text, section.start, section.start, section.end)
            if _low_information_section_penalty(text[start:end]):
                continue
            candidates.append(
                _Window(
                    start,
                    end,
                    section,
                    EvidenceSelectionReason.RELEVANT_SECTION,
                    4,
                )
            )
    return tuple(candidates)


def _required_term_windows(
    text: str,
    sections: tuple[_Section, ...],
    required_terms: tuple[str, ...],
) -> tuple[_Window, ...]:
    """Reserve accepted-baseline terms when they occur in the selected form document."""

    candidates: list[_Window] = []
    for term in dict.fromkeys(required_terms):
        for match in re.finditer(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE):
            position = match.start()
            containing = next(
                (section for section in sections if section.start <= position < section.end),
                None,
            )
            base_section = containing or _Section(
                0,
                len(text),
                f"Retained baseline term: {term}",
                EvidenceSectionKind.FALLBACK_KEYWORD,
                0,
            )
            matched_kind = next(
                (
                    kind
                    for pattern, kind, _ in _MATERIAL_PATTERNS
                    if pattern.search(term) is not None
                ),
                base_section.kind,
            )
            section = _Section(
                start=base_section.start,
                end=base_section.end,
                label=base_section.label,
                kind=matched_kind,
                priority=base_section.priority,
                item_number=base_section.item_number,
            )
            start, end = _material_sentence_window(text, position, section.start, section.end)
            selected_text = text[start:end]
            if _looks_like_table_of_contents(selected_text):
                continue
            if _low_information_section_penalty(selected_text):
                continue
            candidates.append(
                _Window(
                    start,
                    end,
                    section,
                    EvidenceSelectionReason.FALLBACK_KEYWORD,
                    0,
                    _boilerplate_penalty(selected_text),
                )
            )
    return tuple(candidates)


def _select_windows(text: str, candidates: tuple[_Window, ...]) -> tuple[_Window, ...]:
    selected: list[_Window] = []
    used_characters = 0
    substantive_candidates = tuple(item for item in candidates if item.boilerplate_penalty == 0)
    ranked = sorted(
        substantive_candidates or candidates,
        key=lambda item: (
            item.boilerplate_penalty,
            item.hit_priority,
            item.section.priority,
            item.reason is EvidenceSelectionReason.RELEVANT_SECTION,
            item.start,
        ),
    )
    best_per_section: dict[str, _Window] = {}
    for item in ranked:
        diversity_key = item.section.item_number or (
            item.section.label
            if item.section.kind is EvidenceSectionKind.FALLBACK_KEYWORD
            else item.section.kind.value
        )
        best_per_section.setdefault(diversity_key, item)
    diverse = sorted(
        (item for item in best_per_section.values() if item.boilerplate_penalty == 0),
        key=lambda item: (
            item.boilerplate_penalty,
            item.hit_priority,
            item.section.priority,
            item.start,
        ),
    )
    diverse_ids = {id(item) for item in diverse}
    ordered = (*diverse, *(item for item in ranked if id(item) not in diverse_ids))
    for item in ordered:
        if item.reason is EvidenceSelectionReason.FALLBACK_KEYWORD and any(
            present.reason is EvidenceSelectionReason.FALLBACK_KEYWORD
            and present.section.label == item.section.label
            for present in selected
        ):
            continue
        if any(item.start < present.end and item.end > present.start for present in selected):
            continue
        separator = 7 if selected else 0
        available = MAXIMUM_EVIDENCE_CHARACTERS - used_characters - separator
        if available <= 0:
            break
        end = min(item.end, item.start + available)
        if end <= item.start:
            continue
        if end < item.end:
            boundary = text.rfind(" ", item.start, end)
            if boundary > item.start:
                end = boundary
        start = item.start
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        selected.append(
            _Window(
                start,
                end,
                item.section,
                item.reason,
                item.hit_priority,
                item.boilerplate_penalty,
            )
        )
        used_characters += end - start + separator
        if len(selected) >= MAXIMUM_WINDOWS:
            break
    return tuple(sorted(selected, key=lambda item: item.start))


def _whole_word_window(text: str, position: int, lower: int, upper: int) -> tuple[int, int]:
    rough_start = max(lower, position - WINDOW_CHARACTERS // 2)
    rough_end = min(upper, position + WINDOW_CHARACTERS // 2)
    start = rough_start
    end = rough_end
    if rough_start > lower:
        boundary = text.find(" ", rough_start, position)
        if boundary >= 0:
            start = boundary + 1
    if rough_end < upper:
        boundary = text.rfind(" ", position, rough_end)
        if boundary > position:
            end = boundary
    return start, end


def _material_sentence_window(text: str, position: int, lower: int, upper: int) -> tuple[int, int]:
    """Keep the complete material sentence when it fits the accepted fixed window."""

    preceding = max(text.rfind(mark, lower, position) for mark in (". ", "? ", "! "))
    sentence_start = lower if preceding < lower else preceding + 2
    following = [
        found + 1 for mark in (". ", "? ", "! ") if (found := text.find(mark, position, upper)) >= 0
    ]
    sentence_end = min(following) if following else upper
    if sentence_end - sentence_start > WINDOW_CHARACTERS:
        return _whole_word_window(text, position, lower, upper)
    remaining = WINDOW_CHARACTERS - (sentence_end - sentence_start)
    rough_start = max(lower, sentence_start - remaining // 2)
    rough_end = min(upper, sentence_end + remaining - (sentence_start - rough_start))
    start = rough_start
    end = rough_end
    if rough_start > lower:
        boundary = text.find(" ", rough_start, sentence_start)
        if boundary >= 0:
            start = boundary + 1
    if rough_end < upper:
        boundary = text.rfind(" ", sentence_end, rough_end)
        if boundary >= sentence_end:
            end = boundary
    return start, end


def _looks_like_table_of_contents(text: str) -> bool:
    normalized = " ".join(text.split())
    if "$" not in normalized and len(normalized) <= WINDOW_CHARACTERS:
        heading_terms = re.findall(
            r"\b(?:report|statements?|notes?|balance sheets?|operations|cash flows?)\b",
            normalized,
            re.IGNORECASE,
        )
        page_numbers = re.findall(r"(?<![.$])\b\d{1,3}\b(?![.,%])", normalized)
        if len(heading_terms) >= 5 and len(page_numbers) >= 5:
            return True
    if len(normalized) >= 120:
        return False
    cleaned = normalized.casefold().strip(" .")
    for _, _, _, label in _PERIODIC_HEADINGS:
        label_pattern = re.escape(label.casefold())
        if re.fullmatch(
            rf"(?:item\s+\d{{1,2}}[a-c]?\.?\s+)?{label_pattern}"
            rf"(?: and use of proceeds)?(?:\s+\d+)?",
            cleaned,
        ):
            return True
    return not any(mark in normalized for mark in (".", "$", "%"))


def _is_boilerplate_only(text: str) -> bool:
    if not any(pattern.search(text) for pattern in _BOILERPLATE_PATTERNS):
        return False
    return not any(pattern.search(text) for pattern, _, _ in _MATERIAL_PATTERNS)


def _boilerplate_penalty(text: str) -> int:
    """Rank explicit repeated legal/form language after substantive evidence."""

    return 1 if any(pattern.search(text) for pattern in _REPEATED_BOILERPLATE_PATTERNS) else 0


def _low_information_section_penalty(text: str) -> int:
    """Deprioritize explicit empty/no-change sections without deleting them."""

    normalized = " ".join(text.casefold().split())
    if len(normalized) <= 180 and re.search(r"\b(?:not applicable|none)\.?$", normalized):
        return 1
    if re.search(
        r"\b(?:there (?:were|have been)|we identified) no (?:material )?changes\b",
        normalized,
    ):
        return 1
    if re.search(r"\bno response is required\b|\bno material developments?\b", normalized):
        return 1
    if len(normalized) <= 400 and "risk factors" in normalized and "form 10-k" in normalized:
        return 1
    return 0


def _receipt_window(source_hash: str, text: str, window: _Window) -> EvidenceBudgetWindow:
    selected = text[window.start : window.end]
    selected_hash = sha256(selected.encode()).hexdigest()
    return EvidenceBudgetWindow(
        evidence_id=uuid5(
            NAMESPACE_URL,
            f"form-aware-evidence:{source_hash}:{window.start}:{window.end}:{selected_hash}",
        ),
        section_label=window.section.label,
        section_kind=window.section.kind,
        reason=window.reason,
        item_number=window.section.item_number,
        normalized_start=window.start,
        normalized_end=window.end,
        text_sha256=selected_hash,
        text_characters=len(selected),
    )


def _estimated_tokens(text: str) -> int:
    """Return an explicitly heuristic four-characters-per-token estimate."""

    return _estimated_tokens_for_size(len(text))


def _estimated_tokens_for_size(characters: int) -> int:
    return (characters + 3) // 4
