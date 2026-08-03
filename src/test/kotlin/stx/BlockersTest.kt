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
import kotlin.test.assertIs
import kotlin.test.assertTrue
import tech.codingzen.res.Res
import tech.codingzen.res.failureOrNull
import tech.codingzen.res.getOrThrow

/** `blockers` — the inverse read (decision D8). Mirrors [FrontierTest]'s scaffold on purpose. */
class BlockersTest {
    private lateinit var dir: java.io.File
    private lateinit var conn: java.sql.Connection
    private val svc = StxService()

    @BeforeTest fun setup() {
        dir = Files.createTempDirectory("stx-blockers").toFile()
        conn = Db("jdbc:sqlite:${dir.resolve("stx.db")}").also { it.init() }.connect()
    }
    @AfterTest fun teardown() { conn.close(); dir.deleteRecursively() }

    private fun w(cmd: Command): Res<Reply, StxError> = StxService.applyWrite(conn) { svc.dispatch(conn, cmd) }
    private fun r(cmd: Command): Res<Reply, StxError> = svc.dispatch(conn, cmd)
    private fun idOf(res: Res<Reply, StxError>): Long = when (val v = res.getOrThrow()) {
        is TaskDto -> v.id; is TrackDto -> v.id; is WorkspaceDto -> v.id
        is SegmentDto -> v.id; else -> error("no id")
    }

    private fun statusId(ws: Long, name: String) =
        (r(ListStatuses(ws)).getOrThrow() as StatusList).items.first { it.name == name }.id
    private fun task(id: Long) = (r(GetTask(id)).getOrThrow() as TaskDetail).task
    private fun blockers(id: Long, depth: Int = DEFAULT_BLOCKER_DEPTH) =
        (r(ListBlockers(id, depth)).getOrThrow() as BlockerList).items
    private fun blockerIds(id: Long, depth: Int = DEFAULT_BLOCKER_DEPTH) = blockers(id, depth).map { it.id }
    private fun frontier(ws: Long) = (r(Next(ws)).getOrThrow() as FrontierList).items.map { it.id }

    private fun move(id: Long, toName: String) {
        val t = task(id)
        w(MoveStatus(id, statusId(t.workspaceId, toName), t.version)).getOrThrow()
    }
    private fun complete(id: Long) { move(id, "Implementation"); move(id, "Done") }

    @Test fun `a chain reports every unfinished blocker, shallowest first`() {
        val ws = idOf(w(CreateWorkspace("ws")))
        val track = idOf(w(CreateTrack(ws, "main")))
        val t = (1..4).map { idOf(w(CreateTask(trackId = track, title = "T$it"))) }
        for (i in 0 until 3) w(AddBlocks(t[i], t[i + 1])).getOrThrow() // T1->T2->T3->T4

        assertEquals(listOf(t[2], t[1], t[0]), blockerIds(t[3]), "ordered by depth 1,2,3")
        assertEquals(listOf(1, 2, 3), blockers(t[3]).map { it.depth })
        assertTrue(blockerIds(t[0]).isEmpty(), "T1 has nothing in front of it")
    }

    /** The walk never passes *through* a finished blocker — a done task doesn't gate anything. */
    @Test fun `a completed blocker takes its own blockers out of the answer`() {
        val ws = idOf(w(CreateWorkspace("ws")))
        val track = idOf(w(CreateTrack(ws, "main")))
        val t = (1..3).map { idOf(w(CreateTask(trackId = track, title = "T$it"))) }
        w(AddBlocks(t[0], t[1])).getOrThrow() // T1 blocks T2
        w(AddBlocks(t[1], t[2])).getOrThrow() // T2 blocks T3

        assertEquals(listOf(t[1], t[0]), blockerIds(t[2]))
        complete(t[1]) // T2 done -> T3 is free, and T1 is no longer relevant to T3
        assertTrue(blockerIds(t[2]).isEmpty())
    }

    @Test fun `a diamond reports the shared blocker once, at its shallowest depth`() {
        val ws = idOf(w(CreateWorkspace("ws")))
        val track = idOf(w(CreateTrack(ws, "main")))
        val a = idOf(w(CreateTask(trackId = track, title = "A")))
        val b = idOf(w(CreateTask(trackId = track, title = "B")))
        val cc = idOf(w(CreateTask(trackId = track, title = "C")))
        val d = idOf(w(CreateTask(trackId = track, title = "D")))
        w(AddBlocks(a, b)).getOrThrow()
        w(AddBlocks(a, cc)).getOrThrow()
        w(AddBlocks(b, d)).getOrThrow()
        w(AddBlocks(cc, d)).getOrThrow()
        w(AddBlocks(a, d)).getOrThrow() // A also blocks D directly -> min depth 1, not 2

        val items = blockers(d)
        assertEquals(3, items.size, "A appears once despite three paths")
        assertEquals(1, items.single { it.id == a }.depth, "shallowest hop wins")
    }

