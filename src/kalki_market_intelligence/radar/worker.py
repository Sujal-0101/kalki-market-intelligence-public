"""Supervised filing-radar loop connecting discovery, local AI, storage, and Discord."""

from __future__ import annotations

import re
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import HttpUrl

from kalki_market_intelligence.analysis.attempts import (
    AnalystAttemptOrigin,
    AnalystAttemptReceipt,
    AnalystWorkContext,
)
from kalki_market_intelligence.analysis.ollama import ModelProviderError, OllamaModelProvider
from kalki_market_intelligence.analysis.pipeline import AnalysisRejected, AnalystPipeline
from kalki_market_intelligence.config import Settings
from kalki_market_intelligence.contracts.evidence import SourceClass
from kalki_market_intelligence.database import DatabaseOptions, DatabaseRuntime
from kalki_market_intelligence.forensics import (
    EventNoveltyDisposition,
    EventSourceReceipt,
    ForensicInput,
    ForensicSignal,
    TierDecision,
    assess_forensics,
    choose_tier,
    classify_event_novelty,
    extract_strategic_partnership_disclosure,
    xbrl_liquidity_convergence_decision,
)
from kalki_market_intelligence.forensics.contradiction_store import PostgresContradictionStore
from kalki_market_intelligence.forensics.convergence_service import ConvergenceValidationService
from kalki_market_intelligence.notifications.discord import DiscordNotifier
from kalki_market_intelligence.notifications.templates import RadarNotification
from kalki_market_intelligence.providers.sec.client import SecFetchedDocument
from kalki_market_intelligence.providers.sec.contracts import SecFactRecord
from kalki_market_intelligence.providers.sec.normalization import normalize_companyfacts
from kalki_market_intelligence.radar.contracts import (
    FilingCandidate,
    RadarRun,
    RunState,
    WorkerSnapshot,
    WorkerState,
)
from kalki_market_intelligence.radar.extraction import (
    ExtractedFiling,
    exclude_exact_event_evidence,
    extract_research_excerpt,
)
from kalki_market_intelligence.radar.research import (
    analyze_filing,
    build_reconsideration,
    build_research_brief,
    build_verifier_package,
    finalize_deterministically_validated_brief,
    finalize_verified_brief,
)
from kalki_market_intelligence.radar.screening import (
    AutonomousScreeningDecision,
    ScreeningDisposition,
    ScreeningReason,
)
from kalki_market_intelligence.radar.sec_links import (
    ValidatedSecFilingLinks,
    public_sec_filing_links,
    validate_sec_filing_links,
)
from kalki_market_intelligence.radar.sec_source import (
    SecRadarClient,
    SecRadarDocument,
    latest_submission_candidate,
    parse_master_index,
    parse_ticker_mapping,
)
from kalki_market_intelligence.radar.store import PostgresRadarStore
from kalki_market_intelligence.radar.telemetry import (
    PipelineEvent,
    PipelineFailureCategory,
    PipelineStage,
)
from kalki_market_intelligence.research.intake import HumanLeadStatus, HumanResearchLead
from kalki_market_intelligence.research.results import (
    HumanAssessmentStatus,
    HumanDeterministicVerificationReceipt,
    HumanFilingDiffReceipt,
    HumanResearchDisposition,
    HumanResearchResult,
    HumanSecSourceReceipt,
    HumanSourceStatus,
    HumanXbrlReceipt,
)
from kalki_market_intelligence.verification.contracts import (
    CandidateDossier,
    ChallengeCategory,
    VerificationDisposition,
    VerificationOutcome,
    VerifierAudit,
    VerifierPackage,
)
from kalki_market_intelligence.verification.pipeline import (
    VerificationRejected,
    VerifierPipeline,
    arbitrate_verifier_report,
    with_refutations,
)


class VerifierUnavailableError(RuntimeError):
    """Publication verification is disabled, so the candidate must fail closed."""


class FilingRadarWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        store: PostgresRadarStore,
        convergence_service: ConvergenceValidationService | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._convergence_service = convergence_service
        self._now = now or (lambda: datetime.now(UTC))
        self._analyst_provider = OllamaModelProvider(
            model=settings.worker_model,
            base_url=settings.ollama_base_url,
            timeout_seconds=300,
            expected_digest=settings.worker_model_digest,
        )
        self._pipeline = AnalystPipeline(
            self._analyst_provider,
            attempt_sink=store,
            configured_provider_name="ollama-loopback",
            configured_model_name=settings.worker_model,
            configured_model_digest=settings.worker_model_digest,
            now=self._utc_now,
        )
        self._verifier_provider = OllamaModelProvider(
            model=settings.worker_verifier_model,
            base_url=settings.ollama_base_url,
            timeout_seconds=900,
            expected_digest=settings.worker_verifier_model_digest,
        )
        self._verifier = VerifierPipeline(self._verifier_provider, now=self._utc_now)
        webhook = (
            settings.discord_webhook_url.get_secret_value()
            if settings.discord_webhook_url is not None
            else None
        )
        self._notifier = DiscordNotifier(
            enabled=settings.discord_enabled,
            webhook_url=webhook,
            requests_per_second=settings.discord_requests_per_second,
            timeout_seconds=settings.discord_timeout_seconds,
            maximum_response_bytes=settings.discord_maximum_response_bytes,
            maximum_attempts=settings.discord_maximum_attempts,
            public_hostname=settings.web_public_hostname,
        )

    def run_once(self) -> int:
        """Complete one bounded cycle and return the next sleep interval."""

        started = self._utc_now()
        run_id = uuid4()
        if self._settings.sec_user_agent is None:
            self._snapshot(
                state=WorkerState.WAITING_FOR_CONFIGURATION,
                now=started,
                next_run=started + timedelta(seconds=self._settings.worker_poll_seconds),
                error_code="sec_user_agent_missing",
                success=False,
            )
            return self._settings.worker_poll_seconds

        self._store.append_pipeline_event(
            PipelineEvent(
                event_id=uuid4(),
                occurred_at=started,
                stage=PipelineStage.SEC_POLL_ATTEMPTED,
                run_id=run_id,
            )
        )

        discovered = analyzed = published = skipped = 0
        error_code: str | None = None
        run_state = RunState.COMPLETED
        self._snapshot(
            state=WorkerState.RUNNING,
            now=started,
            next_run=started + timedelta(seconds=self._settings.worker_poll_seconds),
            error_code=None,
            success=False,
        )
        try:
            client = SecRadarClient(
                user_agent=self._settings.sec_user_agent,
                requests_per_second=self._settings.sec_requests_per_second,
                timeout_seconds=self._settings.sec_timeout_seconds,
                maximum_response_bytes=self._settings.sec_maximum_response_bytes,
            )
            mapping = parse_ticker_mapping(client.ticker_mapping())
            index = client.latest_master_index(started.date())
            candidates = parse_master_index(index, mapping)
            discovered = self._store.discover(candidates)
            self._store.requeue_stale_processing(now=self._utc_now(), run_id=run_id)
            self._snapshot(
                state=WorkerState.RUNNING,
                now=self._utc_now(),
                next_run=started + timedelta(seconds=self._settings.worker_poll_seconds),
                error_code=None,
                success=False,
            )
            for _ in range(self._settings.worker_batch_size):
                claimed = self._store.claim(now=self._utc_now(), run_id=run_id)
                if claimed is None:
                    break
                candidate = claimed.candidate
                attempt = claimed.attempts
                candidate_failure_category: PipelineFailureCategory = "sec_retrieval"
                source_document_sha256: str | None = None
                try:
                    document = client.filing(candidate.source_url)
                    source_document_sha256 = document.content_sha256
                    self._record_candidate_stage(
                        run_id, candidate.accession_number, PipelineStage.CANDIDATE_RETRIEVED
                    )
                    candidate_failure_category = "filing_parse"
                    extracted = extract_research_excerpt(document.body)
                    self._record_candidate_stage(
                        run_id, candidate.accession_number, PipelineStage.CANDIDATE_PARSED
                    )
                    candidate_failure_category = "deterministic_processing"
                    extracted = self._apply_event_novelty(candidate, document, extracted)
                    tier_decision = choose_tier(
                        research_relevant=extracted.is_research_relevant and bool(extracted.text),
                        material_terms=bool(extracted.opportunity_terms or extracted.risk_terms),
                        context_chars=len(extracted.text),
                        evidence_ids=(
                            uuid5(NAMESPACE_URL, f"sec-routing:{candidate.accession_number}"),
                        ),
                        forensic_signals=assess_forensics(
                            ForensicInput(
                                text=extracted.text[:255],
                                evidence_ids=(
                                    uuid5(
                                        NAMESPACE_URL,
                                        f"sec-routing:{candidate.accession_number}",
                                    ),
                                ),
                            )
                        ),
                    )
                    self._store.record_tier_decision(
                        candidate.accession_number,
                        tier_decision,
                        now=self._utc_now(),
                        run_id=run_id,
                    )
                    if not tier_decision.requires_model:
                        if claimed.reconsideration is not None:
                            assert claimed.first_audit is not None
                            original_candidate = CandidateDossier.model_validate_json(
                                claimed.reconsideration.original_candidate_json
                            )
                            outcome = self._verification_outcome(
                                candidate_id=original_candidate.candidate_id,
                                accession_number=candidate.accession_number,
                                disposition=VerificationDisposition.ANALYST_RETRY_REJECTED,
                                retry_count=1,
                                audits=(claimed.first_audit,),
                                analyst_model_name=original_candidate.analyst_model_name,
                                analyst_model_digest=original_candidate.analyst_model_digest,
                                challenge_categories=tuple(
                                    ChallengeCategory(item)
                                    for item in claimed.reconsideration.challenge_categories
                                ),
                                evidence_ids=claimed.reconsideration.relevant_evidence_ids,
                            )
                            candidate_failure_category = "persistence"
                            decision = self._screening_decision(
                                candidate=candidate,
                                work_attempt=attempt,
                                run_id=run_id,
                                decided_at=outcome.decided_at,
                                disposition=ScreeningDisposition.SCREENED_OUT,
                                reason=ScreeningReason.DETERMINISTIC_QUALIFICATION_NOT_MET,
                                source_document_sha256=source_document_sha256,
                            )
                            self._store.record_verification_outcome(
                                outcome, brief=None, decision=decision
                            )
                            self._store.increment_counter(
                                "deterministic_rejections", now=self._utc_now()
                            )
                            skipped += 1
                            continue
                        decided_at = self._utc_now()
                        self._store.complete_candidate(
                            candidate.accession_number,
                            status="skipped",
                            now=decided_at,
                            run_id=run_id,
                            decision=self._screening_decision(
                                candidate=candidate,
                                work_attempt=attempt,
                                run_id=run_id,
                                decided_at=decided_at,
                                disposition=ScreeningDisposition.SCREENED_OUT,
                                reason=ScreeningReason.DETERMINISTIC_QUALIFICATION_NOT_MET,
                                source_document_sha256=source_document_sha256,
                            ),
                        )
                        skipped += 1
                        continue
                    candidate_failure_category = "sec_retrieval"
                    facts_document = client.companyfacts(candidate.cik)
                    candidate_failure_category = "companyfacts_normalization"
                    facts = normalize_companyfacts(
                        SecFetchedDocument(
                            endpoint="companyfacts",
                            # Daily-master-index candidates may carry an
                            # unpadded numeric CIK; SEC CompanyFacts always
                            # returns the canonical ten-digit form.
                            cik=candidate.cik.zfill(10),
                            url=facts_document.url,
                            status_code=200,
                            headers={"content-type": facts_document.media_type},
                            body=facts_document.body,
                            content_sha256=facts_document.content_sha256,
                            retrieved_at=facts_document.retrieved_at,
                        )
                    )
                    self._record_candidate_stage(
                        run_id,
                        candidate.accession_number,
                        PipelineStage.COMPANYFACTS_NORMALIZED,
                    )
                    candidate_failure_category = "deterministic_processing"
                    convergence_service = getattr(self, "_convergence_service", None)
                    if convergence_service is not None:
                        producer = xbrl_liquidity_convergence_decision(
                            facts,
                            issuer_cik=candidate.cik.zfill(10),
                            accession_number=candidate.accession_number,
                            filing_form=candidate.filing_form,
                            knowledge_cutoff_at=self._utc_now(),
                        )
                        for request in producer.requests:
                            convergence_service.evaluate_and_persist(request)
                    if claimed.reconsideration is None:
                        candidate_failure_category = "analyst"
                        evidence, analyses = analyze_filing(
                            self._pipeline,
                            candidate=candidate,
                            document=document,
                            extracted=extracted,
                            work_context=self._candidate_analyst_context(
                                candidate,
                                work_attempt=attempt,
                                semantic_retry=False,
                            ),
                        )
                        analyzed += 1
                        candidate_failure_category = "deterministic_processing"
                        brief = build_research_brief(
                            candidate=candidate,
                            document=document,
                            extracted=extracted,
                            evidence=evidence,
                            analyses=analyses,
                            facts=facts,
                            published_at=self._utc_now(),
                        )
                        if brief is None:
                            self._store.increment_counter(
                                "deterministic_rejections", now=self._utc_now()
                            )
                            decided_at = self._utc_now()
                            self._store.complete_candidate(
                                candidate.accession_number,
                                status="skipped",
                                now=decided_at,
                                run_id=run_id,
                                decision=self._screening_decision(
                                    candidate=candidate,
                                    work_attempt=attempt,
                                    run_id=run_id,
                                    decided_at=decided_at,
                                    disposition=ScreeningDisposition.SCREENED_OUT,
                                    reason=ScreeningReason.NO_VALIDATED_FINDINGS,
                                    source_document_sha256=source_document_sha256,
                                ),
                            )
                            skipped += 1
                            continue
                        self._store.increment_counter("analyst_candidates", now=self._utc_now())
                        if not self._settings.worker_verifier_enabled:
                            candidate_failure_category = "sec_retrieval"
                            sec_links = self._validated_sec_links(client, candidate, document)
                            decided_at = self._utc_now()
                            final_brief = finalize_deterministically_validated_brief(
                                brief,
                                validated_at=decided_at,
                            )
                            decision = self._screening_decision(
                                candidate=candidate,
                                work_attempt=attempt,
                                run_id=run_id,
                                decided_at=decided_at,
                                disposition=ScreeningDisposition.QUALIFIED,
                                reason=ScreeningReason.VALIDATED_PUBLICATION,
                                source_document_sha256=source_document_sha256,
                            )
                            candidate_failure_category = "persistence"
                            self._store.record_deterministic_publication(
                                final_brief, decision, sec_links
                            )
                            published += 1
                            continue
                        package = build_verifier_package(
                            candidate=candidate,
                            document=document,
                            extracted=extracted,
                            evidence=evidence,
                            analyses=analyses,
                            facts=facts,
                            proposed_brief=brief,
                        )
                        candidate_failure_category = "verifier"
                        self._analyst_provider.unload()
                        first_audit = self._run_verifier(package, review_number=1)
                        first_arbitration = arbitrate_verifier_report(package, first_audit.report)
                        first_audit = with_refutations(first_audit, first_arbitration)
                        if first_arbitration.approved:
                            candidate_failure_category = "sec_retrieval"
                            sec_links = self._validated_sec_links(client, candidate, document)
                            outcome = self._verification_outcome(
                                candidate_id=package.candidate.candidate_id,
                                accession_number=candidate.accession_number,
                                disposition=VerificationDisposition.APPROVED,
                                retry_count=0,
                                audits=(first_audit,),
                                analyst_model_name=brief.model_name,
                                analyst_model_digest=brief.model_digest,
                                challenge_categories=(),
                                evidence_ids=(),
                            )
                            final_brief = finalize_verified_brief(
                                brief,
                                final_audit=first_audit,
                                analyst_retry_count=0,
                                published_at=outcome.decided_at,
                            )
                            candidate_failure_category = "persistence"
                            decision = self._screening_decision(
                                candidate=candidate,
                                work_attempt=attempt,
                                run_id=run_id,
                                decided_at=outcome.decided_at,
                                disposition=ScreeningDisposition.QUALIFIED,
                                reason=ScreeningReason.VALIDATED_PUBLICATION,
                                source_document_sha256=source_document_sha256,
                            )
                            candidate_failure_category = "persistence"
                            self._store.record_verification_outcome(
                                outcome,
                                brief=final_brief,
                                decision=decision,
                                sec_links=sec_links,
                            )
                            published += 1
                            continue
                        reconsideration = build_reconsideration(package, first_arbitration)
                        self._store.reserve_analyst_retry(
                            candidate.accession_number,
                            audit=first_audit,
                            reconsideration=reconsideration,
                            now=self._utc_now(),
                        )
                    else:
                        assert claimed.first_audit is not None
                        if not self._settings.worker_verifier_enabled:
                            raise VerifierUnavailableError(
                                "publication-stage independent verifier is disabled"
                            )
                        first_audit = claimed.first_audit
                        reconsideration = claimed.reconsideration

                    original_candidate = CandidateDossier.model_validate_json(
                        reconsideration.original_candidate_json
                    )
                    retry_challenges = tuple(
                        ChallengeCategory(item) for item in reconsideration.challenge_categories
                    )
                    try:
                        candidate_failure_category = "analyst"
                        retry_evidence, retry_analyses = analyze_filing(
                            self._pipeline,
                            candidate=candidate,
                            document=document,
                            extracted=extracted,
                            reconsideration=reconsideration,
                            work_context=self._candidate_analyst_context(
                                candidate,
                                work_attempt=attempt,
                                semantic_retry=True,
                            ),
                        )
                        if claimed.reconsideration is not None:
                            analyzed += 1
                    except AnalysisRejected:
                        outcome = self._verification_outcome(
                            candidate_id=original_candidate.candidate_id,
                            accession_number=candidate.accession_number,
                            disposition=VerificationDisposition.ANALYST_RETRY_REJECTED,
                            retry_count=1,
                            audits=(first_audit,),
                            analyst_model_name=original_candidate.analyst_model_name,
                            analyst_model_digest=original_candidate.analyst_model_digest,
                            challenge_categories=retry_challenges,
                            evidence_ids=reconsideration.relevant_evidence_ids,
                        )
                        candidate_failure_category = "persistence"
                        decision = self._screening_decision(
                            candidate=candidate,
                            work_attempt=attempt,
                            run_id=run_id,
                            decided_at=outcome.decided_at,
                            disposition=ScreeningDisposition.ANALYSIS_INCOMPLETE,
                            reason=ScreeningReason.ANALYST_CONTRACT_REJECTED,
                            source_document_sha256=source_document_sha256,
                        )
                        self._store.record_verification_outcome(
                            outcome, brief=None, decision=decision
                        )
                        self._store.increment_counter(
                            "deterministic_rejections", now=self._utc_now()
                        )
                        skipped += 1
                        continue
                    retry_brief = build_research_brief(
                        candidate=candidate,
                        document=document,
                        extracted=extracted,
                        evidence=retry_evidence,
                        analyses=retry_analyses,
                        facts=facts,
                        published_at=self._utc_now(),
                    )
                    if retry_brief is None:
                        outcome = self._verification_outcome(
                            candidate_id=original_candidate.candidate_id,
                            accession_number=candidate.accession_number,
                            disposition=VerificationDisposition.ANALYST_RETRY_REJECTED,
                            retry_count=1,
                            audits=(first_audit,),
                            analyst_model_name=original_candidate.analyst_model_name,
                            analyst_model_digest=original_candidate.analyst_model_digest,
                            challenge_categories=retry_challenges,
                            evidence_ids=reconsideration.relevant_evidence_ids,
                        )
                        candidate_failure_category = "persistence"
                        decision = self._screening_decision(
                            candidate=candidate,
                            work_attempt=attempt,
                            run_id=run_id,
                            decided_at=outcome.decided_at,
                            disposition=ScreeningDisposition.SCREENED_OUT,
                            reason=ScreeningReason.NO_VALIDATED_FINDINGS,
                            source_document_sha256=source_document_sha256,
                        )
                        self._store.record_verification_outcome(
                            outcome, brief=None, decision=decision
                        )
                        self._store.increment_counter(
                            "deterministic_rejections", now=self._utc_now()
                        )
                        skipped += 1
                        continue
                    retry_package = build_verifier_package(
                        candidate=candidate,
                        document=document,
                        extracted=extracted,
                        evidence=retry_evidence,
                        analyses=retry_analyses,
                        facts=facts,
                        proposed_brief=retry_brief,
                    )
                    candidate_failure_category = "verifier"
                    self._analyst_provider.unload()
                    second_audit = self._run_verifier(retry_package, review_number=2)
                    second_arbitration = arbitrate_verifier_report(
                        retry_package, second_audit.report
                    )
                    second_audit = with_refutations(second_audit, second_arbitration)
                    if second_arbitration.approved:
                        disposition = VerificationDisposition.APPROVED
                        challenge_categories: tuple[ChallengeCategory, ...] = ()
                        challenge_evidence_ids: tuple[UUID, ...] = ()
                    else:
                        disposition = VerificationDisposition.VERIFICATION_DISAGREEMENT
                        challenge_categories = second_arbitration.material_challenges
                        challenge_evidence_ids = second_arbitration.relevant_evidence_ids
                    retry_sec_links: ValidatedSecFilingLinks | None = None
                    if disposition is VerificationDisposition.APPROVED:
                        candidate_failure_category = "sec_retrieval"
                        retry_sec_links = self._validated_sec_links(client, candidate, document)
                    outcome = self._verification_outcome(
                        candidate_id=retry_package.candidate.candidate_id,
                        accession_number=candidate.accession_number,
                        disposition=disposition,
                        retry_count=1,
                        audits=(first_audit, second_audit),
                        analyst_model_name=retry_brief.model_name,
                        analyst_model_digest=retry_brief.model_digest,
                        challenge_categories=challenge_categories,
                        evidence_ids=challenge_evidence_ids,
                    )
                    if disposition is VerificationDisposition.APPROVED:
                        assert retry_sec_links is not None
                        final_brief = finalize_verified_brief(
                            retry_brief,
                            final_audit=second_audit,
                            analyst_retry_count=1,
                            published_at=outcome.decided_at,
                        )
                        candidate_failure_category = "persistence"
                        decision = self._screening_decision(
                            candidate=candidate,
                            work_attempt=attempt,
                            run_id=run_id,
                            decided_at=outcome.decided_at,
                            disposition=ScreeningDisposition.QUALIFIED,
                            reason=ScreeningReason.VALIDATED_PUBLICATION,
                            source_document_sha256=source_document_sha256,
                        )
                        candidate_failure_category = "persistence"
                        self._store.record_verification_outcome(
                            outcome,
                            brief=final_brief,
                            decision=decision,
                            sec_links=retry_sec_links,
                        )
                        published += 1
                    else:
                        candidate_failure_category = "persistence"
                        decision = self._screening_decision(
                            candidate=candidate,
                            work_attempt=attempt,
                            run_id=run_id,
                            decided_at=outcome.decided_at,
                            disposition=ScreeningDisposition.SCREENED_OUT,
                            reason=ScreeningReason.VERIFICATION_DISAGREEMENT,
                            source_document_sha256=source_document_sha256,
                        )
                        self._store.record_verification_outcome(
                            outcome, brief=None, decision=decision
                        )
                        self._store.increment_counter(
                            "verifier_persistent_disagreements", now=self._utc_now()
                        )
                        skipped += 1
                except Exception as error:  # bounded worker boundary records only the error class
                    if isinstance(error, (VerificationRejected, VerifierUnavailableError)) or (
                        isinstance(error, ModelProviderError)
                        and candidate_failure_category == "verifier"
                    ):
                        self._store.increment_counter("verifier_errors", now=self._utc_now())
                    candidate_error = _error_code(error)
                    maximum_attempts = _maximum_candidate_attempts(error)
                    if attempt >= maximum_attempts:
                        decided_at = self._utc_now()
                        self._store.complete_candidate(
                            candidate.accession_number,
                            status="failed",
                            now=decided_at,
                            error_code=candidate_error,
                            failure_category=candidate_failure_category,
                            run_id=run_id,
                            decision=self._screening_decision(
                                candidate=candidate,
                                work_attempt=attempt,
                                run_id=run_id,
                                decided_at=decided_at,
                                disposition=ScreeningDisposition.ANALYSIS_INCOMPLETE,
                                reason=_incomplete_reason(error, candidate_failure_category),
                                source_document_sha256=source_document_sha256,
                            ),
                        )
                    else:
                        self._store.complete_candidate(
                            candidate.accession_number,
                            status="retry_wait",
                            now=self._utc_now(),
                            error_code=candidate_error,
                            next_attempt_at=self._utc_now() + timedelta(hours=attempt),
                            failure_category=candidate_failure_category,
                            run_id=run_id,
                        )
                    run_state = RunState.DEGRADED
                    error_code = candidate_error
                self._snapshot(
                    state=WorkerState.RUNNING,
                    now=self._utc_now(),
                    next_run=started + timedelta(seconds=self._settings.worker_poll_seconds),
                    error_code=error_code,
                    success=False,
                )
            self._process_one_human_lead(
                client=client, candidates=candidates, ticker_mapping=mapping
            )
            self._deliver_pending_notifications()
        except Exception as error:  # keep the supervised process alive across provider outages
            run_state = RunState.FAILED
            error_code = _error_code(error)

        completed = self._utc_now()
        try:
            self._store.generate_engineering_measurements(now=completed)
        except Exception as error:
            if run_state is RunState.COMPLETED:
                run_state = RunState.DEGRADED
                error_code = f"EngineeringMeasurementError:{type(error).__name__}"[:255]
        self._store.append_run(
            RadarRun(
                run_id=run_id,
                started_at=started,
                completed_at=completed,
                state=run_state,
                discovered_count=discovered,
                analyzed_count=analyzed,
                published_count=published,
                skipped_count=skipped,
                error_code=error_code,
            )
        )
        _, pending, _ = self._store.counts()
        sleep_seconds = 60 if pending else self._settings.worker_poll_seconds
        self._snapshot(
            state=WorkerState.IDLE if run_state is RunState.COMPLETED else WorkerState.DEGRADED,
            now=completed,
            next_run=completed + timedelta(seconds=sleep_seconds),
            error_code=error_code,
            success=run_state is RunState.COMPLETED,
        )
        return sleep_seconds

    def _record_candidate_stage(
        self, run_id: UUID, accession_number: str, stage: PipelineStage
    ) -> None:
        self._store.append_pipeline_event(
            PipelineEvent(
                event_id=uuid4(),
                occurred_at=self._utc_now(),
                stage=stage,
                run_id=run_id,
                accession_number=accession_number,
            )
        )

    def _validated_sec_links(
        self,
        client: SecRadarClient,
        candidate: FilingCandidate,
        document: SecRadarDocument,
    ) -> ValidatedSecFilingLinks:
        """Validate public filing links only after a dossier has qualified."""

        return validate_sec_filing_links(
            client=client,
            canonical_cik=candidate.cik.zfill(10),
            accession_number=candidate.accession_number,
            filing_form=candidate.filing_form,
            complete_submission=document,
        )

    def _apply_event_novelty(
        self,
        candidate: FilingCandidate,
        document: SecRadarDocument,
        extracted: ExtractedFiling,
    ) -> ExtractedFiling:
        """Persist supported novelty and withhold proven recap text from Qwen."""

        source = EventSourceReceipt(
            source_class=SourceClass.SEC,
            publisher="U.S. Securities and Exchange Commission",
            canonical_url=HttpUrl(candidate.source_url),
            accession_number=candidate.accession_number,
            source_content_sha256=document.content_sha256,
            # The daily index provides a filing date, not a precise acceptance
            # timestamp. Preserve UNKNOWN instead of manufacturing midnight UTC.
            published_at=None,
            available_at=document.retrieved_at,
            retrieved_at=document.retrieved_at,
        )
        disclosure = extract_strategic_partnership_disclosure(
            issuer_cik=candidate.cik,
            issuer_name=candidate.company_name,
            text=extracted.text,
            source=source,
        )
        if disclosure is None:
            return extracted
        priors = self._store.event_disclosures(
            issuer_cik=disclosure.issuer_cik,
            category=disclosure.category,
            exclude_source_content_sha256=disclosure.source.source_content_sha256,
        )
        receipt = classify_event_novelty(
            disclosure,
            prior_disclosures=priors,
            # This first slice has no reviewed issuer-IR history adapter. Absence
            # from the prospective ledger therefore cannot prove a new event.
            prior_search_complete=False,
            evaluated_at=self._utc_now(),
        )
        receipt = self._store.append_event_lineage(receipt)
        if receipt.disposition not in {
            EventNoveltyDisposition.RECAP_EXISTING_EVENT,
            EventNoveltyDisposition.DUPLICATE_DISCLOSURE,
            EventNoveltyDisposition.HISTORICAL_CONTEXT,
        }:
            return extracted
        return exclude_exact_event_evidence(
            extracted,
            tuple(item.quote for item in disclosure.evidence),
        )

    def _deliver_pending_notifications(self) -> None:
        if not self._settings.discord_enabled:
            return
        for brief, sec_links in self._store.briefs_pending_notification():
            notification = RadarNotification(
                brief=brief,
                sec_links=(public_sec_filing_links(sec_links) if sec_links is not None else None),
            )
            if self._store.notification_is_terminal(notification.notification_key):
                continue
            delivery = self._notifier.send_radar(notification)
            self._store.append_delivery(brief.brief_id, delivery)

    def _run_verifier(self, package: VerifierPackage, *, review_number: int) -> VerifierAudit:
        try:
            audit = self._verifier.verify(package, review_number=review_number)
        finally:
            self._verifier_provider.unload()
        self._store.increment_counter("verifier_reviews", now=self._utc_now())
        counter = (
            "verifier_approvals"
            if audit.report.verdict.value == "approve"
            else "verifier_challenges"
        )
        self._store.increment_counter(counter, now=self._utc_now())
        return audit

    def _verification_outcome(
        self,
        *,
        candidate_id: UUID,
        accession_number: str,
        disposition: VerificationDisposition,
        retry_count: int,
        audits: tuple[VerifierAudit, ...],
        analyst_model_name: str,
        analyst_model_digest: str,
        challenge_categories: tuple[ChallengeCategory, ...],
        evidence_ids: tuple[UUID, ...],
    ) -> VerificationOutcome:
        decided_at = self._utc_now()
        last_audit = audits[-1]
        return VerificationOutcome(
            disposition_id=uuid5(
                NAMESPACE_URL,
                f"kalki-verification:{candidate_id}:{disposition.value}:{last_audit.review_id}",
            ),
            candidate_id=candidate_id,
            accession_number=accession_number,
            disposition=disposition,
            retry_count=retry_count,
            decided_at=decided_at,
            analyst_model_name=analyst_model_name,
            analyst_model_digest=analyst_model_digest,
            verifier_model_name=last_audit.model_name,
            verifier_model_digest=last_audit.model_digest,
            audits=audits,
            final_challenge_categories=challenge_categories,
            final_evidence_ids=evidence_ids,
        )

    def _screening_decision(
        self,
        *,
        candidate: FilingCandidate,
        work_attempt: int,
        run_id: UUID,
        decided_at: datetime,
        disposition: ScreeningDisposition,
        reason: ScreeningReason,
        source_document_sha256: str | None,
    ) -> AutonomousScreeningDecision:
        return AutonomousScreeningDecision(
            decision_id=uuid5(
                NAMESPACE_URL,
                f"kalki-autonomous-screening:{candidate.accession_number}",
            ),
            accession_number=candidate.accession_number,
            decided_at=decided_at,
            disposition=disposition,
            reason=reason,
            work_attempt=work_attempt,
            run_id=run_id,
            analyst_attempt_ids=self._store.candidate_analyst_attempt_ids(
                candidate.accession_number
            ),
            source_document_sha256=source_document_sha256,
        )

    def _snapshot(
        self,
        *,
        state: WorkerState,
        now: datetime,
        next_run: datetime,
        error_code: str | None,
        success: bool,
    ) -> None:
        discovered, pending, published = self._store.counts()
        verifier_reviews, verifier_approvals, verifier_challenges = self._store.verifier_counts()
        self._store.save_snapshot(
            WorkerSnapshot(
                state=state,
                heartbeat_at=now,
                last_success_at=now if success else None,
                next_run_at=next_run,
                last_error_code=error_code,
                discovered_count=discovered,
                pending_count=pending,
                published_count=published,
                discord_enabled=self._settings.discord_enabled,
                model_name=self._settings.worker_model,
                verifier_enabled=self._settings.worker_verifier_enabled,
                verifier_model_name=(
                    self._settings.worker_verifier_model
                    if self._settings.worker_verifier_enabled
                    else None
                ),
                verifier_reviews=verifier_reviews,
                verifier_approvals=verifier_approvals,
                verifier_challenges=verifier_challenges,
            )
        )

    def _utc_now(self) -> datetime:
        observed = self._now()
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("worker clock must be timezone-aware")
        return observed.astimezone(UTC)

    @staticmethod
    def _candidate_analyst_context(
        candidate: FilingCandidate,
        *,
        work_attempt: int,
        semantic_retry: bool,
    ) -> AnalystWorkContext:
        return AnalystWorkContext(
            origin=AnalystAttemptOrigin.CANDIDATE,
            candidate_accession_number=candidate.accession_number,
            ticker=candidate.ticker,
            cik=candidate.cik,
            accession_number=candidate.accession_number,
            filing_form=candidate.filing_form,
            work_attempt=work_attempt,
            semantic_retry=semantic_retry,
            runtime_retry_eligible=work_attempt < 3,
        )

    def _process_one_human_lead(
        self,
        *,
        client: SecRadarClient,
        candidates: tuple[FilingCandidate, ...],
        ticker_mapping: dict[str, tuple[str, str | None]],
    ) -> None:
        """Consume one lead without allowing human work to preempt SEC analysis."""
        delivery_channel_id = self._settings.discord_intake_results_channel_id
        if delivery_channel_id is None:
            # The base public stack has no Discord destination. Do not claim private
            # work unless the operator configured its closed delivery boundary.
            return
        lead = self._store.claim_human_lead(now=self._utc_now())
        if lead is None:
            return
        disposition = HumanResearchDisposition.INSUFFICIENT_EVIDENCE
        conclusion = "No bounded authoritative SEC filing was supplied or resolved for this lead."
        evidence_ids: tuple[UUID, ...] = ()
        source_receipt = HumanSecSourceReceipt(
            status=HumanSourceStatus.UNRESOLVED,
            ticker=lead.ticker,
            reason="No unambiguous authoritative SEC filing was resolved.",
        )
        xbrl_receipt = HumanXbrlReceipt(
            status=HumanAssessmentStatus.NOT_ASSESSED,
            reason="XBRL was not assessed because no filing identity was resolved.",
        )
        filing_diff_receipt = HumanFilingDiffReceipt(
            status=HumanAssessmentStatus.NOT_ASSESSED,
            reason="No prior comparable filing was retrieved for this human lead.",
        )
        forensic_receipts: tuple[ForensicSignal, ...] = ()
        tier0_status = HumanAssessmentStatus.NOT_ASSESSED
        tier0_decision: TierDecision | None = None
        analyst_status = HumanAssessmentStatus.NOT_ASSESSED
        analyst_attempt_receipts: tuple[AnalystAttemptReceipt, ...] = ()
        deterministic_verification = HumanDeterministicVerificationReceipt(
            status=HumanAssessmentStatus.NOT_ASSESSED,
            reason="No validated analyst claims required deterministic verification.",
        )
        model_invoked = False
        source_url = next(
            (url for url in lead.urls if url.startswith("https://www.sec.gov/Archives/")), None
        )
        resolved = _resolve_human_candidate(lead, candidates)
        if resolved is None and lead.cik is None and lead.ticker is not None:
            mapped_cik = next(
                (cik for cik, (symbol, _) in ticker_mapping.items() if symbol == lead.ticker),
                None,
            )
            if mapped_cik is not None:
                try:
                    resolved = latest_submission_candidate(
                        client.submissions(mapped_cik), cik=mapped_cik, ticker=lead.ticker
                    )
                except Exception:
                    resolved = None
        if source_url is None and resolved is not None:
            source_url = resolved.source_url
        if source_url is not None:
            match = re.search(r"/(\d{10}-\d{2}-\d{6})\.txt$", source_url)
            selected = None
            if match is not None:
                selected = next(
                    (item for item in candidates if item.accession_number == match.group(1)), None
                )
            if selected is None:
                selected = resolved
            if match is not None and selected is not None:
                try:
                    document = client.filing(source_url)
                    extracted = extract_research_excerpt(document.body)
                    evidence_id = uuid5(NAMESPACE_URL, f"human-sec:{lead.lead_id}:{match.group(1)}")
                    evidence_ids = (evidence_id,)
                    source_receipt = HumanSecSourceReceipt(
                        status=HumanSourceStatus.RESOLVED,
                        ticker=selected.ticker,
                        canonical_cik=selected.cik.zfill(10),
                        company_name=selected.company_name,
                        filing_form=selected.filing_form,
                        accession_number=selected.accession_number,
                        authoritative_url=selected.source_url,
                        source_document_sha256=document.content_sha256,
                        excerpt_sha256=extracted.content_sha256,
                        filed_at=selected.filed_at,
                        retrieved_at=document.retrieved_at,
                        reason="Resolved and retrieved from the authoritative SEC archive.",
                    )
                    forensic_receipts = assess_forensics(
                        ForensicInput(text=extracted.text[:255], evidence_ids=evidence_ids)
                    )
                    tier0_decision = choose_tier(
                        research_relevant=extracted.is_research_relevant and bool(extracted.text),
                        material_terms=bool(extracted.opportunity_terms or extracted.risk_terms),
                        context_chars=len(extracted.text),
                        evidence_ids=evidence_ids,
                        forensic_signals=forensic_receipts,
                    )
                    tier0_status = HumanAssessmentStatus.ASSESSED
                    filing_diff_receipt = HumanFilingDiffReceipt(
                        status=HumanAssessmentStatus.NOT_ASSESSED,
                        current_accession_number=selected.accession_number,
                        current_source_content_sha256=document.content_sha256,
                        reason="No prior comparable filing was retrieved for a deterministic diff.",
                    )
                    facts: tuple[SecFactRecord, ...] = ()
                    try:
                        facts_document = client.companyfacts(selected.cik)
                        facts = normalize_companyfacts(
                            SecFetchedDocument(
                                endpoint="companyfacts",
                                cik=selected.cik.zfill(10),
                                url=facts_document.url,
                                status_code=200,
                                headers={"content-type": facts_document.media_type},
                                body=facts_document.body,
                                content_sha256=facts_document.content_sha256,
                                retrieved_at=facts_document.retrieved_at,
                            )
                        )
                        xbrl_receipt = HumanXbrlReceipt(
                            status=HumanAssessmentStatus.ASSESSED,
                            source_url=facts_document.url,
                            source_content_sha256=facts_document.content_sha256,
                            retrieved_at=facts_document.retrieved_at,
                            normalized_fact_count=len(facts),
                            same_filing_fact_count=sum(
                                fact.accession_number == selected.accession_number for fact in facts
                            ),
                            reason="SEC CompanyFacts normalized without guessing contexts.",
                        )
                    except Exception:
                        xbrl_receipt = HumanXbrlReceipt(
                            status=HumanAssessmentStatus.FAILED,
                            reason="SEC CompanyFacts could not be safely retrieved or normalized.",
                        )
                    disposition = (
                        HumanResearchDisposition.SUPPORTED
                        if tier0_decision.requires_model
                        else HumanResearchDisposition.INCONCLUSIVE
                    )
                    conclusion = (
                        "Authoritative SEC evidence was retrieved and classified by "
                        "deterministic Tier-0 analysis."
                    )
                    if tier0_decision.requires_model:
                        model_invoked = True
                        try:
                            analyst_evidence, analyses = analyze_filing(
                                self._pipeline,
                                candidate=selected,
                                document=document,
                                extracted=extracted,
                                work_context=AnalystWorkContext(
                                    origin=AnalystAttemptOrigin.HUMAN,
                                    lead_id=lead.lead_id,
                                    ticker=selected.ticker,
                                    cik=selected.cik,
                                    accession_number=selected.accession_number,
                                    filing_form=selected.filing_form,
                                    work_attempt=lead.attempts,
                                    runtime_retry_eligible=False,
                                ),
                            )
                            evidence_ids = tuple(
                                dict.fromkeys((*evidence_ids, analyst_evidence.evidence_id))
                            )
                            brief = build_research_brief(
                                candidate=selected,
                                document=document,
                                extracted=extracted,
                                evidence=analyst_evidence,
                                analyses=analyses,
                                facts=facts,
                            )
                            if brief is not None:
                                disposition = HumanResearchDisposition.SUPPORTED
                                conclusion = brief.summary[:2_000]
                                deterministic_verification = (
                                    HumanDeterministicVerificationReceipt(
                                        status=HumanAssessmentStatus.ASSESSED,
                                        numeric_verifications=brief.numeric_verifications,
                                        reason=(
                                            "Analyst numeric claims received deterministic checks."
                                        ),
                                    )
                                    if brief.numeric_verifications
                                    else HumanDeterministicVerificationReceipt(
                                        status=HumanAssessmentStatus.NOT_ASSESSED,
                                        reason=(
                                            "Validated analyst output contained no numeric claims."
                                        ),
                                    )
                                )
                            else:
                                disposition = HumanResearchDisposition.INCONCLUSIVE
                                conclusion = (
                                    "Validated analyst output did not support a bounded "
                                    "evidence-backed conclusion."
                                )
                        except (AnalysisRejected, ModelProviderError, ValueError):
                            disposition = HumanResearchDisposition.INCONCLUSIVE
                            conclusion = (
                                "Authoritative SEC evidence was retrieved, but the bounded "
                                "analyst response could not be validated; no interpretation "
                                "was published."
                            )
                except Exception:
                    source_receipt = HumanSecSourceReceipt(
                        status=HumanSourceStatus.RETRIEVAL_FAILED,
                        ticker=selected.ticker,
                        reason="The SEC filing could not be safely retrieved or parsed.",
                    )
                    conclusion = "The supplied SEC pointer could not be safely retrieved or parsed."
        if model_invoked:
            analyst_attempt_receipts = self._store.human_analyst_attempt_receipts(lead.lead_id)
            analyst_status = (
                HumanAssessmentStatus.ASSESSED
                if analyst_attempt_receipts
                else HumanAssessmentStatus.FAILED
            )
        result = HumanResearchResult.from_lead(
            lead,
            source=source_receipt,
            xbrl=xbrl_receipt,
            filing_diff=filing_diff_receipt,
            forensic_receipts=forensic_receipts,
            tier0_status=tier0_status,
            tier0_decision=tier0_decision,
            analyst_status=analyst_status,
            analyst_attempt_receipts=analyst_attempt_receipts,
            deterministic_verification=deterministic_verification,
            disposition=disposition,
            conclusion=conclusion,
            evidence_ids=evidence_ids,
            delivery_channel_id=delivery_channel_id,
            created_at=self._utc_now(),
        )
        self._store.record_human_result(result, channel_id=delivery_channel_id)
        self._store.transition_human_lead(
            lead.lead_id,
            HumanLeadStatus.COMPLETED,
            now=self._utc_now(),
            detail="human lead completed with insufficient authoritative evidence",
        )


