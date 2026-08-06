-- 002 — agent claim / lease (schema v1 -> v2).
--
-- Adds the two lease columns specified in schema.sql since day one, gated on "the moment a second
-- concurrent agent runs". Purely additive: two nullable columns and one partial index, no data
-- rewritten, no table rebuilt. Every existing task reads as free (both columns NULL), which is
-- exactly the pre-migration behavior — nothing is reserved until an agent claims it.
--
-- The CHECK on the pair ((claimed_by IS NULL) = (claimed_until IS NULL)) that the fresh-install
-- schema carries is deliberately NOT added here: SQLite cannot add a table-level CONSTRAINT to an
-- existing table without a full 12-step table rebuild, and the rebuild's cost/risk is not worth a
-- backstop for an invariant the daemon already enforces (both columns are written together, in one
-- statement, by one code path). A migrated DB is therefore structurally identical to a fresh one
-- except for that CHECK; the daemon behaves the same on both.
--
-- The `live_task` view needs no rebuild: it is defined as `SELECT t.*`, and SQLite stores a view's
-- SQL text and re-expands the star at query time, so the new columns appear in it automatically.

ALTER TABLE task ADD COLUMN claimed_by    TEXT;
ALTER TABLE task ADD COLUMN claimed_until TEXT;

CREATE INDEX ix_task_claim ON task(claimed_until) WHERE archived = 0 AND claimed_until IS NOT NULL;
