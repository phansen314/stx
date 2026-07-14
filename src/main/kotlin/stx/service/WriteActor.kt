package stx.service

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import stx.command.WriteCommand
import stx.dto.Reply
import stx.error.StxError
import stx.log.Journal
import tech.codingzen.res.Res
import tech.codingzen.res.getOrNull
import java.sql.Connection
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicLong

/**
 * The single write path (brief §6). One coroutine drains a channel of write jobs and applies
 * each in its own transaction via [StxService.applyWrite] (commit IFF the `Res` is Ok). This
 * serialises all mutations in-process — no contention on the SQLite write lock, deterministic
 * ordering — which is also what makes optimistic locking and the journal correct.
 *
 * The actor owns ONE dedicated write [Connection] and runs on a single pinned thread, so the
 * connection is never touched concurrently. Reads do not come here — they run on their own
 * connections against WAL.
 */
class WriteActor(
    private val conn: Connection,
    private val service: StxService,
    private val journal: Journal? = null,
) : AutoCloseable {

    private class Job(val command: WriteCommand, val reply: CompletableDeferred<Res<Reply, StxError>>)

    private val dispatcher = Executors.newSingleThreadExecutor { r -> Thread(r, "stx-write-actor") }.asCoroutineDispatcher()
    private val scope = CoroutineScope(dispatcher)
    private val channel = Channel<Job>(Channel.UNLIMITED)

    /**
     * Monotonic change token bumped once per committed mutation. In-memory only: a poll client
     * (the TUI) compares by inequality, so a daemon restart resetting this to the seed just reads
     * as "something changed" and triggers one harmless reload. The durable cross-restart cursor
     * remains deferred (schema.sql) until a subscriber needs stronger guarantees.
     */
    private val changeCounter = AtomicLong(1)

    /** Current change token; see [changeCounter]. Safe to read from any (reader) thread. */
    fun changeSeq(): Long = changeCounter.get()

    // Fully qualified: the private inner [Job] class shadows kotlinx's Job in this scope.
    private val worker: kotlinx.coroutines.Job = scope.launch {
        for (job in channel) {
            val result = try {
                StxService.applyWrite(conn) { service.dispatch(conn, job.command) }
            } catch (t: Throwable) {
                // A throw from commit/rollback itself is genuinely exceptional; surface it to the caller.
                job.reply.completeExceptionally(t)
                continue
            }
            // After commit, bump the change token then best-effort journal (brief §7); neither
            // must affect the reply. The counter moves only on a committed mutation.
            if (result.isOk) {
                changeCounter.incrementAndGet()
                result.getOrNull()?.let { reply -> runCatching { journal?.record(job.command, reply) } }
            }
            job.reply.complete(result)
        }
    }

    /** Submit a write and suspend until the actor has applied (and committed/rolled back) it. */
    suspend fun submit(command: WriteCommand): Res<Reply, StxError> {
        val reply = CompletableDeferred<Res<Reply, StxError>>()
        channel.send(Job(command, reply))
        return reply.await()
    }

    /** Blocking bridge for http4k's blocking handlers (brief §6). */
    fun submitBlocking(command: WriteCommand): Res<Reply, StxError> = runBlocking { submit(command) }

    override fun close() {
        channel.close()
        // Drain buffered jobs before tearing down the dispatcher, so in-flight writes are not
        // stranded (their callers left hanging on reply.await()). Bounded so a stuck commit can't
        // wedge shutdown.
        runCatching { runBlocking { withTimeout(DRAIN_TIMEOUT_MS) { worker.join() } } }
        dispatcher.close()
        conn.close()
    }

    private companion object {
        const val DRAIN_TIMEOUT_MS = 5_000L
    }
}
