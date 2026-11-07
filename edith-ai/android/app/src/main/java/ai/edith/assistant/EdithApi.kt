package ai.edith.assistant

import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.URL
import java.net.UnknownHostException

class EdithException(message: String) : Exception(message)

/** Talks to your EDITH server (the same one the website uses). Blocking: call off the main thread. */
class EdithApi(private val baseUrl: String, private val password: String) {

    data class Turn(val role: String, val content: String)

    fun health(): JSONObject = JSONObject(request("GET", "/health", auth = false))

    /** Checks the password with a cheap authenticated call. */
    fun checkPassword() {
        request("GET", "/api/memory/settings")
    }

    fun transcribe(wav: ByteArray, language: String?, hints: String? = null): String {
        val boundary = "edith" + System.currentTimeMillis()
        val body = ByteArrayOutputStream().apply {
            fun line(s: String) = write((s + "\r\n").toByteArray())
            if (!hints.isNullOrBlank()) {
                line("--$boundary")
                line("Content-Disposition: form-data; name=\"prompt\"")
                line("")
                line(hints.take(700))
            }
            if (!language.isNullOrBlank()) {
                line("--$boundary")
                line("Content-Disposition: form-data; name=\"language\"")
                line("")
                line(language)
            }
            line("--$boundary")
            line("Content-Disposition: form-data; name=\"audio\"; filename=\"question.wav\"")
            line("Content-Type: audio/wav")
            line("")
            write(wav)
            line("")
            line("--$boundary--")
        }.toByteArray()
        val res = request("POST", "/api/voice/transcribe", body, "multipart/form-data; boundary=$boundary")
        return JSONObject(res).optString("text").trim()
    }

    fun chat(message: String, history: List<Turn>, language: String?): String {
        val payload = JSONObject()
            .put("message", message)
            .put("mode", "earbud")
            .put("history", JSONArray().apply {
                history.takeLast(12).forEach { put(JSONObject().put("role", it.role).put("content", it.content)) }
            })
        if (!language.isNullOrBlank()) payload.put("language", language)
        val res = request("POST", "/api/chat", payload.toString().toByteArray(), "application/json")
        return JSONObject(res).optString("reply").trim()
    }

    /** kind: "action" | "answer" | "ignore" (not meant for EDITH) | "end" (stop conversation mode) */
    data class Assistant(val kind: String, val action: JSONObject?, val say: String, val reply: String)

    /**
     * Voice entry point: a phone action to perform, or a spoken answer.
     * followup = heard in conversation mode without the wake word (may be meant for someone else).
     */
    fun assistant(message: String, history: List<Turn>, language: String?, followup: Boolean = false,
                  address: String? = null): Assistant {
        val payload = JSONObject()
            .put("message", message)
            .put("mode", "earbud")
            .put("followup", followup)
        if (!address.isNullOrBlank()) payload.put("address", address)
            .put("history", JSONArray().apply {
                history.takeLast(12).forEach { put(JSONObject().put("role", it.role).put("content", it.content)) }
            })
        if (!language.isNullOrBlank()) payload.put("language", language)
        val res = JSONObject(request("POST", "/api/assistant", payload.toString().toByteArray(), "application/json"))
        return Assistant(
            kind = res.optString("kind", "answer"),
            action = if (res.optString("kind") == "action") res.optJSONObject("action") else null,
            say = if (res.isNull("say")) "" else res.optString("say"),
            reply = if (res.isNull("reply")) "" else res.optString("reply").trim(),
        )
    }

    /** Businesses without a website (Google Places), as JSON objects from the server. */
    fun findLeads(query: String, max: Int = 20): List<JSONObject> {
        val payload = JSONObject().put("query", query).put("max_leads", max)
        val res = JSONObject(request("POST", "/api/leads/search", payload.toString().toByteArray(), "application/json"))
        val arr = res.optJSONArray("leads") ?: JSONArray()
        return (0 until arr.length()).map { arr.getJSONObject(it) }
    }

    fun saveLead(lead: JSONObject, status: String = "new") {
        val body = JSONObject(lead.toString()).put("status", status)
        listOf("rating", "reviews").forEach { if (body.isNull(it)) body.remove(it) }
        request("POST", "/api/leads", body.toString().toByteArray(), "application/json")
    }

    /** Human-like speech (WAV/MP3 bytes) from the server's voice model. */
    fun speakAudio(text: String, voice: String?, style: String? = null): ByteArray {
        val payload = JSONObject().put("text", text.take(2400))
        if (!voice.isNullOrBlank()) payload.put("voice", voice)
        if (!style.isNullOrBlank()) payload.put("style", style)
        return requestBytes("POST", "/api/voice/speak", payload.toString().toByteArray(), "application/json")
    }

