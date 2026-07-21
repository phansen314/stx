package stx

import stx.command.*
import stx.dto.*
import stx.error.StxError
import stx.repo.Db
import stx.service.StxService
import java.nio.file.Files
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue
import tech.codingzen.res.Res
import tech.codingzen.res.failureOrNull
import tech.codingzen.res.getOrThrow

/** §8: daemon invariants, bootstrap, and optimistic-locking, exercised through the service
 *  (synchronously via [StxService.applyWrite] — the write-actor's transaction rule). */
class ServiceTest {
    private lateinit var dir: java.io.File
    private lateinit var conn: java.sql.Connection
    private val svc = StxService()

    @BeforeTest fun setup() {
        dir = Files.createTempDirectory("stx-svc").toFile()
        val db = Db("jdbc:sqlite:${dir.resolve("stx.db")}").also { it.init() }
        conn = db.connect()
    }
    @AfterTest fun teardown() { conn.close(); dir.deleteRecursively() }

    private fun w(cmd: Command): Res<Reply, StxError> = StxService.applyWrite(conn) { svc.dispatch(conn, cmd) }
    private fun r(cmd: Command): Res<Reply, StxError> = svc.dispatch(conn, cmd)

    private fun Res<Reply, StxError>.id(): Long = when (val v = getOrThrow()) {
        is WorkspaceDto -> v.id; is TrackDto -> v.id; is SegmentDto -> v.id; is StatusDto -> v.id
        is KindDto -> v.id; is TaskDto -> v.id; is TransitionDto -> v.id; is BlocksDto -> v.id
        is RelatesDto -> v.id; is IdReply -> v.id; else -> error("no id on $v")
    }

    private fun statuses(ws: Long): List<StatusDto> = (r(ListStatuses(ws)).getOrThrow() as StatusList).items
    private fun statusId(ws: Long, name: String): Long = statuses(ws).first { it.name == name }.id
    private fun transitions(ws: Long): List<TransitionDto> = (r(ListTransitions(ws)).getOrThrow() as TransitionList).items
    private fun frontierIds(ws: Long): List<Long> = (r(Next(ws)).getOrThrow() as FrontierList).items.map { it.id }

    /** A workspace with one track; returns (workspaceId, trackId). */
    private fun seedTrack(): Pair<Long, Long> {
        val ws = w(CreateWorkspace("ws")).id()
        val track = w(CreateTrack(ws, "auth")).id()
        return ws to track
    }

    // ── bootstrap & default status ───────────────────────────────────────────────────────────

    @Test fun `workspace bootstrap seeds statuses, transitions, one default, usable immediately`() {
        val ws = w(CreateWorkspace("ws")).id()
        val st = statuses(ws)
        assertEquals(setOf("Backlog", "Implementation", "Review", "Done"), st.map { it.name }.toSet())
        assertEquals(1, st.count { it.isDefault }, "exactly one default")
        assertTrue(st.first { it.name == "Backlog" }.isDefault)
        assertTrue(st.first { it.name == "Done" }.terminal)
        // A task created with no status lands on the live default (Backlog).
        val track = w(CreateTrack(ws, "t")).id()
        val task = w(CreateTask(trackId = track, title = "x")).getOrThrow() as TaskDto
        assertEquals(statusId(ws, "Backlog"), task.statusId)
    }

    @Test fun `set-default moves the flag and changes the create-time status - archiving default rejected`() {
        val (ws, track) = seedTrack()
        w(SetDefaultStatus(ws, statusId(ws, "Implementation"))).getOrThrow()
        assertEquals(1, statuses(ws).count { it.isDefault })
        assertEquals("Implementation", statuses(ws).first { it.isDefault }.name)
        val task = w(CreateTask(trackId = track, title = "x")).getOrThrow() as TaskDto
        assertEquals(statusId(ws, "Implementation"), task.statusId)
        // archiving the current default is rejected
        val res = w(ArchiveStatus(ws, statusId(ws, "Implementation")))
        assertIs<StxError.Validation>(res.failureOrNull())
    }

    @Test fun `terminal status cannot be set as default`() {
        val (ws, _) = seedTrack()
        // Done is terminal -> rejected; the default is left untouched (still Backlog).
        assertIs<StxError.Validation>(w(SetDefaultStatus(ws, statusId(ws, "Done"))).failureOrNull())
        assertEquals("Backlog", statuses(ws).first { it.isDefault }.name)
    }

