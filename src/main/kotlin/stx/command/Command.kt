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
    /**
     * The calling agent's identity, if it has one. A live lease held by *another* agent always
     * hides a task; naming yourself keeps the work you already reserved visible, so an agent that
     * claimed five tasks doesn't then read an empty frontier and look idle.
     */
    val asAgent: String? = null,
) : ReadCommand

/**
 * The inverse of [Next] (next.md "Deferred → built"): what unfinished work is holding [taskId]
 * back, walked transitively backward along `blocks`. [maxDepth] is a defense-in-depth bound —
 * `blocks` is a DAG by invariant #1, so it can only ever bite if that invariant is broken.
 * It must be >= 1 (the service rejects less): the CTE's base case is unconditional, so a 0 or
 * negative cap would silently behave as 1 rather than returning nothing.
 */
@Serializable
data class ListBlockers(val taskId: Long, val maxDepth: Int = DEFAULT_BLOCKER_DEPTH) : ReadCommand

const val DEFAULT_BLOCKER_DEPTH = 64

/** Live leases in a workspace — the human-facing "who is on what". Expired leases are not rows. */
@Serializable
data class ListClaims(val workspaceId: Long) : ReadCommand

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
 * Claim-if-free: reserve [taskId] for [agentId] until now + [ttlSeconds] (schema.sql, "AGENT
 * CLAIM / LEASE"). Wins if the task is free, its lease has expired, or [agentId] already holds it —
 * that last arm is what makes this double as renew/heartbeat, so the framework needs no second
 * verb. Losing returns [stx.error.StxError.Claimed] naming the current holder and expiry.
 *
 * The daemon computes the expiry from the caller's TTL rather than accepting an absolute timestamp:
 * *how long* to reserve is the framework's policy, but the clock the comparison uses must be the
 * clock that set it, or a format/zone slip silently yields a lease that never expires.
 *
 * Deliberately does NOT touch `version`/`updated_at` — a lease is a reservation, not a content
 * edit, and sharing the OL token would make one agent's claim another agent's spurious 409.
 */
@Serializable
data class ClaimTask(val taskId: Long, val agentId: String, val ttlSeconds: Long) : WriteCommand

/**
 * Release a lease. Only the holder may release a *live* lease; a task that is free, or whose lease
 * has already expired, is a successful no-op — that is the shape a crash-recovering agent needs.
 */
@Serializable
data class ReleaseTask(val taskId: Long, val agentId: String) : WriteCommand

/**
 * Fused next-and-claim: compute the frontier and reserve what it returns, in ONE transaction, so
 * two agents can never be handed the same task. A [WriteCommand] (POST) rather than a flag on the
 * `next` read — a GET that mutates breaks the read path's snapshot contract.
 *
 * Reuses [Frontier][stx.service.Frontier] verbatim rather than reimplementing the eligibility
 * predicate — the same discipline decision D8 applied to `blockers`.
 */
@Serializable
data class NextAndClaim(
    val workspaceId: Long,
    val agentId: String,
    val ttlSeconds: Long,
    val trackId: Long? = null,
    val segmentId: Long? = null,
    val kindId: Long? = null,
    val limit: Int? = null,
) : WriteCommand

/**
 * Refile a task under a different segment — a move through the *filing* tree, orthogonal to
 * [MoveStatus]'s move through the kanban. CAS on [expectedVersion] (§6), like every task write.
 *
 * The target segment must sit in the SAME workspace: `task.workspace_id` is denormalized from the
 * container chain (#8) and every incident edge is workspace-local (#7), so a cross-workspace
 * refile would strand both. Cross-*track* refiling is fine — a task's blockers may live in another
 * track by design (next.md, "Cross-track blockers"), so no edge needs touching.
 */
@Serializable
data class RefileTask(val taskId: Long, val segmentId: Long, val expectedVersion: Int) : WriteCommand

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

// ── Writes: container/registry edits ─────────────────────────────────────────
//
// workspace/track carry a version column, so their edits CAS like a task's. segment/status/kind
// do NOT (schema.sql: only workspace/track/task are versioned) — their edits are plain writes,
// same as [SetDefaultStatus] and the archives. Serialization through the single write-actor is
// what orders them; there is no lost-update to guard because there is no read-modify-write in
// the client for these (each edit names its new value outright).

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

/**
 * Rename and/or reparent a filing segment. Unversioned (see section note).
 *
 * A reparent is where invariants #2 and #5 stop being enforced by the mere *absence* of a
 * mutation: the new parent must be live, must belong to the SAME track (#5 — `segment.track_id`
 * is immutable; moving work across tracks is [RefileTask]'s job, per task), and must not sit in
 * the moved segment's own subtree (#2 — `segmentReparentWouldCycle`). The synthetic root segment
 * has no parent to change (`ux_segment_one_root` keeps its `parent_segment_id` NULL), so a
 * reparent of a root is rejected; renaming one is fine.
 *
 * Both fields null is a no-op that returns the row — segment names are not unique by design, so
 * there is nothing to CAS or clash on.
 */
@Serializable
data class EditSegment(val segmentId: Long, val name: String? = null, val parentSegmentId: Long? = null) : WriteCommand

/** Rename a status and/or change its kanban_order (display only). `terminal` is deliberately NOT
 *  editable: flipping it retroactively redefines which existing tasks count as done and silently
 *  rewrites the frontier. Unversioned (see section note). */
@Serializable
data class EditStatus(
    val workspaceId: Long,
    val statusId: Long,
    val name: String? = null,
    val kanbanOrder: Int? = null,
) : WriteCommand

/**
 * Set the whole kanban order in one txn: the listed statuses take positions `0..n-1` in the given
 * order, and any live status left out keeps its relative order behind them. A partial list is
 * therefore a "float these to the front" move, which is how the order is usually adjusted.
 */
@Serializable
data class ReorderStatuses(val workspaceId: Long, val statusIds: List<Long>) : WriteCommand

/** Rename a kind. The registry is what makes `next --kind` trustworthy, so the rename takes the
 *  same case-insensitive duplicate rejection as [CreateKind]. Unversioned (see section note). */
@Serializable
data class EditKind(val workspaceId: Long, val kindId: Long, val name: String) : WriteCommand

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
