package stx.service

import stx.Blocks
import stx.Metadata
import stx.RelatesTo
import stx.Segment
import stx.Status
import stx.StatusTransition
import stx.StxException
import stx.Task
import stx.Track
import stx.Workspace
import stx.command.AddBlocks
import stx.command.AddRelatesTo
import stx.command.ArchiveBlocks
import stx.command.ArchiveRelatesTo
import stx.command.ArchiveSegment
import stx.command.ArchiveStatus
import stx.command.ArchiveTask
import stx.command.ArchiveTrack
import stx.command.ArchiveTransition
import stx.command.ArchiveWorkspace
import stx.command.Command
import stx.command.CreateSegment
import stx.command.CreateStatus
import stx.command.CreateTask
import stx.command.CreateTrack
import stx.command.CreateTransition
import stx.command.CreateWorkspace
import stx.command.DeleteMetaKey
import stx.command.MetaEntity
import stx.command.MoveSegment
import stx.command.MoveTask
import stx.command.MoveTaskToSegment
import stx.command.RenameSegment
import stx.command.SetMetaKey
import stx.command.TaskPatch
import stx.command.UpdateStatus
import stx.command.UpdateTask
import stx.command.UpdateTrack
import stx.command.UpdateWorkspace
import stx.repo.BlocksRepo
import stx.repo.RelatesRepo
import stx.repo.SegmentRepo
import stx.repo.StatusRepo
import stx.repo.TaskRepo
import stx.repo.TrackRepo
import stx.repo.TransitionRepo
import stx.repo.WorkspaceRepo
import stx.support.MetadataCodec
import java.sql.Connection
import java.sql.SQLException

/**
 * The mutation core. [execute] dispatches a [Command] over an exhaustive `when` (no `else`) so
 * the compiler forces every verb to be handled — the deliberate safety feature of the protocol.
 * It runs INSIDE the write-actor's transaction (the connection is already in autoCommit=false);
 * it never opens or commits a transaction itself. It owns the five daemon invariants (§3).
 */
class Service {

    /** Handle one command and return the affected entity. Throws [StxException] on rejection. */
    fun execute(conn: Connection, command: Command): Any = when (command) {
        is CreateWorkspace -> createWorkspace(conn, command)
        is UpdateWorkspace -> updateWorkspace(conn, command)
        is ArchiveWorkspace -> archiveWorkspace(conn, command)
        is CreateStatus -> createStatus(conn, command)
        is UpdateStatus -> updateStatus(conn, command)
        is ArchiveStatus -> archiveStatus(conn, command)
        is CreateTransition -> createTransition(conn, command)
        is ArchiveTransition -> archiveTransition(conn, command)
        is CreateTrack -> createTrack(conn, command)
        is UpdateTrack -> updateTrack(conn, command)
        is ArchiveTrack -> archiveTrack(conn, command)
        is CreateSegment -> createSegment(conn, command)
        is RenameSegment -> renameSegment(conn, command)
        is MoveSegment -> moveSegment(conn, command)
        is ArchiveSegment -> archiveSegment(conn, command)
        is CreateTask -> createTask(conn, command)
        is UpdateTask -> updateTask(conn, command)
        is MoveTask -> moveTask(conn, command)
        is MoveTaskToSegment -> moveTaskToSegment(conn, command)
        is ArchiveTask -> archiveTask(conn, command)
        is AddBlocks -> addBlocks(conn, command)
        is ArchiveBlocks -> archiveBlocks(conn, command)
        is AddRelatesTo -> addRelatesTo(conn, command)
        is ArchiveRelatesTo -> archiveRelatesTo(conn, command)
        is SetMetaKey -> setMetaKey(conn, command)
        is DeleteMetaKey -> deleteMetaKey(conn, command)
    }

    // ── workspace ──────────────────────────────────────────────────────────────
    private fun createWorkspace(conn: Connection, c: CreateWorkspace): Workspace {
        requireName(c.name, "workspace")
        val id = mapConstraints { WorkspaceRepo.insert(conn, c.name, MetadataCodec.encode(c.metadata)) }
        return WorkspaceRepo.get(conn, id)!!
    }

