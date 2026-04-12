CREATE TABLE IF NOT EXISTS group_dependencies (
    group_id      INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    depends_on_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    board_id      INTEGER NOT NULL REFERENCES boards(id),
    PRIMARY KEY (group_id, depends_on_id),
    CHECK (group_id != depends_on_id)
);

CREATE INDEX IF NOT EXISTS idx_group_dependencies_depends_on_id
    ON group_dependencies(depends_on_id);
