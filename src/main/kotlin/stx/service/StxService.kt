package stx.service

import stx.command.*
import stx.dto.*
import stx.error.StxError
import stx.repo.*
import tech.codingzen.res.*
import java.sql.Connection

/**
 * The service: one exhaustive `when(command)` (no else) folding every verb to
 * `Res<Reply, StxError>` (brief §5). Write handlers carry the daemon invariants (§3) via
 * `rail { } / ensure / raise`; reads run plain queries. The caller supplies the [Connection]:
 * the write-actor wraps writes in a transaction ([applyWrite], commit IFF Ok); reads run inline.
 */
class StxService {

    fun dispatch(c: Connection, command: Command): Res<Reply, StxError> = when (command) {
        // ── reads ──
        is ListWorkspaces -> read { WorkspaceList(WorkspaceRepo.listLive(c)) }
        is ListTracks -> read { TrackList(TrackRepo.listLive(c, command.workspaceId)) }
        is ListSegments -> read { SegmentList(SegmentRepo.listLive(c, command.trackId)) }
        is ListStatuses -> read { StatusList(StatusRepo.listLive(c, command.workspaceId)) }
        is ListKinds -> read { KindList(KindRepo.listLive(c, command.workspaceId)) }
        is ListRelatesKinds -> read { RelatesKindList(RelatesRepo.distinctKinds(c, command.workspaceId)) }
        is ListTransitions -> read { TransitionList(TransitionRepo.listLive(c, command.workspaceId)) }
        is ListEdges -> read { EdgeList(BlocksRepo.liveByWorkspace(c, command.workspaceId), RelatesRepo.liveByWorkspace(c, command.workspaceId)) }
        is ListTasks -> read { TaskList(TaskRepo.listVisibleByTrack(c, command.trackId, command.statusId)) }
        is GetTask -> getTask(c, command)
        is Next -> Frontier.next(c, command)
        // ── writes: registries & containers ──
        is CreateWorkspace -> createWorkspace(c, command)
        is CreateStatus -> createStatus(c, command)
        is SetDefaultStatus -> setDefaultStatus(c, command)
        is CreateKind -> createKind(c, command)
        is CreateTransition -> createTransition(c, command)
        is CreateTrack -> createTrack(c, command)
        is CreateSegment -> createSegment(c, command)
        // ── writes: tasks ──
        is CreateTask -> createTask(c, command)
        is MoveStatus -> moveStatus(c, command)
        is EditTask -> editTask(c, command)
        is EditWorkspace -> editWorkspace(c, command)
        is EditTrack -> editTrack(c, command)
        // ── writes: edges ──
        is AddBlocks -> addBlocks(c, command)
        is AddRelates -> addRelates(c, command)
        is RemoveBlocks -> removeBlocks(c, command)
        is RemoveRelates -> removeRelates(c, command)
        // ── writes: archives ──
        is ArchiveTask -> archiveTask(c, command)
        is ArchiveSegment -> archiveSegment(c, command)
        is ArchiveTrack -> archiveTrack(c, command)
        is ArchiveWorkspace -> archiveWorkspace(c, command)
        is ArchiveStatus -> archiveStatus(c, command)
        is ArchiveKind -> archiveKind(c, command)
    }

    // ── reads ────────────────────────────────────────────────────────────────────────────────

    private inline fun read(block: () -> Reply): Res<Reply, StxError> = catching { block() }

    private fun getTask(c: Connection, cmd: GetTask): Res<Reply, StxError> = rail {
        val t = TaskRepo.getById(c, cmd.id) ?: raise(StxError.NotFound("task", cmd.id))
        val relates = RelatesRepo.liveIncident(c, t.id)
            .map { r ->
                val outgoing = r.sourceTaskId == t.id
                RelatesEdge(r.kind, if (outgoing) r.targetTaskId else r.sourceTaskId, outgoing)
            }
            .distinctBy { it.kind to it.otherTaskId } // symmetric display dedup (decision D2)
        TaskDetail(t, BlocksRepo.liveOutgoing(c, t.id), BlocksRepo.liveIncoming(c, t.id), relates)
    }

    // ── bootstrap (brief §3) ─────────────────────────────────────────────────────────────────

