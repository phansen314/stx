package stx

import stx.command.Command
import stx.command.CreateStatus
import stx.command.CreateTask
import stx.command.CreateTrack
import stx.command.CreateTransition
import stx.command.CreateWorkspace
import stx.repo.Db
import stx.repo.SegmentRepo
import stx.service.Service
import java.nio.file.Files
import java.nio.file.Path
import java.sql.Connection

/**
 * Single-threaded test harness: one connection used for both writes (each [exec] is its own
 * transaction, mirroring the write-actor) and reads. Plus seed helpers for fixtures.
 */
class Harness {
    private val tmp: Path = Files.createTempFile("stx-harness", ".db")
    private val db = Db.forFile(tmp.toString())
    val conn: Connection
    private val service = Service()

    init {
        db.init()
        conn = db.open()
    }

    /** Run a command in its own transaction and return the typed result. */
    @Suppress("UNCHECKED_CAST")
    fun <T> exec(command: Command): T {
        conn.autoCommit = false
        try {
            val result = service.execute(conn, command)
            conn.commit()
            return result as T
        } catch (e: Exception) {
            conn.rollback()
            throw e
        } finally {
            conn.autoCommit = true
        }
    }

    fun close() {
        conn.close()
        Files.deleteIfExists(tmp)
        Files.deleteIfExists(Path.of("$tmp-wal"))
        Files.deleteIfExists(Path.of("$tmp-shm"))
    }

    // ── seed helpers ───────────────────────────────────────────────────────────
    fun seedWorkspace(name: String = "ws"): Long = exec<Workspace>(CreateWorkspace(name)).id

    fun seedStatus(ws: Long, name: String, terminal: Boolean = false, order: Int = 0): Long =
        exec<Status>(CreateStatus(ws, name, terminal, order)).id

    fun seedTransition(ws: Long, from: Long, to: Long): Long =
        exec<StatusTransition>(CreateTransition(ws, from, to)).id

    fun seedTrack(ws: Long, name: String): Long = exec<Track>(CreateTrack(ws, name)).id

    fun rootSegment(trackId: Long): Long = SegmentRepo.rootForTrack(conn, trackId)!!.id

    fun seedTask(
        segmentId: Long,
        statusId: Long,
        title: String,
        kind: String? = null,
        priority: Int = 0,
    ): Long = exec<Task>(CreateTask(segmentId, statusId, title, kind = kind, priority = priority)).id
}
