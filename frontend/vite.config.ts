import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

const backend = process.env.V7_BACKEND_ORIGIN ?? 'http://127.0.0.1:5055';
const base = (process.env.V7_CONSOLE_BASE_PATH || '') as '' | `/${string}`;

export default defineConfig({
  plugins: [sveltekit({ adapter: adapter(), paths: { base } })],
  server: {
    proxy: {
      '/api': {
        target: backend,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      }
    }
  }
});
