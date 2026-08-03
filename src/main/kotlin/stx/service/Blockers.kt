package stx.service

import stx.command.ListBlockers
import stx.dto.BlockerItem
import stx.dto.BlockerList
import stx.error.StxError
import tech.codingzen.res.Res
import tech.codingzen.res.catching
import java.sql.Connection

/**
 * `blockers` — the inverse of [Frontier]. Given a task, the unfinished work holding it back: the
 * transitive closure of `blocks` walked *backward*, through live non-terminal blockers only.
 *
 * Deliberately a sibling of [Frontier] rather than a client-side traversal (decision D8). Two
 * reasons the mirror has to live here: the eligibility predicate is *the same* predicate
 * (`live_task` ∧ non-terminal ∧ `blocks.archived=0`), so a second implementation could drift from
 * `next`; and the walk is a multi-statement read that must share one WAL snapshot, which is
 * exactly what `HttpApi.read()` provides and three separate client round trips do not.
 *
 * The walk does **not** pass *through* a finished blocker: a done task no longer gates, so what
 * used to gate it is irrelevant. That is what makes the two reads exact inverses — a task is in
 * the frontier iff its blocker list is empty.
 */
object Blockers {
    fun list(c: Connection, workspaceId: Long, cmd: ListBlockers): Res<BlockerList, StxError> = catching {
        // UNION (not UNION ALL) bounds the recursion by |V|×depth instead of path count, and
        // MIN(depth) collapses diamonds to the shallowest hop. The depth cap is belt-and-braces:
        // `blocks` is acyclic by invariant #1, so it can only matter if that invariant is broken.
        val sql = """
            WITH RECURSIVE term(id) AS (
              SELECT id FROM status WHERE workspace_id=? AND terminal=1 AND archived=0
            ),
            blockers(id, depth) AS (
              SELECT b.source_task_id, 1
                FROM blocks b JOIN live_task s ON s.id=b.source_task_id
               WHERE b.target_task_id=? AND b.archived=0 AND s.status_id NOT IN (SELECT id FROM term)
              UNION
              SELECT b.source_task_id, bl.depth+1
                FROM blockers bl
                JOIN blocks b ON b.target_task_id=bl.id AND b.archived=0
                JOIN live_task s ON s.id=b.source_task_id
               WHERE s.status_id NOT IN (SELECT id FROM term) AND bl.depth < ?
            )
            SELECT t.id, t.title, t.priority, t.status_id, t.segment_id, t.version, MIN(b.depth) AS depth
              FROM blockers b JOIN live_task t ON t.id=b.id
             GROUP BY t.id
             ORDER BY depth ASC, t.priority DESC, t.id ASC
        """.trimIndent()

        val items = c.prepareStatement(sql).use { ps ->
            ps.setLong(1, workspaceId)
            ps.setLong(2, cmd.taskId)
            ps.setInt(3, cmd.maxDepth)
            ps.executeQuery().use { rs ->
                buildList {
                    while (rs.next()) add(
                        BlockerItem(
                            id = rs.getLong("id"), title = rs.getString("title"), priority = rs.getInt("priority"),
                            statusId = rs.getLong("status_id"), segmentId = rs.getLong("segment_id"),
                            version = rs.getInt("version"), depth = rs.getInt("depth"),
                        ),
                    )
                }
            }
        }
        BlockerList(items)
    }
}
