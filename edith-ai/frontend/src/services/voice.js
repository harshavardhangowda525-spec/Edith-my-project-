// Browser voice pipeline: push-to-talk recognition + speech synthesis.
//
// Platform notes (also in docs/ARCHITECTURE.md):
// - Web Speech recognition is available in Chrome/Edge (desktop + Android) and Safari.
//   Firefox does not support it; there we record a clip with MediaRecorder and send it
//   to /api/voice/transcribe when server-side speech is configured.
// - Browsers do NOT let a page choose which microphone the Web Speech API uses. It uses
//   the OS default input, so set your Bluetooth earbuds as the default mic/speaker in
//   Windows / Android. MediaRecorder (fallback) can target a specific deviceId.
// - The microphone is only active while the push-to-talk button is held. There is no
//   wake word and no continuous/background recording.

const SR = typeof window !== 'undefined' ? window.SpeechRecognition || window.webkitSpeechRecognition : null;

export const recognitionSupported = Boolean(SR);
export const synthesisSupported = typeof window !== 'undefined' && 'speechSynthesis' in window;
export const recorderSupported = typeof window !== 'undefined' && 'MediaRecorder' in window;

const BT_HINT = /(bluetooth|airpods|buds|headset|hands-?free|wh-|wf-|jabra|bose|beats|galaxy buds|pixel buds)/i;

/** Ask for mic permission once and describe available devices. Stops the stream immediately. */
export async function probeMicrophone() {
  if (!navigator.mediaDevices?.getUserMedia) {
    return { status: 'unsupported', message: 'This browser cannot access a microphone (HTTPS or localhost required).' };
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const track = stream.getAudioTracks()[0];
    const active = track?.label || 'Default microphone';
    stream.getTracks().forEach((t) => t.stop());
    const devices = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'audioinput');
    return {
      status: 'granted',
      active,
      bluetoothLikely: BT_HINT.test(active),
      devices: devices.map((d) => ({ id: d.deviceId, label: d.label || 'Microphone' })),
    };
  } catch (e) {
    const map = {
      NotAllowedError: 'Microphone permission was denied. Allow it in the browser address bar, then retry.',
      SecurityError: 'Microphone blocked: open the app via https:// or http://localhost.',
      NotFoundError: 'No microphone found. Connect your earbuds and set them as the default input.',
      NotReadableError: 'The microphone is in use by another app.',
    };
    return { status: 'error', message: map[e.name] || `Microphone error: ${e.message}` };
  }
}

/** Push-to-talk recogniser. Call start() on press, stop() on release. */
export function createRecognizer({ lang, onInterim, onFinal, onError, onEnd }) {
  if (!SR) return null;
  const rec = new SR();
  rec.lang = lang || 'en-US';
  rec.interimResults = true;
  rec.continuous = true; // only while the button is held
  rec.maxAlternatives = 1;
  let finalText = '';
  let active = false;

  rec.onresult = (ev) => {
    let interim = '';
    for (let i = ev.resultIndex; i < ev.results.length; i++) {
      const r = ev.results[i];
      if (r.isFinal) finalText += r[0].transcript;
      else interim += r[0].transcript;
    }
    onInterim?.((finalText + ' ' + interim).trim());
  };
  rec.onerror = (ev) => {
    const msg = {
      'not-allowed': 'Microphone permission denied.',
      'service-not-allowed': 'Speech recognition is blocked by the browser.',
      'no-speech': 'No speech detected. Hold the button and speak.',
      'audio-capture': 'No microphone available.',
      network: 'Speech recognition needs a network connection in this browser.',
      aborted: null,
    }[ev.error];
    if (msg) onError?.(msg, ev.error);
  };
  rec.onend = () => {
    const text = finalText.trim();
    active = false;
    finalText = '';
    if (text) onFinal?.(text);
    onEnd?.();
  };

  return {
    start() {
      if (active) return;
      finalText = '';
      active = true;
      try {
        rec.start();
      } catch {
        /* already started */
      }
    },
    stop() {
      if (active) rec.stop();
    },
    abort() {
      active = false;
      finalText = '';
      rec.abort();
    },
  };
}

/** Fallback recorder for browsers without Web Speech recognition. */
export function createClipRecorder({ deviceId } = {}) {
  let recorder = null;
  let chunks = [];
  let stream = null;
  return {
    async start() {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: deviceId ? { deviceId: { exact: deviceId } } : true,
      });
      chunks = [];
      recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      recorder.start();
    },
    stop() {
      return new Promise((resolve) => {
        if (!recorder) return resolve(null);
        recorder.onstop = () => {
          stream?.getTracks().forEach((t) => t.stop());
          resolve(new Blob(chunks, { type: recorder.mimeType || 'audio/webm' }));
          recorder = null;
        };
        recorder.stop();
      });
    },
  };
}

export function listVoices() {
  return synthesisSupported ? window.speechSynthesis.getVoices() : [];
}

function splitForSpeech(text) {
  // Chrome truncates long utterances; speak sentence-sized pieces.
  const parts = text.replace(/\s+/g, ' ').match(/[^.!?]+[.!?]*\s*/g) || [text];
  const out = [];
  let buf = '';
  for (const p of parts) {
    if ((buf + p).length > 200 && buf) {
      out.push(buf.trim());
      buf = '';
    }
    buf += p;
  }
  if (buf.trim()) out.push(buf.trim());
  return out;
}

let currentAudio = null;

/** Speak text through the default audio output (your earbuds when connected). */
export function speak(text, { voiceName, rate = 1, lang, onStart, onEnd } = {}) {
  stopSpeaking();
  if (!synthesisSupported || !text) {
    onEnd?.();
    return;
  }
  const voice = listVoices().find((v) => v.name === voiceName);
  const pieces = splitForSpeech(text);
  pieces.forEach((piece, i) => {
    const u = new SpeechSynthesisUtterance(piece);
    if (voice) u.voice = voice;
    u.lang = voice?.lang || lang || 'en-US';
    u.rate = rate;
    if (i === 0) u.onstart = () => onStart?.();
    if (i === pieces.length - 1) {
      u.onend = () => onEnd?.();
      u.onerror = () => onEnd?.();
    }
    window.speechSynthesis.speak(u);
  });
}

/** Play server-generated audio (when SPEECH_PROVIDER is configured). */
export function playAudioBlob(blob, { onStart, onEnd } = {}) {
  stopSpeaking();
  const url = URL.createObjectURL(blob);
  currentAudio = new Audio(url);
  currentAudio.onplay = () => onStart?.();
  currentAudio.onended = currentAudio.onerror = () => {
    URL.revokeObjectURL(url);
    currentAudio = null;
    onEnd?.();
  };
  currentAudio.play().catch(() => onEnd?.());
}

export function stopSpeaking() {
  if (synthesisSupported) window.speechSynthesis.cancel();
  if (currentAudio) {
    currentAudio.pause();
    currentAudio.onended?.();
  }
}

/** Remove markdown so synthesized speech sounds natural. */
export function toSpeakable(text) {
  return text
    .replace(/```[\s\S]*?```/g, ' code omitted. ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[(.*?)\]\(.*?\)/g, '$1')
    .replace(/[*_#>]+/g, '')
    .replace(/^\s*[-•]\s+/gm, '')
    .trim();
}
