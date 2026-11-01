package ai.edith.assistant

import android.Manifest
import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.SearchManager
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.PixelFormat
import android.media.AudioManager
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.AlarmClock
import android.provider.ContactsContract
import android.provider.MediaStore
import android.provider.Settings
import android.telecom.TelecomManager
import android.util.Log
import android.view.KeyEvent
import android.view.View
import android.view.WindowManager
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * Performs phone actions described by the EDITH server (call, open app, music, alarm, ...).
 * Everything runs on the device: contact names are matched here and never uploaded.
 */
class PhoneActions(private val ctx: Context, private val prefs: Prefs, private val api: EdithApi? = null) {

    data class Contact(val name: String, val number: String)

    /** Result of preparing an action: what to say, and what to run after saying it. */
    sealed class Plan {
        data class Do(val say: String, val sayAfter: Boolean = false, val run: () -> String?) : Plan()
        data class Call(val contact: Contact) : Plan()
        data class Fail(val say: String) : Plan()
        /** Read back [prompt] and only run [onYes] after the user says "yes". */
        data class Confirm(val prompt: String, val doneSay: String = "Done.", val onYes: () -> String?) : Plan()
        data class Leads(val query: String) : Plan()
    }

    fun plan(action: JSONObject, say: String): Plan = when (action.optString("type")) {
        "call" -> planCall(action.optString("contact"))
        "find_leads" -> {
            val q = action.optString("query").trim()
            if (q.isBlank()) Plan.Fail("Which businesses, and where? For example: find leads for dentists in Indiranagar.")
            else Plan.Leads(q)
        }
        "whatsapp" -> planWhatsApp(action.optString("to"), action.optString("message"))
        "email" -> planEmail(action.optString("to"), action.optString("message"))
        "open_app" -> planOpenApp(action.optString("app"))
        "play_music" -> planMusic(action)
        "media" -> planMedia(action.optString("command"), say)
        "alarm" -> Plan.Do(say) {
            launch(Intent(AlarmClock.ACTION_SET_ALARM)
                .putExtra(AlarmClock.EXTRA_HOUR, action.optInt("hour"))
                .putExtra(AlarmClock.EXTRA_MINUTES, action.optInt("minute"))
                .putExtra(AlarmClock.EXTRA_SKIP_UI, true)
                .apply { action.optString("label").takeIf { it.isNotBlank() && it != "null" }?.let { putExtra(AlarmClock.EXTRA_MESSAGE, it) } },
                "the alarm")
        }
        "timer" -> Plan.Do(say) {
            launch(Intent(AlarmClock.ACTION_SET_TIMER)
                .putExtra(AlarmClock.EXTRA_LENGTH, action.optInt("seconds"))
                .putExtra(AlarmClock.EXTRA_SKIP_UI, true), "the timer")
        }
        "navigate" -> {
            val dest = action.optString("destination")
            Plan.Do(say) {
                val maps = Intent(Intent.ACTION_VIEW, Uri.parse("google.navigation:q=" + Uri.encode(dest)))
                    .setPackage("com.google.android.apps.maps")
                if (isInstalled("com.google.android.apps.maps")) launch(maps, "Maps")
                else launch(Intent(Intent.ACTION_VIEW, Uri.parse("geo:0,0?q=" + Uri.encode(dest))), "Maps")
            }
        }
        else -> Plan.Fail("I can't do that on the phone yet.")
    }

    // ------------------------------------------------------------------ calls

