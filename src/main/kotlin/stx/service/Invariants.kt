package stx.service

import stx.dto.TaskDto
import stx.error.StxError
import stx.repo.BlocksRepo
import stx.repo.TaskRepo
import stx.repo.bool
import stx.repo.queryOne
import tech.codingzen.res.Res
import tech.codingzen.res.rail
import java.sql.Connection

/**
 * Reusable daemon invariants and small guards (brief §3). Each returns `Res<…, StxError>` so
 * callers `bind()` them inside a command's `rail { }`; a rejected invariant is a typed Failure,
 * never a thrown exception. Notes on coverage at this verb surface:
 *  - #2 (segment-tree acyclic) and #5 (segment.track_id immutable) are enforced by the ABSENCE
 *    of any reparent / move-segment / track-id mutation: a segment's parent and track are set
 *    only at create (where the new node has no descendants, so no cycle is possible) and never
 *    updated. [segmentReparentWouldCycle] is provided for the day a move-segment verb lands.
 */

/** Load a task that must be visible (live row + live container chain). NotFound vs Gone per D4. */
fun loadVisibleTask(c: Connection, id: Long): Res<TaskDto, StxError> = rail {
    val row = TaskRepo.getById(c, id) ?: raise(StxError.NotFound("task", id))
    if (row.archived) raise(StxError.Gone("task", id))
    // Live row but invisible => an archived ancestor/container (orphan): treat as does-not-exist.
    TaskRepo.getVisible(c, id) ?: raise(StxError.Gone("task", id))
}

/**
 * #1 blocks-DAG: would adding source->target create a cycle? True iff target can already reach
 * source over live blocks edges (a path target->…->source), or it is a self-edge. BFS over
 * live adjacency; the graph is small (solo-dev scale).
 */
fun blocksWouldCycle(c: Connection, source: Long, target: Long): Boolean {
    if (source == target) return true
    val seen = HashSet<Long>()
    val queue = ArrayDeque<Long>()
    queue += target
    while (queue.isNotEmpty()) {
        val node = queue.removeFirst()
        if (!seen.add(node)) continue
        if (node == source) return true
        queue += BlocksRepo.liveTargetsOf(c, node)
    }
    return false
}

/** #2 (future move-segment only): would reparenting [segmentId] under [newParentId] create a
 *  cycle? True iff newParent is in the subtree of segment, or is the segment itself. */
fun segmentReparentWouldCycle(c: Connection, segmentId: Long, newParentId: Long): Boolean =
    newParentId == segmentId || newParentId in stx.repo.SegmentRepo.liveSubtreeIds(c, segmentId)

/** (archived, version) of a versioned row (task/track/workspace), or null if the row is absent. */
fun readArchivedVersion(c: Connection, table: String, id: Long): Pair<Boolean, Int>? =
    c.queryOne("SELECT archived, version FROM $table WHERE id=?", id) { it.bool("archived") to it.getInt("version") }

/**
 * Interpret an optimistic-lock CAS result (brief §6): changes()==1 is success; changes()==0
 * re-reads to decide whether the row is gone, missing, or simply stale (VersionConflict).
 */
fun interpretCas(c: Connection, table: String, entity: String, id: Long, expected: Int, changes: Int): Res<Unit, StxError> = rail {
    if (changes == 1) return@rail Unit
    val (archived, actual) = readArchivedVersion(c, table, id) ?: raise(StxError.NotFound(entity, id))
    if (archived) raise(StxError.Gone(entity, id))
    raise(StxError.VersionConflict(entity, id, expected, actual))
}
