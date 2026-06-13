package stx.command

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import stx.Metadata

/**
 * The mutation protocol (brief §5). Every verb that WRITES is a data class implementing
 * [Command]; reads are plain query methods elsewhere. The service dispatches over this with
 * an exhaustive `when` (no `else`) so the compiler forces every new verb to be handled.
 * All mutations flow through the single write-actor as [Command] values.
 *
 * @Serializable + sealed enables round-trip wire serialization (tested) and keeps the HTTP
 * façade a thin parser: a route builds the right Command and hands it off.
 */
@Serializable
sealed interface Command

/** Partial task edit; a null field means "leave unchanged". */
@Serializable
data class TaskPatch(
    val title: String? = null,
    val description: String? = null,
    val priority: Int? = null,
    val kind: String? = null,
    val dueDate: String? = null,
    val startDate: String? = null,
    val finishDate: String? = null,
    val metadata: Metadata? = null,
)

// ── workspace ────────────────────────────────────────────────────────────────
@Serializable @SerialName("workspace.create")
data class CreateWorkspace(val name: String, val metadata: Metadata = emptyMap()) : Command

@Serializable @SerialName("workspace.update")
data class UpdateWorkspace(val workspaceId: Long, val name: String? = null, val metadata: Metadata? = null) : Command

@Serializable @SerialName("workspace.archive")
data class ArchiveWorkspace(val workspaceId: Long) : Command

// ── status ───────────────────────────────────────────────────────────────────
@Serializable @SerialName("status.create")
data class CreateStatus(
    val workspaceId: Long,
    val name: String,
    val terminal: Boolean = false,
    val kanbanOrder: Int = 0,
) : Command

@Serializable @SerialName("status.update")
data class UpdateStatus(
    val statusId: Long,
    val name: String? = null,
    val terminal: Boolean? = null,
    val kanbanOrder: Int? = null,
) : Command

@Serializable @SerialName("status.archive")
data class ArchiveStatus(val statusId: Long) : Command

// ── transition ───────────────────────────────────────────────────────────────
@Serializable @SerialName("transition.create")
data class CreateTransition(val workspaceId: Long, val fromStatusId: Long, val toStatusId: Long) : Command

@Serializable @SerialName("transition.archive")
data class ArchiveTransition(val transitionId: Long) : Command

// ── track ────────────────────────────────────────────────────────────────────
@Serializable @SerialName("track.create")
data class CreateTrack(
    val workspaceId: Long,
    val name: String,
    val description: String = "",
    val metadata: Metadata = emptyMap(),
) : Command

@Serializable @SerialName("track.update")
data class UpdateTrack(
    val trackId: Long,
    val name: String? = null,
    val description: String? = null,
    val metadata: Metadata? = null,
) : Command

@Serializable @SerialName("track.archive")
data class ArchiveTrack(val trackId: Long) : Command

// ── segment ──────────────────────────────────────────────────────────────────
@Serializable @SerialName("segment.create")
data class CreateSegment(val trackId: Long, val name: String, val parentSegmentId: Long? = null) : Command

/** Reparent within the same track (track_id is immutable; new parent must be in the same track). */
@Serializable @SerialName("segment.move")
data class MoveSegment(val segmentId: Long, val newParentSegmentId: Long?) : Command

@Serializable @SerialName("segment.archive")
data class ArchiveSegment(val segmentId: Long) : Command

// ── task ─────────────────────────────────────────────────────────────────────
/** Create a task in a concrete segment. The HTTP façade resolves "add to track" → root segment. */
@Serializable @SerialName("task.create")
data class CreateTask(
    val segmentId: Long,
    val statusId: Long,
    val title: String,
    val kind: String? = null,
    val description: String = "",
    val priority: Int = 0,
    val dueDate: String? = null,
    val startDate: String? = null,
    val finishDate: String? = null,
    val metadata: Metadata = emptyMap(),
) : Command

@Serializable @SerialName("task.update")
data class UpdateTask(val taskId: Long, val patch: TaskPatch) : Command

/** Move a task to another status — legal IFF a matching status_transition exists. */
@Serializable @SerialName("task.move")
data class MoveTask(val taskId: Long, val toStatusId: Long) : Command

@Serializable @SerialName("task.archive")
data class ArchiveTask(val taskId: Long) : Command

// ── edges ────────────────────────────────────────────────────────────────────
@Serializable @SerialName("blocks.create")
data class AddBlocks(val sourceTaskId: Long, val targetTaskId: Long, val metadata: Metadata = emptyMap()) : Command

@Serializable @SerialName("blocks.archive")
data class ArchiveBlocks(val blocksId: Long) : Command

@Serializable @SerialName("relates.create")
data class AddRelatesTo(
    val kind: String,
    val sourceTaskId: Long,
    val targetTaskId: Long,
    val metadata: Metadata = emptyMap(),
) : Command

@Serializable @SerialName("relates.archive")
data class ArchiveRelatesTo(val relatesId: Long) : Command
