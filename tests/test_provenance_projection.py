"""Private-safe dossier provenance projection tests."""

from kalki_market_intelligence.benchmarking.verifier_cases import verifier_qualification_cases
from kalki_market_intelligence.verification import dossier_provenance


def test_projection_retains_lineage_without_model_trace_fields() -> None:
    package = verifier_qualification_cases()[0].package
    assert package is not None
    projection = dossier_provenance(package)
    assert projection["accession_number"]
    assert projection["source_document_sha256"]
    assert projection["evidence"]
    assert "prompt" not in projection
    assert "chain_of_thought" not in projection
    assert "raw_response" not in projection