    private fun createWorkspace(c: Connection, cmd: CreateWorkspace): Res<Reply, StxError> = rail {
        requireNonBlank("name", cmd.name).bind()
        requireJsonObject("metadata_json", cmd.metadataJson).bind()
        val wsId = WorkspaceRepo.insert(c, cmd.name, cmd.metadataJson).bind()
        val backlog = StatusRepo.insert(c, wsId, "Backlog", 0, terminal = false, isDefault = true).bind()
        val impl = StatusRepo.insert(c, wsId, "Implementation", 1, terminal = false, isDefault = false).bind()
        val review = StatusRepo.insert(c, wsId, "Review", 2, terminal = false, isDefault = false).bind()
        val done = StatusRepo.insert(c, wsId, "Done", 3, terminal = true, isDefault = false).bind()
        // Seeded transition set: forward flow + rework back-edges. Reaching a terminal status is
        // always legal regardless of edges (see moveStatus), so no direct →Done edges are seeded
        // from Backlog/Implementation.
        TransitionRepo.insert(c, wsId, backlog, impl).bind()
        TransitionRepo.insert(c, wsId, impl, review).bind()
        TransitionRepo.insert(c, wsId, review, done).bind()
        TransitionRepo.insert(c, wsId, impl, backlog).bind()
        TransitionRepo.insert(c, wsId, review, impl).bind()
        TransitionRepo.insert(c, wsId, done, review).bind()
        WorkspaceRepo.getById(c, wsId) ?: raise(StxError.NotFound("workspace", wsId))
    }

    private fun createStatus(c: Connection, cmd: CreateStatus): Res<Reply, StxError> = rail {
        requireNonBlank("name", cmd.name).bind()
        WorkspaceRepo.getLive(c, cmd.workspaceId) ?: raise(StxError.NotFound("workspace", cmd.workspaceId))
        // Reject case-insensitive near-duplicates (e.g. "done" when "Done" exists) up front — the SQL
        // uniqueness index is byte-exact, so without this guard both would coexist and confuse the CLI.
        val wanted = cmd.name.trim()
        if (StatusRepo.listLive(c, cmd.workspaceId).any { it.name.trim().equals(wanted, ignoreCase = true) }) {
            raise(StxError.Duplicate("status", "status name '${cmd.name}'"))
        }
        val id = StatusRepo.insert(c, cmd.workspaceId, cmd.name, cmd.kanbanOrder, cmd.terminal, isDefault = false).bind()
        StatusRepo.getById(c, id) ?: raise(StxError.NotFound("status", id))
    }

    private fun setDefaultStatus(c: Connection, cmd: SetDefaultStatus): Res<Reply, StxError> = rail {
        val st = StatusRepo.getLive(c, cmd.statusId) ?: raise(StxError.NotFound("status", cmd.statusId))
        ensure(st.workspaceId == cmd.workspaceId) { StxError.CrossWorkspace(st.id, cmd.workspaceId) }
        // A terminal status as the default would birth every new task "done" and invisible to `next`.
        ensure(!st.terminal) { StxError.Validation("a terminal status cannot be the default") }
        StatusRepo.clearDefault(c, cmd.workspaceId)
        StatusRepo.setDefault(c, st.id).bind()
        IdReply("status", st.id)
    }

    private fun createKind(c: Connection, cmd: CreateKind): Res<Reply, StxError> = rail {
        requireNonBlank("name", cmd.name).bind()
        WorkspaceRepo.getLive(c, cmd.workspaceId) ?: raise(StxError.NotFound("workspace", cmd.workspaceId))
        // Reject case-insensitive near-duplicates (e.g. "Impl" when "impl" exists) so `next --kind`
        // can't fragment — the SQL uniqueness index is byte-exact and won't catch this on its own.
        val wanted = cmd.name.trim()
        if (KindRepo.listLive(c, cmd.workspaceId).any { it.name.trim().equals(wanted, ignoreCase = true) }) {
            raise(StxError.Duplicate("kind", "kind name '${cmd.name}'"))
        }
        val id = KindRepo.insert(c, cmd.workspaceId, cmd.name).bind()
        KindRepo.getById(c, id) ?: raise(StxError.NotFound("kind", id))
    }

