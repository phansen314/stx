package stx.service

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import stx.command.Command
import stx.repo.Db
import java.sql.Connection
import java.util.concurrent.Executors

/**
 * The single writer (brief §6). All mutations flow through one coroutine draining a
 * [Channel] of jobs, each applied in its own transaction on ONE long-lived write connection,
 * in submission order. This serializes writes in-process so we never contend on the SQLite
 * write lock and command ordering is deterministic. Reads bypass this entirely (WAL).
 *
 * @param onCommitted best-effort hook invoked AFTER a successful commit (the sidecar log). It
 *   runs on the actor thread; a throw here is swallowed so logging can never roll back the DB.
 */
class WriteActor(
    private val db: Db,
    private val service: Service,
    private val onCommitted: ((Command, Any) -> Unit)? = null,
) {
    private data class Job(val command: Command, val result: CompletableDeferred<Any>)

    private val executor = Executors.newSingleThreadExecutor { r ->
        Thread(r, "stx-write-actor").apply { isDaemon = true }
    }
    private val dispatcher = executor.asCoroutineDispatcher()
    private val scope = CoroutineScope(dispatcher + SupervisorJob())
    private val channel = Channel<Job>(Channel.UNLIMITED)
    private val writeConn: Connection = db.open()

    fun start() {
        scope.launch {
            for (job in channel) process(job)
        }
    }

    /** Submit a command and suspend until it commits (or fails). */
    suspend fun submit(command: Command): Any {
        val deferred = CompletableDeferred<Any>()
        channel.send(Job(command, deferred))
        return deferred.await()
    }

    /** Blocking submit for non-coroutine callers (e.g. HTTP handler threads). */
    fun submitBlocking(command: Command): Any = runBlocking { submit(command) }

    private fun process(job: Job) {
        try {
            writeConn.autoCommit = false
            val result = service.execute(writeConn, job.command)
            writeConn.commit()
            // After commit: best-effort logging that must never affect the committed state.
            try {
                onCommitted?.invoke(job.command, result)
            } catch (_: Throwable) {
            }
            job.result.complete(result)
        } catch (e: Throwable) {
            try {
                writeConn.rollback()
            } catch (_: Throwable) {
            }
            job.result.completeExceptionally(e)
        } finally {
            try {
                writeConn.autoCommit = true
            } catch (_: Throwable) {
            }
        }
    }

    fun stop() {
        channel.close()
        scope.cancel()
        runCatching { writeConn.close() }
        dispatcher.close()
    }
}
