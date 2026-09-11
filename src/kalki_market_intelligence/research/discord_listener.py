"""Least-privilege Discord Gateway intake adapter.

The listener only validates and persists leads. It never invokes models or
publishes research; the durable worker queue remains the execution boundary.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import discord

from kalki_market_intelligence.config import Settings
from kalki_market_intelligence.database import DatabaseOptions, DatabaseRuntime, read_secret_file
from kalki_market_intelligence.radar.store import PostgresRadarStore
from kalki_market_intelligence.research.intake import parse_discord_submission

LOG = logging.getLogger(__name__)


class ResearchIntakeClient(discord.Client):
    def __init__(
        self,
        *,
        store: PostgresRadarStore,
        channel_id: str,
        allowlist: frozenset[str],
        results_channel_id: str,
    ) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.messages = True
        intents.message_content = True
        super().__init__(intents=intents)
        self._store = store
        self._channel_id = channel_id
        self._allowlist = allowlist
        self._results_channel_id = results_channel_id
        self._history_replayed = False
        self._delivery_task: asyncio.Task[None] | None = None

    async def on_ready(self) -> None:
        LOG.info("Discord research intake connected")
        if self._delivery_task is None:
            self._delivery_task = asyncio.create_task(self._deliver_results())
        if self._history_replayed:
            return
        self._history_replayed = True
        channel = self.get_channel(int(self._channel_id))
        if isinstance(channel, discord.TextChannel):
            async for message in channel.history(limit=20):
                await self.on_message(message)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.webhook_id is not None:
            return
        payload: dict[str, object] = {
            "id": str(message.id),
            "channel_id": str(message.channel.id),
            "timestamp": message.created_at.astimezone(UTC).isoformat(),
            "content": message.content,
            "author": {"id": str(message.author.id)},
        }
        try:
            lead = parse_discord_submission(
                payload, channel_id=self._channel_id, allowlist=self._allowlist
            )
        except (PermissionError, ValueError):
            return
        queued = self._store.enqueue_human_lead(lead, now=datetime.now(UTC))
        status = queued.status.value.upper()
        await message.channel.send(
            "Research lead "
            f"{status.lower()} · {str(lead.lead_id)[:8]} · {lead.ticker or 'unresolved'}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _deliver_results(self) -> None:
        while not self.is_closed():
            try:
                item = self._store.claim_human_result_delivery(now=datetime.now(UTC))
                if item is not None:
                    result_id, record = item
                    channel = self.get_channel(int(self._results_channel_id))
                    if isinstance(channel, discord.TextChannel):
                        disposition = str(record.get("disposition", "inconclusive")).upper()
                        source = record.get("source")
                        ticker = (
                            source.get("ticker")
                            if isinstance(source, dict)
                            else record.get("ticker")
                        ) or "unresolved"
                        hypothesis = str(record.get("hypothesis") or "").strip()
                        conclusion = str(record.get("conclusion") or "").strip()
                        lines = [
                            f"Research result · {str(result_id)[:8]} · {ticker} · {disposition}"
                        ]
                        if hypothesis:
                            lines.append(f"Hypothesis: {hypothesis[:240]}")
                        cik = (
                            source.get("canonical_cik")
                            if isinstance(source, dict)
                            else record.get("cik")
                        )
                        accession = (
                            source.get("accession_number") if isinstance(source, dict) else None
                        )
                        accessions = record.get("accessions")
                        evidence_ids = record.get("evidence_ids")
                        if cik:
                            lines.append(f"SEC CIK: {cik}")
                        if accession:
                            lines.append(f"Accession: {str(accession)[:32]}")
                        elif isinstance(accessions, list) and accessions:
                            lines.append(f"Accession: {str(accessions[0])[:32]}")
                        if isinstance(evidence_ids, list) and evidence_ids:
                            lines.append(f"Evidence: {str(evidence_ids[0])[:36]}")
                        if conclusion:
                            lines.append(f"Conclusion: {conclusion[:400]}")
                        sent = await channel.send(
                            "\n".join(lines),
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                        self._store.complete_human_result_delivery(
                            result_id, now=datetime.now(UTC), message_id=str(sent.id)
                        )
            except Exception:
                LOG.exception("human research result delivery attempt failed")
            await asyncio.sleep(10)


def run_listener(settings: Settings) -> None:
    if not settings.discord_intake_enabled or settings.discord_intake_bot_token_file is None:
        raise RuntimeError("Discord research intake is disabled or missing token configuration")
    if settings.database_password_file is None or settings.discord_intake_channel_id is None:
        raise RuntimeError("Discord research intake requires database and channel configuration")
    token = read_secret_file(settings.discord_intake_bot_token_file, label="Discord bot token")
    runtime = DatabaseRuntime(
        DatabaseOptions(
            host=settings.database_host,
            port=settings.database_port,
            name=settings.database_name,
            user=settings.database_user,
            password_file=settings.database_password_file,
            minimum_pool_size=1,
            maximum_pool_size=2,
        )
    )
    runtime.open()
    try:
        client = ResearchIntakeClient(
            store=PostgresRadarStore(runtime.connection),
            channel_id=settings.discord_intake_channel_id,
            allowlist=frozenset(settings.discord_intake_allowlist),
            results_channel_id=(
                settings.discord_intake_results_channel_id or settings.discord_intake_channel_id
            ),
        )
        client.run(token, log_handler=None)
    finally:
        runtime.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = Settings.load()
    run_listener(settings)
    return 0
