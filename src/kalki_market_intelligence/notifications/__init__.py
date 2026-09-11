"""Optional outbound research notifications."""

from kalki_market_intelligence.notifications.discord import DiscordNotifier
from kalki_market_intelligence.notifications.templates import ResearchNotification

__all__ = ["DiscordNotifier", "ResearchNotification"]
