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
            askCallPermissions.launch(arrayOf(Manifest.permission.READ_CONTACTS, Manifest.permission.CALL_PHONE))
        }
        findViewById<Button>(R.id.allowApps).setOnClickListener {
            if (Settings.canDrawOverlays(this)) toast("Already allowed ✓")
            else startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
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
        val calls = listOf(Manifest.permission.READ_CONTACTS, Manifest.permission.CALL_PHONE)
            .all { ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED }
        val apps = Settings.canDrawOverlays(this)
        findViewById<TextView>(R.id.phoneStatus).text =
            "Calls: ${if (calls) "✓ allowed" else "off"}   ·   Open apps & music: ${if (apps) "✓ allowed" else "off"}"
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
        val showHeard = EdithState.meetingMode && EdithState.lastHeard.isNotBlank()
        heard.text = if (showHeard) "Heard: ${EdithState.lastHeard}" else ""
        heard.visibility = if (showHeard) View.VISIBLE else View.GONE
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
        if (Build.VERSION.SDK_INT >= 31 && prefs.micSource == "headset" && !EdithState.meetingMode) {
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
