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
import kotlin.test.assertTrue
import tech.codingzen.res.Res
import tech.codingzen.res.getOrThrow

/** §8: the `next` lifecycle/rework behaviour — the key behavioural test (brief §8). */
class FrontierTest {
    private lateinit var dir: java.io.File
    private lateinit var conn: java.sql.Connection
    private val svc = StxService()

    @BeforeTest fun setup() {
        dir = Files.createTempDirectory("stx-frontier").toFile()
        conn = Db("jdbc:sqlite:${dir.resolve("stx.db")}").also { it.init() }.connect()
    }
    @AfterTest fun teardown() { conn.close(); dir.deleteRecursively() }

    private fun w(cmd: Command): Res<Reply, StxError> = StxService.applyWrite(conn) { svc.dispatch(conn, cmd) }
    private fun r(cmd: Command): Res<Reply, StxError> = svc.dispatch(conn, cmd)
    private fun idOf(res: Res<Reply, StxError>): Long = when (val v = res.getOrThrow()) {
        is TaskDto -> v.id; is TrackDto -> v.id; is WorkspaceDto -> v.id; is KindDto -> v.id; else -> error("no id")
    }

    private fun statusId(ws: Long, name: String) =
        (r(ListStatuses(ws)).getOrThrow() as StatusList).items.first { it.name == name }.id
    private fun task(id: Long) = (r(GetTask(id)).getOrThrow() as TaskDetail).task
    private fun frontier(ws: Long, track: Long? = null, kind: Long? = null) =
        (r(Next(ws, trackId = track, kindId = kind)).getOrThrow() as FrontierList).items.map { it.id }

    /** Move a task one hop by name, using its current version. */
    private fun move(id: Long, toName: String) {
        val t = task(id)
        w(MoveStatus(id, statusId(t.workspaceId, toName), t.version)).getOrThrow()
    }
    /** Drive a task to terminal: Backlog -> Implementation -> Done (Impl->Done via terminal bypass). */
    private fun complete(id: Long) { move(id, "Implementation"); move(id, "Done") }

    @Test fun `frontier walks a blocks chain and reopens on rework`() {
        val ws = idOf(w(CreateWorkspace("ws")))
        val track = idOf(w(CreateTrack(ws, "main")))
        val t = (1..5).map { idOf(w(CreateTask(trackId = track, title = "T$it"))) }
        // chain T1->T2->T3->T4->T5
        for (i in 0 until 4) w(AddBlocks(t[i], t[i + 1])).getOrThrow()

        assertEquals(listOf(t[0]), frontier(ws)) // only T1 ready
        complete(t[0])
        assertEquals(listOf(t[1]), frontier(ws)) // T2 unblocked, T1 terminal/out

        // a non-terminal in-progress status stays in the frontier
        move(t[1], "Implementation")
        assertEquals(listOf(t[1]), frontier(ws))
        move(t[1], "Done")
        assertEquals(listOf(t[2]), frontier(ws))

        // rework: reopen T1 (Done -> Review). It does not block anyone, so frontier = {T1, T3}.
        move(t[0], "Review")
        assertEquals(setOf(t[0], t[2]), frontier(ws).toSet())

        // rework a blocker: reopen T2 -> it blocks T3 again, so T3 drops out.
        move(t[0], "Done") // tidy reopened T1 back to Done (it is currently in Review)
        move(t[2], "Implementation") // T3 in progress
        // reopen T2 (currently Done) back to Review; recompute-on-read must re-gate T3
        move(t[1], "Review")
        val f = frontier(ws)
        assertTrue(t[1] in f, "reopened blocker T2 is workable")
        assertTrue(t[2] !in f, "T3 re-blocked by reopened T2")
    }

    @Test fun `track scope returns only that track but respects cross-track blockers`() {
        val ws = idOf(w(CreateWorkspace("ws")))
        val auth = idOf(w(CreateTrack(ws, "auth")))
        val billing = idOf(w(CreateTrack(ws, "billing")))
        val a = idOf(w(CreateTask(trackId = auth, title = "auth-task")))
        val b = idOf(w(CreateTask(trackId = billing, title = "billing-task")))
        w(AddBlocks(a, b)).getOrThrow() // cross-track: auth blocks billing

        assertEquals(listOf(a), frontier(ws, track = auth))
        assertTrue(frontier(ws, track = billing).isEmpty(), "b gated by cross-track blocker a")
        complete(a)
        assertEquals(listOf(b), frontier(ws, track = billing)) // now unblocked
    }

    @Test fun `kind filter restricts and excludes untyped tasks`() {
        val ws = idOf(w(CreateWorkspace("ws")))
        val track = idOf(w(CreateTrack(ws, "main")))
        val impl = idOf(w(CreateKind(ws, "impl")))
        val typed = idOf(w(CreateTask(trackId = track, title = "typed", kindId = impl)))
        val untyped = idOf(w(CreateTask(trackId = track, title = "untyped")))

        assertEquals(setOf(typed, untyped), frontier(ws).toSet())
        assertEquals(listOf(typed), frontier(ws, kind = impl)) // untyped excluded when --kind given
    }
}