def _resolve_human_candidate(
    lead: HumanResearchLead, candidates: tuple[FilingCandidate, ...]
) -> FilingCandidate | None:
    """Resolve a lead only when its identity maps to one unambiguous filing."""

    matching = [item for item in candidates if lead.cik is not None and item.cik == lead.cik]
    if lead.ticker is not None:
        matching = [item for item in matching if item.ticker == lead.ticker]
    if not matching and lead.ticker is not None:
        matching = [item for item in candidates if item.ticker == lead.ticker]
    if not matching:
        return None
    return max(matching, key=lambda item: item.filed_at)


def worker_main() -> int:
    settings = _load_worker_settings()
    if not settings.worker_enabled:
        print("Research worker is disabled.", file=sys.stderr)
        return 2
    if settings.database_password_file is None:
        print("Research worker database secret is absent.", file=sys.stderr)
        return 2
    runtime = DatabaseRuntime(
        DatabaseOptions(
            host=settings.database_host,
            port=settings.database_port,
            name=settings.database_name,
            user=settings.database_user,
            password_file=settings.database_password_file,
            minimum_pool_size=settings.database_pool_minimum,
            maximum_pool_size=settings.database_pool_maximum,
        )
    )
    runtime.open()
    try:
        worker = FilingRadarWorker(
            settings=settings,
            store=PostgresRadarStore(runtime.connection),
            convergence_service=ConvergenceValidationService(
                PostgresContradictionStore(runtime.connection)
            ),
        )
        # Claims left by a prior process cannot be safely inherited. Recover
        # them before this worker begins polling; terminal rows are untouched.
        worker._store.requeue_processing_on_startup(now=datetime.now(UTC))
        while True:
            time.sleep(worker.run_once())
    except KeyboardInterrupt:
        return 0
    finally:
        runtime.close()


