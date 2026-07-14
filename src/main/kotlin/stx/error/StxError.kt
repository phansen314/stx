package stx.error

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * The single Failure type (`F`) for every command's `Res<S, StxError>` (brief §1b).
 * These are *expected* domain rejections — values in the type, never thrown. Genuine bugs
 * surface on railway's Defect rail (a Throwable) and map to 500 at the HTTP edge (§5).
 *
 * [code] is the HTTP status each variant maps to; [toJson] is the structured error body.
 * Kept free of any http4k dependency so the transport layer owns the framework coupling.
 */
sealed interface StxError {
    /** No live row with this id. -> 404 */
    data class NotFound(val entity: String, val id: Long) : StxError

    /** Row exists but is archived; a mutation/live-only read targeted it. -> 410 */
    data class Gone(val entity: String, val id: Long) : StxError

    /** Edge would create a cycle: blocks-DAG (#1) or segment-tree (#2). -> 409 */
    data class CycleRejected(val edge: String, val source: Long, val target: Long) : StxError

    /** Cross-row reference spans workspaces: edges (#7) or any FK write (#8). -> 409 */
    data class CrossWorkspace(val source: Long, val target: Long) : StxError

    /** Status move with no live status_transition row. -> 409 */
    data class IllegalTransition(val taskId: Long, val from: Long, val to: Long) : StxError

    /** Attempt to mutate an immutable field, e.g. segment.track_id (#5). -> 409 */
    data class ImmutableField(val entity: String, val field: String) : StxError

    /** Live unique-index clash (duplicate name / edge). -> 409 */
    data class Duplicate(val entity: String, val detail: String) : StxError

    /** Optimistic-lock CAS failed: the row moved since the caller read it. -> 409 */
    data class VersionConflict(val entity: String, val id: Long, val expected: Int, val actual: Int) : StxError

    /** Bad input or a rejected-by-rule mutation (root-segment archive, default-status archive,
     *  status-archive-while-referenced #9, …). -> 400 */
    data class Validation(val message: String) : StxError

    /** The HTTP status code this variant maps to (§5). */
    val code: Int
        get() = when (this) {
            is NotFound -> 404
            is Gone -> 410
            is CycleRejected, is CrossWorkspace, is IllegalTransition,
            is ImmutableField, is Duplicate, is VersionConflict -> 409
            is Validation -> 400
        }

    /** The variant's simple name, used as the `error` discriminator in the body. */
    val variant: String get() = this::class.simpleName ?: "StxError"

    /** Structured JSON error body: `{ "error": "<variant>", ...fields }` (§5).
     *  [VersionConflict] carries `expected` and `actual` version ints (not the full row) — enough
     *  for the client to detect the clash and re-read. */
    fun toJson(): JsonObject = buildJsonObject {
        put("error", variant)
        when (val e = this@StxError) {
            is NotFound -> { put("entity", e.entity); put("id", e.id) }
            is Gone -> { put("entity", e.entity); put("id", e.id) }
            is CycleRejected -> { put("edge", e.edge); put("source", e.source); put("target", e.target) }
            is CrossWorkspace -> { put("source", e.source); put("target", e.target) }
            is IllegalTransition -> { put("taskId", e.taskId); put("from", e.from); put("to", e.to) }
            is ImmutableField -> { put("entity", e.entity); put("field", e.field) }
            is Duplicate -> { put("entity", e.entity); put("detail", e.detail) }
            is VersionConflict -> { put("entity", e.entity); put("id", e.id); put("expected", e.expected); put("actual", e.actual) }
            is Validation -> put("message", e.message)
        }
    }
}
