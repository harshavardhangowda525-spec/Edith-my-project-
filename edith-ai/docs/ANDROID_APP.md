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

## Conversation mode: keep talking after "Edith"

After you say "Edith" and get your first answer, EDITH **keeps listening**. Ask follow-ups or give
tasks without saying "Edith" again:

```
You: "Edith" → beep → "What's Docker?"            → answers, then keeps listening
You: "And how is it different from a VM?"          → answers (follow-up understood)
You (to a friend): "Let's get lunch at one"        → ignored (not meant for EDITH)
You: "Set a timer for 10 minutes"                  → does it
You: "That's all" / "Stop listening" / "Thanks Edith" → ends with a soft tone
```

* It ends by itself after **2 minutes** without a question for EDITH, then waits for "Edith" again.
* Saying "Edith" in a sentence ("Edith, call Rahul") always counts as meant for EDITH.
* Side conversations are recognised by the AI using the conversation so far. It's usually right
  but not perfect: a question asked to a friend ("what time is it?") may still get answered.
  Overheard remarks are never guessed into phone actions; only clear commands like "set a timer
  for 10 minutes" run without "Edith".
* While it's on, sentences said near you are sent to Groq to be turned into text (nothing is saved),
  so it uses more battery and Groq quota than wake-word-only listening.
* Turn it off in the app: uncheck **Keep listening after "Edith"** (section 2).

## Phone control: calls, apps, music, alarms

Say "Edith", wait for the beep, then:

| Say | EDITH does |
|---|---|
| "Call Mom" / "Call Rahul Sharma" | Finds the contact on your phone, says "Calling Mom", waits **3 seconds** (tap **Cancel call** in the notification to stop), then calls |
| "Open Instagram" / "Open camera" | Opens the app |
| "Open Spotify and play my favourite music" | Plays your *favourite music* (set it in the app) on Spotify |
| "Play Arijit Singh" / "Play lo-fi beats on YouTube Music" | Searches and plays it |
| "Pause" / "Resume" / "Next song" / "Previous song" / "Volume up" | Controls what's playing |
| "Set an alarm for 6 AM" / "Timer for 10 minutes" | Sets it in your Clock app |
| "Navigate to the airport" | Starts Google Maps directions |

**Turn it on** in the app under **4 · Phone control**:
1. **Allow calls**: grants *Contacts* and *Phone*. Contact names are matched **on your phone**;
   your contact list is never sent to the server.
2. **Allow opening apps & music**: turn on *Display over other apps* for EDITH. Android needs
   this to let a background app open other apps (music, Maps, Clock). Without it, EDITH shows a
   notification you tap instead.
3. **My favourite music**: e.g. `Liked Songs`, `Arijit Singh`, `90s Bollywood`. Left blank, the music
   app plays its own pick (usually your recent music). Choose **Spotify**, **YouTube Music** or **JioSaavn**.

Good to know:
* A contact saved exactly as you say it ("Mom") is called straight away. If several match ("Mom Jio",
  "Mom Airtel", "Mummy"), EDITH asks **"Which one?"**. Answer "the first one", "second", or a name
  like "Jio". It **remembers your answer**, so next time "call mom" calls that contact directly
  (same for WhatsApp and email). See or clear remembered choices in section 4. "Mom", "Mummy", "Amma", "Papa", "Dad", "Appa", etc. are understood.
* EDITH pauses listening during phone and WhatsApp calls, and resumes afterwards.
* On a locked phone, music, calls, alarms and timers work; apps you open appear after you unlock.
* **Xiaomi / Redmi / POCO / Oppo / Vivo / Realme:** these phones have an extra switch. Tap the
  button in section 4, then *Other permissions* → allow **Display pop-up windows while running in
  the background**. Without it, apps won't open while you're in another app.
* **Recent actions** (section 4) lists what EDITH tried and whether it worked. Send it to me if a
  call or app launch fails.
* EDITH can't tap buttons inside other apps or read your screen. That would need full
  screen access, which we deliberately don't use.

## Leads, email, WhatsApp

"Find me leads for …", "email … saying …", "WhatsApp … saying …": setup and details in
[LEADS_AND_EMAIL.md](LEADS_AND_EMAIL.md).

## Meeting mode: answers to the client's questions, automatically

Tap **Start Meeting mode** and confirm that everyone in the meeting knows an AI assistant is
listening. Then put the phone on the table, where it can hear the room.

```
Client: "So what does database mean in your project?"
   ─► phone mic hears the sentence ─► text (Groq Whisper) ─► "is this a question for me?"
   ─► EDITH whispers in your earbud: "A database is an organised store of data the app
      reads and writes; in this project it's PostgreSQL on Supabase."
```

* **Automatic:** EDITH answers when someone asks a factual, technical or project question. It
  ignores small talk ("how are you?") and statements. The answer also appears on the phone screen.
* **On demand:** tap **Answer now** in the notification (or say "Edith") to answer the latest
  question right away.
* **Your knowledge:** upload project documents on the EDITH website (Settings → Documents) and
  save memories. EDITH uses them to answer questions about *your* project and says when it's not sure.
