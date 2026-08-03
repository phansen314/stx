package stx

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.http4k.core.Method
import org.http4k.core.Request
import org.http4k.core.Response
import org.http4k.server.asServer
import stx.dto.TaskDto
import stx.dto.WorkspaceDto
import stx.repo.Db
import stx.service.StxService
import stx.service.WriteActor
import stx.transport.HttpApi
import stx.transport.LoopbackSunHttp
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.file.Files
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** §8: HTTP protocol — fold mapping (status codes + JSON bodies) and loopback binding. */
class HttpApiTest {
    private lateinit var dir: java.io.File
    private lateinit var actor: WriteActor
    private lateinit var api: HttpApi
    private val parser = Json { ignoreUnknownKeys = true }

    @BeforeTest fun setup() {
        dir = Files.createTempDirectory("stx-http").toFile()
        val db = Db("jdbc:sqlite:${dir.resolve("stx.db")}").also { it.init() }
        actor = WriteActor(db.connect(), StxService())
        api = HttpApi(db, StxService(), actor)
    }
    @AfterTest fun teardown() { actor.close(); dir.deleteRecursively() }

    private fun get(path: String): Response = api.handler(Request(Method.GET, path))
    private fun post(path: String, body: String = "{}"): Response = api.handler(Request(Method.POST, path).body(body))
    private fun patch(path: String, body: String): Response = api.handler(Request(Method.PATCH, path).body(body))
    private fun idOf(res: Response): Long = parser.parseToJsonElement(res.bodyString()).jsonObject["id"]!!.jsonPrimitive.long
    private fun errorOf(res: Response): String = parser.parseToJsonElement(res.bodyString()).jsonObject["error"]!!.jsonPrimitive.content

    @Test fun `happy path - create, list, next, get`() {
        val ws = post("/workspaces", """{"name":"ws"}""")
        assertEquals(200, ws.status.code)
        val wsId = idOf(ws)
        assertEquals("ws", parser.decodeFromString<WorkspaceDto>(ws.bodyString()).name)

        val trackId = idOf(post("/workspaces/$wsId/tracks", """{"name":"main"}"""))
        val taskRes = post("/tracks/$trackId/tasks", """{"title":"do it"}""")
        assertEquals(200, taskRes.status.code)
        val taskId = parser.decodeFromString<TaskDto>(taskRes.bodyString()).id

        val next = get("/next?workspace=$wsId")
        assertEquals(200, next.status.code)
        assertTrue(next.bodyString().contains("\"id\":$taskId"), "task in frontier")

        assertEquals(200, get("/tasks/$taskId").status.code)
    }

    @Test fun `list transitions returns the seeded set`() {
        val wsId = idOf(post("/workspaces", """{"name":"ws"}"""))
        val res = get("/workspaces/$wsId/transitions")
        assertEquals(200, res.status.code)
        val items = parser.parseToJsonElement(res.bodyString()).jsonObject["items"]!! as kotlinx.serialization.json.JsonArray
        // bootstrap seeds: Backlog->Implementation, Implementation->Review, Review->Done,
        // Implementation->Backlog, Review->Implementation, Done->Review
        assertEquals(6, items.size)
    }

    @Test fun `not found maps to 404`() {
        val res = get("/tasks/99999")
        assertEquals(404, res.status.code)
        assertEquals("NotFound", errorOf(res))
    }

    @Test fun `illegal transition maps to 409`() {
        val wsId = idOf(post("/workspaces", """{"name":"ws"}"""))
        val trackId = idOf(post("/workspaces/$wsId/tracks", """{"name":"m"}"""))
        val taskId = idOf(post("/tracks/$trackId/tasks", """{"title":"x"}"""))
        val statusItems = parser.parseToJsonElement(get("/workspaces/$wsId/statuses").bodyString())
            .jsonObject["items"]!! as kotlinx.serialization.json.JsonArray
        // Backlog -> Review has no seeded edge and Review is non-terminal, so it's illegal.
        // (Moving to the terminal Done would now be allowed via the escape hatch.)
        val reviewStatusId = statusItems
            .first { it.jsonObject["name"]!!.jsonPrimitive.content == "Review" }
            .jsonObject["id"]!!.jsonPrimitive.long
        val v = parser.parseToJsonElement(get("/tasks/$taskId").bodyString()).jsonObject["task"]!!.jsonObject["version"]!!.jsonPrimitive.content.toInt()
        val res = post("/tasks/$taskId/status", """{"toStatusId":$reviewStatusId,"expectedVersion":$v}""")
        assertEquals(409, res.status.code)
        assertEquals("IllegalTransition", errorOf(res))
    }