    private fun createTransition(c: Connection, cmd: CreateTransition): Res<Reply, StxError> = rail {
        WorkspaceRepo.getLive(c, cmd.workspaceId) ?: raise(StxError.NotFound("workspace", cmd.workspaceId))
        ensure(cmd.fromStatusId != cmd.toStatusId) { StxError.Validation("self-transition") }
        val from = StatusRepo.getLive(c, cmd.fromStatusId) ?: raise(StxError.NotFound("status", cmd.fromStatusId))
        val to = StatusRepo.getLive(c, cmd.toStatusId) ?: raise(StxError.NotFound("status", cmd.toStatusId))
        // #8: both endpoints belong to the transition's workspace.
        ensure(from.workspaceId == cmd.workspaceId && to.workspaceId == cmd.workspaceId) { StxError.CrossWorkspace(from.id, to.id) }
        val id = TransitionRepo.insert(c, cmd.workspaceId, from.id, to.id).bind()
        TransitionDto(id, cmd.workspaceId, from.id, to.id, archived = false)
    }

    private fun createTrack(c: Connection, cmd: CreateTrack): Res<Reply, StxError> = rail {
        requireNonBlank("name", cmd.name).bind()
        requireJsonObject("metadata_json", cmd.metadataJson).bind()
        val ws = WorkspaceRepo.getLive(c, cmd.workspaceId) ?: raise(StxError.NotFound("workspace", cmd.workspaceId))
        val trackId = TrackRepo.insert(c, ws.id, cmd.name, cmd.description, cmd.metadataJson).bind()
        SegmentRepo.insert(c, ws.id, trackId, parentSegmentId = null, name = "(root)", isRoot = true).bind() // #3
        TrackRepo.getById(c, trackId) ?: raise(StxError.NotFound("track", trackId))
    }

    private fun createSegment(c: Connection, cmd: CreateSegment): Res<Reply, StxError> = rail {
        requireNonBlank("name", cmd.name).bind()
        val track = TrackRepo.getLive(c, cmd.trackId) ?: raise(StxError.NotFound("track", cmd.trackId))
        val parentId = if (cmd.parentSegmentId != null) {
            val parent = SegmentRepo.getLive(c, cmd.parentSegmentId) ?: raise(StxError.NotFound("segment", cmd.parentSegmentId))
            // #8: parent shares the new segment's track + workspace.
            ensure(parent.trackId == track.id && parent.workspaceId == track.workspaceId) { StxError.CrossWorkspace(cmd.parentSegmentId, track.id) }
            parent.id
        } else {
            // No explicit parent → nest under the track's synthetic root, mirroring createTask. Without
            // this the row got a NULL parent and the `tree` view (which descends only from the root) hid it.
            SegmentRepo.rootOf(c, track.id)?.id ?: raise(StxError.NotFound("segment", track.id))
        }
        val id = SegmentRepo.insert(c, track.workspaceId, track.id, parentId, cmd.name, isRoot = false).bind()
        SegmentRepo.getById(c, id) ?: raise(StxError.NotFound("segment", id))
    }

    // ── tasks ────────────────────────────────────────────────────────────────────────────────

    private fun createTask(c: Connection, cmd: CreateTask): Res<Reply, StxError> = rail {
        requireNonBlank("title", cmd.title).bind()
        requireJsonObject("metadata_json", cmd.metadataJson).bind()
        val seg = when {
            cmd.segmentId != null -> SegmentRepo.getLive(c, cmd.segmentId) ?: raise(StxError.NotFound("segment", cmd.segmentId))
            cmd.trackId != null -> {
                val track = TrackRepo.getLive(c, cmd.trackId) ?: raise(StxError.NotFound("track", cmd.trackId))
                SegmentRepo.rootOf(c, track.id) ?: raise(StxError.NotFound("segment", track.id))
            }
            else -> raise(StxError.Validation("task create requires segmentId or trackId"))
        }
        val ws = seg.workspaceId // #8: workspace_id derived from the segment's track chain, never caller-supplied.
        val statusId = if (cmd.statusId != null) {
            val s = StatusRepo.getLive(c, cmd.statusId) ?: raise(StxError.NotFound("status", cmd.statusId))
            ensure(s.workspaceId == ws) { StxError.CrossWorkspace(s.id, ws) }
            s.id
        } else {
            (StatusRepo.liveDefault(c, ws) ?: raise(StxError.Validation("workspace has no default status"))).id
        }
        if (cmd.kindId != null) {
            val k = KindRepo.getLive(c, cmd.kindId) ?: raise(StxError.NotFound("kind", cmd.kindId))
            ensure(k.workspaceId == ws) { StxError.CrossWorkspace(k.id, ws) }
        }
        val id = TaskRepo.insert(
            c, ws, seg.id, statusId, cmd.kindId, cmd.title, cmd.description, cmd.priority, cmd.metadataJson,
        ).bind()
        TaskRepo.getById(c, id) ?: raise(StxError.NotFound("task", id))
    }

