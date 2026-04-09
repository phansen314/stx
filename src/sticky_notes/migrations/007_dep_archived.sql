-- Add archived column to task_dependencies and group_dependencies

CREATE TABLE task_dependencies_new (
    task_id INTEGER NOT NULL,
    depends_on_id INTEGER NOT NULL,
    workspace_id INTEGER NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    PRIMARY KEY (task_id, depends_on_id),
    CHECK (task_id != depends_on_id),
    FOREIGN KEY (task_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (depends_on_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE
);
INSERT INTO task_dependencies_new (task_id, depends_on_id, workspace_id, archived)
    SELECT task_id, depends_on_id, workspace_id, 0 FROM task_dependencies;
DROP TABLE task_dependencies;
ALTER TABLE task_dependencies_new RENAME TO task_dependencies;
CREATE INDEX idx_task_dependencies_depends_on_id ON task_dependencies(depends_on_id);

CREATE TABLE group_dependencies_new (
    group_id      INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    depends_on_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    workspace_id  INTEGER NOT NULL REFERENCES workspaces(id),
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    PRIMARY KEY (group_id, depends_on_id),
    CHECK (group_id != depends_on_id)
);
INSERT INTO group_dependencies_new (group_id, depends_on_id, workspace_id, archived)
    SELECT group_id, depends_on_id, workspace_id, 0 FROM group_dependencies;
DROP TABLE group_dependencies;
ALTER TABLE group_dependencies_new RENAME TO group_dependencies;
CREATE INDEX idx_group_dependencies_depends_on_id ON group_dependencies(depends_on_id);
