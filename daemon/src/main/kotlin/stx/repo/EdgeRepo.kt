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

    /** Live blocks rows incident to a task (either endpoint). */
    fun listIncident(conn: Connection, taskId: Long): List<Blocks> =
        conn.queryAll(
            "SELECT * FROM blocks WHERE archived=0 AND (source_task_id=? OR target_task_id=?) ORDER BY id ASC",
            taskId, taskId,
        ) { it.toBlocks() }

    fun listByWorkspace(conn: Connection, workspaceId: Long): List<Blocks> =
        conn.queryAll(
            "SELECT * FROM blocks WHERE workspace_id=? AND archived=0 ORDER BY id ASC",
            workspaceId,
        ) { it.toBlocks() }

    /** Archive every live blocks row incident to a task (either endpoint). */
    fun archiveIncident(conn: Connection, taskId: Long): Int =
        conn.exec(
            "UPDATE blocks SET archived=1, version=version+1 WHERE archived=0 AND (source_task_id=? OR target_task_id=?)",
            taskId, taskId,
        )

    /** Cascade: archive every live blocks row incident to any of [taskIds]. */
    fun archiveIncidentToAny(conn: Connection, taskIds: List<Long>): Int {
        if (taskIds.isEmpty()) return 0
        val ph = inPlaceholders(taskIds.size)
        return conn.exec(
            "UPDATE blocks SET archived=1, version=version+1 WHERE archived=0 " +
                "AND (source_task_id IN ($ph) OR target_task_id IN ($ph))",
            *taskIds.toTypedArray(), *taskIds.toTypedArray(),
        )
    }

    fun archiveByWorkspace(conn: Connection, workspaceId: Long): Int =
        conn.exec("UPDATE blocks SET archived=1, version=version+1 WHERE workspace_id=? AND archived=0", workspaceId)

    fun updateMetadata(conn: Connection, id: Long, metadataJson: String, expectedVersion: Long? = null): Int =
        conn.exec(
            "UPDATE blocks SET metadata_json=?, version=version+1 WHERE id=?${versionClause(expectedVersion)}",
            metadataJson, id, *versionArg(expectedVersion),
        )

    fun archive(conn: Connection, id: Long, expectedVersion: Long? = null): Int =
        conn.exec(
            "UPDATE blocks SET archived=1, version=version+1 WHERE id=?${versionClause(expectedVersion)}",
            id, *versionArg(expectedVersion),
        )
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

    fun listIncident(conn: Connection, taskId: Long): List<RelatesTo> =
        conn.queryAll(
            "SELECT * FROM relates_to WHERE archived=0 AND (source_task_id=? OR target_task_id=?) ORDER BY id ASC",
            taskId, taskId,
        ) { it.toRelatesTo() }

    fun listByWorkspace(conn: Connection, workspaceId: Long): List<RelatesTo> =
        conn.queryAll(
            "SELECT * FROM relates_to WHERE workspace_id=? AND archived=0 ORDER BY id ASC",
            workspaceId,
        ) { it.toRelatesTo() }

    fun archiveIncident(conn: Connection, taskId: Long): Int =
        conn.exec(
            "UPDATE relates_to SET archived=1, version=version+1 " +
                "WHERE archived=0 AND (source_task_id=? OR target_task_id=?)",
            taskId, taskId,
        )

    fun archiveIncidentToAny(conn: Connection, taskIds: List<Long>): Int {
        if (taskIds.isEmpty()) return 0
        val ph = inPlaceholders(taskIds.size)
        return conn.exec(
            "UPDATE relates_to SET archived=1, version=version+1 WHERE archived=0 " +
                "AND (source_task_id IN ($ph) OR target_task_id IN ($ph))",
            *taskIds.toTypedArray(), *taskIds.toTypedArray(),
        )
    }

    fun archiveByWorkspace(conn: Connection, workspaceId: Long): Int =
        conn.exec("UPDATE relates_to SET archived=1, version=version+1 WHERE workspace_id=? AND archived=0", workspaceId)

    fun updateMetadata(conn: Connection, id: Long, metadataJson: String, expectedVersion: Long? = null): Int =
        conn.exec(
            "UPDATE relates_to SET metadata_json=?, version=version+1 WHERE id=?${versionClause(expectedVersion)}",
            metadataJson, id, *versionArg(expectedVersion),
        )

    fun archive(conn: Connection, id: Long, expectedVersion: Long? = null): Int =
        conn.exec(
            "UPDATE relates_to SET archived=1, version=version+1 WHERE id=?${versionClause(expectedVersion)}",
            id, *versionArg(expectedVersion),
        )
}
