package ai.edith.assistant

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.ToneGenerator
import android.media.session.MediaSession
import android.media.session.PlaybackState
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Log
import android.view.KeyEvent
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import org.json.JSONArray
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer
import org.vosk.android.StorageService
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Locale
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.sqrt

/** Live status shared with the screen. */
object EdithState {
    @Volatile var running = false
    @Volatile var status = "Stopped"
    @Volatile var lastQuestion = ""
    @Volatile var lastAnswer = ""
    private val main = Handler(Looper.getMainLooper())
    private val listeners = mutableSetOf<() -> Unit>()

    fun addListener(l: () -> Unit) = listeners.add(l)
    fun removeListener(l: () -> Unit) = listeners.remove(l)
    fun update(status: String? = null, question: String? = null, answer: String? = null) {
        status?.let { this.status = it }
        question?.let { lastQuestion = it }
        answer?.let { lastAnswer = it }
        main.post { listeners.toList().forEach { it() } }
    }
}

/**
 * Always-on EDITH: listens on-device for the wake word (Vosk, offline), then records one question,
 * sends it to your EDITH server and speaks the answer. Audio never leaves the phone
 * until the wake word is heard. A notification is shown the whole time it listens.
 */
class EdithService : Service() {

    private val running = AtomicBoolean(false)
    private val askNow = AtomicBoolean(false)
    private var worker: Thread? = null
    private var tts: TextToSpeech? = null
    private val ttsReady = CountDownLatch(1)
    private var wakeLock: PowerManager.WakeLock? = null
    private var mediaSession: MediaSession? = null
    private lateinit var routing: AudioRouting
    private val history = ArrayDeque<EdithApi.Turn>()

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        routing = AudioRouting(this)
        createChannel()
        tts = TextToSpeech(this) { status ->
            if (status == TextToSpeech.SUCCESS) tts?.language = Locale.getDefault()
            ttsReady.countDown()
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopSelf()
                return START_NOT_STICKY
            }
            ACTION_ASK -> askNow.set(true)
        }
        startInForeground("Starting…")
        if (running.compareAndSet(false, true)) {
            EdithState.running = true
            acquireWakeLock()
            setupMediaButton()
            worker = Thread({ listenLoop() }, "edith-listener").also { it.start() }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        running.set(false)
        worker?.interrupt()
        worker?.join(1500)
        mediaSession?.release()
        tts?.shutdown()
        routing.release()
        wakeLock?.takeIf { it.isHeld }?.release()
        EdithState.running = false
        EdithState.update(status = "Stopped")
        super.onDestroy()
    }

    // ------------------------------------------------------------------ main loop

    @SuppressLint("MissingPermission") // RECORD_AUDIO is requested by MainActivity before starting
    private fun listenLoop() {
        val prefs = Prefs(this)
        setStatus("Loading wake-word model…")
        val model = try {
            // Copies the model out of the APK on first run (or after an app update), then loads it.
            Model(StorageService.sync(this, "model-en-us", "model"))
        } catch (e: Exception) {
            Log.e(TAG, "Model load failed", e)
            fail("Could not load the wake-word model. Reinstall the app or free some storage.")
            return
        }
        var recognizer: Recognizer? = null
        var recorder: AudioRecord? = null
        try {
            recognizer = Recognizer(model, SAMPLE_RATE.toFloat(), WAKE_GRAMMAR)
            val headsetInput = if (prefs.micSource == "headset") routing.useHeadsetMic() else null
            val source = if (headsetInput != null) MediaRecorder.AudioSource.VOICE_COMMUNICATION
            else MediaRecorder.AudioSource.VOICE_RECOGNITION
            val minBuf = AudioRecord.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
            recorder = AudioRecord(source, SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
                maxOf(minBuf, FRAME * 2 * 8))
            if (recorder.state != AudioRecord.STATE_INITIALIZED) {
                fail("Could not open the microphone. Is another app using it?")
                return
            }
            headsetInput?.let { recorder.preferredDevice = it }
            recorder.startRecording()
            val micName = if (headsetInput != null) "headphone mic" else "phone mic"
            val listening = "Listening for \"Edith\" ($micName)"
            setStatus(listening)

            val buf = ShortArray(FRAME)
            var noise = 300.0
            while (running.get()) {
                if (!readFully(recorder, buf)) continue
                val manual = askNow.getAndSet(false)
                val detected = recognizer.acceptWaveForm(buf, buf.size) &&
                    isWakeWord(recognizer.result, prefs.strictWake)
                if (!detected && !manual) {
                    noise = noise * 0.98 + rms(buf) * 0.02 // track background level
                    continue
                }
                handleQuestion(recorder, FRAME, SAMPLE_RATE, noise, prefs)
                recognizer.reset()
                if (running.get()) {
                    if (recorder.recordingState != AudioRecord.RECORDSTATE_RECORDING) recorder.startRecording()
                    setStatus(listening)
                }
            }
        } catch (e: InterruptedException) {
            // stopping
        } catch (e: Exception) {
            Log.e(TAG, "Listener crashed", e)
            fail("EDITH stopped: ${e.message ?: e.javaClass.simpleName}")
        } finally {
            recorder?.run { runCatching { stop() }; release() }
            recognizer?.close()
            model.close()
            routing.release()
        }
    }

    /** Vosk result JSON -> did the user say the wake word? */
    private fun isWakeWord(resultJson: String, strict: Boolean): Boolean {
        val words = runCatching { JSONObject(resultJson).optString("text") }.getOrDefault("")
            .split(' ').filter { it.isNotBlank() }
        if (words.isEmpty()) return false
        return if (strict) words == listOf("edith") || words == listOf("hey", "edith")
        else "edith" in words
    }

    private fun handleQuestion(recorder: AudioRecord, frame: Int, rate: Int, noise: Double, prefs: Prefs) {
        beep()
        setStatus("Listening to your question…")
        val wav = recordQuestion(recorder, frame, rate, noise)
        recorder.stop()
        if (wav == null) {
            speak("I didn't hear a question.")
            return
        }
        setStatus("Thinking…")
        val api = EdithApi(prefs.serverUrl, prefs.password)
        val lang = Locale.getDefault().toLanguageTag()
        try {
            val question = api.transcribe(wav, lang)
            if (question.isBlank()) {
                speak("Sorry, I didn't catch that.")
                return
            }
            EdithState.update(question = question, answer = "")
            val answer = api.chat(question, history.toList(), lang).ifBlank { "I don't have an answer for that." }
            history.addLast(EdithApi.Turn("user", question))
            history.addLast(EdithApi.Turn("assistant", answer))
            while (history.size > 12) history.removeFirst()
            EdithState.update(answer = answer)
            setStatus("Speaking…")
            speak(answer)
        } catch (e: EdithException) {
            EdithState.update(answer = "⚠ ${e.message}")
            speak(e.message ?: "Something went wrong.")
        }
    }

    /** Records until the speaker pauses. Returns WAV bytes, or null if nobody spoke. */
    private fun recordQuestion(recorder: AudioRecord, frame: Int, rate: Int, noise: Double): ByteArray? {
        val pcm = ByteArrayOutputStream()
        val buf = ShortArray(frame)
        val framesPerSec = rate / frame
        val threshold = maxOf(500.0, noise * 3.0)
        var heardSpeech = false
        var silentFrames = 0
        var total = 0
        val waitForSpeech = framesPerSec * 6     // up to 6 s to start talking
        val endSilence = (framesPerSec * 1.3).toInt() // stop after 1.3 s of quiet
        val maxFrames = framesPerSec * 20        // max 20 s question
        while (running.get() && total < maxFrames) {
            if (!readFully(recorder, buf)) continue
            total++
            val loud = rms(buf) > threshold
            if (loud) {
                heardSpeech = true
                silentFrames = 0
            } else if (heardSpeech) {
                silentFrames++
            }
            if (heardSpeech || total > framesPerSec / 2) writePcm(pcm, buf)
            if (!heardSpeech && total > waitForSpeech) return null
            if (heardSpeech && silentFrames > endSilence) break
        }
        return if (heardSpeech) wav(pcm.toByteArray(), rate) else null
    }

    // ------------------------------------------------------------------ helpers

    private fun readFully(r: AudioRecord, buf: ShortArray): Boolean {
        var off = 0
        while (off < buf.size) {
            val n = r.read(buf, off, buf.size - off)
            if (n <= 0) return false
            off += n
        }
        return true
    }

    private fun rms(buf: ShortArray): Double {
        var sum = 0.0
        for (s in buf) sum += s.toDouble() * s
        return sqrt(sum / buf.size)
    }

    private fun writePcm(out: ByteArrayOutputStream, buf: ShortArray) {
        val bb = ByteBuffer.allocate(buf.size * 2).order(ByteOrder.LITTLE_ENDIAN)
        buf.forEach { bb.putShort(it) }
        out.write(bb.array())
    }

    private fun wav(pcm: ByteArray, rate: Int): ByteArray {
        val h = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
        h.put("RIFF".toByteArray()).putInt(36 + pcm.size).put("WAVE".toByteArray())
        h.put("fmt ".toByteArray()).putInt(16).putShort(1).putShort(1).putInt(rate).putInt(rate * 2)
            .putShort(2).putShort(16)
        h.put("data".toByteArray()).putInt(pcm.size)
        return h.array() + pcm
    }

    private fun beep() {
        try {
            val stream = if (routing.headsetActive) AudioManager.STREAM_VOICE_CALL else AudioManager.STREAM_MUSIC
            val tone = ToneGenerator(stream, 80)
            tone.startTone(ToneGenerator.TONE_PROP_BEEP, 150)
            Thread.sleep(250)
            tone.release()
        } catch (e: RuntimeException) {
            Log.w(TAG, "beep failed", e)
        }
    }

    /** Speaks through the current audio output (your headphones when connected) and waits until done. */
    private fun speak(text: String) {
        val engine = tts ?: return
        if (!ttsReady.await(5, TimeUnit.SECONDS)) return
        val usage = if (routing.headsetActive) AudioAttributes.USAGE_VOICE_COMMUNICATION
        else AudioAttributes.USAGE_ASSISTANT
        engine.setAudioAttributes(
            AudioAttributes.Builder().setUsage(usage).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()
        )
        val done = CountDownLatch(1)
        engine.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {}
            override fun onDone(utteranceId: String?) = done.countDown()
            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) = done.countDown()
            override fun onStop(utteranceId: String?, interrupted: Boolean) = done.countDown()
        })
        val clipped = text.take(TextToSpeech.getMaxSpeechInputLength() - 1)
        engine.speak(clipped, TextToSpeech.QUEUE_FLUSH, null, "edith-${System.nanoTime()}")
        done.await(90, TimeUnit.SECONDS)
    }

    private fun setupMediaButton() {
        if (!Prefs(this).mediaButton) return
        mediaSession = MediaSession(this, "EDITH").apply {
            setCallback(object : MediaSession.Callback() {
                override fun onMediaButtonEvent(mediaButtonIntent: Intent): Boolean {
                    val ev = if (Build.VERSION.SDK_INT >= 33)
                        mediaButtonIntent.getParcelableExtra(Intent.EXTRA_KEY_EVENT, KeyEvent::class.java)
                    else @Suppress("DEPRECATION") mediaButtonIntent.getParcelableExtra(Intent.EXTRA_KEY_EVENT)
                    if (ev?.action == KeyEvent.ACTION_DOWN && ev.keyCode in MEDIA_KEYS) {
                        askNow.set(true)
                        return true
                    }
                    return super.onMediaButtonEvent(mediaButtonIntent)
                }
            })
            setPlaybackState(
                PlaybackState.Builder()
                    .setActions(PlaybackState.ACTION_PLAY_PAUSE or PlaybackState.ACTION_PLAY)
                    .setState(PlaybackState.STATE_PAUSED, 0, 1f).build()
            )
            isActive = true
        }
    }

    private fun acquireWakeLock() {
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "edith:listener").apply {
            setReferenceCounted(false)
            acquire()
        }
    }

    private fun fail(message: String) {
        EdithState.update(status = "⚠ $message")
        updateNotification("⚠ $message")
        speak(message)
        running.set(false)
        Handler(Looper.getMainLooper()).post { stopSelf() }
    }

    private fun setStatus(text: String) {
        EdithState.update(status = text)
        updateNotification(text)
    }

    // ------------------------------------------------------------------ notification

    private fun createChannel() {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL, "EDITH listening", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Shown while EDITH listens for its wake word"
                setShowBadge(false)
            }
        )
    }

    private fun notification(text: String): Notification {
        val flags = PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), flags)
        val stop = PendingIntent.getService(this, 1, Intent(this, EdithService::class.java).setAction(ACTION_STOP), flags)
        val ask = PendingIntent.getService(this, 2, Intent(this, EdithService::class.java).setAction(ACTION_ASK), flags)
        return NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_edith)
            .setContentTitle("EDITH")
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(open)
            .addAction(0, "Ask now", ask)
            .addAction(0, "Stop", stop)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .build()
    }

    private fun startInForeground(text: String) {
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE else 0
        ServiceCompat.startForeground(this, NOTIFICATION_ID, notification(text), type)
    }

    private fun updateNotification(text: String) {
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification(text))
    }

    companion object {
        private const val TAG = "Edith"
        private const val CHANNEL = "edith_listening"
        private const val NOTIFICATION_ID = 7
        private const val SAMPLE_RATE = 16000
        private const val FRAME = 1600 // 100 ms

        /**
         * Wake-word grammar. Similar-sounding "decoy" phrases give the recogniser something
         * better to choose than "edith" for words like "eat it", "edit", "Eddie" or "ready",
         * which cuts false wake-ups. Tested offline against synthetic speech: 9/9 wake,
         * 0/42 false wakes.
         */
        private val WAKE_GRAMMAR: String = JSONArray(
            listOf(
                "edith", "hey edith",
                "eat it", "eat", "it", "edit", "eddie", "eighty", "each", "edison", "ready", "headed",
                "today", "a", "the", "i", "is", "it's", "did", "with", "hey", "eat this", "need it",
                "read it", "heat", "meet", "seat it", "[unk]",
            )
        ).toString()
        const val ACTION_STOP = "ai.edith.assistant.STOP"
        const val ACTION_ASK = "ai.edith.assistant.ASK"
        private val MEDIA_KEYS = setOf(
            KeyEvent.KEYCODE_HEADSETHOOK, KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE,
            KeyEvent.KEYCODE_MEDIA_PLAY, KeyEvent.KEYCODE_MEDIA_PAUSE,
        )
    }
}
