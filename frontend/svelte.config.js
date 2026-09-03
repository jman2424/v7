import adapter from '@sveltejs/adapter-static';

const base = process.env.V7_CONSOLE_BASE_PATH || '';

/** @type {import('@sveltejs/kit').Config} */
const config = {
  kit: {
    adapter: adapter(),
    paths: { base }
  }
};

export default config;
