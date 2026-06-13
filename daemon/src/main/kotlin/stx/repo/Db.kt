package stx.repo

import java.sql.Connection
import java.sql.DriverManager

/**
 * SQLite access. Plain JDBC, no ORM (brief §1).
 *
 * Connection discipline (brief §6): every connection runs WAL + foreign_keys=ON. The
 * write-actor holds ONE long-lived [writeConnection] and serializes all mutations through it;
 * reads open short-lived connections via [readConnection] and run concurrently against WAL.
 *
 * WAL is set once (it persists in the database file); foreign_keys is per-connection in SQLite
 * so we set it on every connection.
 */
class Db(private val jdbcUrl: String) {

    /** Open a connection with the standard pragmas applied. Caller owns its lifecycle. */
    fun open(): Connection {
        val conn = DriverManager.getConnection(jdbcUrl)
        conn.createStatement().use { st ->
            st.execute("PRAGMA journal_mode=WAL")
            st.execute("PRAGMA foreign_keys=ON")
        }
        return conn
    }

    /** Initialize the schema if the database is empty (no `workspace` table yet). */
    fun init() {
        open().use { conn ->
            if (!tableExists(conn, "workspace")) {
                runSchema(conn)
            }
        }
    }

    private fun tableExists(conn: Connection, name: String): Boolean {
        conn.prepareStatement(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        ).use { ps ->
            ps.setString(1, name)
            ps.executeQuery().use { rs -> return rs.next() }
        }
    }

    private fun runSchema(conn: Connection) {
        val sql = Db::class.java.getResourceAsStream("/schema.sql")
            ?.bufferedReader()?.use { it.readText() }
            ?: error("schema.sql resource not found on classpath")
        conn.autoCommit = false
        try {
            conn.createStatement().use { st ->
                for (stmt in splitStatements(sql)) st.execute(stmt)
            }
            conn.commit()
        } catch (e: Exception) {
            conn.rollback()
            throw e
        } finally {
            conn.autoCommit = true
        }
    }

    companion object {
        fun forFile(path: String): Db = Db("jdbc:sqlite:$path")

        /** In-memory DB for tests. `cache=shared` keeps it alive while a connection is held. */
        fun inMemory(): Db = Db("jdbc:sqlite::memory:")

        /**
         * Split a DDL script into executable statements. Strips `-- ...` line comments (the only
         * comment style in schema.sql — block comments are intentionally avoided there) and
         * `PRAGMA` lines (pragmas are applied per-connection in [open], not by the schema runner),
         * then splits on `;`. No semicolons appear inside string literals in our schema.
         */
        internal fun splitStatements(sql: String): List<String> {
            val noComments = sql.lineSequence()
                .map { line -> line.substringBefore("--") }
                .joinToString("\n")
            return noComments.split(";")
                .map { it.trim() }
                .filter { it.isNotEmpty() && !it.uppercase().startsWith("PRAGMA") }
        }
    }
}
