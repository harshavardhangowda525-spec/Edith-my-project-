const LABELS = {
  idle: 'Idle',
  listening: 'Listening',
  thinking: 'Thinking',
  speaking: 'Speaking',
};

/** Animated holographic EDITH orb. Pure CSS/SVG animation; honours prefers-reduced-motion. */
export default function VoiceOrb({ state = 'idle', level = 0 }) {
  return (
    <div className={`orb orb--${state}`} role="img" aria-label={`EDITH is ${LABELS[state]}`}>
      <div className="orb__halo" />
      <svg className="orb__rings" viewBox="0 0 200 200" aria-hidden="true">
        <defs>
          <radialGradient id="orbCore" cx="50%" cy="45%" r="55%">
            <stop offset="0%" stopColor="#cfe0ff" stopOpacity="0.95" />
            <stop offset="35%" stopColor="#3d7bff" stopOpacity="0.85" />
            <stop offset="75%" stopColor="#0b2a8f" stopOpacity="0.6" />
            <stop offset="100%" stopColor="#020615" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#7aa6ff" />
            <stop offset="100%" stopColor="#1d4ed8" stopOpacity="0.2" />
          </linearGradient>
        </defs>
        <circle className="ring ring--outer" cx="100" cy="100" r="92" />
        <circle className="ring ring--dash" cx="100" cy="100" r="80" />
        <circle className="ring ring--arc" cx="100" cy="100" r="68" />
        <circle className="ring ring--inner" cx="100" cy="100" r="56" />
        <circle className="orb__core" cx="100" cy="100" r="44" fill="url(#orbCore)"
          style={{ transform: `scale(${1 + Math.min(level, 1) * 0.12})` }} />
      </svg>
      <div className="orb__wave" aria-hidden="true">
        {Array.from({ length: 5 }).map((_, i) => <span key={i} style={{ animationDelay: `${i * 0.11}s` }} />)}
      </div>
      <div className="orb__label" aria-live="polite">{LABELS[state]}</div>
    </div>
  );
}
