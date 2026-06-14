package stx

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import stx.command.CreateTask
import stx.command.CreateWorkspace
import stx.log.Sidecar
import java.nio.file.Files
import java.nio.file.Path
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals

class SidecarTest {
    private val dir: Path = Files.createTempDirectory("stx-sidecar")
    private val log = dir.resolve("events.log")

    @AfterTest fun cleanup() {
        Files.deleteIfExists(log)
        Files.deleteIfExists(dir)
    }

    private fun lines() = Files.readAllLines(log).filter { it.isNotBlank() }

    @Test fun `records seq-numbered events with workspace and verb`() {
        val sidecar = Sidecar(log, clockMillis = { 1000L })
        sidecar.record(CreateWorkspace("a"), sampleWorkspace(id = 7))
        sidecar.record(CreateTask(1, 2, "t"), sampleTask(id = 3, workspaceId = 7))

        val rows = lines().map { Json.parseToJsonElement(it).jsonObject }
        assertEquals(2, rows.size)
        assertEquals("1", rows[0]["seq"]!!.jsonPrimitive.content)
        assertEquals("workspace", rows[0]["entity_type"]!!.jsonPrimitive.content)
        assertEquals("workspace.create", rows[0]["verb"]!!.jsonPrimitive.content)
        assertEquals("2", rows[1]["seq"]!!.jsonPrimitive.content)
        assertEquals("task", rows[1]["entity_type"]!!.jsonPrimitive.content)
        assertEquals("7", rows[1]["workspace"]!!.jsonPrimitive.content)
        assertEquals("task.create", rows[1]["verb"]!!.jsonPrimitive.content)
    }

    @Test fun `resumes seq from an existing log`() {
        Sidecar(log, clockMillis = { 1L }).record(CreateWorkspace("a"), sampleWorkspace(1))
        // A fresh Sidecar over the same file must continue numbering, not restart at 1.
        val resumed = Sidecar(log, clockMillis = { 2L })
        resumed.record(CreateWorkspace("b"), sampleWorkspace(2))
        assertEquals(2, resumed.currentSeq())
        assertEquals("2", Json.parseToJsonElement(lines().last()).jsonObject["seq"]!!.jsonPrimitive.content)
    }

    private fun sampleWorkspace(id: Long) =
        Workspace(id, "ws", emptyMap(), 0, false, "now", "now")

    private fun sampleTask(id: Long, workspaceId: Long) =
        Task(id, workspaceId, 1, 1, null, "t", "", 0, null, null, null, emptyMap(), 0, false, "now", "now")
}
