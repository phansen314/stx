package stx.transport

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import org.http4k.core.HttpHandler
import org.http4k.core.Method
import org.http4k.core.Request
import org.http4k.core.Response
import org.http4k.core.Status
import org.http4k.core.Uri
import java.net.InetAddress
import java.net.InetSocketAddress
import java.util.concurrent.Executors

/**
 * Minimal HTTP server bound to the loopback interface ONLY (127.0.0.1).
 *
 * Loopback binding is the entire security model (brief §1): any local process may reach
 * the daemon, nothing off-box can. We bridge the JDK [HttpServer] to an http4k [HttpHandler]
 * directly rather than depend on http4k's server backend, so binding stays explicit and the
 * "127.0.0.1 only" invariant is impossible to misconfigure.
 *
 * The JDK server's thread pool gives us concurrent reads against WAL for free; mutations are
 * still serialized downstream by the write-actor, not here.
 */
class LoopbackServer(private val port: Int, private val handler: HttpHandler) {
    private val server: HttpServer =
        HttpServer.create(InetSocketAddress(InetAddress.getLoopbackAddress(), port), 0)

    init {
        server.executor = Executors.newFixedThreadPool(
            (Runtime.getRuntime().availableProcessors()).coerceAtLeast(2),
        )
        server.createContext("/") { exchange -> dispatch(exchange) }
    }

    /** Start serving. Returns the actual bound port (useful when [port] is 0 = ephemeral). */
    fun start(): Int {
        server.start()
        return server.address.port
    }

    fun stop() = server.stop(0)

    fun boundAddress(): InetSocketAddress = server.address

    private fun dispatch(exchange: HttpExchange) {
        exchange.use {
            val response = try {
                handler(exchange.toRequest())
            } catch (e: Exception) {
                Response(Status.INTERNAL_SERVER_ERROR).body(e.message ?: "internal error")
            }
            exchange.write(response)
        }
    }

    private fun HttpExchange.toRequest(): Request {
        var req = Request(Method.valueOf(requestMethod), Uri.of(requestURI.toString()))
        requestHeaders.forEach { (name, values) -> values.forEach { req = req.header(name, it) } }
        val bodyBytes = requestBody.readBytes()
        if (bodyBytes.isNotEmpty()) req = req.body(String(bodyBytes, Charsets.UTF_8))
        return req
    }

    private fun HttpExchange.write(response: Response) {
        response.headers.forEach { (name, value) -> if (value != null) responseHeaders.add(name, value) }
        val payload = response.bodyString().toByteArray(Charsets.UTF_8)
        // Content length 0 with no body would force chunked; use -1 for "no body", else actual length.
        sendResponseHeaders(response.status.code, if (payload.isEmpty()) -1 else payload.size.toLong())
        if (payload.isNotEmpty()) responseBody.write(payload)
    }
}