    // ── workspace coherence (#7/#8) ──────────────────────────────────────────────────────────

    @Test fun `cross-workspace edge and cross-workspace status are rejected`() {
        val (ws1, track1) = seedTrack()
        val t1 = w(CreateTask(trackId = track1, title = "a")).id()
        val ws2 = w(CreateWorkspace("ws2")).id()
        val track2 = w(CreateTrack(ws2, "t2")).id()
        val t2 = w(CreateTask(trackId = track2, title = "b")).id()
        assertIs<StxError.CrossWorkspace>(w(AddBlocks(t1, t2)).failureOrNull())
        // create task pointing at another workspace's status
        val foreignStatus = statusId(ws2, "Backlog")
        assertIs<StxError.CrossWorkspace>(w(CreateTask(trackId = track1, title = "c", statusId = foreignStatus)).failureOrNull())
    }

    @Test fun `#8 coherence - foreign kind, transition endpoints, and segment parent are rejected`() {
        val (ws1, track1) = seedTrack()
        val ws2 = w(CreateWorkspace("ws2")).id()
        val track2 = w(CreateTrack(ws2, "t2")).id()

        // task create/edit pointing at another workspace's KIND
        val foreignKind = w(CreateKind(ws2, "impl")).id()
        assertIs<StxError.CrossWorkspace>(
            w(CreateTask(trackId = track1, title = "a", kindId = foreignKind)).failureOrNull(),
        )
        val local = w(CreateTask(trackId = track1, title = "b")).getOrThrow() as TaskDto
        assertIs<StxError.CrossWorkspace>(
            w(EditTask(local.id, local.version, kindId = foreignKind)).failureOrNull(),
        )

        // transition with an endpoint in another workspace
        assertIs<StxError.CrossWorkspace>(
            w(CreateTransition(ws1, statusId(ws1, "Backlog"), statusId(ws2, "Backlog"))).failureOrNull(),
        )

        // segment whose parent belongs to another track/workspace
        val foreignSeg = w(CreateSegment(track2, "s2")).id()
        assertIs<StxError.CrossWorkspace>(
            w(CreateSegment(track1, "s1", parentSegmentId = foreignSeg)).failureOrNull(),
        )
    }

    @Test fun `#8 task workspace_id is derived from its segment, never drifts`() {
        val (_, _) = seedTrack()
        val ws2 = w(CreateWorkspace("ws2")).id()
        val track2 = w(CreateTrack(ws2, "t2")).id()
        val seg2 = w(CreateSegment(track2, "s2")).id()
        // Filing a task under ws2's segment lands it in ws2 (derived), not the caller's default.
        val t = w(CreateTask(segmentId = seg2, title = "x")).getOrThrow() as TaskDto
        assertEquals(ws2, t.workspaceId)
        assertEquals(statusId(ws2, "Backlog"), t.statusId) // default resolved in the derived ws
    }

    // ── metadata_json validity (schema CHECK + daemon gate) ──────────────────────────────────

    @Test fun `metadata_json must be a JSON object`() {
        val (_, track) = seedTrack()
        assertIs<StxError.Validation>(w(CreateTask(trackId = track, title = "a", metadataJson = "not json")).failureOrNull())
        assertIs<StxError.Validation>(w(CreateTask(trackId = track, title = "b", metadataJson = "[1,2]")).failureOrNull())
        assertIs<StxError.Validation>(w(CreateWorkspace("x", metadataJson = "42")).failureOrNull())
        // an object round-trips; then a bad edit is rejected and a good edit sticks.
        val t = w(CreateTask(trackId = track, title = "c", metadataJson = """{"k":"v"}""")).getOrThrow() as TaskDto
        assertEquals("""{"k":"v"}""", t.metadataJson)
        assertIs<StxError.Validation>(w(EditTask(t.id, t.version, metadataJson = "nope")).failureOrNull())
        val t2 = w(EditTask(t.id, t.version, metadataJson = """{"a":1}""")).getOrThrow() as TaskDto
        assertEquals("""{"a":1}""", t2.metadataJson)
    }

