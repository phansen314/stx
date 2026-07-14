-- Test-only migration (not shipped). Exercises the Db migration runner: a plain DDL
-- statement plus a comment containing a semicolon-like token ';' inside a string literal
-- to confirm the statement splitter is string-aware.
CREATE TABLE migration_probe (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    note  TEXT NOT NULL DEFAULT 'a; not a statement end'
);
