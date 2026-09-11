"""Rate-limited SEC daily-index discovery and bounded filing retrieval."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as datetime_time
from hashlib import sha256

from kalki_market_intelligence.providers.sec.client import (
    RETRYABLE_STATUS_CODES,
    HttpTransport,
    RateLimiter,
    SecHttpError,
    SecResponseError,
    UrllibHttpTransport,
    validate_sec_url,
)
from kalki_market_intelligence.radar.contracts import FilingCandidate

MASTER_INDEX_PATTERN = re.compile(r"^edgar/data/(\d{1,10})/(?:\d{18}/)?(\d{10}-\d{2}-\d{6})\.txt$")
TRACKED_FORMS = frozenset(
    {"8-K", "8-K/A", "10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "40-F", "6-K"}
)


@dataclass(frozen=True, slots=True)
class SecRadarDocument:
    url: str
    body: bytes
    content_sha256: str
    retrieved_at: datetime
    media_type: str


class SecRadarClient:
    """Fetch only documented SEC index, mapping, and archive paths."""

    def __init__(
        self,
        *,
        user_agent: str,
        requests_per_second: float = 2,
        timeout_seconds: float = 30,
        maximum_response_bytes: int = 50_000_000,
        maximum_attempts: int = 3,
        transport: HttpTransport | None = None,
        limiter: RateLimiter | None = None,
        retry_sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        normalized = user_agent.strip()
        if (
            len(normalized) < 10
            or len(normalized) > 255
            or "@" not in normalized
            or " " not in normalized
            or not normalized.isprintable()
        ):
            raise ValueError("SEC user agent must identify the application and a contact email")
        self._headers = {
            "User-Agent": normalized,
            "Accept": "application/json, text/plain, text/html",
            "Accept-Encoding": "gzip, deflate",
        }
        self._timeout = timeout_seconds
        self._maximum_bytes = maximum_response_bytes
        self._maximum_attempts = maximum_attempts
        self._transport = transport or UrllibHttpTransport()
        self._limiter = limiter or RateLimiter(requests_per_second)
        self._retry_sleep = retry_sleep
        self._now = now or (lambda: datetime.now(UTC))

    def fetch(self, url: str, *, media_types: frozenset[str]) -> SecRadarDocument:
        validate_sec_url(url)
        for attempt in range(1, self._maximum_attempts + 1):
            self._limiter.wait()
            response = self._transport.get(
                url,
                headers=self._headers,
                timeout=self._timeout,
                maximum_bytes=self._maximum_bytes,
            )
            if response.status_code == 200:
                media_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if media_type not in media_types:
                    raise SecResponseError(
                        f"SEC radar response has unexpected media type: {media_type or 'missing'}"
                    )
                observed = self._now()
                if observed.tzinfo is None or observed.utcoffset() is None:
                    raise SecResponseError("SEC radar clock must be timezone-aware")
                return SecRadarDocument(
                    url=response.url,
                    body=response.body,
                    content_sha256=sha256(response.body).hexdigest(),
                    retrieved_at=observed.astimezone(UTC),
                    media_type=media_type,
                )
            if (
                response.status_code not in RETRYABLE_STATUS_CODES
                or attempt == self._maximum_attempts
            ):
                raise SecHttpError(response.status_code, url)
            self._retry_sleep(min(60.0, float(2 ** (attempt - 1))))
        raise AssertionError("unreachable SEC radar retry state")

    def latest_master_index(self, observed_on: date) -> SecRadarDocument:
        """Return the newest available daily index from the last seven calendar days."""

        last_error: SecHttpError | None = None
        for days_ago in range(8):
            target = observed_on - timedelta(days=days_ago)
            quarter = (target.month - 1) // 3 + 1
            url = (
                "https://www.sec.gov/Archives/edgar/daily-index/"
                f"{target.year}/QTR{quarter}/master.{target:%Y%m%d}.idx"
            )
            try:
                return self.fetch(
                    url,
                    media_types=frozenset({"text/plain", "application/octet-stream"}),
                )
            except SecHttpError as error:
                # SEC may answer 403 rather than 404 while today's daily index is
                # not yet published. Continue only within this fixed date path;
                # an actual access block will still fail after all bounded dates.
                if error.status_code not in {403, 404}:
                    raise
                last_error = error
        assert last_error is not None
        raise last_error

    def ticker_mapping(self) -> SecRadarDocument:
        return self.fetch(
            "https://www.sec.gov/files/company_tickers_exchange.json",
            media_types=frozenset({"application/json", "text/json"}),
        )

    def filing(self, source_url: str) -> SecRadarDocument:
        if (
            MASTER_INDEX_PATTERN.fullmatch(source_url.removeprefix("https://www.sec.gov/Archives/"))
            is None
        ):
            raise ValueError("filing URL does not match an SEC complete-submission path")
        return self.fetch(
            source_url,
            media_types=frozenset({"text/plain", "application/octet-stream"}),
        )

    def companyfacts(self, cik: str) -> SecRadarDocument:
        """Fetch one bounded SEC XBRL companyfacts document for later claim matching."""

        if not re.fullmatch(r"\d{1,10}", cik):
            raise ValueError("companyfacts CIK must be numeric")
        normalized = cik.zfill(10)
        return self.fetch(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{normalized}.json",
            media_types=frozenset({"application/json", "text/json"}),
        )

    def submissions(self, cik: str) -> SecRadarDocument:
        """Fetch one bounded SEC submissions history for conservative identity resolution."""

        if not re.fullmatch(r"\d{1,10}", cik):
            raise ValueError("submissions CIK must be numeric")
        return self.fetch(
            f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json",
            media_types=frozenset({"application/json", "text/json"}),
        )


def parse_ticker_mapping(document: SecRadarDocument) -> dict[str, tuple[str, str | None]]:
    """Select one deterministic listed symbol per CIK from the SEC mapping."""

    try:
        payload: object = json.loads(document.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SecResponseError("SEC ticker mapping is not valid JSON") from error
    if not isinstance(payload, dict) or payload.get("fields") != [
        "cik",
        "name",
        "ticker",
        "exchange",
    ]:
        raise SecResponseError("SEC ticker mapping fields changed")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise SecResponseError("SEC ticker mapping has no data rows")
    mapping: dict[str, tuple[str, str | None]] = {}
    for row in rows:
        if (
            not isinstance(row, list)
            or len(row) != 4
            or not isinstance(row[0], int)
            or not isinstance(row[2], str)
            or not isinstance(row[3], str | type(None))
        ):
            continue
        cik = str(row[0])
        symbol = row[2].strip().upper()
        exchange = None if row[3] is None else row[3].strip() or None
        if cik not in mapping and re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,14}", symbol):
            mapping[cik] = (symbol, exchange)
    return mapping


def latest_submission_candidate(
    document: SecRadarDocument,
    *,
    cik: str,
    ticker: str | None = None,
) -> FilingCandidate | None:
    """Convert one recent tracked submission into a normal filing candidate."""

    try:
        payload = json.loads(document.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SecResponseError("SEC submissions response is not valid JSON") from error
    recent = payload.get("filings", {}).get("recent") if isinstance(payload, dict) else None
    if not isinstance(recent, dict):
        raise SecResponseError("SEC submissions response has no recent filings")
    forms = recent.get("form")
    accessions = recent.get("accessionNumber")
    dates = recent.get("filingDate")
    if (
        not isinstance(forms, list)
        or not isinstance(accessions, list)
        or not isinstance(dates, list)
    ):
        raise SecResponseError("SEC submissions recent arrays are malformed")
    for form, accession, filed_on in zip(forms, accessions, dates, strict=False):
        if not isinstance(form, str) or form not in TRACKED_FORMS:
            continue
        if not isinstance(accession, str) or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
            continue
        if not isinstance(filed_on, str):
            continue
        try:
            filed_at = datetime.fromisoformat(filed_on).replace(tzinfo=UTC)
        except ValueError:
            continue
        cik_digits = str(int(cik)).zfill(10)
        url = (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{int(cik)}/{accession.replace('-', '')}/{accession}.txt"
        )
        return FilingCandidate(
            accession_number=accession,
            cik=cik_digits,
            company_name=str(payload.get("name", "SEC issuer"))[:240],
            ticker=ticker,
            exchange=None,
            filing_form=form,
            filed_at=filed_at,
            source_url=url,
            discovered_at=document.retrieved_at,
        )
    return None


def parse_master_index(
    document: SecRadarDocument,
    ticker_mapping: Mapping[str, tuple[str, str | None]],
) -> tuple[FilingCandidate, ...]:
    """Parse documented pipe-delimited rows and retain listed operating-company forms."""

    try:
        text = document.body.decode("latin-1")
    except UnicodeDecodeError as error:
        raise SecResponseError("SEC master index could not be decoded") from error
    candidates: list[FilingCandidate] = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) != 5 or parts[2] not in TRACKED_FORMS:
            continue
        cik, company_name, filing_form, filed_on, filename = parts
        match = MASTER_INDEX_PATTERN.fullmatch(filename)
        symbol = ticker_mapping.get(cik)
        if match is None or match.group(1) != cik or symbol is None:
            continue
        try:
            filed_date = date.fromisoformat(filed_on)
        except ValueError:
            continue
        ticker, exchange = symbol
        candidates.append(
            FilingCandidate(
                accession_number=match.group(2),
                cik=cik,
                company_name=" ".join(company_name.split())[:255],
                ticker=ticker,
                exchange=exchange,
                filing_form=filing_form,
                filed_at=datetime.combine(filed_date, datetime_time.min, tzinfo=UTC),
                source_url=f"https://www.sec.gov/Archives/{filename}",
                discovered_at=document.retrieved_at,
            )
        )
    return tuple(candidates)
