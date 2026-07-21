package stx.repo

import stx.command.EditTask
import stx.dto.BlocksDto
import stx.dto.KindDto
import stx.dto.RelatesDto
import stx.dto.SegmentDto
import stx.dto.StatusDto
import stx.dto.TaskDto
import stx.dto.TrackDto
import stx.dto.TransitionDto
import stx.dto.WorkspaceDto
import stx.error.StxError
import tech.codingzen.res.Res
import java.sql.Connection

/**
 * Thin hand-written-SQL repositories (brief §4). Every method takes the caller's [Connection]
 * so the write-actor owns the transaction (commit IFF Ok, §6). Inserts that can hit a live
 * UNIQUE index return `Res` (UNIQUE -> typed [StxError.Duplicate] via [sql]); lookups and
 * traversals are plain and may throw — inside the service `rail { }` a throw routes to the
 * Defect rail (-> 500), which is the right outcome for an unexpected JDBC failure.
 *
 * `updated_at` is owned by the daemon on every UPDATE/archive (brief §3) — SQLite only
 * defaults it on INSERT. Only workspace/track/task carry version + updated_at.
 */
object WorkspaceRepo {
    fun insert(c: Connection, name: String, metadataJson: String): Res<Long, StxError> =
        sql("workspace") { c.insertReturningId("INSERT INTO workspace(name, metadata_json) VALUES (?,?)", name, metadataJson) }

    fun getById(c: Connection, id: Long): WorkspaceDto? =
        c.queryOne("SELECT * FROM workspace WHERE id=?", id) { it.toWorkspace() }

    fun getLive(c: Connection, id: Long): WorkspaceDto? =
        c.queryOne("SELECT * FROM workspace WHERE id=? AND archived=0", id) { it.toWorkspace() }

    fun listLive(c: Connection): List<WorkspaceDto> =
        c.queryList("SELECT * FROM workspace WHERE archived=0 ORDER BY id") { it.toWorkspace() }

    fun casEdit(c: Connection, id: Long, expected: Int, name: String?, metadataJson: String?): Int {
        val sets = buildList {
            if (name != null) add("name=?")
            if (metadataJson != null) add("metadata_json=?")
        }
        if (sets.isEmpty()) return casTouch(c, "workspace", id, expected)
        val params = buildList<Any?> {
            if (name != null) add(name); if (metadataJson != null) add(metadataJson); add(id); add(expected)
        }
        return c.exec(
            "UPDATE workspace SET ${sets.joinToString(",")}, version=version+1, updated_at=datetime('now') " +
                "WHERE id=? AND archived=0 AND version=?", *params.toTypedArray(),
        )
    }

    fun archive(c: Connection, id: Long): Int =
        c.exec("UPDATE workspace SET archived=1, updated_at=datetime('now') WHERE id=? AND archived=0", id)
}

object StatusRepo {
    fun insert(c: Connection, workspaceId: Long, name: String, kanbanOrder: Int, terminal: Boolean, isDefault: Boolean): Res<Long, StxError> =
        sql("status", "status name '$name'") {
            c.insertReturningId(
                "INSERT INTO status(workspace_id, name, kanban_order, terminal, is_default) VALUES (?,?,?,?,?)",
                workspaceId, name, kanbanOrder, terminal, isDefault,
            )
        }

    fun getById(c: Connection, id: Long): StatusDto? =
        c.queryOne("SELECT * FROM status WHERE id=?", id) { it.toStatus() }

    fun getLive(c: Connection, id: Long): StatusDto? =
        c.queryOne("SELECT * FROM status WHERE id=? AND archived=0", id) { it.toStatus() }

    fun listLive(c: Connection, workspaceId: Long): List<StatusDto> =
        c.queryList("SELECT * FROM status WHERE workspace_id=? AND archived=0 ORDER BY kanban_order, id", workspaceId) { it.toStatus() }

    fun liveDefault(c: Connection, workspaceId: Long): StatusDto? =
        c.queryOne("SELECT * FROM status WHERE workspace_id=? AND is_default=1 AND archived=0", workspaceId) { it.toStatus() }

    fun clearDefault(c: Connection, workspaceId: Long): Int =
        c.exec("UPDATE status SET is_default=0 WHERE workspace_id=? AND is_default=1 AND archived=0", workspaceId)