def _load_worker_settings() -> Settings:
    bootstrap = Settings.load()
    if bootstrap.local_settings_file is None:
        return bootstrap
    return Settings(_env_file=bootstrap.local_settings_file)


def _error_code(error: Exception) -> str:
    """Persist a bounded class/message category for post-mortem diagnosis."""

    category = type(error).__name__
    detail = " ".join(str(error).split())
    if detail:
        return f"{category}:{detail}"[:255]
    return category[:255]


def _incomplete_reason(
    error: Exception,
    failure_category: PipelineFailureCategory,
) -> ScreeningReason:
    """Map only observed bounded runtime evidence to a terminal reason."""

    if isinstance(error, AnalysisRejected):
        codes = set(error.error_codes)
        if "numeric_conflict" in codes:
            return ScreeningReason.NUMERIC_CONFLICT
        if "provenance_failure" in codes:
            return ScreeningReason.PROVENANCE_FAILURE
        if codes.intersection({"invalid_evidence_id", "unsupported_claim"}):
            return ScreeningReason.EVIDENCE_VALIDATION_REJECTED
        return ScreeningReason.ANALYST_CONTRACT_REJECTED
    if isinstance(error, VerifierUnavailableError):
        return ScreeningReason.VERIFIER_UNAVAILABLE
    if isinstance(error, VerificationRejected):
        return ScreeningReason.VERIFIER_FAILURE
    if isinstance(error, ModelProviderError):
        observed: BaseException | None = error
        while observed is not None:
            if isinstance(observed, TimeoutError) or "TimeoutError" in str(observed):
                return ScreeningReason.ANALYST_TIMEOUT
            observed = observed.__cause__
        return ScreeningReason.ANALYST_PROVIDER_FAILURE
    return {
        "sec_retrieval": ScreeningReason.SOURCE_RETRIEVAL_FAILURE,
        "filing_parse": ScreeningReason.FILING_PARSE_FAILURE,
        "companyfacts_normalization": ScreeningReason.COMPANYFACTS_NORMALIZATION_FAILURE,
        "deterministic_processing": ScreeningReason.DETERMINISTIC_PROCESSING_FAILURE,
        "analyst": ScreeningReason.OTHER_BOUNDED_FAILURE,
        "verifier": ScreeningReason.VERIFIER_FAILURE,
        "persistence": ScreeningReason.PERSISTENCE_FAILURE,
        "other": ScreeningReason.OTHER_BOUNDED_FAILURE,
    }[failure_category]


def _maximum_candidate_attempts(error: Exception) -> int:
    """Bound deterministic local-analyst retries while retaining verifier recovery."""

    if isinstance(error, (VerificationRejected, VerifierUnavailableError)):
        return 6
    return 3


if __name__ == "__main__":
    raise SystemExit(worker_main())
