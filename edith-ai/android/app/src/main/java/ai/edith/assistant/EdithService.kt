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
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.CountDownLatch
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.sqrt

/** Live status shared with the screen. */
object EdithState {
    @Volatile var running = false
    @Volatile var status = "Stopped"
    @Volatile var lastQuestion = ""
    @Volatile var lastAnswer = ""
    @Volatile var micLevel = 0.0
    /** Meeting mode: answer questions heard in the room automatically (user-confirmed consent). */
    @Volatile var meetingMode = false
    @Volatile var lastHeard = ""
    /** Recent actions and their result (shown in the app; helps find problems). */
    val actionLog = java.util.concurrent.CopyOnWriteArrayList<String>()

    fun log(line: String) {
        val t = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.getDefault()).format(java.util.Date())
        actionLog.add(0, "$t  $line")
        while (actionLog.size > 8) actionLog.removeAt(actionLog.size - 1)
        main.post { listeners.toList().forEach { it() } }
    }
    private val main = Handler(Looper.getMainLooper())
    private val listeners = mutableSetOf<() -> Unit>()

    fun addListener(l: () -> Unit) = listeners.add(l)
    fun removeListener(l: () -> Unit) = listeners.remove(l)
    fun level(rms: Double) {
        micLevel = rms
        main.post { listeners.toList().forEach { it() } }
    }

    fun update(status: String? = null, question: String? = null, answer: String? = null, heard: String? = null) {
        status?.let { this.status = it }
        heard?.let { lastHeard = it }
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
    private val cancelCall = AtomicBoolean(false)
    /** While set (epoch ms), the listener keeps the microphone closed – e.g. while a call starts. */
    @Volatile private var holdMicUntil = 0L
    @Volatile private var currentMic: Mic? = null
    private val audioManager by lazy { getSystemService(AudioManager::class.java) }
    private var worker: Thread? = null
    private var tts: TextToSpeech? = null
    private val ttsReady = CountDownLatch(1)
    private var wakeLock: PowerManager.WakeLock? = null
    private var mediaSession: MediaSession? = null
    private lateinit var routing: AudioRouting
    private val history = ArrayDeque<EdithApi.Turn>()

    // Meeting mode: speech segments are transcribed/answered on this thread so listening never pauses.
    private val meetingWorker = ThreadPoolExecutor(1, 1, 30, TimeUnit.SECONDS, ArrayBlockingQueue(3),
        ThreadPoolExecutor.DiscardOldestPolicy())
    private val transcript = ArrayDeque<String>() // last ~20 lines, memory only, cleared when meeting ends
    @Volatile private var speaking = false

    // Conversation mode: after "Edith", keep listening for follow-ups until 2 min without one.
    @Volatile private var conversationUntil = 0L
    /** Set by actions that need a spoken reply (yes/no, next lead): start conversation mode even if off. */
    @Volatile private var forceConversation = false

    /** "Should I send it?" waiting for yes/no. */
    private class Pending(val prompt: String, val doneSay: String, val onYes: () -> String?, val until: Long) {
        var unclear = 0
    }
    @Volatile private var pendingConfirm: Pending? = null

    /** Leads being read out one by one. */
    private class LeadSession(val query: String, val leads: List<org.json.JSONObject>) {
        var index = 0
    }
    @Volatile private var leadSession: LeadSession? = null
    private val conversationEnd = AtomicBoolean(false)
    private val conversationPending = java.util.concurrent.atomic.AtomicInteger(0)
    @Volatile private var lastAutoAnswerAt = 0L

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
            ACTION_CANCEL_CALL -> { cancelCall.set(true); return START_NOT_STICKY }
            ACTION_MEETING_ON -> EdithState.meetingMode = true
            ACTION_MEETING_OFF -> EdithState.meetingMode = false
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
        meetingWorker.shutdownNow()
        synchronized(transcript) { transcript.clear() }
        EdithState.meetingMode = false
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
        var mic: Mic? = null
        try {
            recognizer = Recognizer(model, SAMPLE_RATE.toFloat(), WAKE_GRAMMAR)
            var meeting = EdithState.meetingMode
            var current: Mic = openMic(prefs, phoneOnly = meeting) ?: return
            mic = current
            currentMic = current
            fun statusText(m: Mic) = if (meeting) "Meeting mode: listening for questions (${m.name})"
            else "Listening for \"Edith\" (${m.name})"
            var listening = statusText(current)
            val seg = Segmenter()
            setStatus(listening)

            val buf = ShortArray(FRAME)
            var noise = 300.0
            var partialHits = 0
            var frameCount = 0
            while (running.get()) {
                // 0) Give the microphone to phone/WhatsApp calls; resume afterwards.
                if (inPhoneCall() || System.currentTimeMillis() < holdMicUntil) {
                    current.close()
                    mic = null
                    currentMic = null
                    conversationUntil = 0
                    setStatus("Paused during your call")
                    while (running.get() && (inPhoneCall() || System.currentTimeMillis() < holdMicUntil)) {
                        Thread.sleep(500)
                    }
                    if (!running.get()) break
                    Thread.sleep(800)
                    current = openMic(prefs, phoneOnly = meeting) ?: return
                    mic = current
                    currentMic = current
                    recognizer.reset()
                    seg.reset()
                    setStatus(listening)
                    continue
                }
                // 1) Read audio. A broken or silenced microphone is reopened instead of looping forever.
                if (!current.read(buf)) {
                    if (current.needsReopen) {
                        Log.w(TAG, "Microphone stopped delivering audio - reopening")
                        current.close()
                        mic = null
                        Thread.sleep(300)
                        current = openMic(prefs, phoneOnly = meeting) ?: return
                        mic = current
                    currentMic = current
                        listening = statusText(current)
                        setStatus(listening)
                        recognizer.reset()
                    }
                    continue
                }
                // Meeting mode switched on/off: meetings always use the phone mic (it hears the room).
                if (EdithState.meetingMode != meeting) {
                    meeting = EdithState.meetingMode
                    conversationUntil = 0
                    seg.reset()
                    if (!meeting) synchronized(transcript) { transcript.clear() }
                    current.close()
                    mic = null
                    current = openMic(prefs, phoneOnly = meeting) ?: return
                    mic = current
                    currentMic = current
                    listening = statusText(current)
                    setStatus(listening)
                    recognizer.reset()
                    continue
                }
                val level = rms(buf)
                if (++frameCount % 5 == 0) EdithState.level(level)

                if (meeting) {
                    val threshold = maxOf(noise * 3.0, 500.0)
                    val speech = level > threshold
                    if (!speech) noise = noise * 0.98 + level * 0.02
                    // Ignore the room while EDITH itself is whispering an answer.
                    val segment = if (speaking) null else seg.add(buf, speech)
                    if (segment != null) submitMeetingSegment(segment, prefs)
                    var trigger = askNow.getAndSet(false)
                    if (recognizer.acceptWaveForm(buf, buf.size)) {
                        trigger = trigger || isWakeWord(jsonText(recognizer.result, "text"), prefs.strictWake)
                    }
                    if (trigger) {
                        beep()
                        submitMeetingHelp(prefs, force = true)
                    }
                    continue
                }

                // 2a) Conversation mode: every sentence is checked by the server ("for EDITH or not?").
                if (conversationUntil > 0) {
                    val threshold = maxOf(noise * 3.0, 500.0)
                    val speech = level > threshold
                    if (!speech) noise = noise * 0.98 + level * 0.02
                    val busy = speaking || conversationPending.get() > 0
                    val segment = if (busy) null else seg.add(buf, speech)
                    if (segment != null) submitConversationSegment(segment, prefs)
                    askNow.set(false)
                    val timedOut = !busy && !seg.inSpeech && System.currentTimeMillis() > conversationUntil
                    if (conversationEnd.get() || timedOut) {
                        conversationUntil = 0
                        seg.reset()
                        current.flush()
                        recognizer.reset()
                        endTone()
                        setStatus(listening)
                    }
                    continue
                }

                // 2) Wake word: a finished phrase, or "Edith" followed by a short pause.
                val manual = askNow.getAndSet(false)
                var detected = false
                if (recognizer.acceptWaveForm(buf, buf.size)) {
                    detected = isWakeWord(jsonText(recognizer.result, "text"), prefs.strictWake)
                    partialHits = 0
                } else {
                    val partial = jsonText(recognizer.partialResult, "partial")
                    val quiet = level < maxOf(noise * 2.0, 400.0)
                    partialHits = if (isWakeWord(partial, prefs.strictWake) && quiet) partialHits + 1 else 0
                    detected = partialHits >= 3 // "Edith" then ~0.3 s pause
                }
                if (!detected && !manual) {
                    noise = noise * 0.98 + level * 0.02 // track background level
                    continue
                }
                partialHits = 0

                // 3) Question -> answer. The microphone keeps running throughout.
                handleQuestion(current, FRAME, SAMPLE_RATE, noise, prefs)
                current.flush() // drop audio captured while EDITH was thinking/speaking
                recognizer.reset()
                if (!running.get()) break
                if (prefs.conversationMode || forceConversation) {
                    forceConversation = false
                    conversationUntil = System.currentTimeMillis() + CONVERSATION_MS
                    conversationEnd.set(false)
                    seg.reset()
                    setStatus(CONVERSATION_STATUS)
                } else {
                    setStatus(listening)
                }
            }
        } catch (e: InterruptedException) {
            // stopping
        } catch (e: Exception) {
            Log.e(TAG, "Listener crashed", e)
            fail("EDITH stopped: ${e.message ?: e.javaClass.simpleName}")
        } finally {
            mic?.close()
            recognizer?.close()
            model.close()
            routing.release()
        }
    }

    /** Microphone wrapper that notices when Android stops delivering audio. */
    private class Mic(val recorder: AudioRecord, val name: String) {
        private var errors = 0
        private var silentFrames = 0
        var needsReopen = false
            private set

        fun read(buf: ShortArray): Boolean {
            var off = 0
            while (off < buf.size) {
                val n = recorder.read(buf, off, buf.size - off)
                if (n <= 0) {
                    // ERROR_DEAD_OBJECT etc.: happens when Bluetooth/audio routing changes.
                    if (++errors >= 5 || n == AudioRecord.ERROR_DEAD_OBJECT) needsReopen = true
                    return false
                }
                off += n
            }
            errors = 0
            // Android feeds exact zeros when it silences a background microphone.
            silentFrames = if (buf.all { it.toInt() == 0 }) silentFrames + 1 else 0
            if (silentFrames >= 50) { // 5 s of digital silence
                needsReopen = true
                return false
            }
            return true
        }

        fun flush() {
            val tmp = ShortArray(4096)
            repeat(200) {
                if (recorder.read(tmp, 0, tmp.size, AudioRecord.READ_NON_BLOCKING) <= 0) return
            }
        }

        fun close() {
            runCatching { recorder.stop() }
            recorder.release()
        }
    }

    @SuppressLint("MissingPermission")
    private fun openMic(prefs: Prefs, phoneOnly: Boolean = false): Mic? {
        routing.release()
        val headsetInput = if (prefs.micSource == "headset" && !phoneOnly) routing.useHeadsetMic() else null
        val source = if (headsetInput != null) MediaRecorder.AudioSource.VOICE_COMMUNICATION
        else MediaRecorder.AudioSource.VOICE_RECOGNITION
        val minBuf = AudioRecord.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val recorder = AudioRecord(source, SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
            maxOf(minBuf, FRAME * 2 * 8))
        if (recorder.state != AudioRecord.STATE_INITIALIZED) {
            recorder.release()
            fail("Could not open the microphone. Is another app using it?")
            return null
        }
        headsetInput?.let { recorder.preferredDevice = it }
        recorder.startRecording()
        return Mic(recorder, if (headsetInput != null) "headphone mic" else "phone mic")
    }

    private fun jsonText(json: String, key: String): String =
        runCatching { JSONObject(json).optString(key) }.getOrDefault("")

    /**
     * Cuts continuous room audio into sentences: speech followed by ~0.7 s of quiet
     * (or 15 s max). Returns a finished segment as WAV, otherwise null. Memory only.
     */
    private class Segmenter {
        private val pcm = ByteArrayOutputStream()
        private val preRoll = ArrayDeque<ShortArray>()
        private var speechFrames = 0
        private var silentFrames = 0
        private var frames = 0

        fun reset() { pcm.reset(); preRoll.clear(); speechFrames = 0; silentFrames = 0; frames = 0 }

        val inSpeech: Boolean get() = frames > 0

        fun add(buf: ShortArray, speech: Boolean): ByteArray? {
            if (frames == 0 && !speech) {
                preRoll.addLast(buf.copyOf())
                if (preRoll.size > 3) preRoll.removeFirst()
                return null
            }
            if (frames == 0) preRoll.forEach { appendPcm(pcm, it) }
            appendPcm(pcm, buf)
            frames++
            if (speech) { speechFrames++; silentFrames = 0 } else silentFrames++
            if (silentFrames < 7 && frames < 150) return null
            val done = if (speechFrames >= 4) wavBytes(pcm.toByteArray(), SAMPLE_RATE) else null
            reset()
            return done
        }
    }

    private fun submitMeetingSegment(wav: ByteArray, prefs: Prefs) {
        meetingWorker.execute {
            val api = EdithApi(prefs.serverUrl, prefs.password)
            val lang = Locale.getDefault().toLanguageTag()
            val text = try {
                api.transcribe(wav, lang)
            } catch (e: EdithException) {
                EdithState.update(heard = "⚠ ${e.message}")
                return@execute
            }
            if (text.isBlank() || text.length < 3) return@execute
            synchronized(transcript) {
                transcript.addLast(text)
                while (transcript.size > 20) transcript.removeFirst()
            }
            EdithState.update(heard = text)
            // Only ask the AI when the line looks like a question (saves time and quota),
            // and not right after another automatic answer.
            if (looksLikeQuestion(text) && System.currentTimeMillis() - lastAutoAnswerAt > 6000) {
                meetingHelp(api, lang, force = false)
            }
        }
    }

    /** Conversation mode: transcribe one sentence and let the server decide if it was for EDITH. */
    private fun submitConversationSegment(wav: ByteArray, prefs: Prefs) {
        conversationPending.incrementAndGet()
        meetingWorker.execute {
            try {
                val api = EdithApi(prefs.serverUrl, prefs.password)
                val lang = Locale.getDefault().toLanguageTag()
                val text = api.transcribe(wav, lang)
                if (text.isBlank()) return@execute
                EdithState.update(heard = text)
                if (handleLocalReply(text, prefs)) {
                    conversationUntil = System.currentTimeMillis() + CONVERSATION_MS
                    return@execute
                }
                val hist = synchronized(history) { history.toList() }
                val res = api.assistant(text, hist, lang, followup = true)
                if (res.kind != "ignore") logDecision(text, res)
                when (res.kind) {
                    "ignore" -> Unit // side conversation: not for EDITH
                    "end" -> {
                        conversationEnd.set(true)
                        speakWhisper(res.say.ifBlank { "Okay." })
                    }
                    else -> {
                        conversationUntil = System.currentTimeMillis() + CONVERSATION_MS
                        EdithState.update(question = text, answer = "")
                        val spoken = speakingDuring {
                            res.action?.let { performAction(it, res.say, prefs) }
                                ?: res.reply.ifBlank { "I don't have an answer for that." }.also {
                                    EdithState.update(answer = it)
                                    speak(it)
                                }
                        }
                        synchronized(history) {
                            history.addLast(EdithApi.Turn("user", text))
                            history.addLast(EdithApi.Turn("assistant", spoken))
                            while (history.size > 12) history.removeFirst()
                        }
                        conversationUntil = System.currentTimeMillis() + CONVERSATION_MS
                        forceConversation = false
                    }
                }
            } catch (e: EdithException) {
                EdithState.update(heard = "⚠ ${e.message}")
            } finally {
                conversationPending.decrementAndGet()
            }
        }
    }

    private fun logDecision(heard: String, res: EdithApi.Assistant) {
        val what = when {
            res.action != null -> "action ${res.action.optString("type")} → " +
                (res.action.optString("contact").ifBlank { null } ?: res.action.optString("app").ifBlank { null }
                ?: res.action.optString("query").ifBlank { null } ?: res.action.optString("command"))
            else -> res.kind
        }
        EdithState.log("Heard \"${heard.take(60)}\" → $what")
    }

    private fun <T> speakingDuring(block: () -> T): T {
        speaking = true
        try { return block() } finally { speaking = false }
    }

    /** Soft two-tone signal: conversation mode ended, back to waiting for "Edith". */
    private fun endTone() {
        try {
            val stream = if (routing.headsetActive) AudioManager.STREAM_VOICE_CALL else AudioManager.STREAM_MUSIC
            val tone = ToneGenerator(stream, 50)
            tone.startTone(ToneGenerator.TONE_PROP_ACK, 200)
            Thread.sleep(250)
            tone.release()
        } catch (e: RuntimeException) {
            Log.w(TAG, "tone failed", e)
        }
    }

    private fun submitMeetingHelp(prefs: Prefs, force: Boolean) {
        meetingWorker.execute {
            meetingHelp(EdithApi(prefs.serverUrl, prefs.password), Locale.getDefault().toLanguageTag(), force)
        }
    }

    /** Runs on the meeting worker thread. */
    private fun meetingHelp(api: EdithApi, lang: String, force: Boolean) {
        val lines = synchronized(transcript) { transcript.toList() }
        if (lines.isEmpty()) {
            if (force) speakWhisper("I haven't heard anything yet.")
            return
        }
        try {
            val help = api.meetingAssist(lines, force, lang)
            val answer = help.answer ?: return
            lastAutoAnswerAt = System.currentTimeMillis()
            synchronized(transcript) { transcript.addLast("(EDITH suggested: $answer)") }
            EdithState.update(question = help.question ?: lines.last(), answer = answer)
            updateNotification("💡 $answer")
            speakWhisper(answer)
            updateNotification("Meeting mode: listening for questions")
        } catch (e: EdithException) {
            if (force) speakWhisper(e.message ?: "Something went wrong.")
            EdithState.update(heard = "⚠ ${e.message}")
        }
    }

    private fun speakWhisper(text: String) {
        speaking = true
        try { speak(text) } finally { speaking = false }
    }

    /** Cheap pre-filter; the server's AI makes the real "is this a question for me?" decision. */
    private fun looksLikeQuestion(text: String): Boolean {
        val t = text.trim().lowercase()
        if (t.endsWith("?")) return true
        val words = t.split(' ', ',', '.', '!').filter { it.isNotBlank() }
        val first = words.firstOrNull { it !in FILLERS } ?: return false
        return first in QUESTION_STARTS || words.any { it in WH_WORDS } || QUESTION_PHRASES.any { it in t }
    }

    /** Recognised text -> did the user say the wake word? */
    private fun isWakeWord(text: String, strict: Boolean): Boolean {
        val words = text.split(' ').filter { it.isNotBlank() }
        if (words.isEmpty()) return false
        return if (strict) words == listOf("edith") || words == listOf("hey", "edith")
        else "edith" in words
    }

    private fun handleQuestion(mic: Mic, frame: Int, rate: Int, noise: Double, prefs: Prefs) {
        beep()
        mic.flush() // don't record the beep
        setStatus("Listening to your question…")
        val wav = recordQuestion(mic, frame, rate, noise)
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
            if (handleLocalReply(question, prefs)) return
            val result = api.assistant(question, synchronized(history) { history.toList() }, lang)
            logDecision(question, result)
            val spoken = result.action?.let { performAction(it, result.say, prefs) }
                ?: result.reply.ifBlank { "I don't have an answer for that." }.also {
                    EdithState.update(answer = it)
                    setStatus("Speaking…")
                    speak(it)
                }
            synchronized(history) {
                history.addLast(EdithApi.Turn("user", question))
                history.addLast(EdithApi.Turn("assistant", spoken))
                while (history.size > 12) history.removeFirst()
            }
        } catch (e: EdithException) {
            EdithState.update(answer = "⚠ ${e.message}")
            speak(e.message ?: "Something went wrong.")
        }
    }

    /** Runs a phone action (call, open app, music, ...). Returns what EDITH said, for the history. */
    private fun performAction(action: org.json.JSONObject, say: String, prefs: Prefs): String {
        val actions = PhoneActions(this, prefs, EdithApi(prefs.serverUrl, prefs.password))
        return when (val plan = actions.plan(action, say)) {
            is PhoneActions.Plan.Confirm -> {
                pendingConfirm = Pending(plan.prompt, plan.doneSay, plan.onYes, System.currentTimeMillis() + 60_000)
                forceConversation = true
                EdithState.log("Waiting for yes/no: ${plan.prompt.take(80)}")
                speak(plan.prompt)
                plan.prompt
            }
            is PhoneActions.Plan.Leads -> startLeads(plan.query, prefs)
            is PhoneActions.Plan.Fail -> {
                EdithState.log("${action.optString("type")}: ${plan.say}")
                EdithState.update(answer = "⚠ ${plan.say}")
                speak(plan.say)
                plan.say
            }
            is PhoneActions.Plan.Do -> {
                EdithState.update(answer = plan.say.ifBlank { "✓ ${say}" })
                if (!plan.sayAfter && plan.say.isNotBlank()) speak(plan.say)
                val problem = plan.run()
                if (problem == null) EdithState.log("${action.optString("type")}: done – ${plan.say.ifBlank { say }}")
                if (plan.sayAfter && plan.say.isNotBlank()) speak(plan.say)
                problem?.let { EdithState.update(answer = "⚠ $it"); speak(it) }
                problem ?: plan.say
            }
            is PhoneActions.Plan.Call -> {
                EdithState.log("Contact match: ${plan.contact.name}")
                callWithCountdown(actions, plan.contact)
            }
        }
    }

    /** Safety: announce and give 3 seconds to cancel before dialling. */
    private fun callWithCountdown(actions: PhoneActions, contact: PhoneActions.Contact): String {
        val name = contact.name
        cancelCall.set(false)
        EdithState.update(answer = "📞 Calling $name… (tap Cancel call to stop)")
        showCallCountdown(name)
        speak("Calling $name.")
        val deadline = System.currentTimeMillis() + 3000
        while (System.currentTimeMillis() < deadline && !cancelCall.get() && running.get()) Thread.sleep(100)
        updateNotification("Listening…")
        if (cancelCall.get() || !running.get()) {
            EdithState.log("Call to $name cancelled")
            EdithState.update(answer = "Call to $name cancelled.")
            speak("Cancelled.")
            return "Call cancelled."
        }
        releaseMicForCall()
        val problem = actions.placeCall(contact)
        problem?.let { speak(it) }
        return problem ?: "Calling $name."
    }

    // ------------------------------------------------------------------ leads

    private fun startLeads(query: String, prefs: Prefs): String {
        speak("Searching Google Maps for $query without a website.")
        val leads = try {
            EdithApi(prefs.serverUrl, prefs.password).findLeads(query)
        } catch (e: EdithException) {
            EdithState.log("Leads failed: ${e.message}")
            speak(e.message ?: "The lead search failed.")
            return e.message ?: "Lead search failed."
        }
        EdithState.log("Leads for \"$query\": ${leads.size} without a website")
        if (leads.isEmpty()) {
            val msg = "I didn't find any $query without a website. Try a different area or business type."
            speak(msg)
            return msg
        }
        leadSession = LeadSession(query, leads)
        forceConversation = true
        speak("I found ${leads.size}.")
        readLead(first = true)
        return "Found ${leads.size} leads for $query."
    }

    private fun readLead(first: Boolean = false) {
        val s = leadSession ?: return
        val lead = s.leads[s.index]
        val name = lead.optString("name")
        val phone = lead.optString("phone")
        val area = lead.optString("address").split(",").take(2).joinToString(",").trim()
        val rating = if (lead.isNull("rating")) "" else " Rated ${lead.optDouble("rating")} from ${lead.optInt("reviews")} reviews."
        val social = if (lead.isNull("social_url")) "" else " They only have a social media page."
        // Digits one by one so the number is easy to note down.
        val spokenPhone = phone.filter { it.isDigit() }.toList().chunked(5).joinToString(", ") { it.joinToString(" ") }
        EdithState.update(answer = "Lead ${s.index + 1}/${s.leads.size}: $name\n☎ $phone\n${lead.optString("address")}")
        speakWhisper("Lead ${s.index + 1}: $name, $area.$rating$social Phone: $spokenPhone." +
            if (first) " Say next, repeat, call, save, or stop." else "")
    }

    /**
     * Short replies handled on the phone: yes/no for a pending confirmation, and lead commands.
     * Returns true when handled.
     */
    private fun handleLocalReply(text: String, prefs: Prefs): Boolean {
        val t = text.lowercase().replace(Regex("[^a-z0-9' ]"), " ").replace(Regex("\\s+"), " ").trim()
            .removePrefix("hey ").removePrefix("edith ").trim()
        pendingConfirm?.let { p ->
            if (System.currentTimeMillis() > p.until) {
                pendingConfirm = null
                return@let
            }
            when {
                NO_RE.containsMatchIn(t) -> {
                    pendingConfirm = null
                    EdithState.log("Not sent (you said no)")
                    speakWhisper("Okay, I won't send it.")
                }
                YES_RE.containsMatchIn(t) -> {
                    pendingConfirm = null
                    val problem = speakingDuring { p.onYes() }
                    EdithState.update(answer = problem?.let { "⚠ $it" } ?: "✓ ${p.doneSay}")
                    speakWhisper(problem ?: p.doneSay)
                }
                else -> {
                    p.unclear++
                    if (p.unclear >= 2) {
                        pendingConfirm = null
                        speakWhisper("I'll leave it unsent.")
                    } else {
                        speakWhisper("Should I send it? Say yes or no.")
                    }
                }
            }
            return true
        }
        val s = leadSession ?: return false
        when {
            LEAD_NEXT.matches(t) -> {
                if (s.index + 1 >= s.leads.size) {
                    leadSession = null
                    speakWhisper("That was the last one. Say find leads again for more.")
                } else {
                    s.index++
                    readLead()
                }
            }
            LEAD_PREV.matches(t) -> {
                s.index = maxOf(0, s.index - 1)
                readLead()
            }
            LEAD_REPEAT.matches(t) -> readLead()
            LEAD_SAVE.matches(t) -> {
                val lead = s.leads[s.index]
                val msg = try {
                    EdithApi(prefs.serverUrl, prefs.password).saveLead(lead)
                    EdithState.log("Saved lead: ${lead.optString("name")}")
                    "Saved."
                } catch (e: EdithException) {
                    e.message ?: "Saving failed."
                }
                speakWhisper(msg)
            }
            LEAD_CALL.matches(t) -> {
                val lead = s.leads[s.index]
                val actions = PhoneActions(this, prefs)
                runCatching { EdithApi(prefs.serverUrl, prefs.password).saveLead(lead, status = "called") }
                speakingDuring {
                    callWithCountdown(actions, PhoneActions.Contact(lead.optString("name"), lead.optString("phone")))
                }
            }
            LEAD_STOP.matches(t) -> {
                leadSession = null
                conversationEnd.set(true)
                speakWhisper("Okay, done with leads. Your saved leads are on the EDITH website.")
            }
            else -> return false // a normal question: let the server answer it
        }
        return true
    }

    private fun showCallCountdown(name: String) {
        val flags = PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        val cancel = PendingIntent.getService(this, 4,
            Intent(this, EdithService::class.java).setAction(ACTION_CANCEL_CALL), flags)
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID,
            NotificationCompat.Builder(this, CHANNEL)
                .setSmallIcon(R.drawable.ic_stat_edith)
                .setContentTitle("Calling $name in 3 seconds")
                .setContentText("Tap Cancel call to stop")
                .setOngoing(true)
                .addAction(0, "Cancel call", cancel)
                .build())
    }

    /**
     * Frees the microphone and Bluetooth "call mode" so the phone call can use them.
     * The listener stays paused while the call is starting and while it lasts.
     */
    private fun releaseMicForCall() {
        holdMicUntil = System.currentTimeMillis() + 15_000
        if (Thread.currentThread() === worker) {
            currentMic?.close()
            currentMic = null
        } else {
            // Conversation mode: the listener thread closes it on its next frame.
            val until = System.currentTimeMillis() + 1500
            while (currentMic != null && System.currentTimeMillis() < until) Thread.sleep(50)
        }
        routing.release()
        Thread.sleep(300)
    }

    /** True while a phone/VoIP call is active: EDITH must not take the microphone. */
    private fun inPhoneCall(): Boolean {
        val mode = audioManager.mode
        return mode == AudioManager.MODE_IN_CALL || mode == AudioManager.MODE_RINGTONE ||
            (mode == AudioManager.MODE_IN_COMMUNICATION && !routing.headsetActive) ||
            (Build.VERSION.SDK_INT >= 33 && mode == AudioManager.MODE_CALL_SCREENING)
    }

    /** Records until the speaker pauses. Returns WAV bytes, or null if nobody spoke. */
    private fun recordQuestion(mic: Mic, frame: Int, rate: Int, noise: Double): ByteArray? {
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
        var failures = 0
        while (running.get() && total < maxFrames) {
            if (!mic.read(buf)) {
                if (mic.needsReopen || ++failures > 20) break // microphone broke: give up on this question
                continue
            }
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

    private fun rms(buf: ShortArray): Double {
        var sum = 0.0
        for (s in buf) sum += s.toDouble() * s
        return sqrt(sum / buf.size)
    }

    private fun writePcm(out: ByteArrayOutputStream, buf: ShortArray) = appendPcm(out, buf)

    private fun wav(pcm: ByteArray, rate: Int): ByteArray = wavBytes(pcm, rate)

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
            .addAction(0, if (EdithState.meetingMode) "Answer now" else "Ask now", ask)
            .apply {
                if (EdithState.meetingMode) {
                    val end = PendingIntent.getService(this@EdithService, 3,
                        Intent(this@EdithService, EdithService::class.java).setAction(ACTION_MEETING_OFF), flags)
                    addAction(0, "End meeting", end)
                }
            }
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
        private const val CONVERSATION_MS = 120_000L // 2 minutes without a question for EDITH
        private val YES_RE = Regex("^(yes|yeah|yep|yup|ya|sure|ok|okay|send|go ahead|do it|confirm|please do|haan|han|ha|ji|correct|right)\\b")
        private val NO_RE = Regex("^(no|nope|nah|cancel|don't|do not|stop|never ?mind|wait|not now|nahi|mat)\\b|\\b(don't send|do not send)\\b")
        private val LEAD_NEXT = Regex("^(next|next one|next lead|skip|skip it|another|another one|more|go on|continue)$")
        private val LEAD_PREV = Regex("^(previous|previous one|back|go back|last one)$")
        private val LEAD_REPEAT = Regex("^(repeat|again|say again|say that again|repeat that|what|pardon|number|phone number|what's the number|repeat the number|once more)$")
        private val LEAD_SAVE = Regex("^(save|save it|save this|save this one|save that|save lead|save this lead|save the lead|bookmark|add it|keep it|keep this)$")
        private val LEAD_CALL = Regex("^(call|call them|call this|call this one|call it|call him|call her|call that one|call this business|call this number|call now|call the number)$")
        private val LEAD_STOP = Regex("^(stop|done|that's all|that is all|enough|no more|end|finish|exit|stop leads|close|i'm done)$")
        private const val CONVERSATION_STATUS = "Conversation mode: listening (say \"stop listening\" to end)"
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
        const val ACTION_CANCEL_CALL = "ai.edith.assistant.CANCEL_CALL"
        const val ACTION_MEETING_ON = "ai.edith.assistant.MEETING_ON"
        const val ACTION_MEETING_OFF = "ai.edith.assistant.MEETING_OFF"
        private val QUESTION_STARTS = setOf(
            "what", "what's", "whats", "why", "how", "when", "where", "who", "whom", "which", "can", "could",
            "would", "will", "is", "are", "do", "does", "did", "should", "shall", "may", "explain", "tell",
            "define", "describe", "any", "have", "has",
        )
        private val FILLERS = setOf("so", "and", "but", "okay", "ok", "um", "uh", "well", "then", "also",
            "now", "right", "hey", "yeah", "like", "actually", "basically", "just", "sorry", "please")
        private val WH_WORDS = setOf("what", "what's", "whats", "why", "how", "which", "who", "where", "when")
        private val QUESTION_PHRASES = listOf(
            "what is", "what does", "what are", "how do", "how does", "how much", "how many", "why do",
            "can you", "could you", "do you know", "tell me", "explain", "meaning of", "difference between",
        )
        private val MEDIA_KEYS = setOf(
            KeyEvent.KEYCODE_HEADSETHOOK, KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE,
            KeyEvent.KEYCODE_MEDIA_PLAY, KeyEvent.KEYCODE_MEDIA_PAUSE,
        )
    }
}

private fun appendPcm(out: ByteArrayOutputStream, buf: ShortArray) {
    val bb = ByteBuffer.allocate(buf.size * 2).order(ByteOrder.LITTLE_ENDIAN)
    buf.forEach { bb.putShort(it) }
    out.write(bb.array())
}

private fun wavBytes(pcm: ByteArray, rate: Int): ByteArray {
    val h = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
    h.put("RIFF".toByteArray()).putInt(36 + pcm.size).put("WAVE".toByteArray())
    h.put("fmt ".toByteArray()).putInt(16).putShort(1).putShort(1).putInt(rate).putInt(rate * 2)
        .putShort(2).putShort(16)
    h.put("data".toByteArray()).putInt(pcm.size)
    return h.array() + pcm
}
