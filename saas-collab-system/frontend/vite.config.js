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
  test: {
    environment: 'jsdom'
  }
});
