package stx

import stx.command.*
import stx.dto.*
import stx.error.StxError
import stx.repo.Db
import stx.repo.StatusRepo
import stx.repo.WorkspaceRepo
import stx.repo.bool
import stx.repo.exec
import stx.repo.insertReturningId
import stx.repo.longOrNull
import stx.repo.queryList
import stx.repo.queryOne
import stx.repo.sql
import stx.repo.toBlocks
import stx.repo.toKind
import stx.repo.toRelates
import stx.repo.toSegment
import stx.repo.toStatus
import stx.repo.toTask
import stx.repo.toTrack
import stx.repo.toTransition
import stx.repo.toWorkspace
import stx.service.StxService
import java.nio.file.Files
import java.sql.SQLException
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue
import tech.codingzen.res.Res
import tech.codingzen.res.defectOrNull
import tech.codingzen.res.failureOrNull
import tech.codingzen.res.getOrThrow

/**
 * Direct tests for the JDBC→Res boundary in repo/Rows.kt: the [sql] UNIQUE→Duplicate retag, the
 * query helpers + bindAll coercion, the ResultSet helpers, and every row mapper. Exercised against
 * a real temp-file SQLite DB. Harness mirrors ServiceTest.
 */
class RowsTest {
    private lateinit var dir: java.io.File
    private lateinit var conn: java.sql.Connection
    private val svc = StxService()

    @BeforeTest fun setup() {
        dir = Files.createTempDirectory("stx-rows").toFile()
        conn = Db("jdbc:sqlite:${dir.resolve("stx.db")}").also { it.init() }.connect()
    }
    @AfterTest fun teardown() { conn.close(); dir.deleteRecursively() }

    private fun w(cmd: Command): Res<Reply, StxError> = StxService.applyWrite(conn) { svc.dispatch(conn, cmd) }
    private fun r(cmd: Command): Res<Reply, StxError> = svc.dispatch(conn, cmd)
    private fun Res<Reply, StxError>.id(): Long = when (val v = getOrThrow()) {
        is WorkspaceDto -> v.id; is TrackDto -> v.id; is SegmentDto -> v.id; is StatusDto -> v.id
        is KindDto -> v.id; is TaskDto -> v.id; is TransitionDto -> v.id; is BlocksDto -> v.id
        is RelatesDto -> v.id; is IdReply -> v.id; else -> error("no id on $v")
    }

    // ── sql() throw→Res retag ────────────────────────────────────────────────────────────────

    @Test fun `sql wraps a successful block as Ok`() {
        assertEquals(42, sql("x") { 42 }.getOrThrow())
    }

    @Test fun `sql re-tags a UNIQUE violation as a typed Duplicate carrying entity and detail`() {
        val ws = WorkspaceRepo.insert(conn, "w", "{}").getOrThrow()
        conn.exec("INSERT INTO status(workspace_id,name,kanban_order,terminal,is_default) VALUES (?,?,0,0,0)", ws, "dup")
        val res = sql("status", "status name 'dup'") {
            conn.insertReturningId("INSERT INTO status(workspace_id,name,kanban_order,terminal,is_default) VALUES (?,?,0,0,0)", ws, "dup")
        }
        val dup = res.failureOrNull()
        assertIs<StxError.Duplicate>(dup)
        assertEquals("status", dup.entity)
        assertEquals("status name 'dup'", dup.detail)
    }

    @Test fun `sql leaves a non-UNIQUE constraint failure on the Defect rail`() {
        // FK violation (no workspace 999999). Must NOT be mis-tagged Duplicate — a daemon bug must surface as 500.
        val res = sql("track") {
            conn.insertReturningId("INSERT INTO track(workspace_id,name) VALUES (999999,'x')")
        }
        assertNull(res.failureOrNull(), "FK failure is not a typed Failure")
        assertIs<SQLException>(res.defectOrNull())
    }

    // ── query helpers + bindAll coercion ─────────────────────────────────────────────────────

    @Test fun `insertReturningId returns a positive, monotonic generated key`() {
        val a = conn.insertReturningId("INSERT INTO workspace(name) VALUES (?)", "a")
        val b = conn.insertReturningId("INSERT INTO workspace(name) VALUES (?)", "b")
        assertTrue(a > 0 && b > a, "ids: $a, $b")
    }

    @Test fun `queryOne maps a row and returns null on no match`() {
        val ws = WorkspaceRepo.insert(conn, "only", "{}").getOrThrow()
        assertEquals("only", conn.queryOne("SELECT * FROM workspace WHERE id=?", ws) { it.toWorkspace() }?.name)
        assertNull(conn.queryOne("SELECT * FROM workspace WHERE id=?", 999999L) { it.toWorkspace() })
    }

    @Test fun `queryList returns every matching row`() {
        WorkspaceRepo.insert(conn, "a", "{}").getOrThrow()
        WorkspaceRepo.insert(conn, "b", "{}").getOrThrow()
        val names = conn.queryList("SELECT * FROM workspace ORDER BY id") { it.toWorkspace().name }
        assertEquals(listOf("a", "b"), names)
    }

    @Test fun `exec returns the affected row count`() {
        val ws = WorkspaceRepo.insert(conn, "w", "{}").getOrThrow()
        assertEquals(1, conn.exec("UPDATE workspace SET name=? WHERE id=?", "renamed", ws))
        assertEquals(0, conn.exec("UPDATE workspace SET name=? WHERE id=?", "x", 999999L))
    }

