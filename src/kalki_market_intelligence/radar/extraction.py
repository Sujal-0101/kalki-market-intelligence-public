"""Deterministic, bounded extraction of research-relevant SEC filing excerpts."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from html.parser import HTMLParser

from kalki_market_intelligence.radar.evidence_budget import (
    EvidenceBudgetReceipt,
    select_form_aware_evidence,
)

OPPORTUNITY_TERMS = (
    "contract",
    "award",
    "partnership",
    "approval",
    "guidance",
    "record revenue",
    "acquisition",
    "strategic agreement",
    "commercial launch",
    "backlog",
)
RISK_TERMS = (
    "going concern",
    "material weakness",
    "investigation",
    "subpoena",
    "impairment",
    "default",
    "bankruptcy",
    "restructuring",
    "dilution",
    "restatement",
)
WINDOW_CHARACTERS = 560
MAXIMUM_WINDOWS = 6
MAXIMUM_EXCERPT_CHARACTERS = 3_600


@dataclass(frozen=True, slots=True)
class ExtractedFiling:
    text: str
    content_sha256: str
    opportunity_terms: tuple[str, ...]
    risk_terms: tuple[str, ...]
    evidence_budget: EvidenceBudgetReceipt | None = None

    @property
    def is_research_relevant(self) -> bool:
        return bool(self.opportunity_terms or self.risk_terms)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style", "svg", "xbrl", "ix:header"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "svg", "xbrl", "ix:header"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)


def extract_research_excerpt(body: bytes) -> ExtractedFiling:
    """Select keyword-centred windows without letting a model choose its own evidence."""

    decoded = body.decode("utf-8", errors="replace")
    parser = _VisibleTextParser()
    parser.feed(decoded)
    visible = " ".join(parser.parts) if parser.parts else decoded
    normalized = " ".join(visible.replace("\x00", " ").split())
    lowered = normalized.casefold()
    opportunity_hits = tuple(term for term in OPPORTUNITY_TERMS if term in lowered)
    risk_hits = tuple(term for term in RISK_TERMS if term in lowered)
    opportunity_positions = tuple(lowered.find(term) for term in opportunity_hits)
    risk_positions = tuple(lowered.find(term) for term in risk_hits)
    prioritized_positions = _diverse_positions(opportunity_positions, risk_positions)
    selected_windows: list[tuple[int, int, str]] = []
    for position in prioritized_positions:
        start, end = _whole_word_window(normalized, position)
        if any(
            start <= selected_end and end >= selected_start
            for selected_start, selected_end, _ in selected_windows
        ):
            continue
        window = normalized[start:end].strip()
        if window:
            selected_windows.append((start, end, window))
        if len(selected_windows) >= MAXIMUM_WINDOWS:
            break
    windows = [item[2] for item in sorted(selected_windows)]
    excerpt = "\n\n[…]\n\n".join(windows)[:MAXIMUM_EXCERPT_CHARACTERS].strip()
    excerpt_lowered = excerpt.casefold()
    return ExtractedFiling(
        text=excerpt,
        content_sha256=sha256(excerpt.encode("utf-8")).hexdigest(),
        opportunity_terms=tuple(term for term in opportunity_hits if term in excerpt_lowered),
        risk_terms=tuple(term for term in risk_hits if term in excerpt_lowered),
    )


def extract_form_aware_research_excerpt(
    body: bytes,
    *,
    filing_form: str,
    changed_section_names: tuple[str, ...] = (),
) -> ExtractedFiling:
    """Apply the form-aware selector while retaining the accepted fallback baseline."""

    baseline = extract_research_excerpt(body)
    selected = select_form_aware_evidence(
        body,
        filing_form=filing_form,
        baseline_text=baseline.text,
        changed_section_names=changed_section_names,
        required_baseline_terms=(*baseline.opportunity_terms, *baseline.risk_terms),
    )
    lowered = selected.text.casefold()
    return ExtractedFiling(
        text=selected.text,
        content_sha256=sha256(selected.text.encode("utf-8")).hexdigest(),
        opportunity_terms=tuple(term for term in OPPORTUNITY_TERMS if term in lowered),
        risk_terms=tuple(term for term in RISK_TERMS if term in lowered),
        evidence_budget=selected.receipt,
    )


def exclude_exact_event_evidence(
    extracted: ExtractedFiling, quotes: tuple[str, ...]
) -> ExtractedFiling:
    """Remove only exact deterministically classified recap evidence before inference."""

    text = extracted.text
    for quote in quotes:
        text = text.replace(quote, " ")
    text = " ".join(text.split())
    lowered = text.casefold()
    evidence_budget = extracted.evidence_budget
    if evidence_budget is not None:
        payload = evidence_budget.model_dump(mode="python")
        payload.update(
            {
                "post_filter_excerpt_sha256": sha256(text.encode("utf-8")).hexdigest(),
                "post_filter_characters": len(text),
                "post_filter_estimated_tokens": (len(text) + 3) // 4,
                "excluded_event_quote_sha256s": tuple(
                    sha256(quote.encode("utf-8")).hexdigest() for quote in quotes
                ),
            }
        )
        evidence_budget = EvidenceBudgetReceipt.model_validate(payload)
    return ExtractedFiling(
        text=text,
        content_sha256=sha256(text.encode("utf-8")).hexdigest(),
        opportunity_terms=tuple(term for term in OPPORTUNITY_TERMS if term in lowered),
        risk_terms=tuple(term for term in RISK_TERMS if term in lowered),
        evidence_budget=evidence_budget,
    )


def _diverse_positions(
    opportunity_positions: tuple[int, ...], risk_positions: tuple[int, ...]
) -> tuple[int, ...]:
    """Reserve one window per present polarity, then fill in filing order."""

    prioritized: list[int] = []
    if opportunity_positions:
        prioritized.append(min(opportunity_positions))
    if risk_positions:
        prioritized.append(min(risk_positions))
    prioritized.extend(sorted({*opportunity_positions, *risk_positions}))
    return tuple(dict.fromkeys(position for position in prioritized if position >= 0))


def _whole_word_window(text: str, position: int) -> tuple[int, int]:
    rough_start = max(0, position - WINDOW_CHARACTERS // 2)
    rough_end = min(len(text), position + WINDOW_CHARACTERS // 2)
    start = rough_start
    end = rough_end
    if rough_start:
        boundary = text.find(" ", rough_start)
        if boundary >= 0 and boundary < position:
            start = boundary + 1
    if rough_end < len(text):
        boundary = text.rfind(" ", position, rough_end)
        if boundary > position:
            end = boundary
    return start, end
