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

## 1. Nothing to sign up for

The wake word runs **offline on your phone** with the open-source Vosk speech engine. You don't
need an account or key, and nothing is sent anywhere until you say "Edith". The speech model is
built into the app, which is why the download is about 50–60 MB.

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

Then:
1. Tap **Test connection**. You should see `Connected ✓ AI: groq, speech: groq`.
2. Tap **Allow EDITH to run in background** → **Allow**. Without this, Android may stop EDITH
   when the screen is off.
3. Connect your Bluetooth headphones.
4. Tap **Start listening for "Edith"** and allow **microphone**, **notifications** and
   **nearby devices** (needed for the Bluetooth mic).
5. A notification "Listening for "Edith"" appears. Lock the phone and say **"Edith"** → *beep* →
   *"What's the capital of Japan?"*

The first start takes a few seconds while the offline speech model is prepared.

**Wake-word option:** *Only wake when "Edith" is said on its own* (on by default). Say "Edith" or
"Hey Edith", pause briefly, wait for the beep, then ask. Turn it off to also wake when "Edith"
appears inside a longer sentence. That's more responsive but wakes by mistake more often.

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

* Wake-word detection runs **offline on the phone** (Vosk); audio is not sent anywhere until you say "Edith".
* After the wake word, only your question (until you pause) is sent to **your** server.
* A notification is always visible while EDITH listens. Android requires this, and it
  means EDITH never listens secretly.

## Good to know

* **Battery:** always-on offline listening uses noticeable battery, more than a commercial
  wake-word chip. Use **Notification → Stop** when you don't need EDITH. The headphone mic adds extra
  drain on the headphones.
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
| Could not load the wake-word model | Free some phone storage (it needs ~80 MB once) and start again, or reinstall |
| Wrong EDITH password | Use the same password as the website (Render → Environment → `OWNER_ACCESS_TOKEN`) |
| Server can't transcribe speech | Server needs `AI_PROVIDER=groq` or `openai`; redeploy the latest code |
| I didn't hear a question | Start speaking within about 6 seconds of the beep |
| Doesn't react to "Edith" | Say it clearly and pause a moment; try "Hey Edith"; or turn off *Only wake when "Edith" is said on its own* |
| Wakes up by itself | Turn *Only wake when "Edith" is said on its own* back on; use the phone mic in noisy places |
