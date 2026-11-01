# EDITH Android app

Always-on wake word ("Edith") → question → your EDITH server → spoken answer in your headphones.
User guide: [../docs/ANDROID_APP.md](../docs/ANDROID_APP.md).

## Build

GitHub builds it automatically (`.github/workflows/android.yml`) and publishes the APK under
**Releases**. To build yourself (Android Studio, or JDK 17+ and the Android SDK):

```bash
cd edith-ai/android
./gradlew assembleRelease     # -> app/build/outputs/apk/release/app-release.apk
```

The build downloads the offline Vosk model (`vosk-model-small-en-us-0.15`, ~40 MB, Apache-2.0)
from alphacephei.com into `app/build/` and packs it into the APK. Nothing large is committed.

## Code map

| File | Purpose |
|---|---|
| `EdithService.kt` | Foreground service (microphone type): offline Vosk wake word ("edith" + decoy grammar) → voice-activity capture → `/api/voice/transcribe` → `/api/chat` → TextToSpeech |
| `AudioRouting.kt` | Routes input to a Bluetooth headset mic (SCO / `setCommunicationDevice`) |
| `EdithApi.kt` | Minimal HTTP client for the EDITH backend |
| `MainActivity.kt` | Settings screen, permissions, start/stop |
| `Prefs.kt` | Private on-device settings |

## Signing key

`keystore/edith-sideload.jks` (password `edith-sideload`) is committed on purpose. Every build
then has the same signature, so new versions install over old ones without losing settings. It only
identifies this personal, sideloaded app. If you publish the app or want a private key, generate
your own and set `EDITH_KEYSTORE`, `EDITH_KEYSTORE_PASSWORD`, `EDITH_KEY_ALIAS` and `EDITH_KEY_PASSWORD`
(e.g. as GitHub Actions secrets). Phones with the old build must then uninstall it once.