    fun setDefault(c: Connection, id: Long): Res<Int, StxError> =
        sql("status") { c.exec("UPDATE status SET is_default=1 WHERE id=? AND archived=0", id) }

    fun archive(c: Connection, id: Long): Int =
        c.exec("UPDATE status SET archived=1 WHERE id=? AND archived=0", id)
}

object TransitionRepo {
    fun insert(c: Connection, workspaceId: Long, from: Long, to: Long): Res<Long, StxError> =
        sql("status_transition", "transition $from->$to") {
            c.insertReturningId("INSERT INTO status_transition(workspace_id, from_status_id, to_status_id) VALUES (?,?,?)", workspaceId, from, to)
        }

    fun liveExists(c: Connection, workspaceId: Long, from: Long, to: Long): Boolean =
        c.queryOne(
            "SELECT 1 FROM status_transition WHERE workspace_id=? AND from_status_id=? AND to_status_id=? AND archived=0",
            workspaceId, from, to,
        ) { true } ?: false

    fun listLive(c: Connection, workspaceId: Long): List<TransitionDto> =
        c.queryList("SELECT * FROM status_transition WHERE workspace_id=? AND archived=0 ORDER BY id", workspaceId) { it.toTransition() }

    /** #9: archive every live transition incident to a status, in the same txn as the status archive. */
    fun archiveIncident(c: Connection, statusId: Long): Int =
        c.exec("UPDATE status_transition SET archived=1 WHERE archived=0 AND (from_status_id=? OR to_status_id=?)", statusId, statusId)
}

object TrackRepo {
    fun insert(c: Connection, workspaceId: Long, name: String, description: String, metadataJson: String): Res<Long, StxError> =
        sql("track") { c.insertReturningId("INSERT INTO track(workspace_id, name, description, metadata_json) VALUES (?,?,?,?)", workspaceId, name, description, metadataJson) }

    fun getById(c: Connection, id: Long): TrackDto? =
        c.queryOne("SELECT * FROM track WHERE id=?", id) { it.toTrack() }

    fun getLive(c: Connection, id: Long): TrackDto? =
        c.queryOne("SELECT * FROM track WHERE id=? AND archived=0", id) { it.toTrack() }

    fun listLive(c: Connection, workspaceId: Long): List<TrackDto> =
        c.queryList("SELECT * FROM track WHERE workspace_id=? AND archived=0 ORDER BY id", workspaceId) { it.toTrack() }

    fun liveIdsOfWorkspace(c: Connection, workspaceId: Long): List<Long> =
        c.queryList("SELECT id FROM track WHERE workspace_id=? AND archived=0", workspaceId) { it.getLong("id") }

    /** All track ids in the workspace, archived or not — the workspace cascade sweeps every track
     *  (like archiveTrackCascade sweeps every segment) so no live task under a pre-archived track
     *  is orphaned (C4b). */
    fun allIdsOfWorkspace(c: Connection, workspaceId: Long): List<Long> =
        c.queryList("SELECT id FROM track WHERE workspace_id=?", workspaceId) { it.getLong("id") }

    fun casEdit(c: Connection, id: Long, expected: Int, name: String?, description: String?, metadataJson: String?): Int {
        val sets = buildList {
            if (name != null) add("name=?")
            if (description != null) add("description=?")
            if (metadataJson != null) add("metadata_json=?")
        }
        if (sets.isEmpty()) return casTouch(c, "track", id, expected)
        val params = buildList<Any?> {
            if (name != null) add(name); if (description != null) add(description); if (metadataJson != null) add(metadataJson)
            add(id); add(expected)
        }
        return c.exec(
            "UPDATE track SET ${sets.joinToString(",")}, version=version+1, updated_at=datetime('now') " +
                "WHERE id=? AND archived=0 AND version=?", *params.toTypedArray(),
        )
    }

    fun archive(c: Connection, id: Long): Int =
        c.exec("UPDATE track SET archived=1, updated_at=datetime('now') WHERE id=? AND archived=0", id)
}

object SegmentRepo {
    fun insert(c: Connection, workspaceId: Long, trackId: Long, parentSegmentId: Long?, name: String, isRoot: Boolean): Res<Long, StxError> =
        sql("segment", "root segment for track $trackId") {
            c.insertReturningId(
                "INSERT INTO segment(workspace_id, track_id, parent_segment_id, name, is_root) VALUES (?,?,?,?,?)",
                workspaceId, trackId, parentSegmentId, name, isRoot,
            )
        }

