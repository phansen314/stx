package stx

import stx.command.AddBlocks
import stx.command.AddRelatesTo
import stx.command.ArchiveTrack
import stx.command.ArchiveWorkspace
import stx.command.CreateSegment
import stx.command.DeleteMetaKey
import stx.command.MetaEntity
import stx.command.MoveTaskToSegment
import stx.command.RenameSegment
import stx.command.SetMetaKey
import stx.command.UpdateTask
import stx.command.TaskPatch
import stx.repo.BlocksRepo
import stx.repo.RelatesRepo
import stx.repo.SegmentRepo
import stx.repo.TaskRepo
import stx.service.Frontier
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Covers the v3 CRUD extensions: CAS, archive cascades, task refiling, segment rename, per-key meta. */
class CrudExtensionsTest {
    private val h = Harness()

    @AfterTest fun cleanup() = h.close()

    private fun fixture(): Triple<Long, Long, Long> {
        val ws = h.seedWorkspace()
        val todo = h.seedStatus(ws, "todo")
        val track = h.seedTrack(ws, "auth")
        return Triple(ws, todo, h.rootSegment(track))
    }

    // ── CAS / optimistic locking ─────────────────────────────────────────────────
    @Test fun `stale expectedVersion is a conflict, current version succeeds`() {
        val (_, todo, seg) = fixture()
        val id = h.seedTask(seg, todo, "a")
        assertEquals(0, TaskRepo.get(h.conn, id)!!.version, "fresh row starts at version 0")

        // Matching version succeeds and bumps the token.
        h.exec<Task>(UpdateTask(id, TaskPatch(title = "a1"), expectedVersion = 0))
        assertEquals(1, TaskRepo.get(h.conn, id)!!.version)

        // The same (now stale) expectedVersion is rejected.
        assertFailsWith<StxException.Conflict> {
            h.exec<Task>(UpdateTask(id, TaskPatch(title = "a2"), expectedVersion = 0))
        }
        // The current version goes through.
        h.exec<Task>(UpdateTask(id, TaskPatch(title = "a2"), expectedVersion = 1))
        assertEquals("a2", TaskRepo.get(h.conn, id)!!.title)
    }

    @Test fun `null expectedVersion skips the CAS check`() {
        val (_, todo, seg) = fixture()
        val id = h.seedTask(seg, todo, "a")
        // No version supplied → unconditional write, version still advances.
        h.exec<Task>(UpdateTask(id, TaskPatch(priority = 5)))
        h.exec<Task>(UpdateTask(id, TaskPatch(priority = 6)))
        assertEquals(2, TaskRepo.get(h.conn, id)!!.version)
    }

    // ── archive cascades ───────────────────────────────────────────────────────────
    @Test fun `archiving a track cascades to its segments, tasks and edges`() {
        val ws = h.seedWorkspace()
        val todo = h.seedStatus(ws, "todo")
        val track = h.seedTrack(ws, "auth")
        val root = h.rootSegment(track)
        val child = h.exec<Segment>(CreateSegment(track, "child", parentSegmentId = root)).id
        val a = h.seedTask(root, todo, "a")
        val b = h.seedTask(child, todo, "b")
        val blk = h.exec<Blocks>(AddBlocks(a, b))
        val rel = h.exec<RelatesTo>(AddRelatesTo("relates", a, b))

        h.exec<Track>(ArchiveTrack(track))

        assertTrue(SegmentRepo.get(h.conn, root)!!.archived, "root segment archived")
        assertTrue(SegmentRepo.get(h.conn, child)!!.archived, "child segment archived")
        assertTrue(TaskRepo.get(h.conn, a)!!.archived, "task a archived")
        assertTrue(TaskRepo.get(h.conn, b)!!.archived, "task b archived")
        assertTrue(BlocksRepo.get(h.conn, blk.id)!!.archived, "incident blocks archived")
        assertTrue(RelatesRepo.get(h.conn, rel.id)!!.archived, "incident relates archived")
        // Frontier no longer surfaces tasks of an archived track.
        assertTrue(Frontier().next(h.conn, ws).isEmpty(), "no live tasks remain in the frontier")
    }

