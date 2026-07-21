package stx.repo

import java.sql.Connection
import java.sql.DriverManager

/**
 * Owns SQLite connection setup and one-time schema initialisation (brief §6, build step 2).
 *
 * Concurrency model (brief §6): SQLite in WAL mode is the entire story — a single
 * write-actor connection serialises mutations, while read connections run concurrently.
 * WAL is persisted in the database file header, so it is set once at [init]; `foreign_keys`
 * and `busy_timeout` are per-connection and re-applied by every [connect].
 *
 * Use a file-backed url (`jdbc:sqlite:/path/stx.db`). A bare `:memory:` url gives each
 * connection its own empty database, which breaks the multi-connection model — tests use a
 * temp file instead.
 */
class Db(private val url: String) {

    /** Open a connection with the per-connection pragmas every caller needs. */
    fun connect(): Connection =
        DriverManager.getConnection(url).apply {
            createStatement().use { st ->
                st.execute("PRAGMA foreign_keys = ON")
                st.execute("PRAGMA busy_timeout = 5000")
            }
        }

    /**
     * Set WAL (persistent), then either load the schema (fresh DB) or run pending migrations
     * (existing DB). Versioning uses SQLite's native `PRAGMA user_version`, mirroring the runner
     * in ~/code/stx: a fresh DB reads version 0; a loaded DB carries [SCHEMA_VERSION]. Idempotent.
     */
    fun init() {
        connect().use { c ->
            c.createStatement().use { it.execute("PRAGMA journal_mode = WAL") }
            if (userVersion(c) == 0) {
                // user_version 0 == never initialised. Tables already present at v0 means a
                // pre-versioning or crash-truncated load — surface it instead of CREATE-failing.
                check(!schemaPresent(c)) {
                    "stx database has tables but user_version=0 (pre-versioning or partial load); " +
                        "back up and recreate the database."
                }
                inTransaction(c) { execStatements(c, loadResource(SCHEMA_RESOURCE)) }
                setUserVersion(c, SCHEMA_VERSION)
            } else {
                runMigrations(c)
            }
        }
    }

    private fun schemaPresent(c: Connection): Boolean =
        c.createStatement().use { st ->
            st.executeQuery("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspace'")
                .use { it.next() }
        }

    /**
     * Apply every forward migration from the on-disk `user_version` up to [target] (C3), each in
     * its own transaction with the version bump, mirroring ~/code/stx's runner. Foreign keys are
     * disabled across each migration (so table-rebuild patterns work) then re-validated with
     * `foreign_key_check`. Refuses a DB newer than this daemon understands. [migrations] maps a
     * target version -> classpath path of the script that produces it; injectable for tests.
     */
    internal fun runMigrations(c: Connection, target: Int = SCHEMA_VERSION, migrations: Map<Int, String> = MIGRATIONS) {
        val current = userVersion(c)
        check(current <= target) {
            "stx database schema v$current is newer than this daemon (v$target); refusing to downgrade — upgrade stx."
        }
        for (v in current + 1..target) {
            val path = migrations[v] ?: error("stx cannot upgrade v${v - 1} -> v$v: no migration registered for v$v.")
            val sql = loadResource(path)
            // Enforcement toggles are ignored inside a transaction, so disable OUTSIDE it (table-
            // rebuild patterns need FKs off mid-migration). `foreign_key_check` is a manual scan that
            // works with enforcement off AND inside the txn — run it BEFORE setUserVersion/commit so a
            // violation rolls the whole migration back (data + version bump). Checking after commit
            // would leave the DB durably advanced past a broken migration that no restart re-checks.
            c.createStatement().use { it.execute("PRAGMA foreign_keys = OFF") }
            try {
                inTransaction(c) {
                    execStatements(c, sql)
                    val violations = foreignKeyViolations(c)
                    check(violations.isEmpty()) { "stx migration to v$v left foreign-key violations: $violations" }
                    setUserVersion(c, v)
                }
            } finally {
                runCatching { c.createStatement().use { it.execute("PRAGMA foreign_keys = ON") } }
            }
        }
    }

    private fun userVersion(c: Connection): Int =
        c.createStatement().use { st -> st.executeQuery("PRAGMA user_version").use { it.next(); it.getInt(1) } }

    /** PRAGMA cannot bind parameters; [v] is a daemon-internal Int, never user input. */
    private fun setUserVersion(c: Connection, v: Int) =
        c.createStatement().use { it.execute("PRAGMA user_version = $v") }

    private fun foreignKeyViolations(c: Connection): List<String> =
        c.createStatement().use { st ->
            st.executeQuery("PRAGMA foreign_key_check").use { rs ->
                buildList { while (rs.next()) add(rs.getString(1)) }
            }
        }

    /**
     * Defense-in-depth integrity check the schema foot (#6) promises: NO live task may sit under
     * an archived container — including an archived ANCESTOR segment, walked recursively up
     * parent_segment_id. The `live_task` view deliberately cannot see ancestor archival, so a
     * cascade bug would otherwise be silently masked on reads. Call once at startup (Main): throw
     * with the offending task ids so the bug surfaces instead of quietly orphaning work.
     */
    fun assertConsistent() {
        connect().use { c ->
            // Enabling foreign_keys per-connection does NOT retro-validate existing rows, so scan
            // explicitly: catches any dangling FK from a legacy/tampered DB (or a pre-fix migration)
            // loudly at boot rather than serving it.
            val fkViolations = foreignKeyViolations(c)
            check(fkViolations.isEmpty()) {
                "stx integrity check failed: foreign-key violations in table(s) $fkViolations"
            }
            val orphans = scanIds(c, ORPHAN_QUERY)
            check(orphans.isEmpty()) {
                "stx integrity check failed: live task(s) under an archived container (cascade bug): $orphans"
            }
            // #8 defense-in-depth (symmetric with the orphan scan for #6): the denormalized
            // workspace_id on task/segment must equal the workspace reached via the track chain.
            // The daemon enforces this on every write, but the live_task view joins task.workspace_id
            // AND segment->track->workspace WITHOUT asserting they are equal — so a drift would serve
            // wrong-workspace rows silently. Surface it loudly at boot instead.
            val drifted = scanIds(c, COHERENCE_QUERY)
            check(drifted.isEmpty()) {
                "stx integrity check failed: live task(s) whose workspace_id drifted from the track chain (#8): $drifted"
            }
        }
    }

