package stx.command

import kotlinx.serialization.Serializable

/**
 * The full API modelled as a sealed hierarchy (brief §5). The service dispatches over this
 * with an exhaustive `when` (no else) so adding a verb is a compile error until handled.
 *
 * The read/write split is the dispatch boundary (brief §6): [WriteCommand]s are sent to the
 * single write-actor and applied in their own transaction; [ReadCommand]s run inline on the
 * request thread against WAL. Deciding once, by subtype, keeps that routing type-driven.
 */
@Serializable
sealed interface Command

@Serializable
sealed interface ReadCommand : Command

@Serializable
sealed interface WriteCommand : Command

// ── Reads ────────────────────────────────────────────────────────────────────

/** The frontier (brief §4 / next.md). workspace required; track/segment/kind optional. */
@Serializable
data class Next(
    val workspaceId: Long,
    val trackId: Long? = null,
    val segmentId: Long? = null,
    val kindId: Long? = null,
    val limit: Int? = null,
) : ReadCommand

@Serializable
data object ListWorkspaces : ReadCommand

@Serializable
data class ListTracks(val workspaceId: Long) : ReadCommand

@Serializable
data class ListSegments(val trackId: Long) : ReadCommand

@Serializable
data class ListStatuses(val workspaceId: Long) : ReadCommand

@Serializable
data class ListKinds(val workspaceId: Long) : ReadCommand

/** Distinct free-text `relates_to.kind` values in live use (decision D6): a drift self-check, not a registry. */
@Serializable
data class ListRelatesKinds(val workspaceId: Long) : ReadCommand

@Serializable
data class ListTransitions(val workspaceId: Long) : ReadCommand

/** All live edges (blocks + relates_to) in a workspace — bulk read for graph export. */
@Serializable
data class ListEdges(val workspaceId: Long) : ReadCommand

/** Single task incl. embedded edges (decision D2). May return an archived row (decision D4). */
@Serializable
data class GetTask(val id: Long) : ReadCommand

/** Kanban data: a track's live tasks, optionally filtered to one status. */
@Serializable
data class ListTasks(val trackId: Long, val statusId: Long? = null) : ReadCommand

// ── Writes: registries & containers ──────────────────────────────────────────

/** Create workspace + seed default statuses/transitions + is_default in one txn (§3 bootstrap). */
@Serializable
data class CreateWorkspace(val name: String, val metadataJson: String = "{}") : WriteCommand

@Serializable
data class CreateStatus(
    val workspaceId: Long,
    val name: String,
    val kanbanOrder: Int = 0,
    val terminal: Boolean = false,
) : WriteCommand

/** Move the create-time default status (clear old + set new, one txn). */
@Serializable
data class SetDefaultStatus(val workspaceId: Long, val statusId: Long) : WriteCommand

@Serializable
data class CreateKind(val workspaceId: Long, val name: String) : WriteCommand

@Serializable
data class CreateTransition(val workspaceId: Long, val fromStatusId: Long, val toStatusId: Long) : WriteCommand

/** Create track + its auto root segment (#3). */
@Serializable
data class CreateTrack(
    val workspaceId: Long,
    val name: String,
    val description: String = "",
    val metadataJson: String = "{}",
) : WriteCommand

/** Create a nested filing segment. parentSegmentId null = directly under the track root. */
@Serializable
data class CreateSegment(val trackId: Long, val name: String, val parentSegmentId: Long? = null) : WriteCommand

// ── Writes: tasks ────────────────────────────────────────────────────────────

/**
 * Create a task. Exactly one of [segmentId] / [trackId] is set: a trackId routes to that
 * track's root segment (§5). workspace_id is derived from the segment's track (#8), never
 * supplied. statusId null lands on the live is_default status (§3 bootstrap).
 */
@Serializable
data class CreateTask(
    val segmentId: Long? = null,
    val trackId: Long? = null,
    val title: String,
    val description: String = "",
    val priority: Int = 0,
    val statusId: Long? = null,
    val kindId: Long? = null,
    val metadataJson: String = "{}",
) : WriteCommand

/** Status move; validates a live transition exists, CAS on the task version (§5/§6). */
@Serializable
data class MoveStatus(val taskId: Long, val toStatusId: Long, val expectedVersion: Int) : WriteCommand

/**
 * Edit an existing task; CAS on [expectedVersion] (§6). A non-null scalar updates that field;
 * the genuinely-nullable columns use explicit clear flags so "leave unchanged" (null) is
 * distinct from "set to null": [clearKind].
 */
@Serializable
data class EditTask(
    val taskId: Long,
    val expectedVersion: Int,
    val title: String? = null,
    val description: String? = null,
    val priority: Int? = null,
    val kindId: Long? = null,
    val clearKind: Boolean = false,
    val metadataJson: String? = null,
) : WriteCommand

// ── Writes: container/registry edits (versioned rows) ─────────────────────────

@Serializable
data class EditWorkspace(
    val id: Long,
    val expectedVersion: Int,
    val name: String? = null,
    val metadataJson: String? = null,
) : WriteCommand

@Serializable
data class EditTrack(
    val id: Long,
    val expectedVersion: Int,
    val name: String? = null,
    val description: String? = null,
    val metadataJson: String? = null,
) : WriteCommand

// ── Writes: edges ────────────────────────────────────────────────────────────

/** blocks edge (spine). DAG check (#1) + same-workspace (#7); workspace_id derived. */
@Serializable
data class AddBlocks(val sourceTaskId: Long, val targetTaskId: Long) : WriteCommand

/** relates_to edge (decorative). same-workspace (#7); workspace_id derived. */
@Serializable
data class AddRelates(val kind: String, val sourceTaskId: Long, val targetTaskId: Long) : WriteCommand

/** Remove a blocks edge by archiving the single live row (archive-only design). Un-gates the
 *  target in `next` via the same mechanism as #4. NotFound if no live edge for the pair. */
@Serializable
data class RemoveBlocks(val sourceTaskId: Long, val targetTaskId: Long) : WriteCommand

/** Remove a relates_to edge by archiving the single live row. Keyed on (kind, source, target). */
@Serializable
data class RemoveRelates(val kind: String, val sourceTaskId: Long, val targetTaskId: Long) : WriteCommand

// ── Writes: archives ─────────────────────────────────────────────────────────

@Serializable
data class ArchiveTask(val id: Long) : WriteCommand

/** Cascades the segment subtree (#6). A direct root-segment archive is rejected (Validation). */
@Serializable
data class ArchiveSegment(val id: Long) : WriteCommand

/** Cascades segments + tasks + edges (#6). */
@Serializable
data class ArchiveTrack(val id: Long) : WriteCommand

/** Cascades down through tracks (#6). */
@Serializable
data class ArchiveWorkspace(val id: Long) : WriteCommand

/** #9: rejected while any live task is in it; cascades incident transitions; default rejected. */
@Serializable
data class ArchiveStatus(val workspaceId: Long, val statusId: Long) : WriteCommand

/** #9: null-cascades kind_id=NULL on referencing live tasks, then archives the kind. */
@Serializable
data class ArchiveKind(val workspaceId: Long, val kindId: Long) : WriteCommand
