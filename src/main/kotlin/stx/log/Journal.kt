package stx.log

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import org.apache.logging.log4j.LogManager
import stx.command.WriteCommand
import stx.dto.*
import java.time.Instant

/**
 * Non-authoritative history (brief §7): one JSON line per committed mutation, emitted to the
 * dedicated `stx.journal` log4j2 logger (its own rolling file, `additivity=false`). SQLite is
 * the source of truth — the journal is write-only, never read back. No `seq`: the single
 * write-actor logs in commit order, so physical line order IS event order. Best-effort — the
 * call happens after commit and log4j swallows appender errors, so it can never affect the txn.
 */
class Journal {
    private val logger = LogManager.getLogger("stx.journal")
    private val json = Json { encodeDefaults = true }

    @Serializable
    data class Event(
        val ts: String,
        val verb: String,
        val entity: String,
        val id: Long?,
        val workspaceId: Long?,
        val version: Int?,
    )

    /** Build and emit the event for a successful write. Called by the write-actor after commit. */
    fun record(command: WriteCommand, reply: Reply) {
        val verb = command::class.simpleName ?: "Write"
        val e = when (reply) {
            is WorkspaceDto -> Event(now(), verb, "workspace", reply.id, reply.id, reply.version)
            is StatusDto -> Event(now(), verb, "status", reply.id, reply.workspaceId, null)
            is TransitionDto -> Event(now(), verb, "status_transition", reply.id, reply.workspaceId, null)
            is TrackDto -> Event(now(), verb, "track", reply.id, reply.workspaceId, reply.version)
            is SegmentDto -> Event(now(), verb, "segment", reply.id, reply.workspaceId, null)
            is KindDto -> Event(now(), verb, "task_kind", reply.id, reply.workspaceId, null)
            is TaskDto -> Event(now(), verb, "task", reply.id, reply.workspaceId, reply.version)
            is BlocksDto -> Event(now(), verb, "blocks", reply.id, reply.workspaceId, null)
            is RelatesDto -> Event(now(), verb, "relates_to", reply.id, reply.workspaceId, null)
            is IdReply -> Event(now(), verb, reply.entity, reply.id, null, reply.version)
            else -> Event(now(), verb, "unknown", null, null, null)
        }
        logger.info(json.encodeToString(e))
    }

    private fun now(): String = Instant.now().toString()
}