    fun getById(c: Connection, id: Long): SegmentDto? =
        c.queryOne("SELECT * FROM segment WHERE id=?", id) { it.toSegment() }

    fun getLive(c: Connection, id: Long): SegmentDto? =
        c.queryOne("SELECT * FROM segment WHERE id=? AND archived=0", id) { it.toSegment() }

    fun rootOf(c: Connection, trackId: Long): SegmentDto? =
        c.queryOne("SELECT * FROM segment WHERE track_id=? AND is_root=1 AND archived=0", trackId) { it.toSegment() }

    fun listLive(c: Connection, trackId: Long): List<SegmentDto> =
        c.queryList("SELECT * FROM segment WHERE track_id=? AND archived=0 ORDER BY id", trackId) { it.toSegment() }

    fun liveChildren(c: Connection, parentSegmentId: Long): List<Long> =
        c.queryList("SELECT id FROM segment WHERE parent_segment_id=? AND archived=0", parentSegmentId) { it.getLong("id") }

    /** Children regardless of archived state — the cascade must descend through an already-archived
     *  mid-tree node to reach any live descendant left under it (C4b), else it would orphan them. */
    fun allChildren(c: Connection, parentSegmentId: Long): List<Long> =
        c.queryList("SELECT id FROM segment WHERE parent_segment_id=?", parentSegmentId) { it.getLong("id") }

    /** All live segment ids in the subtree rooted at [segmentId] (inclusive), walking parent_segment_id down. */
    fun liveSubtreeIds(c: Connection, segmentId: Long): List<Long> {
        val out = mutableListOf(segmentId)
        var frontier = listOf(segmentId)
        while (frontier.isNotEmpty()) {
            val next = frontier.flatMap { liveChildren(c, it) }
            out += next
            frontier = next
        }
        return out
    }

    /** Every segment id in the subtree rooted at [segmentId] (inclusive), archived or not — the
     *  set the archive cascade must sweep so no live descendant survives under an archived ancestor. */
    fun subtreeIds(c: Connection, segmentId: Long): List<Long> {
        val out = mutableListOf(segmentId)
        var frontier = listOf(segmentId)
        while (frontier.isNotEmpty()) {
            val next = frontier.flatMap { allChildren(c, it) }
            out += next
            frontier = next
        }
        return out
    }

    /** Every segment id in a track, archived or not — flat via denormalized track_id. The track/
     *  workspace cascade sweeps this so a pre-archived mid-tree segment can't shelter a live task. */
    fun allIdsOfTrack(c: Connection, trackId: Long): List<Long> =
        c.queryList("SELECT id FROM segment WHERE track_id=?", trackId) { it.getLong("id") }

    fun archive(c: Connection, id: Long): Int =
        c.exec("UPDATE segment SET archived=1 WHERE id=? AND archived=0", id)
}

object KindRepo {
    fun insert(c: Connection, workspaceId: Long, name: String): Res<Long, StxError> =
        sql("task_kind", "kind '$name'") { c.insertReturningId("INSERT INTO task_kind(workspace_id, name) VALUES (?,?)", workspaceId, name) }

    fun getById(c: Connection, id: Long): KindDto? =
        c.queryOne("SELECT * FROM task_kind WHERE id=?", id) { it.toKind() }

    fun getLive(c: Connection, id: Long): KindDto? =
        c.queryOne("SELECT * FROM task_kind WHERE id=? AND archived=0", id) { it.toKind() }

    fun listLive(c: Connection, workspaceId: Long): List<KindDto> =
        c.queryList("SELECT * FROM task_kind WHERE workspace_id=? AND archived=0 ORDER BY id", workspaceId) { it.toKind() }

    /** #9: kind archive null-cascades — referencing live tasks become untyped. */
    fun nullCascade(c: Connection, kindId: Long): Int =
        c.exec("UPDATE task SET kind_id=NULL, updated_at=datetime('now') WHERE kind_id=? AND archived=0", kindId)

    fun archive(c: Connection, id: Long): Int =
        c.exec("UPDATE task_kind SET archived=1 WHERE id=? AND archived=0", id)
}