    private fun updateWorkspace(conn: Connection, c: UpdateWorkspace): Workspace {
        liveWorkspace(conn, c.workspaceId)
        c.name?.let { requireName(it, "workspace") }
        val metaJson = c.metadata?.let { MetadataCodec.encode(it) }
        val rows = mapConstraints { WorkspaceRepo.update(conn, c.workspaceId, c.name, metaJson, c.expectedVersion) }
        requireWritten(rows, c.expectedVersion)
        return WorkspaceRepo.get(conn, c.workspaceId)!!
    }

    private fun archiveWorkspace(conn: Connection, c: ArchiveWorkspace): Workspace {
        liveWorkspace(conn, c.workspaceId)
        val rows = WorkspaceRepo.archive(conn, c.workspaceId, c.expectedVersion)
        requireWritten(rows, c.expectedVersion)
        // Cascade: archive every child of the workspace so nothing is left dangling-live.
        StatusRepo.archiveByWorkspace(conn, c.workspaceId)
        TransitionRepo.archiveByWorkspace(conn, c.workspaceId)
        TrackRepo.archiveByWorkspace(conn, c.workspaceId)
        SegmentRepo.archiveByWorkspace(conn, c.workspaceId)
        TaskRepo.archiveByWorkspace(conn, c.workspaceId)
        BlocksRepo.archiveByWorkspace(conn, c.workspaceId)
        RelatesRepo.archiveByWorkspace(conn, c.workspaceId)
        return WorkspaceRepo.get(conn, c.workspaceId)!!
    }

    // ── status ─────────────────────────────────────────────────────────────────
    private fun createStatus(conn: Connection, c: CreateStatus): Status {
        liveWorkspace(conn, c.workspaceId)
        requireName(c.name, "status")
        val id = mapConstraints {
            StatusRepo.insert(conn, c.workspaceId, c.name, c.terminal, c.kanbanOrder)
        }
        return StatusRepo.get(conn, id)!!
    }

    private fun updateStatus(conn: Connection, c: UpdateStatus): Status {
        liveStatus(conn, c.statusId)
        c.name?.let { requireName(it, "status") }
        val rows = mapConstraints {
            StatusRepo.update(conn, c.statusId, c.name, c.terminal, c.kanbanOrder, c.expectedVersion)
        }
        requireWritten(rows, c.expectedVersion)
        return StatusRepo.get(conn, c.statusId)!!
    }

    private fun archiveStatus(conn: Connection, c: ArchiveStatus): Status {
        liveStatus(conn, c.statusId)
        requireWritten(StatusRepo.archive(conn, c.statusId, c.expectedVersion), c.expectedVersion)
        return StatusRepo.get(conn, c.statusId)!!
    }

    // ── transition ───────────────────────────────────────────────────────────────
    private fun createTransition(conn: Connection, c: CreateTransition): StatusTransition {
        liveWorkspace(conn, c.workspaceId)
        if (c.fromStatusId == c.toStatusId) throw StxException.Validation("a transition cannot loop a status to itself")
        val from = liveStatus(conn, c.fromStatusId)
        val to = liveStatus(conn, c.toStatusId)
        if (from.workspaceId != c.workspaceId || to.workspaceId != c.workspaceId) {
            throw StxException.Validation("transition statuses must belong to the workspace")
        }
        val id = mapConstraints { TransitionRepo.insert(conn, c.workspaceId, c.fromStatusId, c.toStatusId) }
        return TransitionRepo.get(conn, id)!!
    }

    private fun archiveTransition(conn: Connection, c: ArchiveTransition): StatusTransition {
        TransitionRepo.get(conn, c.transitionId) ?: throw StxException.NotFound("transition ${c.transitionId}")
        requireWritten(TransitionRepo.archive(conn, c.transitionId, c.expectedVersion), c.expectedVersion)
        return TransitionRepo.get(conn, c.transitionId)!!
    }

