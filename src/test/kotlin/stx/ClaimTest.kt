package stx

import stx.command.*
import stx.dto.*
import stx.error.StxError
import stx.repo.Db
import stx.repo.TaskRepo
import stx.service.StxService
import stx.service.WriteActor
import java.nio.file.Files
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue
import tech.codingzen.res.Res
import tech.codingzen.res.failureOrNull
import tech.codingzen.res.getOrThrow

/**
 * The agent lease (schema v2): claim-if-free, renew, expiry, and the frontier predicate that makes
 * a reservation mean something. The property under test throughout is **no double-work** — the gap
 * optimistic locking deliberately does not close (design.md, "Double-work").
 */
class ClaimTest {
    private lateinit var dir: java.io.File
    private lateinit var db: Db
    private lateinit var conn: java.sql.Connection
    private val svc = StxService()

    @BeforeTest fun setup() {
        dir = Files.createTempDirectory("stx-claim").toFile()
        db = Db("jdbc:sqlite:${dir.resolve("stx.db")}").also { it.init() }
        conn = db.connect()
    }
    @AfterTest fun teardown() { conn.close(); dir.deleteRecursively() }

    private fun w(cmd: Command): Res<Reply, StxError> = StxService.applyWrite(conn) { svc.dispatch(conn, cmd) }
    private fun r(cmd: Command): Res<Reply, StxError> = svc.dispatch(conn, cmd)
    private fun task(cmd: Command): TaskDto = w(cmd).getOrThrow() as TaskDto
    private fun frontier(ws: Long, asAgent: String? = null): List<Long> =
        (r(Next(ws, asAgent = asAgent)).getOrThrow() as FrontierList).items.map { it.id }

    /** workspace + track + two ready tasks. */
    private fun seed(): Triple<Long, Long, Long> {
        val ws = (w(CreateWorkspace("ws")).getOrThrow() as WorkspaceDto).id
        val track = (w(CreateTrack(ws, "t")).getOrThrow() as TrackDto).id
        val a = task(CreateTask(trackId = track, title = "a", priority = 2)).id
        val b = task(CreateTask(trackId = track, title = "b", priority = 1)).id
        return Triple(ws, a, b)
    }

    // ── the primitive ────────────────────────────────────────────────────────────────────────

    @Test fun `claim-if-free - first agent wins, second is told who holds it and until when`() {
        val (_, a, _) = seed()
        val held = w(ClaimTask(a, "agent-1", 60)).getOrThrow() as TaskDto
        assertEquals("agent-1", held.claimedBy)
        assertNotNull(held.claimedUntil)

        val lost = w(ClaimTask(a, "agent-2", 60)).failureOrNull()
        val claimed = assertTrue(lost is StxError.Claimed, "want Claimed, got $lost").let { lost as StxError.Claimed }
        assertEquals("agent-1", claimed.by, "the loser must be told the holder, not just 'no'")
        assertEquals(held.claimedUntil, claimed.until)
    }

    @Test fun `a claim does not move version or updated_at - lease and OL are separate axes`() {
        val (_, a, _) = seed()
        // updated_at is second-granularity, so comparing it across a same-second claim would pass
        // whether or not the claim wrote it. Backdate first — now the assertion has teeth.
        val backdated = "2000-01-01 00:00:00"
        conn.createStatement().use { it.execute("UPDATE task SET updated_at='$backdated' WHERE id=$a") }
        val original = (r(GetTask(a)).getOrThrow() as TaskDetail).task

        w(ClaimTask(a, "agent-1", 60)).getOrThrow()
        val after = (r(GetTask(a)).getOrThrow() as TaskDetail).task
        assertEquals(original.version, after.version, "claiming must not bump the OL token")
        assertEquals(backdated, after.updatedAt, "claiming is a reservation, not a content edit")
        // The consequence that matters: a CAS an agent planned before someone else's claim still
        // applies. If the lease shared `version`, this would be a spurious 409.
        assertTrue(w(EditTask(a, original.version, title = "still editable")).getOrThrow() is TaskDto)
    }

