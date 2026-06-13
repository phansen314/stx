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

    /** Reparent (track_id is immutable, so it is never touched here). */
    fun reparent(conn: Connection, id: Long, newParentSegmentId: Long?): Int =
        conn.prepareStatement("UPDATE segment SET parent_segment_id=? WHERE id=?").use { ps ->
            if (newParentSegmentId == null) ps.setNull(1, Types.INTEGER) else ps.setLong(1, newParentSegmentId)
            ps.setLong(2, id)
            ps.executeUpdate()
        }

    fun archive(conn: Connection, id: Long): Int =
        conn.exec("UPDATE segment SET archived=1 WHERE id=?", id)
}
