import { defineConfig } from 'vite';
import { readFileSync } from 'node:fs';
import { assertProductionMode } from './scripts/production-mode-guard.mjs';
import vue from '@vitejs/plugin-vue';
import AutoImport from 'unplugin-auto-import/vite';
import Components from 'unplugin-vue-components/vite';
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers';

const elementPlusResolver = ElementPlusResolver({
  importStyle: process.env.VITEST ? false : 'css'
});

export default defineConfig({
  plugins: [
    {
      name: 'production-mode-and-release-notes',
      configResolved(config) { assertProductionMode(config.command, config.env); },
      generateBundle() {
        this.emitFile({ type: 'asset', fileName: 'release-notes.json', source: readFileSync(new URL('./src/data/releaseNotes.json', import.meta.url)) });
      }
    },
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
