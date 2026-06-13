package stx.service

import stx.Blocks
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
import stx.command.MoveSegment
import stx.command.MoveTask
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
        is MoveSegment -> moveSegment(conn, command)
        is ArchiveSegment -> archiveSegment(conn, command)
        is CreateTask -> createTask(conn, command)
        is UpdateTask -> updateTask(conn, command)
        is MoveTask -> moveTask(conn, command)
        is ArchiveTask -> archiveTask(conn, command)
        is AddBlocks -> addBlocks(conn, command)
        is ArchiveBlocks -> archiveBlocks(conn, command)
        is AddRelatesTo -> addRelatesTo(conn, command)
        is ArchiveRelatesTo -> archiveRelatesTo(conn, command)
    }

    // ── workspace ──────────────────────────────────────────────────────────────
    private fun createWorkspace(conn: Connection, c: CreateWorkspace): Workspace {
        requireName(c.name, "workspace")
        val id = mapConstraints { WorkspaceRepo.insert(conn, c.name, MetadataCodec.encode(c.metadata)) }
        return WorkspaceRepo.get(conn, id)!!
    }

    private fun updateWorkspace(conn: Connection, c: UpdateWorkspace): Workspace {
        liveWorkspace(conn, c.workspaceId)
        c.name?.let { requireName(it, "workspace"); mapConstraints { WorkspaceRepo.updateName(conn, c.workspaceId, it) } }
        c.metadata?.let { WorkspaceRepo.updateMetadata(conn, c.workspaceId, MetadataCodec.encode(it)) }
        return WorkspaceRepo.get(conn, c.workspaceId)!!
    }

    private fun archiveWorkspace(conn: Connection, c: ArchiveWorkspace): Workspace {
        liveWorkspace(conn, c.workspaceId)
        WorkspaceRepo.archive(conn, c.workspaceId)
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
        mapConstraints { StatusRepo.update(conn, c.statusId, c.name, c.terminal, c.kanbanOrder) }
        return StatusRepo.get(conn, c.statusId)!!
    }

    private fun archiveStatus(conn: Connection, c: ArchiveStatus): Status {
        liveStatus(conn, c.statusId)
        StatusRepo.archive(conn, c.statusId)
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
        val t = TransitionRepo.get(conn, c.transitionId) ?: throw StxException.NotFound("transition ${c.transitionId}")
        TransitionRepo.archive(conn, c.transitionId)
        return t.copy(archived = true)
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
        mapConstraints { TrackRepo.update(conn, c.trackId, c.name, c.description, metaJson) }
        return TrackRepo.get(conn, c.trackId)!!
    }

    private fun archiveTrack(conn: Connection, c: ArchiveTrack): Track {
        liveTrack(conn, c.trackId)
        TrackRepo.archive(conn, c.trackId)
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
        SegmentRepo.reparent(conn, c.segmentId, c.newParentSegmentId)
        return SegmentRepo.get(conn, c.segmentId)!!
    }

    private fun archiveSegment(conn: Connection, c: ArchiveSegment): Segment {
        val seg = liveSegment(conn, c.segmentId)
        SegmentRepo.archive(conn, c.segmentId)
        return seg.copy(archived = true)
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
        mapConstraints { TaskRepo.applyPatch(conn, c.taskId, c.patch) }
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
        TaskRepo.moveStatus(conn, c.taskId, c.toStatusId)
        return TaskRepo.get(conn, c.taskId)!!
    }

    private fun archiveTask(conn: Connection, c: ArchiveTask): Task {
        liveTask(conn, c.taskId)
        // Invariant 4: archive incident edges in the same transaction so a live edge always
        // joins two live tasks (lets the frontier skip checking blocker archived-state).
        BlocksRepo.archiveIncident(conn, c.taskId)
        RelatesRepo.archiveIncident(conn, c.taskId)
        TaskRepo.archive(conn, c.taskId)
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
        val b = BlocksRepo.get(conn, c.blocksId) ?: throw StxException.NotFound("blocks ${c.blocksId}")
        BlocksRepo.archive(conn, c.blocksId)
        return b.copy(archived = true)
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
        val r = RelatesRepo.get(conn, c.relatesId) ?: throw StxException.NotFound("relates_to ${c.relatesId}")
        RelatesRepo.archive(conn, c.relatesId)
        return r.copy(archived = true)
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
