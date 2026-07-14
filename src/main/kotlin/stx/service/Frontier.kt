package stx.service

import stx.command.Next
import stx.dto.FrontierItem
import stx.dto.FrontierList
import stx.error.StxError
import stx.repo.SegmentRepo
import tech.codingzen.res.Res
import tech.codingzen.res.catching
import java.sql.Connection

/**
 * The `next` frontier (brief §4 / authoritative SQL in next.md). A task is in the frontier iff
 * it is visible (live_task), its status is non-terminal, and no live blocks edge points at it
 * from a non-terminal (also-visible) blocker. Recompute-on-read; order is presentation only
 * (`priority DESC, id ASC`). Workspace scope required; track/segment-subtree/kind optional.
 */
object Frontier {
    fun next(c: Connection, cmd: Next): Res<FrontierList, StxError> = catching {
        val termSub = "SELECT id FROM status WHERE workspace_id=? AND terminal=1 AND archived=0"
        val params = mutableListOf<Any?>()
        val sb = StringBuilder()
        sb.append("SELECT t.id, t.title, t.priority, t.status_id, t.segment_id, t.version FROM live_task t ")
        if (cmd.trackId != null) sb.append("JOIN segment f ON f.id = t.segment_id ")
        sb.append("WHERE t.workspace_id=? ").also { params += cmd.workspaceId }
        sb.append("AND t.status_id NOT IN ($termSub) ").also { params += cmd.workspaceId }
        sb.append(
            "AND NOT EXISTS (SELECT 1 FROM blocks b JOIN live_task bt ON bt.id=b.source_task_id " +
                "WHERE b.target_task_id=t.id AND b.archived=0 AND bt.status_id NOT IN ($termSub)) ",
        ).also { params += cmd.workspaceId }
        if (cmd.trackId != null) sb.append("AND f.track_id=? ").also { params += cmd.trackId }
        if (cmd.segmentId != null) {
            val ids = SegmentRepo.liveSubtreeIds(c, cmd.segmentId)
            sb.append("AND t.segment_id IN (${ids.joinToString(",") { "?" }}) ")
            params.addAll(ids)
        }
        if (cmd.kindId != null) sb.append("AND t.kind_id=? ").also { params += cmd.kindId }
        sb.append("ORDER BY t.priority DESC, t.id ASC")
        if (cmd.limit != null) sb.append(" LIMIT ?").also { params += cmd.limit }

        val items = c.prepareStatement(sb.toString()).use { ps ->
            params.forEachIndexed { i, p ->
                when (p) {
                    is Int -> ps.setInt(i + 1, p)
                    is Long -> ps.setLong(i + 1, p)
                    else -> ps.setObject(i + 1, p)
                }
            }
            ps.executeQuery().use { rs ->
                buildList {
                    while (rs.next()) add(
                        FrontierItem(
                            id = rs.getLong("id"), title = rs.getString("title"), priority = rs.getInt("priority"),
                            statusId = rs.getLong("status_id"), segmentId = rs.getLong("segment_id"), version = rs.getInt("version"),
                        ),
                    )
                }
            }
        }
        FrontierList(items)
    }
}