    private fun moveStatus(c: Connection, cmd: MoveStatus): Res<Reply, StxError> = rail {
        val task = loadVisibleTask(c, cmd.taskId).bind()
        // OL first (§6): a stale read invalidates the whole plan — including which transition is
        // legal — so a racing loser gets a clean VersionConflict, not an IllegalTransition.
        ensure(task.version == cmd.expectedVersion) {
            StxError.VersionConflict("task", task.id, cmd.expectedVersion, task.version)
        }
        val to = StatusRepo.getLive(c, cmd.toStatusId) ?: raise(StxError.NotFound("status", cmd.toStatusId))
        ensure(to.workspaceId == task.workspaceId) { StxError.CrossWorkspace(to.id, task.workspaceId) }
        // Reaching a terminal status ("done") is an always-legal escape hatch from any status; the
        // transition graph only governs moves between non-terminal states. So `stx done` (and an
        // explicit `mv <id> Done`) succeed from anywhere, while other moves still respect the edges.
        ensure(to.terminal || TransitionRepo.liveExists(c, task.workspaceId, task.statusId, to.id)) {
            StxError.IllegalTransition(task.id, task.statusId, to.id)
        }
        val changes = TaskRepo.casMoveStatus(c, task.id, to.id, cmd.expectedVersion)
        interpretCas(c, "task", "task", task.id, cmd.expectedVersion, changes).bind()
        TaskRepo.getById(c, task.id) ?: raise(StxError.NotFound("task", task.id))
    }

    private fun editTask(c: Connection, cmd: EditTask): Res<Reply, StxError> = rail {
        cmd.title?.let { requireNonBlank("title", it).bind() }
        cmd.metadataJson?.let { requireJsonObject("metadata_json", it).bind() }
        val task = loadVisibleTask(c, cmd.taskId).bind()
        // clearKind wins in casEdit, so don't validate a (possibly stale) kindId that is being cleared.
        if (!cmd.clearKind && cmd.kindId != null) {
            val k = KindRepo.getLive(c, cmd.kindId) ?: raise(StxError.NotFound("kind", cmd.kindId))
            ensure(k.workspaceId == task.workspaceId) { StxError.CrossWorkspace(k.id, task.workspaceId) }
        }
        val changes = TaskRepo.casEdit(c, cmd)
        interpretCas(c, "task", "task", cmd.taskId, cmd.expectedVersion, changes).bind()
        TaskRepo.getById(c, cmd.taskId) ?: raise(StxError.NotFound("task", cmd.taskId))
    }

    private fun editWorkspace(c: Connection, cmd: EditWorkspace): Res<Reply, StxError> = rail {
        cmd.name?.let { requireNonBlank("name", it).bind() }
        cmd.metadataJson?.let { requireJsonObject("metadata_json", it).bind() }
        val changes = WorkspaceRepo.casEdit(c, cmd.id, cmd.expectedVersion, cmd.name, cmd.metadataJson)
        interpretCas(c, "workspace", "workspace", cmd.id, cmd.expectedVersion, changes).bind()
        WorkspaceRepo.getById(c, cmd.id) ?: raise(StxError.NotFound("workspace", cmd.id))
    }