    @Test fun `archiving a workspace cascades to every child`() {
        val ws = h.seedWorkspace()
        val todo = h.seedStatus(ws, "todo")
        val track = h.seedTrack(ws, "auth")
        val seg = h.rootSegment(track)
        val t = h.seedTask(seg, todo, "a")

        h.exec<Workspace>(ArchiveWorkspace(ws))

        assertTrue(TaskRepo.get(h.conn, t)!!.archived)
        assertTrue(SegmentRepo.get(h.conn, seg)!!.archived)
        assertTrue(Frontier().next(h.conn, ws).isEmpty())
    }

    // ── refile a task under a different segment ──────────────────────────────────────
    @Test fun `moving a task to another segment updates its parent`() {
        val (_, todo, root) = fixture()
        val track = SegmentRepo.get(h.conn, root)!!.trackId
        val other = h.exec<Segment>(CreateSegment(track, "other", parentSegmentId = root)).id
        val t = h.seedTask(root, todo, "a")

        val moved = h.exec<Task>(MoveTaskToSegment(t, other))
        assertEquals(other, moved.segmentId)
    }

    @Test fun `moving a task across workspaces is rejected`() {
        val (_, todo, root) = fixture()
        val t = h.seedTask(root, todo, "a")
        // A segment in a different workspace.
        val ws2 = h.seedWorkspace("ws2")
        val track2 = h.seedTrack(ws2, "t2")
        val seg2 = h.rootSegment(track2)
        assertFailsWith<StxException.Validation> { h.exec<Task>(MoveTaskToSegment(t, seg2)) }
    }

    // ── segment rename ───────────────────────────────────────────────────────────
    @Test fun `renaming a segment changes its name, blank rejected`() {
        val (_, _, root) = fixture()
        val track = SegmentRepo.get(h.conn, root)!!.trackId
        val seg = h.exec<Segment>(CreateSegment(track, "old", parentSegmentId = root)).id
        val renamed = h.exec<Segment>(RenameSegment(seg, "new"))
        assertEquals("new", renamed.name)
        assertFailsWith<StxException.Validation> { h.exec<Segment>(RenameSegment(seg, "  ")) }
    }

    // ── per-key metadata ───────────────────────────────────────────────────────────
    @Test fun `set then delete a single metadata key, keys lowercased`() {
        val (_, todo, seg) = fixture()
        val id = h.seedTask(seg, todo, "a")
        h.exec<Task>(SetMetaKey(MetaEntity.TASK, id, "jira_key", "AUTH-1"))
        h.exec<Task>(SetMetaKey(MetaEntity.TASK, id, "Owner", "pat")) // mixed case → lowercased
        val withMeta = TaskRepo.get(h.conn, id)!!.metadata
        assertEquals("AUTH-1", withMeta["jira_key"])
        assertEquals("pat", withMeta["owner"])

        h.exec<Task>(DeleteMetaKey(MetaEntity.TASK, id, "JIRA_KEY"))
        val after = TaskRepo.get(h.conn, id)!!.metadata
        assertNull(after["jira_key"], "deleted key gone")
        assertEquals("pat", after["owner"], "sibling key untouched")
    }

    // ── edge reads ─────────────────────────────────────────────────────────────────
    @Test fun `incident edge reads return both directions`() {
        val (_, todo, seg) = fixture()
        val a = h.seedTask(seg, todo, "a")
        val b = h.seedTask(seg, todo, "b")
        h.exec<Blocks>(AddBlocks(a, b)) // a blocks b
        // Both endpoints see the incident blocks edge.
        assertEquals(1, BlocksRepo.listIncident(h.conn, a).size)
        assertEquals(1, BlocksRepo.listIncident(h.conn, b).size)
    }
}