    data class EmailDraft(val subject: String, val body: String)

    fun emailDraft(toName: String, instruction: String): EmailDraft {
        val payload = JSONObject().put("to_name", toName).put("instruction", instruction)
        val res = JSONObject(request("POST", "/api/email/draft", payload.toString().toByteArray(), "application/json"))
        return EmailDraft(res.optString("subject"), res.optString("body"))
    }

    /** Only call after the user heard the draft and said yes. */
    fun emailSend(to: String, draft: EmailDraft) {
        val payload = JSONObject().put("to", to).put("subject", draft.subject).put("body", draft.body)
            .put("confirmed", true)
        request("POST", "/api/email/send", payload.toString().toByteArray(), "application/json")
    }

    /**
     * Replaces the "About me" profile on the server: one memory (category "profile") per line.
     * Profile memories are always included in EDITH's answers.
     */
    fun saveProfile(text: String) {
        val existing = JSONArray(request("GET", "/api/memory"))
        for (i in 0 until existing.length()) {
            val m = existing.getJSONObject(i)
            if (m.optString("category") == "profile") request("DELETE", "/api/memory/" + m.getString("id"))
        }
        text.lines().map { it.trim() }.filter { it.isNotEmpty() }.flatMap { it.chunked(900) }.take(10).forEach {
            val body = JSONObject().put("content", it).put("category", "profile")
            request("POST", "/api/memory", body.toString().toByteArray(), "application/json")
        }
    }

    /** Device context sent with each question: local time (with zone) and battery percent. */
    data class Device(val time: String, val battery: Int?)

    /**
     * One round trip for a spoken question: uploads the audio and reads the streamed answer.
     * [onEvent] gets each server event (transcript, meta, token, action, ignore, end, done, error)
     * as it arrives; return false to stop reading (barge-in).
     */
    fun voiceAsk(wav: ByteArray, language: String?, hints: String?, history: List<Turn>, followup: Boolean,
                 address: String?, device: Device?, onEvent: (JSONObject) -> Boolean) {
        val boundary = "edith" + System.nanoTime()
        val body = ByteArrayOutputStream().apply {
            fun line(s: String) = write((s + "\r\n").toByteArray())
            fun field(name: String, value: String?) {
                if (value.isNullOrBlank()) return
                line("--$boundary"); line("Content-Disposition: form-data; name=\"$name\""); line(""); line(value)
            }
            field("language", language)
            field("prompt", hints?.take(700))
            field("history", JSONArray().apply {
                history.takeLast(12).forEach { put(JSONObject().put("role", it.role).put("content", it.content)) }
            }.toString())
            field("followup", followup.toString())
            field("address", address)
            field("client_time", device?.time)
            field("battery", device?.battery?.toString())
            line("--$boundary")
            line("Content-Disposition: form-data; name=\"audio\"; filename=\"question.wav\"")
            line("Content-Type: audio/wav")
            line("")
            write(wav)
            line("")
            line("--$boundary--")
        }.toByteArray()
        stream("/api/voice/ask", body, "multipart/form-data; boundary=$boundary", onEvent)
    }

    /** Streamed answer for text (used when the phone already has the transcript). */
    fun assistantStream(message: String, history: List<Turn>, language: String?, followup: Boolean,
                        address: String?, device: Device?, onEvent: (JSONObject) -> Boolean) {
        val payload = JSONObject().put("message", message).put("mode", "earbud").put("followup", followup)
            .put("history", JSONArray().apply {
                history.takeLast(12).forEach { put(JSONObject().put("role", it.role).put("content", it.content)) }
            })
        if (!language.isNullOrBlank()) payload.put("language", language)
        if (!address.isNullOrBlank()) payload.put("address", address)
        device?.let { d -> payload.put("client_time", d.time); d.battery?.let { payload.put("battery", it) } }
        stream("/api/assistant/stream", payload.toString().toByteArray(), "application/json", onEvent)
    }

