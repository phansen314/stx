package stx.service

import stx.Blocks
import stx.FrontierTask
import stx.RelatesTo
import stx.Segment
import stx.Status
import stx.StatusTransition
import stx.StxException
import stx.Task
import stx.Track
import stx.Workspace
import stx.repo.BlocksRepo
import stx.repo.Db
import stx.repo.RelatesRepo
import stx.repo.SegmentRepo
import stx.repo.StatusRepo
import stx.repo.TaskRepo
import stx.repo.TrackRepo
import stx.repo.TransitionRepo
import stx.repo.WorkspaceRepo
import stx.repo.queryAll
import stx.repo.toTask

/**
 * Read side. Reads open short-lived connections and run concurrently against WAL — they do NOT
 * go through the write-actor (brief §6). Each method opens, queries, and closes its connection.
 */
class Reads(private val db: Db, private val frontier: Frontier = Frontier()) {

    fun listWorkspaces(includeArchived: Boolean = false): List<Workspace> =
        db.open().use { WorkspaceRepo.list(it, includeArchived) }

    fun getWorkspace(id: Long): Workspace =
        db.open().use { WorkspaceRepo.get(it, id) } ?: throw StxException.NotFound("workspace $id")

    fun listStatuses(workspaceId: Long): List<Status> =
        db.open().use { StatusRepo.listByWorkspace(it, workspaceId, includeArchived = false) }

    fun getStatus(id: Long): Status =
        db.open().use { StatusRepo.get(it, id) } ?: throw StxException.NotFound("status $id")

    fun listTransitions(workspaceId: Long): List<StatusTransition> =
        db.open().use { TransitionRepo.listByWorkspace(it, workspaceId) }

    fun listTracks(workspaceId: Long): List<Track> =
        db.open().use { TrackRepo.listByWorkspace(it, workspaceId, includeArchived = false) }

    fun getTrack(id: Long): Track =
        db.open().use { TrackRepo.get(it, id) } ?: throw StxException.NotFound("track $id")

    fun listSegments(trackId: Long): List<Segment> =
        db.open().use { SegmentRepo.listByTrack(it, trackId, includeArchived = false) }

    fun getSegment(id: Long): Segment =
        db.open().use { SegmentRepo.get(it, id) } ?: throw StxException.NotFound("segment $id")

    /** Live tasks filed directly in a segment (non-recursive). */
    fun listTasksBySegment(segmentId: Long): List<Task> =
        db.open().use { TaskRepo.listBySegment(it, segmentId, includeArchived = false) }

    /** Live tasks in a segment and its whole subtree (recursive scope). */
    fun listTasksBySegmentSubtree(segmentId: Long): List<Task> = db.open().use { conn ->
        val ids = SegmentRepo.subtreeIds(conn, segmentId)
        if (ids.isEmpty()) emptyList()
        else conn.queryAll(
            "SELECT * FROM task WHERE archived=0 AND segment_id IN (${ids.joinToString(",") { "?" }}) " +
                "ORDER BY priority DESC, id ASC",
            *ids.toTypedArray(),
        ) { it.toTask() }
    }

    fun getTask(id: Long): Task =
        db.open().use { TaskRepo.get(it, id) } ?: throw StxException.NotFound("task $id")

    // ── edge reads ───────────────────────────────────────────────────────────────
    fun listBlocksForTask(taskId: Long): List<Blocks> =
        db.open().use { BlocksRepo.listIncident(it, taskId) }

    fun listBlocksForWorkspace(workspaceId: Long): List<Blocks> =
        db.open().use { BlocksRepo.listByWorkspace(it, workspaceId) }

    fun listRelatesForTask(taskId: Long): List<RelatesTo> =
        db.open().use { RelatesRepo.listIncident(it, taskId) }

    fun listRelatesForWorkspace(workspaceId: Long): List<RelatesTo> =
        db.open().use { RelatesRepo.listByWorkspace(it, workspaceId) }

    /** Kanban data: live tasks in a track (all its segments), optionally filtered by status. */
    fun listTasksByTrack(trackId: Long, statusId: Long? = null): List<Task> = db.open().use { conn ->
        val sql = StringBuilder(
            "SELECT t.* FROM task t JOIN segment s ON s.id = t.segment_id " +
                "WHERE s.track_id = ? AND t.archived = 0",
        )
        val args = mutableListOf<Any?>(trackId)
        if (statusId != null) { sql.append(" AND t.status_id = ?"); args.add(statusId) }
        sql.append(" ORDER BY t.priority DESC, t.id ASC")
        conn.queryAll(sql.toString(), *args.toTypedArray()) { it.toTask() }
    }

    fun next(
        workspaceId: Long,
        trackId: Long? = null,
        segmentId: Long? = null,
        kind: String? = null,
        limit: Int? = null,
    ): List<FrontierTask> = db.open().use { frontier.next(it, workspaceId, trackId, segmentId, kind, limit) }
}
