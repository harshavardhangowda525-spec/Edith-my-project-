import { useCallback, useEffect, useRef, useState } from 'react';
import { supabaseAuthEnabled, supabaseSignIn } from '../services/api.js';
import { listVoices, synthesisSupported } from '../services/voice.js';

const TABS = ['General', 'Voice', 'Memory', 'Documents', 'Meeting', 'Privacy'];

export default function SettingsPanel({ open, onClose, settings, onChange, api, health, onClearConversation, notify }) {
  const [tab, setTab] = useState('General');
  const dialogRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    dialogRef.current?.focus();
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;
  const set = (patch) => onChange({ ...settings, ...patch });

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="glass drawer" role="dialog" aria-modal="true" aria-label="Settings"
        tabIndex={-1} ref={dialogRef} onClick={(e) => e.stopPropagation()}>
        <header className="panel-head">
          <h2>Settings</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close settings">✕</button>
        </header>
        <nav className="tabs" role="tablist">
          {TABS.map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? 'tab tab--on' : 'tab'}
              onClick={() => setTab(t)}>{t}</button>
          ))}
        </nav>
        <div className="drawer__body">
          {tab === 'General' && <General settings={settings} set={set} health={health} notify={notify} />}
          {tab === 'Voice' && <Voice settings={settings} set={set} health={health} />}
          {tab === 'Memory' && <MemoryTab api={api} notify={notify} />}
          {tab === 'Documents' && <DocumentsTab api={api} notify={notify} />}
          {tab === 'Meeting' && <MeetingTab api={api} notify={notify} />}
          {tab === 'Privacy' && (
            <PrivacyTab api={api} settings={settings} set={set} notify={notify}
              onClearConversation={onClearConversation} />
          )}
        </div>
      </aside>
    </div>
  );
}

function Field({ label, hint, children }) {
  return (
    <label className="field">
      <span className="field__label">{label}</span>
      {children}
      {hint && <span className="field__hint">{hint}</span>}
    </label>
  );
}

function General({ settings, set, health, notify }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  async function signIn(e) {
    e.preventDefault();
    try {
      const token = await supabaseSignIn(email, password);
      set({ accessToken: token });
      setPassword('');
      notify('Signed in');
    } catch (err) {
      notify(err.message, 'error');
    }
  }
  return (
    <>
      <Field label="Backend API URL" hint="Where the EDITH backend runs. Use https:// outside localhost.">
        <input value={settings.apiUrl} onChange={(e) => set({ apiUrl: e.target.value.trim() })} />
      </Field>
      {supabaseAuthEnabled && health?.auth_mode === 'supabase' ? (
        <form onSubmit={signIn} className="stack">
          <span className="field__label">Sign in</span>
          <input type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          <input type="password" placeholder="Password" value={password}
            onChange={(e) => setPassword(e.target.value)} required />
          <div className="row">
            <button className="btn btn--primary" type="submit">Sign in</button>
            {settings.accessToken && (
              <button type="button" className="btn" onClick={() => set({ accessToken: '' })}>Sign out</button>
            )}
          </div>
        </form>
      ) : (
        <Field label="Access token"
          hint="Your personal token from LOCAL_ACCESS_TOKENS (dev) or a Supabase access token. Stored only in this browser.">
          <input type="password" value={settings.accessToken} autoComplete="off"
            onChange={(e) => set({ accessToken: e.target.value.trim() })} />
        </Field>
      )}
      <Field label="AI model" hint="Leave blank for the server default. Only server-allowed models are accepted.">
        <input value={settings.model} placeholder="server default" onChange={(e) => set({ model: e.target.value.trim() })} />
      </Field>
      <Field label="Response style">
        <select value={settings.mode} onChange={(e) => set({ mode: e.target.value })}>
          <option value="earbud">Earbud – short spoken answers</option>
          <option value="detailed">Detailed – on-screen explanations</option>
          <option value="meeting">Meeting – suggested answers</option>
        </select>
      </Field>
      <Field label="Language" hint="Used for recognition, speech and replies (e.g. en-US, hi-IN, kn-IN, es-ES).">
        <input value={settings.language} onChange={(e) => set({ language: e.target.value.trim() })} />
      </Field>
    </>
  );
}

