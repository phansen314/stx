package stx.repo

import stx.Segment
import java.sql.Connection
import java.sql.Types

object SegmentRepo {
    fun insert(
        conn: Connection,
        workspaceId: Long,
        trackId: Long,
        parentSegmentId: Long?,
        name: String,
        isRoot: Boolean,
    ): Long = conn.insertReturningId(
        "INSERT INTO segment(workspace_id, track_id, parent_segment_id, name, is_root) VALUES(?, ?, ?, ?, ?)",
    ) { ps ->
        ps.setLong(1, workspaceId)
        ps.setLong(2, trackId)
        if (parentSegmentId == null) ps.setNull(3, Types.INTEGER) else ps.setLong(3, parentSegmentId)
        ps.setString(4, name)
        ps.setInt(5, if (isRoot) 1 else 0)
    }

    fun get(conn: Connection, id: Long): Segment? =
        conn.queryOne("SELECT * FROM segment WHERE id=?", id) { it.toSegment() }

    fun rootForTrack(conn: Connection, trackId: Long): Segment? =
        conn.queryOne(
            "SELECT * FROM segment WHERE track_id=? AND is_root=1 AND archived=0",
            trackId,
        ) { it.toSegment() }

    fun listByTrack(conn: Connection, trackId: Long, includeArchived: Boolean): List<Segment> =
        conn.queryAll(
            "SELECT * FROM segment WHERE track_id=?" + (if (includeArchived) "" else " AND archived=0") +
                " ORDER BY id ASC",
            trackId,
        ) { it.toSegment() }

    fun children(conn: Connection, parentSegmentId: Long): List<Segment> =
        conn.queryAll(
            "SELECT * FROM segment WHERE parent_segment_id=? AND archived=0 ORDER BY id ASC",
            parentSegmentId,
        ) { it.toSegment() }

    /** A segment plus all its live descendants (the recursive scope), as ids. */
    fun subtreeIds(conn: Connection, rootId: Long): List<Long> {
        val ids = mutableListOf(rootId)
        val queue = ArrayDeque<Long>().apply { addLast(rootId) }
        while (queue.isNotEmpty()) {
            for (child in children(conn, queue.removeFirst())) { ids += child.id; queue.addLast(child.id) }
        }
        return ids
    }

    fun liveIdsByTrack(conn: Connection, trackId: Long): List<Long> =
        conn.queryAll("SELECT id FROM segment WHERE track_id=? AND archived=0", trackId) { it.getLong("id") }

    fun rename(conn: Connection, id: Long, name: String, expectedVersion: Long? = null): Int =
        conn.exec(
            "UPDATE segment SET name=?, version=version+1 WHERE id=?${versionClause(expectedVersion)}",
            name, id, *versionArg(expectedVersion),
        )

    /** Reparent (track_id is immutable, so it is never touched here). */
    fun reparent(conn: Connection, id: Long, newParentSegmentId: Long?, expectedVersion: Long? = null): Int =
        conn.prepareStatement(
            "UPDATE segment SET parent_segment_id=?, version=version+1 WHERE id=?${versionClause(expectedVersion)}",
        ).use { ps ->
            if (newParentSegmentId == null) ps.setNull(1, Types.INTEGER) else ps.setLong(1, newParentSegmentId)
            ps.setLong(2, id)
            if (expectedVersion != null) ps.setLong(3, expectedVersion)
            ps.executeUpdate()
        }

    fun archive(conn: Connection, id: Long, expectedVersion: Long? = null): Int =
        conn.exec(
            "UPDATE segment SET archived=1, version=version+1 WHERE id=?${versionClause(expectedVersion)}",
            id, *versionArg(expectedVersion),
        )

    /** Bulk-archive a set of segments (cascade; no CAS). */
    fun archiveByIds(conn: Connection, ids: List<Long>): Int {
        if (ids.isEmpty()) return 0
        return conn.exec(
            "UPDATE segment SET archived=1, version=version+1 WHERE archived=0 AND id IN (${inPlaceholders(ids.size)})",
            *ids.toTypedArray(),
        )
    }

    fun archiveByWorkspace(conn: Connection, workspaceId: Long): Int =
        conn.exec("UPDATE segment SET archived=1, version=version+1 WHERE workspace_id=? AND archived=0", workspaceId)
}