    @Test fun `archived edges and archived blockers drop out`() {
        val ws = idOf(w(CreateWorkspace("ws")))
        val track = idOf(w(CreateTrack(ws, "main")))
        val a = idOf(w(CreateTask(trackId = track, title = "A")))
        val b = idOf(w(CreateTask(trackId = track, title = "B")))
        val target = idOf(w(CreateTask(trackId = track, title = "target")))
        w(AddBlocks(a, target)).getOrThrow()
        w(AddBlocks(b, target)).getOrThrow()
        assertEquals(setOf(a, b), blockerIds(target).toSet())

        w(RemoveBlocks(a, target)).getOrThrow() // edge archived
        assertEquals(listOf(b), blockerIds(target))
        w(ArchiveTask(b)).getOrThrow() // blocker archived -> its edges cascade (invariant #4)
        assertTrue(blockerIds(target).isEmpty())
    }

    /**
     * A finished task is not waiting on anything, even when its blocker is still open — the
     * question does not apply to it. Regression: the CTE only filters the *blockers'* status, so
     * without the target check in [StxService] a Done task reported a full blocker list and the
     * next ⟺ blockers identity broke at the terminal boundary.
     */
    @Test fun `a terminal or archived target has no blockers`() {
        val ws = idOf(w(CreateWorkspace("ws")))
        val track = idOf(w(CreateTrack(ws, "main")))
        val blocker = idOf(w(CreateTask(trackId = track, title = "blocker")))
        val target = idOf(w(CreateTask(trackId = track, title = "target")))
        val other = idOf(w(CreateTask(trackId = track, title = "other")))
        w(AddBlocks(blocker, target)).getOrThrow()
        w(AddBlocks(blocker, other)).getOrThrow()
        assertEquals(listOf(blocker), blockerIds(target), "open target is blocked")

        complete(target) // blocker is still open — the target is done anyway
        assertTrue(blockerIds(target).isEmpty(), "a done task is not waiting on anything")

        // archived target: empty on its own terms, not merely because cascade #4 killed the edges
        w(ArchiveTask(other)).getOrThrow()
        assertTrue(blockerIds(other).isEmpty())
    }

    /**
     * The CTE's base case is unconditional, so a cap below 1 would silently behave as 1 rather
     * than returning nothing. Rejected at the service boundary instead.
     */
    @Test fun `a depth below 1 is a validation error`() {
        val ws = idOf(w(CreateWorkspace("ws")))
        val track = idOf(w(CreateTrack(ws, "main")))
        val a = idOf(w(CreateTask(trackId = track, title = "a")))
        val b = idOf(w(CreateTask(trackId = track, title = "b")))
        w(AddBlocks(a, b)).getOrThrow()

        for (bad in listOf(0, -1, -64)) {
            assertIs<StxError.Validation>(r(ListBlockers(b, bad)).failureOrNull(), "depth=$bad")
        }
        assertEquals(listOf(a), blockerIds(b, depth = 1), "depth 1 is the smallest legal walk")
    }

    /** Depth 1 is exactly `show`'s blocked-by, filtered to live. */
    @Test fun `depth 1 equals the one-hop blocked-by view`() {
        val ws = idOf(w(CreateWorkspace("ws")))
        val track = idOf(w(CreateTrack(ws, "main")))
        val t = (1..3).map { idOf(w(CreateTask(trackId = track, title = "T$it"))) }
        w(AddBlocks(t[0], t[1])).getOrThrow()
        w(AddBlocks(t[1], t[2])).getOrThrow()

        assertEquals(listOf(t[1]), blockerIds(t[2], depth = 1))
        val blockedBy = (r(GetTask(t[2])).getOrThrow() as TaskDetail).blocksIn // already ids (D2)
        assertEquals(blockedBy.toSet(), blockerIds(t[2], depth = 1).toSet())
    }

    /** The cap truncates at every level, not only at 1. */
    @Test fun `the depth cap truncates mid-chain`() {
        val ws = idOf(w(CreateWorkspace("ws")))
        val track = idOf(w(CreateTrack(ws, "main")))
        val t = (1..5).map { idOf(w(CreateTask(trackId = track, title = "T$it"))) }
        for (i in 0 until 4) w(AddBlocks(t[i], t[i + 1])).getOrThrow() // T1→…→T5

        assertEquals(listOf(t[3]), blockerIds(t[4], depth = 1))
        assertEquals(listOf(t[3], t[2]), blockerIds(t[4], depth = 2))
        assertEquals(listOf(t[3], t[2], t[1]), blockerIds(t[4], depth = 3))
        assertEquals(listOf(t[3], t[2], t[1], t[0]), blockerIds(t[4], depth = 4))
        assertEquals(blockerIds(t[4], depth = 4), blockerIds(t[4]), "cap above the height is a no-op")
    }

