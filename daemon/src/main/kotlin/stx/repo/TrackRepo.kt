package stx.repo

import stx.Track
import java.sql.Connection

object TrackRepo {
    fun insert(conn: Connection, workspaceId: Long, name: String, description: String, metadataJson: String): Long =
        conn.insertReturningId(
            "INSERT INTO track(workspace_id, name, description, metadata_json) VALUES(?, ?, ?, ?)",
        ) { ps ->
            ps.setLong(1, workspaceId); ps.setString(2, name)
            ps.setString(3, description); ps.setString(4, metadataJson)
        }

    fun get(conn: Connection, id: Long): Track? =
        conn.queryOne("SELECT * FROM track WHERE id=?", id) { it.toTrack() }

    fun listByWorkspace(conn: Connection, workspaceId: Long, includeArchived: Boolean): List<Track> =
        conn.queryAll(
            "SELECT * FROM track WHERE workspace_id=?" + (if (includeArchived) "" else " AND archived=0") +
                " ORDER BY id ASC",
            workspaceId,
        ) { it.toTrack() }

    fun update(
        conn: Connection,
        id: Long,
        name: String?,
        description: String?,
        metadataJson: String?,
        expectedVersion: Long?,
    ): Int {
        val sets = mutableListOf<String>()
        val args = mutableListOf<Any?>()
        if (name != null) { sets += "name=?"; args += name }
        if (description != null) { sets += "description=?"; args += description }
        if (metadataJson != null) { sets += "metadata_json=?"; args += metadataJson }
        sets += "version=version+1"
        sets += "updated_at=datetime('now')"
        return conn.exec(
            "UPDATE track SET ${sets.joinToString(", ")} WHERE id=?${versionClause(expectedVersion)}",
            *args.toTypedArray(), id, *versionArg(expectedVersion),
        )
    }

    fun archive(conn: Connection, id: Long, expectedVersion: Long? = null): Int =
        conn.exec(
            "UPDATE track SET archived=1, version=version+1, updated_at=datetime('now') " +
                "WHERE id=?${versionClause(expectedVersion)}",
            id, *versionArg(expectedVersion),
        )

    fun archiveByWorkspace(conn: Connection, workspaceId: Long): Int =
        conn.exec(
            "UPDATE track SET archived=1, version=version+1, updated_at=datetime('now') " +
                "WHERE workspace_id=? AND archived=0",
            workspaceId,
        )
}
