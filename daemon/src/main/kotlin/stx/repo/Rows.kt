package stx.repo

import stx.Blocks
import stx.RelatesTo
import stx.Segment
import stx.Status
import stx.StatusTransition
import stx.Task
import stx.Track
import stx.Workspace
import stx.support.MetadataCodec
import java.sql.Connection
import java.sql.ResultSet
import java.sql.Statement

// ── ResultSet helpers ──────────────────────────────────────────────────────────
internal fun ResultSet.bool(col: String): Boolean = getInt(col) != 0
internal fun ResultSet.longOrNull(col: String): Long? = getLong(col).let { if (wasNull()) null else it }
internal fun ResultSet.intOrNull(col: String): Int? = getInt(col).let { if (wasNull()) null else it }

/** Execute an INSERT and return the autoincrement rowid. */
internal fun Connection.insertReturningId(sql: String, bind: (java.sql.PreparedStatement) -> Unit): Long {
    prepareStatement(sql, Statement.RETURN_GENERATED_KEYS).use { ps ->
        bind(ps)
        ps.executeUpdate()
        ps.generatedKeys.use { keys ->
            require(keys.next()) { "insert produced no generated key" }
            return keys.getLong(1)
        }
    }
}

// ── row → entity mappers ─────────────────────────────────────────────────────────
internal fun ResultSet.toWorkspace() = Workspace(
    id = getLong("id"),
    name = getString("name"),
    metadata = MetadataCodec.decode(getString("metadata_json")),
    version = getLong("version"),
    archived = bool("archived"),
    createdAt = getString("created_at"),
    updatedAt = getString("updated_at"),
)

internal fun ResultSet.toStatus() = Status(
    id = getLong("id"),
    workspaceId = getLong("workspace_id"),
    name = getString("name"),
    kanbanOrder = getInt("kanban_order"),
    terminal = bool("terminal"),
    version = getLong("version"),
    archived = bool("archived"),
    createdAt = getString("created_at"),
)

internal fun ResultSet.toTransition() = StatusTransition(
    id = getLong("id"),
    workspaceId = getLong("workspace_id"),
    fromStatusId = getLong("from_status_id"),
    toStatusId = getLong("to_status_id"),
    version = getLong("version"),
    archived = bool("archived"),
)

internal fun ResultSet.toTrack() = Track(
    id = getLong("id"),
    workspaceId = getLong("workspace_id"),
    name = getString("name"),
    description = getString("description"),
    metadata = MetadataCodec.decode(getString("metadata_json")),
    version = getLong("version"),
    archived = bool("archived"),
    createdAt = getString("created_at"),
    updatedAt = getString("updated_at"),
)

internal fun ResultSet.toSegment() = Segment(
    id = getLong("id"),
    workspaceId = getLong("workspace_id"),
    trackId = getLong("track_id"),
    parentSegmentId = longOrNull("parent_segment_id"),
    name = getString("name"),
    isRoot = bool("is_root"),
    version = getLong("version"),
    archived = bool("archived"),
    createdAt = getString("created_at"),
)

internal fun ResultSet.toTask() = Task(
    id = getLong("id"),
    workspaceId = getLong("workspace_id"),
    segmentId = getLong("segment_id"),
    statusId = getLong("status_id"),
    kind = getString("kind"),
    title = getString("title"),
    description = getString("description"),
    priority = getInt("priority"),
    dueDate = getString("due_date"),
    startDate = getString("start_date"),
    finishDate = getString("finish_date"),
    metadata = MetadataCodec.decode(getString("metadata_json")),
    version = getLong("version"),
    archived = bool("archived"),
    createdAt = getString("created_at"),
    updatedAt = getString("updated_at"),
)

internal fun ResultSet.toBlocks() = Blocks(
    id = getLong("id"),
    workspaceId = getLong("workspace_id"),
    sourceTaskId = getLong("source_task_id"),
    targetTaskId = getLong("target_task_id"),
    metadata = MetadataCodec.decode(getString("metadata_json")),
    version = getLong("version"),
    archived = bool("archived"),
    createdAt = getString("created_at"),
)

internal fun ResultSet.toRelatesTo() = RelatesTo(
    id = getLong("id"),
    workspaceId = getLong("workspace_id"),
    kind = getString("kind"),
    sourceTaskId = getLong("source_task_id"),
    targetTaskId = getLong("target_task_id"),
    metadata = MetadataCodec.decode(getString("metadata_json")),
    version = getLong("version"),
    archived = bool("archived"),
    createdAt = getString("created_at"),
)

/** Run a query and map the first row, or null. */
internal fun <T> Connection.queryOne(sql: String, vararg args: Any?, map: (ResultSet) -> T): T? {
    prepareStatement(sql).use { ps ->
        args.forEachIndexed { i, a -> ps.setObject(i + 1, a) }
        ps.executeQuery().use { rs -> return if (rs.next()) map(rs) else null }
    }
}

/** Run a query and map all rows. */
internal fun <T> Connection.queryAll(sql: String, vararg args: Any?, map: (ResultSet) -> T): List<T> {
    prepareStatement(sql).use { ps ->
        args.forEachIndexed { i, a -> ps.setObject(i + 1, a) }
        ps.executeQuery().use { rs ->
            val out = ArrayList<T>()
            while (rs.next()) out.add(map(rs))
            return out
        }
    }
}

/**
 * Optimistic-lock helpers. When a caller passes a non-null `expectedVersion`, write SQL appends
 * `AND version=?` and binds the expected value; null means "no CAS guard" (unconditional write).
 * Every versioned write also does `version=version+1` in its SET clause (callers add that).
 */
internal fun versionClause(expectedVersion: Long?): String = if (expectedVersion != null) " AND version=?" else ""
internal fun versionArg(expectedVersion: Long?): Array<Any?> =
    if (expectedVersion != null) arrayOf(expectedVersion) else emptyArray()

/** `?,?,?` placeholders for an `IN (...)` clause of [n] elements. */
internal fun inPlaceholders(n: Int): String = List(n) { "?" }.joinToString(",")

/** Run an UPDATE/DELETE-style statement and return affected row count. */
internal fun Connection.exec(sql: String, vararg args: Any?): Int {
    prepareStatement(sql).use { ps ->
        args.forEachIndexed { i, a -> ps.setObject(i + 1, a) }
        return ps.executeUpdate()
    }
}
