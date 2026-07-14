package stx.transport

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import org.http4k.core.HttpHandler
import org.http4k.core.Method
import org.http4k.core.Request
import org.http4k.core.Response
import org.http4k.core.Status
import org.http4k.server.Http4kServer
import org.http4k.server.ServerConfig
import java.net.InetAddress
import java.net.InetSocketAddress
import java.util.concurrent.Executors

/**
 * http4k's bundled [org.http4k.server.SunHttp] only takes a port and binds the wildcard
 * address (0.0.0.0). stx's entire security model is loopback-only binding (brief §1), so
 * we supply our own [ServerConfig] backed by the JDK's [HttpServer] bound explicitly to
 * the loopback address. Requests are dispatched on virtual threads (JDK 21) so blocking
 * handlers — reads, and the write-actor bridge — run concurrently without a fixed pool.
 */
class LoopbackSunHttp(private val port: Int) : ServerConfig {
    override fun toServer(http: HttpHandler): Http4kServer = object : Http4kServer {
        private val server: HttpServer =
            HttpServer.create(InetSocketAddress(InetAddress.getLoopbackAddress(), port), 0).apply {
                executor = Executors.newVirtualThreadPerTaskExecutor()
                createContext("/") { exchange -> dispatch(exchange, http) }
            }

        override fun start(): Http4kServer = apply { server.start() }
        override fun stop(): Http4kServer = apply { server.stop(0) }
        override fun port(): Int = server.address.port
    }

    private fun dispatch(exchange: HttpExchange, http: HttpHandler) {
        exchange.use {
            // An unrecognized HTTP verb is a client fault (405), not a server defect (500).
            val method = runCatching { Method.valueOf(it.requestMethod) }.getOrNull()
            val response = if (method == null) {
                Response(Status.METHOD_NOT_ALLOWED)
            } else try {
                http(it.asRequest(method))
            } catch (t: Throwable) {
                Response(Status.INTERNAL_SERVER_ERROR)
            }
            // A client that disconnects mid-response throws here; the request is already served, so
            // swallow it rather than let it escape the virtual thread.
            runCatching { it.write(response) }
        }
    }

    private fun HttpExchange.asRequest(method: Method): Request {
        val headers = requestHeaders.entries.flatMap { (k, vs) -> vs.map { v -> k to v } }
        val length = requestHeaders.getFirst("Content-Length")?.toLongOrNull()
        return Request(method, requestURI.toString())
            .headers(headers)
            .body(requestBody, length)
    }

    private fun HttpExchange.write(response: Response) {
        response.headers.forEach { (k, v) ->
            // The JDK server owns Content-Length / Transfer-Encoding; setting them throws.
            if (v != null && !k.equals("Content-Length", true) && !k.equals("Transfer-Encoding", true)) {
                responseHeaders.add(k, v)
            }
        }
        val bytes = response.body.stream.readBytes()
        sendResponseHeaders(response.status.code, if (bytes.isEmpty()) -1L else bytes.size.toLong())
        if (bytes.isNotEmpty()) responseBody.use { it.write(bytes) }
    }
}