* **Microphone:** Meeting mode always uses the **phone** microphone, because the earbud mic mostly hears
  you, not the client. Answers play in your earbuds.
* **End it:** tap **End Meeting mode** in the app or **End meeting** in the notification.

**Privacy and consent:** audio is never saved. Only the last ~20 lines of text are kept in the phone's
memory and deleted when the meeting ends. The server stores nothing. A notification is shown the
whole time. Recording people without their knowledge can be illegal and may breach client
agreements, so tell participants you use an AI assistant (e.g. "I use an AI note assistant").

**Good to know:**
* Answers arrive about 3–6 seconds after the question (longer if the free server was asleep: open
  the app a minute before the meeting).
* Each spoken sentence is sent to Groq for transcription. Long meetings use more of your Groq
  quota; check your limits at console.groq.com.
* Busy rooms, distant speakers or people talking over each other lower accuracy.
* For video calls (Zoom/Meet on a laptop), the phone must be able to hear the laptop's speaker.

## Dictation: "What should I type?"

| Say | EDITH |
|---|---|
| "Open Notes and type" / "Take a note" | *"What should I write, sir?"* → beep → you speak (pauses are fine; stop for ~3 s when done) → creates the note in Google Keep / your notes app |
| "Take a note: call the plumber tomorrow" | Creates it straight away |
| "WhatsApp Rahul" / "Send a message to Mom" | *"What should I say to Rahul?"* → you speak → reads it back → **yes** sends (full edition) or opens it typed (normal edition) |
| "Open Instagram and type" | *"What should I type on Instagram?"* → full edition: opens Instagram, waits for you to open the chat, types it, asks *"Should I send it?"*. Normal edition: opens Instagram's share screen with your text |
| "Type" / "Type I'll call you back" (in any app) | Full edition: types into the open app's text box and offers to press Send. Normal edition: copies it so you can paste |

Typing into other apps and pressing Send needs the **full edition** (installed from a PC) with
**Allow typing & Send in apps** switched on. That access works in any app with a text box, never
types into password fields, and only acts right after you dictate.

## Personality & voice

EDITH is friendly and a little cheeky, calls you **sir** (change it in *EDITH's voice & hearing*), jokes
when it fits (never in Meeting mode or serious moments), and greets you when your headphones
connect: *"Welcome back, sir. Missed me?"*. Say *"Edith, hello, I'm back"* and it responds like it.

**Voice:** EDITH uses the most natural offline voice on your phone automatically. Tap **🗣 Choose
EDITH's voice** to hear and pick another, and adjust **Speed** and **Pitch**. For more natural
voices, install *English (India)* voice data: Settings → System → Languages → Text-to-speech →
Speech Services by Google → ⚙ → Install voice data.

**Groq studio voice (optional, off by default):** with `AI_PROVIDER=groq`, EDITH can speak with Groq's Orpheus voice
(choose Hannah, Diana, Autumn, Daniel, Austin or Troy, then **▶ Test voice**). It's about a second
slower than the phone voice and uses Groq quota. If the server can't produce it, EDITH automatically
uses the phone voice. If *Test voice* reports an error from Groq, open <https://console.groq.com>,
try the Orpheus model in the Playground once (some models ask you to accept terms), then test again.

## Hearing you properly

* EDITH now uses Groq's most accurate speech model (`whisper-large-v3`), Android's noise suppression
  and automatic volume boost, and waits longer before deciding you've finished speaking.
* Add names and unusual words in **Words EDITH should recognise** (your name from *About me* is
  added automatically).
* **🎧 Hearing test:** start EDITH, tap it, speak for 5 seconds. You'll see and hear exactly what
  EDITH understood and how loud your voice arrives.
* Bluetooth earbud mics send call-quality audio. If the test shows mistakes or "quiet", choose **Phone
  microphone** in section 3.

## My headphones: EDITH only works with yours

At the top of the app, **My headphones**:
1. Pair and connect your headphones in Android's Bluetooth settings as usual.
2. Tap **Register my headphones**, allow *Nearby devices*, tick your headphones, then **Save**.
3. Keep **Only work when my registered headphones are connected** on.

Now EDITH **pauses with the microphone off** whenever those headphones aren't connected (status:
*"Waiting for your headphones"*), and when they reconnect it says **"EDITH ready."** and listens
again. To use different headphones, pair them in Android, then register them here (you can tick
several). With no headphones registered, EDITH works with any audio, as before.

> This stops EDITH answering through other headphones. It isn't strong security, because
> Bluetooth names and addresses can be imitated. Your EDITH password still protects your server.

## About me

Section **5 · About me**: write who you are, one fact per line, e.g.

```
My name is Harsha.
I run a web design agency in Bangalore.
I build websites and apps for small businesses.
Sign my emails as: Harsha, Founder
```

Tap **Save "About me"**. EDITH stores it as your profile on your server and uses it in every answer,
email draft and Meeting-mode reply ("What do you do?" → it knows). Edit and save again any time.
(It needs *Persistent memory* on in the website's Privacy settings, which is on by default.)

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
