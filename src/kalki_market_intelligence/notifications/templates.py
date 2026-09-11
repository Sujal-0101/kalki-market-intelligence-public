"""Deterministic, research-only Discord message templates."""

from datetime import date
from hashlib import sha256
from uuid import UUID

from pydantic import Field, model_validator

from kalki_market_intelligence.contracts.common import ContractModel, Sha256Hex, UtcDatetime
from kalki_market_intelligence.notifications.contracts import DiscordPayload
from kalki_market_intelligence.predictions.contracts import PredictionRecord
from kalki_market_intelligence.radar.contracts import ResearchBrief
from kalki_market_intelligence.radar.sec_links import PublicSecFilingLinks
from kalki_market_intelligence.signals.contracts import RiskProfile, SignalLabel

TEMPLATE_VERSION = "discord-research-v1"
RADAR_TEMPLATE_VERSION = "discord-radar-v2"
DISCLAIMER = "Research only — not financial advice or a trade instruction. No action is requested."


class ResearchNotification(ContractModel):
    """Minimum immutable publication fields permitted in an outbound alert."""

    prediction_id: UUID
    published_at: UtcDatetime
    label: SignalLabel
    risk_profile: RiskProfile
    opportunity_points: int = Field(ge=0, le=100)
    risk_points: int = Field(ge=0, le=100)
    research_confidence_points: int = Field(ge=0, le=100)
    horizon_days: int = Field(ge=30, le=180)
    evaluation_due_on: date
    evidence_count: int = Field(ge=1)
    signal_fingerprint: Sha256Hex

    @classmethod
    def from_prediction(cls, prediction: PredictionRecord) -> "ResearchNotification":
        return cls(
            prediction_id=prediction.prediction_id,
            published_at=prediction.published_at,
            label=prediction.label,
            risk_profile=prediction.risk_profile,
            opportunity_points=prediction.scores.opportunity_points,
            risk_points=prediction.scores.risk_points,
            research_confidence_points=prediction.scores.research_confidence_points,
            horizon_days=prediction.horizon_days,
            evaluation_due_on=prediction.evaluation_due_on,
            evidence_count=len(prediction.evidence),
            signal_fingerprint=prediction.versions.signal_fingerprint,
        )

    @property
    def notification_key(self) -> str:
        source = f"{TEMPLATE_VERSION}\n{self.prediction_id}\n{self.signal_fingerprint}"
        return sha256(source.encode()).hexdigest()


def render_research_notification(notification: ResearchNotification) -> DiscordPayload:
    """Render bounded facts without thesis prose, mentions, or action language."""

    content = "\n".join(
        (
            "**Kalki Market Intelligence — Published research update**",
            DISCLAIMER,
            f"Prediction: `{notification.prediction_id}`",
            f"Published: {notification.published_at.isoformat().replace('+00:00', 'Z')}",
            f"Label: {notification.label.value}",
            f"Risk profile: {notification.risk_profile.value}",
            f"Opportunity: {notification.opportunity_points}/100 heuristic points",
            f"Risk: {notification.risk_points}/100 heuristic points",
            (
                "Research confidence: "
                f"{notification.research_confidence_points}/100 ordinal support points "
                "(not a probability)"
            ),
            (
                f"Horizon: {notification.horizon_days} calendar days; "
                f"evaluation due {notification.evaluation_due_on.isoformat()}"
            ),
            f"Evidence records: {notification.evidence_count}",
            f"Signal fingerprint: `{notification.signal_fingerprint}`",
        )
    )
    return DiscordPayload(content=content)


def render_connection_test() -> DiscordPayload:
    """Render a synthetic connectivity check containing no market assertion."""

    return DiscordPayload(
        content=(
            "**Kalki Market Intelligence — Discord connection test**\n"
            f"{DISCLAIMER}\n"
            "This is a synthetic transport test. It contains no market data, prediction, or signal."
        )
    )


class RadarNotification(ContractModel):
    """Bounded public filing-radar fields permitted in an outbound alert."""

    brief: ResearchBrief
    sec_links: PublicSecFilingLinks | None = None

    @model_validator(mode="after")
    def links_match_brief(self) -> "RadarNotification":
        if self.sec_links is not None and (
            self.sec_links.accession_number != self.brief.accession_number
            or self.sec_links.complete_submission_url != self.brief.source_url
        ):
            raise ValueError("public SEC links do not match the radar brief")
        return self

    @property
    def notification_key(self) -> str:
        source = (
            f"{RADAR_TEMPLATE_VERSION}\n{self.brief.brief_id}\n{self.brief.source_document_sha256}"
        )
        return sha256(source.encode()).hexdigest()


def render_radar_notification(
    notification: RadarNotification,
    *,
    public_hostname: str = "localhost",
) -> DiscordPayload:
    brief = notification.brief
    ticker = brief.ticker or f"CIK {brief.cik}"
    public_url = f"https://{public_hostname}/radar/{brief.brief_id}"
    lines = [
        f"**Kalki Filing Radar — {ticker} · {brief.classification.value.title()}**",
        DISCLAIMER,
        brief.headline,
        brief.why_it_matters,
        f"Research attention: {brief.attention_points}/100 heuristic priority points",
        f"Risk: {brief.risk_points}/100 heuristic points",
        f"Evidence strength: {brief.evidence_strength_points}/100 ordinal support points",
        f"Filed form: {brief.filing_form} · SEC accession `{brief.accession_number}`",
        f"Evidence: {len(brief.evidence)} exact SEC quotation(s)",
        f"Read the evidence-backed brief: {public_url}",
    ]
    if notification.sec_links is not None:
        lines.append(
            f"Validated SEC primary document: {notification.sec_links.primary_document_url}"
        )
    content = "\n".join(lines)
    return DiscordPayload(content=content)