    @Test fun `blank names and titles are rejected`() {
        val (ws, track) = seedTrack()
        assertIs<StxError.Validation>(w(CreateWorkspace("   ")).failureOrNull())
        assertIs<StxError.Validation>(w(CreateTrack(ws, "")).failureOrNull())
        assertIs<StxError.Validation>(w(CreateStatus(ws, "\t")).failureOrNull())
        assertIs<StxError.Validation>(w(CreateKind(ws, "")).failureOrNull())
        assertIs<StxError.Validation>(w(CreateSegment(track, "  ")).failureOrNull())
        assertIs<StxError.Validation>(w(CreateTask(trackId = track, title = " ")).failureOrNull())
        // edit path: a blank title is rejected too (a non-blank one still applies)
        val t = w(CreateTask(trackId = track, title = "real")).getOrThrow() as TaskDto
        assertIs<StxError.Validation>(w(EditTask(t.id, t.version, title = " ")).failureOrNull())
    }

    // ── blocks DAG (#1) ──────────────────────────────────────────────────────────────────────

    @Test fun `blocks cycle and self-block are rejected - duplicate live edge rejected`() {
        val (_, track) = seedTrack()
        val a = w(CreateTask(trackId = track, title = "a")).id()
        val b = w(CreateTask(trackId = track, title = "b")).id()
        val c = w(CreateTask(trackId = track, title = "c")).id()
        w(AddBlocks(a, b)).getOrThrow()
        w(AddBlocks(b, c)).getOrThrow()
        assertIs<StxError.CycleRejected>(w(AddBlocks(c, a)).failureOrNull()) // c->a closes a->b->c->a
        assertIs<StxError.CycleRejected>(w(AddBlocks(a, a)).failureOrNull()) // self
        assertIs<StxError.Duplicate>(w(AddBlocks(a, b)).failureOrNull())     // duplicate live edge
    }

    // ── archive cascade: edges (#4) & containers (#6) ────────────────────────────────────────

    @Test fun `archiving a blocker auto-unblocks its dependents`() {
        val (ws, track) = seedTrack()
        val a = w(CreateTask(trackId = track, title = "a")).id()
        val b = w(CreateTask(trackId = track, title = "b")).id()
        w(AddBlocks(a, b)).getOrThrow()
        assertEquals(listOf(a), frontierIds(ws)) // b blocked by a
        w(ArchiveTask(a)).getOrThrow()
        assertEquals(listOf(b), frontierIds(ws)) // edge archived (#4) -> b unblocked, a gone
    }

    @Test fun `removeBlocks archives the single edge and un-gates the target - NotFound when absent`() {
        val (ws, track) = seedTrack()
        val a = w(CreateTask(trackId = track, title = "a")).id()
        val b = w(CreateTask(trackId = track, title = "b")).id()
        w(AddBlocks(a, b)).getOrThrow()
        assertEquals(listOf(a), frontierIds(ws))         // b blocked by a
        w(RemoveBlocks(a, b)).getOrThrow()
        assertEquals(listOf(a, b), frontierIds(ws))      // edge gone -> b unblocked, both live tasks stay
        assertIs<StxError.NotFound>(w(RemoveBlocks(a, b)).failureOrNull()) // no live edge left
        // re-adding is allowed now that the prior row is archived (unique-live index freed)
        w(AddBlocks(a, b)).getOrThrow()
    }

    @Test fun `removeRelates is keyed on kind - wrong kind is NotFound`() {
        val (_, track) = seedTrack()
        val a = w(CreateTask(trackId = track, title = "a")).id()
        val b = w(CreateTask(trackId = track, title = "b")).id()
        w(AddRelates("mentions", a, b)).getOrThrow()
        assertIs<StxError.NotFound>(w(RemoveRelates("spawns", a, b)).failureOrNull()) // kind mismatch
        w(RemoveRelates("mentions", a, b)).getOrThrow()
        w(AddRelates("mentions", a, b)).getOrThrow()     // re-add allowed after archive
    }

    @Test fun `archiving a track cascades its segments and tasks - none remain in next`() {
        val (ws, track) = seedTrack()
        w(CreateTask(trackId = track, title = "a")).id()
        w(CreateTask(trackId = track, title = "b")).id()
        assertEquals(2, frontierIds(ws).size)
        w(ArchiveTrack(track)).getOrThrow()
        assertTrue(frontierIds(ws).isEmpty())
        assertTrue((r(ListTasks(track)).getOrThrow() as TaskList).items.isEmpty())
    }

