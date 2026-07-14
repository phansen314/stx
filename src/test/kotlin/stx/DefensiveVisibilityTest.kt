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
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue
import tech.codingzen.res.Res
import tech.codingzen.res.getOrThrow

/**
 * §8: the `next` consistency trio (archived-terminal name reuse, orphan blocker), defensive
 * visibility via `live_task`, relates_to symmetry, and the archive-then-recreate edge rule.
 * Some force degenerate states with direct DB writes the service would never produce.
 */
class DefensiveVisibilityTest {
    private lateinit var dir: java.io.File
    private lateinit var db: Db
    private lateinit var conn: java.sql.Connection
    private val svc = StxService()

    @BeforeTest fun setup() {
        dir = Files.createTempDirectory("stx-vis").toFile()
        db = Db("jdbc:sqlite:${dir.resolve("stx.db")}").also { it.init() }
        conn = db.connect()
    }
    @AfterTest fun teardown() { conn.close(); dir.deleteRecursively() }

    private fun w(cmd: Command): Res<Reply, StxError> = StxService.applyWrite(conn) { svc.dispatch(conn, cmd) }
    private fun r(cmd: Command): Res<Reply, StxError> = svc.dispatch(conn, cmd)
    private fun id(res: Res<Reply, StxError>) = when (val v = res.getOrThrow()) {
        is WorkspaceDto -> v.id; is TrackDto -> v.id; is SegmentDto -> v.id; is StatusDto -> v.id
        is TaskDto -> v.id; is BlocksDto -> v.id; is RelatesDto -> v.id; else -> error("no id")
    }
    private fun statusId(ws: Long, name: String) =
        (r(ListStatuses(ws)).getOrThrow() as StatusList).items.first { it.name == name }.id
    private fun frontierIds(ws: Long) = (r(Next(ws)).getOrThrow() as FrontierList).items.map { it.id }
    private fun execRaw(sql: String) = conn.createStatement().use { it.executeUpdate(sql) }
    private fun count(sql: String): Int = conn.createStatement().use { s -> s.executeQuery(sql).use { it.next(); it.getInt(1) } }

    /** Consistency assertion (brief §6/#6): no live task may sit under an archived container,
     *  including an archived ANCESTOR segment (recursive walk up parent_segment_id). */
    private fun orphanCount(): Int = count(
        """
        WITH RECURSIVE seg_anc(task_id, seg_id) AS (
            SELECT t.id, t.segment_id FROM task t WHERE t.archived = 0
            UNION ALL
            SELECT sa.task_id, s.parent_segment_id
            FROM seg_anc sa JOIN segment s ON s.id = sa.seg_id
            WHERE s.parent_segment_id IS NOT NULL
        )
        SELECT COUNT(DISTINCT t.id) FROM task t WHERE t.archived = 0 AND (
            EXISTS (SELECT 1 FROM workspace w WHERE w.id = t.workspace_id AND w.archived = 1)
            OR EXISTS (SELECT 1 FROM segment s JOIN track k ON k.id = s.track_id WHERE s.id = t.segment_id AND k.archived = 1)
            OR EXISTS (SELECT 1 FROM seg_anc sa JOIN segment s ON s.id = sa.seg_id WHERE sa.task_id = t.id AND s.archived = 1)
        )
        """.trimIndent(),
    )

    @Test fun `archived terminal status name does not shadow a live non-terminal one of the same name`() {
        val ws = id(w(CreateWorkspace("ws")))
        val track = id(w(CreateTrack(ws, "t")))
        // retire the seeded terminal 'Done', then re-create a LIVE non-terminal status named 'Done'
        w(ArchiveStatus(ws, statusId(ws, "Done"))).getOrThrow()
        val liveDone = id(w(CreateStatus(ws, "Done", kanbanOrder = 5, terminal = false)))
        val task = id(w(CreateTask(trackId = track, title = "x", statusId = liveDone)))
        assertTrue(task in frontierIds(ws), "task in live non-terminal 'Done' is workable; archived terminal 'Done' must not exclude it")
    }

