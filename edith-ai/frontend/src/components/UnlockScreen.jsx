import { useState } from 'react';

/** Shown when this device has no EDITH password yet (or the saved one was rejected). */
export default function UnlockScreen({ onUnlock, error, checking }) {
  const [value, setValue] = useState('');
  const [show, setShow] = useState(false);

  function submit(e) {
    e.preventDefault();
    if (value.trim()) onUnlock(value.trim());
  }

  return (
    <div className="unlock">
      <form className="glass unlock__card" onSubmit={submit}>
        <span className="brand__mark unlock__mark" aria-hidden="true" />
        <h1>EDITH</h1>
        <p className="note">Enter your EDITH password to unlock this device. It is stored only on this device.</p>
        <label htmlFor="edith-password" className="sr-only">EDITH password</label>
        <div className="row">
          <input id="edith-password" type={show ? 'text' : 'password'} value={value} autoFocus
            autoComplete="current-password" placeholder="EDITH password"
            onChange={(e) => setValue(e.target.value)} />
          <button type="button" className="btn" onClick={() => setShow((s) => !s)}
            aria-label={show ? 'Hide password' : 'Show password'}>{show ? 'Hide' : 'Show'}</button>
        </div>
        {error && <p className="unlock__error" role="alert">{error}</p>}
        <button className="btn btn--primary unlock__go" type="submit" disabled={checking || !value.trim()}>
          {checking ? 'Checking…' : 'Unlock'}
        </button>
      </form>
    </div>
  );
}