    // ── track ──────────────────────────────────────────────────────────────────
    private fun createTrack(conn: Connection, c: CreateTrack): Track {
        liveWorkspace(conn, c.workspaceId)
        requireName(c.name, "track")
        val id = mapConstraints {
            TrackRepo.insert(conn, c.workspaceId, c.name, c.description, MetadataCodec.encode(c.metadata))
        }
        // Invariant 3: every track has exactly one root segment, auto-created with it.
        SegmentRepo.insert(conn, c.workspaceId, id, parentSegmentId = null, name = c.name, isRoot = true)
        return TrackRepo.get(conn, id)!!
    }

    private fun updateTrack(conn: Connection, c: UpdateTrack): Track {
        liveTrack(conn, c.trackId)
        c.name?.let { requireName(it, "track") }
        val metaJson = c.metadata?.let { MetadataCodec.encode(it) }
        val rows = mapConstraints {
            TrackRepo.update(conn, c.trackId, c.name, c.description, metaJson, c.expectedVersion)
        }
        requireWritten(rows, c.expectedVersion)
        return TrackRepo.get(conn, c.trackId)!!
    }

    private fun archiveTrack(conn: Connection, c: ArchiveTrack): Track {
        liveTrack(conn, c.trackId)
        requireWritten(TrackRepo.archive(conn, c.trackId, c.expectedVersion), c.expectedVersion)
        // Cascade: archive the track's segments, their tasks, and those tasks' incident edges.
        val segmentIds = SegmentRepo.liveIdsByTrack(conn, c.trackId)
        cascadeArchiveSegmentsAndTasks(conn, segmentIds)
        return TrackRepo.get(conn, c.trackId)!!
    }

    // ── segment ──────────────────────────────────────────────────────────────────
    private fun createSegment(conn: Connection, c: CreateSegment): Segment {
        val track = liveTrack(conn, c.trackId)
        requireName(c.name, "segment")
        if (c.parentSegmentId != null) {
            val parent = liveSegment(conn, c.parentSegmentId)
            if (parent.trackId != c.trackId) {
                throw StxException.Validation("parent segment belongs to a different track")
            }
        }
        val id = mapConstraints {
            SegmentRepo.insert(conn, track.workspaceId, c.trackId, c.parentSegmentId, c.name, isRoot = false)
        }
        return SegmentRepo.get(conn, id)!!
    }

    private fun renameSegment(conn: Connection, c: RenameSegment): Segment {
        liveSegment(conn, c.segmentId)
        requireName(c.name, "segment")
        requireWritten(SegmentRepo.rename(conn, c.segmentId, c.name, c.expectedVersion), c.expectedVersion)
        return SegmentRepo.get(conn, c.segmentId)!!
    }

    private fun moveSegment(conn: Connection, c: MoveSegment): Segment {
        val seg = liveSegment(conn, c.segmentId)
        if (seg.isRoot) throw StxException.Validation("the root segment cannot be reparented")
        if (c.newParentSegmentId != null) {
            val parent = liveSegment(conn, c.newParentSegmentId)
            // Invariant 5: track_id is immutable — a reparent may not cross tracks.
            if (parent.trackId != seg.trackId) {
                throw StxException.Validation("cannot move a segment to a different track")
            }
            // Invariant 2: no cycles in the segment tree.
            if (Invariants.segmentReparentWouldCycle(conn, c.segmentId, c.newParentSegmentId)) {
                throw StxException.Validation("reparenting would create a cycle in the segment tree")
            }
        }
        requireWritten(
            SegmentRepo.reparent(conn, c.segmentId, c.newParentSegmentId, c.expectedVersion),
            c.expectedVersion,
        )
        return SegmentRepo.get(conn, c.segmentId)!!
    }

