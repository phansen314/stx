package stx.transport

import kotlinx.serialization.json.JsonObject
import org.apache.logging.log4j.LogManager
import org.http4k.core.Method.GET
import org.http4k.core.Method.PATCH
import org.http4k.core.Method.POST
import org.http4k.core.Filter
import org.http4k.core.HttpHandler
import org.http4k.core.Request
import org.http4k.core.Response
import org.http4k.core.Status
import org.http4k.core.then
import org.http4k.routing.RoutingHttpHandler
import org.http4k.routing.bind
import org.http4k.routing.path
import org.http4k.routing.routes
import stx.command.*
import stx.dto.Reply
import stx.error.StxError
import stx.repo.Db
import stx.service.StxService
import stx.service.WriteActor
import tech.codingzen.res.Res
import tech.codingzen.res.fold

/**
 * Lightly-RESTful façade (brief §5): parse a request into a [Command], hand it to the service
 * (reads inline against WAL; writes through the [WriteActor]), and end every request with the
 * single `fold` that turns the `Res` rails into status codes + JSON. The HTTP layer holds no
 * domain logic — it only translates.
 */
class HttpApi(private val db: Db, private val service: StxService, private val actor: WriteActor) {
    private val log = LogManager.getLogger(HttpApi::class.java)

    /** Malformed numeric path/query params raise [BadParam] deep in a handler; map it to 400 here
     *  instead of letting a NumberFormatException escape to the transport catch-all (-> 500). */
    private val numericGuard = Filter { next ->
        { req: Request ->
            try { next(req) } catch (e: BadParam) { badRequest(e.message ?: "invalid parameter") }
        }
    }

    val handler: HttpHandler = numericGuard.then(routes(
        "/health" bind GET to { Response(Status.OK).body("stx ok") },
        // Cheap poll token: `seq` bumps on every committed write; `schema` is the DB user_version.
        // No DB hit — the counter lives in the write actor (brief §6/§7).
        "/changes" bind GET to { Response(Status.OK).jsonBody("""{"seq":${actor.changeSeq()},"schema":${Db.SCHEMA_VERSION}}""") },

        // ── reads ──
        "/next" bind GET to ::next,
        "/workspaces" bind GET to { read(ListWorkspaces) },
        "/workspaces/{id}/tracks" bind GET to { read(ListTracks(it.longPath("id"))) },
        "/workspaces/{id}/statuses" bind GET to { read(ListStatuses(it.longPath("id"))) },
        "/workspaces/{id}/kinds" bind GET to { read(ListKinds(it.longPath("id"))) },
        "/workspaces/{id}/relates-kinds" bind GET to { read(ListRelatesKinds(it.longPath("id"))) },
        "/workspaces/{id}/transitions" bind GET to { read(ListTransitions(it.longPath("id"))) },
        "/tracks/{id}/segments" bind GET to { read(ListSegments(it.longPath("id"))) },
        "/tracks/{id}/tasks" bind GET to { read(ListTasks(it.longPath("id"), it.longQuery("status"))) },
        "/tasks/{id}" bind GET to { read(GetTask(it.longPath("id"))) },

        // ── writes: registries & containers ──
        "/workspaces" bind POST to { req -> body<WorkspaceBody>(req) { CreateWorkspace(it.name, it.metadataJson) } },
        "/workspaces/{id}/statuses" bind POST to { req -> body<StatusBody>(req) { CreateStatus(req.longPath("id"), it.name, it.kanbanOrder, it.terminal) } },
        "/workspaces/{id}/statuses/{sid}/default" bind POST to { req -> write(SetDefaultStatus(req.longPath("id"), req.longPath("sid"))) },
        "/workspaces/{id}/kinds" bind POST to { req -> body<KindBody>(req) { CreateKind(req.longPath("id"), it.name) } },
        "/workspaces/{id}/transitions" bind POST to { req -> body<TransitionBody>(req) { CreateTransition(req.longPath("id"), it.fromStatusId, it.toStatusId) } },
        "/workspaces/{id}/tracks" bind POST to { req -> body<TrackBody>(req) { CreateTrack(req.longPath("id"), it.name, it.description, it.metadataJson) } },
        "/tracks/{id}/segments" bind POST to { req -> body<SegmentBody>(req) { CreateSegment(req.longPath("id"), it.name, it.parentSegmentId) } },

        // ── writes: tasks ──
        "/tracks/{id}/tasks" bind POST to { req -> body<TaskBody>(req) { taskFrom(trackId = req.longPath("id"), segmentId = null, b = it) } },
        "/segments/{id}/tasks" bind POST to { req -> body<TaskBody>(req) { taskFrom(trackId = null, segmentId = req.longPath("id"), b = it) } },
        "/tasks/{id}/status" bind POST to { req -> body<MoveStatusBody>(req) { MoveStatus(req.longPath("id"), it.toStatusId, it.expectedVersion) } },
        "/tasks/{id}" bind PATCH to { req -> body<EditTaskBody>(req) { editFrom(req.longPath("id"), it) } },
        "/workspaces/{id}" bind PATCH to { req -> body<EditWorkspaceBody>(req) { EditWorkspace(req.longPath("id"), it.expectedVersion, it.name, it.metadataJson) } },
        "/tracks/{id}" bind PATCH to { req -> body<EditTrackBody>(req) { EditTrack(req.longPath("id"), it.expectedVersion, it.name, it.description, it.metadataJson) } },

        // ── writes: edges ──
        "/blocks" bind POST to { req -> body<BlocksBody>(req) { AddBlocks(it.sourceTaskId, it.targetTaskId) } },
        "/relates" bind POST to { req -> body<RelatesBody>(req) { AddRelates(it.kind, it.sourceTaskId, it.targetTaskId) } },
        "/blocks/archive" bind POST to { req -> body<BlocksBody>(req) { RemoveBlocks(it.sourceTaskId, it.targetTaskId) } },
        "/relates/archive" bind POST to { req -> body<RelatesBody>(req) { RemoveRelates(it.kind, it.sourceTaskId, it.targetTaskId) } },

        // ── writes: archives ──
        "/tasks/{id}/archive" bind POST to { write(ArchiveTask(it.longPath("id"))) },
        "/segments/{id}/archive" bind POST to { write(ArchiveSegment(it.longPath("id"))) },
        "/tracks/{id}/archive" bind POST to { write(ArchiveTrack(it.longPath("id"))) },
        "/workspaces/{id}/archive" bind POST to { write(ArchiveWorkspace(it.longPath("id"))) },
        "/workspaces/{id}/statuses/{sid}/archive" bind POST to { req -> write(ArchiveStatus(req.longPath("id"), req.longPath("sid"))) },
        "/workspaces/{id}/kinds/{kid}/archive" bind POST to { req -> write(ArchiveKind(req.longPath("id"), req.longPath("kid"))) },
    ))

