"""Private point-in-time reads for deterministic prospective-outcome science."""

from __future__ import annotations

from datetime import UTC, datetime

from kalki_market_intelligence.database import ConnectionFactory, DatabaseRow
from kalki_market_intelligence.prospective.contracts import (
    ProspectiveOutcome,
    ProspectiveOutcomePlan,
)
from kalki_market_intelligence.prospective.science import (
    OutcomePublicationVersion,
    OutcomeScienceCase,
    OutcomeSciencePopulation,
    OutcomeScienceSnapshot,
    build_outcome_science_snapshot,
)
from kalki_market_intelligence.radar.contracts import ResearchBrief


class PostgresOutcomeScienceRepository:
    """Read private immutable plans/outcomes without activating their provider."""

    def __init__(self, connection: ConnectionFactory) -> None:
        self._connection = connection

    def population_at(
        self,
        *,
        knowledge_cutoff_at: datetime,
        maximum_plans: int = 100_000,
    ) -> OutcomeSciencePopulation:
        cutoff = _utc_cutoff(knowledge_cutoff_at)
        if not 1 <= maximum_plans <= 100_000:
            raise ValueError("outcome-science plan limit must be 1-100000")
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT p.record AS plan_record,
                       o.record AS outcome_record,
                       b.record AS publication_record
                FROM research_prospective_outcome_plans p
                LEFT JOIN research_prospective_outcomes o
                  ON o.plan_id = p.plan_id AND o.appended_at <= %s
                LEFT JOIN research_briefs b ON b.brief_id = p.publication_id
                WHERE p.enrolled_at <= %s
                ORDER BY p.enrolled_at, p.publication_id, p.horizon, p.provider_name
                LIMIT %s
                """,
                (cutoff, cutoff, maximum_plans + 1),
            ).fetchall()
        if len(rows) > maximum_plans:
            raise ValueError("outcome-science population exceeds its bounded read")
        return build_outcome_science_population(tuple(rows), knowledge_cutoff_at=cutoff)

    def snapshot_at(
        self,
        *,
        knowledge_cutoff_at: datetime,
        maximum_plans: int = 100_000,
    ) -> OutcomeScienceSnapshot:
        population = self.population_at(
            knowledge_cutoff_at=knowledge_cutoff_at,
            maximum_plans=maximum_plans,
        )
        return build_outcome_science_snapshot(population)


def build_outcome_science_population(
    rows: tuple[DatabaseRow, ...],
    *,
    knowledge_cutoff_at: datetime,
) -> OutcomeSciencePopulation:
    """Revalidate joined immutable records and account for every enrolled plan."""

    cutoff = _utc_cutoff(knowledge_cutoff_at)
    cases: list[OutcomeScienceCase] = []
    not_yet_due = 0
    due_without_outcome = 0
    plan_keys: set[tuple[object, ...]] = set()
    for row in rows:
        plan = ProspectiveOutcomePlan.model_validate(row.get("plan_record"))
        plan_key = (plan.publication_id, plan.horizon, plan.provider_name)
        if plan_key in plan_keys:
            raise ValueError("outcome-science repository returned a duplicate plan")
        plan_keys.add(plan_key)
        if plan.enrolled_at > cutoff:
            raise ValueError("outcome-science repository returned a future plan")

        publication_record = row.get("publication_record")
        if publication_record is None:
            raise ValueError("outcome-science plan has no immutable publication")
        publication = ResearchBrief.model_validate(publication_record)
        publication_version = OutcomePublicationVersion.from_brief(publication)
        if (
            publication.brief_id != plan.publication_id
            or publication.published_at != plan.published_at
            or publication.ticker != plan.asset_symbol
        ):
            raise ValueError("outcome-science plan does not match its publication")

        outcome_record = row.get("outcome_record")
        if outcome_record is None:
            if plan.target_session_close_at > cutoff:
                not_yet_due += 1
            else:
                due_without_outcome += 1
            continue
        outcome = ProspectiveOutcome.model_validate(outcome_record)
        if outcome.plan != plan:
            raise ValueError("outcome-science outcome does not match its stored plan")
        if outcome.appended_at > cutoff:
            raise ValueError("outcome-science repository returned a future outcome")
        cases.append(
            OutcomeScienceCase(
                outcome=outcome,
                publication_version=publication_version,
            )
        )

    return OutcomeSciencePopulation(
        knowledge_cutoff_at=cutoff,
        enrolled_plan_count=len(rows),
        terminal_outcome_count=len(cases),
        not_yet_due_plan_count=not_yet_due,
        due_without_outcome_count=due_without_outcome,
        cases=tuple(cases),
    )


def _utc_cutoff(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("outcome-science knowledge cutoff must be timezone-aware")
    return value.astimezone(UTC)