    @Test fun `re-claiming your own task renews it - one primitive, no separate heartbeat verb`() {
        val (_, a, _) = seed()
        val first = task(ClaimTask(a, "agent-1", 1))
        val renewed = task(ClaimTask(a, "agent-1", 3600))
        assertEquals("agent-1", renewed.claimedBy)
        assertTrue(renewed.claimedUntil!! > first.claimedUntil!!, "renew must push the expiry out")
        assertEquals(first.version, renewed.version, "renew is still not a content edit")
    }

    @Test fun `an expired lease is re-claimable by anyone, with no sweeper having run`() {
        val (ws, a, _) = seed()
        // A TTL in the past: expiry is evaluated on read, so this is immediately lapsed.
        conn.createStatement().use {
            it.execute("UPDATE task SET claimed_by='ghost', claimed_until=datetime('now','-1 hour') WHERE id=$a")
        }
        assertTrue(a in frontier(ws), "a lapsed lease must not hold the frontier")
        val taken = task(ClaimTask(a, "agent-2", 60))
        assertEquals("agent-2", taken.claimedBy, "a crashed agent's lease is reclaimable when it expires")
    }

    // ── frontier ─────────────────────────────────────────────────────────────────────────────

    @Test fun `a live lease removes the task from next - but not from its own holder's view`() {
        val (ws, a, b) = seed()
        assertEquals(listOf(a, b), frontier(ws))
        w(ClaimTask(a, "agent-1", 600)).getOrThrow()
        assertEquals(listOf(b), frontier(ws), "an unidentified read sees only free work")
        assertEquals(listOf(a, b), frontier(ws, asAgent = "agent-1"), "the holder still sees what it reserved")
        assertEquals(listOf(b), frontier(ws, asAgent = "agent-2"), "another agent does not")
    }

    @Test fun `releasing returns the task to the frontier - non-holders are refused`() {
        val (ws, a, _) = seed()
        w(ClaimTask(a, "agent-1", 600)).getOrThrow()
        assertTrue(a !in frontier(ws))

        val refused = w(ReleaseTask(a, "agent-2")).failureOrNull()
        assertTrue(refused is StxError.Claimed, "a non-holder must not be able to release, got $refused")
        assertTrue(a !in frontier(ws), "the refused release must not have dropped the lease")

        val freed = task(ReleaseTask(a, "agent-1"))
        assertNull(freed.claimedBy)
        assertNull(freed.claimedUntil)
        assertTrue(a in frontier(ws))
    }

    @Test fun `releasing something free or already expired is a no-op, not an error`() {
        val (_, a, _) = seed()
        // never claimed
        assertNull((w(ReleaseTask(a, "agent-1")).getOrThrow() as TaskDto).claimedBy)
        // lapsed lease held by someone else: a recovering agent must not have to special-case this
        conn.createStatement().use {
            it.execute("UPDATE task SET claimed_by='ghost', claimed_until=datetime('now','-1 hour') WHERE id=$a")
        }
        assertTrue(w(ReleaseTask(a, "agent-1")).getOrThrow() is TaskDto)
    }

    // ── guards ───────────────────────────────────────────────────────────────────────────────

    @Test fun `claim rejects a blank agent, a non-positive ttl, a done task, and an archived one`() {
        val (ws, a, b) = seed()
        assertTrue(w(ClaimTask(a, "  ", 60)).failureOrNull() is StxError.Validation)
        assertTrue(w(ClaimTask(a, "agent-1", 0)).failureOrNull() is StxError.Validation)
        assertTrue(w(ClaimTask(a, "agent-1", -5)).failureOrNull() is StxError.Validation)

        val done = (r(ListStatuses(ws)).getOrThrow() as StatusList).items.first { it.terminal }
        w(MoveStatus(a, done.id, 0)).getOrThrow()
        assertTrue(
            w(ClaimTask(a, "agent-1", 60)).failureOrNull() is StxError.Validation,
            "a finished task has nothing left to reserve",
        )
        w(ArchiveTask(b)).getOrThrow()
        assertTrue(w(ClaimTask(b, "agent-1", 60)).failureOrNull() is StxError.Gone)
        assertTrue(w(ClaimTask(99999, "agent-1", 60)).failureOrNull() is StxError.NotFound)
    }

