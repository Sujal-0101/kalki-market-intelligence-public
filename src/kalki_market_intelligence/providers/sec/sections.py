"""Bounded deterministic section mapping for filing HTML."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser


@dataclass(frozen=True, slots=True)
class FilingSectionText:
    name: str
    text: str


class _SectionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[FilingSectionText] = []
        self._heading: str | None = None
        self._parts: list[str] = []
        self._capture_heading = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"h1", "h2", "h3"}:
            self._finish()
            self._capture_heading = True
            self._heading = ""

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"h1", "h2", "h3"}:
            self._capture_heading = False

    def handle_data(self, data: str) -> None:
        normalized = " ".join(data.split())
        if not normalized:
            return
        if self._capture_heading and self._heading is not None:
            self._heading += f" {normalized}"
        elif self._heading is not None:
            self._parts.append(normalized)

    def close(self) -> None:
        super().close()
        self._finish()

    def _finish(self) -> None:
        if self._heading and self._parts:
            self.sections.append(
                FilingSectionText(self._heading.strip()[:255], " ".join(self._parts)[:20_000])
            )
        self._heading = None
        self._parts = []


def extract_filing_sections(
    body: bytes, *, maximum_sections: int = 64
) -> tuple[FilingSectionText, ...]:
    """Extract named heading sections without interpreting their meaning."""

    parser = _SectionParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    parser.close()
    return tuple(parser.sections[:maximum_sections])
