import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import VoiceOrb from './components/VoiceOrb.jsx';
import ChatPanel from './components/ChatPanel.jsx';
import DeviceStatus from './components/DeviceStatus.jsx';
import SettingsPanel from './components/SettingsPanel.jsx';
import UnlockScreen from './components/UnlockScreen.jsx';
import CommandPalette from './components/CommandPalette.jsx';
import TasksDrawer from './components/TasksDrawer.jsx';
import { createApi, loadSettings, saveSettings } from './services/api.js';
import {
  createClipRecorder,
  createRecognizer,
  playAudioBlob,
  probeMicrophone,
  recognitionSupported,
  recorderSupported,
  requestWakeLock,
  speak,
  speakableEnd,
  speakQueued,
  stopSpeaking,
  synthesisSupported,
  toSpeakable,
} from './services/voice.js';

let nextId = 1;

/** Local time as ISO 8601 with the UTC offset (e.g. 2026-11-07T13:42:05+05:30), so "what time is it" is local. */
function localIsoTime(d = new Date()) {
  const pad = (n) => String(Math.floor(Math.abs(n))).padStart(2, '0');
  const off = -d.getTimezoneOffset();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:` +
    `${pad(d.getSeconds())}${off >= 0 ? '+' : '-'}${pad(off / 60)}:${pad(off % 60)}`;
}
const uid = () => `m${nextId++}`;

export default function App() {
  const [settings, setSettings] = useState(loadSettings);
  const settingsRef = useRef(settings);
  settingsRef.current = settings;

  const api = useMemo(() => createApi(() => settingsRef.current), []);

  // idle | listening | understanding | processing | speaking | executing | completed | error
  const [state, setState] = useState('idle');
  const [stateDetail, setStateDetail] = useState('');
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [tasksOpen, setTasksOpen] = useState(false);
  const [tasks, setTasks] = useState(null);
  const [dragging, setDragging] = useState(false);
  const streamRef = useRef(null);
  const knownTasks = useRef({});
  const [messages, setMessages] = useState([]);
  const [interim, setInterim] = useState('');
  const [health, setHealth] = useState(null);
  const [backendError, setBackendError] = useState('');
  const [mic, setMic] = useState({ status: 'unknown' });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [toast, setToast] = useState(null);
  const [unlockError, setUnlockError] = useState('');
  const [unlocking, setUnlocking] = useState(false);

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
    settingsRef.current = next;
    setSettings(next);
    saveSettings(next);
  }

  const lock = useCallback((reason) => {
    const next = { ...settingsRef.current, accessToken: '' };
    settingsRef.current = next;
    setSettings(next);
    saveSettings(next);
    setUnlockError(reason || '');
  }, []);

  // Password gate (personal/local auth). Supabase mode signs in from Settings instead.
  const needsUnlock = Boolean(health) && health.auth_mode !== 'supabase' && !settings.accessToken;

  async function unlock(password) {
    setUnlocking(true);
    setUnlockError('');
    const previous = settingsRef.current;
    settingsRef.current = { ...previous, accessToken: password };
    try {
      await api.getMemorySettings(); // cheap authenticated call to verify the password
      updateSettings({ ...previous, accessToken: password });
    } catch (e) {
      settingsRef.current = previous;
      setUnlockError(e.status === 401 ? 'That password is not correct.' : e.message);
    } finally {
      setUnlocking(false);
    }
  }

  // Optionally keep the screen awake while EDITH is open (re-acquired when returning to the tab).
  useEffect(() => {
    if (!settings.keepAwake) return undefined;
    let lockRef = null;
    const acquire = async () => {
      if (document.visibilityState === 'visible') lockRef = await requestWakeLock();
    };
    acquire();
    document.addEventListener('visibilitychange', acquire);
    return () => {
      document.removeEventListener('visibilitychange', acquire);
      lockRef?.release?.().catch(() => {});
    };
  }, [settings.keepAwake]);

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

  // Brief "Completed" / "Error" flash, then back to idle (unless something else started meanwhile).
  const flash = useCallback((st, detail = '') => {
    setState(st);
    setStateDetail(detail);
    setTimeout(() => setState((cur) => (cur === st ? 'idle' : cur)), 1600);
  }, []);

  // --- send message (streamed: words appear and are spoken as they arrive) ---
  const send = useCallback(async (text) => {
    const s = settingsRef.current;
    stopSpeaking();
    streamRef.current?.abort();
    const ctrl = new AbortController();
    streamRef.current = ctrl;
    const history = messagesRef.current
      .filter((m) => !m.error && m.content)
      .slice(-12)
      .map(({ role, content }) => ({ role, content }));
    const id = uid();
    setMessages((ms) => [...ms, { id: uid(), role: 'user', content: text },
      { id, role: 'assistant', content: '', streaming: true }]);
    setState('understanding');
    setStateDetail('');
    const patch = (fn) => setMessages((ms) => ms.map((m) => (m.id === id ? { ...m, ...fn(m) } : m)));
    const speakLive = s.autoSpeak && !s.serverSpeech && synthesisSupported;
    let full = '';
    let spoken = 0;
    let speaking = 0;
    const onStart = () => { speaking += 1; setState('speaking'); };
    const onEnd = () => {
      speaking -= 1;
      if (speaking <= 0) setState((st) => (st === 'speaking' ? 'idle' : st));
    };
    const voiceOpts = { voiceName: s.voiceName, rate: s.speechRate, lang: s.language, onStart, onEnd };
    let kind = 'answer';
    try {
      await api.assistantStream({
        message: text,
        history,
        mode: s.mode === 'earbud' ? 'earbud' : s.mode,
        model: s.model || null,
        language: s.language || null,
        use_memory: s.useMemory,
        use_documents: s.useDocuments,
        route: s.route && s.route !== 'auto' ? s.route : null,
        client_time: localIsoTime(),
        address: s.address || null,
      }, (ev) => {
        if (ev.type === 'meta') {
          setState('processing');
          setStateDetail(ev.route === 'local' ? 'instant' : `${ev.route} · ${ev.model}`);
          patch(() => ({ model: ev.model, route: ev.route, cached: ev.cached }));
        } else if (ev.type === 'token') {
          full += ev.t;
          patch(() => ({ content: full }));
          if (speakLive) {
            const end = speakableEnd(full.slice(spoken));
            if (end > 0) {
              speakQueued(toSpeakable(full.slice(spoken, spoken + end)), voiceOpts);
              spoken += end;
            }
          }
        } else if (ev.type === 'sources') {
          patch(() => ({ sources: ev.sources }));
        } else if (ev.type === 'task') {
          setState('executing');
          setStateDetail(ev.task.title);
          knownTasks.current[ev.task.id] = ev.task.status;
          setTasks((ts) => [ev.task, ...(ts || [])]);
        } else if (ev.type === 'action') {
          kind = 'action';
          full = `${ev.say} — that's a phone action, so ask me on the EDITH phone app.`;
          patch(() => ({ content: full }));
        } else if (ev.type === 'ignore' || ev.type === 'end') {
          kind = ev.type;
          full = ev.say || full;
          patch(() => ({ content: full }));
        } else if (ev.type === 'done') {
          patch(() => ({ timings: ev.timings, model: ev.model || undefined }));
        }
      }, ctrl.signal);
      patch(() => ({ streaming: false, content: full.trim() || '(no answer)' }));
      const rest = full.slice(spoken).trim();
      if (!s.autoSpeak || !full.trim()) {
        flash('completed');
      } else if (speakLive) {
        if (rest) speakQueued(toSpeakable(rest), voiceOpts);
        else if (speaking <= 0) flash('completed');
      } else {
        say(full);
      }
      if (kind === 'action') setStateDetail('phone action');
    } catch (e) {
      if (e.name === 'AbortError') {
        patch(() => ({ streaming: false }));
        return;
      }
      if (e.status === 401 && settingsRef.current.accessToken && health?.auth_mode !== 'supabase') {
        lock('Your saved password was rejected. Please enter it again.');
      }
      const hint = e.status === 401 ? ' Sign in again to continue.' : '';
      const msg = /[.!?]$/.test(e.message) ? e.message : `${e.message}.`;
      patch((m) => ({ streaming: false, error: !m.content, content: m.content ? `${m.content}\n\n(${msg})` : msg + hint }));
      flash('error', e.code || '');
    }
  }, [api, say, lock, health, flash]);

  const stopAll = useCallback(() => {
    streamRef.current?.abort();
    stopSpeaking();
    setState('idle');
  }, []);

  // --- background tasks: poll while any is active, notify when one finishes ---
  const reloadTasks = useCallback(async () => {
    try {
      const list = await api.listTasks();
      for (const t of list) {
        const before = knownTasks.current[t.id];
        if (before && ['queued', 'running', 'paused'].includes(before) && ['completed', 'failed'].includes(t.status)) {
          const text = t.status === 'completed' ? `Done: ${t.title}` : `Failed: ${t.title} — ${t.error}`;
          notify(text, t.status === 'completed' ? 'info' : 'error');
          if (typeof Notification !== 'undefined' && Notification.permission === 'granted' && document.hidden) {
            new Notification('EDITH', { body: text });
          }
        }
        knownTasks.current[t.id] = t.status;
      }
      setTasks(list);
    } catch {
      /* not signed in yet or offline - try again later */
    }
  }, [api, notify]);

  const anyActive = (tasks || []).some((t) => ['queued', 'running', 'paused'].includes(t.status));
  useEffect(() => {
    if (needsUnlock || !health) return undefined;
    reloadTasks();
    const id = setInterval(reloadTasks, anyActive || tasksOpen ? 3000 : 30000);
    return () => clearInterval(id);
  }, [reloadTasks, anyActive, tasksOpen, needsUnlock, health]);

  async function startTask(type, params, title) {
    try {
      const t = await api.createTask(type, params, title);
      knownTasks.current[t.id] = t.status;
      setTasks((ts) => [t, ...(ts || [])]);
      notify(`Started: ${t.title}`);
      flash('executing', t.title);
    } catch (e) {
      notify(e.message, 'error');
    }
  }

  // --- push-to-talk ---
  const pttStart = useCallback(async () => {
    if (state === 'listening') return;
    stopSpeaking();
    const s = settingsRef.current;
    if (recognitionSupported) {
      if (!recognizerRef.current) {
        recognizerRef.current = createRecognizer({
          lang: s.language,
          continuous: s.talkMode !== 'tap',
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

  // Rebuild the recogniser when the language or talk mode changes.
  useEffect(() => {
    recognizerRef.current?.abort();
    recognizerRef.current = null;
  }, [settings.language, settings.talkMode, send]);

  // Space bar = push-to-talk (when not typing).
  useEffect(() => {
    const typing = (e) => ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName) || e.target.isContentEditable;
    const down = (e) => {
      if (e.code === 'Space' && !e.repeat && !typing(e) && !settingsOpen) {
        e.preventDefault();
        pttStart();
      }
      if (e.key === 'Escape' && ['speaking', 'processing', 'understanding'].includes(state)) stopAll();
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
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
  }, [pttStart, pttEnd, settingsOpen, state, stopAll]);

  // --- drag & drop text/code files onto the page = add them to your documents ---
  async function dropFiles(files) {
    let added = 0;
    for (const f of files) {
      if (f.size > 190_000) {
        notify(`${f.name} is too large (max ~190 KB of text).`, 'error');
        continue;
      }
      const text = await f.text().catch(() => '');
      if (!text.trim() || text.includes('\u0000')) {
        notify(`${f.name} doesn't look like a text file.`, 'error');
        continue;
      }
      try {
        await api.addDocument(f.name, text);
        added += 1;
      } catch (e) {
        notify(e.message, 'error');
      }
    }
    if (added) notify(`Added ${added} file${added > 1 ? 's' : ''} to your documents — ask me about ${added > 1 ? 'them' : 'it'}.`);
  }
  const dragProps = {
    onDragOver: (e) => {
      if (e.dataTransfer?.types?.includes('Files')) {
        e.preventDefault();
        setDragging(true);
      }
    },
    onDragLeave: (e) => {
      if (e.currentTarget === e.target || !e.relatedTarget) setDragging(false);
    },
    onDrop: (e) => {
      e.preventDefault();
      setDragging(false);
      dropFiles(Array.from(e.dataTransfer?.files || []));
    },
  };

  const setRoute = (route) => {
    updateSettings({ ...settingsRef.current, route });
    notify(`Model route: ${route}${route === 'auto' ? ' (EDITH picks fast, balanced or deep)' : ''}`);
  };
  const commands = [
    { id: 'research', label: 'Research in the background…', hint: 'deep model, notifies when done', needsArg: true,
      placeholder: 'What should I research?', run: (q) => startTask('research', { question: q }, `Research: ${q.slice(0, 80)}`) },
    { id: 'github', label: 'Check GitHub…', hint: 'PRs, issues, CI', needsArg: true, placeholder: 'owner/repo (or "default")',
      run: (r) => startTask('github_summary', { repo: r === 'default' ? null : r }, `GitHub: ${r}`) },
    { id: 'tests', label: 'Run tests on my PC…', hint: 'needs the PC bridge; asks on the PC first', needsArg: true,
      placeholder: 'project name (or "default")',
      run: (p) => startTask('pc', { kind: 'run_tests', args: { project: p === 'default' ? null : p } }, `PC: run tests ${p}`) },
    { id: 'gitstatus', label: 'Git status on my PC…', hint: 'PC bridge', needsArg: true, placeholder: 'project name (or "default")',
      run: (p) => startTask('pc', { kind: 'git_status', args: { project: p === 'default' ? null : p } }, `PC: git status ${p}`) },
    { id: 'index', label: 'Index a project on my PC…', hint: 'incremental; only changed files', needsArg: true,
      placeholder: 'project name (or "default")',
      run: (p) => startTask('pc', { kind: 'index_project', args: { project: p === 'default' ? null : p } }, `PC: index ${p}`) },
    { id: 'remember', label: 'Remember…', hint: 'saves a memory', needsArg: true, placeholder: 'What should I remember?',
      run: (t) => send(`remember ${t}`) },
    { id: 'tasks', label: 'Show tasks', hint: 'progress & results', run: () => setTasksOpen(true) },
    { id: 'system', label: 'Show system status', hint: 'latency p50/p95, models, bridge', run: () => setTasksOpen(true) },
    { id: 'auto', label: 'Route: auto', hint: settings.route === 'auto' ? 'current' : '', run: () => setRoute('auto') },
    { id: 'fast', label: 'Route: fast', hint: settings.route === 'fast' ? 'current' : 'quickest model', run: () => setRoute('fast') },
    { id: 'balanced', label: 'Route: balanced', hint: settings.route === 'balanced' ? 'current' : 'coding & detail', run: () => setRoute('balanced') },
    { id: 'deep', label: 'Route: deep', hint: settings.route === 'deep' ? 'current' : 'hard problems, slower', run: () => setRoute('deep') },
    { id: 'minimal', label: settings.minimal ? 'Leave minimal mode' : 'Minimal mode', hint: 'orb only',
      run: () => updateSettings({ ...settingsRef.current, minimal: !settingsRef.current.minimal }) },
    { id: 'notify', label: 'Enable desktop notifications', hint: 'when a task finishes',
      run: () => (typeof Notification !== 'undefined' ? Notification.requestPermission() : notify('Not supported here', 'error')) },
    { id: 'clear', label: 'Clear conversation', run: () => setMessages([]) },
    { id: 'settings', label: 'Open settings', run: () => setSettingsOpen(true) },
  ];
  const activeCount = (tasks || []).filter((t) => ['queued', 'running', 'paused'].includes(t.status)).length;
  const lastAnswer = [...messages].reverse().find((m) => m.role === 'assistant');

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
  const tapMode = settings.talkMode === 'tap';
  const talkHandlers = tapMode
    ? { onClick: () => (listening ? pttEnd() : pttStart()) }
    : {
        onPointerDown: (e) => {
          e.currentTarget.setPointerCapture?.(e.pointerId);
          pttStart();
        },
        onPointerUp: pttEnd,
        onPointerCancel: pttEnd,
        onKeyDown: (e) => e.key === 'Enter' && !e.repeat && pttStart(),
        onKeyUp: (e) => e.key === 'Enter' && pttEnd(),
      };
  const talkLabel = tapMode ? (listening ? 'Listening… tap to send' : 'Tap to talk')
    : (listening ? 'Release to send' : 'Hold to talk');

  if (needsUnlock) {
    return (
      <div className="app">
        <div className="bg-grid" aria-hidden="true" />
        <UnlockScreen onUnlock={unlock} error={unlockError} checking={unlocking} />
      </div>
    );
  }

  return (
    <div className="app" {...dragProps}>
      <div className="bg-grid" aria-hidden="true" />
      <header className="topbar">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true" />
          <span className="brand__name">EDITH</span>
          <span className="brand__sub">Personal Intelligence</span>
        </div>
        <div className="topbar__actions">
          <button className="icon-btn" onClick={() => setPaletteOpen(true)} aria-label="Commands (Ctrl+K)" title="Commands (Ctrl+K)">⌘</button>
          <button className="icon-btn icon-btn--badge" data-count={activeCount || undefined} onClick={() => setTasksOpen(true)}
            aria-label={`Tasks and system${activeCount ? `, ${activeCount} running` : ''}`} title="Tasks & system">☰</button>
          <button className="icon-btn" onClick={() => setSettingsOpen(true)} aria-label="Open settings">⚙</button>
        </div>
      </header>

      {health?.mock_mode && (
        <div className="banner" role="status">
          Mock mode: no AI provider is connected, replies are placeholders. Set <code>AI_PROVIDER</code> and{' '}
          <code>AI_API_KEY</code> on the server (Render → Environment, or <code>backend/.env</code> locally).
        </div>
      )}

      <main className={`layout${settings.minimal ? ' layout--minimal' : ''}`}>
        <section className="stage" aria-label="Voice assistant">
          <VoiceOrb state={state} detail={['processing', 'executing', 'error'].includes(state) ? stateDetail : ''} />
          {settings.minimal && lastAnswer && <p className="minimal-answer" aria-live="polite">{lastAnswer.content}</p>}
          <div className="controls">
            <button
              className={`ptt ${listening ? 'ptt--on' : ''}`}
              {...talkHandlers}
              onContextMenu={(e) => e.preventDefault()}
              aria-pressed={listening}
              aria-label={talkLabel}
            >
              <span className="ptt__icon" aria-hidden="true">🎙</span>
              {talkLabel}
            </button>
            {['speaking', 'processing', 'understanding'].includes(state) && (
              <button className="btn" onClick={stopAll}>Stop</button>
            )}
          </div>
          <DeviceStatus health={health} backendError={backendError} mic={mic} recognition={recognitionSupported}
            synthesis={synthesisSupported} onProbeMic={checkMic} />
        </section>

        {!settings.minimal && (
          <ChatPanel messages={messages} onSend={send} busy={state === 'thinking'} interim={interim}
            onRemember={remember} onClear={() => setMessages([])} />
        )}
      </main>

      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} settings={settings}
        onChange={updateSettings} api={api} health={health} notify={notify}
        onClearConversation={() => { setMessages([]); notify('Conversation cleared'); }} />

      <TasksDrawer open={tasksOpen} onClose={() => setTasksOpen(false)} api={api} notify={notify}
        tasks={tasks} reloadTasks={reloadTasks} />
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} commands={commands} />
      {dragging && <div className="dropzone">Drop text or code files to add them to your documents</div>}

      {toast && (
        <div key={toast.id} className={`toast toast--${toast.kind}`} role={toast.kind === 'error' ? 'alert' : 'status'}>
          {toast.text}
        </div>
      )}
    </div>
  );
}
