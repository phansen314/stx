package stx.transport

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import stx.dto.*

/** kotlinx.serialization setup + the single place a [Reply] becomes a JSON string. */
val json: Json = Json {
    ignoreUnknownKeys = true
    encodeDefaults = true
}

/**
 * Encode any [Reply] to JSON via an exhaustive `when` (no else) — adding a Reply type is a
 * compile error here until handled. Each branch is smart-cast, so `encodeToString` infers the
 * concrete serializer; no polymorphic discriminator pollutes the curl-friendly body.
 */
fun encodeReply(reply: Reply): String = when (reply) {
    is IdReply -> json.encodeToString(reply)
    is WorkspaceDto -> json.encodeToString(reply)
    is StatusDto -> json.encodeToString(reply)
    is TransitionDto -> json.encodeToString(reply)
    is TrackDto -> json.encodeToString(reply)
    is SegmentDto -> json.encodeToString(reply)
    is KindDto -> json.encodeToString(reply)
    is TaskDto -> json.encodeToString(reply)
    is BlocksDto -> json.encodeToString(reply)
    is RelatesDto -> json.encodeToString(reply)
    is TaskDetail -> json.encodeToString(reply)
    is FrontierItem -> json.encodeToString(reply)
    is WorkspaceList -> json.encodeToString(reply)
    is StatusList -> json.encodeToString(reply)
    is TransitionList -> json.encodeToString(reply)
    is KindList -> json.encodeToString(reply)
    is RelatesKindList -> json.encodeToString(reply)
    is TrackList -> json.encodeToString(reply)
    is SegmentList -> json.encodeToString(reply)
    is TaskList -> json.encodeToString(reply)
    is FrontierList -> json.encodeToString(reply)
}

// ── Request body shapes (path supplies ids; body supplies the rest) ──────────────────────────

@Serializable data class WorkspaceBody(val name: String, val metadataJson: String = "{}")
@Serializable data class StatusBody(val name: String, val kanbanOrder: Int = 0, val terminal: Boolean = false)
@Serializable data class KindBody(val name: String)
@Serializable data class TransitionBody(val fromStatusId: Long, val toStatusId: Long)
@Serializable data class TrackBody(val name: String, val description: String = "", val metadataJson: String = "{}")
@Serializable data class SegmentBody(val name: String, val parentSegmentId: Long? = null)

@Serializable data class TaskBody(
    val title: String,
    val description: String = "",
    val priority: Int = 0,
    val statusId: Long? = null,
    val kindId: Long? = null,
    val metadataJson: String = "{}",
)

@Serializable data class MoveStatusBody(val toStatusId: Long, val expectedVersion: Int)

@Serializable data class EditTaskBody(
    val expectedVersion: Int,
    val title: String? = null,
    val description: String? = null,
    val priority: Int? = null,
    val kindId: Long? = null,
    val clearKind: Boolean = false,
    val metadataJson: String? = null,
)

@Serializable data class EditWorkspaceBody(val expectedVersion: Int, val name: String? = null, val metadataJson: String? = null)
@Serializable data class EditTrackBody(val expectedVersion: Int, val name: String? = null, val description: String? = null, val metadataJson: String? = null)
@Serializable data class BlocksBody(val sourceTaskId: Long, val targetTaskId: Long)
@Serializable data class RelatesBody(val kind: String, val sourceTaskId: Long, val targetTaskId: Long)