object TaskRepo {
    fun insert(
        c: Connection, workspaceId: Long, segmentId: Long, statusId: Long, kindId: Long?,
        title: String, description: String, priority: Int, metadataJson: String,
    ): Res<Long, StxError> = sql("task") {
        c.insertReturningId(
            "INSERT INTO task(workspace_id, segment_id, status_id, kind_id, title, description, priority, metadata_json) " +
                "VALUES (?,?,?,?,?,?,?,?)",
            workspaceId, segmentId, statusId, kindId, title, description, priority, metadataJson,
        )
    }

    /** From the task table, any archived state (direct GET may inspect an archived row — D4). */
    fun getById(c: Connection, id: Long): TaskDto? =
        c.queryOne("SELECT * FROM task WHERE id=?", id) { it.toTask() }

    /** Through the live_task view: visible iff task + own segment + track + workspace all unarchived. */
    fun getVisible(c: Connection, id: Long): TaskDto? =
        c.queryOne("SELECT * FROM live_task WHERE id=?", id) { it.toTask() }

    /** Kanban: a track's visible tasks (optionally one status), via live_task + segment join. */
    fun listVisibleByTrack(c: Connection, trackId: Long, statusId: Long?): List<TaskDto> {
        val base = "SELECT t.* FROM live_task t JOIN segment s ON s.id=t.segment_id WHERE s.track_id=?"
        return if (statusId == null) {
            c.queryList("$base ORDER BY t.priority DESC, t.id", trackId) { it.toTask() }
        } else {
            c.queryList("$base AND t.status_id=? ORDER BY t.priority DESC, t.id", trackId, statusId) { it.toTask() }
        }
    }

    /** Live task ids filed directly under any of [segmentIds] (used by container cascade #6). */
    fun liveTaskIdsInSegments(c: Connection, segmentIds: List<Long>): List<Long> {
        if (segmentIds.isEmpty()) return emptyList()
        val placeholders = segmentIds.joinToString(",") { "?" }
        return c.queryList("SELECT id FROM task WHERE archived=0 AND segment_id IN ($placeholders)", *segmentIds.toTypedArray()) { it.getLong("id") }
    }

    fun existsLiveWithStatus(c: Connection, statusId: Long): Boolean =
        c.queryOne("SELECT 1 FROM task WHERE status_id=? AND archived=0", statusId) { true } ?: false

    fun casMoveStatus(c: Connection, id: Long, statusId: Long, expected: Int): Int =
        c.exec(
            "UPDATE task SET status_id=?, version=version+1, updated_at=datetime('now') WHERE id=? AND archived=0 AND version=?",
            statusId, id, expected,
        )

    fun casEdit(c: Connection, e: EditTask): Int {
        val sets = mutableListOf<String>()
        val params = mutableListOf<Any?>()
        e.title?.let { sets += "title=?"; params += it }
        e.description?.let { sets += "description=?"; params += it }
        e.priority?.let { sets += "priority=?"; params += it }
        e.metadataJson?.let { sets += "metadata_json=?"; params += it }
        when {
            e.clearKind -> sets += "kind_id=NULL"
            e.kindId != null -> { sets += "kind_id=?"; params += e.kindId }
        }
        if (sets.isEmpty()) return casTouch(c, "task", e.taskId, e.expectedVersion)
        params += e.taskId; params += e.expectedVersion
        return c.exec(
            "UPDATE task SET ${sets.joinToString(",")}, version=version+1, updated_at=datetime('now') WHERE id=? AND archived=0 AND version=?",
            *params.toTypedArray(),
        )
    }

    fun archive(c: Connection, id: Long): Int =
        c.exec("UPDATE task SET archived=1, updated_at=datetime('now') WHERE id=? AND archived=0", id)
}

object BlocksRepo {
    fun insert(c: Connection, workspaceId: Long, source: Long, target: Long): Res<Long, StxError> =
        sql("blocks", "blocks $source->$target") {
            c.insertReturningId("INSERT INTO blocks(workspace_id, source_task_id, target_task_id) VALUES (?,?,?)", workspaceId, source, target)
        }

