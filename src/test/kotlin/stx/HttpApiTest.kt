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
