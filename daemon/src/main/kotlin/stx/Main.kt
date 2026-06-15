package stx

import org.apache.logging.log4j.kotlin.logger
import stx.log.Sidecar
import stx.repo.Db
import stx.service.Reads
import stx.service.Service
import stx.service.WriteActor
import stx.transport.HttpApi
import stx.transport.LoopbackServer
import java.nio.file.Path

private val log = logger("stx.Main")

const val DEFAULT_PORT = 8473

private fun arg(args: Array<String>, name: String): String? =
    args.firstOrNull { it.startsWith("--$name=") }?.substringAfter("=")

private fun defaultDbPath(): String {
    val data = System.getenv("XDG_DATA_HOME")?.takeIf { it.isNotBlank() }
        ?: (System.getProperty("user.home") + "/.local/share")
    return Path.of(data, "stx", "stx.db").toString()
}

fun main(args: Array<String>) {
    val port = arg(args, "port")?.toIntOrNull() ?: DEFAULT_PORT
    val dbPath = arg(args, "db") ?: defaultDbPath()
    Path.of(dbPath).parent?.let { java.nio.file.Files.createDirectories(it) }

    val db = Db.forFile(dbPath)
    db.init()

    val sidecar = Sidecar(Sidecar.defaultPath())
    val actor = WriteActor(db, Service()) { command, result -> sidecar.record(command, result) }
    actor.start()

    val reads = Reads(db)
    val api = HttpApi(reads, writeFn = actor::submitBlocking)
    val server = LoopbackServer(port, api.handler())
    val bound = server.start()
    log.info { "stx daemon listening on 127.0.0.1:$bound  (db=$dbPath)" }

    Runtime.getRuntime().addShutdownHook(
        Thread {
            server.stop()
            actor.stop()
        },
    )
}
