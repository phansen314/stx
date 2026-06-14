package stx

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import stx.repo.Db
import stx.service.Reads
import stx.service.Service
import stx.service.WriteActor
import stx.transport.HttpApi
import stx.transport.LoopbackServer
import java.net.InetAddress
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpRequest.BodyPublishers
import java.net.http.HttpResponse.BodyHandlers
import java.nio.file.Files
import java.nio.file.Path
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class HttpApiTest {
    private val tmp: Path = Files.createTempFile("stx-http", ".db")
    private val db = Db.forFile(tmp.toString())
    private val actor: WriteActor
    private val server: LoopbackServer
    private val port: Int
    private val http = HttpClient.newHttpClient()

    init {
        db.init()
        actor = WriteActor(db, Service())
        actor.start()
        val api = HttpApi(Reads(db), writeFn = actor::submitBlocking)
        server = LoopbackServer(0, api.handler())
        port = server.start()
    }

    @AfterTest fun cleanup() {
        server.stop()
        actor.stop()
        Files.deleteIfExists(tmp)
        Files.deleteIfExists(Path.of("$tmp-wal"))
        Files.deleteIfExists(Path.of("$tmp-shm"))
    }

    private data class Resp(val status: Int, val body: String) {
        fun json() = Json.parseToJsonElement(body).jsonObject
        fun id() = json()["id"]!!.jsonPrimitive.long
        fun array(): JsonArray = Json.parseToJsonElement(body).jsonArray
    }

    private fun post(path: String, body: String = "{}"): Resp = send("POST", path, body)
    private fun patch(path: String, body: String): Resp = send("PATCH", path, body)
    private fun put(path: String, body: String): Resp = send("PUT", path, body)
    private fun delete(path: String): Resp = send("DELETE", path, null)
    private fun get(path: String): Resp = send("GET", path, null)

    private fun send(method: String, path: String, body: String?): Resp {
        val builder = HttpRequest.newBuilder(URI.create("http://127.0.0.1:$port$path"))
            .header("Content-Type", "application/json")
        when (method) {
            "GET" -> builder.GET()
            "DELETE" -> builder.DELETE()
            "PATCH" -> builder.method("PATCH", BodyPublishers.ofString(body ?: ""))
            "PUT" -> builder.PUT(BodyPublishers.ofString(body ?: ""))
            else -> builder.POST(BodyPublishers.ofString(body ?: ""))
        }
        val r = http.send(builder.build(), BodyHandlers.ofString())
        return Resp(r.statusCode(), r.body())
    }

    @Test fun `server binds loopback only`() {
        assertTrue(server.boundAddress().address.isLoopbackAddress, "must bind a loopback address")
        // The external interface address must not be the bound one.
        val ext = InetAddress.getAllByName(InetAddress.getLocalHost().hostName)
            .firstOrNull { !it.isLoopbackAddress }
        if (ext != null) assertTrue(ext != server.boundAddress().address)
    }

    @Test fun `full lifecycle over http with legal and illegal status moves`() {
        val ws = post("/workspaces", """{"name":"demo"}""").id()
        val todo = post("/workspaces/$ws/statuses", """{"name":"todo"}""").id()
        val done = post("/workspaces/$ws/statuses", """{"name":"done","terminal":true}""").id()
        post("/workspaces/$ws/transitions", """{"fromStatusId":$todo,"toStatusId":$done}""")

        val trackResp = post("/workspaces/$ws/tracks", """{"name":"auth"}""")
        assertEquals(201, trackResp.status)
        val track = trackResp.id()

        // Root segment auto-created with the track.
        val segments = get("/tracks/$track/segments").array()
        assertEquals(1, segments.size)
        assertTrue(segments[0].jsonObject["isRoot"]!!.jsonPrimitive.content == "true")

        // "Add to track" routes to the root segment.
        val task = post("/tracks/$track/tasks", """{"statusId":$todo,"title":"build it"}""").id()

        // Frontier contains the workable task.
        val frontierBefore = get("/next?workspace=$ws").array()
        assertEquals(listOf(task), frontierBefore.map { it.jsonObject["id"]!!.jsonPrimitive.long })

        // Legal move todo→done (terminal) accepted; task leaves the frontier.
        assertEquals(200, post("/tasks/$task/status", """{"toStatusId":$done}""").status)
        assertTrue(get("/next?workspace=$ws").array().isEmpty(), "terminal task drops out of the frontier")

        // Illegal move done→todo (no such transition) rejected with 400.
        val illegal = post("/tasks/$task/status", """{"toStatusId":$todo}""")
        assertEquals(400, illegal.status)
        assertEquals("Validation", illegal.json()["kind"]!!.jsonPrimitive.content)
    }

    @Test fun `stale expectedVersion over http is a 409`() {
        val ws = post("/workspaces", """{"name":"demo"}""").id()
        val todo = post("/workspaces/$ws/statuses", """{"name":"todo"}""").id()
        val track = post("/workspaces/$ws/tracks", """{"name":"auth"}""").id()
        val task = post("/tracks/$track/tasks", """{"statusId":$todo,"title":"t"}""").id()

        // version starts at 0; a matching CAS write succeeds.
        assertEquals(0L, get("/tasks/$task").json()["version"]!!.jsonPrimitive.long)
        assertEquals(200, patch("/tasks/$task?expectedVersion=0", """{"title":"t1"}""").status)
        // The now-stale token is rejected with a structured 409.
        val stale = patch("/tasks/$task?expectedVersion=0", """{"title":"t2"}""")
        assertEquals(409, stale.status)
        assertEquals("Conflict", stale.json()["kind"]!!.jsonPrimitive.content)
    }

    @Test fun `per-key metadata set and delete over http`() {
        val ws = post("/workspaces", """{"name":"demo"}""").id()
        val todo = post("/workspaces/$ws/statuses", """{"name":"todo"}""").id()
        val track = post("/workspaces/$ws/tracks", """{"name":"auth"}""").id()
        val task = post("/tracks/$track/tasks", """{"statusId":$todo,"title":"t"}""").id()

        val set = put("/tasks/$task/meta/jira_key", """{"value":"AUTH-1"}""")
        assertEquals(200, set.status)
        assertEquals("AUTH-1", set.json()["metadata"]!!.jsonObject["jira_key"]!!.jsonPrimitive.content)

        val del = delete("/tasks/$task/meta/jira_key")
        assertEquals(200, del.status)
        assertTrue(del.json()["metadata"]!!.jsonObject["jira_key"] == null, "key removed")
    }

    @Test fun `task refile and edge reads over http`() {
        val ws = post("/workspaces", """{"name":"demo"}""").id()
        val todo = post("/workspaces/$ws/statuses", """{"name":"todo"}""").id()
        val track = post("/workspaces/$ws/tracks", """{"name":"auth"}""").id()
        val root = get("/tracks/$track/segments").array()[0].jsonObject["id"]!!.jsonPrimitive.long
        val seg = post("/tracks/$track/segments", """{"name":"child","parentSegmentId":$root}""").id()
        val a = post("/tracks/$track/tasks", """{"statusId":$todo,"title":"a"}""").id()
        val b = post("/tracks/$track/tasks", """{"statusId":$todo,"title":"b"}""").id()

        // Refile task a under the child segment.
        assertEquals(200, post("/tasks/$a/segment", """{"toSegmentId":$seg}""").status)
        assertEquals(seg, get("/tasks/$a").json()["segmentId"]!!.jsonPrimitive.long)

        // Add a blocks edge and read it back from both incident endpoints.
        post("/blocks", """{"source":$a,"target":$b}""")
        assertEquals(1, get("/tasks/$a/blocks").array().size)
        assertEquals(1, get("/tasks/$b/blocks").array().size)
        assertEquals(1, get("/workspaces/$ws/blocks").array().size)
    }

    @Test fun `unknown task is a structured 404`() {
        val r = get("/tasks/999")
        assertEquals(404, r.status)
        assertEquals("NotFound", r.json()["kind"]!!.jsonPrimitive.content)
    }

    @Test fun `malformed body is a 400`() {
        val r = post("/workspaces", """{"nope":true}""")
        assertEquals(400, r.status)
    }
}
