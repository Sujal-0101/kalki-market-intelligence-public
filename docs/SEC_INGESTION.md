# SEC/US Ingestion

> **Status:** Phase 3 provider boundary completed on 2026-08-21 UTC. It retrieves
> only explicitly requested CIKs; it is not a crawler, scheduler, database, or
> complete historical filing downloader.

Phase 15 does not change this Phase 3 adapter. It adds a separate supervised filing
radar over the SEC's documented daily master indexes and complete-submission archive
paths. That narrower operating path is described in
[LIVE_RESEARCH_RADAR.md](LIVE_RESEARCH_RADAR.md).

## Official interfaces and access policy

The implementation is based on the SEC's current official documentation:

- [EDGAR Application Programming Interfaces](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [Developer Resources and Fair Access](https://www.sec.gov/about/developer-resources)
- [Accessing EDGAR Data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
- [Webmaster developer FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions)

The SEC documents that `data.sec.gov` needs no authentication or API key, asks
automated tools to declare an application/contact email in `User-Agent`, and
currently limits total automated access to no more than 10 requests per second.
Kalki defaults to two requests per second and refuses configuration above ten.
Retries are bounded and respect a numeric `Retry-After` value up to 60 seconds.
Run only one ingestion process at a time: the limiter is shared within a process,
while the SEC's ceiling applies to the operator's combined traffic.

The application sends the contact identity to SEC as required. Use a contact
address the operator is comfortable disclosing in HTTP request logs. This is not
an API credential and must not be replaced with a secret token.

## Implemented endpoints

For a validated, zero-padded ten-digit CIK, the provider can retrieve:

```text
https://data.sec.gov/submissions/CIK##########.json
https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
```

The first response supplies issuer metadata and recent filing history. The second
supplies entity-wide facts that the SEC can aggregate under supported standard
taxonomies. The adapter does not use the authenticated EDGAR filing-submission
APIs, full-text search, browser automation, or undocumented endpoints.

Submissions responses can reference separate files containing older history.
Phase 3 retains those references in the raw response but deliberately normalizes
only the `filings.recent` arrays. Expanding historical files and downloading full
filing documents require a later scoped ingestion job with the same access policy.

## Trust and time semantics

External JSON is untrusted. The client permits only HTTPS on `data.sec.gov` and
`www.sec.gov`, including redirects; requires a JSON object and approved media
type; bounds compressed and decoded response size; validates parallel column
lengths; and rejects unsafe document names before constructing archive URLs.

Each successful raw response is hashed with SHA-256 and stored once under:

```text
data/raw/sec/blobs/<content-sha256>.json
data/raw/sec/manifests/<endpoint>/<cik>/<retrieval-id>.json
```

Manifests preserve endpoint, CIK, URL, HTTP status, media type, byte length,
content hash, retrieval time, and available ETag/Last-Modified values. Writes use
an atomic temporary-file replacement so interruption cannot leave a partial file.
These paths are local generated data and remain ignored by Git.

The SEC acceptance timestamp is preserved as `accepted_at`. Because the SEC says
there is no timestamp showing the exact moment filing content first becomes
public, this phase conservatively sets `available_at` to this system's UTC
retrieval time. This may be later than actual publication, but it prevents
look-ahead: research can never claim access before retrieval.

Normalized records preserve source content hashes and stable logical IDs:

- issuer identity, SIC metadata, and explicitly missing exchange values;
- recent filing accession, form, dates, primary document, and archive URL; and
- XBRL taxonomy, tag, label, unit, exact decimal value, reporting context,
  accession, form, and filed date.

No ratios, financial interpretation, or arithmetic occur during ingestion.

## Local use

Copy `.env.example` to the ignored `.env` and replace the SEC user-agent example
with an application name and monitored contact email. Then ingest only CIKs that
are needed:

```bash
.venv/bin/kalki-ingest-sec 320193
```

The command prints record counts and a logical fingerprint, not the raw response.
It returns a non-zero status on transport, HTTP, validation, normalization, or
storage-integrity failures. Re-running identical inputs deduplicates raw blobs and
produces the same logical record IDs. A later persistence phase can upsert those
IDs into PostgreSQL without coupling storage to SEC's response layout.

## Verification and current limitation

Tracked fixtures cover two explicitly synthetic issuers, multiple listings,
annual, quarterly, and current filings, instant and duration facts, missing
optional fields, retry, partial-failure recovery, provenance, and idempotency.
They are schema fixtures, not financial evidence.

A Phase 3 live smoke request to each documented public endpoint and the SEC ticker
file returned HTTP 403 from the current environment on 2026-08-21 UTC. The test
stopped after those responses; no bypass or repeated probing was attempted and no
live response was stored. The fixture-driven adapter is complete, but actual live
operation remains dependent on SEC accepting requests from the operator's network.
