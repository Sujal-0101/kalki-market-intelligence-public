"""Bounded deterministic filing-to-filing text comparisons."""

from __future__ import annotations

from difflib import SequenceMatcher
from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from kalki_market_intelligence.contracts.common import ContractModel, NonEmptyText, Sha256Hex

FILING_DIFF_VERSION = "1.0.0"
type FilingIdentifier = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class FilingDiffChangeKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"


class FilingSection(ContractModel):
    """One bounded named section extracted from a filing."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    text: NonEmptyText = Field(max_length=20_000)


class FilingSnapshot(ContractModel):
    """Comparable filing text plus immutable source identity."""

    filing_id: FilingIdentifier
    accession_number: FilingIdentifier
    source_content_sha256: Sha256Hex
    sections: tuple[FilingSection, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def section_names_are_unique(self) -> FilingSnapshot:
        names = tuple(section.name for section in self.sections)
        if len(set(names)) != len(names):
            raise ValueError("filing section names must be unique")
        return self


class FilingDiffChange(ContractModel):
    """One section-level change retaining both bounded text sides."""

    section_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ]
    kind: FilingDiffChangeKind
    previous_text: str = Field(default="", max_length=20_000)
    current_text: str = Field(default="", max_length=20_000)

    @model_validator(mode="after")
    def change_has_expected_sides(self) -> FilingDiffChange:
        if self.kind is FilingDiffChangeKind.ADDED and not self.current_text:
            raise ValueError("added filing change requires current text")
        if self.kind is FilingDiffChangeKind.REMOVED and not self.previous_text:
            raise ValueError("removed filing change requires previous text")
        if self.kind is FilingDiffChangeKind.MODIFIED and (
            not self.previous_text or not self.current_text
        ):
            raise ValueError("modified filing change requires both text sides")
        return self


class FilingDiff(ContractModel):
    """A reproducible diff whose inputs remain independently addressable."""

    previous_filing_id: FilingIdentifier
    current_filing_id: FilingIdentifier
    previous_accession_number: FilingIdentifier
    current_accession_number: FilingIdentifier
    previous_source_content_sha256: Sha256Hex
    current_source_content_sha256: Sha256Hex
    calculation_version: str = FILING_DIFF_VERSION
    changes: tuple[FilingDiffChange, ...] = Field(max_length=128)


def compare_filings(previous: FilingSnapshot, current: FilingSnapshot) -> FilingDiff:
    """Compare matching named sections without using an LLM or external parser."""

    previous_sections = {section.name: section.text for section in previous.sections}
    current_sections = {section.name: section.text for section in current.sections}
    changes: list[FilingDiffChange] = []
    for name in sorted(set(previous_sections) | set(current_sections)):
        before = previous_sections.get(name)
        after = current_sections.get(name)
        if before is None:
            changes.append(
                FilingDiffChange(
                    section_name=name,
                    kind=FilingDiffChangeKind.ADDED,
                    current_text=after or "",
                )
            )
            continue
        if after is None:
            changes.append(
                FilingDiffChange(
                    section_name=name,
                    kind=FilingDiffChangeKind.REMOVED,
                    previous_text=before,
                )
            )
            continue
        if _normalize_text(before) == _normalize_text(after):
            continue
        # SequenceMatcher is used as a deterministic meaningful-change gate; the
        # full bounded sides remain available for provenance and later inspection.
        matcher = SequenceMatcher(None, _lines(before), _lines(after), autojunk=False)
        if matcher.ratio() < 1.0:
            changes.append(
                FilingDiffChange(
                    section_name=name,
                    kind=FilingDiffChangeKind.MODIFIED,
                    previous_text=before,
                    current_text=after,
                )
            )
    return FilingDiff(
        previous_filing_id=previous.filing_id,
        current_filing_id=current.filing_id,
        previous_accession_number=previous.accession_number,
        current_accession_number=current.accession_number,
        previous_source_content_sha256=previous.source_content_sha256,
        current_source_content_sha256=current.source_content_sha256,
        changes=tuple(changes),
    )


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def _lines(value: str) -> list[str]:
    return [_normalize_text(line) for line in value.splitlines() if _normalize_text(line)]
