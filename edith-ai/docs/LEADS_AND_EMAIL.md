# Lead finder, Gmail, WhatsApp: setup

## 1. Lead finder: businesses without a website (Google Maps data)

EDITH uses Google's official **Places API (New)**, the same business data as Google Maps, to find
businesses and keep only the ones **without a website**. A Facebook/Instagram page or directory
listing counts as "no website" (still a lead).

### Get a Google Maps API key (about 10 minutes)
1. Go to <https://console.cloud.google.com> → create a project (e.g. `edith`).
2. **Billing** → link a billing account. Google requires one for Places. It includes a free monthly
   usage allowance; check current pricing at <https://mapsplatform.google.com/pricing>. Each search
   asks for phone and website fields, which are billed per request.
3. **APIs & Services → Library** → search **Places API (New)** → **Enable**.
4. **APIs & Services → Credentials → Create credentials → API key**. Copy it.
5. Click the key → **API restrictions → Restrict key → Places API (New)** → Save. It's then useless
   for anything else if leaked.
6. Optional: **Quotas** → set a daily cap so you can never be billed more than you expect.
7. In **Render → edith-ai → Environment** add `GOOGLE_MAPS_API_KEY` = your key → Save.

### Save leads permanently (Supabase)
Supabase → **SQL Editor** → paste `edith-ai/database/migrations/0002_leads.sql` → **Run**.

### Use it
> "Edith, find me leads for dentists in Indiranagar Bangalore"

EDITH: *"I found 14. Lead 1: Smile Dental, 100 Feet Road, Indiranagar. Rated 4.6 from 38 reviews.
Phone: 9 8 4 5 0, 1 2 3 4 5. Say next, repeat, call, save, or stop."*

| Say | Does |
|---|---|
| next / skip | Next business |
| previous / back | Previous one |
| repeat / number | Read it again |
| call / call them | Calls it (3-second cancellable countdown), marks it *called* |
| save | Saves it to your Leads list |
| stop / done | Ends the lead list |

Saved leads: EDITH website → ⚙ Settings → **Leads**. Change status (called, interested, won…),
delete, or **Download CSV** to open in Excel/Google Sheets.

> Cold calling and messaging businesses is regulated in many countries (e.g. India's TRAI/DND rules,
> GDPR in Europe). Keep it relevant and respect "no".

## 2. Gmail: send emails by voice

EDITH sends with Gmail SMTP and a Google **App password**. It can only **send**; it never reads
your inbox. It always reads the email back and asks **"Should I send it?"** first.

1. Turn on **2-Step Verification**: <https://myaccount.google.com/signinoptions/twosv>
2. Create an **App password**: <https://myaccount.google.com/apppasswords> → name it `EDITH` →
   copy the 16-letter password (spaces don't matter).
3. **Render → edith-ai → Environment**, add:
   * `GMAIL_ADDRESS` = `you@gmail.com`
   * `GMAIL_APP_PASSWORD` = the 16 letters
   * `EMAIL_SENDER_NAME` = your name, for the sign-off (e.g. `Harsha`)
4. Save. Render restarts EDITH.

> "Edith, email Rahul saying the proposal is ready and I'll send it tomorrow"

EDITH finds Rahul's email in your phone contacts, writes a short professional email, reads it back
and sends it only after you say **yes**. You can also say an address: "email rahul at gmail dot com
saying …". To stop EDITH sending email at any time, delete the App password on the Google page above.

## 3. WhatsApp messages

> "Edith, WhatsApp Rahul saying I'll be late by 10 minutes" (or "open WhatsApp and type hello to Priya")

EDITH reads it back. Say **yes** and it opens Rahul's chat with the text typed. With **WhatsApp
auto-send** on, it also presses Send.

### Two editions (because of Google Play Protect)

Google Play Protect's fraud protection (rolled out in India and other countries) **blocks installing
apps from a browser or file manager if they use Accessibility**. Auto-send needs Accessibility, so:

| File on the Releases page | Install from | WhatsApp |
|---|---|---|
| `EDITH-N.apk` (**normal**, recommended) | your phone, as usual | EDITH types the message, **you tap Send** |
| `EDITH-N-full-install-from-PC.apk` | a computer with a USB cable | EDITH also **presses Send**, and can type dictated text into any app (Instagram, Notes…) |

Both share the same settings, and either one installs over the other. Don't turn off Play Protect
to get around the block.

**Installing the full edition from a Windows PC (about 10 minutes, once):**
1. Phone: **Settings → About phone** → tap **Build number** 7 times → enter your PIN. "Developer
   options" is now on.
2. **Settings → System → Developer options** → turn on **USB debugging**. On Xiaomi/Redmi/POCO also
   turn on **Install via USB** (it may ask you to sign in to a Mi account).
3. PC: download **SDK Platform-Tools for Windows** from
   <https://developer.android.com/tools/releases/platform-tools> and unzip it, e.g. to `C:\platform-tools`.
4. Download `EDITH-N-full-install-from-PC.apk` to the PC (e.g. into `C:\platform-tools`).
5. Connect the phone by USB → on the phone tap **Allow USB debugging**.
6. In that folder, Shift + right-click → **Open in Terminal / PowerShell**, then run:
   ```powershell
   .\adb devices
   .\adb install -r EDITH-N-full-install-from-PC.apk
   ```
   (Replace `N` with the build number.) `Success` means it's installed. You can turn USB debugging off again.

**No computer? Install it from the phone itself (Android 11+, about 15 minutes, once):**
This uses Android's own *Wireless debugging*, the same method as the PC, run on the phone.
1. Install **Termux** from F-Droid: <https://f-droid.org/packages/com.termux/> (the Play Store version
   is outdated). Open it and run:
   ```bash
   pkg update && pkg install android-tools
   termux-setup-storage
   ```
2. Connect to Wi-Fi. **Settings → Developer options → Wireless debugging → On** (turn on Developer
   options first: tap *Build number* 7 times).
3. Put **Settings and Termux side by side** (split screen), because the pairing code disappears if you leave
   Settings. Tap **Pair device with pairing code**, then in Termux run (use the numbers shown):
   ```bash
   adb pair 127.0.0.1:PAIRING_PORT PAIRING_CODE
   ```
4. Then connect with the port shown on the main *Wireless debugging* screen, and install the file you
   downloaded in your browser:
   ```bash
   adb connect 127.0.0.1:PORT
   adb install -r ~/storage/downloads/EDITH-N-full-install-from-PC.apk
   ```
   `Success` = done. Turn Wireless debugging off again afterwards.

Then turn on auto-send in the EDITH app (section 4 → **Allow WhatsApp auto-send**):
1. Read the explanation → **Continue** → **Installed apps / Downloaded apps** → **EDITH WhatsApp
   auto-send** → turn on.
2. If Android says **"Restricted setting"**: tap **Open EDITH App info** → **⋮** (top right) →
   **Allow restricted settings** → go back and turn it on again. Android adds this step for
   apps installed outside the Play Store.

How it's limited:
* Android only gives this access to WhatsApp's screen. EDITH can't see any other app.
* It acts only within 20 seconds after you said "yes", and only presses Send if the typed text
  exactly matches the message it read back to you.
* Set **Country code** in the app if your contacts are saved without `+91` etc. (it's detected from
  your SIM otherwise).

## 4. Spotify: play a specific song

> "Edith, open Spotify and play Kesariya by Arijit Singh"

Saying **"*song* by *artist*"** tells Spotify it's an exact track, which picks the right song more often
than a plain search. (Allow **opening apps & music** in section 4 first.)