    /** Live targets blocked by [source] — adjacency for the DAG cycle check (#1). */
    fun liveTargetsOf(c: Connection, source: Long): List<Long> =
        c.queryList("SELECT target_task_id FROM blocks WHERE source_task_id=? AND archived=0", source) { it.getLong("target_task_id") }

    fun liveOutgoing(c: Connection, taskId: Long): List<Long> = liveTargetsOf(c, taskId)

    /** All live blocks edges in a workspace — bulk read for graph export. */
    fun liveByWorkspace(c: Connection, workspaceId: Long): List<BlocksDto> =
        c.queryList("SELECT * FROM blocks WHERE workspace_id=? AND archived=0", workspaceId) { it.toBlocks() }

    fun liveIncoming(c: Connection, taskId: Long): List<Long> =
        c.queryList("SELECT source_task_id FROM blocks WHERE target_task_id=? AND archived=0", taskId) { it.getLong("source_task_id") }

    /** #4: archive all live blocks edges incident to a task, in the same txn as the task archive. */
    fun archiveIncident(c: Connection, taskId: Long): Int =
        c.exec("UPDATE blocks SET archived=1 WHERE archived=0 AND (source_task_id=? OR target_task_id=?)", taskId, taskId)

    /** Archive the single live blocks edge for a source→target pair (edge removal). Rows affected
     *  is 0 when no such live edge exists. */
    fun archiveEdge(c: Connection, source: Long, target: Long): Int =
        c.exec("UPDATE blocks SET archived=1 WHERE archived=0 AND source_task_id=? AND target_task_id=?", source, target)
}

object RelatesRepo {
    fun insert(c: Connection, workspaceId: Long, kind: String, source: Long, target: Long): Res<Long, StxError> =
        sql("relates_to", "relates '$kind' $source->$target") {
            c.insertReturningId("INSERT INTO relates_to(workspace_id, kind, source_task_id, target_task_id) VALUES (?,?,?,?)", workspaceId, kind, source, target)
        }

    /** D6: distinct live `kind` values in this workspace — surfaces drift (`relates-to` vs `relates_to`)
     *  without constraining the free-text vocabulary. */
    fun distinctKinds(c: Connection, workspaceId: Long): List<String> =
        c.queryList("SELECT DISTINCT kind FROM relates_to WHERE workspace_id=? AND archived=0 ORDER BY kind", workspaceId) { it.getString("kind") }

    /** All live relates_to edges in a workspace — bulk read for graph export. Intentionally NOT
     *  deduped: a reciprocal symmetric pair (A→B and B→A) returns as two rows (decision D7). The
     *  daemon can't know which kinds are symmetric (kind is free text, D6), so it stays dumb and
     *  the renderer collapses symmetric edges at view time. Do not add distinctBy here. */
    fun liveByWorkspace(c: Connection, workspaceId: Long): List<RelatesDto> =
        c.queryList("SELECT * FROM relates_to WHERE workspace_id=? AND archived=0", workspaceId) { it.toRelates() }

    /** Symmetric read (D2): live relations with this task as source OR target. */
    fun liveIncident(c: Connection, taskId: Long): List<RelatesDto> =
        c.queryList(
            "SELECT * FROM relates_to WHERE archived=0 AND (source_task_id=? OR target_task_id=?)",
            taskId, taskId,
        ) { it.toRelates() }

    /** #4: archive all live relates_to edges incident to a task. */
    fun archiveIncident(c: Connection, taskId: Long): Int =
        c.exec("UPDATE relates_to SET archived=1 WHERE archived=0 AND (source_task_id=? OR target_task_id=?)", taskId, taskId)

    /** Archive the single live relates_to edge keyed on (kind, source, target). Rows affected is 0
     *  when no such live edge exists. */
    fun archiveEdge(c: Connection, kind: String, source: Long, target: Long): Int =
        c.exec("UPDATE relates_to SET archived=1 WHERE archived=0 AND kind=? AND source_task_id=? AND target_task_id=?", kind, source, target)
}

/** Shared CAS no-op touch: bump version/updated_at when an edit names no changed columns but still
 *  must enforce the version check (so a stale [expectedVersion] is still a conflict). */
private fun casTouch(c: Connection, table: String, id: Long, expected: Int): Int =
    c.exec("UPDATE $table SET version=version+1, updated_at=datetime('now') WHERE id=? AND archived=0 AND version=?", id, expected)
