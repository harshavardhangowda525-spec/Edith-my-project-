import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The backend URL is configured at runtime via VITE_API_URL (see .env.example)
// and can be overridden by the user in Settings.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, host: '127.0.0.1' },
  preview: { port: 4173 },
});
