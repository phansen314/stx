package stx.service

import stx.repo.BlocksRepo
import stx.repo.SegmentRepo
import java.sql.Connection

/**
 * Graph invariants SQLite cannot express (brief §3). Each is a small, transactional check the
 * service runs before a write. Acyclicity uses live edges only — the archive-cascade invariant
 * guarantees a live edge always joins two live tasks, so we never inspect archived rows here.
 */
object Invariants {

    /**
     * Invariant 1 — `blocks` is a DAG. Adding source→target (source blocks target) creates a
     * cycle iff target can already reach source along live blocks edges. Returns true if the
     * edge would introduce a cycle.
     */
    fun blocksWouldCycle(conn: Connection, workspaceId: Long, source: Long, target: Long): Boolean {
        if (source == target) return true
        val adj = HashMap<Long, MutableList<Long>>()
        for ((s, t) in BlocksRepo.liveEdges(conn, workspaceId)) {
            adj.getOrPut(s) { mutableListOf() }.add(t)
        }
        val seen = HashSet<Long>()
        val stack = ArrayDeque<Long>()
        stack.addLast(target)
        while (stack.isNotEmpty()) {
            val n = stack.removeLast()
            if (n == source) return true
            if (!seen.add(n)) continue
            adj[n]?.forEach { stack.addLast(it) }
        }
        return false
    }

    /**
     * Invariant 2 — the segment tree is acyclic within a track. Reparenting `segmentId` under
     * `newParentId` creates a cycle iff the segment is itself an ancestor (or equal) of the new
     * parent. Walks ancestors of the proposed parent.
     */
    fun segmentReparentWouldCycle(conn: Connection, segmentId: Long, newParentId: Long?): Boolean {
        if (newParentId == null) return false
        if (newParentId == segmentId) return true
        var cur: Long? = newParentId
        val seen = HashSet<Long>()
        while (cur != null) {
            if (cur == segmentId) return true
            if (!seen.add(cur)) break
            cur = SegmentRepo.get(conn, cur)?.parentSegmentId
        }
        return false
    }
}