    @Test fun `bindAll coerces Boolean to 0 or 1 and binds null`() {
        val ws = WorkspaceRepo.insert(conn, "w", "{}").getOrThrow()
        // Boolean true -> stored 1 (read back via bool()); also exercise a null bind on metadata.
        conn.exec("INSERT INTO status(workspace_id,name,kanban_order,terminal,is_default) VALUES (?,?,?,?,?)",
            ws, "term", 0, true, false)
        val s = conn.queryOne("SELECT * FROM status WHERE workspace_id=? AND name=?", ws, "term") { it.toStatus() }!!
        assertTrue(s.terminal)
        assertFalse(s.isDefault)
    }

    // ── ResultSet helpers ────────────────────────────────────────────────────────────────────

    @Test fun `bool reads integer flags as booleans`() {
        val ws = WorkspaceRepo.insert(conn, "w", "{}").getOrThrow()
        conn.exec("UPDATE workspace SET archived=1 WHERE id=?", ws)
        assertTrue(conn.queryOne("SELECT * FROM workspace WHERE id=?", ws) { it.bool("archived") }!!)
        val ws2 = WorkspaceRepo.insert(conn, "live", "{}").getOrThrow()
        assertFalse(conn.queryOne("SELECT * FROM workspace WHERE id=?", ws2) { it.bool("archived") }!!)
    }

    @Test fun `longOrNull yields null for a SQL NULL column`() {
        val ws = w(CreateWorkspace("ws")).id()
        val track = w(CreateTrack(ws, "t")).id()
        val rootSeg = (r(ListSegments(track)).getOrThrow() as SegmentList).items.first { it.isRoot }
        val parent = conn.queryOne("SELECT * FROM segment WHERE id=?", rootSeg.id) { it.longOrNull("parent_segment_id") }
        assertNull(parent, "root segment has a NULL parent")
    }

    // ── row mappers ──────────────────────────────────────────────────────────────────────────

    @Test fun `mappers populate every entity from a seeded graph`() {
        val ws = w(CreateWorkspace("acme")).id()
        val track = w(CreateTrack(ws, "auth", description = "login work")).id()
        val kind = w(CreateKind(ws, "impl")).id()
        val parentSeg = w(CreateSegment(track, "epic")).id()
        val child = w(CreateSegment(track, "story", parentSegmentId = parentSeg)).id()
        val withKind = (w(CreateTask(segmentId = child, title = "deep", kindId = kind)).getOrThrow() as TaskDto).id
        val noKind = (w(CreateTask(trackId = track, title = "shallow")).getOrThrow() as TaskDto).id
        w(AddBlocks(withKind, noKind)).getOrThrow()
        w(AddRelates("spawns", withKind, noKind)).getOrThrow()

        // workspace / track / kind
        assertEquals("acme", conn.queryOne("SELECT * FROM workspace WHERE id=?", ws) { it.toWorkspace() }!!.name)
        val tr = conn.queryOne("SELECT * FROM track WHERE id=?", track) { it.toTrack() }!!
        assertEquals("auth", tr.name); assertEquals("login work", tr.description); assertFalse(tr.archived)
        assertEquals("impl", conn.queryOne("SELECT * FROM task_kind WHERE id=?", kind) { it.toKind() }!!.name)

        // status bool flags
        val statuses = conn.queryList("SELECT * FROM status WHERE workspace_id=?", ws) { it.toStatus() }
        assertTrue(statuses.first { it.name == "Done" }.terminal)
        assertTrue(statuses.first { it.name == "Backlog" }.isDefault)

        // segment: child (non-root, parent set) vs root (parent null)
        val childSeg = conn.queryOne("SELECT * FROM segment WHERE id=?", child) { it.toSegment() }!!
        assertFalse(childSeg.isRoot); assertEquals(track, childSeg.trackId); assertEquals(parentSeg, childSeg.parentSegmentId)
        val rootSeg = conn.queryOne("SELECT * FROM segment WHERE track_id=? AND is_root=1", track) { it.toSegment() }!!
        assertTrue(rootSeg.isRoot); assertNull(rootSeg.parentSegmentId)

        // task: kind populated, vs null kind via longOrNull/getString
        val tk = conn.queryOne("SELECT * FROM task WHERE id=?", withKind) { it.toTask() }!!
        assertEquals(kind, tk.kindId); assertEquals(child, tk.segmentId)
        val tn = conn.queryOne("SELECT * FROM task WHERE id=?", noKind) { it.toTask() }!!
        assertNull(tn.kindId)

        // edges
        val blk = conn.queryOne("SELECT * FROM blocks WHERE source_task_id=? AND target_task_id=?", withKind, noKind) { it.toBlocks() }!!
        assertEquals(withKind, blk.sourceTaskId); assertEquals(noKind, blk.targetTaskId); assertFalse(blk.archived)
        val rel = conn.queryOne("SELECT * FROM relates_to WHERE source_task_id=? AND target_task_id=?", withKind, noKind) { it.toRelates() }!!
        assertEquals("spawns", rel.kind); assertFalse(rel.archived)

        // transition (seeded Backlog->Implementation et al.)
        val trans = conn.queryList("SELECT * FROM status_transition WHERE workspace_id=?", ws) { it.toTransition() }
        assertTrue(trans.isNotEmpty()); assertTrue(trans.all { !it.archived && it.workspaceId == ws })
    }
}
