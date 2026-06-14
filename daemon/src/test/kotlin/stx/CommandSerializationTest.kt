package stx

import kotlinx.serialization.json.Json
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
import stx.command.DeleteMetaKey
import stx.command.MetaEntity
import stx.command.MoveSegment
import stx.command.MoveTask
import stx.command.MoveTaskToSegment
import stx.command.RenameSegment
import stx.command.SetMetaKey
import stx.command.TaskPatch
import stx.command.UpdateStatus
import stx.command.UpdateTask
import stx.command.UpdateTrack
import stx.command.UpdateWorkspace
import kotlin.test.Test
import kotlin.test.assertEquals

class CommandSerializationTest {
    private val json = Json

    /** One instance of every Command variant — keep in sync with the sealed hierarchy. */
    private val all: List<Command> = listOf(
        CreateWorkspace("ws", mapOf("k" to "v")),
        UpdateWorkspace(1, name = "ws2", metadata = mapOf("a" to "b")),
        ArchiveWorkspace(1),
        CreateStatus(1, "todo", terminal = false, kanbanOrder = 1),
        UpdateStatus(1, name = "doing", terminal = true, kanbanOrder = 2),
        ArchiveStatus(1),
        CreateTransition(1, 2, 3),
        ArchiveTransition(1),
        CreateTrack(1, "auth", description = "blurb", metadata = mapOf("jira_key" to "AUTH-1")),
        UpdateTrack(1, name = "auth2", description = "d", metadata = emptyMap()),
        ArchiveTrack(1),
        CreateSegment(1, "seg", parentSegmentId = 2),
        RenameSegment(1, "seg2", expectedVersion = 3),
        MoveSegment(1, newParentSegmentId = null),
        ArchiveSegment(1),
        CreateTask(1, 2, "title", kind = "impl", description = "d", priority = 5),
        UpdateTask(1, TaskPatch(title = "t", priority = 9, kind = "review"), expectedVersion = 7),
        MoveTask(1, 2),
        MoveTaskToSegment(1, 5, expectedVersion = 2),
        ArchiveTask(1),
        AddBlocks(1, 2),
        ArchiveBlocks(1),
        AddRelatesTo("spawns", 1, 2),
        ArchiveRelatesTo(1),
        SetMetaKey(MetaEntity.TASK, 1, "jira_key", "AUTH-1", expectedVersion = 4),
        DeleteMetaKey(MetaEntity.WORKSPACE, 1, "stale"),
    )

    @Test fun `every command round-trips through json`() {
        for (cmd in all) {
            val text = json.encodeToString(Command.serializer(), cmd)
            val back = json.decodeFromString(Command.serializer(), text)
            assertEquals(cmd, back, "round-trip mismatch for ${cmd::class.simpleName}: $text")
        }
    }
}