    @Test fun `archiving a non-root segment cascades its subtree - root-segment archive rejected`() {
        val (ws, track) = seedTrack()
        val parent = w(CreateSegment(track, "epic")).id()
        val child = w(CreateSegment(track, "story", parentSegmentId = parent)).id()
        w(CreateTask(segmentId = child, title = "deep")).id()
        assertEquals(1, frontierIds(ws).size)
        w(ArchiveSegment(parent)).getOrThrow()
        assertTrue(frontierIds(ws).isEmpty(), "subtree task should be gone")
        // the track's root segment cannot be archived directly
        val rootSeg = (r(ListSegments(track)).getOrThrow() as SegmentList).items.first { it.isRoot }
        assertIs<StxError.Validation>(w(ArchiveSegment(rootSeg.id)).failureOrNull())
    }

    // ── status/kind archival (#9) ────────────────────────────────────────────────────────────

    @Test fun `status archive rejected while referenced, allowed after move, cascades transitions`() {
        val (ws, track) = seedTrack()
        val backlog = statusId(ws, "Backlog")
        w(CreateTask(trackId = track, title = "x")).id() // on Backlog (default)
        w(SetDefaultStatus(ws, statusId(ws, "Implementation"))).getOrThrow() // free 'Backlog' from default
        // still a live task on 'Backlog' -> archive rejected
        assertIs<StxError.Validation>(w(ArchiveStatus(ws, backlog)).failureOrNull())
        // Backlog is incident to seeded transitions (Backlog->Implementation, Implementation->Backlog)
        // while still live.
        assertTrue(transitions(ws).any { it.fromStatusId == backlog || it.toStatusId == backlog })
        // move the task off 'Backlog', then archive succeeds
        val taskId = (r(ListTasks(track)).getOrThrow() as TaskList).items.first().id
        val v = (r(GetTask(taskId)).getOrThrow() as TaskDetail).task.version
        w(MoveStatus(taskId, statusId(ws, "Implementation"), v)).getOrThrow()
        w(ArchiveStatus(ws, backlog)).getOrThrow()
        assertFalse(statuses(ws).any { it.name == "Backlog" }, "Backlog archived")
        // #9: every live transition incident to the archived status is gone (the actual cascade,
        // not merely "some transitions remain").
        assertFalse(
            transitions(ws).any { it.fromStatusId == backlog || it.toStatusId == backlog },
            "incident transitions cascaded to archived",
        )
        // untouched transitions survive (Implementation->Review still lists).
        assertTrue(transitions(ws).any {
            it.fromStatusId == statusId(ws, "Implementation") && it.toStatusId == statusId(ws, "Review")
        })
    }

    @Test fun `kind archive null-cascades referencing tasks`() {
        val (ws, track) = seedTrack()
        val kind = w(CreateKind(ws, "impl")).id()
        val taskId = (w(CreateTask(trackId = track, title = "x", kindId = kind)).getOrThrow() as TaskDto).id
        w(ArchiveKind(ws, kind)).getOrThrow()
        val task = (r(GetTask(taskId)).getOrThrow() as TaskDetail).task
        assertNull(task.kindId, "kind nulled on archive")
    }

    @Test fun `editTask clearKind succeeds even when the passed kindId is now archived`() {
        val (ws, track) = seedTrack()
        val kind = w(CreateKind(ws, "impl")).id()
        val taskId = (w(CreateTask(trackId = track, title = "x", kindId = kind)).getOrThrow() as TaskDto).id
        w(ArchiveKind(ws, kind)).getOrThrow() // kind archived; clearKind must not re-validate it
        val v = (r(GetTask(taskId)).getOrThrow() as TaskDetail).task.version
        w(EditTask(taskId, expectedVersion = v, clearKind = true, kindId = kind)).getOrThrow()
        assertNull((r(GetTask(taskId)).getOrThrow() as TaskDetail).task.kindId)
    }

    // ── optimistic locking (§6) ──────────────────────────────────────────────────────────────

