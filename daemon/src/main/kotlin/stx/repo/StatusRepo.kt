package stx.repo

import stx.Status
import stx.StatusTransition
import java.sql.Connection

object StatusRepo {
    fun insert(conn: Connection, workspaceId: Long, name: String, terminal: Boolean, kanbanOrder: Int): Long =
        conn.insertReturningId(
            "INSERT INTO status(workspace_id, name, terminal, kanban_order) VALUES(?, ?, ?, ?)",
        ) { ps ->
            ps.setLong(1, workspaceId); ps.setString(2, name)
            ps.setInt(3, if (terminal) 1 else 0); ps.setInt(4, kanbanOrder)
        }

    fun get(conn: Connection, id: Long): Status? =
        conn.queryOne("SELECT * FROM status WHERE id=?", id) { it.toStatus() }

    fun listByWorkspace(conn: Connection, workspaceId: Long, includeArchived: Boolean): List<Status> =
        conn.queryAll(
            "SELECT * FROM status WHERE workspace_id=?" + (if (includeArchived) "" else " AND archived=0") +
                " ORDER BY kanban_order ASC, id ASC",
            workspaceId,
        ) { it.toStatus() }

    fun update(conn: Connection, id: Long, name: String?, terminal: Boolean?, kanbanOrder: Int?): Int {
        val sets = mutableListOf<String>()
        val args = mutableListOf<Any?>()
        if (name != null) { sets += "name=?"; args += name }
        if (terminal != null) { sets += "terminal=?"; args += if (terminal) 1 else 0 }
        if (kanbanOrder != null) { sets += "kanban_order=?"; args += kanbanOrder }
        if (sets.isEmpty()) return 0
        args += id
        return conn.exec("UPDATE status SET ${sets.joinToString(", ")} WHERE id=?", *args.toTypedArray())
    }

    fun archive(conn: Connection, id: Long): Int =
        conn.exec("UPDATE status SET archived=1 WHERE id=?", id)

    /** Live terminal status ids for a workspace — used by the frontier query. */
    fun terminalIds(conn: Connection, workspaceId: Long): List<Long> =
        conn.queryAll(
            "SELECT id FROM status WHERE workspace_id=? AND terminal=1 AND archived=0",
            workspaceId,
        ) { it.getLong("id") }
}

object TransitionRepo {
    fun insert(conn: Connection, workspaceId: Long, fromStatusId: Long, toStatusId: Long): Long =
        conn.insertReturningId(
            "INSERT INTO status_transition(workspace_id, from_status_id, to_status_id) VALUES(?, ?, ?)",
        ) { ps -> ps.setLong(1, workspaceId); ps.setLong(2, fromStatusId); ps.setLong(3, toStatusId) }

    fun get(conn: Connection, id: Long): StatusTransition? =
        conn.queryOne("SELECT * FROM status_transition WHERE id=?", id) { it.toTransition() }

    fun listByWorkspace(conn: Connection, workspaceId: Long): List<StatusTransition> =
        conn.queryAll(
            "SELECT * FROM status_transition WHERE workspace_id=? AND archived=0 ORDER BY id ASC",
            workspaceId,
        ) { it.toTransition() }

    /** Does a live transition from→to exist in this workspace? */
    fun exists(conn: Connection, workspaceId: Long, fromStatusId: Long, toStatusId: Long): Boolean =
        conn.queryOne(
            "SELECT 1 FROM status_transition " +
                "WHERE workspace_id=? AND from_status_id=? AND to_status_id=? AND archived=0",
            workspaceId, fromStatusId, toStatusId,
        ) { true } ?: false

    fun archive(conn: Connection, id: Long): Int =
        conn.exec("UPDATE status_transition SET archived=1 WHERE id=?", id)
}
