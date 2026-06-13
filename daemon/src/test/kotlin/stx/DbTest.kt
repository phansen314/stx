package stx

import stx.repo.Db
import java.nio.file.Files
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class DbTest {
    private val tmp = Files.createTempFile("stx-test", ".db")
    private val db = Db.forFile(tmp.toString())

    @AfterTest fun cleanup() {
        Files.deleteIfExists(tmp)
        Files.deleteIfExists(java.nio.file.Path.of("$tmp-wal"))
        Files.deleteIfExists(java.nio.file.Path.of("$tmp-shm"))
    }

    @Test fun `init creates the full schema`() {
        db.init()
        db.open().use { conn ->
            val tables = mutableSetOf<String>()
            conn.createStatement().executeQuery(
                "SELECT name FROM sqlite_master WHERE type='table'",
            ).use { rs -> while (rs.next()) tables.add(rs.getString(1)) }
            for (t in listOf(
                "workspace", "status", "status_transition", "track",
                "segment", "task", "blocks", "relates_to",
            )) assertTrue(t in tables, "expected table '$t', got $tables")
        }
    }

    @Test fun `pragmas are applied`() {
        db.init()
        db.open().use { conn ->
            conn.createStatement().executeQuery("PRAGMA journal_mode").use { rs ->
                rs.next(); assertEquals("wal", rs.getString(1).lowercase())
            }
            conn.createStatement().executeQuery("PRAGMA foreign_keys").use { rs ->
                rs.next(); assertEquals(1, rs.getInt(1))
            }
        }
    }

    @Test fun `init is idempotent`() {
        db.init()
        db.init() // must not throw on an already-populated DB
    }

    @Test fun `splitStatements strips comments and pragmas`() {
        val stmts = Db.splitStatements(
            """
            PRAGMA foreign_keys = ON;
            -- a comment
            CREATE TABLE a (id INTEGER); -- trailing comment
            CREATE TABLE b (id INTEGER);
            """.trimIndent(),
        )
        assertEquals(2, stmts.size)
        assertTrue(stmts.all { it.startsWith("CREATE TABLE") })
    }
}
