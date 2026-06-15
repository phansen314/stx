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

    @Test fun `health check returns 200`() {
        assertEquals(200, get("/health").status)
    }

    @Test fun `workspace and child-entity collection and single reads`() {
        val ws = post("/workspaces", """{"name":"rdtest","metadata":{"owner":"demo"}}""").id()

        val list = get("/workspaces").array()
        assertTrue(list.any { it.jsonObject["id"]!!.jsonPrimitive.long == ws })

        val single = get("/workspaces/$ws").json()
        assertEquals("rdtest", single["name"]!!.jsonPrimitive.content)
        assertEquals("demo", single["metadata"]!!.jsonObject["owner"]!!.jsonPrimitive.content)

        val backlog = post("/workspaces/$ws/statuses", """{"name":"Backlog","kanbanOrder":0}""").id()
        val done = post("/workspaces/$ws/statuses", """{"name":"Done","terminal":true,"kanbanOrder":1}""").id()
        post("/workspaces/$ws/transitions", """{"fromStatusId":$backlog,"toStatusId":$done}""")

        val statuses = get("/workspaces/$ws/statuses").array()
        assertEquals(2, statuses.size)
        val statusSingle = get("/statuses/$backlog").json()
        assertEquals("Backlog", statusSingle["name"]!!.jsonPrimitive.content)

        val transitions = get("/workspaces/$ws/transitions").array()
        assertEquals(1, transitions.size)

        val track = post(
            "/workspaces/$ws/tracks",
            """{"name":"Payments","description":"Billing rewrite","metadata":{"quarter":"Q3"}}"""
        ).id()

        val tracks = get("/workspaces/$ws/tracks").array()
        assertEquals(1, tracks.size)
        val trackSingle = get("/tracks/$track").json()
        assertEquals("Payments", trackSingle["name"]!!.jsonPrimitive.content)
        assertEquals("Billing rewrite", trackSingle["description"]!!.jsonPrimitive.content)
        assertEquals("Q3", trackSingle["metadata"]!!.jsonObject["quarter"]!!.jsonPrimitive.content)
    }

    @Test fun `segment reads - single entity, direct tasks, and recursive tasks`() {
        val ws = post("/workspaces", """{"name":"segtest"}""").id()
        val todo = post("/workspaces/$ws/statuses", """{"name":"todo"}""").id()
        val track = post("/workspaces/$ws/tracks", """{"name":"t"}""").id()
        val root = get("/tracks/$track/segments").array()[0].jsonObject["id"]!!.jsonPrimitive.long
        val child = post("/tracks/$track/segments", """{"name":"child","parentSegmentId":$root}""").id()

        val segSingle = get("/segments/$child").json()
        assertEquals("child", segSingle["name"]!!.jsonPrimitive.content)

        post("/tracks/$track/tasks", """{"statusId":$todo,"title":"root-task"}""").id()
        val childTask = post("/segments/$child/tasks", """{"statusId":$todo,"title":"child-task"}""").id()

        val direct = get("/segments/$child/tasks").array()
        assertEquals(1, direct.size)
        assertEquals(childTask, direct[0].jsonObject["id"]!!.jsonPrimitive.long)

        val recursive = get("/segments/$root/tasks?recursive=true").array()
        assertEquals(2, recursive.size)

        val trackTasks = get("/tracks/$track/tasks").array()
        assertEquals(2, trackTasks.size)
    }

    @Test fun `relates edges - create with kind and read at task and workspace level`() {
        val ws = post("/workspaces", """{"name":"reltest"}""").id()
        val todo = post("/workspaces/$ws/statuses", """{"name":"todo"}""").id()
        val track = post("/workspaces/$ws/tracks", """{"name":"t"}""").id()
        val a = post("/tracks/$track/tasks", """{"statusId":$todo,"title":"a"}""").id()
        val b = post("/tracks/$track/tasks", """{"statusId":$todo,"title":"b"}""").id()

        post("/relates", """{"kind":"duplicates","source":$a,"target":$b}""")

        assertEquals(1, get("/tasks/$a/relates").array().size)
        assertEquals(1, get("/tasks/$b/relates").array().size)
        assertEquals(1, get("/workspaces/$ws/relates").array().size)
    }

    @Test fun `scoped frontier by segment subtree and by kind`() {
        val ws = post("/workspaces", """{"name":"scopetest"}""").id()
        val todo = post("/workspaces/$ws/statuses", """{"name":"todo"}""").id()
        val track = post("/workspaces/$ws/tracks", """{"name":"t"}""").id()
        val root = get("/tracks/$track/segments").array()[0].jsonObject["id"]!!.jsonPrimitive.long
        val child = post("/tracks/$track/segments", """{"name":"child","parentSegmentId":$root}""").id()

        val design = post("/tracks/$track/tasks", """{"statusId":$todo,"title":"design","kind":"design"}""").id()
        val feature = post("/segments/$child/tasks", """{"statusId":$todo,"title":"feature","kind":"feature"}""").id()

        assertEquals(2, get("/next?workspace=$ws").array().size)

        val segScoped = get("/next?workspace=$ws&segment=$child").array()
        assertEquals(1, segScoped.size)
        assertEquals(feature, segScoped[0].jsonObject["id"]!!.jsonPrimitive.long)

        val kindFiltered = get("/next?workspace=$ws&kind=design").array()
        assertEquals(1, kindFiltered.size)
        assertEquals(design, kindFiltered[0].jsonObject["id"]!!.jsonPrimitive.long)
    }

    @Test fun `archiving a task cascades its incident edges and unblocks dependents`() {
        val ws = post("/workspaces", """{"name":"archtest"}""").id()
        val todo = post("/workspaces/$ws/statuses", """{"name":"todo"}""").id()
        val track = post("/workspaces/$ws/tracks", """{"name":"t"}""").id()
        val a = post("/tracks/$track/tasks", """{"statusId":$todo,"title":"a"}""").id()
        val b = post("/tracks/$track/tasks", """{"statusId":$todo,"title":"b"}""").id()
        val c = post("/tracks/$track/tasks", """{"statusId":$todo,"title":"c"}""").id()

        post("/blocks", """{"source":$a,"target":$b}""")
        post("/relates", """{"kind":"dup","source":$b,"target":$c}""")

        // a and c are frontier; b is blocked
        val before = get("/next?workspace=$ws").array().map { it.jsonObject["id"]!!.jsonPrimitive.long }.toSet()
        assertEquals(setOf(a, c), before)

        // Archive a → blocks edge cascades → b now unblocked
        assertEquals(200, post("/tasks/$a/archive").status)
        assertEquals(0, get("/tasks/$a/blocks").array().size)
        val after = get("/next?workspace=$ws").array().map { it.jsonObject["id"]!!.jsonPrimitive.long }.toSet()
        assertEquals(setOf(b, c), after)
    }

    @Test fun `segment rename is reflected on subsequent read`() {
        val ws = post("/workspaces", """{"name":"rentest"}""").id()
        val track = post("/workspaces/$ws/tracks", """{"name":"t"}""").id()
        val root = get("/tracks/$track/segments").array()[0].jsonObject["id"]!!.jsonPrimitive.long
        val seg = post("/tracks/$track/segments", """{"name":"old","parentSegmentId":$root}""").id()

        assertEquals(200, patch("/segments/$seg", """{"name":"new"}""").status)
        assertEquals("new", get("/segments/$seg").json()["name"]!!.jsonPrimitive.content)
    }

    @Test fun `track archive cascades all children and leaves frontier empty`() {
        val ws = post("/workspaces", """{"name":"trackarch"}""").id()
        val todo = post("/workspaces/$ws/statuses", """{"name":"todo"}""").id()
        val track = post("/workspaces/$ws/tracks", """{"name":"t"}""").id()
        val root = get("/tracks/$track/segments").array()[0].jsonObject["id"]!!.jsonPrimitive.long
        val child = post("/tracks/$track/segments", """{"name":"child","parentSegmentId":$root}""").id()
        val t1 = post("/tracks/$track/tasks", """{"statusId":$todo,"title":"t1"}""").id()
        val t2 = post("/segments/$child/tasks", """{"statusId":$todo,"title":"t2"}""").id()
        post("/blocks", """{"source":$t1,"target":$t2}""")

        assertEquals(1, get("/next?workspace=$ws").array().size)

        assertEquals(200, post("/tracks/$track/archive").status)
        assertTrue(get("/next?workspace=$ws").array().isEmpty(), "frontier empty after track archive")
    }
}