    @Test fun `claiming a blocked task is allowed - the daemon holds no policy about what to reserve`() {
        val (ws, a, b) = seed()
        w(AddBlocks(a, b)).getOrThrow() // b is blocked by a, so b is not in `next`
        assertTrue(b !in frontier(ws))
        assertEquals("agent-1", task(ClaimTask(b, "agent-1", 60)).claimedBy)
    }

    // ── fused next-and-claim ─────────────────────────────────────────────────────────────────

    @Test fun `next-and-claim returns only what it reserved, ordered like the frontier`() {
        val (ws, a, b) = seed()
        val got = (w(NextAndClaim(ws, "agent-1", 600)).getOrThrow() as FrontierList).items
        assertEquals(listOf(a, b), got.map { it.id })
        assertTrue(got.all { it.claimedBy == "agent-1" && it.claimedUntil != null }, "rows must carry the lease taken")
        assertTrue(frontier(ws).isEmpty(), "everything is now reserved")
        // a second agent's fused call comes back empty rather than failing
        assertTrue((w(NextAndClaim(ws, "agent-2", 600)).getOrThrow() as FrontierList).items.isEmpty())
    }

    @Test fun `next-and-claim honours limit and scope, and renews the caller's own rows`() {
        val (ws, a, _) = seed()
        val first = (w(NextAndClaim(ws, "agent-1", 1, limit = 1)).getOrThrow() as FrontierList).items
        assertEquals(listOf(a), first.map { it.id })
        val again = (w(NextAndClaim(ws, "agent-1", 3600, limit = 1)).getOrThrow() as FrontierList).items
        assertEquals(listOf(a), again.map { it.id }, "the caller's own lease is renewable through the same loop")
        assertTrue(again[0].claimedUntil!! > first[0].claimedUntil!!)
        assertTrue(w(ClaimTask(a, "agent-2", 60)).failureOrNull() is StxError.Claimed)
    }

    /**
     * The actual anti-double-work property, exercised through the real write actor rather than the
     * synchronous test path: two agents racing `--limit 1` over a two-task frontier must come away
     * with *different* tasks. Serialization is what guarantees it, so this is the test that would
     * catch someone "optimising" the fused call out of the actor.
     */
    @Test fun `two concurrent next-and-claim calls never hand out the same task`() {
        val (ws, a, b) = seed()
        WriteActor(db.connect(), StxService()).use { actor ->
            val pool = Executors.newFixedThreadPool(2)
            try {
                val jobs = listOf("agent-1", "agent-2").map { agent ->
                    Callable { actor.submitBlocking(NextAndClaim(ws, agent, 600, limit = 1)) }
                }
                val results = pool.invokeAll(jobs).map { (it.get().getOrThrow() as FrontierList).items }
                val claimedIds = results.flatten().map { it.id }
                assertEquals(2, claimedIds.size, "each agent should get exactly one task")
                assertEquals(setOf(a, b), claimedIds.toSet(), "and never the same one twice")
            } finally {
                pool.shutdownNow()
            }
        }
    }

    @Test fun `claims lists live leases only`() {
        val (ws, a, b) = seed()
        w(ClaimTask(a, "agent-1", 600)).getOrThrow()
        conn.createStatement().use {
            it.execute("UPDATE task SET claimed_by='ghost', claimed_until=datetime('now','-1 hour') WHERE id=$b")
        }
        val items = (r(ListClaims(ws)).getOrThrow() as ClaimList).items
        assertEquals(listOf(a), items.map { it.id }, "an expired lease is not a claim")
        assertEquals("agent-1", items[0].claimedBy)
        assertEquals("a", items[0].title)
    }

    @Test fun `the lease survives a round trip through the repo layer unchanged`() {
        val (_, a, _) = seed()
        w(ClaimTask(a, "agent-1", 600)).getOrThrow()
        val row = TaskRepo.getById(conn, a)!!
        assertEquals("agent-1", row.claimedBy)
        assertTrue(!TaskRepo.leaseExpired(conn, a))
    }
}