function Voice({ settings, set, health }) {
  const [voices, setVoices] = useState(listVoices());
  useEffect(() => {
    if (!synthesisSupported) return;
    const update = () => setVoices(listVoices());
    window.speechSynthesis.addEventListener('voiceschanged', update);
    return () => window.speechSynthesis.removeEventListener('voiceschanged', update);
  }, []);
  return (
    <>
      <Field label="Voice">
        <select value={settings.voiceName} onChange={(e) => set({ voiceName: e.target.value })}>
          <option value="">System default</option>
          {voices.map((v) => <option key={v.name} value={v.name}>{v.name} ({v.lang})</option>)}
        </select>
      </Field>
      <Field label={`Speech rate: ${settings.speechRate.toFixed(2)}×`}>
        <input type="range" min="0.7" max="1.6" step="0.05" value={settings.speechRate}
          onChange={(e) => set({ speechRate: Number(e.target.value) })} />
      </Field>
      <label className="check">
        <input type="checkbox" checked={settings.autoSpeak} onChange={(e) => set({ autoSpeak: e.target.checked })} />
        Speak replies aloud
      </label>
      <label className="check">
        <input type="checkbox" checked={settings.serverSpeech} disabled={health?.speech_provider === 'none'}
          onChange={(e) => set({ serverSpeech: e.target.checked })} />
        Use server speech provider {health?.speech_provider === 'none' && '(not configured on server)'}
      </label>
      <p className="note">
        Audio goes to your system’s default output and input. To use Bluetooth earbuds, pair them and
        set them as the default device in Windows Sound settings or Android Bluetooth settings.
        Browsers cannot force a specific Bluetooth microphone.
      </p>
    </>
  );
}

function useList(loader, notify) {
  const [items, setItems] = useState(null);
  const reload = useCallback(async () => {
    try {
      setItems(await loader());
    } catch (e) {
      notify(e.message, 'error');
      setItems([]);
    }
  }, [loader, notify]);
  useEffect(() => {
    reload();
  }, [reload]);
  return [items, reload];
}