    private fun planCall(spoken: String): Plan {
        if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.READ_CONTACTS) != PackageManager.PERMISSION_GRANTED) {
            return Plan.Fail("I need permission to read your contacts. Turn on calls in the EDITH app.")
        }
        val matches = findContacts(spoken)
        return when {
            matches.isEmpty() -> Plan.Fail("I couldn't find $spoken in your contacts.")
            matches.size == 1 -> Plan.Call(matches[0])
            else -> Plan.Fail("I found ${matches.take(3).joinToString(" and ") { it.name }}. Please say the full name.")
        }
    }

    /** Best-matching contacts for a spoken name. Several only when they are equally good. */
    fun findContacts(spoken: String): List<Contact> {
        if (normalise(spoken).isBlank()) return emptyList()
        val all = mutableListOf<Triple<String, String, Boolean>>()
        ctx.contentResolver.query(
            ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
            arrayOf(
                ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
                ContactsContract.CommonDataKinds.Phone.NUMBER,
                ContactsContract.CommonDataKinds.Phone.IS_SUPER_PRIMARY,
            ), null, null, null,
        )?.use { c ->
            while (c.moveToNext()) {
                val name = c.getString(0) ?: continue
                val number = c.getString(1) ?: continue
                all += Triple(name, number, c.getInt(2) == 1)
            }
        }
        return matchContacts(spoken, all)
    }

    /**
     * Places the call and checks that it really started. Tries, in order:
     * 1. TelecomManager.placeCall (needs the Phone permission),
     * 2. the standard "call" screen (ACTION_CALL, opened like any app),
     * 3. the dialer with the number filled in (you press call).
     */
    @SuppressLint("MissingPermission")
    fun placeCall(contact: Contact): String? {
        val number = contact.number.filter { it.isDigit() || it == '+' || it == '*' || it == '#' }
        if (number.isBlank()) return "${contact.name} has no phone number saved."
        val uri = Uri.fromParts("tel", number, null)
        val who = "${contact.name} (${mask(number)})"
        if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.CALL_PHONE) != PackageManager.PERMISSION_GRANTED) {
            EdithState.log("Call $who: Phone permission is OFF – opening dialer")
            return launch(Intent(Intent.ACTION_DIAL, uri), "the dialer")
                ?: "I opened the dialer. Turn on Allow calls in EDITH so I can call directly."
        }

        // 1) Telecom, with a SIM chosen up front: on dual-SIM phones set to "Ask every time" the
        //    "choose SIM" popup can't appear for a background app, so the call would never start.
        try {
            val extras = Bundle()
            chooseSim()?.let { (handle, label) ->
                extras.putParcelable(TelecomManager.EXTRA_PHONE_ACCOUNT_HANDLE, handle)
                EdithState.log("Call $who: using $label")
            }
            ctx.getSystemService(TelecomManager::class.java).placeCall(uri, extras)
            if (callStarted()) {
                EdithState.log("Call $who: started (Telecom)")
                return null
            }
            EdithState.log("Call $who: Telecom accepted but no call started – trying call screen")
        } catch (e: Exception) {
            Log.w(TAG, "placeCall failed", e)
            EdithState.log("Call $who: Telecom error ${e.javaClass.simpleName}: ${e.message}")
        }

        // 2) Call screen (only if no call is in progress, so we never dial twice)
        if (callStarted(500)) {
            EdithState.log("Call $who: started (Telecom, late)")
            return null
        }
        val err = launch(Intent(Intent.ACTION_CALL, uri), "the call screen")
        if (err == null && callStarted()) {
            EdithState.log("Call $who: started (call screen)")
            return null
        }
        EdithState.log("Call $who: call screen failed${err?.let { " – $it" } ?: ""} – opening dialer")

        // 3) Dialer
        return launch(Intent(Intent.ACTION_DIAL, uri), "the dialer")
            ?: "I couldn't start the call by myself, so I opened the dialer with the number. Press call."
    }

    /** Default calling SIM, or the first SIM when the phone asks every time. Needs READ_PHONE_STATE. */
    @SuppressLint("MissingPermission")
    private fun chooseSim(): Pair<android.telecom.PhoneAccountHandle, String>? {
        if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.READ_PHONE_STATE) != PackageManager.PERMISSION_GRANTED) {
            return null
        }
        return runCatching {
            val tm = ctx.getSystemService(TelecomManager::class.java)
            val default = tm.getDefaultOutgoingPhoneAccount("tel")
            val accounts = tm.callCapablePhoneAccounts
            val handle = default ?: accounts.firstOrNull() ?: return null
            val label = tm.getPhoneAccount(handle)?.label?.toString()?.ifBlank { null } ?: "SIM"
            handle to (if (default != null) "default SIM ($label)" else "SIM 1 of ${accounts.size} ($label) – phone is set to ask every time")
        }.onFailure { Log.w(TAG, "SIM choice failed", it) }.getOrNull()
    }

    /** Waits up to [timeoutMs] for the phone to enter a call. */
    private fun callStarted(timeoutMs: Long = 5000): Boolean {
        val am = ctx.getSystemService(AudioManager::class.java)
        val tm = ctx.getSystemService(TelecomManager::class.java)
        val until = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < until) {
            if (am.mode == AudioManager.MODE_IN_CALL) return true
            // isInCall needs READ_PHONE_STATE (part of "Allow calls"); true as soon as dialling starts.
            val inCall = ContextCompat.checkSelfPermission(ctx, Manifest.permission.READ_PHONE_STATE) ==
                PackageManager.PERMISSION_GRANTED && runCatching { tm.isInCall }.getOrDefault(false)
            if (inCall) return true
            Thread.sleep(200)
        }
        return false
    }

    private fun mask(n: String) = if (n.length > 4) "…" + n.takeLast(4) else n

    // ------------------------------------------------------------------ WhatsApp & email

    private fun planWhatsApp(to: String, message: String): Plan {
        val pkg = listOf("com.whatsapp", "com.whatsapp.w4b").firstOrNull { isInstalled(it) }
            ?: return Plan.Fail("WhatsApp isn't installed on this phone.")
        if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.READ_CONTACTS) != PackageManager.PERMISSION_GRANTED) {
            return Plan.Fail("I need permission to read your contacts. Turn on calls in the EDITH app.")
        }
        val matches = findContacts(to)
        val contact = when {
            matches.isEmpty() -> return Plan.Fail("I couldn't find $to in your contacts.")
            matches.size > 1 -> return Plan.Fail("I found ${matches.take(3).joinToString(" and ") { it.name }}. Please say the full name.")
            else -> matches[0]
        }
        val phone = whatsAppNumber(contact.number)
            ?: return Plan.Fail("${contact.name}'s number has no country code. Set your country code in EDITH settings.")
        val text = message.trim()
        val autoSend = WhatsAppSender.isEnabled(ctx)
        return Plan.Confirm("WhatsApp to ${contact.name}: $text. Should I send it?",
            doneSay = if (autoSend) "Sending it on WhatsApp." else "It's typed in WhatsApp. Tap send.") {
            val auto = WhatsAppSender.isEnabled(ctx)
            if (auto) WhatsAppSender.arm(text)
            val intent = Intent(Intent.ACTION_VIEW,
                Uri.parse("https://api.whatsapp.com/send?phone=$phone&text=" + Uri.encode(text))).setPackage(pkg)
            val err = launch(intent, "WhatsApp")
            when {
                err != null -> { WhatsAppSender.disarm(); err }
                auto -> { EdithState.log("WhatsApp to ${contact.name}: opened, auto-send armed"); null }
                else -> "The message is typed in WhatsApp. Tap send. To let me send it myself, turn on WhatsApp auto-send in EDITH."
            }
        }
    }

    /** Digits with country code, as WhatsApp links need (e.g. 919845012345). */
    fun whatsAppNumber(raw: String): String? =
        intlNumber(raw, prefs.countryCode.ifBlank { defaultCountryCode() })

    private fun defaultCountryCode(): String {
        val iso = runCatching {
            ctx.getSystemService(android.telephony.TelephonyManager::class.java).simCountryIso
        }.getOrNull()?.lowercase().orEmpty().ifBlank { java.util.Locale.getDefault().country.lowercase() }
        return COUNTRY_CODES[iso] ?: ""
    }

    private fun planEmail(to: String, instruction: String): Plan {
        val api = api ?: return Plan.Fail("Email isn't available right now.")
        val (name, address) = if ("@" in to) {
            to.substringBefore("@") to to.trim()
        } else {
            if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.READ_CONTACTS) != PackageManager.PERMISSION_GRANTED) {
                return Plan.Fail("I need permission to read your contacts. Turn on calls in the EDITH app.")
            }
            val matches = findContactEmails(to)
            when {
                matches.isEmpty() -> return Plan.Fail("I couldn't find an email address for $to in your contacts.")
                matches.size > 1 -> return Plan.Fail("I found ${matches.take(3).joinToString(" and ") { it.name }}. Please say the full name.")
                else -> matches[0].name to matches[0].number
            }
        }
        val draft = try {
            api.emailDraft(name, instruction)
        } catch (e: EdithException) {
            return Plan.Fail(e.message ?: "I couldn't write the email.")
        }
        EdithState.update(answer = "✉ To: $address\nSubject: ${draft.subject}\n\n${draft.body}")
        val prompt = "Email to $name. Subject: ${draft.subject}. It says: ${draft.body.replace("\n", " ")}. Should I send it?"
        return Plan.Confirm(prompt, doneSay = "Email sent.") {
            try {
                api.emailSend(address, draft)
                EdithState.log("Email sent to $name ($address)")
                null
            } catch (e: EdithException) {
                EdithState.log("Email to $name failed: ${e.message}")
                e.message ?: "Sending failed."
            }
        }
    }

    /** Contacts with an email address; Contact.number holds the address. */
    fun findContactEmails(spoken: String): List<Contact> {
        val all = mutableListOf<Triple<String, String, Boolean>>()
        ctx.contentResolver.query(
            ContactsContract.CommonDataKinds.Email.CONTENT_URI,
            arrayOf(
                ContactsContract.CommonDataKinds.Email.DISPLAY_NAME_PRIMARY,
                ContactsContract.CommonDataKinds.Email.ADDRESS,
                ContactsContract.CommonDataKinds.Email.IS_SUPER_PRIMARY,
            ), null, null, null,
        )?.use { c ->
            while (c.moveToNext()) {
                val name = c.getString(0) ?: continue
                val email = c.getString(1) ?: continue
                all += Triple(name, email, c.getInt(2) == 1)
            }
        }
        return matchContacts(spoken, all)
    }

    // ------------------------------------------------------------------ apps

    private fun planOpenApp(spoken: String): Plan {
        val wanted = normalise(spoken)
        val pm = ctx.packageManager
        val apps = pm.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)
            .map { it.loadLabel(pm).toString() to it.activityInfo.packageName }
            .distinctBy { it.second }
        val scored = apps.map { (label, pkg) ->
            val l = normalise(label)
            val s = when {
                l == wanted -> 100
                l.replace(" ", "") == wanted.replace(" ", "") -> 95
                l.startsWith("$wanted ") -> 80
                wanted in l.split(' ') -> 70
                similarity(wanted, l) >= 0.8 -> 60
                else -> 0
            }
            Triple(s, label, pkg)
        }.filter { it.first > 0 }.sortedByDescending { it.first }
        val hit = scored.firstOrNull() ?: return Plan.Fail("I couldn't find an app called $spoken.")
        return Plan.Do("Opening ${hit.second}.") {
            val intent = pm.getLaunchIntentForPackage(hit.third) ?: return@Do "I can't open ${hit.second}."
            launch(intent, hit.second)
        }
    }

    // ------------------------------------------------------------------ music & media

    private fun planMusic(action: JSONObject): Plan {
        val appKey = action.optString("app").takeIf { it.isNotBlank() && it != "null" } ?: prefs.musicApp
        val pkg = MUSIC_PACKAGES[appKey] ?: MUSIC_PACKAGES.getValue("spotify")
        val appName = MUSIC_NAMES[appKey] ?: "Spotify"
        if (!isInstalled(pkg)) return Plan.Fail("$appName isn't installed on this phone.")
        val favourite = action.optBoolean("favorite")
        val query = if (favourite) prefs.favoriteMusic.trim() else action.optString("query").trim()
        val say = when {
            favourite && query.isBlank() -> "Playing your music on $appName."
            favourite -> "Playing $query on $appName."
            else -> "Playing $query on $appName."
        }
        return Plan.Do(say) {
            // Standard Android "play from search" (also used by Google Assistant). An empty query asks
            // the app to play something it picks for you (usually your recent music).
            val intent = Intent(MediaStore.INTENT_ACTION_MEDIA_PLAY_FROM_SEARCH)
                .setPackage(pkg)
                .putExtra(SearchManager.QUERY, query)
            val title = action.optString("title").takeIf { it.isNotBlank() && it != "null" }
            val artist = action.optString("artist").takeIf { it.isNotBlank() && it != "null" }
            if (title != null) {
                // "song by artist": tell the app it's a specific track, so it plays that song.
                intent.putExtra(MediaStore.EXTRA_MEDIA_FOCUS, MediaStore.Audio.Media.ENTRY_CONTENT_TYPE)
                    .putExtra(MediaStore.EXTRA_MEDIA_TITLE, title)
                artist?.let { intent.putExtra(MediaStore.EXTRA_MEDIA_ARTIST, it) }
            } else {
                intent.putExtra(MediaStore.EXTRA_MEDIA_FOCUS, "vnd.android.cursor.item/*")
            }
            launch(intent, appName)
        }
    }

    private fun planMedia(command: String, say: String): Plan {
        val am = ctx.getSystemService(AudioManager::class.java)
        fun key(code: Int) {
            val t = SystemClock.uptimeMillis()
            am.dispatchMediaKeyEvent(KeyEvent(t, t, KeyEvent.ACTION_DOWN, code, 0))
            am.dispatchMediaKeyEvent(KeyEvent(t, t, KeyEvent.ACTION_UP, code, 0))
        }
        val run: () -> String? = {
            when (command) {
                "pause" -> key(KeyEvent.KEYCODE_MEDIA_PAUSE)
                "stop" -> key(KeyEvent.KEYCODE_MEDIA_STOP)
                "play", "resume" -> key(KeyEvent.KEYCODE_MEDIA_PLAY)
                "next" -> key(KeyEvent.KEYCODE_MEDIA_NEXT)
                "previous" -> key(KeyEvent.KEYCODE_MEDIA_PREVIOUS)
                "volume_up" -> am.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_RAISE, 0)
                "volume_down" -> am.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_LOWER, 0)
                "mute" -> am.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_MUTE, 0)
            }
            null
        }
        // Speak "Paused" after pausing; announce the others first so the voice isn't covered by music.
        val after = command in setOf("pause", "stop", "mute")
        return Plan.Do(if (command in setOf("play", "resume", "next", "previous")) "" else say, sayAfter = after, run = run)
    }

    // ------------------------------------------------------------------ launching activities

    /**
     * Opens an app screen from the background. Android only allows that when EDITH may
     * "display over other apps"; otherwise a tap-to-open notification is shown instead.
     * Returns a sentence to speak when something went wrong, or null on success.
     */
    fun launch(intent: Intent, what: String): String? {
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (!canOpenAppsInBackground(ctx)) {
            showTapToOpen(intent, what)
            EdithState.log("Open $what: needs 'Display over other apps' – showed tap-to-open")
            return "Tap the notification to open $what. To skip this step, allow EDITH to display over other apps."
        }
        val main = Handler(Looper.getMainLooper())
        val done = CountDownLatch(1)
        var error: String? = null
        main.post {
            // Android only lets a background app open another app while it shows a VISIBLE window.
            // Add a tiny, almost transparent overlay, wait until it has really been drawn, then launch.
            val wm = ctx.getSystemService(WindowManager::class.java)
            val view = View(ctx).apply { setBackgroundColor(0x01000000) }
            val params = WindowManager.LayoutParams(
                2, 2, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                    WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
                PixelFormat.TRANSLUCENT,
            ).apply { gravity = android.view.Gravity.TOP or android.view.Gravity.START }
            val added = runCatching { wm.addView(view, params) }
                .onFailure { Log.w(TAG, "overlay failed", it) }.isSuccess
            val start = Runnable {
                try {
                    startWithBackgroundPermission(intent)
                    EdithState.log("Opened $what")
                } catch (e: ActivityNotFoundException) {
                    error = "I couldn't find an app to open $what."
                } catch (e: Exception) {
                    Log.w(TAG, "launch failed", e)
                    error = "Android blocked opening $what (${e.javaClass.simpleName})."
                }
                error?.let { EdithState.log("Open $what failed: $it") }
                if (added) main.postDelayed({ runCatching { wm.removeView(view) } }, 2500)
                done.countDown()
            }
            // Wait for the overlay's first frame (or 400 ms at most).
            if (added) {
                var fired = false
                val fire = { if (!fired) { fired = true; main.postDelayed(start, 120) } }
                view.viewTreeObserver.addOnDrawListener { main.post { fire() } }
                main.postDelayed({ fire() }, 400)
            } else {
                start.run()
            }
        }
        done.await(4, TimeUnit.SECONDS)
        return error
    }

    /** Android 14+: explicitly let our "display over other apps" permission cover this launch. */
    private fun startWithBackgroundPermission(intent: Intent) {
        if (android.os.Build.VERSION.SDK_INT >= 34) {
            val pi = PendingIntent.getActivity(ctx, intent.hashCode(), intent,
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val options = android.app.ActivityOptions.makeBasic().setPendingIntentBackgroundActivityStartMode(
                android.app.ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED)
            try {
                pi.send(ctx, 0, null, null, null, null, options.toBundle())
                return
            } catch (e: PendingIntent.CanceledException) {
                Log.w(TAG, "PendingIntent launch cancelled, trying startActivity", e)
            }
        }
        ctx.startActivity(intent)
    }

    private fun showTapToOpen(intent: Intent, what: String) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(ACTION_CHANNEL, "EDITH actions", NotificationManager.IMPORTANCE_HIGH))
        val pi = PendingIntent.getActivity(ctx, 100, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        nm.notify(ACTION_NOTIFICATION_ID, NotificationCompat.Builder(ctx, ACTION_CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_edith)
            .setContentTitle("EDITH")
            .setContentText("Tap to open $what")
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(pi)
            .build())
    }

    private fun isInstalled(pkg: String): Boolean =
        runCatching { ctx.packageManager.getPackageInfo(pkg, 0); true }.getOrDefault(false)

    companion object {
        private const val TAG = "EdithActions"
        private const val ACTION_CHANNEL = "edith_actions"
        private const val ACTION_NOTIFICATION_ID = 11

        fun canOpenAppsInBackground(ctx: Context) = Settings.canDrawOverlays(ctx)

        val MUSIC_PACKAGES = mapOf(
            "spotify" to "com.spotify.music",
            "youtube_music" to "com.google.android.apps.youtube.music",
            "youtube" to "com.google.android.youtube",
            "jiosaavn" to "com.jio.media.jiobeats",
            "gaana" to "com.gaana",
            "wynk" to "com.bsbportal.music",
            "amazon_music" to "com.amazon.mp3",
            "apple_music" to "com.apple.android.music",
        )
        val MUSIC_NAMES = mapOf(
            "spotify" to "Spotify", "youtube_music" to "YouTube Music", "youtube" to "YouTube",
            "jiosaavn" to "JioSaavn", "gaana" to "Gaana", "wynk" to "Wynk", "amazon_music" to "Amazon Music",
            "apple_music" to "Apple Music",
        )

        /** "+91 98450 12345", "098450 12345", "9845012345" (cc 91) -> "919845012345"; null if unsure. */
        fun intlNumber(raw: String, cc: String): String? {
            val n = raw.filter { it.isDigit() || it == '+' }
            return when {
                n.startsWith("+") -> n.drop(1).filter { it.isDigit() }
                n.startsWith("00") -> n.drop(2)
                cc.isBlank() -> null
                n.startsWith("0") -> cc + n.trimStart('0')
                n.length == 10 -> cc + n
                n.length > 10 && n.startsWith(cc) -> n
                else -> cc + n
            }?.takeIf { it.length in 8..15 }
        }

        private val COUNTRY_CODES = mapOf(
            "in" to "91", "us" to "1", "ca" to "1", "gb" to "44", "ae" to "971", "sa" to "966", "au" to "61",
            "sg" to "65", "my" to "60", "de" to "49", "fr" to "33", "nl" to "31", "ie" to "353", "nz" to "64",
            "pk" to "92", "bd" to "880", "lk" to "94", "np" to "977", "qa" to "974", "kw" to "965", "om" to "968",
            "bh" to "973", "za" to "27", "ng" to "234", "ke" to "254", "id" to "62", "ph" to "63", "jp" to "81",
        )

        /** Common ways people save family members (incl. Indian usage). */
        private val RELATIONS = mapOf(
            "mother" to listOf("mom", "mum", "mummy", "mother", "mama", "maa", "ma", "amma", "aai", "mom mobile"),
            "father" to listOf("dad", "daddy", "papa", "pappa", "father", "appa", "baba", "pitaji", "dad mobile"),
            "wife" to listOf("wife", "wifey", "my wife", "biwi", "patni"),
            "husband" to listOf("husband", "hubby", "my husband", "pati"),
            "brother" to listOf("brother", "bro", "bhai", "bhaiya", "anna"),
            "sister" to listOf("sister", "sis", "didi", "behen", "akka"),
        )

        fun normalise(s: String): String =
            s.lowercase().replace(Regex("[^\\p{L}\\p{N} ]"), " ").replace(Regex("\\s+"), " ").trim()

        /**
         * Best contacts for a spoken name from (name, number, isPrimary) rows. Returns several
         * only when they are equally good, so EDITH asks instead of calling the wrong person.
         */
        fun matchContacts(spoken: String, rows: List<Triple<String, String, Boolean>>): List<Contact> {
            val wanted = normalise(spoken)
            if (wanted.isBlank()) return emptyList()
            val bare = wanted.removePrefix("my ").trim()
            val spokenForms = listOf(wanted, bare).distinct()
            // Family nicknames ("mummy", "papa", ...) count only as a whole name or clear first name,
            // so "call mom" can never ring a stranger whose name merely starts with "Ma".
            val nicknames = (RELATIONS.values.firstOrNull { bare in it } ?: emptyList()) - spokenForms.toSet()
            val best = mutableMapOf<String, Pair<Int, Contact>>()
            for ((name, number, primary) in rows) {
                val n = normalise(name)
                val nickScore = nicknames.maxOfOrNull { v ->
                    when {
                        n == v -> 100
                        v.length >= 4 && n.split(' ').first() == v -> 75
                        else -> 0
                    }
                } ?: 0
                val score = maxOf(spokenForms.maxOf { scoreName(it, n) }, nickScore)
                if (score <= 0) continue
                val prev = best[n]
                if (prev == null || score > prev.first || (score == prev.first && primary)) {
                    best[n] = score to Contact(name, number)
                }
            }
            if (best.isEmpty()) return emptyList()
            val top = best.values.maxOf { it.first }
            return best.values.filter { it.first == top }.map { it.second }
        }

        fun scoreName(wanted: String, name: String): Int {
            if (name == wanted) return 100
            val nw = name.split(' ')
            val ww = wanted.split(' ')
            if (nw.first() == wanted && nw.size > 1) return 80          // "rahul" -> "rahul sharma"
            if (ww.all { it in nw }) return 70                          // all spoken words present
            if (name.startsWith(wanted) && wanted.length >= 3) return 60
            val sim = similarity(wanted, name)
            if (sim >= 0.8) return (50 * sim).toInt()                   // "priya" vs "pria"
            val firstSim = similarity(wanted, nw.first())
            if (firstSim >= 0.85 && wanted.length >= 4) return (40 * firstSim).toInt()
            return 0
        }

        /** 1.0 = identical; Levenshtein-based. */
        fun similarity(a: String, b: String): Double {
            if (a == b) return 1.0
            if (a.isEmpty() || b.isEmpty()) return 0.0
            val d = Array(a.length + 1) { IntArray(b.length + 1) }
            for (i in 0..a.length) d[i][0] = i
            for (j in 0..b.length) d[0][j] = j
            for (i in 1..a.length) for (j in 1..b.length) {
                val cost = if (a[i - 1] == b[j - 1]) 0 else 1
                d[i][j] = minOf(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            }
            return 1.0 - d[a.length][b.length].toDouble() / maxOf(a.length, b.length)
        }
    }
}
