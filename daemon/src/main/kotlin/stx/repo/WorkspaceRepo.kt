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

    /** Update name and/or metadata in one statement. Bumps version; CAS-guarded when [expectedVersion] set. */
    fun update(conn: Connection, id: Long, name: String?, metadataJson: String?, expectedVersion: Long?): Int {
        val sets = mutableListOf<String>()
        val args = mutableListOf<Any?>()
        if (name != null) { sets += "name=?"; args += name }
        if (metadataJson != null) { sets += "metadata_json=?"; args += metadataJson }
        sets += "version=version+1"
        sets += "updated_at=datetime('now')"
        return conn.exec(
            "UPDATE workspace SET ${sets.joinToString(", ")} WHERE id=?${versionClause(expectedVersion)}",
            *args.toTypedArray(), id, *versionArg(expectedVersion),
        )
    }

    fun archive(conn: Connection, id: Long, expectedVersion: Long? = null): Int =
        conn.exec(
            "UPDATE workspace SET archived=1, version=version+1, updated_at=datetime('now') " +
                "WHERE id=?${versionClause(expectedVersion)}",
            id, *versionArg(expectedVersion),
        )
}
