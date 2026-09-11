"""Static accessibility checks for the repository-native observatory design."""

from __future__ import annotations

import re
import struct
from pathlib import Path

ROOT = Path(__file__).parents[1]
STATIC = ROOT / "src/kalki_market_intelligence/web/static"


def _luminance(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: str, second: str) -> float:
    bright, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (bright + 0.05) / (dark + 0.05)


def test_core_semantic_text_palette_meets_wcag_aa_on_editorial_paper() -> None:
    stylesheet = (STATIC / "app.css").read_text(encoding="utf-8")
    colors = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-f]{6})", stylesheet))

    for name in ("ink", "indigo", "cobalt", "muted", "jade", "coral", "saffron", "violet"):
        assert _contrast(colors[name], colors["paper"]) >= 4.5, name
    assert _contrast(colors["white"], colors["indigo"]) >= 4.5


def test_original_identity_assets_have_accessible_metadata_and_social_dimensions() -> None:
    mark = (STATIC / "kalki-mark.svg").read_text(encoding="utf-8")
    social_svg = (STATIC / "social-card.svg").read_text(encoding="utf-8")
    social_png = (STATIC / "social-card.png").read_bytes()

    assert "<title" in mark and "<desc" in mark
    assert "<title" in social_svg and "<desc" in social_svg
    assert social_png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", social_png[16:24])
    assert (width, height) == (1200, 630)
