"""Append-only application ledger; PostgreSQL adds database-level guards."""

from __future__ import annotations

from hashlib import sha256
from typing import TypeVar
from uuid import UUID

from kalki_market_intelligence.contracts.common import ContractModel
from kalki_market_intelligence.predictions.contracts import (
    OutcomeRecord,
    PredictionCorrection,
    PredictionRecord,
)

RecordT = TypeVar("RecordT", bound=ContractModel)


class DuplicateRecordError(ValueError):
    """Raised when an append would reuse an immutable record ID."""


class ImmutableRecordError(RuntimeError):
    """Raised for every attempted update or deletion."""


class UnknownPredictionError(ValueError):
    """Raised when a child record has no published parent prediction."""


class MemoryPredictionLedger:
    """Deterministic test/local ledger with no mutation surface."""

    def __init__(self) -> None:
        self._predictions: list[PredictionRecord] = []
        self._corrections: list[PredictionCorrection] = []
        self._outcomes: list[OutcomeRecord] = []
        self._hash_chain: list[str] = []

    def append_prediction(self, record: PredictionRecord) -> str:
        self._ensure_new(record.prediction_id, self._predictions, "prediction_id")
        self._predictions.append(record)
        return self._append_hash("prediction", record)

    def append_correction(self, record: PredictionCorrection) -> str:
        prediction = self._require_prediction(record.prediction_id)
        if record.appended_at < prediction.published_at:
            raise ValueError("prediction correction cannot predate publication")
        self._ensure_new(record.correction_id, self._corrections, "correction_id")
        self._corrections.append(record)
        return self._append_hash("correction", record)

    def append_outcome(self, record: OutcomeRecord) -> str:
        prediction = self._require_prediction(record.prediction_id)
        if record.evaluated_at.date() < prediction.evaluation_due_on:
            raise ValueError("prediction outcome cannot predate its declared horizon")
        if record.evaluation_rule is not prediction.evaluation_rule:
            raise ValueError("prediction outcome changed the declared evaluation rule")
        self._ensure_new(record.outcome_id, self._outcomes, "outcome_id")
        self._outcomes.append(record)
        return self._append_hash("outcome", record)

    @property
    def predictions(self) -> tuple[PredictionRecord, ...]:
        return tuple(self._predictions)

    @property
    def corrections(self) -> tuple[PredictionCorrection, ...]:
        return tuple(self._corrections)

    @property
    def outcomes(self) -> tuple[OutcomeRecord, ...]:
        return tuple(self._outcomes)

    @property
    def chain_head(self) -> str | None:
        return self._hash_chain[-1] if self._hash_chain else None

    def update_prediction(self, *_: object, **__: object) -> None:
        raise ImmutableRecordError("published predictions cannot be updated")

    def delete_prediction(self, *_: object, **__: object) -> None:
        raise ImmutableRecordError("published predictions cannot be deleted")

    def _append_hash(self, kind: str, record: ContractModel) -> str:
        previous = self._hash_chain[-1] if self._hash_chain else "0" * 64
        digest = sha256(f"{previous}\n{kind}\n{record.model_dump_json()}".encode()).hexdigest()
        self._hash_chain.append(digest)
        return digest

    def _require_prediction(self, prediction_id: UUID) -> PredictionRecord:
        for item in self._predictions:
            if item.prediction_id == prediction_id:
                return item
        raise UnknownPredictionError("child record requires an existing prediction")

    @staticmethod
    def _ensure_new(
        record_id: UUID,
        records: list[RecordT],
        id_field: str,
    ) -> None:
        if any(getattr(item, id_field) == record_id for item in records):
            raise DuplicateRecordError(f"duplicate append-only {id_field}")
