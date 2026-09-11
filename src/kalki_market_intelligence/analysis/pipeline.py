"""Bounded model execution followed by deterministic evidence validation."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from time import monotonic
from uuid import UUID, uuid4

from pydantic import ValidationError

from kalki_market_intelligence.analysis.attempts import (
    AnalystAttemptOutcome,
    AnalystAttemptReceipt,
    AnalystAttemptSink,
    AnalystAttemptStart,
    AnalystFailureCategory,
    AnalystFailureLayer,
    AnalystRetryScope,
    AnalystTerminalDisposition,
    AnalystWorkContext,
    AttemptCheckStatus,
)
from kalki_market_intelligence.analysis.contracts import (
    PROMPT_VERSION,
    VALIDATION_VERSION,
    AnalysisAudit,
    AnalystEvidence,
    AnalystReconsideration,
    AnalystReport,
    AnalystRole,
    Assessment,
    ContradictionStatus,
    EvidenceCitation,
    FindingCategory,
    FindingKind,
    FindingPolarity,
    ModelRequest,
    ModelResponse,
    ValidatedAnalysis,
    analyst_generation_schema,
)
from kalki_market_intelligence.analysis.prompts import SYSTEM_PROMPT_V2, build_user_prompt
from kalki_market_intelligence.analysis.provider import ModelProvider
from kalki_market_intelligence.contracts.common import normalize_utc

MAXIMUM_EVIDENCE_RECORDS = 8
MAXIMUM_EVIDENCE_CHARACTERS = 32_000
MAXIMUM_ATTEMPTS = 2

_INJECTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above)\s+instructions?\b",
        r"\b(?:system|developer)\s+(?:prompt|message|instructions?)\b",
        r"\byou\s+are\s+now\b",
        r"\b(?:call|invoke|use)\s+(?:a\s+|the\s+)?(?:tool|function|terminal|shell)\b",
        r"\b(?:execute|run)\s+(?:this\s+|the\s+)?(?:command|code|script)\b",
        r"\breveal\s+(?:the\s+|your\s+)?(?:prompt|secret|credentials?)\b",
        r"\b(?:send|upload|exfiltrate)\b.{0,80}\bhttps?://",
    )
)
_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d[\d,]*(?:\.\d+)?%?")
_URL_PATTERN = re.compile(r"https?://[^\s)\]}>\"']+", re.IGNORECASE)
_WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")
_GROUNDING_STOP_WORDS = {
    "about",
    "after",
    "before",
    "company",
    "could",
    "evidence",
    "from",
    "have",
    "into",
    "only",
    "that",
    "their",
    "there",
    "these",
    "this",
    "with",
    "would",
}

_ROLE_CATEGORIES: dict[AnalystRole, set[FindingCategory]] = {
    AnalystRole.DOCUMENT_INTERPRETER: {FindingCategory.DOCUMENT_FACT},
    AnalystRole.CATALYST_ANALYST: {FindingCategory.CATALYST},
    AnalystRole.PARTNERSHIP_ANALYST: {FindingCategory.PARTNERSHIP},
    AnalystRole.MANAGEMENT_COMMENTARY_ANALYST: {FindingCategory.MANAGEMENT_COMMENTARY},
    AnalystRole.CONTRADICTION_ANALYST: {FindingCategory.DOCUMENT_FACT},
    AnalystRole.BULL_BEAR_RISK_ANALYST: {
        FindingCategory.BULL_CASE,
        FindingCategory.BEAR_CASE,
        FindingCategory.RISK,
    },
}


class UnsafeEvidenceError(ValueError):
    """Evidence was quarantined before it reached the model."""


class AnalysisRejected(ValueError):
    """No model attempt passed deterministic output validation."""

    def __init__(self, error_codes: Sequence[str], attempts: int) -> None:
        self.error_codes = tuple(sorted(set(error_codes)))
        self.attempts = attempts
        super().__init__(
            f"analysis rejected after {attempts} attempt(s): {', '.join(self.error_codes)}"
        )


class AnalystPipeline:
    def __init__(
        self,
        provider: ModelProvider,
        *,
        maximum_attempts: int = MAXIMUM_ATTEMPTS,
        attempt_sink: AnalystAttemptSink | None = None,
        configured_provider_name: str | None = None,
        configured_model_name: str | None = None,
        configured_model_digest: str | None = None,
        now: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        if maximum_attempts < 1 or maximum_attempts > MAXIMUM_ATTEMPTS:
            raise ValueError("analysis attempts must be between one and two")
        configured_identity = (
            configured_provider_name,
            configured_model_name,
            configured_model_digest,
        )
        if attempt_sink is not None and any(item is None for item in configured_identity):
            raise ValueError("durable analyst attempts require configured model identity")
        self._provider = provider
        self._maximum_attempts = maximum_attempts
        self._attempt_sink = attempt_sink
        self._configured_provider_name = configured_provider_name
        self._configured_model_name = configured_model_name
        self._configured_model_digest = configured_model_digest
        self._now = now or (lambda: datetime.now(UTC))
        self._monotonic = monotonic_clock

    def analyze(
        self,
        *,
        role: AnalystRole,
        evidence: Sequence[AnalystEvidence],
        knowledge_cutoff_at: datetime,
        reconsideration: AnalystReconsideration | None = None,
        work_context: AnalystWorkContext | None = None,
    ) -> ValidatedAnalysis:
        cutoff = normalize_utc(knowledge_cutoff_at)
        if cutoff > datetime.now(UTC):
            raise ValueError("analysis knowledge cutoff must not be in the future")
        records = _validate_evidence(evidence, cutoff)
        if self._attempt_sink is not None and work_context is None:
            raise ValueError("durable analyst attempts require a work context")
        errors: tuple[str, ...] = ()
        last_response: ModelResponse | None = None
        normalizations: tuple[str, ...] = ()
        invocation_id = uuid4()
        for attempt in range(1, self._maximum_attempts + 1):
            request = ModelRequest(
                system_prompt=SYSTEM_PROMPT_V2,
                user_prompt=build_user_prompt(
                    role,
                    records,
                    repair_errors=errors,
                    reconsideration=reconsideration,
                ),
                output_schema=analyst_generation_schema(),
            )
            started = self._start_attempt(
                invocation_id=invocation_id,
                attempt_number=attempt,
                role=role,
                records=records,
                request=request,
                work_context=work_context,
            )
            started_clock = self._monotonic()
            try:
                last_response = self._provider.generate(request)
            except Exception as error:
                category = _classify_runtime_failure(error)
                retry_eligible = bool(
                    work_context is not None
                    and work_context.runtime_retry_eligible
                    and category is not AnalystFailureCategory.REFUSAL
                )
                self._finish_attempt(
                    started,
                    started_clock=started_clock,
                    response=None,
                    parse_status=AttemptCheckStatus.NOT_CHECKED,
                    schema_status=AttemptCheckStatus.NOT_CHECKED,
                    evidence_status=AttemptCheckStatus.NOT_CHECKED,
                    failure_layer=AnalystFailureLayer.RUNTIME,
                    failure_category=category,
                    failure_path="provider.generate",
                    retry_scope=(
                        AnalystRetryScope.WORK_ITEM if retry_eligible else AnalystRetryScope.NONE
                    ),
                    outcome=AnalystAttemptOutcome.RUNTIME_ERROR,
                    terminal_disposition=(
                        AnalystTerminalDisposition.RETRY_PENDING
                        if retry_eligible
                        else (
                            AnalystTerminalDisposition.REFUSAL
                            if category is AnalystFailureCategory.REFUSAL
                            else AnalystTerminalDisposition.PROVIDER_ERROR
                        )
                    ),
                )
                raise
            try:
                raw_report: object = json.loads(last_response.content)
                raw_report, raw_normalizations = normalize_raw_report(raw_report)
                report = AnalystReport.model_validate(raw_report)
            except json.JSONDecodeError:
                category = _classify_json_failure(last_response.content)
                errors = (category.value,)
                self._finish_rejected_attempt(
                    started,
                    started_clock=started_clock,
                    response=last_response,
                    attempt_number=attempt,
                    failure_layer=AnalystFailureLayer.FORMAT,
                    failure_category=category,
                    failure_path="$",
                    parse_status=AttemptCheckStatus.FAILED,
                    schema_status=AttemptCheckStatus.NOT_CHECKED,
                    evidence_status=AttemptCheckStatus.NOT_CHECKED,
                )
                continue
            except ValidationError as error:
                errors = _classify_validation_errors(error)
                category, failure_path = _diagnose_validation_errors(error)
                self._finish_rejected_attempt(
                    started,
                    started_clock=started_clock,
                    response=last_response,
                    attempt_number=attempt,
                    failure_layer=AnalystFailureLayer.FORMAT,
                    failure_category=category,
                    failure_path=failure_path,
                    parse_status=AttemptCheckStatus.PASSED,
                    schema_status=AttemptCheckStatus.FAILED,
                    evidence_status=AttemptCheckStatus.NOT_CHECKED,
                )
                continue
            except ValueError:
                errors = ("schema_validation",)
                self._finish_rejected_attempt(
                    started,
                    started_clock=started_clock,
                    response=last_response,
                    attempt_number=attempt,
                    failure_layer=AnalystFailureLayer.FORMAT,
                    failure_category=AnalystFailureCategory.OTHER,
                    failure_path="$",
                    parse_status=AttemptCheckStatus.PASSED,
                    schema_status=AttemptCheckStatus.FAILED,
                    evidence_status=AttemptCheckStatus.NOT_CHECKED,
                )
                continue
            report, evidence_normalizations = normalize_report(report, records)
            normalizations = tuple(sorted({*raw_normalizations, *evidence_normalizations}))
            errors = validate_report(report, role=role, evidence=records)
            if errors:
                category, failure_path = _diagnose_report_errors(errors)
                self._finish_rejected_attempt(
                    started,
                    started_clock=started_clock,
                    response=last_response,
                    attempt_number=attempt,
                    failure_layer=AnalystFailureLayer.CONTENT_EVIDENCE,
                    failure_category=category,
                    failure_path=failure_path,
                    parse_status=AttemptCheckStatus.PASSED,
                    schema_status=AttemptCheckStatus.PASSED,
                    evidence_status=AttemptCheckStatus.FAILED,
                )
                continue
            self._finish_attempt(
                started,
                started_clock=started_clock,
                response=last_response,
                parse_status=AttemptCheckStatus.PASSED,
                schema_status=AttemptCheckStatus.PASSED,
                evidence_status=AttemptCheckStatus.PASSED,
                failure_layer=AnalystFailureLayer.NONE,
                failure_category=None,
                failure_path=None,
                retry_scope=AnalystRetryScope.NONE,
                outcome=AnalystAttemptOutcome.ACCEPTED,
                terminal_disposition=AnalystTerminalDisposition.ACCEPTED,
            )
            return ValidatedAnalysis(
                report=report,
                audit=AnalysisAudit(
                    provider_name=last_response.provider_name,
                    model_name=last_response.model_name,
                    model_digest=last_response.model_digest,
                    prompt_version=PROMPT_VERSION,
                    validation_version=VALIDATION_VERSION,
                    knowledge_cutoff_at=cutoff,
                    completed_at=datetime.now(UTC),
                    attempts=attempt,
                    evidence_ids=tuple(item.evidence_id for item in records),
                    evidence_hashes=tuple(item.content_sha256 for item in records),
                    normalizations=normalizations,
                ),
            )
        assert last_response is not None
        raise AnalysisRejected(errors or ("unknown_validation_failure",), self._maximum_attempts)

    def _start_attempt(
        self,
        *,
        invocation_id: UUID,
        attempt_number: int,
        role: AnalystRole,
        records: Sequence[AnalystEvidence],
        request: ModelRequest,
        work_context: AnalystWorkContext | None,
    ) -> AnalystAttemptStart | None:
        if self._attempt_sink is None:
            return None
        assert work_context is not None
        assert self._configured_provider_name is not None
        assert self._configured_model_name is not None
        assert self._configured_model_digest is not None
        started = AnalystAttemptStart(
            attempt_id=uuid4(),
            invocation_id=invocation_id,
            context=work_context,
            provider_name=self._configured_provider_name,
            model_name=self._configured_model_name,
            model_digest=self._configured_model_digest,
            role=role,
            attempt_number=attempt_number,
            started_at=self._utc_now(),
            input_evidence_count=len(records),
            input_evidence_characters=sum(len(item.text) for item in records),
            system_prompt_characters=len(request.system_prompt),
            user_prompt_characters=len(request.user_prompt),
            context_tokens=request.context_tokens,
            maximum_output_tokens=request.maximum_output_tokens,
        )
        self._attempt_sink.start_analyst_attempt(started)
        return started

    def _finish_rejected_attempt(
        self,
        started: AnalystAttemptStart | None,
        *,
        started_clock: float,
        response: ModelResponse,
        attempt_number: int,
        failure_layer: AnalystFailureLayer,
        failure_category: AnalystFailureCategory,
        failure_path: str,
        parse_status: AttemptCheckStatus,
        schema_status: AttemptCheckStatus,
        evidence_status: AttemptCheckStatus,
    ) -> None:
        retry_eligible = attempt_number < self._maximum_attempts
        self._finish_attempt(
            started,
            started_clock=started_clock,
            response=response,
            parse_status=parse_status,
            schema_status=schema_status,
            evidence_status=evidence_status,
            failure_layer=failure_layer,
            failure_category=failure_category,
            failure_path=failure_path,
            retry_scope=(AnalystRetryScope.PIPELINE if retry_eligible else AnalystRetryScope.NONE),
            outcome=AnalystAttemptOutcome.REJECTED,
            terminal_disposition=(
                AnalystTerminalDisposition.RETRY_PENDING
                if retry_eligible
                else AnalystTerminalDisposition.REJECTED
            ),
        )

    def _finish_attempt(
        self,
        started: AnalystAttemptStart | None,
        *,
        started_clock: float,
        response: ModelResponse | None,
        parse_status: AttemptCheckStatus,
        schema_status: AttemptCheckStatus,
        evidence_status: AttemptCheckStatus,
        failure_layer: AnalystFailureLayer,
        failure_category: AnalystFailureCategory | None,
        failure_path: str | None,
        retry_scope: AnalystRetryScope,
        outcome: AnalystAttemptOutcome,
        terminal_disposition: AnalystTerminalDisposition,
    ) -> None:
        if started is None:
            return
        assert self._attempt_sink is not None
        content = response.content if response is not None else None
        receipt = AnalystAttemptReceipt(
            start=started,
            completed_at=self._utc_now(),
            latency_ms=max(0, round((self._monotonic() - started_clock) * 1_000)),
            response_sha256=(sha256(content.encode("utf-8")).hexdigest() if content else None),
            response_characters=len(content) if content is not None else None,
            response_bytes=len(content.encode("utf-8")) if content is not None else None,
            prompt_tokens=response.prompt_tokens if response is not None else None,
            generated_tokens=response.generated_tokens if response is not None else None,
            parse_status=parse_status,
            schema_status=schema_status,
            evidence_status=evidence_status,
            failure_layer=failure_layer,
            failure_category=failure_category,
            failure_path=failure_path,
            retry_eligible=retry_scope is not AnalystRetryScope.NONE,
            retry_scope=retry_scope,
            outcome=outcome,
            terminal_disposition=terminal_disposition,
        )
        self._attempt_sink.finish_analyst_attempt(receipt)

    def _utc_now(self) -> datetime:
        observed = self._now()
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("analyst attempt clock must be timezone-aware")
        return observed.astimezone(UTC)


def _classify_validation_errors(error: ValidationError) -> tuple[str, ...]:
    """Map untrusted model validation failures to bounded diagnostic categories."""

    categories: set[str] = set()
    for item in error.errors(include_url=False):
        error_type = str(item.get("type", ""))
        location = item.get("loc", ())
        path = ".".join(str(part) for part in location)
        if error_type in {"literal_error", "enum"}:
            categories.add("invalid_enum")
        elif error_type in {"string_type", "int_type", "float_type", "list_type", "dict_type"}:
            categories.add("invalid_type")
        elif "missing" in error_type:
            categories.add("missing_required_field")
        elif path:
            categories.add("schema_validation")
        else:
            categories.add("schema_validation")
    return tuple(sorted(categories or {"schema_validation"}))


def _classify_json_failure(content: str) -> AnalystFailureCategory:
    """Distinguish surrounding prose without accepting or repairing it."""

    decoder = json.JSONDecoder()
    for index, character in enumerate(content):
        if character not in "[{":
            continue
        try:
            value, end = decoder.raw_decode(content, index)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and (content[:index].strip() or content[end:].strip()):
            return AnalystFailureCategory.EXTRA_PROSE
    return AnalystFailureCategory.MALFORMED_JSON


def _diagnose_validation_errors(
    error: ValidationError,
) -> tuple[AnalystFailureCategory, str]:
    """Return one stable category/path while retaining detailed codes in exceptions."""

    diagnosed: list[tuple[int, AnalystFailureCategory, str]] = []
    priority = {
        AnalystFailureCategory.MISSING_REQUIRED_FIELD: 0,
        AnalystFailureCategory.INVALID_TYPE: 1,
        AnalystFailureCategory.INVALID_ENUM: 2,
        AnalystFailureCategory.OTHER: 3,
    }
    for item in error.errors(include_url=False):
        error_type = str(item.get("type", ""))
        location = item.get("loc", ())
        path = "$" + "".join(
            f"[{part}]" if isinstance(part, int) else f".{part}" for part in location
        )
        if "missing" in error_type:
            category = AnalystFailureCategory.MISSING_REQUIRED_FIELD
        elif error_type in {
            "string_type",
            "int_type",
            "float_type",
            "list_type",
            "dict_type",
            "bool_type",
            "uuid_type",
        }:
            category = AnalystFailureCategory.INVALID_TYPE
        elif error_type in {"literal_error", "enum"}:
            category = AnalystFailureCategory.INVALID_ENUM
        else:
            category = AnalystFailureCategory.OTHER
        diagnosed.append((priority[category], category, path[:255]))
    if not diagnosed:
        return AnalystFailureCategory.OTHER, "$"
    _, category, path = min(diagnosed, key=lambda item: (item[0], item[2]))
    return category, path


def _diagnose_report_errors(
    errors: Sequence[str],
) -> tuple[AnalystFailureCategory, str]:
    mappings: tuple[tuple[frozenset[str], AnalystFailureCategory, str], ...] = (
        (
            frozenset({"unknown_evidence_id"}),
            AnalystFailureCategory.INVALID_EVIDENCE_ID,
            "$.findings.citations.evidence_id",
        ),
        (
            frozenset({"unsupported_numeric_token"}),
            AnalystFailureCategory.NUMERIC_CONFLICT,
            "$.findings.statement",
        ),
        (
            frozenset(
                {
                    "correction_not_explicit_or_later",
                    "explicit_correction_not_resolved",
                    "conflict_without_contradiction",
                }
            ),
            AnalystFailureCategory.PROVENANCE_FAILURE,
            "$.contradictions",
        ),
        (
            frozenset(
                {
                    "prompt_version_mismatch",
                    "role_mismatch",
                    "category_not_allowed_for_role",
                    "reported_fact_must_be_neutral",
                    "document_interpreter_must_report_neutral_facts",
                }
            ),
            AnalystFailureCategory.INVALID_ENUM,
            "$.role",
        ),
        (
            frozenset(
                {
                    "quote_not_verbatim",
                    "reported_fact_not_verbatim",
                    "inference_lexically_ungrounded",
                    "unsupported_url",
                }
            ),
            AnalystFailureCategory.UNSUPPORTED_CLAIM,
            "$.findings",
        ),
    )
    error_set = frozenset(errors)
    for candidates, category, path in mappings:
        if error_set & candidates:
            return category, path
    return AnalystFailureCategory.OTHER, "$"


def _classify_runtime_failure(error: Exception) -> AnalystFailureCategory:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, TimeoutError) or "timeout" in type(current).__name__.casefold():
            return AnalystFailureCategory.TIMEOUT
        current = current.__cause__ or current.__context__
    label = f"{type(error).__name__} {error}".casefold()
    if "refusal" in label or "refused" in label:
        return AnalystFailureCategory.REFUSAL
    return AnalystFailureCategory.PROVIDER_ERROR


def detect_prompt_injection(text: str) -> tuple[str, ...]:
    """Conservative high-confidence scanner; one defense layer, not a proof of safety."""

    return tuple(
        f"pattern_{index}"
        for index, pattern in enumerate(_INJECTION_PATTERNS, start=1)
        if pattern.search(text)
    )


def validate_report(
    report: AnalystReport,
    *,
    role: AnalystRole,
    evidence: Sequence[AnalystEvidence],
) -> tuple[str, ...]:
    errors: set[str] = set()
    if report.prompt_version != PROMPT_VERSION:
        errors.add("prompt_version_mismatch")
    if report.role is not role:
        errors.add("role_mismatch")
    records = {item.evidence_id: item for item in evidence}
    allowed_categories = _ROLE_CATEGORIES[role]
    for finding in report.findings:
        if finding.category not in allowed_categories:
            errors.add("category_not_allowed_for_role")
        if (
            finding.kind is FindingKind.REPORTED_FACT
            and finding.polarity is not FindingPolarity.NEUTRAL
        ):
            errors.add("reported_fact_must_be_neutral")
        if role is AnalystRole.DOCUMENT_INTERPRETER and (
            finding.kind is not FindingKind.REPORTED_FACT
            or finding.polarity is not FindingPolarity.NEUTRAL
        ):
            errors.add("document_interpreter_must_report_neutral_facts")
        cited_quotes = _validate_citations(finding.citations, records, errors)
        if finding.kind is FindingKind.REPORTED_FACT and not any(
            _normalize_text(finding.statement) == _normalize_text(quote) for quote in cited_quotes
        ):
            errors.add("reported_fact_not_verbatim")
        if finding.kind is FindingKind.ANALYST_INFERENCE:
            _validate_inference_grounding(finding.statement, cited_quotes, errors)
        _validate_tokens(finding.statement, cited_quotes, errors)
    for contradiction in report.contradictions:
        cited_quotes = _validate_citations(contradiction.citations, records, errors)
        _validate_tokens(contradiction.topic, cited_quotes, errors)
        explicit_correction = _has_explicit_later_correction(contradiction.citations, records)
        if (
            contradiction.status is ContradictionStatus.RESOLVED_BY_LATER_CORRECTION
            and not explicit_correction
        ):
            errors.add("correction_not_explicit_or_later")
        if (
            contradiction.status is not ContradictionStatus.RESOLVED_BY_LATER_CORRECTION
            and explicit_correction
        ):
            errors.add("explicit_correction_not_resolved")
    if report.assessment is Assessment.CONFLICTING_EVIDENCE and not report.contradictions:
        errors.add("conflict_without_contradiction")
    return tuple(sorted(errors))


def normalize_report(
    report: AnalystReport, evidence: Sequence[AnalystEvidence]
) -> tuple[AnalystReport, tuple[str, ...]]:
    """Apply only deterministic, evidence-provable normalization to model output."""

    records = {item.evidence_id: item for item in evidence}
    changed = False
    contradictions = []
    for contradiction in report.contradictions:
        if (
            contradiction.status is not ContradictionStatus.RESOLVED_BY_LATER_CORRECTION
            and _has_explicit_later_correction(contradiction.citations, records)
        ):
            contradiction = contradiction.model_copy(
                update={"status": ContradictionStatus.RESOLVED_BY_LATER_CORRECTION}
            )
            changed = True
        contradictions.append(contradiction)
    if not changed:
        return report, ()
    return (
        report.model_copy(update={"contradictions": tuple(contradictions)}),
        ("explicit_later_correction_status",),
    )


def normalize_raw_report(value: object) -> tuple[object, tuple[str, ...]]:
    """Normalize only output-shape fields whose correct value is structurally provable."""

    if not isinstance(value, dict):
        return value, ()
    payload = dict(value)
    changes: set[str] = set()
    findings = payload.get("findings")
    if isinstance(findings, list):
        normalized_findings: list[object] = []
        for finding in findings:
            if isinstance(finding, dict):
                finding = dict(finding)
                if (
                    finding.get("kind") == FindingKind.REPORTED_FACT.value
                    and finding.get("polarity") != FindingPolarity.NEUTRAL.value
                ):
                    finding["polarity"] = FindingPolarity.NEUTRAL.value
                    changes.add("reported_fact_neutral_polarity")
            normalized_findings.append(finding)
        payload["findings"] = normalized_findings
    contradictions = payload.get("contradictions")
    if (
        isinstance(contradictions, list)
        and contradictions
        and payload.get("assessment") != Assessment.CONFLICTING_EVIDENCE.value
    ):
        payload["assessment"] = Assessment.CONFLICTING_EVIDENCE.value
        changes.add("contradiction_assessment")
    return payload, tuple(sorted(changes))


def _validate_evidence(
    evidence: Sequence[AnalystEvidence], cutoff: datetime
) -> tuple[AnalystEvidence, ...]:
    records = tuple(evidence)
    if not records or len(records) > MAXIMUM_EVIDENCE_RECORDS:
        raise ValueError("analysis requires one to eight evidence records")
    if sum(len(item.text) for item in records) > MAXIMUM_EVIDENCE_CHARACTERS:
        raise ValueError("analysis evidence exceeds the bounded context size")
    ids = tuple(item.evidence_id for item in records)
    if len(set(ids)) != len(ids):
        raise ValueError("analysis evidence IDs must be unique")
    for item in records:
        if item.available_at > cutoff or item.retrieved_at > cutoff:
            raise ValueError("analysis evidence was unavailable or unretrieved at the cutoff")
        injection_matches = detect_prompt_injection(item.text)
        if injection_matches:
            raise UnsafeEvidenceError(
                f"evidence {item.evidence_id} quarantined for prompt-injection indicators"
            )
    return records


def _validate_citations(
    citations: Sequence[EvidenceCitation],
    records: Mapping[UUID, AnalystEvidence],
    errors: set[str],
) -> tuple[str, ...]:
    quotes: list[str] = []
    for citation in citations:
        record = records.get(citation.evidence_id)
        if record is None:
            errors.add("unknown_evidence_id")
            continue
        if citation.quote not in record.text:
            errors.add("quote_not_verbatim")
            continue
        quotes.append(citation.quote)
    return tuple(quotes)


def _validate_tokens(statement: str, cited_quotes: Sequence[str], errors: set[str]) -> None:
    support = " ".join(cited_quotes)
    for number in _NUMBER_PATTERN.findall(statement):
        if number not in support:
            errors.add("unsupported_numeric_token")
    for url in _URL_PATTERN.findall(statement):
        if url not in support:
            errors.add("unsupported_url")


def _validate_inference_grounding(
    statement: str, cited_quotes: Sequence[str], errors: set[str]
) -> None:
    statement_words = {
        word.casefold()
        for word in _WORD_PATTERN.findall(statement)
        if word.casefold() not in _GROUNDING_STOP_WORDS
    }
    support_words = {
        word.casefold() for quote in cited_quotes for word in _WORD_PATTERN.findall(quote)
    }
    overlap = statement_words & support_words
    required = max(2, (len(statement_words) + 3) // 4)
    if len(overlap) < required:
        errors.add("inference_lexically_ungrounded")


def _has_explicit_later_correction(
    citations: Sequence[EvidenceCitation], records: Mapping[UUID, AnalystEvidence]
) -> bool:
    cited = [
        (citation, records[citation.evidence_id])
        for citation in citations
        if citation.evidence_id in records and citation.quote in records[citation.evidence_id].text
    ]
    if len({record.available_at for _, record in cited}) < 2:
        return False
    latest_available = max(record.available_at for _, record in cited)
    latest_quote = " ".join(
        citation.quote for citation, record in cited if record.available_at == latest_available
    )
    return bool(
        re.search(r"\b(correct|corrected|correction|revised|supersed)\w*\b", latest_quote, re.I)
    )


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).casefold()
