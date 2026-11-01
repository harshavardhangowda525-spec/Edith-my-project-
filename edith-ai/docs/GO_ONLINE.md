# Use EDITH Anywhere — Step-by-Step

After these steps EDITH has its own `https://` web address. Open it on your phone from anywhere
with internet, connect your headphones, tap the button and ask anything.

You will create **two free accounts** (Supabase for memory, Render for hosting) and paste in
your **AI API key**. This takes about 20 minutes. No coding is needed.

```
Phone + headphones ──internet──► Render (EDITH app + backend) ──► AI provider (your key)
                                            │
                                            └──► Supabase (your memories & documents)
```

---

## Before you start

* An **AI API key**, for example:
  * Groq (free tier available): <https://console.groq.com/keys>, or
  * OpenAI: <https://platform.openai.com/api-keys> (you need billing credit), or
  * Anthropic: <https://console.anthropic.com/> → API Keys.
* Your GitHub login (the account that owns `Edith-my-project-`).

Keep the key secret. Paste it **only** into Render (step B4), never into code or chat.

---

## A. Supabase: permanent memory (about 7 minutes)

1. Go to <https://supabase.com> → **Start your project** → sign in with GitHub.
2. **New project**
   * Name: `edith`
   * Database password: click **Generate a password** (you won't need it again)
   * Region: the one closest to you (for India: **Mumbai**)
   * Click **Create new project** and wait about 2 minutes.
3. Left menu → **SQL Editor** → **New query**.
   Open [`edith-ai/database/schema.sql`](../database/schema.sql) on GitHub, click **Copy raw file**,
   paste it into the editor and click **Run**. You should see *"Success. No rows returned"*.
4. Left menu → **Authentication** → **Users** → **Add user** → **Create new user**.
   * Enter your email and any password, and tick **Auto Confirm User**. Click **Create user**.
   * Click the new user and **copy its User UID** (looks like `3f2a9c1e-…`).
     → This is your **OWNER_USER_ID**.
5. Left menu → **Project Settings** (⚙):
   * **Data API** (or **API**): copy the **Project URL** (`https://xxxx.supabase.co`).
     → This is your **SUPABASE_URL**.
   * **API Keys**: open the **Legacy API keys** tab and copy the **service_role** key
     (click *Reveal*). If your project only shows new keys, copy the **secret** key (`sb_secret_…`).
     → This is your **SUPABASE_SERVICE_ROLE_KEY**. It is very private; never share it.

Write the three values down somewhere safe for the next part.

---

## B. Render: put EDITH online (about 10 minutes)

1. Go to <https://render.com> → **Get Started** → sign up with **GitHub**.
   When GitHub asks which repositories Render may see, allow **Edith-my-project-**.
2. Dashboard → **New +** → **Blueprint**.
3. Choose the **Edith-my-project-** repository.
   * **Branch:** pick `claude/dreamy-planck-xwmyqu`, or `main` if you have merged the code there.
   * Render finds the `render.yaml` file and shows one service called **edith-ai**.
4. Fill in the values it asks for:

   | Setting | What to enter |
   |---|---|
   | `AI_PROVIDER` | `groq`, `openai`, `anthropic`, `openrouter`, `gemini`, `deepseek`, `mistral` or `together` |
   | `AI_API_KEY` | your AI key from that provider |
   | `AI_MODEL` | leave blank for the default model, or enter a model ID from your provider |
   | `AI_BASE_URL` | leave blank (EDITH fills in the provider's address) |
   | `OWNER_USER_ID` | the User UID from A4 |
   | `SUPABASE_URL` | the Project URL from A5 |
   | `SUPABASE_SERVICE_ROLE_KEY` | the service_role / secret key from A5 |

   Default models: groq `llama-3.3-70b-versatile`, openai `gpt-4o-mini`, anthropic
   `claude-sonnet-5-5`. Providers rename models over time. If you see "endpoint or model not
   found", copy a current model ID from your provider's dashboard into `AI_MODEL`.
   See [API_SETUP.md](API_SETUP.md) for other services.
5. Click **Apply** (or **Deploy Blueprint**). The first build takes about 5–8 minutes.
   When it says **Live**, your address is shown at the top, like
   `https://edith-ai-xxxx.onrender.com`.
6. **Get your EDITH password:** open the **edith-ai** service → **Environment** →
   find `OWNER_ACCESS_TOKEN` → click the eye icon and copy it.
   Render generated this long random password for you. Keep it private.

**Check it worked:** open `https://edith-ai-xxxx.onrender.com/health` in a browser. You should see
`"ai_configured":true`, `"mock_mode":false` and `"storage_backend":"supabase"`.

---

## C. Phone + headphones (2 minutes)

1. Pair your Bluetooth headphones with your phone as usual.
2. Open your EDITH address in **Chrome** (Android) or **Safari** (iPhone).
3. Paste your EDITH password → **Unlock**. Allow the microphone when asked.
4. Add it to your home screen so it opens like an app:
   * Android Chrome: **⋮** menu → **Add to Home screen** / **Install app**
   * iPhone Safari: **Share** → **Add to Home Screen**
5. Tap **Tap to talk**, ask your question, and pause. EDITH sends it by itself and answers in your
   headphones. Tap again any time to talk. Use **Stop speaking** to interrupt.

Useful settings (⚙):
* **Voice → Keep screen on while EDITH is open**: stops the phone sleeping in the middle of a conversation.
* **Voice → Talk button**: *Tap to talk* (default on phones) or *Hold to talk*.
* **General → Response style**: *Earbud* gives short spoken answers; *Detailed* gives longer ones on screen.

---

## Good to know

* **Free plan wake-up:** Render's free plan sleeps after about 15 minutes without use. The first
  request after that takes about 30–60 seconds; after that it's fast. To avoid this, change the service
  to a paid **Starter** instance in Render (Settings → Instance Type).
* **Supabase free projects** pause after about a week with no activity. If memory stops working,
  open the Supabase dashboard and click **Restore project**.
* **AI costs:** your AI provider bills per use. Set a monthly spending limit in its dashboard.
* **The screen must be on:** EDITH listens only while its page is open and you tap the button.
  Phones don't let websites listen with the screen off or in your pocket. Screen-off use with the
  headphone button needs the native Android app planned in [HARDWARE_ROADMAP.md](HARDWARE_ROADMAP.md).
* **iPhone:** if voice input doesn't work from the home-screen icon, open the address in Safari.
* **Updates:** Render redeploys automatically whenever new code is pushed to the branch you chose.
* **Change your password:** edit `OWNER_ACCESS_TOKEN` in Render → Environment (24+ random characters)
  and save. Each device will ask for the new password.
* **Lost phone:** change the password as above. The old one stops working immediately.

## Troubleshooting

| You see | Fix |
|---|---|
| "Cannot reach the EDITH server" | The free plan is waking up. Wait 60 seconds and try again |
| Yellow "Mock mode" banner | `AI_PROVIDER` / `AI_API_KEY` are missing in Render → Environment |
| "AI provider rejected the API key" | Wrong key, or no billing credit with the AI provider |
| "OWNER_USER_ID must be the User UID…" | In Supabase → Authentication → Users, click your user and copy the **User UID** (36 characters like `3f2a9c1e-1234-4abc-9def-0123456789ab`), not your email or the project ID. The message tells you how many characters the server received |
| "Database error" | Check `SUPABASE_URL` / key, and that `schema.sql` ran successfully |
| Microphone blocked | Tap the lock icon in the address bar → Permissions → Microphone → Allow |
| Sound plays from the phone speaker | Reconnect the headphones, then reload EDITH |

Render logs: **edith-ai** service → **Logs**. Keys are never printed there.
