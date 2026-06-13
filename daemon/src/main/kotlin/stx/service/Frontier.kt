package stx.service

import stx.FrontierTask
import stx.repo.SegmentRepo
import java.sql.Connection

/**
 * `next` — the frontier (brief §4 / stx-v3-next.md). A FILTER, not a recommender: returns the
 * ready set and makes no prioritization decision. Recompute-on-read — no caching — so rework
 * (reopening a terminal task) re-derives the frontier with zero stale-cache risk.
 *
 * A task is in the frontier IFF: archived=0, status not terminal, and no live `blocks` points at
 * it from a non-terminal task. The archive-cascade invariant means a live blocks edge always
 * joins two live tasks, so we never check a blocker's archived flag here.
 *
 * This is a read: it runs on a read connection, NOT through the write-actor.
 */
class Frontier {

    fun next(
        conn: Connection,
        workspaceId: Long,
        trackId: Long? = null,
        segmentId: Long? = null,
        kind: String? = null,
        limit: Int? = null,
    ): List<FrontierTask> {
        val sql = StringBuilder()
        val params = mutableListOf<Any?>()

        sql.append("SELECT t.id, t.title, t.priority, t.status_id, t.kind, t.segment_id FROM task t ")
        if (trackId != null) sql.append("JOIN segment s ON s.id = t.segment_id ")
        sql.append("WHERE t.workspace_id = ? AND t.archived = 0 ")
        params.add(workspaceId)
        sql.append("AND t.status_id NOT IN (SELECT id FROM status WHERE workspace_id = ? AND terminal = 1) ")
        params.add(workspaceId)
        sql.append(
            "AND NOT EXISTS (SELECT 1 FROM blocks b JOIN task bt ON bt.id = b.source_task_id " +
                "WHERE b.target_task_id = t.id AND b.archived = 0 " +
                "AND bt.status_id NOT IN (SELECT id FROM status WHERE workspace_id = ? AND terminal = 1)) ",
        )
        params.add(workspaceId)

        if (trackId != null) {
            sql.append("AND s.track_id = ? ")
            params.add(trackId)
        }
        if (segmentId != null) {
            val ids = segmentSubtree(conn, segmentId)
            sql.append("AND t.segment_id IN (${ids.joinToString(",") { "?" }}) ")
            params.addAll(ids)
        }
        if (kind != null) {
            sql.append("AND t.kind = ? ")
            params.add(kind)
        }
        sql.append("ORDER BY t.priority DESC, t.id ASC")
        if (limit != null) {
            sql.append(" LIMIT ?")
            params.add(limit)
        }

        conn.prepareStatement(sql.toString()).use { ps ->
            params.forEachIndexed { i, p -> ps.setObject(i + 1, p) }
            ps.executeQuery().use { rs ->
                val out = ArrayList<FrontierTask>()
                while (rs.next()) {
                    out.add(
                        FrontierTask(
                            id = rs.getLong("id"),
                            title = rs.getString("title"),
                            priority = rs.getInt("priority"),
                            statusId = rs.getLong("status_id"),
                            kind = rs.getString("kind"),
                            segmentId = rs.getLong("segment_id"),
                        ),
                    )
                }
                return out
            }
        }
    }

    /** Collect a segment and all its live descendants via parent_segment_id (the one recursive scope). */
    private fun segmentSubtree(conn: Connection, root: Long): List<Long> {
        val ids = mutableListOf(root)
        val queue = ArrayDeque<Long>()
        queue.addLast(root)
        while (queue.isNotEmpty()) {
            val cur = queue.removeFirst()
            for (child in SegmentRepo.children(conn, cur)) {
                ids.add(child.id)
                queue.addLast(child.id)
            }
        }
        return ids
    }
}