    private fun scanIds(c: Connection, query: String): List<Long> =
        c.createStatement().use { st ->
            st.executeQuery(query).use { rs -> buildList { while (rs.next()) add(rs.getLong(1)) } }
        }

    private fun loadResource(path: String): String =
        Db::class.java.getResourceAsStream(path)
            ?.bufferedReader()?.use { it.readText() }
            ?: error("resource $path not found on classpath")

    /**
     * Run an all-or-nothing block on [c] in one transaction (C2): a failure partway through
     * rolls back fully, so a crash mid-load never leaves a half-built DB the next boot would
     * mistake for ready (`user_version` would also still be 0). Restores the prior autocommit.
     */
    private fun <T> inTransaction(c: Connection, block: () -> T): T {
        val prevAutoCommit = c.autoCommit
        c.autoCommit = false
        return try {
            val r = block()
            c.commit()
            r
        } catch (t: Throwable) {
            runCatching { c.rollback() }
            throw t
        } finally {
            runCatching { c.autoCommit = prevAutoCommit }
        }
    }

    /** Execute a multi-statement SQL script (xerial runs one statement per call). */
    private fun execStatements(c: Connection, script: String) {
        c.createStatement().use { st -> splitStatements(script).forEach { st.execute(it) } }
    }

    companion object {
        const val SCHEMA_RESOURCE = "/schema.sql"

        /**
         * Schema version this daemon understands; stamped into `PRAGMA user_version` on fresh load.
         * Bump by exactly 1 whenever you add a migration, and register its script in [MIGRATIONS].
         */
        const val SCHEMA_VERSION = 1

        /**
         * version -> classpath path of the forward migration that PRODUCES that version
         * (migrations[n] upgrades a v(n-1) DB to vn). Explicit registry rather than directory
         * scanning so it resolves identically from a jar. Empty until the first schema change, e.g.
         *   mapOf(2 to "/migrations/002_add_xyz.sql")
         */
        private val MIGRATIONS: Map<Int, String> = emptyMap()

        /**
         * Split a SQL script into statements (xerial runs one per call). Tracks single-quoted
         * string literals so a `;` or `--` inside a literal does not slice a statement or get
         * mistaken for a comment (ported from ~/code/stx). The doubled `''` escape falls out of
         * the toggle naturally. Out-of-string `-- ...` runs to end of line.
         */
        internal fun splitStatements(script: String): List<String> {
            val out = mutableListOf<String>()
            val buf = StringBuilder()
            var inStr = false
            var i = 0
            while (i < script.length) {
                val ch = script[i]
                when {
                    ch == '\'' -> { inStr = !inStr; buf.append(ch) }
                    !inStr && ch == '-' && i + 1 < script.length && script[i + 1] == '-' -> {
                        while (i < script.length && script[i] != '\n') i++
                        continue
                    }
                    !inStr && ch == ';' -> { buf.toString().trim().takeIf { it.isNotEmpty() }?.let { out += it }; buf.clear() }
                    else -> buf.append(ch)
                }
                i++
            }
            buf.toString().trim().takeIf { it.isNotEmpty() }?.let { out += it }
            return out
        }

        /**
         * Live tasks under an archived container, incl. an archived ANCESTOR segment (recursive
         * walk up parent_segment_id) — the orphan case `live_task` cannot see. Returns task ids.
         */
        private val ORPHAN_QUERY =
            """
            WITH RECURSIVE seg_anc(task_id, seg_id) AS (
                SELECT t.id, t.segment_id FROM task t WHERE t.archived = 0
                UNION ALL
                SELECT sa.task_id, s.parent_segment_id
                FROM seg_anc sa JOIN segment s ON s.id = sa.seg_id
                WHERE s.parent_segment_id IS NOT NULL
            )
            SELECT DISTINCT t.id FROM task t WHERE t.archived = 0 AND (
                EXISTS (SELECT 1 FROM workspace w WHERE w.id = t.workspace_id AND w.archived = 1)
                OR EXISTS (SELECT 1 FROM segment s JOIN track k ON k.id = s.track_id WHERE s.id = t.segment_id AND k.archived = 1)
                OR EXISTS (SELECT 1 FROM seg_anc sa JOIN segment s ON s.id = sa.seg_id WHERE sa.task_id = t.id AND s.archived = 1)
            )
            """.trimIndent()

        /**
         * #8 coherence: live tasks whose denormalized workspace_id disagrees with the workspace
         * reached through segment->track (or whose own segment's workspace_id disagrees with its
         * track). The daemon derives these on write so they can't drift in normal operation; this
         * catches a legacy/tampered/buggy DB before it serves cross-workspace rows.
         */
        private val COHERENCE_QUERY =
            """
            SELECT t.id
            FROM task t
            JOIN segment s ON s.id = t.segment_id
            JOIN track   k ON k.id = s.track_id
            WHERE t.archived = 0
              AND (t.workspace_id <> k.workspace_id OR s.workspace_id <> k.workspace_id)
            """.trimIndent()
    }
}
