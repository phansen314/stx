package stx

import stx.command.AddBlocks
import stx.command.AddRelatesTo
import stx.command.ArchiveBlocks
import stx.command.ArchiveTask
import stx.command.CreateSegment
import stx.command.CreateStatus
import stx.command.CreateTransition
import stx.command.MoveSegment
import stx.repo.BlocksRepo
import stx.repo.RelatesRepo
import stx.repo.SegmentRepo
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class InvariantsTest {
    private val h = Harness()

    @AfterTest fun cleanup() = h.close()

    private fun fixture(): Triple<Long, Long, Long> {
        val ws = h.seedWorkspace()
        val todo = h.seedStatus(ws, "todo")
        val track = h.seedTrack(ws, "auth")
        val seg = h.rootSegment(track)
        return Triple(ws, todo, seg)
    }

    @Test fun `self-block rejected`() {
        val (_, todo, seg) = fixture()
        val t = h.seedTask(seg, todo, "a")
        assertFailsWith<StxException.Validation> { h.exec<Blocks>(AddBlocks(t, t)) }
    }

    @Test fun `duplicate live blocks rejected but archive-then-recreate allowed`() {
        val (_, todo, seg) = fixture()
        val a = h.seedTask(seg, todo, "a")
        val b = h.seedTask(seg, todo, "b")
        val edge = h.exec<Blocks>(AddBlocks(a, b))
        assertFailsWith<StxException.Conflict> { h.exec<Blocks>(AddBlocks(a, b)) }
        h.exec<Blocks>(ArchiveBlocks(edge.id))
        // Same pair re-added after archiving the old one is allowed (partial unique index).
        h.exec<Blocks>(AddBlocks(a, b))
    }

    @Test fun `duplicate live status name rejected`() {
        val ws = h.seedWorkspace()
        h.seedStatus(ws, "todo")
        assertFailsWith<StxException.Conflict> { h.exec<Status>(CreateStatus(ws, "todo")) }
    }

    @Test fun `self-transition rejected`() {
        val ws = h.seedWorkspace()
        val s = h.seedStatus(ws, "todo")
        assertFailsWith<StxException.Validation> { h.exec<StatusTransition>(CreateTransition(ws, s, s)) }
    }

    @Test fun `bad reference rejected`() {
        val ws = h.seedWorkspace()
        // status in a workspace that doesn't exist
        assertFailsWith<StxException.NotFound> { h.exec<Status>(CreateStatus(999, "x")) }
    }

    @Test fun `blocks cycle rejected`() {
        val (_, todo, seg) = fixture()
        val a = h.seedTask(seg, todo, "a")
        val b = h.seedTask(seg, todo, "b")
        val c = h.seedTask(seg, todo, "c")
        h.exec<Blocks>(AddBlocks(a, b)) // a→b
        h.exec<Blocks>(AddBlocks(b, c)) // b→c
        assertFailsWith<StxException.Validation> { h.exec<Blocks>(AddBlocks(c, a)) } // c→a closes a cycle
    }

    @Test fun `segment cycle rejected`() {
        val ws = h.seedWorkspace()
        val track = h.seedTrack(ws, "t")
        val root = h.rootSegment(track)
        val parent = h.exec<Segment>(CreateSegment(track, "parent", parentSegmentId = root))
        val child = h.exec<Segment>(CreateSegment(track, "child", parentSegmentId = parent.id))
        // Moving parent under its own child must be rejected.
        assertFailsWith<StxException.Validation> { h.exec<Segment>(MoveSegment(parent.id, child.id)) }
    }

    @Test fun `each track has exactly one root segment`() {
        val ws = h.seedWorkspace()
        val track = h.seedTrack(ws, "t")
        val roots = SegmentRepo.listByTrack(h.conn, track, includeArchived = false).filter { it.isRoot }
        assertEquals(1, roots.size)
        // A direct second-root insert is blocked by the partial unique index.
        assertFailsWith<Exception> {
            SegmentRepo.insert(h.conn, ws, track, parentSegmentId = null, name = "dup-root", isRoot = true)
        }
    }

    @Test fun `archiving a task archives its incident edges`() {
        val (_, todo, seg) = fixture()
        val a = h.seedTask(seg, todo, "a")
        val b = h.seedTask(seg, todo, "b")
        val blk = h.exec<Blocks>(AddBlocks(a, b))
        val rel = h.exec<RelatesTo>(AddRelatesTo("relates", a, b))
        h.exec<Task>(ArchiveTask(a))
        assertTrue(BlocksRepo.get(h.conn, blk.id)!!.archived, "incident blocks should be archived")
        assertTrue(RelatesRepo.get(h.conn, rel.id)!!.archived, "incident relates_to should be archived")
    }
}
