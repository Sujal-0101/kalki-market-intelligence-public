BEGIN;

DROP INDEX predictions_publication_order_idx;
DELETE FROM schema_migrations WHERE version = '0003_publication_list_index';

COMMIT;