    private fun archiveSegment(conn: Connection, c: ArchiveSegment): Segment {
        liveSegment(conn, c.segmentId)
        requireWritten(SegmentRepo.archive(conn, c.segmentId, c.expectedVersion), c.expectedVersion)
        // Cascade: archive descendant segments, their tasks, and those tasks' incident edges.
        // The subtree includes c.segmentId itself; archiving it twice is harmless (idempotent).
        cascadeArchiveSegmentsAndTasks(conn, SegmentRepo.subtreeIds(conn, c.segmentId))
        return SegmentRepo.get(conn, c.segmentId)!!
    }

    // ── task ─────────────────────────────────────────────────────────────────────
    private fun createTask(conn: Connection, c: CreateTask): Task {
        val segment = liveSegment(conn, c.segmentId)
        val status = liveStatus(conn, c.statusId)
        if (status.workspaceId != segment.workspaceId) {
            throw StxException.Validation("status belongs to a different workspace than the segment")
        }
        requireName(c.title, "task")
        val id = mapConstraints {
            TaskRepo.insert(
                conn, segment.workspaceId, c.segmentId, c.statusId, c.kind, c.title,
                c.description, c.priority, c.dueDate, c.startDate, c.finishDate,
                MetadataCodec.encode(c.metadata),
            )
        }
        return TaskRepo.get(conn, id)!!
    }

    private fun updateTask(conn: Connection, c: UpdateTask): Task {
        liveTask(conn, c.taskId)
        c.patch.title?.let { requireName(it, "task") }
        val rows = mapConstraints { TaskRepo.applyPatch(conn, c.taskId, c.patch, c.expectedVersion) }
        requireWritten(rows, c.expectedVersion)
        return TaskRepo.get(conn, c.taskId)!!
    }

    private fun moveTask(conn: Connection, c: MoveTask): Task {
        val task = liveTask(conn, c.taskId)
        val to = liveStatus(conn, c.toStatusId)
        if (to.workspaceId != task.workspaceId) {
            throw StxException.Validation("target status belongs to a different workspace")
        }
        if (task.statusId == c.toStatusId) return task // no-op move
        if (!TransitionRepo.exists(conn, task.workspaceId, task.statusId, c.toStatusId)) {
            throw StxException.Validation("no legal transition from status ${task.statusId} to ${c.toStatusId}")
        }
        requireWritten(TaskRepo.moveStatus(conn, c.taskId, c.toStatusId, c.expectedVersion), c.expectedVersion)
        return TaskRepo.get(conn, c.taskId)!!
    }

    private fun moveTaskToSegment(conn: Connection, c: MoveTaskToSegment): Task {
        val task = liveTask(conn, c.taskId)
        val segment = liveSegment(conn, c.toSegmentId)
        // task.segment_id is the uniform parent — it must not cross a workspace boundary.
        if (segment.workspaceId != task.workspaceId) {
            throw StxException.Validation("target segment belongs to a different workspace")
        }
        if (task.segmentId == c.toSegmentId) return task // no-op move
        requireWritten(TaskRepo.moveSegment(conn, c.taskId, c.toSegmentId, c.expectedVersion), c.expectedVersion)
        return TaskRepo.get(conn, c.taskId)!!
    }

    private fun archiveTask(conn: Connection, c: ArchiveTask): Task {
        liveTask(conn, c.taskId)
        requireWritten(TaskRepo.archive(conn, c.taskId, c.expectedVersion), c.expectedVersion)
        // Invariant 4: archive incident edges in the same transaction so a live edge always
        // joins two live tasks (lets the frontier skip checking blocker archived-state).
        BlocksRepo.archiveIncident(conn, c.taskId)
        RelatesRepo.archiveIncident(conn, c.taskId)
        return TaskRepo.get(conn, c.taskId)!!
    }

