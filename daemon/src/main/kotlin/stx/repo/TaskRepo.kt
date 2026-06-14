package stx.repo

import stx.Task
import stx.command.TaskPatch
import stx.support.MetadataCodec
import java.sql.Connection
import java.sql.Types

object TaskRepo {
    fun insert(
        conn: Connection,
        workspaceId: Long,
        segmentId: Long,
        statusId: Long,
        kind: String?,
        title: String,
        description: String,
        priority: Int,
        dueDate: String?,
        startDate: String?,
        finishDate: String?,
        metadataJson: String,
    ): Long = conn.insertReturningId(
        "INSERT INTO task(workspace_id, segment_id, status_id, kind, title, description, priority, " +
            "due_date, start_date, finish_date, metadata_json) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    ) { ps ->
        ps.setLong(1, workspaceId)
        ps.setLong(2, segmentId)
        ps.setLong(3, statusId)
        ps.setStringOrNull(4, kind)
        ps.setString(5, title)
        ps.setString(6, description)
        ps.setInt(7, priority)
        ps.setStringOrNull(8, dueDate)
        ps.setStringOrNull(9, startDate)
        ps.setStringOrNull(10, finishDate)
        ps.setString(11, metadataJson)
    }

    fun get(conn: Connection, id: Long): Task? =
        conn.queryOne("SELECT * FROM task WHERE id=?", id) { it.toTask() }

    fun listBySegment(conn: Connection, segmentId: Long, includeArchived: Boolean): List<Task> =
        conn.queryAll(
            "SELECT * FROM task WHERE segment_id=?" + (if (includeArchived) "" else " AND archived=0") +
                " ORDER BY priority DESC, id ASC",
            segmentId,
        ) { it.toTask() }

    fun listByStatus(conn: Connection, statusId: Long): List<Task> =
        conn.queryAll(
            "SELECT * FROM task WHERE status_id=? AND archived=0 ORDER BY priority DESC, id ASC",
            statusId,
        ) { it.toTask() }

    /** Apply a partial edit. A null patch field leaves the column unchanged. Always bumps version. */
    fun applyPatch(conn: Connection, id: Long, patch: TaskPatch, expectedVersion: Long? = null): Int {
        val sets = mutableListOf<String>()
        val binders = mutableListOf<(java.sql.PreparedStatement, Int) -> Unit>()
        fun str(col: String, v: String) { sets += "$col=?"; binders += { ps, i -> ps.setString(i, v) } }
        fun strN(col: String, v: String?) { sets += "$col=?"; binders += { ps, i -> ps.setStringOrNull(i, v) } }
        patch.title?.let { str("title", it) }
        patch.description?.let { str("description", it) }
        patch.priority?.let { v -> sets += "priority=?"; binders += { ps, i -> ps.setInt(i, v) } }
        // kind/dates are nullable columns; patching them sets the provided value (null clears).
        if (patch.kind != null) strN("kind", patch.kind)
        if (patch.dueDate != null) strN("due_date", patch.dueDate)
        if (patch.startDate != null) strN("start_date", patch.startDate)
        if (patch.finishDate != null) strN("finish_date", patch.finishDate)
        patch.metadata?.let { m -> str("metadata_json", MetadataCodec.encode(m)) }
        sets += "version=version+1"
        sets += "updated_at=datetime('now')"
        return conn.prepareStatement(
            "UPDATE task SET ${sets.joinToString(", ")} WHERE id=?${versionClause(expectedVersion)}",
        ).use { ps ->
            var i = 1
            binders.forEach { it(ps, i++) }
            ps.setLong(i++, id)
            if (expectedVersion != null) ps.setLong(i, expectedVersion)
            ps.executeUpdate()
        }
    }

    fun moveStatus(conn: Connection, id: Long, toStatusId: Long, expectedVersion: Long? = null): Int =
        conn.exec(
            "UPDATE task SET status_id=?, version=version+1, updated_at=datetime('now') " +
                "WHERE id=?${versionClause(expectedVersion)}",
            toStatusId, id, *versionArg(expectedVersion),
        )

    fun moveSegment(conn: Connection, id: Long, toSegmentId: Long, expectedVersion: Long? = null): Int =
        conn.exec(
            "UPDATE task SET segment_id=?, version=version+1, updated_at=datetime('now') " +
                "WHERE id=?${versionClause(expectedVersion)}",
            toSegmentId, id, *versionArg(expectedVersion),
        )

    fun archive(conn: Connection, id: Long, expectedVersion: Long? = null): Int =
        conn.exec(
            "UPDATE task SET archived=1, version=version+1, updated_at=datetime('now') " +
                "WHERE id=?${versionClause(expectedVersion)}",
            id, *versionArg(expectedVersion),
        )

    // ── cascade helpers (bulk; no CAS) ───────────────────────────────────────────
    fun liveIdsInSegments(conn: Connection, segmentIds: List<Long>): List<Long> {
        if (segmentIds.isEmpty()) return emptyList()
        return conn.queryAll(
            "SELECT id FROM task WHERE archived=0 AND segment_id IN (${inPlaceholders(segmentIds.size)})",
            *segmentIds.toTypedArray(),
        ) { it.getLong("id") }
    }

    fun archiveByIds(conn: Connection, ids: List<Long>): Int {
        if (ids.isEmpty()) return 0
        return conn.exec(
            "UPDATE task SET archived=1, version=version+1, updated_at=datetime('now') " +
                "WHERE archived=0 AND id IN (${inPlaceholders(ids.size)})",
            *ids.toTypedArray(),
        )
    }

    fun archiveByWorkspace(conn: Connection, workspaceId: Long): Int =
        conn.exec(
            "UPDATE task SET archived=1, version=version+1, updated_at=datetime('now') " +
                "WHERE workspace_id=? AND archived=0",
            workspaceId,
        )
}

internal fun java.sql.PreparedStatement.setStringOrNull(index: Int, value: String?) {
    if (value == null) setNull(index, Types.VARCHAR) else setString(index, value)
}
