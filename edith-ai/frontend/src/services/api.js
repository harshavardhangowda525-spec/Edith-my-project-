// Thin client for the EDITH backend. No secrets live here: the browser only ever
// holds the user's own access token, never AI or service-role keys.

const STORAGE_KEY = 'edith.settings.v1';

// VITE_API_URL wins when set. Otherwise: dev server -> local backend; production
// build -> same origin (the backend serves the app in the single-container deploy).
const defaultApiUrl =
  import.meta.env.VITE_API_URL || (import.meta.env.DEV ? 'http://localhost:8000' : '');

const isTouch = typeof window !== 'undefined' && window.matchMedia?.('(pointer: coarse)').matches;

const defaults = {
  apiUrl: defaultApiUrl,
  accessToken: '',
  model: '',
  mode: 'earbud',
  language: navigator.language || 'en-US',
  voiceName: '',
  speechRate: 1.05,
  autoSpeak: true,
  useMemory: true,
  useDocuments: true,
  serverSpeech: false,
  talkMode: isTouch ? 'tap' : 'hold', // tap: tap once, speak, it sends when you pause
  keepAwake: false,
};

export function loadSettings() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? { ...defaults, ...JSON.parse(raw) } : { ...defaults };
  } catch {
    return { ...defaults };
  }
}

export function saveSettings(s) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
  } catch {
    /* storage unavailable (private mode) - settings stay in memory */
  }
}

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function createApi(getSettings) {
  async function request(path, { method = 'GET', body, form, timeoutMs = 45000, raw = false } = {}) {
    const { apiUrl, accessToken } = getSettings();
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    const headers = {};
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    let res;
    try {
      res = await fetch(apiUrl.replace(/\/$/, '') + path, {
        method,
        headers,
        body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
        signal: ctrl.signal,
      });
    } catch (e) {
      if (e.name === 'AbortError') throw new ApiError(0, 'timeout', 'The request timed out.');
      throw new ApiError(0, 'network', `Cannot reach the EDITH server${apiUrl ? ` at ${apiUrl}` : ''}. Check your internet connection.`);
    } finally {
      clearTimeout(timer);
    }
    if (!res.ok) {
      let code = 'http_error';
      let message = `Request failed (HTTP ${res.status})`;
      try {
        const data = await res.json();
        if (data?.error) ({ code, message } = data.error);
      } catch {
        /* non-JSON error */
      }
      throw new ApiError(res.status, code, message);
    }
    if (raw) return res;
    if (res.status === 204) return null;
    return res.json();
  }

  return {
    health: () => request('/health', { timeoutMs: 5000 }),
    chat: (payload) => request('/api/chat', { method: 'POST', body: payload }),
    listMemories: () => request('/api/memory'),
    addMemory: (content, category = 'general') =>
      request('/api/memory', { method: 'POST', body: { content, category } }),
    updateMemory: (id, content) => request(`/api/memory/${id}`, { method: 'PATCH', body: { content } }),
    deleteMemory: (id) => request(`/api/memory/${id}`, { method: 'DELETE' }),
    getMemorySettings: () => request('/api/memory/settings'),
    setMemoryEnabled: (enabled) =>
      request('/api/memory/settings', { method: 'PUT', body: { memory_enabled: enabled } }),
    listDocuments: () => request('/api/documents'),
    addDocument: (title, content) => request('/api/documents', { method: 'POST', body: { title, content } }),
    deleteDocument: (id) => request(`/api/documents/${id}`, { method: 'DELETE' }),
    briefing: (topic) => request('/api/meeting/briefing', { method: 'POST', body: { topic }, timeoutMs: 90000 }),
    summarize: (notes, consent) =>
      request('/api/meeting/summarize', {
        method: 'POST',
        body: { notes, consent_confirmed: consent },
        timeoutMs: 90000,
      }),
    listLeads: () => request('/api/leads'),
    saveLead: (lead) => request('/api/leads', { method: 'POST', body: lead }),
    deleteLead: (id) => request(`/api/leads/${id}`, { method: 'DELETE' }),
    exportLeads: async () => {
      const res = await request('/api/leads/export.csv', { raw: true });
      return res.blob();
    },
    transcribe: (blob, language) => {
      const form = new FormData();
      form.append('audio', blob, 'clip.webm');
      if (language) form.append('language', language);
      return request('/api/voice/transcribe', { method: 'POST', form });
    },
    speak: async (text) => {
      const res = await request('/api/voice/speak', { method: 'POST', body: { text }, raw: true });
      return res.blob();
    },
  };
}

// Optional Supabase email/password sign-in. Uses the PUBLIC anon key only.
export const supabaseAuthEnabled = Boolean(
  import.meta.env.VITE_SUPABASE_URL && import.meta.env.VITE_SUPABASE_ANON_KEY,
);

export async function supabaseSignIn(email, password) {
  const url = `${import.meta.env.VITE_SUPABASE_URL.replace(/\/$/, '')}/auth/v1/token?grant_type=password`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { apikey: import.meta.env.VITE_SUPABASE_ANON_KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error_description || data.msg || 'Sign-in failed');
  return data.access_token;
}
