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

    fun transcribe(wav: ByteArray, language: String?): String {
        val boundary = "edith" + System.currentTimeMillis()
        val body = ByteArrayOutputStream().apply {
            fun line(s: String) = write((s + "\r\n").toByteArray())
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
    fun assistant(message: String, history: List<Turn>, language: String?, followup: Boolean = false): Assistant {
        val payload = JSONObject()
            .put("message", message)
            .put("mode", "earbud")
            .put("followup", followup)
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

    data class MeetingHelp(val question: String?, val answer: String?)

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
    ): String {
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
            val text = stream?.bufferedReader()?.use { it.readText() } ?: ""
            if (code !in 200..299) {
                val msg = runCatching { JSONObject(text).getJSONObject("error").getString("message") }
                    .getOrDefault("Server error (HTTP $code)")
                throw EdithException(if (code == 401) "Wrong EDITH password." else msg)
            }
            return text
        } catch (e: EdithException) {
            throw e
        } catch (e: UnknownHostException) {
            throw EdithException("No internet connection, or the server address is wrong.")
        } catch (e: SocketTimeoutException) {
            throw EdithException("The EDITH server took too long to answer.")
        } catch (e: IOException) {
            throw EdithException("Could not reach the EDITH server.")
        } finally {
            conn.disconnect()
        }
    }
}
