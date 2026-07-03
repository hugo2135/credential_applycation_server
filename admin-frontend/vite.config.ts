import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  plugins: [
    vue(),
    vueDevTools(),
    AutoImport({
      resolvers: [ElementPlusResolver()],
    }),
    Components({
      resolvers: [ElementPlusResolver()],
    }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    proxy: {
      '/admin': {
        target: 'http://localhost:8000',
        bypass(req) {
          // Page navigations (browser fetch with text/html) must be served locally
          // so Vue Router handles the route. Only proxy actual API calls.
          if (req.headers.accept?.includes('text/html')) return '/index.html'
        },
      },
      '/auth': 'http://localhost:8000',
      '/api': 'http://localhost:8000',
    },
  },
})
