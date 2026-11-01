# EDITH Android App: say "Edith" and ask anything

The app listens on your phone for the word **"Edith"**, even with the screen off and other apps
open. Say "Edith", wait for the **beep**, ask your question, and EDITH answers in your headphones.

```
"Edith" ─► wake word detected on the phone (nothing is sent yet)
       ─► beep ─► your question is recorded until you pause
       ─► your EDITH server: speech → text (Groq Whisper) → answer (Groq)
       ─► answer spoken in your headphones ─► listening for "Edith" again
```

It uses the EDITH server you already set up ([GO_ONLINE.md](GO_ONLINE.md)) with the same password.

---

## 1. Picovoice: create the "Edith" wake word (5 minutes, free)

1. Go to <https://console.picovoice.ai> and sign up (free account for personal use).
2. On the dashboard, copy your **AccessKey**. You'll paste it into the app.
3. Open **Porcupine Wake Word**:
   * Type the phrase **`Edith`** and click **Train** (you can test it in the browser).
   * Choose platform **Android** and click **Download**.
   * You get a `.zip` file. Inside is a file like `Edith_en_android_v4_0_0.ppn`.
4. Put the `.ppn` file on your phone. Download it directly on the phone and unzip it with the
   **Files** app (tap the zip → **Extract**), or send it to yourself.

> If EDITH misses "Edith" or wakes up by mistake, train **`Hey Edith`** instead. Longer phrases
> are more reliable. You can also adjust **Sensitivity** in the app.

## 2. Make sure your server can understand speech

The app sends your recorded question to your EDITH server, which converts it to text with Groq's
Whisper model using your existing Groq key. **Nothing to set up** if `AI_PROVIDER=groq` (or
`openai`). Check `https://<your-edith-address>/health`; it should show `"speech_provider":"groq"`.
If it shows `"none"`, wait for the latest deploy or click **Manual Deploy → Deploy latest commit**
in Render.

## 3. Install the app

1. On your phone, open your GitHub repository → **Releases** (right side of the repo page, or
   `https://github.com/<you>/Edith-my-project-/releases`).
2. Open the newest **EDITH Android app (build N)** and tap **EDITH-N.apk**.
3. When Android asks, allow **Install unknown apps** for your browser, then tap **Install**.
   (Play Protect may say it doesn't recognise the developer; that's expected for your own app.
   Tap **Install anyway**.)

Updates: install a newer APK the same way. It replaces the old app and keeps your settings.

## 4. Set it up in the app

| Field | What to enter |
|---|---|
| Server address | your EDITH address, e.g. `https://edith-ai-xxxx.onrender.com` |
| EDITH password | the same password you use on the website (`OWNER_ACCESS_TOKEN`) |
| Picovoice AccessKey | from step 1.2 |
| Wake word | **Choose "Edith" file (.ppn)** → pick the file from step 1.3 |

Then:
1. Tap **Test connection**. You should see `Connected ✓ AI: groq, speech: groq`.
2. Tap **Allow EDITH to run in background** → **Allow**. Without this, Android may stop EDITH
   when the screen is off.
3. Connect your Bluetooth headphones.
4. Tap **Start listening for "Edith"** and allow **microphone**, **notifications** and
   **nearby devices** (needed for the Bluetooth mic).
5. A notification "Listening for "Edith"" appears. Lock the phone and say **"Edith"** → *beep* →
   *"What's the capital of Japan?"*

No `.ppn` file yet? Select **"Jarvis" (built-in, for testing)** to try everything first.

## Microphone choice

| Setting | Good | Trade-off |
|---|---|---|
| **Headphone microphone** (default) | Works with the phone in your pocket or bag | Bluetooth stays in "call mode": music sounds like a phone call and the headphone battery drains faster |
| **Phone microphone** | Normal music quality, better battery | The phone must be able to hear you (not deep in a bag) |

If the headphones aren't connected, EDITH uses the phone microphone automatically.

## Other controls

* **Notification → Ask now**: ask without saying the wake word.
* **Notification → Stop**: stop listening. Nothing is recorded while stopped.
* **Headphone play/pause button** (optional setting): pressing it asks EDITH. It may take over
  your music app's play/pause.

## Privacy

* Wake-word detection runs **on the phone** (Picovoice); audio is not sent anywhere until you say "Edith".
* After the wake word, only your question (until you pause) is sent to **your** server.
* A notification is always visible while EDITH listens. Android requires this, and it
  means EDITH never listens secretly.

## Good to know

* **Battery:** always-on listening uses some battery. Picovoice is very efficient, but expect a few
  percent extra per day, more with the headphone mic.
* **First question after a quiet period** may take up to a minute if your Render server is on the
  free plan and asleep. EDITH says so if it times out.
* **After restarting the phone**, open the app and tap Start again. Android doesn't allow
  microphone apps to start on their own at boot.
* **Some phone brands** (Xiaomi, Oppo, Vivo, Realme, OnePlus, Samsung) have extra battery savers.
  If EDITH stops by itself, search "<your phone brand> allow background app" and set EDITH to
  *No restrictions / Allow auto-start*.

## Troubleshooting

| Message | Fix |
|---|---|
| Picovoice AccessKey was refused | Copy the AccessKey again from console.picovoice.ai |
| The wake-word file doesn't fit this app | Download the **Android** version of the `.ppn` again |
| Picovoice device limit reached | Free plans allow a limited number of devices; check your Picovoice console |
| Wrong EDITH password | Use the same password as the website (Render → Environment → `OWNER_ACCESS_TOKEN`) |
| Server can't transcribe speech | Server needs `AI_PROVIDER=groq` or `openai`; redeploy the latest code |
| I didn't hear a question | Start speaking within about 6 seconds of the beep |
| Doesn't react to "Edith" | Raise Sensitivity, speak a bit louder, or train "Hey Edith" |
| Wakes up by itself | Lower Sensitivity |
