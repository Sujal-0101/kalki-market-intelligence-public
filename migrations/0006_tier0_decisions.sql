BEGIN;

ALTER TABLE research_candidates
    ADD COLUMN tier_outcome text CHECK (tier_outcome IN ('skip', 'retain', 'escalate')),
    ADD COLUMN tier_reason text,
    ADD COLUMN tier_evidence_ids uuid[] NOT NULL DEFAULT '{}',
    ADD COLUMN tier_decision_record jsonb;

CREATE INDEX research_candidates_tier_outcome_idx
    ON research_candidates (tier_outcome, filed_at DESC);

INSERT INTO schema_migrations (version) VALUES ('0006_tier0_decisions');

COMMIT;
