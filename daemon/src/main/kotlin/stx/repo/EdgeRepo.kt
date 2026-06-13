package stx.repo

import stx.Blocks
import stx.RelatesTo
import java.sql.Connection

object BlocksRepo {
    fun insert(conn: Connection, workspaceId: Long, sourceTaskId: Long, targetTaskId: Long, metadataJson: String): Long =
        conn.insertReturningId(
            "INSERT INTO blocks(workspace_id, source_task_id, target_task_id, metadata_json) VALUES(?, ?, ?, ?)",
        ) { ps ->
            ps.setLong(1, workspaceId); ps.setLong(2, sourceTaskId)
            ps.setLong(3, targetTaskId); ps.setString(4, metadataJson)
        }

    fun get(conn: Connection, id: Long): Blocks? =
        conn.queryOne("SELECT * FROM blocks WHERE id=?", id) { it.toBlocks() }

    /** Live blocks edges as (source, target) pairs for a workspace — used by the DAG check. */
    fun liveEdges(conn: Connection, workspaceId: Long): List<Pair<Long, Long>> =
        conn.queryAll(
            "SELECT source_task_id, target_task_id FROM blocks WHERE workspace_id=? AND archived=0",
            workspaceId,
        ) { it.getLong("source_task_id") to it.getLong("target_task_id") }

    /** Archive every live blocks row incident to a task (either endpoint). */
    fun archiveIncident(conn: Connection, taskId: Long): Int =
        conn.exec(
            "UPDATE blocks SET archived=1 WHERE archived=0 AND (source_task_id=? OR target_task_id=?)",
            taskId, taskId,
        )

    fun archive(conn: Connection, id: Long): Int =
        conn.exec("UPDATE blocks SET archived=1 WHERE id=?", id)
}

object RelatesRepo {
    fun insert(
        conn: Connection,
        workspaceId: Long,
        kind: String,
        sourceTaskId: Long,
        targetTaskId: Long,
        metadataJson: String,
    ): Long = conn.insertReturningId(
        "INSERT INTO relates_to(workspace_id, kind, source_task_id, target_task_id, metadata_json) " +
            "VALUES(?, ?, ?, ?, ?)",
    ) { ps ->
        ps.setLong(1, workspaceId); ps.setString(2, kind)
        ps.setLong(3, sourceTaskId); ps.setLong(4, targetTaskId); ps.setString(5, metadataJson)
    }

    fun get(conn: Connection, id: Long): RelatesTo? =
        conn.queryOne("SELECT * FROM relates_to WHERE id=?", id) { it.toRelatesTo() }

    fun archiveIncident(conn: Connection, taskId: Long): Int =
        conn.exec(
            "UPDATE relates_to SET archived=1 WHERE archived=0 AND (source_task_id=? OR target_task_id=?)",
            taskId, taskId,
        )

    fun archive(conn: Connection, id: Long): Int =
        conn.exec("UPDATE relates_to SET archived=1 WHERE id=?", id)
}
