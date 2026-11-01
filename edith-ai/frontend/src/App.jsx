import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import VoiceOrb from './components/VoiceOrb.jsx';
import ChatPanel from './components/ChatPanel.jsx';
import DeviceStatus from './components/DeviceStatus.jsx';
import SettingsPanel from './components/SettingsPanel.jsx';
import { createApi, loadSettings, saveSettings } from './services/api.js';
import {
  createClipRecorder,
  createRecognizer,
  playAudioBlob,
  probeMicrophone,
  recognitionSupported,
  recorderSupported,
  speak,
  stopSpeaking,
  synthesisSupported,
  toSpeakable,
} from './services/voice.js';

let nextId = 1;
const uid = () => `m${nextId++}`;

export default function App() {
  const [settings, setSettings] = useState(loadSettings);
  const settingsRef = useRef(settings);
  settingsRef.current = settings;

  const api = useMemo(() => createApi(() => settingsRef.current), []);

  const [state, setState] = useState('idle'); // idle | listening | thinking | speaking
  const [messages, setMessages] = useState([]);
  const [interim, setInterim] = useState('');
  const [health, setHealth] = useState(null);
  const [backendError, setBackendError] = useState('');
  const [mic, setMic] = useState({ status: 'unknown' });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [toast, setToast] = useState(null);

  const recognizerRef = useRef(null);
  const recorderRef = useRef(null);
  const messagesRef = useRef(messages);
  messagesRef.current = messages;

  const notify = useCallback((text, kind = 'info') => {
    setToast({ text, kind, id: Date.now() });
  }, []);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4500);
    return () => clearTimeout(t);
  }, [toast]);

  function updateSettings(next) {
    setSettings(next);
    saveSettings(next);
  }

  // --- backend health polling ---
  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        const h = await api.health();
        if (!cancelled) {
          setHealth(h);
          setBackendError('');
        }
      } catch (e) {
        if (!cancelled) setBackendError(e.message);
      }
    }
    check();
    const id = setInterval(check, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [api, settings.apiUrl]);

  // --- speech output ---
  const say = useCallback(async (text) => {
    const s = settingsRef.current;
    if (!s.autoSpeak || !text) {
      setState('idle');
      return;
    }
    const onStart = () => setState('speaking');
    const onEnd = () => setState((st) => (st === 'speaking' || st === 'thinking' ? 'idle' : st));
    if (s.serverSpeech) {
      try {
        const blob = await api.speak(toSpeakable(text).slice(0, 4000));
        playAudioBlob(blob, { onStart, onEnd });
        return;
      } catch (e) {
        notify(`Server speech failed, using browser voice. (${e.message})`, 'error');
      }
    }
    if (synthesisSupported) {
      speak(toSpeakable(text), { voiceName: s.voiceName, rate: s.speechRate, lang: s.language, onStart, onEnd });
    } else {
      setState('idle');
    }
  }, [api, notify]);

  // --- send message ---
  const send = useCallback(async (text) => {
    const s = settingsRef.current;
    stopSpeaking();
    const history = messagesRef.current
      .filter((m) => !m.error)
      .slice(-12)
      .map(({ role, content }) => ({ role, content }));
    setMessages((ms) => [...ms, { id: uid(), role: 'user', content: text }]);
    setState('thinking');
    try {
      const r = await api.chat({
        message: text,
        history,
        mode: s.mode,
        model: s.model || null,
        language: s.language || null,
        use_memory: s.useMemory,
        use_documents: s.useDocuments,
      });
      setMessages((ms) => [...ms, { id: uid(), role: 'assistant', content: r.reply, sources: r.sources, mock: r.mock }]);
      say(r.reply);
    } catch (e) {
      const hint = e.status === 401 ? ' Add your access token in Settings → General.' : '';
      const msg = /[.!?]$/.test(e.message) ? e.message : `${e.message}.`;
      setMessages((ms) => [...ms, { id: uid(), role: 'assistant', content: msg + hint, error: true }]);
      setState('idle');
    }
  }, [api, say]);

  // --- push-to-talk ---
  const pttStart = useCallback(async () => {
    if (state === 'listening') return;
    stopSpeaking();
    const s = settingsRef.current;
    if (recognitionSupported) {
      if (!recognizerRef.current) {
        recognizerRef.current = createRecognizer({
          lang: s.language,
          onInterim: setInterim,
          onFinal: (t) => {
            setInterim('');
            send(t);
          },
          onError: (msg, code) => {
            notify(msg, 'error');
            if (code === 'not-allowed' || code === 'service-not-allowed') {
              setMic({ status: 'error', message: msg });
            }
          },
          onEnd: () => {
            setInterim('');
            setState((st) => (st === 'listening' ? 'idle' : st));
          },
        });
      }
      setState('listening');
      recognizerRef.current.start();
      return;
    }
    if (recorderSupported && health?.speech_provider && health.speech_provider !== 'none') {
      try {
        recorderRef.current = createClipRecorder();
        await recorderRef.current.start();
        setState('listening');
      } catch (e) {
        notify('Microphone unavailable: ' + e.message, 'error');
        setMic({ status: 'error', message: e.message });
      }
      return;
    }
    notify('Voice input is not supported in this browser. Use Chrome or Edge, or type your message.', 'error');
  }, [state, send, notify, health]);

  const pttEnd = useCallback(async () => {
    if (recognizerRef.current && recognitionSupported) {
      recognizerRef.current.stop();
      return;
    }
    if (recorderRef.current) {
      const blob = await recorderRef.current.stop();
      recorderRef.current = null;
      if (!blob || blob.size < 1000) {
        setState('idle');
        return;
      }
      setState('thinking');
      try {
        const { text } = await api.transcribe(blob, settingsRef.current.language);
        if (text) send(text);
        else setState('idle');
      } catch (e) {
        notify(e.message, 'error');
        setState('idle');
      }
    }
  }, [api, send, notify]);

  // Rebuild the recogniser when the language changes.
  useEffect(() => {
    recognizerRef.current?.abort();
    recognizerRef.current = null;
  }, [settings.language]);

  // Space bar = push-to-talk (when not typing).
  useEffect(() => {
    const typing = (e) => ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName) || e.target.isContentEditable;
    const down = (e) => {
      if (e.code === 'Space' && !e.repeat && !typing(e) && !settingsOpen) {
        e.preventDefault();
        pttStart();
      }
      if (e.key === 'Escape' && state === 'speaking') stopSpeaking();
    };
    const up = (e) => {
      if (e.code === 'Space' && !typing(e) && !settingsOpen) {
        e.preventDefault();
        pttEnd();
      }
    };
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    return () => {
      window.removeEventListener('keydown', down);
      window.removeEventListener('keyup', up);
    };
  }, [pttStart, pttEnd, settingsOpen, state]);

  async function checkMic() {
    setMic(await probeMicrophone());
  }

  async function remember(content) {
    try {
      await api.addMemory(content.slice(0, 1000));
      notify('Saved to memory');
    } catch (e) {
      notify(e.message, 'error');
    }
  }

  const listening = state === 'listening';

  return (
    <div className="app">
      <div className="bg-grid" aria-hidden="true" />
      <header className="topbar">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true" />
          <span className="brand__name">EDITH</span>
          <span className="brand__sub">Personal Intelligence</span>
        </div>
        <button className="icon-btn" onClick={() => setSettingsOpen(true)} aria-label="Open settings">⚙</button>
      </header>

      {health?.mock_mode && (
        <div className="banner" role="status">
          Mock mode: no AI provider is connected, replies are placeholders. Set <code>AI_PROVIDER</code> and{' '}
          <code>AI_API_KEY</code> in <code>backend/.env</code>.
        </div>
      )}

      <main className="layout">
        <section className="stage" aria-label="Voice assistant">
          <VoiceOrb state={state} />
          <div className="controls">
            <button
              className={`ptt ${listening ? 'ptt--on' : ''}`}
              onPointerDown={(e) => {
                e.currentTarget.setPointerCapture?.(e.pointerId);
                pttStart();
              }}
              onPointerUp={pttEnd}
              onPointerCancel={pttEnd}
              onKeyDown={(e) => (e.key === 'Enter' && !e.repeat) && pttStart()}
              onKeyUp={(e) => e.key === 'Enter' && pttEnd()}
              onContextMenu={(e) => e.preventDefault()}
              aria-pressed={listening}
              aria-label="Hold to talk"
              disabled={state === 'thinking'}
            >
              <span className="ptt__icon" aria-hidden="true">🎙</span>
              {listening ? 'Release to send' : 'Hold to talk'}
            </button>
            {state === 'speaking' && (
              <button className="btn" onClick={() => { stopSpeaking(); setState('idle'); }}>Stop speaking</button>
            )}
          </div>
          <DeviceStatus health={health} backendError={backendError} mic={mic} recognition={recognitionSupported}
            synthesis={synthesisSupported} onProbeMic={checkMic} />
        </section>

        <ChatPanel messages={messages} onSend={send} busy={state === 'thinking'} interim={interim}
          onRemember={remember} onClear={() => setMessages([])} />
      </main>

      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} settings={settings}
        onChange={updateSettings} api={api} health={health} notify={notify}
        onClearConversation={() => { setMessages([]); notify('Conversation cleared'); }} />

      {toast && (
        <div key={toast.id} className={`toast toast--${toast.kind}`} role={toast.kind === 'error' ? 'alert' : 'status'}>
          {toast.text}
        </div>
      )}
    </div>
  );
}
