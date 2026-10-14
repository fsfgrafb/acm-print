ALTER TABLE system_state ADD COLUMN submit_visit_count BIGINT NOT NULL DEFAULT 0;
CREATE TABLE submit_page_visits (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX submit_page_visits_created_at_idx ON submit_page_visits (created_at);