function MemoryTab({ api, notify }) {
  const [items, reload] = useList(api.listMemories, notify);
  const [draft, setDraft] = useState('');
  const [editing, setEditing] = useState(null);

  async function add(e) {
    e.preventDefault();
    if (!draft.trim()) return;
    try {
      await api.addMemory(draft.trim());
      setDraft('');
      reload();
    } catch (err) {
      notify(err.message, 'error');
    }
  }
  async function save(id, content) {
    try {
      await api.updateMemory(id, content);
      setEditing(null);
      reload();
    } catch (err) {
      notify(err.message, 'error');
    }
  }
  async function remove(id) {
    try {
      await api.deleteMemory(id);
      reload();
    } catch (err) {
      notify(err.message, 'error');
    }
  }

  return (
    <>
      <p className="note">EDITH only remembers what you explicitly save here or with “Remember”.</p>
      <form className="row" onSubmit={add}>
        <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="e.g. I prefer metric units"
          maxLength={1000} aria-label="New memory" />
        <button className="btn btn--primary" type="submit">Add</button>
      </form>
      {items === null ? <p className="note">Loading…</p> : items.length === 0 ? (
        <p className="note">No memories saved.</p>
      ) : (
        <ul className="list">
          {items.map((m) => (
            <li key={m.id}>
              {editing?.id === m.id ? (
                <form className="row" onSubmit={(e) => { e.preventDefault(); save(m.id, editing.content); }}>
                  <input value={editing.content} autoFocus aria-label="Edit memory"
                    onChange={(e) => setEditing({ ...editing, content: e.target.value })} />
                  <button className="btn btn--primary" type="submit">Save</button>
                  <button className="btn" type="button" onClick={() => setEditing(null)}>Cancel</button>
                </form>
              ) : (
                <>
                  <span className="list__text">{m.content}</span>
                  <button className="link-btn" onClick={() => setEditing({ id: m.id, content: m.content })}>Edit</button>
                  <button className="link-btn link-btn--danger" onClick={() => remove(m.id)}>Delete</button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function DocumentsTab({ api, notify }) {
  const [items, reload] = useList(api.listDocuments, notify);
  const [busy, setBusy] = useState(false);

  async function onFiles(e) {
    const files = Array.from(e.target.files || []);
    e.target.value = '';
    setBusy(true);
    for (const f of files) {
      if (f.size > 900_000) {
        notify(`${f.name} is too large (max ~900 KB of text).`, 'error');
        continue;
      }
      try {
        await api.addDocument(f.name, await f.text());
        notify(`Added ${f.name}`);
      } catch (err) {
        notify(`${f.name}: ${err.message}`, 'error');
      }
    }
    setBusy(false);
    reload();
  }

  return (
    <>
      <p className="note">Upload plain-text or Markdown files (.txt, .md, .csv, .json). EDITH cites them when answering.</p>
      <label className="btn btn--primary file-btn">
        {busy ? 'Uploading…' : 'Upload documents'}
        <input type="file" accept=".txt,.md,.markdown,.csv,.json,text/plain,text/markdown" multiple
          onChange={onFiles} disabled={busy} />
      </label>
      {items === null ? <p className="note">Loading…</p> : items.length === 0 ? (
        <p className="note">No documents uploaded.</p>
      ) : (
        <ul className="list">
          {items.map((d) => (
            <li key={d.id}>
              <span className="list__text">{d.title} <small>({d.chunk_count} parts)</small></span>
              <button className="link-btn link-btn--danger"
                onClick={async () => { await api.deleteDocument(d.id).catch((e) => notify(e.message, 'error')); reload(); }}>
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function MeetingTab({ api, notify }) {
  const [topic, setTopic] = useState('');
  const [notes, setNotes] = useState('');
  const [consent, setConsent] = useState(false);
  const [out, setOut] = useState(null);
  const [busy, setBusy] = useState(false);

  async function run(fn) {
    setBusy(true);
    try {
      setOut(await fn());
    } catch (e) {
      notify(e.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Field label="Prepare a briefing" hint="Built only from your uploaded documents.">
        <div className="row">
          <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="e.g. backend architecture review" />
          <button className="btn btn--primary" disabled={busy || !topic.trim()}
            onClick={() => run(() => api.briefing(topic.trim()))}>Brief me</button>
        </div>
      </Field>
      <Field label="Summarise meeting notes" hint="Paste or dictate notes. EDITH never records in the background.">
        <textarea rows={5} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </Field>
      <label className="check">
        <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
        All participants agreed to note-taking / recording.
      </label>
      <button className="btn btn--primary" disabled={busy || !notes.trim() || !consent}
        onClick={() => run(() => api.summarize(notes, consent))}>Summarise</button>
      {out && (
        <div className="result">
          {out.mock && <span className="tag tag--warn">mock</span>}
          <pre>{out.content}</pre>
          {out.sources?.length > 0 && <p className="note">Sources: {[...new Set(out.sources.map((s) => s.title))].join(', ')}</p>}
        </div>
      )}
    </>
  );
}

function PrivacyTab({ api, settings, set, notify, onClearConversation }) {
  const [enabled, setEnabled] = useState(null);
  useEffect(() => {
    api.getMemorySettings().then((r) => setEnabled(r.memory_enabled)).catch((e) => notify(e.message, 'error'));
  }, [api, notify]);

  async function toggle(v) {
    try {
      const r = await api.setMemoryEnabled(v);
      setEnabled(r.memory_enabled);
    } catch (e) {
      notify(e.message, 'error');
    }
  }

  return (
    <>
      <label className="check">
        <input type="checkbox" checked={Boolean(enabled)} disabled={enabled === null}
          onChange={(e) => toggle(e.target.checked)} />
        Persistent memory (saved memories are stored and used in answers)
      </label>
      <label className="check">
        <input type="checkbox" checked={settings.useMemory} onChange={(e) => set({ useMemory: e.target.checked })} />
        Use saved memories in this browser’s chats
      </label>
      <label className="check">
        <input type="checkbox" checked={settings.useDocuments}
          onChange={(e) => set({ useDocuments: e.target.checked })} />
        Search my documents when answering
      </label>
      <ul className="note">
        <li>Conversations are kept only on this screen and are not stored on the server.</li>
        <li>The microphone is active only while you hold push-to-talk.</li>
        <li>Your messages are sent to the AI provider configured on the server.</li>
      </ul>
      <div className="row">
        <button className="btn" onClick={onClearConversation}>Clear conversation</button>
        <button className="btn link-btn--danger" onClick={() => {
          try { localStorage.clear(); } catch { /* ignore */ }
          notify('Local settings cleared. Reloading…');
          setTimeout(() => window.location.reload(), 600);
        }}>Forget this browser</button>
      </div>
    </>
  );
}
