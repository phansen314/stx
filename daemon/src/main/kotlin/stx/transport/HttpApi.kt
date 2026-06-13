package stx.transport

import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerializationException
import kotlinx.serialization.builtins.ListSerializer
import org.http4k.core.HttpHandler
import org.http4k.core.Method.GET
import org.http4k.core.Method.PATCH
import org.http4k.core.Method.POST
import org.http4k.core.Request
import org.http4k.core.Response
import org.http4k.core.Status
import org.http4k.routing.bind
import org.http4k.routing.path
import org.http4k.routing.routes
import stx.Blocks
import stx.FrontierTask
import stx.RelatesTo
import stx.Segment
import stx.Status as StatusEntity
import stx.StatusTransition
import stx.StxException
import stx.Task
import stx.Track
import stx.Workspace
import stx.command.AddBlocks
import stx.command.AddRelatesTo
import stx.command.ArchiveBlocks
import stx.command.ArchiveRelatesTo
import stx.command.ArchiveSegment
import stx.command.ArchiveStatus
import stx.command.ArchiveTask
import stx.command.ArchiveTrack
import stx.command.ArchiveTransition
import stx.command.ArchiveWorkspace
import stx.command.Command
import stx.command.CreateSegment
import stx.command.CreateStatus
import stx.command.CreateTask
import stx.command.CreateTrack
import stx.command.CreateTransition
import stx.command.CreateWorkspace
import stx.command.MoveSegment
import stx.command.MoveTask
import stx.command.TaskPatch
import stx.command.UpdateStatus
import stx.command.UpdateTask
import stx.command.UpdateTrack
import stx.command.UpdateWorkspace
import stx.service.Reads
import stx.service.WriteActor

/**
 * The HTTP façade (brief §5): a thin, lightly-RESTful layer that parses a request into the right
 * [Command] and hands it to the write-actor (mutations) or the read side (queries). It holds no
 * business logic — invariants live in the service. Every response is JSON, including structured
 * error envelopes. Bound to 127.0.0.1 only by [LoopbackServer].
 *
 * @param writeFn how a Command reaches the single writer (the actor's blocking submit).
 */
