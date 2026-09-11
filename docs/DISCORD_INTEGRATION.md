# Optional Discord Integration

> **Status:** Phase 10 is complete. User approval was received on 2026-08-24, all
> offline checks pass, and a synthetic message was confirmed in the intended
> private destination. The webhook remains only in ignored local configuration.

## Safety boundary

The integration only sends outbound HTTPS messages through one configured Discord
incoming webhook. It has no bot token, Discord account credentials, inbound
listener, command handling, brokerage connection, or trade execution capability.
It is hard-disabled unless both `KALKI_DISCORD_ENABLED=true` and a validated
`KALKI_DISCORD_WEBHOOK_URL` are present.

Webhook URLs are secrets. They belong only in the ignored local `.env` file or a
future reviewed secret store. Do not paste one into chat, logs, tests,
documentation, shell history, or Git. Audit records retain a hash of the webhook
ID—not its token or URL.

## Message policy

Published-research alerts contain only immutable prediction metadata: label,
separate heuristic opportunity/risk/research-confidence points, risk profile,
horizon, evidence count, and signal fingerprint. Thesis prose is excluded from
Discord to prevent embedded mentions or action language. Every message says it is
research only, not financial advice or a trade instruction, requests no action,
and disables all Discord mention parsing.

The adapter:

- stays within Discord's 2,000-character content boundary;
- uses `wait=true` so a success includes a saved message ID;
- spaces local sends conservatively and honors returned 429 retry delays;
- deduplicates by prediction ID, signal fingerprint, and template version;
- retries only explicit 429 responses;
- suppresses automatic resend after timeouts, invalid success bodies, redirects,
  or server errors because delivery may already have happened; and
- emits closed, secret-free delivery records for sent, duplicate, disabled,
  rejected, rate-limited, and uncertain outcomes.

These choices follow Discord's official [webhook execution](https://docs.discord.com/developers/resources/webhook)
and [rate-limit](https://docs.discord.com/developers/topics/rate-limits) guidance.

## Private setup and live gate

The user must create or select a private Discord channel, create an incoming
webhook for that channel, and copy its URL directly into the ignored local `.env`
file:

```dotenv
KALKI_DISCORD_ENABLED=true
KALKI_DISCORD_WEBHOOK_URL="your Discord webhook URL"
```

Do not send the URL to Codex in chat. Once the local file is ready, run one
synthetic connection test from the repository root:

```bash
.venv/bin/python -m kalki_market_intelligence.notifications.cli --confirm-live-send
```

The command sends no market data, prediction, or signal. It prints only the
secret-free delivery audit. The final gate succeeded in one attempt and the user
confirmed the message arrived in the intended private test channel. An earlier
synthetic test reached the wrong non-private channel; it contained no research data
and was deleted before the phase was accepted. Disable the adapter at any time by
setting `KALKI_DISCORD_ENABLED=false` or removing the local secret; this does not
affect prediction or outcome functionality.

## Limitations

- Legacy prediction-test deduplication remains process-local. Phase 15 filing-radar
  deliveries are durable in PostgreSQL and are resumed by the supervised worker.
- A timeout or server failure is reported as delivery-uncertain and requires human
  inspection before any manual retry.
- The Phase 15 worker automatically delivers accepted filing-radar briefs. It sends
  nothing while SEC identity is unconfigured or when analysis fails validation.