    private fun editTrack(c: Connection, cmd: EditTrack): Res<Reply, StxError> = rail {
        cmd.name?.let { requireNonBlank("name", it).bind() }
        cmd.metadataJson?.let { requireJsonObject("metadata_json", it).bind() }
        val changes = TrackRepo.casEdit(c, cmd.id, cmd.expectedVersion, cmd.name, cmd.description, cmd.metadataJson)
        interpretCas(c, "track", "track", cmd.id, cmd.expectedVersion, changes).bind()
        TrackRepo.getById(c, cmd.id) ?: raise(StxError.NotFound("track", cmd.id))
    }

    // ── edges ────────────────────────────────────────────────────────────────────────────────

    private fun addBlocks(c: Connection, cmd: AddBlocks): Res<Reply, StxError> = rail {
        val s = loadVisibleTask(c, cmd.sourceTaskId).bind()
        val t = loadVisibleTask(c, cmd.targetTaskId).bind()
        ensure(s.workspaceId == t.workspaceId) { StxError.CrossWorkspace(s.id, t.id) }       // #7
        ensure(!blocksWouldCycle(c, s.id, t.id)) { StxError.CycleRejected("blocks", s.id, t.id) } // #1
        val id = BlocksRepo.insert(c, s.workspaceId, s.id, t.id).bind()
        BlocksDto(id, s.workspaceId, s.id, t.id, archived = false)
    }

    private fun addRelates(c: Connection, cmd: AddRelates): Res<Reply, StxError> = rail {
        val s = loadVisibleTask(c, cmd.sourceTaskId).bind()
        val t = loadVisibleTask(c, cmd.targetTaskId).bind()
        ensure(s.id != t.id) { StxError.Validation("self relation") }
        ensure(s.workspaceId == t.workspaceId) { StxError.CrossWorkspace(s.id, t.id) }       // #7
        val id = RelatesRepo.insert(c, s.workspaceId, cmd.kind, s.id, t.id).bind()
        RelatesDto(id, s.workspaceId, cmd.kind, s.id, t.id, archived = false)
    }

    private fun removeBlocks(c: Connection, cmd: RemoveBlocks): Res<Reply, StxError> = rail {
        val s = loadVisibleTask(c, cmd.sourceTaskId).bind()
        val t = loadVisibleTask(c, cmd.targetTaskId).bind()
        ensure(BlocksRepo.archiveEdge(c, s.id, t.id) > 0) { StxError.NotFound("blocks", t.id) }
        IdReply("blocks", t.id)
    }

    private fun removeRelates(c: Connection, cmd: RemoveRelates): Res<Reply, StxError> = rail {
        val s = loadVisibleTask(c, cmd.sourceTaskId).bind()
        val t = loadVisibleTask(c, cmd.targetTaskId).bind()
        ensure(RelatesRepo.archiveEdge(c, cmd.kind, s.id, t.id) > 0) { StxError.NotFound("relates_to", t.id) }
        IdReply("relates_to", t.id)
    }

    // ── archives (cascades: #4 edges, #6 containers, #9 status/kind) ─────────────────────────

    private fun archiveTask(c: Connection, cmd: ArchiveTask): Res<Reply, StxError> = rail {
        val row = TaskRepo.getById(c, cmd.id) ?: raise(StxError.NotFound("task", cmd.id))
        if (row.archived) raise(StxError.Gone("task", cmd.id))
        archiveTaskCascade(c, cmd.id)
        IdReply("task", cmd.id)
    }

    private fun archiveSegment(c: Connection, cmd: ArchiveSegment): Res<Reply, StxError> = rail {
        val seg = SegmentRepo.getById(c, cmd.id) ?: raise(StxError.NotFound("segment", cmd.id))
        if (seg.archived) raise(StxError.Gone("segment", cmd.id))
        ensure(!seg.isRoot) { StxError.Validation("root segment is archived only via its track") } // #6
        archiveSegmentSubtree(c, seg.id)
        IdReply("segment", cmd.id)
    }

    private fun archiveTrack(c: Connection, cmd: ArchiveTrack): Res<Reply, StxError> = rail {
        val track = TrackRepo.getById(c, cmd.id) ?: raise(StxError.NotFound("track", cmd.id))
        if (track.archived) raise(StxError.Gone("track", cmd.id))
        archiveTrackCascade(c, track.id)
        IdReply("track", cmd.id)
    }

