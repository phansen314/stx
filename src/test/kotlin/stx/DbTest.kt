package stx

import stx.repo.Db
import java.nio.file.Files
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class DbTest {
    private lateinit var dir: java.io.File
    private lateinit var db: Db

    @BeforeTest
    fun setup() {
        dir = Files.createTempDirectory("stx-db-test").toFile()
        db = Db("jdbc:sqlite:${dir.resolve("stx.db")}")
    }

    @AfterTest
    fun teardown() {
        dir.deleteRecursively()
    }

    @Test
    fun `init creates all tables and the live_task view`() {
        db.init()
        val expectedTables = setOf(
            "workspace", "status", "status_transition", "track",
            "segment", "task_kind", "task", "blocks", "relates_to",
        )
        db.connect().use { c ->
            val names = mutableSetOf<String>()
            c.createStatement().use { st ->
                st.executeQuery("SELECT name, type FROM sqlite_master WHERE type IN ('table','view')").use { rs ->
                    while (rs.next()) names += rs.getString("name")
                }
            }
            assertTrue(names.containsAll(expectedTables), "missing tables: ${expectedTables - names}")
            assertTrue("live_task" in names, "live_task view missing")
        }
    }

    @Test
    fun `connect enables foreign keys and WAL is set`() {
        db.init()
        db.connect().use { c ->
            c.createStatement().use { st ->
                st.executeQuery("PRAGMA foreign_keys").use { rs ->
                    rs.next(); assertEquals(1, rs.getInt(1), "foreign_keys not ON")
                }
                st.executeQuery("PRAGMA journal_mode").use { rs ->
                    rs.next(); assertEquals("wal", rs.getString(1).lowercase(), "WAL not set")
                }
            }
        }
    }

    @Test
    fun `init is idempotent`() {
        db.init()
        db.init() // must not throw on already-present schema
    }

    @Test
    fun `init stamps user_version to SCHEMA_VERSION`() {
        db.init()
        db.connect().use { c ->
            c.createStatement().use { st ->
                st.executeQuery("PRAGMA user_version").use {
                    assertTrue(it.next())
                    assertEquals(Db.SCHEMA_VERSION, it.getInt(1))
                }
            }
        }
    }

    @Test
    fun `init refuses a database newer than the daemon`() {
        db.init()
        db.connect().use { c -> c.createStatement().use { it.execute("PRAGMA user_version = 999") } }
        val ex = assertFailsWith<IllegalStateException> { db.init() }
        assertTrue(ex.message!!.contains("refusing to downgrade"), "unexpected: ${ex.message}")
    }

    @Test
    fun `init rejects a pre-versioning database - tables present but user_version 0`() {
        // Crash-truncated / pre-versioning load: a table exists but user_version was never stamped.
        // The old code re-ran the schema and CREATE-failed opaquely; now it surfaces clearly.
        db.connect().use { c ->
            c.createStatement().use { it.execute("CREATE TABLE workspace (id INTEGER PRIMARY KEY)") }
        }
        val ex = assertFailsWith<IllegalStateException> { db.init() }
        assertTrue(ex.message!!.contains("user_version=0"), "unexpected: ${ex.message}")
    }

    @Test
    fun `runMigrations applies a registered forward migration and bumps user_version`() {
        db.init() // fresh at SCHEMA_VERSION
        val next = Db.SCHEMA_VERSION + 1 // relative, so shipping a real migration doesn't break this
        db.connect().use { c ->
            db.runMigrations(c, target = next, migrations = mapOf(next to "/migrations/test_002.sql"))
            assertEquals(next, c.createStatement().use { st -> st.executeQuery("PRAGMA user_version").use { it.next(); it.getInt(1) } })
            val applied = c.createStatement().use { st ->
                st.executeQuery("SELECT 1 FROM sqlite_master WHERE type='table' AND name='migration_probe'").use { it.next() }
            }
            assertTrue(applied, "migration DDL did not apply")
        }
    }

    @Test
    fun `runMigrations fails when a version in the chain has no registered migration`() {
        db.init()
        val next = Db.SCHEMA_VERSION + 1
        db.connect().use { c ->
            val ex = assertFailsWith<IllegalStateException> {
                db.runMigrations(c, target = next + 1, migrations = mapOf(next to "/migrations/test_002.sql"))
            }
            assertTrue(ex.message!!.contains("v${next + 1}"), "must name the missing version: ${ex.message}")
        }
    }

    @Test
    fun `a migration that leaves an FK violation rolls back fully - version does not advance`() {
        db.init() // fresh at SCHEMA_VERSION
        val next = Db.SCHEMA_VERSION + 1
        db.connect().use { c ->
            fun userVersion() = c.createStatement().use { st ->
                st.executeQuery("PRAGMA user_version").use { it.next(); it.getInt(1) }
            }
            fun taskCount() = c.createStatement().use { st ->
                st.executeQuery("SELECT count(*) FROM task").use { it.next(); it.getInt(1) }
            }
            val before = userVersion()
            val ex = assertFailsWith<IllegalStateException> {
                db.runMigrations(c, target = next, migrations = mapOf(next to "/migrations/test_bad_fk.sql"))
            }
            assertTrue(ex.message!!.contains("foreign-key"), "unexpected: ${ex.message}")
            assertEquals(before, userVersion(), "user_version must NOT advance past a failed migration")
            assertEquals(0, taskCount(), "the failed migration's rows must roll back")
            // FK enforcement must be restored for subsequent connections.
            c.createStatement().use { st ->
                st.executeQuery("PRAGMA foreign_keys").use { assertTrue(it.next()); assertEquals(1, it.getInt(1)) }
            }
        }
    }

    @Test
    fun `runMigrations refuses a downgrade`() {
        db.init()
        db.connect().use { c ->
            c.createStatement().use { it.execute("PRAGMA user_version = 5") }
            val ex = assertFailsWith<IllegalStateException> { db.runMigrations(c, target = 1, migrations = emptyMap()) }
            assertTrue(ex.message!!.contains("refusing to downgrade"), "unexpected: ${ex.message}")
        }
    }

    @Test
    fun `splitStatements ignores semicolons and comment markers inside string literals`() {
        val stmts = Db.splitStatements("INSERT INTO t VALUES ('a; -- b'); CREATE TABLE u (x);")
        assertEquals(2, stmts.size, "string-internal ; / -- must not split or truncate: $stmts")
        assertTrue(stmts[0].contains("'a; -- b'"))
    }

    /**
     * The shipped migration, against a POPULATED v1 database — the case `runMigrations` has never
     * actually seen (the registry was empty until 002). `schema_v1.sql` is a frozen copy of the
     * schema as of the v3.0.0 tag, so this is the real upgrade path, not a synthetic one.
     */
    @Test
    fun `migration 002 upgrades a populated v1 database without touching its rows`() {
        seedV1Database()

        db.init() // sees user_version=1 and runs the registered migration chain

        db.connect().use { c ->
            fun scalar(sql: String) = c.createStatement().use { st -> st.executeQuery(sql).use { it.next(); it.getString(1) } }
            assertEquals(Db.SCHEMA_VERSION.toString(), scalar("PRAGMA user_version"))
            // the pre-existing row survived verbatim and reads as UNCLAIMED, which is exactly the
            // pre-migration behavior — a migration must not reserve anything
            assertEquals("pre-existing work", scalar("SELECT title FROM task WHERE id=1"))
            assertEquals("0", scalar("SELECT count(*) FROM task WHERE claimed_by IS NOT NULL OR claimed_until IS NOT NULL"))
            assertEquals("1", scalar("SELECT count(*) FROM sqlite_master WHERE type='index' AND name='ix_task_claim'"))
            // the columns are usable, not merely present
            c.createStatement().use {
                it.execute("UPDATE task SET claimed_by='a1', claimed_until=datetime('now','+60 seconds') WHERE id=1")
            }
            assertEquals("a1", scalar("SELECT claimed_by FROM task WHERE id=1"))
            c.createStatement().use { st ->
                st.executeQuery("PRAGMA foreign_key_check").use { assertTrue(!it.next(), "migration left FK violations") }
            }
        }
        db.init() // already at target: a second boot must be a no-op, not a re-apply
        db.assertConsistent()
    }

    /** A v1-schema database with one task in it, stamped user_version=1 (pre-002). */
    private fun seedV1Database() {
        val v1 = DbTest::class.java.getResourceAsStream("/schema_v1.sql")!!.bufferedReader().use { it.readText() }
        db.connect().use { c ->
            c.createStatement().use { st ->
                st.execute("PRAGMA journal_mode = WAL")
                Db.splitStatements(v1).forEach { st.execute(it) }
                st.execute("INSERT INTO workspace(id, name) VALUES (1, 'ws')")
                st.execute("INSERT INTO status(id, workspace_id, name, kanban_order, is_default) VALUES (1, 1, 'Backlog', 0, 1)")
                st.execute("INSERT INTO track(id, workspace_id, name) VALUES (1, 1, 'main')")
                st.execute("INSERT INTO segment(id, workspace_id, track_id, name, is_root) VALUES (1, 1, 1, '(root)', 1)")
                st.execute("INSERT INTO task(id, workspace_id, segment_id, status_id, title) VALUES (1, 1, 1, 1, 'pre-existing work')")
                st.execute("PRAGMA user_version = 1")
            }
        }
    }

    @Test
    fun `assertConsistent passes on a freshly initialised database`() {
        db.init()
        db.assertConsistent() // empty schema has no orphans
    }
}
