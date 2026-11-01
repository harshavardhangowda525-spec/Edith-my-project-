import { useEffect, useRef, useState } from 'react';

export default function ChatPanel({ messages, onSend, busy, interim, onRemember, onClear }) {
  const [text, setText] = useState('');
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, interim]);

  function submit(e) {
    e.preventDefault();
    const t = text.trim();
    if (!t || busy) return;
    onSend(t);
    setText('');
  }

  return (
    <section className="glass chat" aria-label="Conversation">
      <header className="panel-head">
        <h2>Conversation</h2>
        {messages.length > 0 && (
          <button className="link-btn" onClick={onClear} title="Clear this conversation from the screen">
            Clear
          </button>
        )}
      </header>

      <ol className="chat__log" aria-live="polite">
        {messages.length === 0 && !interim && (
          <li className="chat__empty">
            Hold the button (or <kbd>Space</kbd>) and speak, or type below.
            <br />Conversations are not saved unless you choose “Remember”.
          </li>
        )}
        {messages.map((m) => (
          <li key={m.id} className={`msg msg--${m.role}${m.error ? ' msg--error' : ''}`}>
            <div className="msg__bubble">
              {m.content}
              {m.mock && <span className="tag tag--warn">mock</span>}
            </div>
            {m.sources?.length > 0 && (
              <details className="msg__sources">
                <summary>{m.sources.length} source{m.sources.length > 1 ? 's' : ''}</summary>
                <ul>
                  {m.sources.map((s, i) => (
                    <li key={i}>
                      <strong>{s.title}</strong> · part {s.chunk_index + 1}
                      <p>{s.excerpt}</p>
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {m.role === 'user' && !m.error && (
              <button className="link-btn msg__remember" onClick={() => onRemember(m.content)}
                aria-label="Save this message as a memory">
                Remember
              </button>
            )}
          </li>
        ))}
        {interim && (
          <li className="msg msg--user msg--interim">
            <div className="msg__bubble">{interim}…</div>
          </li>
        )}
        {busy && (
          <li className="msg msg--assistant">
            <div className="msg__bubble typing" aria-label="EDITH is thinking"><span /><span /><span /></div>
          </li>
        )}
        <li ref={endRef} aria-hidden="true" />
      </ol>

      <form className="chat__input" onSubmit={submit}>
        <label htmlFor="chat-text" className="sr-only">Message EDITH</label>
        <input id="chat-text" value={text} onChange={(e) => setText(e.target.value)}
          placeholder="Type a message…" maxLength={4000} autoComplete="off" />
        <button type="submit" className="btn btn--primary" disabled={busy || !text.trim()}>Send</button>
      </form>
    </section>
  );
}