    @Test fun `stale edit is a VersionConflict - fresh edit succeeds`() {
        val (_, track) = seedTrack()
        val taskId = (w(CreateTask(trackId = track, title = "x")).getOrThrow() as TaskDto).id
        val v0 = (r(GetTask(taskId)).getOrThrow() as TaskDetail).task.version
        w(EditTask(taskId, expectedVersion = v0, title = "first")).getOrThrow() // bumps to v0+1
        val conflict = w(EditTask(taskId, expectedVersion = v0, title = "second")) // stale
        val f = conflict.failureOrNull()
        assertIs<StxError.VersionConflict>(f)
        assertEquals(v0, f.expected)
        assertEquals(v0 + 1, f.actual)
    }

    @Test fun `two racing status moves - first wins, second conflicts`() {
        val (ws, track) = seedTrack()
        val taskId = (w(CreateTask(trackId = track, title = "x")).getOrThrow() as TaskDto).id
        val v0 = (r(GetTask(taskId)).getOrThrow() as TaskDetail).task.version
        val inProg = statusId(ws, "Implementation")
        w(MoveStatus(taskId, inProg, v0)).getOrThrow()
        assertIs<StxError.VersionConflict>(w(MoveStatus(taskId, inProg, v0)).failureOrNull())
    }

    @Test fun `illegal status move rejected`() {
        val (ws, track) = seedTrack()
        val taskId = (w(CreateTask(trackId = track, title = "x")).getOrThrow() as TaskDto).id
        val v0 = (r(GetTask(taskId)).getOrThrow() as TaskDetail).task.version
        // Backlog -> Review is not a seeded transition (and Review is non-terminal, so no bypass).
        // (Backlog -> Done would now be legal via the terminal escape hatch.)
        assertIs<StxError.IllegalTransition>(w(MoveStatus(taskId, statusId(ws, "Review"), v0)).failureOrNull())
    }

    @Test fun `moving to a terminal status is always legal, even with no direct edge`() {
        val (ws, track) = seedTrack()
        val taskId = (w(CreateTask(trackId = track, title = "x")).getOrThrow() as TaskDto).id // on Backlog
        val v0 = (r(GetTask(taskId)).getOrThrow() as TaskDetail).task.version
        // Backlog -> Done has no seeded edge, but Done is terminal, so the move is allowed (the
        // `stx done` escape hatch). A non-terminal no-edge move would still be rejected (test above).
        val moved = w(MoveStatus(taskId, statusId(ws, "Done"), v0)).getOrThrow() as TaskDto
        assertEquals(statusId(ws, "Done"), moved.statusId)
    }

    // ── status naming (#66: case-insensitive dedupe) ─────────────────────────────────────────────

    @Test fun `creating a status whose name case-insensitively duplicates a live one is rejected`() {
        val (ws, _) = seedTrack()
        // 'Backlog' is seeded live; 'backlog' / '  BACKLOG ' must be refused as duplicates.
        assertIs<StxError.Duplicate>(w(CreateStatus(ws, "backlog", kanbanOrder = 9, terminal = false)).failureOrNull())
        assertIs<StxError.Duplicate>(w(CreateStatus(ws, "  BACKLOG ", kanbanOrder = 9, terminal = false)).failureOrNull())
        // a genuinely new name still succeeds
        w(CreateStatus(ws, "Blocked", kanbanOrder = 9, terminal = false)).getOrThrow()
    }

    @Test fun `creating a kind whose name case-insensitively duplicates a live one is rejected`() {
        val (ws, _) = seedTrack()
        w(CreateKind(ws, "impl")).getOrThrow()
        // 'Impl' / '  IMPL ' must be refused so `next --kind` can't fragment on casing/whitespace.
        assertIs<StxError.Duplicate>(w(CreateKind(ws, "Impl")).failureOrNull())
        assertIs<StxError.Duplicate>(w(CreateKind(ws, "  IMPL ")).failureOrNull())
        // a genuinely new name still succeeds
        w(CreateKind(ws, "docs")).getOrThrow()
    }

    // ── segment default parent (#68) ─────────────────────────────────────────────────────────────

    @Test fun `segment created without a parent nests under the track root`() {
        val (_, track) = seedTrack()
        val seg = w(CreateSegment(track, "phase-1")).getOrThrow() as SegmentDto
        assertFalse(seg.isRoot)
        val root = (r(ListSegments(track)).getOrThrow() as SegmentList).items.first { it.isRoot }
        assertEquals(root.id, seg.parentSegmentId, "no-parent segment defaults to the root, not NULL")
    }
}
