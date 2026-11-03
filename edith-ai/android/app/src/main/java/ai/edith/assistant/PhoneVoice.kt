package ai.edith.assistant

import android.speech.tts.TextToSpeech
import android.speech.tts.Voice
import java.util.Locale

/** Picks and applies the most natural voice installed on the phone. */
object PhoneVoice {

    /** English voices that work offline, best first (quality, then Indian/US/UK English). */
    fun candidates(tts: TextToSpeech): List<Voice> {
        val voices = runCatching { tts.voices }.getOrNull().orEmpty()
        val preferred = listOf(Locale.getDefault().toLanguageTag(), "en-IN", "en-US", "en-GB", "en-AU")
        return voices
            .filter { it.locale.language == "en" || it.locale.language == Locale.getDefault().language }
            .filter { !it.isNetworkConnectionRequired } // network voices stall without internet
            .filter { it.features?.contains(TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED) != true }
            .sortedWith(
                compareByDescending<Voice> { it.quality }
                    .thenBy { v -> preferred.indexOf(v.locale.toLanguageTag()).let { if (it < 0) 99 else it } }
                    .thenBy { it.name },
            )
    }

    /** Applies the chosen voice (or the best one) plus speed and pitch. */
    fun apply(tts: TextToSpeech, prefs: Prefs) {
        val all = candidates(tts)
        val chosen = all.firstOrNull { it.name == prefs.phoneVoice } ?: all.firstOrNull()
        if (chosen != null) runCatching { tts.voice = chosen } else tts.language = Locale.getDefault()
        tts.setSpeechRate(prefs.speechRate)
        tts.setPitch(prefs.speechPitch)
    }

    /** Short, human-readable label like "English (India) · very high quality · en-in-x-ene". */
    fun label(v: Voice): String {
        val q = when {
            v.quality >= Voice.QUALITY_VERY_HIGH -> "very high quality"
            v.quality >= Voice.QUALITY_HIGH -> "high quality"
            else -> "normal quality"
        }
        return "${v.locale.displayName} · $q · ${v.name}"
    }
}
