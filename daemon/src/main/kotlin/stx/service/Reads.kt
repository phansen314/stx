package stx.service

import stx.FrontierTask
import stx.Segment
import stx.Status
import stx.StatusTransition
import stx.StxException
import stx.Task
import stx.Track
import stx.Workspace
import stx.repo.Db
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

    fun listTransitions(workspaceId: Long): List<StatusTransition> =
        db.open().use { TransitionRepo.listByWorkspace(it, workspaceId) }

    fun listTracks(workspaceId: Long): List<Track> =
        db.open().use { TrackRepo.listByWorkspace(it, workspaceId, includeArchived = false) }

    fun listSegments(trackId: Long): List<Segment> =
        db.open().use { SegmentRepo.listByTrack(it, trackId, includeArchived = false) }

    fun getTask(id: Long): Task =
        db.open().use { TaskRepo.get(it, id) } ?: throw StxException.NotFound("task $id")

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
