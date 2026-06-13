package stx

import stx.command.CreateStatus
import stx.command.CreateWorkspace
import stx.repo.Db
import stx.repo.WorkspaceRepo
import stx.service.Service
import stx.service.WriteActor
import java.nio.file.Files
import java.nio.file.Path
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class WriteActorTest {
    private val tmp: Path = Files.createTempFile("stx-actor", ".db")
    private val db = Db.forFile(tmp.toString())
    private val actor: WriteActor

    init {
        db.init()
        actor = WriteActor(db, Service())
        actor.start()
    }

    @AfterTest fun cleanup() {
        actor.stop()
        Files.deleteIfExists(tmp)
        Files.deleteIfExists(Path.of("$tmp-wal"))
        Files.deleteIfExists(Path.of("$tmp-shm"))
    }

    @Test fun `commits a mutation visible to a separate read connection`() {
        val ws = actor.submitBlocking(CreateWorkspace("a")) as Workspace
        assertEquals("a", ws.name)
        db.open().use { read -> assertTrue(WorkspaceRepo.get(read, ws.id) != null) }
    }

    @Test fun `serializes in submission order with ascending ids`() {
        val ids = (1..5).map { (actor.submitBlocking(CreateWorkspace("w$it")) as Workspace).id }
        assertEquals(ids.sorted(), ids, "ids should be monotonically increasing in submission order")
        assertEquals(5, ids.toSet().size)
    }

    @Test fun `a failed command rolls back and the actor survives`() {
        assertFailsWith<StxException.NotFound> { actor.submitBlocking(CreateStatus(999, "x")) }
        // Actor still healthy: a subsequent valid command commits.
        val ws = actor.submitBlocking(CreateWorkspace("after")) as Workspace
        assertEquals("after", ws.name)
    }

    @Test fun `onCommitted hook fires after a successful commit`() {
        val seen = mutableListOf<Any>()
        val a2 = WriteActor(db, Service()) { cmd, _ -> seen.add(cmd) }
        a2.start()
        try {
            a2.submitBlocking(CreateWorkspace("logged"))
            assertEquals(1, seen.size)
            assertTrue(seen[0] is CreateWorkspace)
        } finally {
            a2.stop()
        }
    }
}