    @Test fun `version conflict maps to 409 with expected and actual`() {
        val wsId = idOf(post("/workspaces", """{"name":"ws"}"""))
        val trackId = idOf(post("/workspaces/$wsId/tracks", """{"name":"m"}"""))
        val taskId = idOf(post("/tracks/$trackId/tasks", """{"title":"x"}"""))
        val v = parser.parseToJsonElement(get("/tasks/$taskId").bodyString()).jsonObject["task"]!!.jsonObject["version"]!!.jsonPrimitive.content.toInt()
        assertEquals(200, patch("/tasks/$taskId", """{"expectedVersion":$v,"title":"a"}""").status.code)
        val conflict = patch("/tasks/$taskId", """{"expectedVersion":$v,"title":"b"}""")
        assertEquals(409, conflict.status.code)
        assertEquals("VersionConflict", errorOf(conflict))
    }

    @Test fun `malformed body maps to 400`() {
        val res = post("/workspaces", """{"nam""")
        assertEquals(400, res.status.code)
    }

    @Test fun `malformed path id maps to 400 not 500`() {
        val res = get("/tasks/abc")
        assertEquals(400, res.status.code)
        assertEquals("Validation", errorOf(res))
    }

    @Test fun `malformed query params map to 400 not 500`() {
        assertEquals(400, get("/next?workspace=1&track=x").status.code)
        assertEquals(400, get("/tracks/1/tasks?status=nope").status.code)
    }

    /**
     * `/changes` is the poll token: a run-scoped write counter plus the schema version. It moves
     * on a committed write and stays put on a read — that's the whole contract, and `stx version`
     * is its first consumer.
     */
    @Test fun `changes exposes the schema version and a write-only counter`() {
        val before = parser.parseToJsonElement(get("/changes").bodyString()).jsonObject
        assertEquals(Db.SCHEMA_VERSION, before["schema"]!!.jsonPrimitive.content.toInt())
        val seq0 = before["seq"]!!.jsonPrimitive.long

        get("/workspaces") // a read must not move it
        assertEquals(seq0, parser.parseToJsonElement(get("/changes").bodyString()).jsonObject["seq"]!!.jsonPrimitive.long)

        post("/workspaces", """{"name":"ws"}""")
        val seq1 = parser.parseToJsonElement(get("/changes").bodyString()).jsonObject["seq"]!!.jsonPrimitive.long
        assertTrue(seq1 > seq0, "a committed write bumps seq ($seq0 -> $seq1)")
    }

    @Test fun `patch workspace renames under CAS`() {
        val wsId = idOf(post("/workspaces", """{"name":"ws"}"""))
        val ok = patch("/workspaces/$wsId", """{"expectedVersion":0,"name":"renamed"}""")
        assertEquals(200, ok.status.code)
        assertEquals("renamed", parser.decodeFromString<WorkspaceDto>(ok.bodyString()).name)

        val stale = patch("/workspaces/$wsId", """{"expectedVersion":0,"name":"again"}""")
        assertEquals(409, stale.status.code)
        assertEquals("VersionConflict", errorOf(stale))
    }

    @Test fun `patch track edits name and description under CAS`() {
        val wsId = idOf(post("/workspaces", """{"name":"ws"}"""))
        val trackId = idOf(post("/workspaces/$wsId/tracks", """{"name":"main"}"""))
        val ok = patch("/tracks/$trackId", """{"expectedVersion":0,"name":"core","description":"the core"}""")
        assertEquals(200, ok.status.code)
        val body = parser.parseToJsonElement(ok.bodyString()).jsonObject
        assertEquals("core", body["name"]!!.jsonPrimitive.content)
        assertEquals("the core", body["description"]!!.jsonPrimitive.content)

        assertEquals(409, patch("/tracks/$trackId", """{"expectedVersion":0,"name":"x"}""").status.code)
    }

    @Test fun `bulk edge export returns both edge kinds`() {
        val wsId = idOf(post("/workspaces", """{"name":"ws"}"""))
        val trackId = idOf(post("/workspaces/$wsId/tracks", """{"name":"m"}"""))
        val a = idOf(post("/tracks/$trackId/tasks", """{"title":"a"}"""))
        val b = idOf(post("/tracks/$trackId/tasks", """{"title":"b"}"""))
        post("/blocks", """{"sourceTaskId":$a,"targetTaskId":$b}""")
        post("/relates", """{"sourceTaskId":$a,"targetTaskId":$b,"kind":"relates_to"}""")

        val res = get("/workspaces/$wsId/edges")
        assertEquals(200, res.status.code)
        val body = parser.parseToJsonElement(res.bodyString()).jsonObject
        assertEquals(1, (body["blocks"]!! as kotlinx.serialization.json.JsonArray).size)
        assertEquals(1, (body["relates"]!! as kotlinx.serialization.json.JsonArray).size)
    }

