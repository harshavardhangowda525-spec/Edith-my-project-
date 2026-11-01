package ai.edith.assistant

import android.content.Context

/** App settings, stored privately on the phone (only this app can read them). */
class Prefs(context: Context) {
    private val p = context.getSharedPreferences("edith", Context.MODE_PRIVATE)

    var serverUrl: String
        get() = p.getString("server_url", "") ?: ""
        set(v) = p.edit().putString("server_url", normalizeUrl(v)).apply()

    var password: String
        get() = p.getString("password", "") ?: ""
        set(v) = p.edit().putString("password", v.trim()).apply()

    /** true: wake only when "Edith" / "Hey Edith" is said on its own (fewer false wake-ups). */
    var strictWake: Boolean
        get() = p.getBoolean("strict_wake", true)
        set(v) = p.edit().putBoolean("strict_wake", v).apply()

    /** "headset" = Bluetooth headphone mic when connected; "phone" = the phone's own mic. */
    var micSource: String
        get() = p.getString("mic_source", "headset") ?: "headset"
        set(v) = p.edit().putString("mic_source", v).apply()

    var mediaButton: Boolean
        get() = p.getBoolean("media_button", false)
        set(v) = p.edit().putBoolean("media_button", v).apply()

    /** After "Edith", keep listening for follow-up questions (ignores side conversations). */
    var conversationMode: Boolean
        get() = p.getBoolean("conversation_mode", true)
        set(v) = p.edit().putBoolean("conversation_mode", v).apply()

    /** What "play my favourite music" plays, e.g. "Liked Songs", "Arijit Singh" (blank = app's pick). */
    var favoriteMusic: String
        get() = p.getString("favorite_music", "") ?: ""
        set(v) = p.edit().putString("favorite_music", v).apply()

    /** Default music app key: spotify, youtube_music, jiosaavn, ... */
    var musicApp: String
        get() = p.getString("music_app", "spotify") ?: "spotify"
        set(v) = p.edit().putString("music_app", v).apply()

    /** What is missing before EDITH can listen, or null when ready. */
    fun missing(): String? = when {
        serverUrl.isBlank() -> "Enter your EDITH server address."
        password.isBlank() -> "Enter your EDITH password."
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
