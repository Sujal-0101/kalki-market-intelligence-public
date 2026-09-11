"""Structured verifier execution followed by deterministic semantic arbitration."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from kalki_market_intelligence.analysis.contracts import ModelRequest, ModelResponse
from kalki_market_intelligence.analysis.provider import ModelProvider
from kalki_market_intelligence.verification.contracts import (
    ArbitrationResult,
    ChallengeCategory,
    ClassificationSupport,
    VerifierAudit,
    VerifierPackage,
    VerifierReport,
    verifier_generation_schema,
)
from kalki_market_intelligence.verification.prompts import (
    VERIFIER_SYSTEM_PROMPT_V1,
    build_verifier_prompt,
)

MAXIMUM_VERIFIER_ATTEMPTS = 2
VERIFIER_MAXIMUM_OUTPUT_TOKENS = 512


class VerificationRejected(ValueError):
    """No bounded verifier response passed schema/reference validation."""

    def __init__(self, error_codes: Sequence[str], attempts: int) -> None:
        self.error_codes = tuple(sorted(set(error_codes)))
        self.attempts = attempts
        super().__init__(
            f"verification rejected after {attempts} attempt(s): " + ", ".join(self.error_codes)
        )


class VerifierPipeline:
    def __init__(
        self,
        provider: ModelProvider,
        *,
        maximum_attempts: int = MAXIMUM_VERIFIER_ATTEMPTS,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if maximum_attempts < 1 or maximum_attempts > MAXIMUM_VERIFIER_ATTEMPTS:
            raise ValueError("verifier attempts must be between one and two")
        self._provider = provider
        self._maximum_attempts = maximum_attempts
        self._now = now or (lambda: datetime.now(UTC))

    def verify(self, package: VerifierPackage, *, review_number: int) -> VerifierAudit:
        if review_number not in {1, 2}:
            raise ValueError("review number must be one or two")
        errors: tuple[str, ...] = ()
        last_response: ModelResponse | None = None
        for attempt in range(1, self._maximum_attempts + 1):
            request = ModelRequest(
                system_prompt=VERIFIER_SYSTEM_PROMPT_V1,
                user_prompt=build_verifier_prompt(package, repair_errors=errors),
                output_schema=verifier_generation_schema(),
                # The package is deliberately bounded; 4K covers facts, excerpts,
                # definitions, candidate, and the small JSON response without
                # reserving unnecessary KV memory on the production host.
                context_tokens=4_096,
                maximum_output_tokens=VERIFIER_MAXIMUM_OUTPUT_TOKENS,
            )
            last_response = self._provider.generate(request)
            try:
                report = VerifierReport.model_validate_json(last_response.content)
            except (ValidationError, ValueError):
                errors = ("schema_validation",)
                continue
            errors = validate_verifier_report(report, package)
            if errors:
                continue
            if last_response.model_digest is None:
                errors = ("model_digest_missing",)
                continue
            completed_at = self._now().astimezone(UTC)
            report_fingerprint = sha256(report.model_dump_json().encode("utf-8")).hexdigest()
            return VerifierAudit(
                review_id=uuid5(
                    NAMESPACE_URL,
                    f"kalki-verifier:{package.candidate.candidate_id}:{review_number}:"
                    f"{report_fingerprint}",
                ),
                candidate_id=package.candidate.candidate_id,
                review_number=review_number,
                provider_name=last_response.provider_name,
                model_name=last_response.model_name,
                model_digest=last_response.model_digest,
                completed_at=completed_at,
                attempts=attempt,
                evidence_ids=tuple(item.evidence_id for item in package.evidence),
                report=report,
                deterministic_refutations=(),
            )
        assert last_response is not None
        raise VerificationRejected(
            errors or ("unknown_validation_failure",), self._maximum_attempts
        )


def validate_verifier_report(
    report: VerifierReport,
    package: VerifierPackage,
) -> tuple[str, ...]:
    errors: set[str] = set()
    evidence_ids = {item.evidence_id for item in package.evidence}
    claim_ids = {item.claim_id for item in package.candidate.claims}
    if not set(report.unsupported_claim_ids).issubset(claim_ids):
        errors.add("unknown_claim_id")
    referenced_evidence = {
        *report.missing_material_risk_evidence_ids,
        *report.missing_material_catalyst_evidence_ids,
        *(item.evidence_id for item in report.numeric_concerns),
    }
    if not referenced_evidence.issubset(evidence_ids):
        errors.add("unknown_evidence_id")
    if any(item.claim_id not in claim_ids for item in report.numeric_concerns):
        errors.add("unknown_numeric_claim_id")
    return tuple(sorted(errors))


def arbitrate_verifier_report(
    package: VerifierPackage,
    report: VerifierReport,
) -> ArbitrationResult:
    """Let provable facts outrank both models; retain genuinely semantic concerns."""

    challenges = set(report.challenge_categories)
    relevant_evidence = {
        *report.missing_material_risk_evidence_ids,
        *report.missing_material_catalyst_evidence_ids,
    }
    relevant_claims = set(report.unsupported_claim_ids)
    refutations: set[str] = set()

    if report.identity_concern:
        # SEC identity fields are authoritative, but their presence alone cannot prove
        # that every candidate claim refers to that issuer. Retain the semantic concern
        # unless a future version adds a specific deterministic mismatch check.
        challenges.add(ChallengeCategory.IDENTITY_CONCERN)
        relevant_evidence.update(item.evidence_id for item in package.evidence)
        relevant_claims.update(item.claim_id for item in package.candidate.claims)
    else:
        challenges.discard(ChallengeCategory.IDENTITY_CONCERN)

    unresolved_numeric = False
    claims = {item.claim_id: item for item in package.candidate.claims}
    evidence = {item.evidence_id: item for item in package.evidence}
    for concern in report.numeric_concerns:
        claim = claims[concern.claim_id]
        source = evidence[concern.evidence_id]
        relevant_evidence.add(concern.evidence_id)
        relevant_claims.add(concern.claim_id)
        if (
            concern.evidence_id in claim.evidence_ids
            and _contains_numeric_token(claim.statement, concern.numeric_token)
            and _contains_numeric_token(source.text, concern.numeric_token)
        ):
            refutations.add(f"numeric_match_refuted:{concern.claim_id}")
        else:
            unresolved_numeric = True
    if unresolved_numeric:
        challenges.add(ChallengeCategory.NUMERIC_CONCERN)
    else:
        challenges.discard(ChallengeCategory.NUMERIC_CONCERN)

    if report.unsupported_claim_ids:
        challenges.add(ChallengeCategory.UNSUPPORTED_INTERPRETATION)
        for claim_id in report.unsupported_claim_ids:
            relevant_evidence.update(claims[claim_id].evidence_ids)
    if report.missing_material_risk_evidence_ids:
        challenges.add(ChallengeCategory.MISSING_MATERIAL_RISK)
    if report.missing_material_catalyst_evidence_ids:
        challenges.add(ChallengeCategory.MISSING_MATERIAL_CATALYST)
    if report.material_omissions:
        challenges.add(ChallengeCategory.MISSING_COUNTEREVIDENCE)
    if report.uncertainty_concern:
        challenges.add(ChallengeCategory.UNCERTAINTY_OVERSTATED)
    if report.classification_support is ClassificationSupport.TOO_BULLISH:
        challenges.add(ChallengeCategory.CLASSIFICATION_TOO_BULLISH)
    elif report.classification_support is ClassificationSupport.TOO_BEARISH:
        challenges.add(ChallengeCategory.CLASSIFICATION_TOO_BEARISH)
    elif report.classification_support is ClassificationSupport.INSUFFICIENT:
        challenges.add(ChallengeCategory.UNSUPPORTED_INTERPRETATION)

    if challenges and not relevant_evidence:
        relevant_evidence.update(item.evidence_id for item in package.evidence)
    ordered_challenges = tuple(sorted(challenges, key=str))
    return ArbitrationResult(
        approved=not ordered_challenges,
        material_challenges=ordered_challenges,
        relevant_evidence_ids=tuple(sorted(relevant_evidence, key=str)),
        relevant_claim_ids=tuple(sorted(relevant_claims)),
        deterministic_refutations=tuple(sorted(refutations)),
    )


def with_refutations(audit: VerifierAudit, result: ArbitrationResult) -> VerifierAudit:
    return audit.model_copy(update={"deterministic_refutations": result.deterministic_refutations})


def _contains_numeric_token(text: str, token: str) -> bool:
    normalized_text = re.sub(r"(?<=\d),(?=\d)", "", text)
    normalized_token = token.replace(",", "")
    pattern = rf"(?<![A-Za-z0-9_]){re.escape(normalized_token)}(?![A-Za-z0-9_])"
    return re.search(pattern, normalized_text) is not None