class HttpApi(
    private val reads: Reads,
    private val writeFn: (Command) -> Any,
) {
    fun handler(): HttpHandler = routes(
        "/health" bind GET to { Response(Status.OK).body("ok") },

        // ── reads ────────────────────────────────────────────────────────────
        "/next" bind GET to ::next,
        "/workspaces" bind GET to { okList(reads.listWorkspaces(), Workspace.serializer()) },
        "/workspaces/{id}/statuses" bind GET to { req ->
            okList(reads.listStatuses(req.id()), StatusEntity.serializer())
        },
        "/workspaces/{id}/tracks" bind GET to { req ->
            okList(reads.listTracks(req.id()), Track.serializer())
        },
        "/tracks/{id}/segments" bind GET to { req ->
            okList(reads.listSegments(req.id()), Segment.serializer())
        },
        "/tracks/{id}/tasks" bind GET to { req ->
            okList(reads.listTasksByTrack(req.id(), req.longQuery("status")), Task.serializer())
        },
        "/tasks/{id}" bind GET to { req -> ok(reads.getTask(req.id()), Task.serializer()) },

        // ── workspace mutations ──────────────────────────────────────────────
        "/workspaces" bind POST to { req ->
            val b = req.parse(WorkspaceBody.serializer())
            created(write(CreateWorkspace(b.name, b.metadata)), Workspace.serializer())
        },
        "/workspaces/{id}" bind PATCH to { req ->
            val b = req.parse(WorkspacePatchBody.serializer())
            ok(write(UpdateWorkspace(req.id(), b.name, b.metadata)), Workspace.serializer())
        },
        "/workspaces/{id}/archive" bind POST to { req ->
            ok(write(ArchiveWorkspace(req.id())), Workspace.serializer())
        },

        // ── status mutations ─────────────────────────────────────────────────
        "/workspaces/{id}/statuses" bind POST to { req ->
            val b = req.parse(StatusBody.serializer())
            created(write(CreateStatus(req.id(), b.name, b.terminal, b.kanbanOrder)), StatusEntity.serializer())
        },
        "/statuses/{id}" bind PATCH to { req ->
            val b = req.parse(StatusPatchBody.serializer())
            ok(write(UpdateStatus(req.id(), b.name, b.terminal, b.kanbanOrder)), StatusEntity.serializer())
        },
        "/statuses/{id}/archive" bind POST to { req ->
            ok(write(ArchiveStatus(req.id())), StatusEntity.serializer())
        },

        // ── transition mutations ─────────────────────────────────────────────
        "/workspaces/{id}/transitions" bind POST to { req ->
            val b = req.parse(TransitionBody.serializer())
            created(write(CreateTransition(req.id(), b.fromStatusId, b.toStatusId)), StatusTransition.serializer())
        },
        "/transitions/{id}/archive" bind POST to { req ->
            ok(write(ArchiveTransition(req.id())), StatusTransition.serializer())
        },

        // ── track mutations ──────────────────────────────────────────────────
        "/workspaces/{id}/tracks" bind POST to { req ->
            val b = req.parse(TrackBody.serializer())
            created(write(CreateTrack(req.id(), b.name, b.description, b.metadata)), Track.serializer())
        },
        "/tracks/{id}" bind PATCH to { req ->
            val b = req.parse(TrackPatchBody.serializer())
            ok(write(UpdateTrack(req.id(), b.name, b.description, b.metadata)), Track.serializer())
        },
        "/tracks/{id}/archive" bind POST to { req -> ok(write(ArchiveTrack(req.id())), Track.serializer()) },

        // ── segment mutations ────────────────────────────────────────────────
        "/tracks/{id}/segments" bind POST to { req ->
            val b = req.parse(SegmentBody.serializer())
            created(write(CreateSegment(req.id(), b.name, b.parentSegmentId)), Segment.serializer())
        },
        "/segments/{id}/move" bind POST to { req ->
            val b = req.parse(SegmentMoveBody.serializer())
            ok(write(MoveSegment(req.id(), b.newParentSegmentId)), Segment.serializer())
        },
        "/segments/{id}/archive" bind POST to { req -> ok(write(ArchiveSegment(req.id())), Segment.serializer()) },
        "/segments/{id}/tasks" bind POST to { req ->
            val b = req.parse(TaskBody.serializer())
            created(write(taskCommand(req.id(), b)), Task.serializer())
        },

        // ── task mutations ───────────────────────────────────────────────────
        "/tracks/{id}/tasks" bind POST to { req ->
            // "Add to the track" routes to the track's auto-created root segment.
            val rootSegmentId = reads.listSegments(req.id()).firstOrNull { it.isRoot }?.id
                ?: throw StxException.NotFound("root segment for track ${req.id()}")
            val b = req.parse(TaskBody.serializer())
            created(write(taskCommand(rootSegmentId, b)), Task.serializer())
        },
        "/tasks/{id}" bind PATCH to { req ->
            val patch = req.parse(TaskPatch.serializer())
            ok(write(UpdateTask(req.id(), patch)), Task.serializer())
        },
        "/tasks/{id}/status" bind POST to { req ->
            val b = req.parse(TaskStatusBody.serializer())
            ok(write(MoveTask(req.id(), b.toStatusId)), Task.serializer())
        },
        "/tasks/{id}/archive" bind POST to { req -> ok(write(ArchiveTask(req.id())), Task.serializer()) },

        // ── edge mutations ───────────────────────────────────────────────────
        "/blocks" bind POST to { req ->
            val b = req.parse(BlocksBody.serializer())
            created(write(AddBlocks(b.source, b.target, b.metadata)), Blocks.serializer())
        },
        "/blocks/{id}/archive" bind POST to { req -> ok(write(ArchiveBlocks(req.id())), Blocks.serializer()) },
        "/relates" bind POST to { req ->
            val b = req.parse(RelatesBody.serializer())
            created(write(AddRelatesTo(b.kind, b.source, b.target, b.metadata)), RelatesTo.serializer())
        },
        "/relates/{id}/archive" bind POST to { req -> ok(write(ArchiveRelatesTo(req.id())), RelatesTo.serializer()) },
    ).withErrorEnvelope()

    private fun next(req: Request): Response {
        val ws = req.longQuery("workspace") ?: throw StxException.Validation("query param 'workspace' is required")
        val result = reads.next(
            workspaceId = ws,
            trackId = req.longQuery("track"),
            segmentId = req.longQuery("segment"),
            kind = req.query("kind"),
            limit = req.longQuery("limit")?.toInt(),
        )
        return okList(result, FrontierTask.serializer())
    }

    private fun taskCommand(segmentId: Long, b: TaskBody) = CreateTask(
        segmentId = segmentId,
        statusId = b.statusId,
        title = b.title,
        kind = b.kind,
        description = b.description,
        priority = b.priority,
        dueDate = b.dueDate,
        startDate = b.startDate,
        finishDate = b.finishDate,
        metadata = b.metadata,
    )

    private fun write(command: Command): Any = writeFn(command)

    // ── request/response helpers ─────────────────────────────────────────────
    private fun Request.id(): Long =
        path("id")?.toLongOrNull() ?: throw StxException.Validation("invalid or missing path id")

    private fun Request.longQuery(name: String): Long? =
        query(name)?.let { it.toLongOrNull() ?: throw StxException.Validation("query param '$name' must be an integer") }

    private fun <T> Request.parse(serializer: KSerializer<T>): T = try {
        Wire.decodeFromString(serializer, bodyString())
    } catch (e: SerializationException) {
        throw StxException.Validation("malformed request body: ${e.message}")
    }

    @Suppress("UNCHECKED_CAST")
    private fun <T> ok(value: Any, serializer: KSerializer<T>): Response =
        jsonResponse(Status.OK, Wire.encodeToString(serializer, value as T))

    @Suppress("UNCHECKED_CAST")
    private fun <T> created(value: Any, serializer: KSerializer<T>): Response =
        jsonResponse(Status.CREATED, Wire.encodeToString(serializer, value as T))

    private fun <T> okList(values: List<T>, serializer: KSerializer<T>): Response =
        jsonResponse(Status.OK, Wire.encodeToString(ListSerializer(serializer), values))

    private fun jsonResponse(status: Status, body: String): Response =
        Response(status).header("Content-Type", "application/json").body(body)

    /** Wrap the whole app so any thrown [StxException] becomes a structured JSON error. */
    private fun HttpHandler.withErrorEnvelope(): HttpHandler = { req ->
        try {
            this(req)
        } catch (e: StxException) {
            val status = when (e) {
                is StxException.Validation -> Status.BAD_REQUEST
                is StxException.NotFound -> Status.NOT_FOUND
                is StxException.Conflict -> Status.CONFLICT
            }
            jsonResponse(status, Wire.encodeToString(ErrorBody.serializer(), ErrorBody(e.message ?: "", e.kind())))
        } catch (e: Exception) {
            jsonResponse(
                Status.INTERNAL_SERVER_ERROR,
                Wire.encodeToString(ErrorBody.serializer(), ErrorBody(e.message ?: "internal error", "Internal")),
            )
        }
    }

    private fun StxException.kind(): String = when (this) {
        is StxException.Validation -> "Validation"
        is StxException.NotFound -> "NotFound"
        is StxException.Conflict -> "Conflict"
    }
}
