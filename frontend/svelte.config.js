import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: {
    // Local-first SPA: every route is client-rendered, API lives on FastAPI.
    adapter: adapter({ fallback: 'index.html' })
  }
};

export default config;
