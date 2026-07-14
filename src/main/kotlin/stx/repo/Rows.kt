package stx.repo

import stx.dto.BlocksDto
import stx.dto.KindDto
import stx.dto.RelatesDto
import stx.dto.SegmentDto
import stx.dto.StatusDto
import stx.dto.TaskDto
import stx.dto.TrackDto
import stx.dto.TransitionDto
import stx.dto.WorkspaceDto
import stx.error.StxError
import tech.codingzen.res.Res
import tech.codingzen.res.catching
import tech.codingzen.res.defectOrNull
import tech.codingzen.res.fail
import java.sql.Connection
import java.sql.PreparedStatement
import java.sql.ResultSet
import java.sql.SQLException
import java.sql.Statement

// ── JDBC edge: throw -> Res, with UNIQUE-violation mapped to a typed Duplicate ─────────────
//
// Brief §1b: adapt throwing JDBC at the boundary. We run the op inside railway's `catching`
// (any throw -> Defect rail), then re-tag a UNIQUE-constraint Defect as a typed Duplicate
// Failure. Other constraint failures (FK/CHECK) indicate a daemon-side bug — the relevant
// invariant should have rejected first — so they stay Defects (-> 500), surfacing the bug.

fun <S> sql(entity: String, detail: String = "unique constraint", block: () -> S): Res<S, StxError> {
    val r: Res<S, StxError> = catching { block() }
    val d = r.defectOrNull()
    return if (d is SQLException && isUniqueViolation(d)) fail(StxError.Duplicate(entity, detail)) else r
}

private fun isUniqueViolation(e: SQLException): Boolean =
    e.message?.contains("UNIQUE constraint failed", ignoreCase = true) == true

// ── Tiny query helpers (the only place raw JDBC lives) ─────────────────────────────────────

private fun PreparedStatement.bindAll(params: List<Any?>) {
    params.forEachIndexed { i, p ->
        val idx = i + 1
        when (p) {
            null -> setObject(idx, null)
            is Boolean -> setInt(idx, if (p) 1 else 0)
            is Int -> setInt(idx, p)
            is Long -> setLong(idx, p)
            is String -> setString(idx, p)
            else -> setObject(idx, p)
        }
    }
}

fun <T> Connection.queryList(sqlText: String, vararg params: Any?, map: (ResultSet) -> T): List<T> =
    prepareStatement(sqlText).use { ps ->
        ps.bindAll(params.toList())
        ps.executeQuery().use { rs -> buildList { while (rs.next()) add(map(rs)) } }
    }

fun <T> Connection.queryOne(sqlText: String, vararg params: Any?, map: (ResultSet) -> T): T? =
    prepareStatement(sqlText).use { ps ->
        ps.bindAll(params.toList())
        ps.executeQuery().use { rs -> if (rs.next()) map(rs) else null }
    }

fun Connection.exec(sqlText: String, vararg params: Any?): Int =
    prepareStatement(sqlText).use { ps -> ps.bindAll(params.toList()); ps.executeUpdate() }

fun Connection.insertReturningId(sqlText: String, vararg params: Any?): Long =
    prepareStatement(sqlText, Statement.RETURN_GENERATED_KEYS).use { ps ->
        ps.bindAll(params.toList())
        ps.executeUpdate()
        ps.generatedKeys.use { if (it.next()) it.getLong(1) else error("no generated key for: $sqlText") }
    }

// ── ResultSet helpers ──────────────────────────────────────────────────────────────────────

fun ResultSet.bool(col: String): Boolean = getInt(col) != 0

fun ResultSet.longOrNull(col: String): Long? = getLong(col).let { if (wasNull()) null else it }

// ── Row mappers (column names mirror schema.sql) ─────────────────────────────────────────────

fun ResultSet.toWorkspace() = WorkspaceDto(
    id = getLong("id"), name = getString("name"), metadataJson = getString("metadata_json"),
    archived = bool("archived"), version = getInt("version"),
    createdAt = getString("created_at"), updatedAt = getString("updated_at"),
)

fun ResultSet.toStatus() = StatusDto(
    id = getLong("id"), workspaceId = getLong("workspace_id"), name = getString("name"),
    kanbanOrder = getInt("kanban_order"), terminal = bool("terminal"), isDefault = bool("is_default"),
    archived = bool("archived"), createdAt = getString("created_at"),
)

fun ResultSet.toTransition() = TransitionDto(
    id = getLong("id"), workspaceId = getLong("workspace_id"),
    fromStatusId = getLong("from_status_id"), toStatusId = getLong("to_status_id"), archived = bool("archived"),
)

fun ResultSet.toTrack() = TrackDto(
    id = getLong("id"), workspaceId = getLong("workspace_id"), name = getString("name"),
    description = getString("description"), metadataJson = getString("metadata_json"),
    archived = bool("archived"), version = getInt("version"),
    createdAt = getString("created_at"), updatedAt = getString("updated_at"),
)

fun ResultSet.toSegment() = SegmentDto(
    id = getLong("id"), workspaceId = getLong("workspace_id"), trackId = getLong("track_id"),
    parentSegmentId = longOrNull("parent_segment_id"), name = getString("name"),
    isRoot = bool("is_root"), archived = bool("archived"), createdAt = getString("created_at"),
)

fun ResultSet.toKind() = KindDto(
    id = getLong("id"), workspaceId = getLong("workspace_id"), name = getString("name"),
    archived = bool("archived"), createdAt = getString("created_at"),
)

fun ResultSet.toTask() = TaskDto(
    id = getLong("id"), workspaceId = getLong("workspace_id"), segmentId = getLong("segment_id"),
    statusId = getLong("status_id"), kindId = longOrNull("kind_id"),
    title = getString("title"), description = getString("description"), priority = getInt("priority"),
    metadataJson = getString("metadata_json"), archived = bool("archived"), version = getInt("version"),
    createdAt = getString("created_at"), updatedAt = getString("updated_at"),
)

fun ResultSet.toBlocks() = BlocksDto(
    id = getLong("id"), workspaceId = getLong("workspace_id"),
    sourceTaskId = getLong("source_task_id"), targetTaskId = getLong("target_task_id"), archived = bool("archived"),
)

fun ResultSet.toRelates() = RelatesDto(
    id = getLong("id"), workspaceId = getLong("workspace_id"), kind = getString("kind"),
    sourceTaskId = getLong("source_task_id"), targetTaskId = getLong("target_task_id"), archived = bool("archived"),
)
