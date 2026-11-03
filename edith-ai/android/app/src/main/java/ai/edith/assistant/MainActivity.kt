package ai.edith.assistant

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.text.Editable
import android.text.TextWatcher
import android.view.View
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.RadioGroup
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import kotlin.concurrent.thread

class MainActivity : AppCompatActivity() {

    private lateinit var prefs: Prefs
    private lateinit var status: TextView
    private lateinit var toggle: Button
    private lateinit var lastQa: TextView
    private lateinit var micLevel: TextView
    private lateinit var meetingToggle: Button
    private lateinit var heard: TextView
    private val stateListener: () -> Unit = { render() }

    private val askCallPermissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        render()
        if (it.values.any { granted -> !granted }) toast("Without these permissions EDITH can't call your contacts.")
    }

    private val askBluetooth = registerForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) showHeadphonePicker() else toast("EDITH needs the Nearby devices permission to see your headphones.")
    }

    private val askPermissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { res ->
        if (res[Manifest.permission.RECORD_AUDIO] == true) startEdith()
        else { EdithState.meetingMode = false; toast("EDITH needs microphone permission to hear “Edith”.") }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        prefs = Prefs(this)
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.root)) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }

        status = findViewById(R.id.status)
        toggle = findViewById(R.id.toggle)
        lastQa = findViewById(R.id.lastQa)
        micLevel = findViewById(R.id.micLevel)
        meetingToggle = findViewById(R.id.meetingToggle)
        heard = findViewById(R.id.heard)
        meetingToggle.setOnClickListener {
            if (EdithState.meetingMode) setMeeting(false) else confirmMeeting()
        }

        bindText(R.id.serverUrl, prefs.serverUrl) { prefs.serverUrl = it }
        bindText(R.id.password, prefs.password) { prefs.password = it }
        findViewById<CheckBox>(R.id.conversationMode).apply {
            isChecked = prefs.conversationMode
            setOnCheckedChangeListener { _, v -> prefs.conversationMode = v }
        }
        findViewById<CheckBox>(R.id.strictWake).apply {
            isChecked = prefs.strictWake
            setOnCheckedChangeListener { _, v -> prefs.strictWake = v }
        }
        findViewById<RadioGroup>(R.id.micSource).apply {
            check(if (prefs.micSource == "headset") R.id.micHeadset else R.id.micPhone)
            setOnCheckedChangeListener { _, id -> prefs.micSource = if (id == R.id.micHeadset) "headset" else "phone" }
        }
        findViewById<CheckBox>(R.id.mediaButton).apply {
            isChecked = prefs.mediaButton
            setOnCheckedChangeListener { _, v -> prefs.mediaButton = v }
        }
        findViewById<Button>(R.id.test).setOnClickListener { testConnection() }
        findViewById<Button>(R.id.allowCalls).setOnClickListener {
            askCallPermissions.launch(arrayOf(Manifest.permission.READ_CONTACTS, Manifest.permission.CALL_PHONE,
                Manifest.permission.READ_PHONE_STATE))
        }
        findViewById<Button>(R.id.testCall).setOnClickListener { testCall() }
        bindText(R.id.address, prefs.address.takeIf { it != "sir" } ?: "") { prefs.address = it }
        bindText(R.id.extraWords, prefs.extraWords) { prefs.extraWords = it }
        findViewById<CheckBox>(R.id.humanVoice).apply {
            isChecked = prefs.humanVoice
            setOnCheckedChangeListener { _, v -> prefs.humanVoice = v }
        }
        val voices = mapOf(R.id.vHannah to "hannah", R.id.vDiana to "diana", R.id.vAutumn to "autumn",
            R.id.vDaniel to "daniel", R.id.vAustin to "austin", R.id.vTroy to "troy")
        findViewById<RadioGroup>(R.id.voiceName).apply {
            check(voices.entries.firstOrNull { it.value == prefs.voiceName }?.key ?: R.id.vHannah)
            setOnCheckedChangeListener { _, id -> prefs.voiceName = voices[id] ?: "hannah" }
        }
        findViewById<Button>(R.id.testVoice).setOnClickListener { testVoice() }
        findViewById<Button>(R.id.phoneVoice).setOnClickListener { choosePhoneVoice() }
        val speedLabel = findViewById<TextView>(R.id.speedLabel)
        findViewById<android.widget.SeekBar>(R.id.speed).apply {
            progress = ((prefs.speechRate - 0.6f) * 100).toInt()
            speedLabel.text = "Speed: ${"%.2f".format(prefs.speechRate)}×"
            setOnSeekBarChangeListener(simpleSeek { p ->
                prefs.speechRate = 0.6f + p / 100f
                speedLabel.text = "Speed: ${"%.2f".format(prefs.speechRate)}×"
            })
        }
        val pitchLabel = findViewById<TextView>(R.id.pitchLabel)
        findViewById<android.widget.SeekBar>(R.id.pitch).apply {
            progress = ((prefs.speechPitch - 0.7f) * 100).toInt()
            pitchLabel.text = "Pitch: ${"%.2f".format(prefs.speechPitch)}"
            setOnSeekBarChangeListener(simpleSeek { p ->
                prefs.speechPitch = 0.7f + p / 100f
                pitchLabel.text = "Pitch: ${"%.2f".format(prefs.speechPitch)}"
            })
        }
        findViewById<Button>(R.id.hearingTest).setOnClickListener {
            if (!EdithState.running) toast("Start EDITH first, then run the hearing test.")
            else startService(Intent(this, EdithService::class.java).setAction(EdithService.ACTION_HEARING_TEST))
        }
        findViewById<Button>(R.id.clearAliases).setOnClickListener {
            prefs.contactAliases = emptyMap()
            toast("Forgotten. EDITH will ask again when several contacts match.")
            render()
        }
        findViewById<Button>(R.id.registerHeadphones).setOnClickListener {
            if (Build.VERSION.SDK_INT >= 31 &&
                ContextCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED
            ) askBluetooth.launch(Manifest.permission.BLUETOOTH_CONNECT) else showHeadphonePicker()
        }
        findViewById<CheckBox>(R.id.headphoneLock).apply {
            isChecked = prefs.headphoneLock
            setOnCheckedChangeListener { _, v -> prefs.headphoneLock = v; render() }
        }
        findViewById<EditText>(R.id.aboutMe).setText(prefs.aboutMe)
        findViewById<Button>(R.id.saveAboutMe).setOnClickListener { saveAboutMe() }
        findViewById<Button>(R.id.allowApps).setOnClickListener {
            if (Settings.canDrawOverlays(this)) toast("Already allowed ✓")
            else startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
        }
        findViewById<Button>(R.id.allowWhatsApp).setOnClickListener {
            if (!BuildConfig.WHATSAPP_AUTO_SEND) {
                androidx.appcompat.app.AlertDialog.Builder(this)
                    .setTitle("Typing & Send in apps")
                    .setMessage("This edition opens WhatsApp with the message typed (you tap Send) and copies " +
                        "dictated text for you to paste.\n\n" +
                        "Typing into any app and pressing Send automatically needs the \"full\" edition. Google Play Protect blocks " +
                        "installing it from the phone (it uses Accessibility), so it has to be installed from a " +
                        "computer: see docs/LEADS_AND_EMAIL.md → WhatsApp.")
                    .setPositiveButton("OK", null)
                    .show()
                return@setOnClickListener
            }
            if (WhatsAppSender.isEnabled(this)) { toast("Already allowed ✓"); return@setOnClickListener }
            androidx.appcompat.app.AlertDialog.Builder(this)
                .setTitle("Typing & Send in apps")
                .setMessage("EDITH will be able to type what you dictate into the open app (WhatsApp, Instagram, " +
                    "Notes or any app with a text box) and press Send after you say \"yes\".\n\n" +
                    "It only acts right after you give EDITH a typing command, never types into password " +
                    "fields, and doesn't read, store or upload your screen. This access is powerful: only turn " +
                    "it on on your own phone.\n\nNext screen: Installed/Downloaded apps → EDITH typing & Send → turn on.")
                .setPositiveButton("Continue") { _, _ ->
                    startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
                }
                .setNegativeButton("Cancel", null)
                .show()
        }
        findViewById<Button>(R.id.appInfo).setOnClickListener {
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
        }
        bindText(R.id.countryCode, prefs.countryCode) { prefs.countryCode = it }
        findViewById<Button>(R.id.brandPopups).setOnClickListener {
            toast("Open “Other permissions” (or “Permissions”) → allow “Display pop-up windows while running in the background” and “Display pop-up windows”.")
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
        }
        bindText(R.id.favoriteMusic, prefs.favoriteMusic) { prefs.favoriteMusic = it }
        findViewById<RadioGroup>(R.id.musicApp).apply {
            check(when (prefs.musicApp) { "youtube_music" -> R.id.musicYtMusic; "jiosaavn" -> R.id.musicJioSaavn; else -> R.id.musicSpotify })
            setOnCheckedChangeListener { _, id ->
                prefs.musicApp = when (id) { R.id.musicYtMusic -> "youtube_music"; R.id.musicJioSaavn -> "jiosaavn"; else -> "spotify" }
            }
        }
        findViewById<Button>(R.id.battery).setOnClickListener { openBatterySettings() }
        findViewById<Button>(R.id.askNow).setOnClickListener {
            if (EdithState.running) startService(Intent(this, EdithService::class.java).setAction(EdithService.ACTION_ASK))
            else toast("Start EDITH first.")
        }
        toggle.setOnClickListener {
            if (EdithState.running) stopService(Intent(this, EdithService::class.java)) else requestAndStart()
        }
    }

    override fun onResume() {
        super.onResume()
        render() // permissions may have changed in system settings
    }

    override fun onStart() {
        super.onStart()
        EdithState.addListener(stateListener)
        render()
    }

    override fun onStop() {
        EdithState.removeListener(stateListener)
        super.onStop()
    }

    private fun render() {
        status.text = EdithState.status
        val trusted = prefs.trustedHeadphones
        val now = Headphones.trustedConnected(this, trusted)
        findViewById<TextView>(R.id.headphoneStatus).text = when {
            trusted.isEmpty() -> "No headphones registered: EDITH works with any headphones (or none)."
            !prefs.headphoneLock -> "Registered: ${trusted.joinToString { it.name }} (lock is off)"
            now != null -> "Locked to: ${trusted.joinToString { it.name }}. ${now.name} connected ✓"
            else -> "Locked to: ${trusted.joinToString { it.name }}. Not connected: EDITH is paused."
        }
        val calls = listOf(Manifest.permission.READ_CONTACTS, Manifest.permission.CALL_PHONE,
            Manifest.permission.READ_PHONE_STATE)
            .all { ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED }
        val apps = Settings.canDrawOverlays(this)
        val aliases = prefs.contactAliases
        findViewById<TextView>(R.id.aliases).text = if (aliases.isEmpty())
            "Remembered contacts: none yet. When several contacts match, EDITH asks which one and remembers your answer."
        else "Remembered contacts: " + aliases.entries.joinToString("   ·   ") { "“${it.key}” → ${it.value}" }
        findViewById<TextView>(R.id.actionLog).text =
            EdithState.actionLog.joinToString("\n").ifBlank { "Nothing yet" }
        findViewById<TextView>(R.id.phoneStatus).text =
            "Calls: ${if (calls) "✓ allowed" else "off"}   ·   Open apps & music: ${if (apps) "✓ allowed" else "off"}" +
                "   ·   Typing & Send: ${when {
                    !BuildConfig.WHATSAPP_AUTO_SEND -> "full edition only"
                    WhatsAppSender.isEnabled(this) -> "✓ on (all apps)"
                    else -> "off"
                }}"
        if (EdithState.running) {
            // 0-10 bars on a log scale: lets you see whether EDITH hears anything at all.
            val bars = (kotlin.math.ln(EdithState.micLevel + 1) / kotlin.math.ln(4000.0) * 10).toInt().coerceIn(0, 10)
            micLevel.text = "Mic  " + "▮".repeat(bars) + "▯".repeat(10 - bars)
            micLevel.visibility = View.VISIBLE
        } else {
            micLevel.visibility = View.GONE
        }
        toggle.text = if (EdithState.running) "Stop EDITH" else "Start listening for “Edith”"
        lastQa.text = buildString {
            if (EdithState.lastQuestion.isNotBlank()) append("You: ${EdithState.lastQuestion}\n")
            if (EdithState.lastAnswer.isNotBlank()) append("EDITH: ${EdithState.lastAnswer}")
        }
        lastQa.visibility = if (lastQa.text.isBlank()) View.GONE else View.VISIBLE
        meetingToggle.text = if (EdithState.meetingMode) "End Meeting mode" else "Start Meeting mode"
        val showHeard = EdithState.running && EdithState.lastHeard.isNotBlank() &&
            (EdithState.meetingMode || EdithState.status.startsWith("Conversation"))
        heard.text = if (showHeard) "Heard: ${EdithState.lastHeard}" else ""
        heard.visibility = if (showHeard) View.VISIBLE else View.GONE
    }

    private fun simpleSeek(onChange: (Int) -> Unit) = object : android.widget.SeekBar.OnSeekBarChangeListener {
        override fun onProgressChanged(sb: android.widget.SeekBar?, p: Int, fromUser: Boolean) { if (fromUser) onChange(p) }
        override fun onStartTrackingTouch(sb: android.widget.SeekBar?) {}
        override fun onStopTrackingTouch(sb: android.widget.SeekBar?) { previewPhoneVoice(null) }
    }

    private var previewTts: android.speech.tts.TextToSpeech? = null

    private fun withPreviewTts(block: (android.speech.tts.TextToSpeech) -> Unit) {
        previewTts?.let { block(it); return }
        var engine: android.speech.tts.TextToSpeech? = null
        engine = android.speech.tts.TextToSpeech(this) { status ->
            if (status == android.speech.tts.TextToSpeech.SUCCESS) engine?.let { previewTts = it; block(it) }
            else toast("No text-to-speech engine on this phone.")
        }
    }

    /** Lists the natural offline voices on this phone; tap to hear, OK to choose. */
    private fun choosePhoneVoice() = withPreviewTts { engine ->
        val voices = PhoneVoice.candidates(engine)
        if (voices.isEmpty()) { toast("No offline English voices installed. See the hint below the buttons."); return@withPreviewTts }
        val labels = (listOf("Automatic (most natural)") + voices.map { PhoneVoice.label(it) }).toTypedArray()
        var selected = voices.indexOfFirst { it.name == prefs.phoneVoice } + 1
        runOnUiThread {
            androidx.appcompat.app.AlertDialog.Builder(this)
                .setTitle("EDITH's voice")
                .setSingleChoiceItems(labels, selected) { _, i ->
                    selected = i
                    previewPhoneVoice(if (i == 0) "" else voices[i - 1].name)
                }
                .setPositiveButton("Use this voice") { _, _ ->
                    prefs.phoneVoice = if (selected <= 0) "" else voices[selected - 1].name
                    toast("Saved. EDITH uses it from the next sentence.")
                }
                .setNegativeButton("Cancel", null)
                .show()
        }
    }

    private fun previewPhoneVoice(voiceName: String?) = withPreviewTts { engine ->
        val saved = prefs.phoneVoice
        if (voiceName != null) prefs.phoneVoice = voiceName
        PhoneVoice.apply(engine, prefs)
        if (voiceName != null) prefs.phoneVoice = saved
        engine.speak("Hello ${prefs.address}! Ready when you are. Shall we get some work done?",
            android.speech.tts.TextToSpeech.QUEUE_FLUSH, null, "preview")
    }

    override fun onDestroy() {
        previewTts?.shutdown()
        super.onDestroy()
    }

    /** Plays a sample of the selected human-like voice. */
    private fun testVoice() {
        prefs.missing()?.let { toast(it); return }
        toast("Getting a sample…")
        thread {
            val msg = try {
                val audio = EdithApi(prefs.serverUrl, prefs.password)
                    .speakAudio("Hello ${prefs.address}! This is how I sound. Ready when you are.", prefs.voiceName, "cheerful")
                val f = java.io.File(cacheDir, "voice-test.audio").apply { writeBytes(audio) }
                android.media.MediaPlayer().apply {
                    setDataSource(f.absolutePath)
                    setOnCompletionListener { it.release(); f.delete() }
                    prepare()
                    start()
                }
                null
            } catch (e: EdithException) {
                "Human voice unavailable: ${e.message}"
            } catch (e: Exception) {
                "Couldn't play the sample: ${e.javaClass.simpleName}"
            }
            msg?.let { runOnUiThread { toast(it) } }
        }
    }

    /** Pick which paired Bluetooth headphones EDITH may work with. */
    private fun showHeadphonePicker() {
        val connected = Headphones.connected(this)
        val all = (connected + Headphones.paired(this))
            .filter { it.name.isNotBlank() || it.address.isNotBlank() }
            .distinctBy { it.address.uppercase().ifBlank { it.name } }
        if (all.isEmpty()) {
            toast("No Bluetooth headphones found. Pair and connect them in Android's Bluetooth settings first.")
            return
        }
        val trusted = prefs.trustedHeadphones
        val labels = all.map { d ->
            d.name.ifBlank { d.address } + if (connected.any { Headphones.same(it, d) }) "  (connected)" else ""
        }.toTypedArray()
        val checked = all.map { d -> trusted.any { Headphones.same(it, d) } }.toBooleanArray()
        androidx.appcompat.app.AlertDialog.Builder(this)
            .setTitle("Which headphones can use EDITH?")
            .setMultiChoiceItems(labels, checked) { _, i, on -> checked[i] = on }
            .setPositiveButton("Save") { _, _ ->
                prefs.trustedHeadphones = all.filterIndexed { i, _ -> checked[i] }
                toast(if (prefs.trustedHeadphones.isEmpty()) "No headphones registered: EDITH works with any audio."
                      else "Saved. EDITH now works only with these headphones.")
                render()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun saveAboutMe() {
        val text = findViewById<EditText>(R.id.aboutMe).text.toString().trim()
        prefs.aboutMe = text
        prefs.missing()?.let { toast("Saved on this phone. $it"); return }
        thread {
            val msg = try {
                EdithApi(prefs.serverUrl, prefs.password).saveProfile(text)
                if (text.isBlank()) "About me cleared." else "Saved. EDITH will remember this."
            } catch (e: EdithException) {
                "Saved on this phone, but not on the server: ${e.message}"
            }
            runOnUiThread { toast(msg) }
        }
    }

    /** Calls a contact without voice or server, and reports every step (for troubleshooting). */
    private fun testCall() {
        val input = EditText(this).apply {
            hint = "Contact name, e.g. Mom"
            setSingleLine()
        }
        androidx.appcompat.app.AlertDialog.Builder(this)
            .setTitle("Test call")
            .setMessage("EDITH will find this contact and call it the same way it does by voice. " +
                "Then it shows what happened at each step.")
            .setView(input)
            .setPositiveButton("Call") { _, _ -> runTestCall(input.text.toString().trim()) }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun runTestCall(name: String) {
        if (name.isBlank()) { toast("Type a contact name."); return }
        fun granted(p: String) = ContextCompat.checkSelfPermission(this, p) == PackageManager.PERMISSION_GRANTED
        val report = StringBuilder()
        report.append("Phone: ${Build.MANUFACTURER} ${Build.MODEL}, Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})\n")
        report.append("Permissions: contacts=${granted(Manifest.permission.READ_CONTACTS)}, " +
            "phone=${granted(Manifest.permission.CALL_PHONE)}, phone-state=${granted(Manifest.permission.READ_PHONE_STATE)}, " +
            "display-over-apps=${Settings.canDrawOverlays(this)}\n")
        status.text = "Test call: working…"
        val before = EdithState.actionLog.toList()
        thread {
            val actions = PhoneActions(this, prefs)
            try {
                val matches = actions.findContacts(name)
                report.append("Contact search \"$name\": ${matches.size} match(es) ${matches.joinToString { it.name }}\n")
                when {
                    matches.isEmpty() -> report.append("→ No contact found. Use the name exactly as saved.\n")
                    matches.size > 1 -> report.append("→ More than one match. Use the full name.\n")
                    else -> {
                        val result = actions.placeCall(matches[0])
                        report.append("Result: ${result ?: "call started ✓"}\n")
                    }
                }
            } catch (e: Exception) {
                report.append("CRASH: ${e.javaClass.name}: ${e.message}\n")
            }
            val newLines = EdithState.actionLog.toList().filter { it !in before }.reversed()
            if (newLines.isNotEmpty()) report.append("\nSteps:\n").append(newLines.joinToString("\n"))
            runOnUiThread {
                status.text = EdithState.status
                val text = report.toString()
                androidx.appcompat.app.AlertDialog.Builder(this)
                    .setTitle("Test call report")
                    .setMessage(text)
                    .setPositiveButton("Copy") { _, _ ->
                        getSystemService(android.content.ClipboardManager::class.java)
                            .setPrimaryClip(android.content.ClipData.newPlainText("EDITH test call", text))
                        toast("Copied. Paste it to Claude.")
                    }
                    .setNegativeButton("Close", null)
                    .show()
            }
        }
    }

    /** Meeting mode listens to the room, so the user confirms participants know first. */
    private fun confirmMeeting() {
        prefs.missing()?.let { toast(it); return }
        androidx.appcompat.app.AlertDialog.Builder(this)
            .setTitle("Start Meeting mode?")
            .setMessage(
                "EDITH will listen to the conversation through the phone's microphone, turn what " +
                    "people say into text, and whisper answers to questions in your earbud.\n\n" +
                    "Only start it if everyone in the meeting knows an AI assistant is listening " +
                    "(e.g. say \"I use an AI note assistant\"). Recording people without consent can " +
                    "be illegal and may breach client agreements.\n\n" +
                    "No audio is saved. Only the last ~20 lines of text are kept in memory and " +
                    "deleted when the meeting ends. Put the phone where it can hear the room."
            )
            .setPositiveButton("Everyone knows – start") { _, _ -> setMeeting(true) }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun setMeeting(on: Boolean) {
        EdithState.meetingMode = on
        if (on && !EdithState.running) {
            requestAndStart()
        } else if (EdithState.running) {
            val action = if (on) EdithService.ACTION_MEETING_ON else EdithService.ACTION_MEETING_OFF
            startService(Intent(this, EdithService::class.java).setAction(action))
        }
        render()
    }

    private fun requestAndStart() {
        prefs.missing()?.let { toast(it); return }
        val needed = mutableListOf(Manifest.permission.RECORD_AUDIO)
        if (Build.VERSION.SDK_INT >= 33) needed += Manifest.permission.POST_NOTIFICATIONS
        if (Build.VERSION.SDK_INT >= 31 && ((prefs.micSource == "headset" && !EdithState.meetingMode) || prefs.headphoneLockActive)) {
            needed += Manifest.permission.BLUETOOTH_CONNECT
        }
        val missing = needed.filter { ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isEmpty()) startEdith() else askPermissions.launch(missing.toTypedArray())
    }

    private fun startEdith() {
        ContextCompat.startForegroundService(this, Intent(this, EdithService::class.java))
    }

    private fun testConnection() {
        if (prefs.serverUrl.isBlank()) { toast("Enter your server address first."); return }
        status.text = "Testing connection… (can take up to a minute if the server was asleep)"
        thread {
            val msg = try {
                val api = EdithApi(prefs.serverUrl, prefs.password)
                val h = api.health()
                api.checkPassword()
                val speech = h.optString("speech_provider")
                when {
                    h.optBoolean("mock_mode") -> "Connected, but the server is in mock mode (no AI key)."
                    !h.optBoolean("ai_configured") -> "Connected, but the server's AI is not configured."
                    speech == "none" -> "Connected ✓ but the server can't transcribe speech. Use AI_PROVIDER=groq or openai."
                    else -> "Connected ✓ AI: ${h.optString("ai_provider")}, speech: $speech"
                }
            } catch (e: EdithException) {
                "⚠ ${e.message}"
            } catch (e: Exception) {
                "⚠ Unexpected answer from server. Check the address."
            }
            runOnUiThread { status.text = msg }
        }
    }

    @SuppressLint("BatteryLife") // sideloaded personal assistant: needs to run with the screen off
    private fun openBatterySettings() {
        val pm = getSystemService(PowerManager::class.java)
        if (pm.isIgnoringBatteryOptimizations(packageName)) {
            toast("Already allowed ✓")
            return
        }
        try {
            startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
        } catch (e: Exception) {
            startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        }
    }

    private fun bindText(id: Int, initial: String, save: (String) -> Unit) {
        findViewById<EditText>(id).apply {
            setText(initial)
            addTextChangedListener(object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
                override fun onTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
                override fun afterTextChanged(s: Editable?) = save(s?.toString() ?: "")
            })
        }
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_LONG).show()
}
