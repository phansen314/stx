package stx.log

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import stx.Blocks
import stx.RelatesTo
import stx.Segment
import stx.Status
import stx.StatusTransition
import stx.Task
import stx.Track
import stx.Workspace
import stx.command.Command
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardOpenOption

/**
 * Append-only event log (brief §7). NON-AUTHORITATIVE: SQLite is the source of truth and this
 * file is never read back to determine state. It exists so the single ordered write path can be
 * clean *logging* rather than after-the-fact auditing. One global file with a `workspace` field;
 * monotonic seq numbers resumed by scanning the last line on startup.
 *
 * Invoked via the write-actor's onCommitted hook, AFTER commit, on the actor thread — so there is
 * no concurrent writer. The actor swallows any throw here so a log failure can never roll back
 * the committed transaction.
 */
class Sidecar(private val path: Path, private val clockMillis: () -> Long = System::currentTimeMillis) {
    private val json = Json
    private var seq: Long = readMaxSeq(path)

    fun record(command: Command, result: Any) {
        val ref = describe(result) ?: return
        val verb = verbOf(command)
        seq += 1
        val event: JsonObject = buildJsonObject {
            put("seq", seq)
            put("ts", clockMillis())
            put("workspace", ref.workspaceId)
            put("entity_type", ref.entityType)
            put("entity_id", ref.entityId)
            put("verb", verb)
        }
        path.parent?.let { Files.createDirectories(it) }
        Files.write(
            path,
            (event.toString() + "\n").toByteArray(Charsets.UTF_8),
            StandardOpenOption.CREATE,
            StandardOpenOption.APPEND,
        )
    }

    /** Last assigned seq (for tests / introspection). */
    fun currentSeq(): Long = seq

    private data class EntityRef(val entityType: String, val entityId: Long, val workspaceId: Long)

    private fun describe(result: Any): EntityRef? = when (result) {
        is Workspace -> EntityRef("workspace", result.id, result.id)
        is Status -> EntityRef("status", result.id, result.workspaceId)
        is StatusTransition -> EntityRef("transition", result.id, result.workspaceId)
        is Track -> EntityRef("track", result.id, result.workspaceId)
        is Segment -> EntityRef("segment", result.id, result.workspaceId)
        is Task -> EntityRef("task", result.id, result.workspaceId)
        is Blocks -> EntityRef("blocks", result.id, result.workspaceId)
        is RelatesTo -> EntityRef("relates_to", result.id, result.workspaceId)
        else -> null
    }

    private fun verbOf(command: Command): String =
        (json.encodeToJsonElement(Command.serializer(), command) as JsonObject)["type"]
            ?.jsonPrimitive?.content
            ?: command::class.simpleName.orEmpty()

    private fun readMaxSeq(path: Path): Long {
        if (!Files.exists(path)) return 0
        val last = Files.newBufferedReader(path).useLines { lines ->
            lines.map { it.trim() }.filter { it.isNotEmpty() }.lastOrNull()
        } ?: return 0
        return runCatching {
            json.parseToJsonElement(last).jsonObject["seq"]!!.jsonPrimitive.content.toLong()
        }.getOrDefault(0)
    }

    companion object {
        /** Default log path under the XDG state dir: `$XDG_STATE_HOME/stx/events.log`. */
        fun defaultPath(): Path {
            val state = System.getenv("XDG_STATE_HOME")?.takeIf { it.isNotBlank() }
                ?: (System.getProperty("user.home") + "/.local/state")
            return Path.of(state, "stx", "events.log")
        }
    }
}
