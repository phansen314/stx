package stx.repo

import stx.Workspace
import java.sql.Connection

/** Thin hand-written SQL for `workspace`. Receives a connection; never commits (service owns tx). */
object WorkspaceRepo {
    fun insert(conn: Connection, name: String, metadataJson: String): Long =
        conn.insertReturningId(
            "INSERT INTO workspace(name, metadata_json) VALUES(?, ?)",
        ) { ps -> ps.setString(1, name); ps.setString(2, metadataJson) }

    fun get(conn: Connection, id: Long): Workspace? =
        conn.queryOne("SELECT * FROM workspace WHERE id=?", id) { it.toWorkspace() }

    fun list(conn: Connection, includeArchived: Boolean): List<Workspace> =
        conn.queryAll(
            "SELECT * FROM workspace" + (if (includeArchived) "" else " WHERE archived=0") +
                " ORDER BY id ASC",
        ) { it.toWorkspace() }

    fun updateName(conn: Connection, id: Long, name: String): Int =
        conn.exec("UPDATE workspace SET name=?, updated_at=datetime('now') WHERE id=?", name, id)

    fun updateMetadata(conn: Connection, id: Long, metadataJson: String): Int =
        conn.exec(
            "UPDATE workspace SET metadata_json=?, updated_at=datetime('now') WHERE id=?",
            metadataJson, id,
        )

    fun archive(conn: Connection, id: Long): Int =
        conn.exec("UPDATE workspace SET archived=1, updated_at=datetime('now') WHERE id=?", id)
}
