function Dot({ ok, warn }) {
  return <span className={`dot ${ok ? 'dot--ok' : warn ? 'dot--warn' : 'dot--bad'}`} aria-hidden="true" />;
}

export default function DeviceStatus({ health, backendError, mic, recognition, synthesis, onProbeMic }) {
  const backendOk = Boolean(health) && !backendError;
  return (
    <section className="glass status" aria-label="Device status">
      <ul>
        <li title={backendError || ''}>
          <Dot ok={backendOk} />
          <span>Backend</span>
          <em>{backendOk ? 'Connected' : backendError ? 'Offline' : 'Checking…'}</em>
        </li>
        <li>
          <Dot ok={backendOk && !health?.mock_mode && health?.ai_configured} warn={health?.mock_mode} />
          <span>AI</span>
          <em>
            {!health ? '—' : health.mock_mode ? 'Mock mode' : health.ai_configured ? health.ai_provider : 'No API key'}
          </em>
        </li>
        <li title={mic.message || mic.active || ''}>
          <Dot ok={mic.status === 'granted'} warn={mic.status === 'unknown'} />
          <span>Mic</span>
          <em>
            {mic.status === 'granted' ? (mic.bluetoothLikely ? 'Earbuds' : 'Ready') :
              mic.status === 'unknown' ? (
                <button className="link-btn" onClick={onProbeMic}>Check</button>
              ) : 'Blocked'}
          </em>
        </li>
        <li>
          <Dot ok={recognition} warn={!recognition} />
          <span>Speech in</span>
          <em>{recognition ? 'Browser' : 'Fallback'}</em>
        </li>
        <li>
          <Dot ok={synthesis} />
          <span>Speech out</span>
          <em>{synthesis ? 'Browser' : 'Unavailable'}</em>
        </li>
      </ul>
      {mic.status === 'granted' && (
        <p className="status__hint">Input: {mic.active}</p>
      )}
      {mic.status === 'error' && <p className="status__hint status__hint--bad" role="alert">{mic.message}</p>}
    </section>
  );
}
