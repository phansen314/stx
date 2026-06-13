package stx

import stx.command.AddBlocks
import stx.command.MoveTask
import stx.service.Frontier
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class FrontierTest {
    private val h = Harness()
    private val frontier = Frontier()

    @AfterTest fun cleanup() = h.close()

    /** A workspace with todo/doing/done(terminal) statuses and a permissive transition mesh. */
    private inner class World(name: String) {
        val ws = h.seedWorkspace(name)
        val todo = h.seedStatus(ws, "todo", terminal = false, order = 0)
        val doing = h.seedStatus(ws, "doing", terminal = false, order = 1)
        val done = h.seedStatus(ws, "done", terminal = true, order = 2)

        init {
            for ((from, to) in listOf(
                todo to doing, doing to done, todo to done,
                done to todo, done to doing, doing to todo,
            )) h.seedTransition(ws, from, to)
        }

        fun move(task: Long, to: Long) = h.exec<Task>(MoveTask(task, to))
        fun ids(trackId: Long? = null, kind: String? = null) =
            frontier.next(h.conn, ws, trackId = trackId, kind = kind).map { it.id }.toSet()
    }

    @Test fun `frontier walks forward as the blocks chain completes`() {
        val w = World("chain")
        val track = h.seedTrack(w.ws, "t")
        val seg = h.rootSegment(track)
        val t = (1..5).map { h.seedTask(seg, w.todo, "T$it") }
        for (i in 0 until 4) h.exec<Blocks>(AddBlocks(t[i], t[i + 1])) // T1→T2→…→T5

        assertEquals(setOf(t[0]), w.ids(), "only the chain head is workable")

        w.move(t[0], w.done)
        assertEquals(setOf(t[1]), w.ids(), "completing T1 surfaces T2")

        // In-progress stays in the frontier (only terminal/blocked are excluded).
        w.move(t[1], w.doing)
        assertEquals(setOf(t[1]), w.ids(), "an in-progress task remains workable")

        // Rework: reopening T1 must drop its dependent T2 back out (recompute-on-read).
        w.move(t[0], w.todo)
        val after = w.ids()
        assertTrue(t[0] in after, "reopened T1 is workable again")
        assertFalse(t[1] in after, "T2 is blocked again once T1 is non-terminal")
    }

    @Test fun `track scope respects cross-track blockers`() {
        val w = World("cross")
        val track1 = h.seedTrack(w.ws, "track1")
        val track2 = h.seedTrack(w.ws, "track2")
        val a = h.seedTask(h.rootSegment(track1), w.todo, "A") // in track1
        val b = h.seedTask(h.rootSegment(track2), w.todo, "B") // in track2
        h.exec<Blocks>(AddBlocks(b, a)) // B (track2) blocks A (track1)

        // Track-scoped next returns only track1's tasks, but the cross-track blocker still gates A.
        assertEquals(emptySet(), w.ids(trackId = track1), "A is gated by a blocker in another track")
        w.move(b, w.done)
        assertEquals(setOf(a), w.ids(trackId = track1), "completing the cross-track blocker frees A")
    }

    @Test fun `kind filter restricts and excludes null-kind`() {
        val w = World("kinds")
        val track = h.seedTrack(w.ws, "t")
        val seg = h.rootSegment(track)
        val impl = h.seedTask(seg, w.todo, "impl-task", kind = "impl")
        val review = h.seedTask(seg, w.todo, "review-task", kind = "review")
        val untyped = h.seedTask(seg, w.todo, "untyped")

        assertEquals(setOf(impl, review, untyped), w.ids(), "no kind filter returns all")
        assertEquals(setOf(impl), w.ids(kind = "impl"), "--kind impl returns only impl, excludes null-kind")
    }

    @Test fun `frontier orders by priority desc then id asc`() {
        val w = World("order")
        val track = h.seedTrack(w.ws, "t")
        val seg = h.rootSegment(track)
        val low = h.seedTask(seg, w.todo, "low", priority = 1)
        val highA = h.seedTask(seg, w.todo, "highA", priority = 9)
        val highB = h.seedTask(seg, w.todo, "highB", priority = 9)
        val ordered = frontier.next(h.conn, w.ws).map { it.id }
        assertEquals(listOf(highA, highB, low), ordered, "priority DESC, then id ASC for ties")
    }
}
