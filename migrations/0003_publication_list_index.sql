BEGIN;

CREATE INDEX predictions_publication_order_idx
    ON predictions (published_at DESC, prediction_id DESC);

INSERT INTO schema_migrations (version) VALUES ('0003_publication_list_index');

COMMIT;