    // ── edges ──────────────────────────────────────────────────────────────────
    private fun addBlocks(conn: Connection, c: AddBlocks): Blocks {
        if (c.sourceTaskId == c.targetTaskId) throw StxException.Validation("a task cannot block itself")
        val source = liveTask(conn, c.sourceTaskId)
        val target = liveTask(conn, c.targetTaskId)
        if (source.workspaceId != target.workspaceId) {
            throw StxException.Validation("blocks edge cannot cross a workspace boundary")
        }
        // Invariant 1: blocks must stay acyclic.
        if (Invariants.blocksWouldCycle(conn, source.workspaceId, c.sourceTaskId, c.targetTaskId)) {
            throw StxException.Validation("blocks edge would create a cycle")
        }
        val id = mapConstraints {
            BlocksRepo.insert(conn, source.workspaceId, c.sourceTaskId, c.targetTaskId, MetadataCodec.encode(c.metadata))
        }
        return BlocksRepo.get(conn, id)!!
    }

    private fun archiveBlocks(conn: Connection, c: ArchiveBlocks): Blocks {
        BlocksRepo.get(conn, c.blocksId) ?: throw StxException.NotFound("blocks ${c.blocksId}")
        requireWritten(BlocksRepo.archive(conn, c.blocksId, c.expectedVersion), c.expectedVersion)
        return BlocksRepo.get(conn, c.blocksId)!!
    }

    private fun addRelatesTo(conn: Connection, c: AddRelatesTo): RelatesTo {
        requireName(c.kind, "relates_to kind")
        if (c.sourceTaskId == c.targetTaskId) throw StxException.Validation("a task cannot relate to itself")
        val source = liveTask(conn, c.sourceTaskId)
        val target = liveTask(conn, c.targetTaskId)
        if (source.workspaceId != target.workspaceId) {
            throw StxException.Validation("relates_to edge cannot cross a workspace boundary")
        }
        val id = mapConstraints {
            RelatesRepo.insert(conn, source.workspaceId, c.kind, c.sourceTaskId, c.targetTaskId, MetadataCodec.encode(c.metadata))
        }
        return RelatesRepo.get(conn, id)!!
    }

    private fun archiveRelatesTo(conn: Connection, c: ArchiveRelatesTo): RelatesTo {
        RelatesRepo.get(conn, c.relatesId) ?: throw StxException.NotFound("relates_to ${c.relatesId}")
        requireWritten(RelatesRepo.archive(conn, c.relatesId, c.expectedVersion), c.expectedVersion)
        return RelatesRepo.get(conn, c.relatesId)!!
    }

    // ── per-key metadata ─────────────────────────────────────────────────────────
    private fun setMetaKey(conn: Connection, c: SetMetaKey): Any {
        val key = normalizeMetaKey(c.key)
        return mutateMeta(conn, c.entity, c.entityId, c.expectedVersion) { it + (key to c.value) }
    }

    private fun deleteMetaKey(conn: Connection, c: DeleteMetaKey): Any {
        val key = normalizeMetaKey(c.key)
        return mutateMeta(conn, c.entity, c.entityId, c.expectedVersion) { it - key }
    }

    /**
     * Read-modify-write a single metadata blob: load the live entity, transform its map, persist.
     * Returns the refreshed entity. The whole thing runs inside the caller's transaction, so the
     * read-then-write is atomic against other writers (the single write-actor serializes mutations).
     */
    private fun mutateMeta(
        conn: Connection,
        entity: MetaEntity,
        id: Long,
        expectedVersion: Long?,
        transform: (Metadata) -> Metadata,
    ): Any = when (entity) {
        MetaEntity.WORKSPACE -> {
            val e = liveWorkspace(conn, id)
            val json = MetadataCodec.encode(transform(e.metadata))
            requireWritten(WorkspaceRepo.update(conn, id, null, json, expectedVersion), expectedVersion)
            WorkspaceRepo.get(conn, id)!!
        }
        MetaEntity.TRACK -> {
            val e = liveTrack(conn, id)
            val json = MetadataCodec.encode(transform(e.metadata))
            requireWritten(TrackRepo.update(conn, id, null, null, json, expectedVersion), expectedVersion)
            TrackRepo.get(conn, id)!!
        }
        MetaEntity.TASK -> {
            val e = liveTask(conn, id)
            requireWritten(
                TaskRepo.applyPatch(conn, id, TaskPatch(metadata = transform(e.metadata)), expectedVersion),
                expectedVersion,
            )
            TaskRepo.get(conn, id)!!
        }
        MetaEntity.BLOCKS -> {
            val e = BlocksRepo.get(conn, id)?.takeUnless { it.archived } ?: throw StxException.NotFound("blocks $id")
            val json = MetadataCodec.encode(transform(e.metadata))
            requireWritten(BlocksRepo.updateMetadata(conn, id, json, expectedVersion), expectedVersion)
            BlocksRepo.get(conn, id)!!
        }
        MetaEntity.RELATES_TO -> {
            val e = RelatesRepo.get(conn, id)?.takeUnless { it.archived }
                ?: throw StxException.NotFound("relates_to $id")
            val json = MetadataCodec.encode(transform(e.metadata))
            requireWritten(RelatesRepo.updateMetadata(conn, id, json, expectedVersion), expectedVersion)
            RelatesRepo.get(conn, id)!!
        }
    }