    /**
     * MIN(depth) across two purely *recursive* paths. The earlier diamond has a direct edge, so
     * its minimum comes from the base case; here the shared blocker is only ever reached by
     * recursion, down a 2-hop and a 3-hop path.
     */
    @Test fun `the minimum hop count comes from the shorter recursive path`() {
        val ws = idOf(w(CreateWorkspace("ws")))
        val track = idOf(w(CreateTrack(ws, "main")))
        val root = idOf(w(CreateTask(trackId = track, title = "root")))
        val short = idOf(w(CreateTask(trackId = track, title = "short")))
        val longA = idOf(w(CreateTask(trackId = track, title = "longA")))
        val longB = idOf(w(CreateTask(trackId = track, title = "longB")))
        val target = idOf(w(CreateTask(trackId = track, title = "target")))
        w(AddBlocks(root, short)).getOrThrow() // root →2 hops→ target
        w(AddBlocks(short, target)).getOrThrow()
        w(AddBlocks(root, longA)).getOrThrow() // root →3 hops→ target
        w(AddBlocks(longA, longB)).getOrThrow()
        w(AddBlocks(longB, target)).getOrThrow()

        val items = blockers(target)
        assertEquals(4, items.size)
        assertEquals(2, items.single { it.id == root }.depth, "shorter path wins")
        // At cap 2 the short path has already reached root, while the long one has only got as
        // far as longA — the same node set, but root is in via the 2-hop route only.
        assertEquals(setOf(short, longB, root, longA), blockerIds(target, depth = 2).toSet())
        assertEquals(setOf(short, longB), blockerIds(target, depth = 1).toSet())
    }

    /**
     * The identity that makes `blockers` provably the inverse of `next` rather than merely some
     * traversal: a live non-terminal task is in the frontier **iff** nothing is blocking it.
     *
     * The graph deliberately exercises BOTH halves of the shared eligibility predicate — the
     * status half (terminal blocker, terminal target, in-progress) and the `live_task` half
     * (archived task, archived container) — plus a cross-track edge, because a fixture with
     * nothing archived would let a broken `live_task` join pass unnoticed. The oracle keys off
     * `archived` rather than assuming it, for the same reason.
     */
    @Test fun `next and blockers are exact inverses`() {
        val ws = idOf(w(CreateWorkspace("ws")))
        val main = idOf(w(CreateTrack(ws, "main")))
        val other = idOf(w(CreateTrack(ws, "other")))
        val t = (1..6).map { idOf(w(CreateTask(trackId = main, title = "T$it"))) }
        val crossBlocker = idOf(w(CreateTask(trackId = other, title = "cross")))

        w(AddBlocks(t[0], t[1])).getOrThrow()
        w(AddBlocks(t[1], t[2])).getOrThrow()
        w(AddBlocks(t[0], t[3])).getOrThrow()
        w(AddBlocks(t[4], t[3])).getOrThrow()
        w(AddBlocks(crossBlocker, t[5])).getOrThrow() // gated from another track

        // a task under a segment we then archive — cascade #6 should take it out of both reads
        val root = (r(ListSegments(main)).getOrThrow() as SegmentList).items.first { it.isRoot }.id
        val doomed = idOf(w(CreateSegment(main, "doomed", parentSegmentId = root)))
        val inDoomed = idOf(w(CreateTask(segmentId = doomed, title = "in-doomed")))
        val archivedTask = idOf(w(CreateTask(trackId = main, title = "archived")))

        complete(t[4])                // terminal blocker stops gating T4
        complete(t[2])                // terminal *target*: excluded from the identity's scope
        move(t[1], "Implementation")  // in-progress is workable and still blocking
        w(ArchiveTask(archivedTask)).getOrThrow()
        w(ArchiveSegment(doomed)).getOrThrow()

        val all = t + listOf(crossBlocker, inDoomed, archivedTask)
        val ready = frontier(ws).toSet()
        val termId = statusId(ws, "Done")

        var checked = 0
        for (id in all) {
            val row = task(id)
            val eligible = !row.archived && row.statusId != termId
            if (!eligible) {
                assertTrue(id !in ready, "task #$id is archived/terminal, so it cannot be in next")
                assertTrue(blockerIds(id).isEmpty(), "task #$id is archived/terminal, so it has no blockers")
                continue
            }
            checked++
            val blocked = blockerIds(id).isNotEmpty()
            assertEquals(!blocked, id in ready, "task #$id: in next = ${id in ready}, blocked = $blocked")
        }
        assertTrue(checked >= 5, "the identity was only checked on $checked tasks")
        assertTrue(inDoomed !in ready, "a task under an archived segment is invisible to both reads")
    }

    @Test fun `an unknown task is not found`() {
        assertIs<StxError.NotFound>(r(ListBlockers(99999)).failureOrNull())
    }
}
