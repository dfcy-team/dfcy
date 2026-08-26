import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import AutoImport from 'unplugin-auto-import/vite';
import Components from 'unplugin-vue-components/vite';
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers';

const elementPlusResolver = ElementPlusResolver({
  importStyle: process.env.VITEST ? false : 'css'
});

export default defineConfig({
  plugins: [
    vue(),
    AutoImport({ resolvers: [elementPlusResolver], dts: false }),
    Components({ resolvers: [elementPlusResolver], dts: false })
  ],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          vue: ['vue', 'vue-router', 'pinia'],
          axios: ['axios']
        }
      }
    }
  },
  server: {
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_API_PROXY_TARGET || 'http://127.0.0.1:8001',
        changeOrigin: true
      }
    }
  },
  test: {
    environment: 'jsdom'
  }
});
