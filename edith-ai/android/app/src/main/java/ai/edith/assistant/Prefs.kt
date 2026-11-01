package ai.edith.assistant

import android.content.Context
import java.io.File

/** App settings, stored privately on the phone (only this app can read them). */
class Prefs(context: Context) {
    private val p = context.getSharedPreferences("edith", Context.MODE_PRIVATE)
    private val filesDir = context.filesDir

    var serverUrl: String
        get() = p.getString("server_url", "") ?: ""
        set(v) = p.edit().putString("server_url", normalizeUrl(v)).apply()

    var password: String
        get() = p.getString("password", "") ?: ""
        set(v) = p.edit().putString("password", v.trim()).apply()

    var picovoiceKey: String
        get() = p.getString("picovoice_key", "") ?: ""
        set(v) = p.edit().putString("picovoice_key", v.trim()).apply()

    /** "custom" = the trained "Edith" .ppn file; "jarvis" = built-in test word. */
    var wakeWord: String
        get() = p.getString("wake_word", "custom") ?: "custom"
        set(v) = p.edit().putString("wake_word", v).apply()

    var sensitivity: Float
        get() = p.getFloat("sensitivity", 0.6f)
        set(v) = p.edit().putFloat("sensitivity", v.coerceIn(0.1f, 0.95f)).apply()

    /** "headset" = Bluetooth headphone mic when connected; "phone" = the phone's own mic. */
    var micSource: String
        get() = p.getString("mic_source", "headset") ?: "headset"
        set(v) = p.edit().putString("mic_source", v).apply()

    var mediaButton: Boolean
        get() = p.getBoolean("media_button", false)
        set(v) = p.edit().putBoolean("media_button", v).apply()

    val keywordFile: File get() = File(filesDir, "edith_wake_word.ppn")
    val hasKeywordFile: Boolean get() = keywordFile.isFile && keywordFile.length() > 0

    /** What is missing before EDITH can listen, or null when ready. */
    fun missing(): String? = when {
        serverUrl.isBlank() -> "Enter your EDITH server address."
        password.isBlank() -> "Enter your EDITH password."
        picovoiceKey.isBlank() -> "Enter your Picovoice AccessKey."
        wakeWord == "custom" && !hasKeywordFile ->
            "Choose your 'Edith' wake-word file (.ppn), or use the test word 'Jarvis'."
        else -> null
    }

    companion object {
        fun normalizeUrl(raw: String): String {
            var u = raw.trim().trimEnd('/')
            if (u.isNotEmpty() && !u.startsWith("http://") && !u.startsWith("https://")) u = "https://$u"
            return u
        }
    }
}
