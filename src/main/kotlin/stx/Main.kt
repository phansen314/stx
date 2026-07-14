package stx

import org.http4k.server.asServer
import stx.log.Journal
import stx.repo.Db
import stx.service.StxService
import stx.service.WriteActor
import stx.transport.HttpApi
import stx.transport.LoopbackSunHttp
import java.io.File
import java.io.RandomAccessFile
import java.nio.channels.FileLock
import kotlin.system.exitProcess

const val DEFAULT_PORT = 8420

/** XDG state dir for the SQLite database + lock (matches the journal's location, brief §7). */
private fun stateDir(): File {
    val base = System.getenv("XDG_STATE_HOME")?.takeIf { it.isNotBlank() }
        ?: "${System.getProperty("user.home")}/.local/state"
    return File(base, "stx").apply { mkdirs() }
}

/**
 * Single-daemon guard (C1). The whole concurrency model rests on exactly ONE write-actor owning
 * the DB; the default port only protects by accident (a second bind throws "address in use") and
 * the STX_PORT override defeats it. An exclusive OS advisory lock on a sidecar file, keyed to the
 * DB directory (NOT the port), refuses a second daemon against the same DB regardless of port.
 * The OS releases the lock automatically if this process dies, so there is no stale-lock failure.
 */
private fun acquireSingletonLock(dir: File): FileLock {
    val channel = RandomAccessFile(File(dir, "stx.lock"), "rw").channel
    val lock = runCatching { channel.tryLock() }.getOrNull()
    if (lock == null) {
        System.err.println("stx: another daemon already holds ${File(dir, "stx.lock")}; refusing to start")
        exitProcess(1)
    }
    return lock
}

fun main() {
    val dir = stateDir()
    // Single source of truth for the journal location: hand the resolved state dir to log4j2 BEFORE
    // any logger initializes, so the journal file always matches the DB dir — including the blank
    // XDG_STATE_HOME case, where log4j2's own `:-` default (unset-only, not blank) would diverge.
    System.setProperty("stx.journalDir", dir.absolutePath)
    val lock = acquireSingletonLock(dir) // before opening the DB: one writer, always

    val db = Db("jdbc:sqlite:${File(dir, "stx.db")}").also { it.init() }
    db.assertConsistent() // fail loud on any orphan (#6) instead of serving silently-masked reads
    val service = StxService()
    val actor = WriteActor(db.connect(), service, Journal())
    val api = HttpApi(db, service, actor)

    val port = System.getenv("STX_PORT")?.toIntOrNull() ?: DEFAULT_PORT
    val server = api.handler.asServer(LoopbackSunHttp(port)).start()
    println("stx listening on 127.0.0.1:${server.port()}")

    Runtime.getRuntime().addShutdownHook(Thread {
        runCatching { server.stop() }
        runCatching { actor.close() }
        runCatching { lock.release(); lock.channel().close() }
    })
    Thread.currentThread().join()
}
