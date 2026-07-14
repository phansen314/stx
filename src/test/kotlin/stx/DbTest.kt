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
        db.connect().use { c ->
            db.runMigrations(c, target = 2, migrations = mapOf(2 to "/migrations/test_002.sql"))
            assertEquals(2, c.createStatement().use { st -> st.executeQuery("PRAGMA user_version").use { it.next(); it.getInt(1) } })
            val applied = c.createStatement().use { st ->
                st.executeQuery("SELECT 1 FROM sqlite_master WHERE type='table' AND name='migration_probe'").use { it.next() }
            }
            assertTrue(applied, "migration DDL did not apply")
        }
    }

    @Test
    fun `runMigrations fails when a version in the chain has no registered migration`() {
        db.init()
        db.connect().use { c ->
            val ex = assertFailsWith<IllegalStateException> {
                db.runMigrations(c, target = 3, migrations = mapOf(2 to "/migrations/test_002.sql"))
            }
            assertTrue(ex.message!!.contains("v3"), "must name the missing version: ${ex.message}")
        }
    }

    @Test
    fun `a migration that leaves an FK violation rolls back fully - version does not advance`() {
        db.init() // fresh at SCHEMA_VERSION (v1)
        db.connect().use { c ->
            fun userVersion() = c.createStatement().use { st ->
                st.executeQuery("PRAGMA user_version").use { it.next(); it.getInt(1) }
            }
            fun taskCount() = c.createStatement().use { st ->
                st.executeQuery("SELECT count(*) FROM task").use { it.next(); it.getInt(1) }
            }
            val before = userVersion()
            val ex = assertFailsWith<IllegalStateException> {
                db.runMigrations(c, target = 2, migrations = mapOf(2 to "/migrations/test_bad_fk.sql"))
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

    @Test
    fun `assertConsistent passes on a freshly initialised database`() {
        db.init()
        db.assertConsistent() // empty schema has no orphans
    }
}
