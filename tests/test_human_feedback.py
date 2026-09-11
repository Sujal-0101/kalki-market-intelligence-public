from datetime import UTC, datetime

from kalki_market_intelligence.research.feedback import FeedbackType, HumanResearchFeedback


def test_feedback_is_bounded_and_utc() -> None:
    feedback = HumanResearchFeedback(
        research_reference="pub-123",
        submitter_user_id="12345678901234567",
        submitted_at=datetime(2026, 1, 1, tzinfo=UTC),
        feedback_type=FeedbackType.USEFUL,
        note="  useful context  ",
    )
    assert feedback.note == "useful context"
    assert feedback.submitted_at.tzinfo is UTC


def test_feedback_rejects_invalid_discord_identity() -> None:
    try:
        HumanResearchFeedback(
            research_reference="pub-123",
            submitter_user_id="not-a-snowflake",
            submitted_at=datetime.now(UTC),
            feedback_type=FeedbackType.OTHER,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("invalid identity accepted")
