import fs from 'node:fs';
import { parse, compileScript, compileStyle } from '@vue/compiler-sfc';
import { build } from 'esbuild';
const file = 'src/components/TikTokAdsDailySpendOverview.vue';
const { descriptor } = parse(fs.readFileSync(file, 'utf8'));
const scope = 'data-v-gmvonly20261104';
let code = compileScript(descriptor, { id: scope, inlineTemplate: true }).content;
const components = {
  'el-form': ['a', 'el-form-item-CTmf19ep.js'], 'el-form-item': ['E', 'el-form-item-CTmf19ep.js'],
  'el-select': ['E', 'el-select-BNiHe5Rw.js'], 'el-option': ['a', 'el-select-BNiHe5Rw.js'],
  'el-button': ['E', 'el-button-v0AG5dET.js'], 'el-alert': ['E', 'el-alert-B9jHW0Rq.js'],
  'el-tag': ['E', 'index-B8z8Asp6.js'], 'el-date-picker': ['E', 'el-date-picker-B2M7aJv1.js'],
  'el-empty': ['E', 'el-empty-D0j968Gz.js'], 'el-table': ['E', 'el-table-column-CKFJpEP1.js'],
  'el-table-column': ['a', 'el-table-column-CKFJpEP1.js'],
};
let imports = '';
for (const [name, [exp, module]] of Object.entries(components)) {
  const alias = 'live_' + name.replaceAll('-', '_');
  imports += `import { ${exp} as ${alias} } from './${module}';\n`;
  code = code.replaceAll(`_resolveComponent("${name}")`, alias);
}
const vue = {ref:'r',watch:'c',onBeforeUnmount:'T',computed:'p',openBlock:'D',createBlock:'B',withCtx:'E',createVNode:'F',createElementBlock:'L',renderList:'a3',Fragment:'X',createTextVNode:'$',withModifiers:'a2',createCommentVNode:'a0',createElementVNode:'O',toDisplayString:'Q',unref:'u',resolveComponent:'aa'};
code = code.replace(/import\s*\{([^}]+)\}\s*from\s*['"]vue['"]/g, (_, bindings) => {
  return 'import {' + bindings.split(',').map(b => {
    const [name, alias] = b.trim().split(/\s+as\s+/);
    if (!vue[name]) throw new Error('Unmapped Vue helper ' + name);
    return vue[name] + ' as ' + (alias || name);
  }).join(',') + '} from "./vue-CtE0VcsI.js"';
});
code = code.replace("import AppPage from './AppPage.vue'", "import { A as AppPage } from './AppPage-ZJASEWaB.js'")
  .replace("import { fetchTikTokDailySpend } from '../api/advertising'", "import { f as fetchTikTokDailySpend } from './ShopeeAdvertisingReport-BqjbJmoY.js'")
  .replace('export default ', 'const component = ');
code += `\ncomponent.__scopeId = '${scope}'; export default component;\n`;
const css = descriptor.styles.map(s => compileStyle({ source:s.content, filename:file, id:scope, scoped:s.scoped }).code).join('\n');
code += `\nif (!document.getElementById('gmv-only-style')) { const s=document.createElement('style'); s.id='gmv-only-style'; s.textContent=${JSON.stringify(css)}; document.head.appendChild(s); }\n`;
fs.mkdirSync('gmv-overlay', {recursive:true});
const external = [...new Set(Object.values(components).map(([, module]) => './' + module)), './vue-CtE0VcsI.js', './AppPage-ZJASEWaB.js', './ShopeeAdvertisingReport-BqjbJmoY.js'];
await build({stdin:{contents:imports+code,resolveDir:process.cwd()+'/src/components',loader:'js'},bundle:true,format:'esm',outfile:'gmv-overlay/TikTokGmvOnly-20261104.js',external,minify:true});
