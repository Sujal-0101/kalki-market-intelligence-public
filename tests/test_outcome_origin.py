"""Outcome origin is explicit so forward evidence is not confused with backfill."""

from kalki_market_intelligence.predictions import ObservationOrigin


def test_observation_origin_vocabulary_is_closed() -> None:
    assert ObservationOrigin.FORWARD.value == "forward"
    assert ObservationOrigin.RECONSTRUCTED.value == "reconstructed"
