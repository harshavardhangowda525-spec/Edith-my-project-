import { useCallback, useEffect, useRef, useState } from 'react';

const ACTIVE = ['queued', 'running', 'paused'];

/** Background tasks (progress, cancel/pause/resume/retry, results) and a live system dashboard. */
export default function TasksDrawer({ open, onClose, api, notify, tasks, reloadTasks }) {
  const [tab, setTab] = useState('Tasks');
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    ref.current?.focus();
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="glass drawer" role="dialog" aria-modal="true" aria-label="Tasks and system" tabIndex={-1}
        ref={ref} onClick={(e) => e.stopPropagation()}>
        <header className="panel-head">
          <h2>Tasks &amp; system</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </header>
        <nav className="tabs" role="tablist">
          {['Tasks', 'System'].map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? 'tab tab--on' : 'tab'}
              onClick={() => setTab(t)}>{t}</button>
          ))}
        </nav>
        <div className="drawer__body">
          {tab === 'Tasks' ? <Tasks api={api} notify={notify} tasks={tasks} reload={reloadTasks} />
            : <System api={api} notify={notify} />}
        </div>
      </aside>
    </div>
  );
}

function Tasks({ api, notify, tasks, reload }) {
  async function act(id, action) {
    try {
      await api.taskAction(id, action);
      reload();
    } catch (e) {
      notify(e.message, 'error');
    }
  }
  if (tasks === null) return <p className="note">Loading…</p>;
  if (!tasks.length) {
    return (
      <p className="note">
        No background tasks yet. Say or type “in the background, research …”, “check my GitHub”, or
        “run the tests on my PC”, or press <kbd>Ctrl</kbd>+<kbd>K</kbd>.
      </p>
    );
  }
  return (
    <ul className="list">
      {tasks.map((t) => (
        <li key={t.id} className="task" style={{ display: 'block' }}>
          <div className="task__head">
            <span className="task__title">{t.title}</span>
            <span className={`task__status task__status--${t.status}`}>{t.status}</span>
          </div>
          {ACTIVE.includes(t.status) && <div className="task__bar"><span style={{ width: `${t.progress}%` }} /></div>}
          <div className="task__msg">{t.error || t.message}{t.attempts > 1 ? ` · attempt ${t.attempts}` : ''}</div>
          {t.result && <details><summary className="link-btn">Result</summary><div className="task__result">{t.result}</div></details>}
          <div className="task__actions">
            {t.status === 'running' || t.status === 'queued' ? <button className="link-btn" onClick={() => act(t.id, 'pause')}>Pause</button> : null}
            {t.status === 'paused' && <button className="link-btn" onClick={() => act(t.id, 'resume')}>Resume</button>}
            {ACTIVE.includes(t.status) && <button className="link-btn link-btn--danger" onClick={() => act(t.id, 'cancel')}>Cancel</button>}
            {(t.status === 'failed' || t.status === 'cancelled') && <button className="link-btn" onClick={() => act(t.id, 'retry')}>Retry</button>}
          </div>
        </li>
      ))}
    </ul>
  );
}

const SHOW = [
  ['assistant_first_token_ms', 'First words (server)'],
  ['assistant_total_ms', 'Full answer (server)'],
  ['stt_ms', 'Speech to text'],
  ['context_ms', 'Memory + documents'],
];

function System({ api, notify }) {
  const [m, setM] = useState(null);
  const [bridge, setBridge] = useState(null);
  const load = useCallback(async () => {
    try {
      const [metrics, b] = await Promise.all([api.metrics(), api.bridgeStatus().catch(() => null)]);
      setM(metrics);
      setBridge(b);
    } catch (e) {
      notify(e.message, 'error');
    }
  }, [api, notify]);
  useEffect(() => {
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [load]);
  if (!m) return <p className="note">Loading…</p>;
  const lat = m.latency || {};
  return (
    <>
      <p className="note">Live numbers since the server last started. Measured, not estimated.</p>
      <table className="stats">
        <thead><tr><th>Step</th><th>count</th><th>p50 ms</th><th>p95 ms</th><th>p99 ms</th></tr></thead>
        <tbody>
          {SHOW.filter(([k]) => lat[k]).map(([k, label]) => (
            <tr key={k}><td>{label}</td><td>{lat[k].count}</td><td>{lat[k].p50_ms}</td><td>{lat[k].p95_ms}</td><td>{lat[k].p99_ms}</td></tr>
          ))}
        </tbody>
      </table>
      {!SHOW.some(([k]) => lat[k]) && <p className="note">No questions answered yet.</p>}
      <p className="note">
        Cache hit rate: {m.cache_hit_rate != null ? `${Math.round(m.cache_hit_rate * 100)}%` : '–'} ·
        AI failure rate: {m.ai_failure_rate != null ? `${Math.round(m.ai_failure_rate * 100)}%` : '–'}
        {typeof m.cost_usd === 'number' && <> · Estimated cost: ${m.cost_usd.toFixed(4)}</>}
      </p>
      {m.routes && (
        <p className="note">Models: {Object.entries(m.routes).map(([r, model]) => `${r} → ${model}`).join(' · ')}</p>
      )}
      {m.circuit_breakers && Object.keys(m.circuit_breakers).length > 0 && (
        <p className="note">Circuit breakers: {Object.entries(m.circuit_breakers).map(([k, v]) => `${k}: ${v.open_for_s > 0 ? `paused ${Math.ceil(v.open_for_s)} s` : 'ok'}`).join(' · ')}</p>
      )}
      <p className="note">
        PC bridge: {bridge ? (bridge.online ? `online (${bridge.hostname || 'PC'}${bridge.projects?.length ? `, projects: ${bridge.projects.join(', ')}` : ''})` : 'offline — run python edith_bridge.py serve on your PC') : 'unknown'}
      </p>
    </>
  );
}
