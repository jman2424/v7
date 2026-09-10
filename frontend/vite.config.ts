import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

const backend = process.env.V7_BACKEND_ORIGIN ?? 'http://127.0.0.1:5055';

export default defineConfig({
  plugins: [sveltekit()],
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
