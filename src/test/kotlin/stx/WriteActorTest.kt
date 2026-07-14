package stx

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.runBlocking
import stx.command.*
import stx.dto.*
import stx.error.StxError
import stx.repo.Db
import stx.service.StxService
import stx.service.WriteActor
import java.nio.file.Files
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import tech.codingzen.res.failureOrNull
import tech.codingzen.res.getOrThrow

/** §8/§6: the write-actor serialises mutations and OL arbitrates concurrent edits. */
class WriteActorTest {
    private lateinit var dir: java.io.File
    private lateinit var readConn: java.sql.Connection
    private lateinit var actor: WriteActor
    private val svc = StxService()

    @BeforeTest fun setup() {
        dir = Files.createTempDirectory("stx-actor").toFile()
        val db = Db("jdbc:sqlite:${dir.resolve("stx.db")}").also { it.init() }
        actor = WriteActor(db.connect(), svc)
        readConn = db.connect()
    }
    @AfterTest fun teardown() { actor.close(); readConn.close(); dir.deleteRecursively() }

    private fun id(res: tech.codingzen.res.Res<Reply, StxError>) = when (val v = res.getOrThrow()) {
        is WorkspaceDto -> v.id; is TrackDto -> v.id; is TaskDto -> v.id; else -> error("no id")
    }
    private fun task(id: Long) = (svc.dispatch(readConn, GetTask(id)).getOrThrow() as TaskDetail).task

    @Test fun `concurrent creates all commit and are serialised`() = runBlocking {
        val ws = id(actor.submitBlocking(CreateWorkspace("ws")))
        val track = id(actor.submitBlocking(CreateTrack(ws, "main")))
        val n = 50
        val results = (1..n).map { i ->
            async(Dispatchers.Default) { actor.submit(CreateTask(trackId = track, title = "T$i")) }
        }.awaitAll()
        assertEquals(n, results.count { it.isOk })
        val listed = (svc.dispatch(readConn, ListTasks(track)).getOrThrow() as TaskList).items
        assertEquals(n, listed.size)
    }

    @Test fun `two concurrent edits off the same version - exactly one wins`() = runBlocking {
        val ws = id(actor.submitBlocking(CreateWorkspace("ws")))
        val track = id(actor.submitBlocking(CreateTrack(ws, "main")))
        val taskId = id(actor.submitBlocking(CreateTask(trackId = track, title = "x")))
        val v0 = task(taskId).version

        val (a, b) = listOf("first", "second").map { label ->
            async(Dispatchers.Default) { actor.submit(EditTask(taskId, expectedVersion = v0, title = label)) }
        }.awaitAll()

        assertEquals(1, listOf(a, b).count { it.isOk }, "exactly one edit wins")
        val loser = listOf(a, b).first { it.isFailure }
        assertIs<StxError.VersionConflict>(loser.failureOrNull())
        assertEquals(v0 + 1, task(taskId).version)
    }
}
