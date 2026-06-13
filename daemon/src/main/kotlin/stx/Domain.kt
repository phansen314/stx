package stx

import kotlinx.serialization.Serializable

/**
 * Persisted domain entities — the shapes returned by reads and by mutation handlers.
 * One data class per table in schema.sql. Timestamps are the raw SQLite TEXT
 * (`datetime('now')`) values; formatting is a client concern. Metadata is a flat
 * string→string blob (see [stx.support.Metadata]).
 */

typealias Metadata = Map<String, String>

@Serializable
data class Workspace(
    val id: Long,
    val name: String,
    val metadata: Metadata,
    val archived: Boolean,
    val createdAt: String,
    val updatedAt: String,
)

@Serializable
data class Status(
    val id: Long,
    val workspaceId: Long,
    val name: String,
    val kanbanOrder: Int,
    val terminal: Boolean,
    val archived: Boolean,
    val createdAt: String,
)

@Serializable
data class StatusTransition(
    val id: Long,
    val workspaceId: Long,
    val fromStatusId: Long,
    val toStatusId: Long,
    val archived: Boolean,
)

@Serializable
data class Track(
    val id: Long,
    val workspaceId: Long,
    val name: String,
    val description: String,
    val metadata: Metadata,
    val archived: Boolean,
    val createdAt: String,
    val updatedAt: String,
)

@Serializable
data class Segment(
    val id: Long,
    val workspaceId: Long,
    val trackId: Long,
    val parentSegmentId: Long?,
    val name: String,
    val isRoot: Boolean,
    val archived: Boolean,
    val createdAt: String,
)

@Serializable
data class Task(
    val id: Long,
    val workspaceId: Long,
    val segmentId: Long,
    val statusId: Long,
    val kind: String?,
    val title: String,
    val description: String,
    val priority: Int,
    val dueDate: String?,
    val startDate: String?,
    val finishDate: String?,
    val metadata: Metadata,
    val archived: Boolean,
    val createdAt: String,
    val updatedAt: String,
)

@Serializable
data class Blocks(
    val id: Long,
    val workspaceId: Long,
    val sourceTaskId: Long,
    val targetTaskId: Long,
    val metadata: Metadata,
    val archived: Boolean,
    val createdAt: String,
)

@Serializable
data class RelatesTo(
    val id: Long,
    val workspaceId: Long,
    val kind: String,
    val sourceTaskId: Long,
    val targetTaskId: Long,
    val metadata: Metadata,
    val archived: Boolean,
    val createdAt: String,
)

/** A frontier entry returned by `next` — the actionable-now projection of a task. */
@Serializable
data class FrontierTask(
    val id: Long,
    val title: String,
    val priority: Int,
    val statusId: Long,
    val kind: String?,
    val segmentId: Long,
)
