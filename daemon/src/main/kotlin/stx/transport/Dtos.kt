package stx.transport

import kotlinx.serialization.Serializable
import stx.Metadata

/**
 * Request body shapes for the HTTP façade. Path-borne ids are NOT repeated here; a handler
 * combines the path id with the parsed body to build the right Command.
 */

@Serializable data class WorkspaceBody(val name: String, val metadata: Metadata = emptyMap())
@Serializable data class WorkspacePatchBody(val name: String? = null, val metadata: Metadata? = null)

@Serializable data class StatusBody(val name: String, val terminal: Boolean = false, val kanbanOrder: Int = 0)
@Serializable data class StatusPatchBody(
    val name: String? = null,
    val terminal: Boolean? = null,
    val kanbanOrder: Int? = null,
)

@Serializable data class TransitionBody(val fromStatusId: Long, val toStatusId: Long)

@Serializable data class TrackBody(val name: String, val description: String = "", val metadata: Metadata = emptyMap())
@Serializable data class TrackPatchBody(
    val name: String? = null,
    val description: String? = null,
    val metadata: Metadata? = null,
)

@Serializable data class SegmentBody(val name: String, val parentSegmentId: Long? = null)
@Serializable data class SegmentMoveBody(val newParentSegmentId: Long? = null)

@Serializable data class TaskBody(
    val statusId: Long,
    val title: String,
    val kind: String? = null,
    val description: String = "",
    val priority: Int = 0,
    val dueDate: String? = null,
    val startDate: String? = null,
    val finishDate: String? = null,
    val metadata: Metadata = emptyMap(),
)

@Serializable data class TaskStatusBody(val toStatusId: Long)

@Serializable data class BlocksBody(val source: Long, val target: Long, val metadata: Metadata = emptyMap())
@Serializable data class RelatesBody(
    val kind: String,
    val source: Long,
    val target: Long,
    val metadata: Metadata = emptyMap(),
)

/** Structured error envelope returned for every 4xx/5xx. */
@Serializable data class ErrorBody(val error: String, val kind: String)