    // ── helpers ──────────────────────────────────────────────────────────────────────────────

    private fun next(req: Request): Response {
        val ws = req.longQuery("workspace") ?: return badRequest("workspace query param required")
        return read(Next(ws, req.longQuery("track"), req.longQuery("segment"), req.longQuery("kind"), req.intQuery("limit")))
    }

    private fun taskFrom(trackId: Long?, segmentId: Long?, b: TaskBody) = CreateTask(
        segmentId = segmentId, trackId = trackId, title = b.title, description = b.description, priority = b.priority,
        statusId = b.statusId, kindId = b.kindId, metadataJson = b.metadataJson,
    )

    private fun editFrom(id: Long, b: EditTaskBody) = EditTask(
        taskId = id, expectedVersion = b.expectedVersion, title = b.title, description = b.description, priority = b.priority,
        kindId = b.kindId, clearKind = b.clearKind, metadataJson = b.metadataJson,
    )

    private fun Request.longPath(name: String): Long =
        (path(name) ?: throw BadParam("missing path parameter '$name'")).toLongOrNull()
            ?: throw BadParam("invalid path parameter '$name'")

    private fun Request.longQuery(name: String): Long? =
        query(name)?.let { it.toLongOrNull() ?: throw BadParam("invalid query parameter '$name'") }

    private fun Request.intQuery(name: String): Int? =
        query(name)?.let { it.toIntOrNull() ?: throw BadParam("invalid query parameter '$name'") }

    /** Reads run in a deferred transaction so every statement of a multi-statement read (e.g.
     *  [StxService.getTask], `next --segment`) shares ONE WAL snapshot — no torn composite read
     *  when a write commits mid-read. Read-only, so the txn is always rolled back. */
    private fun read(cmd: Command): Response = db.connect().use { c ->
        c.autoCommit = false
        try {
            reply(service.dispatch(c, cmd))
        } finally {
            runCatching { c.rollback() }
            runCatching { c.autoCommit = true }
        }
    }

    private fun write(cmd: WriteCommand): Response = reply(actor.submitBlocking(cmd))

    /** Decode a JSON body to [T], build a write command, submit it. Malformed body -> 400. */
    private inline fun <reified T> body(req: Request, build: (T) -> WriteCommand): Response =
        runCatching { json.decodeFromString<T>(req.bodyString()) }
            .fold({ write(build(it)) }, { badRequest(it.message ?: "invalid request body") })

    /** The one place rails become HTTP (brief §5). */
    private fun reply(res: Res<Reply, StxError>): Response = res.fold(
        onOk = { Response(Status.OK).jsonBody(encodeReply(it)) },
        onFailure = { e -> Response(Status(e.code, e.variant)).jsonBody(json.encodeToString(JsonObject.serializer(), e.toJson())) },
        onDefect = { t ->
            log.error("unexpected defect", t)
            Response(Status.INTERNAL_SERVER_ERROR).jsonBody("""{"error":"Internal"}""")
        },
    )

    private fun badRequest(message: String): Response =
        Response(Status.BAD_REQUEST).jsonBody("""{"error":"Validation","message":${json.encodeToString(message)}}""")

    private fun Response.jsonBody(s: String): Response = header("Content-Type", "application/json").body(s)
}

/** Malformed numeric path/query input; [HttpApi.numericGuard] maps it to 400 (never a 500). */
private class BadParam(message: String) : RuntimeException(message)
