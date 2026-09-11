"""Validated local-model analysis and deterministic filing-radar scoring."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from kalki_market_intelligence.analysis.attempts import AnalystWorkContext
from kalki_market_intelligence.analysis.contracts import (
    AnalystEvidence,
    AnalystFinding,
    AnalystReconsideration,
    AnalystRole,
    FindingCategory,
    FindingPolarity,
    ValidatedAnalysis,
)
from kalki_market_intelligence.analysis.pipeline import AnalystPipeline
from kalki_market_intelligence.contracts.evidence import SourceClass
from kalki_market_intelligence.forensics import ForensicInput, assess_forensics
from kalki_market_intelligence.forensics.filing_diff import FilingDiff
from kalki_market_intelligence.providers.sec.contracts import SecFactRecord
from kalki_market_intelligence.quantitative.claim_verification import (
    NumericClaim,
    NumericVerification,
    verify_numeric_claim,
)
from kalki_market_intelligence.quantitative.xbrl_claims import verify_numeric_claim_against_xbrl
from kalki_market_intelligence.radar.contracts import (
    BriefEvidence,
    FilingCandidate,
    PublicationGateMode,
    PublicPublicationGateReceipt,
    PublicVerificationReceipt,
    RadarClassification,
    ResearchBrief,
)
from kalki_market_intelligence.radar.extraction import ExtractedFiling
from kalki_market_intelligence.radar.sec_source import SecRadarDocument
from kalki_market_intelligence.verification.contracts import (
    ArbitrationResult,
    CandidateClaim,
    CandidateDossier,
    DeterministicFilingFacts,
    VerifierAudit,
    VerifierEvidence,
    VerifierPackage,
)

ANALYST_ROLES = (AnalystRole.CATALYST_ANALYST, AnalystRole.BULL_BEAR_RISK_ANALYST)


def analyze_filing(
    pipeline: AnalystPipeline,
    *,
    candidate: FilingCandidate,
    document: SecRadarDocument,
    extracted: ExtractedFiling,
    reconsideration: AnalystReconsideration | None = None,
    work_context: AnalystWorkContext | None = None,
) -> tuple[AnalystEvidence, tuple[ValidatedAnalysis, ...]]:
    """Run two narrow roles against the same immutable, bounded SEC excerpt."""

    subject_id = uuid5(NAMESPACE_URL, f"sec-cik:{candidate.cik}")
    evidence_id = uuid5(NAMESPACE_URL, f"sec-filing-excerpt:{candidate.accession_number}")
    source_id = uuid5(NAMESPACE_URL, candidate.source_url)
    evidence = AnalystEvidence(
        evidence_id=evidence_id,
        subject_id=subject_id,
        source_id=source_id,
        source_class=SourceClass.SEC,
        publisher="U.S. Securities and Exchange Commission",
        locator=candidate.source_url,
        text=extracted.text,
        content_sha256=extracted.content_sha256,
        published_at=candidate.filed_at,
        available_at=document.retrieved_at,
        retrieved_at=document.retrieved_at,
    )
    analyses = tuple(
        pipeline.analyze(
            role=role,
            evidence=(evidence,),
            knowledge_cutoff_at=document.retrieved_at,
            reconsideration=reconsideration,
            work_context=work_context,
        )
        for role in ANALYST_ROLES
    )
    return evidence, analyses


def build_research_brief(
    *,
    candidate: FilingCandidate,
    document: SecRadarDocument,
    extracted: ExtractedFiling,
    evidence: AnalystEvidence,
    analyses: Sequence[ValidatedAnalysis],
    facts: Sequence[SecFactRecord] = (),
    published_at: datetime | None = None,
) -> ResearchBrief | None:
    """Turn validated findings into a transparent priority brief, or publish nothing."""

    findings = tuple(finding for analysis in analyses for finding in analysis.report.findings)
    if not findings:
        return None
    positive = tuple(
        item
        for item in findings
        if item.category in {FindingCategory.CATALYST, FindingCategory.BULL_CASE}
        or item.polarity is FindingPolarity.BULLISH
    )
    negative = tuple(
        item
        for item in findings
        if item.category in {FindingCategory.RISK, FindingCategory.BEAR_CASE}
        or item.polarity is FindingPolarity.BEARISH
    )
    attention_points = min(
        100,
        len(extracted.opportunity_terms) * 5 + len(positive) * 18 + len(findings) * 3,
    )
    risk_points = min(100, len(extracted.risk_terms) * 7 + len(negative) * 18)
    citation_count = sum(len(item.citations) for item in findings)
    evidence_strength = min(100, 35 + len(analyses) * 15 + citation_count * 5)
    classification = _classification(attention_points, risk_points, bool(positive), bool(negative))
    statements = tuple(dict.fromkeys(item.statement for item in (*positive, *negative, *findings)))
    summary = " ".join(statements[:3])[:10_000]
    if not summary:
        return None
    citations = tuple(
        citation
        for finding in findings
        for citation in finding.citations
        if citation.evidence_id == evidence.evidence_id
    )
    unique_quotes = tuple(dict.fromkeys(item.quote for item in citations))[:12]
    if not unique_quotes:
        return None
    model_names = {analysis.audit.model_name for analysis in analyses}
    model_digests = {analysis.audit.model_digest for analysis in analyses}
    prompt_versions = {analysis.audit.prompt_version for analysis in analyses}
    if (
        len(model_names) != 1
        or len(model_digests) != 1
        or len(prompt_versions) != 1
        or None in model_digests
    ):
        raise ValueError("radar analyses must use one digest-identified local model")
    selected_published_at = (published_at or datetime.now(UTC)).astimezone(UTC)
    ticker_label = candidate.ticker or f"CIK {candidate.cik}"
    evidence_records = tuple(
        BriefEvidence(
            evidence_id=uuid5(
                NAMESPACE_URL,
                f"brief-quote:{candidate.accession_number}:{sha256(quote.encode()).hexdigest()}",
            ),
            quote=quote,
            excerpt_sha256=extracted.content_sha256,
            source_url=candidate.source_url,
            source_document_sha256=document.content_sha256,
            available_at=document.retrieved_at,
            retrieved_at=document.retrieved_at,
        )
        for quote in unique_quotes
    )
    numeric_verifications = _verify_finding_numbers(
        findings,
        evidence,
        extracted.content_sha256,
        facts=facts,
        accession_number=candidate.accession_number,
    )
    limitations = (
        "Filing-driven radar; no licensed live price or volume feed is used.",
        "Scores prioritize follow-up research and are not probabilities or expected returns.",
        "The local model interprets only deterministically selected filing excerpts.",
    )
    return ResearchBrief(
        brief_id=uuid5(NAMESPACE_URL, f"kalki-radar:{candidate.accession_number}"),
        accession_number=candidate.accession_number,
        cik=candidate.cik,
        company_name=candidate.company_name,
        ticker=candidate.ticker,
        exchange=candidate.exchange,
        filing_form=candidate.filing_form,
        filed_at=candidate.filed_at,
        retrieved_at=document.retrieved_at,
        published_at=selected_published_at,
        source_url=candidate.source_url,
        source_document_sha256=document.content_sha256,
        classification=classification,
        attention_points=attention_points,
        risk_points=risk_points,
        evidence_strength_points=evidence_strength,
        headline=f"{ticker_label} · {candidate.filing_form} filing radar",
        summary=summary,
        why_it_matters=(
            f"Validated review found {len(positive)} opportunity-side and {len(negative)} "
            f"risk-side finding(s) across {len(unique_quotes)} exact SEC quotation(s)."
        ),
        evidence=evidence_records,
        numeric_verifications=numeric_verifications,
        model_name=next(iter(model_names)),
        model_digest=next(item for item in model_digests if item is not None),
        prompt_version=next(iter(prompt_versions)),
        limitations=limitations,
    )


def finalize_deterministically_validated_brief(
    brief: ResearchBrief,
    *,
    validated_at: datetime,
) -> ResearchBrief:
    """Version a qualifying brief for the accepted Qwen-plus-deterministic gate."""

    selected_time = validated_at.astimezone(UTC)
    payload = brief.model_dump(mode="json")
    payload.update(
        {
            "schema_version": "3.0.0",
            "published_at": selected_time,
            "verification": None,
            "publication_gate": PublicPublicationGateReceipt(
                mode=PublicationGateMode.DETERMINISTIC_ONLY,
                validated_at=selected_time,
                independent_verifier_status="disabled",
            ).model_dump(mode="json"),
        }
    )
    return ResearchBrief.model_validate(payload)


def build_verifier_package(
    *,
    candidate: FilingCandidate,
    document: SecRadarDocument,
    extracted: ExtractedFiling,
    evidence: AnalystEvidence,
    analyses: Sequence[ValidatedAnalysis],
    proposed_brief: ResearchBrief,
    facts: Sequence[SecFactRecord] = (),
    filing_diff: FilingDiff | None = None,
) -> VerifierPackage:
    """Build an evidence-first package with no raw filing or hidden model reasoning."""

    findings = tuple(finding for analysis in analyses for finding in analysis.report.findings)
    claims = tuple(
        CandidateClaim(
            claim_id=f"C{index:02d}",
            kind=finding.kind.value,
            category=finding.category.value,
            polarity=finding.polarity.value,
            statement=finding.statement,
            evidence_ids=tuple(citation.evidence_id for citation in finding.citations),
        )
        for index, finding in enumerate(findings, start=1)
    )
    if not claims:
        raise ValueError("publication verifier package requires candidate claims")
    return VerifierPackage(
        facts=DeterministicFilingFacts(
            accession_number=candidate.accession_number,
            cik=candidate.cik,
            company_name=candidate.company_name,
            ticker=candidate.ticker,
            exchange=candidate.exchange,
            filing_form=candidate.filing_form,
            source_url=candidate.source_url,
            source_document_sha256=document.content_sha256,
            excerpt_sha256=extracted.content_sha256,
            filed_at=candidate.filed_at,
            retrieved_at=document.retrieved_at,
            opportunity_terms=extracted.opportunity_terms,
            risk_terms=extracted.risk_terms,
        ),
        evidence=(
            VerifierEvidence(
                evidence_id=evidence.evidence_id,
                text=evidence.text,
                content_sha256=evidence.content_sha256,
                source_url=candidate.source_url,
            ),
        ),
        classification_definitions={
            "opportunity": "Opportunity-side evidence is material and not outweighed here.",
            "mixed": "Material opportunity and material risk evidence are both present.",
            "risk": "Material risk-side evidence is the dominant publication reason.",
            "watch": "Evidence merits follow-up but does not support a stronger class.",
        },
        candidate=CandidateDossier(
            candidate_id=uuid5(
                NAMESPACE_URL, f"kalki-radar-candidate:{candidate.accession_number}"
            ),
            classification=proposed_brief.classification.value,
            attention_points=proposed_brief.attention_points,
            risk_points=proposed_brief.risk_points,
            evidence_strength_points=proposed_brief.evidence_strength_points,
            summary=proposed_brief.summary,
            why_it_matters=proposed_brief.why_it_matters,
            claims=claims,
            numeric_verifications=tuple(
                _verify_finding_numbers(
                    findings,
                    evidence,
                    extracted.content_sha256,
                    facts=facts,
                    accession_number=candidate.accession_number,
                )
            ),
            forensic_signals=assess_forensics(
                ForensicInput(text=extracted.text[:255], evidence_ids=(evidence.evidence_id,))
            ),
            filing_diff=filing_diff,
            analyst_model_name=proposed_brief.model_name,
            analyst_model_digest=proposed_brief.model_digest,
            analyst_prompt_version=proposed_brief.prompt_version,
        ),
    )


_NUMERIC_LITERAL = re.compile(r"(?<![A-Za-z0-9])(?:\$?\d[\d,]*(?:\.\d+)?%?)(?![A-Za-z0-9])")


def _verify_finding_numbers(
    findings: Sequence[AnalystFinding],
    evidence: AnalystEvidence,
    source_hash: str,
    *,
    facts: Sequence[SecFactRecord],
    accession_number: str,
) -> tuple[NumericVerification, ...]:
    """Verify only literals stated by a finding against its exact cited quotations."""

    results: list[NumericVerification] = []
    for index, finding in enumerate(findings, start=1):
        statement = finding.statement
        citations = finding.citations
        quotes = tuple(
            citation.quote for citation in citations if citation.evidence_id == evidence.evidence_id
        )
        for token in dict.fromkeys(_NUMERIC_LITERAL.findall(statement)):
            normalized = token.replace("$", "").replace(",", "").replace("%", "")
            try:
                claimed = Decimal(normalized)
            except InvalidOperation:
                continue
            source_value = None
            for quote in quotes:
                if token in quote:
                    source_value = claimed
                    break
            claim = NumericClaim(
                claim_id=f"C{index:02d}",
                evidence_id=str(evidence.evidence_id),
                claimed_value=claimed,
                unit="percent" if token.endswith("%") else "reported_value",
                source_value=source_value,
                source_content_sha256=source_hash,
            )
            result = (
                verify_numeric_claim_against_xbrl(claim, facts, accession_number=accession_number)
                if source_value is None and facts
                else verify_numeric_claim(claim)
            )
            results.append(result)
            if len(results) >= 24:
                return tuple(results)
    return tuple(results)


def build_reconsideration(
    package: VerifierPackage,
    arbitration: ArbitrationResult,
) -> AnalystReconsideration:
    """Give Qwen a neutral, bounded description of the disputed evidence."""

    if arbitration.approved:
        raise ValueError("approved candidates do not require reconsideration")
    return AnalystReconsideration(
        original_candidate_json=package.candidate.model_dump_json(),
        challenge_categories=tuple(item.value for item in arbitration.material_challenges),
        relevant_evidence_ids=arbitration.relevant_evidence_ids,
        relevant_claim_ids=arbitration.relevant_claim_ids,
    )


def finalize_verified_brief(
    proposed_brief: ResearchBrief,
    *,
    final_audit: VerifierAudit,
    analyst_retry_count: int,
    published_at: datetime,
) -> ResearchBrief:
    """Create the only brief shape permitted for new publication after Phase 17."""

    payload = proposed_brief.model_dump(mode="json")
    payload.update(
        {
            "schema_version": "2.0.0",
            "published_at": published_at.astimezone(UTC),
            "verification": PublicVerificationReceipt(
                verifier_model_name=final_audit.model_name,
                verifier_model_digest=final_audit.model_digest,
                reviewed_at=final_audit.completed_at,
                analyst_retry_count=analyst_retry_count,
            ).model_dump(mode="json"),
        }
    )
    return ResearchBrief.model_validate(payload)


def _classification(
    attention: int, risk: int, has_positive: bool, has_negative: bool
) -> RadarClassification:
    if has_positive and has_negative and min(attention, risk) >= 30:
        return RadarClassification.MIXED
    if has_positive and attention >= 35:
        return RadarClassification.OPPORTUNITY
    if has_negative and risk >= 35:
        return RadarClassification.RISK
    return RadarClassification.WATCH
