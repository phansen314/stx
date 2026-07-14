package stx

import kotlinx.serialization.json.Json
import stx.command.AddBlocks
import stx.command.Command
import stx.command.CreateTask
import stx.command.CreateWorkspace
import stx.command.ListWorkspaces
import stx.command.MoveStatus
import stx.command.Next
import kotlin.test.Test
import kotlin.test.assertEquals

/** §8 protocol test: every Command round-trips through kotlinx polymorphic serialization. */
class CommandSerializationTest {
    private val json = Json

    private inline fun <reified T : Command> roundtrip(value: T) {
        val encoded = json.encodeToString(Command.serializer(), value)
        val decoded = json.decodeFromString(Command.serializer(), encoded)
        assertEquals(value, decoded, "round-trip mismatch for $value (encoded=$encoded)")
    }

    @Test
    fun `commands round-trip`() {
        roundtrip(ListWorkspaces)
        roundtrip(CreateWorkspace("auth", """{"jira":"X-1"}"""))
        roundtrip(Next(workspaceId = 1, trackId = 2, kindId = 3, limit = 10))
        roundtrip(CreateTask(trackId = 4, title = "do it", priority = 5))
        roundtrip(MoveStatus(taskId = 7, toStatusId = 2, expectedVersion = 3))
        roundtrip(AddBlocks(sourceTaskId = 1, targetTaskId = 2))
    }
}
