import { useEffect, useMemo, useRef, useState } from 'react';

/** Ctrl/Cmd+K command palette. `commands`: [{ id, label, hint, run(arg) , needsArg, placeholder }]. */
export default function CommandPalette({ open, onClose, commands }) {
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const [pending, setPending] = useState(null); // a command waiting for its text argument
  const inputRef = useRef(null);

  useEffect(() => {
    if (open) {
      setQuery('');
      setActive(0);
      setPending(null);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  const list = useMemo(() => {
    if (pending) return [];
    const q = query.trim().toLowerCase();
    return commands.filter((c) => !q || c.label.toLowerCase().includes(q) || c.hint?.toLowerCase().includes(q));
  }, [commands, query, pending]);

  if (!open) return null;

  function choose(cmd) {
    if (cmd.needsArg) {
      setPending(cmd);
      setQuery('');
      setTimeout(() => inputRef.current?.focus(), 0);
      return;
    }
    onClose();
    cmd.run();
  }

  function onKey(e) {
    if (e.key === 'Escape') {
      if (pending) setPending(null);
      else onClose();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, list.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (pending) {
        const value = e.currentTarget.value.trim(); // the DOM value: never one keystroke behind
        if (!value) return;
        onClose();
        pending.run(value);
      } else if (list[active]) {
        choose(list[active]);
      }
    }
  }

  return (
    <div className="palette-backdrop" onClick={onClose}>
      <div className="glass palette" role="dialog" aria-modal="true" aria-label="Command palette"
        onClick={(e) => e.stopPropagation()}>
        <input ref={inputRef} autoFocus value={query} onKeyDown={onKey}
          onChange={(e) => { setQuery(e.target.value); setActive(0); }}
          placeholder={pending ? pending.placeholder || pending.label : 'Type a command…'}
          aria-label={pending ? pending.label : 'Search commands'} />
        {pending && <p className="hint">{pending.label} — press Enter to start, Esc to go back.</p>}
        <ul role="listbox">
          {list.map((c, i) => (
            <li key={c.id}>
              <button role="option" aria-selected={i === active} onMouseEnter={() => setActive(i)}
                onClick={() => choose(c)}>
                <span>{c.label}</span>
                {c.hint && <span className="hint">{c.hint}</span>}
              </button>
            </li>
          ))}
          {!pending && list.length === 0 && <li className="hint">No matching command.</li>}
        </ul>
      </div>
    </div>
  );
}