    /** The kanban read: ?status= filters a track's tasks to one stage. */
    @Test fun `track tasks filter by status`() {
        val wsId = idOf(post("/workspaces", """{"name":"ws"}"""))
        val trackId = idOf(post("/workspaces/$wsId/tracks", """{"name":"m"}"""))
        idOf(post("/tracks/$trackId/tasks", """{"title":"a"}"""))
        val statusItems = parser.parseToJsonElement(get("/workspaces/$wsId/statuses").bodyString())
            .jsonObject["items"]!! as kotlinx.serialization.json.JsonArray
        fun statusId(name: String) = statusItems
            .first { it.jsonObject["name"]!!.jsonPrimitive.content == name }
            .jsonObject["id"]!!.jsonPrimitive.long

        fun count(q: String) =
            ((parser.parseToJsonElement(get("/tracks/$trackId/tasks$q").bodyString())
                .jsonObject["items"]!!) as kotlinx.serialization.json.JsonArray).size

        assertEquals(1, count(""))
        assertEquals(1, count("?status=${statusId("Backlog")}"))
        assertEquals(0, count("?status=${statusId("Done")}"))
    }

    @Test fun `blockers returns them ordered, 404s an unknown task and 400s a bad depth`() {
        val wsId = idOf(post("/workspaces", """{"name":"ws"}"""))
        val trackId = idOf(post("/workspaces/$wsId/tracks", """{"name":"m"}"""))
        val a = idOf(post("/tracks/$trackId/tasks", """{"title":"a"}"""))
        val b = idOf(post("/tracks/$trackId/tasks", """{"title":"b"}"""))
        val target = idOf(post("/tracks/$trackId/tasks", """{"title":"target"}"""))
        post("/blocks", """{"sourceTaskId":$a,"targetTaskId":$b}""")
        post("/blocks", """{"sourceTaskId":$b,"targetTaskId":$target}""")

        val res = get("/tasks/$target/blockers")
        assertEquals(200, res.status.code)
        val items = parser.parseToJsonElement(res.bodyString()).jsonObject["items"]!! as kotlinx.serialization.json.JsonArray
        assertEquals(listOf(b, a), items.map { it.jsonObject["id"]!!.jsonPrimitive.long })
        assertEquals(listOf(1, 2), items.map { it.jsonObject["depth"]!!.jsonPrimitive.content.toInt() })

        // ?depth= truncates the walk
        val shallow = get("/tasks/$target/blockers?depth=1")
        assertEquals(1, (parser.parseToJsonElement(shallow.bodyString()).jsonObject["items"]!! as kotlinx.serialization.json.JsonArray).size)

        // an unblocked task has an empty answer — not an error
        assertEquals(200, get("/tasks/$a/blockers").status.code)
        assertEquals(0, (parser.parseToJsonElement(get("/tasks/$a/blockers").bodyString())
            .jsonObject["items"]!! as kotlinx.serialization.json.JsonArray).size)

        assertEquals(404, get("/tasks/99999/blockers").status.code)
        assertEquals(400, get("/tasks/$target/blockers?depth=deep").status.code)
        // depth < 1 would silently behave as 1 (the CTE base case is unconditional), so it is a
        // Validation error rather than a surprising one-hop answer.
        assertEquals(400, get("/tasks/$target/blockers?depth=0").status.code)
        assertEquals(400, get("/tasks/$target/blockers?depth=-3").status.code)

        // a finished task is not waiting on anything, even with an open blocker upstream
        val statusItems = parser.parseToJsonElement(get("/workspaces/$wsId/statuses").bodyString())
            .jsonObject["items"]!! as kotlinx.serialization.json.JsonArray
        val doneId = statusItems.first { it.jsonObject["name"]!!.jsonPrimitive.content == "Done" }
            .jsonObject["id"]!!.jsonPrimitive.long
        val v = parser.parseToJsonElement(get("/tasks/$target").bodyString())
            .jsonObject["task"]!!.jsonObject["version"]!!.jsonPrimitive.content.toInt()
        assertEquals(200, post("/tasks/$target/status", """{"toStatusId":$doneId,"expectedVersion":$v}""").status.code)
        val afterDone = get("/tasks/$target/blockers")
        assertEquals(200, afterDone.status.code)
        assertEquals(0, (parser.parseToJsonElement(afterDone.bodyString())
            .jsonObject["items"]!! as kotlinx.serialization.json.JsonArray).size)
    }

    @Test fun `unknown http method maps to 405`() {
        val server = api.handler.asServer(LoopbackSunHttp(0)).start()
        try {
            val client = HttpClient.newHttpClient()
            val resp = client.send(
                HttpRequest.newBuilder(URI("http://127.0.0.1:${server.port()}/health"))
                    .method("FOO", HttpRequest.BodyPublishers.noBody()).build(),
                HttpResponse.BodyHandlers.ofString(),
            )
            assertEquals(405, resp.statusCode())
        } finally {
            server.stop()
        }
    }

    @Test fun `server binds loopback and serves health`() {
        val server = api.handler.asServer(LoopbackSunHttp(0)).start()
        try {
            val port = server.port()
            val client = HttpClient.newHttpClient()
            val resp = client.send(
                HttpRequest.newBuilder(URI("http://127.0.0.1:$port/health")).build(),
                HttpResponse.BodyHandlers.ofString(),
            )
            assertEquals(200, resp.statusCode())
            assertEquals("stx ok", resp.body())
        } finally {
            server.stop()
        }
    }
}
