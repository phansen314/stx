package stx.dto

import kotlinx.serialization.Serializable

/**
 * Success payloads returned on the Ok rail (`Res<Reply, StxError>`). A marker interface, not a
 * polymorphic-serialized union: each implementer is independently `@Serializable`, and the HTTP
 * layer serialises the concrete type via an exhaustive `when` (transport/Json.kt). Row DTOs map
 * 1:1 to schema.sql columns and double as the read output shape (brief §2 / schema.sql).
 */
sealed interface Reply

/** Generic acknowledgement for mutations that need no body beyond identity + new version. */
@Serializable
data class IdReply(val entity: String, val id: Long, val version: Int? = null) : Reply

@Serializable
data class WorkspaceDto(
    val id: Long,
    val name: String,
    val metadataJson: String,
    val archived: Boolean,
    val version: Int,
    val createdAt: String,
    val updatedAt: String,
) : Reply

@Serializable
data class StatusDto(
    val id: Long,
    val workspaceId: Long,
    val name: String,
    val kanbanOrder: Int,
    val terminal: Boolean,
    val isDefault: Boolean,
    val archived: Boolean,
    val createdAt: String,
) : Reply

@Serializable
data class TransitionDto(
    val id: Long,
    val workspaceId: Long,
    val fromStatusId: Long,
    val toStatusId: Long,
    val archived: Boolean,
) : Reply

@Serializable
data class TrackDto(
    val id: Long,
    val workspaceId: Long,
    val name: String,
    val description: String,
    val metadataJson: String,
    val archived: Boolean,
    val version: Int,
    val createdAt: String,
    val updatedAt: String,
) : Reply

@Serializable
data class SegmentDto(
    val id: Long,
    val workspaceId: Long,
    val trackId: Long,
    val parentSegmentId: Long?,
    val name: String,
    val isRoot: Boolean,
    val archived: Boolean,
    val createdAt: String,
) : Reply

@Serializable
data class KindDto(
    val id: Long,
    val workspaceId: Long,
    val name: String,
    val archived: Boolean,
    val createdAt: String,
) : Reply

@Serializable
data class TaskDto(
    val id: Long,
    val workspaceId: Long,
    val segmentId: Long,
    val statusId: Long,
    val kindId: Long?,
    val title: String,
    val description: String,
    val priority: Int,
    val metadataJson: String,
    val archived: Boolean,
    val version: Int,
    val createdAt: String,
    val updatedAt: String,
) : Reply

@Serializable
data class BlocksDto(
    val id: Long,
    val workspaceId: Long,
    val sourceTaskId: Long,
    val targetTaskId: Long,
    val archived: Boolean,
) : Reply

@Serializable
data class RelatesDto(
    val id: Long,
    val workspaceId: Long,
    val kind: String,
    val sourceTaskId: Long,
    val targetTaskId: Long,
    val archived: Boolean,
) : Reply

// ── Composite / read-only replies ────────────────────────────────────────────

/** A single related task as seen by the symmetric read (decision D2): the other endpoint plus
 *  the relation kind and whether this task was the source (direction matters for `spawns`). */
@Serializable
data class RelatesEdge(val kind: String, val otherTaskId: Long, val outgoing: Boolean)

/** GET /tasks/{id}: the task plus its live edges, deduped (decision D2). */
@Serializable
data class TaskDetail(
    val task: TaskDto,
    val blocksOut: List<Long>,
    val blocksIn: List<Long>,
    val relates: List<RelatesEdge>,
) : Reply

/** One frontier row (next.md Reference query projection). */
@Serializable
data class FrontierItem(
    val id: Long,
    val title: String,
    val priority: Int,
    val statusId: Long,
    val segmentId: Long,
    val version: Int,
) : Reply

@Serializable
data class WorkspaceList(val items: List<WorkspaceDto>) : Reply
@Serializable
data class StatusList(val items: List<StatusDto>) : Reply
@Serializable
data class TransitionList(val items: List<TransitionDto>) : Reply
@Serializable
data class KindList(val items: List<KindDto>) : Reply
@Serializable
data class RelatesKindList(val items: List<String>) : Reply
@Serializable
data class TrackList(val items: List<TrackDto>) : Reply
@Serializable
data class SegmentList(val items: List<SegmentDto>) : Reply
@Serializable
data class TaskList(val items: List<TaskDto>) : Reply
@Serializable
data class FrontierList(val items: List<FrontierItem>) : Reply