    // ── cascade + CAS helpers ────────────────────────────────────────────────────
    /** Bulk-archive a set of segments, every live task inside them, and those tasks' incident edges. */
    private fun cascadeArchiveSegmentsAndTasks(conn: Connection, segmentIds: List<Long>) {
        if (segmentIds.isEmpty()) return
        val taskIds = TaskRepo.liveIdsInSegments(conn, segmentIds)
        // Invariant 4: archive incident edges so a live edge always joins two live tasks.
        BlocksRepo.archiveIncidentToAny(conn, taskIds)
        RelatesRepo.archiveIncidentToAny(conn, taskIds)
        TaskRepo.archiveByIds(conn, taskIds)
        SegmentRepo.archiveByIds(conn, segmentIds)
    }

    /** A versioned write that affected zero rows after a live-guard passed means the version was stale. */
    private fun requireWritten(rows: Int, expectedVersion: Long?) {
        if (expectedVersion != null && rows == 0) {
            throw StxException.Conflict("version conflict: the entity was modified concurrently (stale expectedVersion)")
        }
    }

    /** Metadata keys are normalized to lowercase (matching the v2 convention). */
    private fun normalizeMetaKey(key: String): String {
        val k = key.trim().lowercase()
        if (k.isEmpty()) throw StxException.Validation("metadata key must not be blank")
        return k
    }

    // ── shared guards ────────────────────────────────────────────────────────────
    private fun liveWorkspace(conn: Connection, id: Long): Workspace =
        WorkspaceRepo.get(conn, id)?.takeUnless { it.archived }
            ?: throw StxException.NotFound("workspace $id")

    private fun liveStatus(conn: Connection, id: Long): Status =
        StatusRepo.get(conn, id)?.takeUnless { it.archived } ?: throw StxException.NotFound("status $id")

    private fun liveTrack(conn: Connection, id: Long): Track =
        TrackRepo.get(conn, id)?.takeUnless { it.archived } ?: throw StxException.NotFound("track $id")

    private fun liveSegment(conn: Connection, id: Long): Segment =
        SegmentRepo.get(conn, id)?.takeUnless { it.archived } ?: throw StxException.NotFound("segment $id")

    private fun liveTask(conn: Connection, id: Long): Task =
        TaskRepo.get(conn, id)?.takeUnless { it.archived } ?: throw StxException.NotFound("task $id")

    private fun requireName(value: String, what: String) {
        if (value.isBlank()) throw StxException.Validation("$what name must not be blank")
    }

    /** Translate SQLite constraint failures into the service error taxonomy. */
    private fun <T> mapConstraints(block: () -> T): T = try {
        block()
    } catch (e: SQLException) {
        val m = e.message ?: ""
        when {
            "UNIQUE constraint failed" in m -> throw StxException.Conflict(m)
            "FOREIGN KEY constraint failed" in m -> throw StxException.Validation("referenced entity does not exist")
            "CHECK constraint failed" in m -> throw StxException.Validation(m)
            else -> throw e
        }
    }
}