    private fun archiveWorkspace(c: Connection, cmd: ArchiveWorkspace): Res<Reply, StxError> = rail {
        val ws = WorkspaceRepo.getById(c, cmd.id) ?: raise(StxError.NotFound("workspace", cmd.id))
        if (ws.archived) raise(StxError.Gone("workspace", cmd.id))
        TrackRepo.allIdsOfWorkspace(c, ws.id).forEach { archiveTrackCascade(c, it) }
        WorkspaceRepo.archive(c, ws.id)
        IdReply("workspace", cmd.id)
    }

    private fun archiveStatus(c: Connection, cmd: ArchiveStatus): Res<Reply, StxError> = rail {
        val st = StatusRepo.getById(c, cmd.statusId) ?: raise(StxError.NotFound("status", cmd.statusId))
        if (st.archived) raise(StxError.Gone("status", cmd.statusId))
        ensure(st.workspaceId == cmd.workspaceId) { StxError.CrossWorkspace(st.id, cmd.workspaceId) }
        ensure(!st.isDefault) { StxError.Validation("set another default first") }
        ensure(!TaskRepo.existsLiveWithStatus(c, st.id)) { StxError.Validation("move those tasks first") } // #9
        TransitionRepo.archiveIncident(c, st.id)
        StatusRepo.archive(c, st.id)
        IdReply("status", st.id)
    }

    private fun archiveKind(c: Connection, cmd: ArchiveKind): Res<Reply, StxError> = rail {
        val k = KindRepo.getById(c, cmd.kindId) ?: raise(StxError.NotFound("kind", cmd.kindId))
        if (k.archived) raise(StxError.Gone("kind", cmd.kindId))
        ensure(k.workspaceId == cmd.workspaceId) { StxError.CrossWorkspace(k.id, cmd.workspaceId) }
        KindRepo.nullCascade(c, k.id) // #9
        KindRepo.archive(c, k.id)
        IdReply("kind", k.id)
    }

    // ── cascade helpers ──────────────────────────────────────────────────────────────────────

    /** #4: a task archive cascades its incident blocks/relates edges (same txn). */
    private fun archiveTaskCascade(c: Connection, taskId: Long) {
        TaskRepo.archive(c, taskId)
        BlocksRepo.archiveIncident(c, taskId)
        RelatesRepo.archiveIncident(c, taskId)
    }

    /** #6: archive a segment subtree — its tasks (with edges) then the segments themselves. Sweeps
     *  the FULL subtree (incl. any already-archived mid-tree node) so no live descendant is orphaned
     *  under an archived ancestor (C4b); archive() is a no-op on rows already archived. */
    private fun archiveSegmentSubtree(c: Connection, segmentId: Long) {
        val segmentIds = SegmentRepo.subtreeIds(c, segmentId)
        TaskRepo.liveTaskIdsInSegments(c, segmentIds).forEach { archiveTaskCascade(c, it) }
        segmentIds.forEach { SegmentRepo.archive(c, it) }
    }

    /** #6: archive a whole track — all its segments (flat via denormalized track_id, archived or
     *  not), their tasks + edges, then the track. Sweeping all segment ids (not just live ones)
     *  guarantees no live task survives under a pre-archived segment in the track (C4b). */
    private fun archiveTrackCascade(c: Connection, trackId: Long) {
        val segmentIds = SegmentRepo.allIdsOfTrack(c, trackId)
        TaskRepo.liveTaskIdsInSegments(c, segmentIds).forEach { archiveTaskCascade(c, it) }
        segmentIds.forEach { SegmentRepo.archive(c, it) }
        TrackRepo.archive(c, trackId)
    }

    companion object {
        /**
         * Run a write inside a transaction (brief §6): commit IFF the `Res` is Ok, else roll back
         * (a rejected invariant or a Defect must leave no partial write). The write-actor calls
         * this on its single connection; tests reuse it to apply a write synchronously.
         */
        fun <T> applyWrite(c: Connection, block: () -> Res<T, StxError>): Res<T, StxError> {
            c.autoCommit = false
            return try {
                val r = block()
                if (r.isOk) c.commit() else c.rollback()
                r
            } catch (t: Throwable) {
                runCatching { c.rollback() }
                throw t
            } finally {
                runCatching { c.autoCommit = true }
            }
        }
    }
}
