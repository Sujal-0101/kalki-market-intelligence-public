# Kalki capability audit (observation baseline)

This is a decision record, not a claim that every upstream project is suitable
for production. Kalki keeps its own contracts and provenance boundary; upstream
projects are references for narrowly useful ideas only. No paid service is a
core dependency.

| Capability | Current Kalki support | Reference | Decision |
|---|---|---|---|
| SEC acquisition, accession identity, hashes | SEC radar client and immutable records | SEC EDGAR / EdgarTools | ALREADY_IMPLEMENTED; keep adapter isolated until equivalence proves a gain |
| XBRL/context-aware numeric verification | CompanyFacts normalization and fail-closed matching | sec-analyzer-ai | ALREADY_IMPLEMENTED; expand only with a reproducible missing case |
| Filing-to-filing section diffs | bounded provenance-preserving textual diff | sec-analyzer-ai | ALREADY_IMPLEMENTED; defer semantic model interpretation |
| Share growth, liquidity, going concern, reverse split | deterministic forensic signals with explicit unknown states | PennyTune | ALREADY_IMPLEMENTED |
| ATM/shelf/warrant/convertible forensic parsing | no reliable bounded primary-source contract yet | PennyTune | DEFER_UNTIL_OBSERVATION; add only with fixtures and a real consumer |
| Form 4 / Form 144 / 13D/G | no production source contract | SEC primary filings | DEFER_UNTIL_OBSERVATION; requires separate identity and context fixtures |
| Tiered routing | deterministic Tier-0 and selective Qwen Tier-2 path | reverse-quant concepts | ALREADY_IMPLEMENTED; no Tier-1 model without measured need |
| Independent verifier | Gemma 12B qualification failed safety/latency | Phase 17 evaluation | REJECT for production; keep disabled |
| Provenance dossier | evidence, numeric receipts, forensic/diff lineage | LangAlpha concepts | ALREADY_IMPLEMENTED for current public/private surfaces |
| Human research intake/execution | bounded Gateway intake, durable queue, SEC resolution, private result delivery | native Kalki | IMPLEMENTED; observe real usage |
| Convergence lineage | authority-aware independent-channel counts | LangAlpha/Pulsar concepts | ALREADY_IMPLEMENTED; no opaque predictive score |
| Forward outcome science | append-only forward/reconstructed distinction and conservative reports | YUCLAW methodology | ALREADY_IMPLEMENTED foundation; defer richer statistics until sample size |
| Market-price/news aggregation | intentionally limited; no paid feed | OpenBB/FinRobot/TradingAgents | REJECT for core; unofficial sources cannot outrank SEC evidence |
| Multi-agent debate/RAG/vector infrastructure | absent | TradingAgents, FinGPT, RAG Equity | REJECT: cost, complexity, and no demonstrated consumer on this hardware |
| Trading/brokerage execution | absent by policy | AI Hedge Fund-style projects | REJECT permanently |

## Observation triggers

Reopen a deferred capability only after a real production case demonstrates a
miss, repeated false positive, measurable queue bottleneck, or a concrete
researcher workflow need. Synthetic fixtures alone do not justify a new model,
source, or always-on service.