    private fun stream(path: String, body: ByteArray, contentType: String, onEvent: (JSONObject) -> Boolean) {
        val conn = try {
            URL(baseUrl.trimEnd('/') + path).openConnection() as HttpURLConnection
        } catch (e: Exception) {
            throw EdithException("The EDITH server address looks wrong.")
        }
        try {
            conn.requestMethod = "POST"
            conn.connectTimeout = 20_000
            conn.readTimeout = 70_000
            conn.doOutput = true
            conn.setRequestProperty("Authorization", "Bearer $password")
            conn.setRequestProperty("Content-Type", contentType)
            conn.setRequestProperty("Accept", "text/event-stream")
            conn.setFixedLengthStreamingMode(body.size)
            conn.outputStream.use { it.write(body) }
            val code = conn.responseCode
            if (code !in 200..299) {
                val text = conn.errorStream?.use { String(it.readBytes()) } ?: ""
                val msg = runCatching { JSONObject(text).getJSONObject("error").getString("message") }
                    .getOrDefault("Server error (HTTP $code)")
                throw EdithException(if (code == 401) "Wrong EDITH password." else msg)
            }
            conn.inputStream.bufferedReader().use { reader ->
                while (true) {
                    val line = reader.readLine() ?: break
                    if (!line.startsWith("data:")) continue
                    val ev = runCatching { JSONObject(line.substring(5).trim()) }.getOrNull() ?: continue
                    if (ev.optString("type") == "error") throw EdithException(ev.optString("message", "Server error"))
                    if (!onEvent(ev)) {
                        conn.disconnect() // barge-in: stop the download now
                        return
                    }
                }
            }
        } catch (e: EdithException) {
            throw e
        } catch (e: UnknownHostException) {
            throw EdithException("No internet connection, or the server address is wrong.")
        } catch (e: SocketTimeoutException) {
            throw EdithException("The EDITH server took too long to answer.")
        } catch (e: IOException) {
            throw EdithException("Could not reach the EDITH server.")
        }
    }

    data class MeetingHelp(val question: String?, val answer: String?)

    /** A background task on the server (research, GitHub summary, a job on your PC). */
    data class TaskInfo(val id: String, val title: String, val status: String, val result: String?, val error: String?) {
        val finished get() = status == "completed" || status == "failed" || status == "cancelled"
    }

    fun task(id: String): TaskInfo {
        val t = JSONObject(request("GET", "/api/tasks/$id"))
        fun str(key: String) = if (t.isNull(key)) null else t.optString(key).ifBlank { null }
        return TaskInfo(t.optString("id"), t.optString("title"), t.optString("status"), str("result"), str("error"))
    }

    /** Live meeting help. Returns answer = null when there is nothing worth answering. */
    fun meetingAssist(transcript: List<String>, force: Boolean, language: String?): MeetingHelp {
        val payload = JSONObject()
            .put("transcript", JSONArray(transcript.takeLast(12)))
            .put("force", force)
            .put("consent_confirmed", true) // confirmed by the user when switching Meeting mode on
        if (!language.isNullOrBlank()) payload.put("language", language)
        val res = JSONObject(request("POST", "/api/meeting/assist", payload.toString().toByteArray(), "application/json"))
        fun str(key: String) = if (res.isNull(key)) null else res.optString(key).trim().ifBlank { null }
        return MeetingHelp(str("question"), str("answer"))
    }

    private fun request(
        method: String, path: String, body: ByteArray? = null,
        contentType: String? = null, auth: Boolean = true,
    ): String = String(requestBytes(method, path, body, contentType, auth))

    private fun requestBytes(
        method: String, path: String, body: ByteArray? = null,
        contentType: String? = null, auth: Boolean = true,
    ): ByteArray {
        val conn = try {
            URL(baseUrl.trimEnd('/') + path).openConnection() as HttpURLConnection
        } catch (e: Exception) {
            throw EdithException("The EDITH server address looks wrong.")
        }
        try {
            conn.requestMethod = method
            conn.connectTimeout = 20_000
            conn.readTimeout = 70_000 // the free Render plan may need ~60 s to wake up
            if (auth) conn.setRequestProperty("Authorization", "Bearer $password")
            if (body != null) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", contentType ?: "application/octet-stream")
                conn.setFixedLengthStreamingMode(body.size)
                conn.outputStream.use { it.write(body) }
            }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val bytes = stream?.use { it.readBytes() } ?: ByteArray(0)
            val text = if (code in 200..299) "" else String(bytes)
            if (code !in 200..299) {
                val msg = runCatching { JSONObject(text).getJSONObject("error").getString("message") }
                    .getOrDefault("Server error (HTTP $code)")
                throw EdithException(if (code == 401) "Wrong EDITH password." else msg)
            }
            return bytes
        } catch (e: EdithException) {
            throw e
        } catch (e: UnknownHostException) {
            throw EdithException("No internet connection, or the server address is wrong.")
        } catch (e: SocketTimeoutException) {
            throw EdithException("The EDITH server took too long to answer.")
        } catch (e: IOException) {
            throw EdithException("Could not reach the EDITH server.")
        }
        // No disconnect(): Android keeps the connection alive and re-uses it for the next request,
        // which skips a new TLS handshake (often 100-300 ms on mobile networks).
    }
}
