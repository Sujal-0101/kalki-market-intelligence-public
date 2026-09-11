"""Local-only typed web and administration boundary."""

from kalki_market_intelligence.web.app import create_public_web_app, create_web_app
from kalki_market_intelligence.web.repository import (
    MemoryResearchRepository,
    PostgresResearchRepository,
)

__all__ = [
    "MemoryResearchRepository",
    "PostgresResearchRepository",
    "create_public_web_app",
    "create_web_app",
]
