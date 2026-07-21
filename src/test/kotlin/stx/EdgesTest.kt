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
import tech.codingzen.res.Res
import tech.codingzen.res.getOrThrow

/** GET /workspaces/{id}/edges: the bulk edge read backing `stx graph` — live blocks + relates,
 *  archived excluded. */
class EdgesTest {
    private lateinit var dir: java.io.File
    private lateinit var conn: java.sql.Connection
    private val svc = StxService()

    @BeforeTest fun setup() {
        dir = Files.createTempDirectory("stx-edges").toFile()
        conn = Db("jdbc:sqlite:${dir.resolve("stx.db")}").also { it.init() }.connect()
    }
    @AfterTest fun teardown() { conn.close(); dir.deleteRecursively() }

    private fun w(cmd: Command): Res<Reply, StxError> = StxService.applyWrite(conn) { svc.dispatch(conn, cmd) }
    private fun idOf(res: Res<Reply, StxError>): Long = when (val v = res.getOrThrow()) {
        is TaskDto -> v.id; is TrackDto -> v.id; is WorkspaceDto -> v.id; else -> error("no id")
    }
    private fun edges(ws: Long) = svc.dispatch(conn, ListEdges(ws)).getOrThrow() as EdgeList

    @Test fun `edges returns live blocks and relates, excludes archived`() {
        val ws = idOf(w(CreateWorkspace("ws")))
        val track = idOf(w(CreateTrack(ws, "main")))
        val t = (1..3).map { idOf(w(CreateTask(trackId = track, title = "T$it"))) }
        w(AddBlocks(t[0], t[1])).getOrThrow()
        w(AddRelates("spawns", t[0], t[2])).getOrThrow()

        val e = edges(ws)
        assertEquals(listOf(t[0] to t[1]), e.blocks.map { it.sourceTaskId to it.targetTaskId })
        assertEquals(listOf(Triple("spawns", t[0], t[2])),
            e.relates.map { Triple(it.kind, it.sourceTaskId, it.targetTaskId) })

        // archiving the blocks edge drops it from the bulk read; the relate remains
        w(RemoveBlocks(t[0], t[1])).getOrThrow()
        val e2 = edges(ws)
        assertEquals(emptyList(), e2.blocks)
        assertEquals(1, e2.relates.size)
    }

    /** #4 corollary: archiving a task cascades its incident relates_to rows (both directions),
     *  symmetric with the blocks cascade — so a live edge never dangles off an archived task. */
    @Test fun `archiving a task cascades its incident relates edges`() {
        val ws = idOf(w(CreateWorkspace("ws")))
        val track = idOf(w(CreateTrack(ws, "main")))
        val t = (1..3).map { idOf(w(CreateTask(trackId = track, title = "T$it"))) }
        w(AddRelates("spawns", t[0], t[1])).getOrThrow()   // t0 as source
        w(AddRelates("mentions", t[2], t[0])).getOrThrow() // t0 as target
        assertEquals(2, edges(ws).relates.size)

        w(ArchiveTask(t[0])).getOrThrow()
        // both the source-side and target-side relations incident to t0 are archived out.
        assertEquals(emptyList(), edges(ws).relates)
    }
}