    @Test fun `orphan blocker neither blocks nor shows, and the consistency assertion finds it`() {
        val ws = id(w(CreateWorkspace("ws")))
        val track = id(w(CreateTrack(ws, "t")))
        val seg = id(w(CreateSegment(track, "child"))) // non-root segment
        val a = id(w(CreateTask(segmentId = seg, title = "blocker")))   // blocker lives in child segment
        val b = id(w(CreateTask(trackId = track, title = "blocked")))   // blocked lives in root segment
        w(AddBlocks(a, b)).getOrThrow()
        assertEquals(listOf(a), frontierIds(ws)) // b gated by a

        // Force an orphan: archive a's segment directly, WITHOUT the cascade that would archive a.
        execRaw("UPDATE segment SET archived = 1 WHERE id = $seg")
        // a is now a live task under an archived segment -> invisible via live_task.
        val f = frontierIds(ws)
        assertTrue(a !in f, "orphaned blocker is invisible")
        assertTrue(b in f, "blocker invisible via live_task -> b no longer gated")
        assertEquals(1, orphanCount(), "the consistency assertion surfaces the orphan the view masked")
    }

    @Test fun `segment cascade reaches a live task under an already-archived mid-tree segment`() {
        val ws = id(w(CreateWorkspace("ws")))
        val track = id(w(CreateTrack(ws, "t")))
        val parent = id(w(CreateSegment(track, "parent")))
        val mid = id(w(CreateSegment(track, "mid", parentSegmentId = parent)))
        val deep = id(w(CreateTask(segmentId = mid, title = "deep")))
        // Degenerate state: mid archived directly WITHOUT cascading its task -> `deep` orphaned under it.
        execRaw("UPDATE segment SET archived = 1 WHERE id = $mid")
        assertEquals(1, orphanCount(), "precondition: deep orphaned under archived mid")
        // Archiving the ancestor must descend THROUGH the archived mid and sweep `deep` (C4b).
        w(ArchiveSegment(parent)).getOrThrow()
        assertEquals(0, orphanCount(), "cascade descended through the archived mid and archived deep")
    }

    @Test fun `assertConsistent throws on a live task orphaned under an archived ancestor segment`() {
        val ws = id(w(CreateWorkspace("ws")))
        val track = id(w(CreateTrack(ws, "t")))
        val seg = id(w(CreateSegment(track, "child")))
        val orphan = id(w(CreateTask(segmentId = seg, title = "x")))
        db.assertConsistent() // clean so far
        execRaw("UPDATE segment SET archived = 1 WHERE id = $seg") // orphan the task
        val ex = assertFailsWith<IllegalStateException> { db.assertConsistent() }
        assertTrue(ex.message!!.contains(orphan.toString()), "error must name the offending task: ${ex.message}")
    }

    @Test fun `relates_to symmetric read dedups - reciprocal directional rows both persist`() {
        val ws = id(w(CreateWorkspace("ws")))
        val track = id(w(CreateTrack(ws, "t")))
        val a = id(w(CreateTask(trackId = track, title = "a")))
        val b = id(w(CreateTask(trackId = track, title = "b")))
        // reciprocal symmetric relation
        w(AddRelates("relates-to", a, b)).getOrThrow()
        w(AddRelates("relates-to", b, a)).getOrThrow()
        // reciprocal directional relation
        w(AddRelates("spawns", a, b)).getOrThrow()
        w(AddRelates("spawns", b, a)).getOrThrow()

        val detail = r(GetTask(a)).getOrThrow() as TaskDetail
        val relatesToB = detail.relates.count { it.otherTaskId == b && it.kind == "relates-to" }
        assertEquals(1, relatesToB, "symmetric relates-to to B shown once (deduped)")
        // both directional spawns rows physically persist (not canonicalised on write)
        assertEquals(2, count("SELECT COUNT(*) FROM relates_to WHERE kind='spawns' AND archived=0"))
    }

    @Test fun `a live duplicate blocks edge is rejected but an archived one can be recreated`() {
        val ws = id(w(CreateWorkspace("ws")))
        val track = id(w(CreateTrack(ws, "t")))
        val a = id(w(CreateTask(trackId = track, title = "a")))
        val b = id(w(CreateTask(trackId = track, title = "b")))
        w(AddBlocks(a, b)).getOrThrow()
        // archive the edge directly (no archive-edge verb exists; the partial unique index is on archived=0)
        execRaw("UPDATE blocks SET archived = 1 WHERE source_task_id = $a AND target_task_id = $b")
        // recreating the same edge is now allowed (only a LIVE duplicate clashes)
        assertTrue(w(AddBlocks(a, b)).isOk, "archived edge does not block recreation")
        assertEquals(1, count("SELECT COUNT(*) FROM blocks WHERE source_task_id=$a AND target_task_id=$b AND archived=0"))
        assertEquals(2, count("SELECT COUNT(*) FROM blocks WHERE source_task_id=$a AND target_task_id=$b"))
    }
}
