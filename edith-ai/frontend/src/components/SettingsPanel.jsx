import { useCallback, useEffect, useRef, useState } from 'react';
import { supabaseAuthEnabled, supabaseSignIn } from '../services/api.js';
import { listVoices, synthesisSupported } from '../services/voice.js';

const TABS = ['General', 'Voice', 'Memory', 'Documents', 'Leads', 'Meeting', 'Privacy'];

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
          {tab === 'Leads' && <LeadsTab api={api} notify={notify} health={health} />}
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
        <div className="stack">
          <span className="field__label">EDITH password</span>
          <p className="field__hint">
            {settings.accessToken ? 'This device is unlocked. The password is stored only on this device.'
              : 'Not set.'}
          </p>
          {settings.accessToken && (
            <button type="button" className="btn" onClick={() => set({ accessToken: '' })}>
              Lock this device
            </button>
          )}
        </div>
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
      <Field label="Talk button"
        hint="Tap: tap once, speak, and EDITH sends when you pause. Hold: hold while speaking.">
        <select value={settings.talkMode} onChange={(e) => set({ talkMode: e.target.value })}>
          <option value="tap">Tap to talk (best on phones)</option>
          <option value="hold">Hold to talk</option>
        </select>
      </Field>
      <label className="check">
        <input type="checkbox" checked={settings.keepAwake} onChange={(e) => set({ keepAwake: e.target.checked })}
          disabled={!('wakeLock' in navigator)} />
        Keep screen on while EDITH is open {!('wakeLock' in navigator) && '(not supported in this browser)'}
      </label>
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

const MEMORY_CATEGORIES = {
  general: 'General', profile: 'About me', project: 'Project', decision: 'Decision', error_fix: 'Error fix',
  preference: 'Preference', task: 'Task', command: 'Command',
};

function MemoryTab({ api, notify }) {
  const [items, reload] = useList(api.listMemories, notify);
  const [draft, setDraft] = useState('');
  const [draftCat, setDraftCat] = useState('general');
  const [filter, setFilter] = useState('all');
  const [editing, setEditing] = useState(null);
  const shown = items && filter !== 'all' ? items.filter((m) => m.category === filter) : items;

  async function add(e) {
    e.preventDefault();
    if (!draft.trim()) return;
    try {
      await api.addMemory(draft.trim(), draftCat);
      setDraft('');
      reload();
    } catch (err) {
      notify(err.message, 'error');
    }
  }
  async function save(id, content) {
    try {
      await api.updateMemory(id, content, editing?.category);
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
      <p className="note">
        EDITH only remembers what you explicitly save here, with “Remember”, or by saying “remember that …”
        (e.g. “remember for project shop: we decided to use Stripe”). Correct or delete anything here.
      </p>
      <form className="row" onSubmit={add}>
        <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="e.g. I prefer metric units"
          maxLength={1000} aria-label="New memory" />
        <select value={draftCat} onChange={(e) => setDraftCat(e.target.value)} aria-label="Category">
          {Object.entries(MEMORY_CATEGORIES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <button className="btn btn--primary" type="submit">Add</button>
      </form>
      <label className="field">
        <span className="field__label">Show</span>
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="all">All categories</option>
          {Object.entries(MEMORY_CATEGORIES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </label>
      {shown === null ? <p className="note">Loading…</p> : shown.length === 0 ? (
        <p className="note">No memories saved{filter !== 'all' ? ' in this category' : ''}.</p>
      ) : (
        <ul className="list">
          {shown.map((m) => (
            <li key={m.id}>
              {editing?.id === m.id ? (
                <form className="row" onSubmit={(e) => { e.preventDefault(); save(m.id, editing.content); }}>
                  <input value={editing.content} autoFocus aria-label="Edit memory"
                    onChange={(e) => setEditing({ ...editing, content: e.target.value })} />
                  <select value={editing.category} aria-label="Category"
                    onChange={(e) => setEditing({ ...editing, category: e.target.value })}>
                    {Object.entries(MEMORY_CATEGORIES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                  <button className="btn btn--primary" type="submit">Save</button>
                  <button className="btn" type="button" onClick={() => setEditing(null)}>Cancel</button>
                </form>
              ) : (
                <>
                  <span className="list__text">
                    <span className="tag">{MEMORY_CATEGORIES[m.category] || m.category}</span> {m.content}
                  </span>
                  <button className="link-btn" onClick={() => setEditing({ id: m.id, content: m.content, category: m.category })}>Edit</button>
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

const LEAD_STATUSES = ['new', 'called', 'interested', 'not_interested', 'won'];

function LeadsTab({ api, notify, health }) {
  const [items, reload] = useList(api.listLeads, notify);

  async function setStatus(lead, status) {
    try {
      await api.saveLead({ ...lead, status, rating: lead.rating ?? null, reviews: lead.reviews ?? null });
      reload();
    } catch (e) {
      notify(e.message, 'error');
    }
  }

  async function download() {
    try {
      const blob = await api.exportLeads();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'edith-leads.csv';
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      notify(e.message, 'error');
    }
  }

  return (
    <>
      <p className="note">
        On your phone say <em>“Edith, find me leads for dentists in Indiranagar”</em>. EDITH reads businesses
        without a website one by one; say <em>“save”</em> to keep one here.
      </p>
      {health && !health.leads_configured && (
        <p className="note" style={{ color: 'var(--warn)' }}>
          Lead finder isn’t set up yet: add GOOGLE_MAPS_API_KEY on the server (see docs/LEADS_AND_EMAIL.md).
        </p>
      )}
      <button className="btn btn--primary" onClick={download} disabled={!items?.length}>Download CSV (Excel)</button>
      {items === null ? <p className="note">Loading…</p> : items.length === 0 ? (
        <p className="note">No saved leads yet.</p>
      ) : (
        <ul className="list">
          {items.map((l) => (
            <li key={l.id} style={{ flexWrap: 'wrap' }}>
              <span className="list__text">
                <strong>{l.name}</strong>{l.rating ? ` · ${l.rating}★` : ''}<br />
                {l.phone && <a href={`tel:${l.phone}`}>{l.phone}</a>}{' '}
                <small>{l.address}</small>
                {l.maps_url && <> · <a href={l.maps_url} target="_blank" rel="noreferrer">Maps</a></>}
              </span>
              <select value={l.status} onChange={(e) => setStatus(l, e.target.value)} style={{ width: 'auto' }}
                aria-label={`Status of ${l.name}`}>
                {LEAD_STATUSES.map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
              </select>
              <button className="link-btn link-btn--danger"
                onClick={async () => { await api.deleteLead(l.id).catch((e) => notify(e.message, 'error')); reload(); }}>
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
