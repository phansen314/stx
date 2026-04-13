-- Migration 017: drop tags feature
--
-- Removes the tags and task_tags tables along with their indexes. Per-entity
-- metadata JSON blobs now cover the tagging use case. Historical journal rows
-- are left untouched intentionally (journal.entity_type is an unconstrained
-- TEXT column, so dead 'tag'/'task_tag' rows remain decodable as-is).

DROP INDEX IF EXISTS idx_task_tags_tag_id;
DROP INDEX IF EXISTS idx_tags_workspace_archived_name;
DROP INDEX IF EXISTS uq_tags_workspace_name_active;
DROP TABLE IF EXISTS task_tags;
DROP TABLE IF EXISTS tags;
