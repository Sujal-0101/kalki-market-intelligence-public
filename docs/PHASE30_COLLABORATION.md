# Phase 30 — collaboration and observation readiness

Human feedback is an append-only observation linked to a research reference. It
cannot mutate publications, predictions, confidence, rulesets, or outcomes.
Each trusted submitter may record one feedback type per reference; repeat
submissions are idempotent. Notes are bounded to 1,000 characters and Discord
identities are stable snowflake IDs.

The current Discord integration is webhook-only. Inbound intake therefore stays
disabled until an administrator creates a Discord application/bot. The minimum
future boundary is a bot restricted to the private intake/research channels,
with View Channel, Read Message History, and Send Messages only; the Message
Content privileged intent may be required to read message bodies. Store the bot
token in an ignored local file referenced by `KALKI_DISCORD_INTAKE_BOT_TOKEN_FILE`
and configure channel/user IDs through ignored environment configuration. Never
paste the token into chat, documentation, logs, or Git.

The credential-free parser already enforces channel and stable-user allowlists,
bounded content, and safe lead contracts. Message content remains hypothesis
data, including prompt-injection text; it is never concatenated into a system
prompt. Human URLs are pointers and are validated before any future retrieval.

Observation mode begins after the deployed migration and dashboard gates pass.
Track real production counts for leads, Tier-0 outcomes, model calls avoided,
feedback, publication latency, and forward outcomes. Do not infer predictive
performance from synthetic or small samples. No further major feature phase is
authorized without a real production bug, security issue, measured bottleneck,
repeated false positive/negative, or a demonstrated research workflow need.
