# Custom Earbud Hardware Roadmap

V1 deliberately uses off-the-shelf Bluetooth earbuds. This document prepares — but does not
implement — a path to dedicated EDITH hardware. The backend API stays the same; only the
client changes.

## Phased plan

| Phase | Hardware | Client | Notes |
|---|---|---|---|
| V1 (now) | Any BT earbuds | Browser on PC/Android | Push-to-talk in the UI |
| V2 | Any BT earbuds | Native Android companion app | Media-button push-to-talk, background-safe audio routing, streaming STT/TTS |
| V3 | Dev-kit earbud/necklace (e.g. nRF5340 / ESP32-S3 + I²S MEMS mics) | Companion app as gateway | Physical PTT button, BLE Audio (LC3) |
| V4 | Custom enclosure | Companion app | Industrial design, certification |

## Bluetooth audio requirements

* **Classic BT:** A2DP (high-quality playback) + HFP (mic). Using the mic switches most
  earbuds to HFP's narrow-band codec (CVSD 8 kHz / mSBC 16 kHz) → lower playback quality while
  talking. Acceptable for an assistant; document it to users.
* **LE Audio (BT 5.2+):** LC3 codec, simultaneous good-quality mic + playback, lower power,
  Auracast. Target this for custom hardware; Android 13+ supports it on compatible phones.
* **Control channel:** BLE GATT service for button events, battery level, firmware version,
  and settings (separate from audio).
* **Latency budget (target < 1.5 s to first audio):** BT capture ~100–200 ms, streaming STT
  ~300 ms after end-of-speech, LLM first token 300–800 ms, streaming TTS first chunk ~200 ms.

## Low-power processing

* Keep heavy compute on the phone/cloud. The earbud does: button handling, mic capture,
  optional on-device voice-activity detection (VAD) to avoid streaming silence.
* Optional on-device wake word only with a visible/audible indicator and user opt-in;
  V1–V2 intentionally use push-to-talk only.
* Candidate SoCs: Nordic nRF5340 (LE Audio), Qualcomm QCC51xx/QCC30xx (LE Audio earbuds,
  requires Qualcomm partnership), ESP32-S3 (prototyping, not earbud-sized).

## Microphone selection

* Digital MEMS mics (PDM or I²S), SNR ≥ 64 dB, AOP ≥ 120 dB SPL.
* At least 2 mics for beamforming / noise suppression; consider a bone-conduction or
  in-ear feedback mic for wind and crowd noise robustness.
* Acoustic port design and mesh matter as much as the part choice — prototype early.

## Battery & charging safety

* Li-ion/LiPo coin cells (40–80 mAh per bud) from reputable suppliers with protection
  circuitry (over-charge, over-discharge, over-current, short-circuit).
* Dedicated charger IC with JEITA temperature-based charging and an NTC thermistor.
* Charging case: own protection IC, certified cells, thermal cutoff.
* Comply with IEC 62133-2 and UN 38.3 for transport; never ship hand-assembled cells to users.
* Certifications for a product: Bluetooth SIG qualification, FCC/CE/IC/WPC (India) radio,
  RoHS/REACH.

## Hardware ↔ software communication

```
[Earbud]  --BLE GATT (button, battery, cfg)-->  [Companion app]  --HTTPS/WSS-->  [EDITH backend]
          --LE Audio / HFP (audio)---------->        │
                                                     └─ streaming STT/TTS (provider adapters)
```

* Proposed GATT service `EDITH Control`: characteristics `ptt_state` (notify),
  `battery` (standard Battery Service), `device_info`, `config` (write, authenticated).
* Companion app reuses the existing REST API (`/api/chat`, `/api/memory`, …) and adds a
  WebSocket streaming endpoint (`/api/voice/stream`, future) for low-latency audio.
* Firmware updates via signed OTA (MCUboot / Nordic DFU), with rollback.
* Pairing uses LE Secure Connections; bond keys stored in secure storage on the phone.

## Smartphone companion (V2)

* Kotlin Android app with a foreground service only while a session is active (visible
  notification); media-button (`KEYCODE_HEADSETHOOK`) push-to-talk.
* `AudioManager.setCommunicationDevice()` (Android 12+) to explicitly select the BT headset mic —
  something browsers cannot do.
* Secure token storage with Android Keystore; Supabase Auth session refresh.

## Custom enclosure

* Start with 3D-printed SLA prototypes from scanned ear-geometry references; iterate on fit
  and acoustic seal with multiple ear-tip sizes.
* Plan for IPX4 sweat resistance, antenna keep-out zones, and serviceable battery position.
* Move to injection moulding only after acoustic and RF validation.

## Ethics & legal

* Visible indicator (LED or tone) whenever the mic streams.
* No covert recording; meeting features require participant consent and comply with local
  recording laws (one- vs two-party consent jurisdictions).
