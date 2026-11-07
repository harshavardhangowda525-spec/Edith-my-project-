package ai.edith.assistant

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import java.net.ServerSocket
import kotlin.concurrent.thread

/** A tiny HTTP server on a plain socket: answers each request with server-sent events. */
class StreamingTest {
    private lateinit var server: ServerSocket
    private var port = 0

    @Before fun start() {
        server = ServerSocket(0)
        port = server.localPort
        thread(isDaemon = true) {
            while (!server.isClosed) {
                val sock = runCatching { server.accept() }.getOrNull() ?: break
                thread(isDaemon = true) {
                    sock.use { s ->
                        val input = s.getInputStream().bufferedReader(Charsets.ISO_8859_1)
                        val requestLine = input.readLine() ?: return@use
                        var length = 0
                        while (true) {
                            val h = input.readLine() ?: break
                            if (h.isEmpty()) break
                            if (h.lowercase().startsWith("content-length:")) length = h.substringAfter(":").trim().toInt()
                        }
                        repeat(length) { input.read() }
                        val out = s.getOutputStream()
                        out.write("HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n".toByteArray())
                        out.flush()
                        val events = if (requestLine.contains("/api/voice/ask"))
                            listOf("""{"type":"error","message":"Groq rate limit"}""")
                        else listOf("""{"type":"meta","route":"fast","model":"m"}""", """{"type":"token","t":"Hello"}""",
                                    """{"type":"token","t":" sir."}""", """{"type":"done","timings":{}}""")
                        for (ev in events) {
                            out.write("data: $ev\n\n".toByteArray()); out.flush()
                            Thread.sleep(300) // events arrive over time, like a real model
                        }
                    }
                }
            }
        }
    }

    @After fun stop() = server.close()

    private val api get() = EdithApi("http://127.0.0.1:$port", "pw")

    @Test fun eventsArriveWhileStreaming() {
        val t0 = System.currentTimeMillis()
        val got = mutableListOf<Pair<String, Long>>()
        api.assistantStream("hi", emptyList(), "en", false, "sir", null) { ev ->
            got += ev.getString("type") to (System.currentTimeMillis() - t0); true
        }
        assertEquals(listOf("meta", "token", "token", "done"), got.map { it.first })
        // The first event came long before the stream finished (true streaming, not buffered).
        assertTrue("first ${got[0].second} ms, last ${got.last().second} ms", got.last().second - got[0].second >= 800)
    }

    @Test fun stopReadingOnBargeIn() {
        val got = mutableListOf<String>()
        api.assistantStream("hi", emptyList(), "en", false, null, null) { ev ->
            got += ev.getString("type"); got.size < 2 // stop after the second event
        }
        assertEquals(listOf("meta", "token"), got)
    }

    @Test fun serverErrorEventBecomesException() {
        try {
            api.voiceAsk(ByteArray(10), "en", null, emptyList(), false, null, null) { true }
            fail("expected EdithException")
        } catch (e: EdithException) {
            assertEquals("Groq rate limit", e.message)
        }
    }

    @Test fun speakAtSentenceEnds() {
        assertEquals(0, EdithService.speakableEnd("Sure"))
        assertEquals(0, EdithService.speakableEnd("Hi."))                       // too short to bother the voice
        assertEquals("Tokyo is the capital. ".length, EdithService.speakableEnd("Tokyo is the capital. It has"))
        assertEquals(0, EdithService.speakableEnd("Version 3.5 is out"))       // a decimal point is not a sentence end
        val long = "When you deploy your app to Vercel, the build runs on their servers in the cloud, "
        assertEquals(long.length, EdithService.speakableEnd(long + "then"))   // long phrase: break at the comma
    }
}
