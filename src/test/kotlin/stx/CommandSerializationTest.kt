package stx

import kotlinx.serialization.json.Json
import stx.command.AddBlocks
import stx.command.Command
import stx.command.CreateTask
import stx.command.CreateWorkspace
import stx.command.ListWorkspaces
import stx.command.ClaimTask
import stx.command.EditKind
import stx.command.ListClaims
import stx.command.NextAndClaim
import stx.command.ReleaseTask
import stx.command.EditSegment
import stx.command.EditStatus
import stx.command.MoveStatus
import stx.command.Next
import stx.command.RefileTask
import stx.command.ReorderStatuses
import stx.command.ListBlockers
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
        roundtrip(ListBlockers(taskId = 9, maxDepth = 8))
        roundtrip(CreateTask(trackId = 4, title = "do it", priority = 5))
        roundtrip(MoveStatus(taskId = 7, toStatusId = 2, expectedVersion = 3))
        roundtrip(AddBlocks(sourceTaskId = 1, targetTaskId = 2))
        roundtrip(RefileTask(taskId = 7, segmentId = 3, expectedVersion = 2))
        roundtrip(EditSegment(segmentId = 5, name = "phase-2", parentSegmentId = 6))
        roundtrip(EditStatus(workspaceId = 1, statusId = 2, name = "Todo", kanbanOrder = 3))
        roundtrip(ReorderStatuses(workspaceId = 1, statusIds = listOf(3, 1, 2)))
        roundtrip(EditKind(workspaceId = 1, kindId = 4, name = "impl"))
        roundtrip(Next(workspaceId = 1, asAgent = "agent-1"))
        roundtrip(ClaimTask(taskId = 7, agentId = "agent-1", ttlSeconds = 900))
        roundtrip(ReleaseTask(taskId = 7, agentId = "agent-1"))
        roundtrip(NextAndClaim(workspaceId = 1, agentId = "agent-1", ttlSeconds = 900, trackId = 2, limit = 5))
        roundtrip(ListClaims(workspaceId = 1))
    }
}
