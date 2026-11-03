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

    /** Country calling code used for WhatsApp numbers saved without one (e.g. 91 for India). */
    var countryCode: String
        get() = p.getString("country_code", "") ?: ""
        set(v) = p.edit().putString("country_code", v.filter { it.isDigit() }.take(4)).apply()

    /** Registered headphones ("address|name" per entry). */
    var trustedHeadphones: List<Headphones.Device>
        get() = (p.getStringSet("trusted_headphones", emptySet()) ?: emptySet()).map { Headphones.Device.decode(it) }
        set(v) = p.edit().putStringSet("trusted_headphones", v.map { it.encode() }.toSet()).apply()

    /** Only listen while registered headphones are connected (when any are registered). */
    var headphoneLock: Boolean
        get() = p.getBoolean("headphone_lock", true)
        set(v) = p.edit().putBoolean("headphone_lock", v).apply()

    val headphoneLockActive: Boolean get() = headphoneLock && trustedHeadphones.isNotEmpty()

    /** "About me" text, also saved on the server as profile memories. */
    var aboutMe: String
        get() = p.getString("about_me", "") ?: ""
        set(v) = p.edit().putString("about_me", v).apply()

    /** Remembered contact choices: what you say ("mom") -> saved contact name ("Mom Jio"). */
    var contactAliases: Map<String, String>
        get() = (p.getStringSet("contact_aliases", emptySet()) ?: emptySet())
            .mapNotNull { e -> e.split('|', limit = 2).takeIf { it.size == 2 }?.let { it[0] to it[1] } }.toMap()
        set(v) = p.edit().putStringSet("contact_aliases", v.map { "${it.key}|${it.value}" }.toSet()).apply()

    fun rememberContact(spoken: String, contactName: String) {
        contactAliases = contactAliases + (PhoneActions.normalise(spoken).removePrefix("my ").trim() to contactName)
    }

    /** How EDITH addresses you ("sir", "boss", your name). */
    var address: String
        get() = (p.getString("address", "sir") ?: "sir").ifBlank { "sir" }
        set(v) = p.edit().putString("address", v.trim().take(30)).apply()

    /** Natural, human-like voice from the server (Groq Orpheus); falls back to the phone voice. */
    var humanVoice: Boolean
        get() = p.getBoolean("human_voice_v2", false) // off by default: Groq's voice quota runs out fast
        set(v) = p.edit().putBoolean("human_voice_v2", v).apply()

    /** Phone (offline) voice name; blank = pick the most natural one automatically. */
    var phoneVoice: String
        get() = p.getString("phone_voice", "") ?: ""
        set(v) = p.edit().putString("phone_voice", v).apply()

    var speechRate: Float
        get() = p.getFloat("speech_rate", 1.0f)
        set(v) = p.edit().putFloat("speech_rate", v.coerceIn(0.6f, 1.6f)).apply()

    var speechPitch: Float
        get() = p.getFloat("speech_pitch", 1.0f)
        set(v) = p.edit().putFloat("speech_pitch", v.coerceIn(0.7f, 1.4f)).apply()

    /** Orpheus voice: autumn, diana, hannah, austin, daniel, troy. */
    var voiceName: String
        get() = p.getString("voice_name", "hannah") ?: "hannah"
        set(v) = p.edit().putString("voice_name", v).apply()

    /** Names/words EDITH should recognise (comma separated), sent as spelling hints to speech-to-text. */
    var extraWords: String
        get() = p.getString("extra_words", "") ?: ""
        set(v) = p.edit().putString("extra_words", v.take(400)).apply()

    /** Spelling hints for speech-to-text: your name from About me + your words. */
    fun hearingHints(): String {
        val name = Regex("(?i)my name is ([\\p{L}]+(?: [\\p{L}]+)?)").find(aboutMe)?.groupValues?.get(1)
        return listOfNotNull("EDITH", name, extraWords.takeIf { it.isNotBlank() }).joinToString(", ")
    }

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
