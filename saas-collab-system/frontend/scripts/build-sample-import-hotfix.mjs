import { build } from 'vite';
import vue from '@vitejs/plugin-vue';
import Components from 'unplugin-vue-components/vite';
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers';
import { fileURLToPath } from 'node:url';

await build({
  configFile: false,
  root: fileURLToPath(new URL('../', import.meta.url)),
  define: { 'import.meta.env.VITE_USE_MOCK': JSON.stringify('false'), 'import.meta.env.VITE_API_BASE_URL': JSON.stringify('') },
  plugins: [vue(), Components({ resolvers: [ElementPlusResolver()], dts: false })],
  build: {
    outDir: 'sample-import-hotfix',
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      input: fileURLToPath(new URL('./sample-import-hotfix-entry.js', import.meta.url)),
      output: { entryFileNames: 'sample-import-[hash].js', assetFileNames: 'sample-import-[hash][extname]' }
    }
  }
});
