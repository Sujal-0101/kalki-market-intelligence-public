"""Read-only web repository and public projection tests."""

from datetime import timedelta
from uuid import UUID

import pytest
from test_live_radar import brief
from test_prediction_outcomes import prediction

from kalki_market_intelligence.predictions.contracts import PredictionRecord
from kalki_market_intelligence.web.contracts import public_detail, public_index_item, public_summary
from kalki_market_intelligence.web.repository import MemoryResearchRepository


def test_repository_is_read_only_unique_and_newest_first() -> None:
    older = prediction()
    newer = older.model_copy(
        update={
            "prediction_id": UUID("10000000-0000-4000-8000-000000000002"),
            "published_at": older.published_at + timedelta(minutes=1),
        }
    )
    repository = MemoryResearchRepository((older, newer))

    assert repository.list_predictions() == (newer, older)
    assert repository.list_predictions(limit=1) == (newer,)
    assert repository.list_predictions(limit=1, offset=1) == (older,)
    with pytest.raises(ValueError, match="between one and 500"):
        repository.list_predictions(limit=501)
    with pytest.raises(ValueError, match="between zero and 100000"):
        repository.list_predictions(offset=-1)
    assert repository.get_prediction(older.prediction_id) is older
    assert not hasattr(repository, "append_prediction")
    with pytest.raises(ValueError, match="must be unique"):
        MemoryResearchRepository((older, older))


def test_public_projection_retains_evidence_and_omits_operational_identity() -> None:
    record = prediction()
    summary = public_summary(record)
    detail = public_detail(record)

    assert summary.evidence_count == len(record.evidence)
    assert detail.thesis == record.thesis
    assert detail.evidence[0].content_sha256 == record.evidence[0].content_sha256
    assert "published_by" not in detail.model_dump()
    assert "metric_input_hashes" not in detail.model_dump()
    assert summary.model_json_schema()["additionalProperties"] is False
    assert detail.model_json_schema()["additionalProperties"] is False


def test_combined_publication_index_is_exact_typed_ordered_and_paginated() -> None:
    forecast = prediction()
    dossier = brief()
    repository = MemoryResearchRepository((forecast,), briefs=(dossier,))

    records = repository.list_publications()
    projected = tuple(public_index_item(item) for item in records)

    assert records == (dossier, forecast)
    assert repository.list_publications(limit=1) == (dossier,)
    assert repository.list_publications(limit=1, offset=1) == (forecast,)
    assert [item.record_type for item in projected] == ["dossier", "forecast"]
    assert projected[0].canonical_url == f"/radar/{dossier.brief_id}"
    assert projected[1].canonical_url == f"/research/{forecast.prediction_id}"
    assert len({(item.record_type, item.canonical_url) for item in projected}) == 2
    assert all(item.model_json_schema()["additionalProperties"] is False for item in projected)


def test_combined_publication_index_breaks_cross_table_ties_deterministically() -> None:
    forecast_payload = prediction().model_dump(mode="json")
    dossier = brief()
    forecast_payload.update(
        {
            "prediction_id": str(dossier.brief_id),
            "published_at": dossier.published_at.isoformat(),
        }
    )
    forecast = PredictionRecord.model_validate(forecast_payload)

    records = MemoryResearchRepository((forecast,), briefs=(dossier,)).list_publications()

    assert records == (dossier, forecast)
