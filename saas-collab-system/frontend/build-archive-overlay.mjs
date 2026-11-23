import fs from 'node:fs';
import { parse, compileScript, compileStyle } from '@vue/compiler-sfc';
import { build } from 'esbuild';
const file='src/views/influencers/InfluencerResourceLibrary.vue';
const {descriptor}=parse(fs.readFileSync(file,'utf8'));
const scope='data-v-archive20261105';
let code=compileScript(descriptor,{id:scope,inlineTemplate:true}).content;
const components={
 'el-alert':['E','el-alert-DKAWOyX9.js'],'el-form':['a','el-form-item-MH1UTd0a.js'],'el-form-item':['E','el-form-item-MH1UTd0a.js'],
 'el-input':['E','index-BsThDjGK.js'],'el-button':['E','el-button-CX8h5y-T.js'],'el-tag':['E','index-B52pQPXR.js'],
 'el-select':['E','el-select-BHi3bIgz.js'],'el-option':['a','el-select-BHi3bIgz.js'],'el-card':['E','el-card-m9gVS1R0.js'],
 'el-table':['E','el-table-column-BjWIMDS0.js'],'el-table-column':['a','el-table-column-BjWIMDS0.js'],'el-checkbox':['b','el-table-column-BjWIMDS0.js'],
 'el-descriptions':['E','el-descriptions-BQeA4fcf.js'],'el-descriptions-item':['a','el-descriptions-BQeA4fcf.js'],
 'el-dialog':['E','el-dialog-D7s-DH60.js'],'el-divider':['E','el-divider-BnW9K3hz.js'],'el-drawer':['E','el-drawer-BFpkW4lU.js'],
 'el-input-number':['E','el-input-number-CGWtf0LH.js'],'el-pagination':['E','el-pagination-B2aUnoHF.js'],
 'el-switch':['E','el-switch-Clpr3Vxp.js'],'el-timeline':['E','el-timeline-item-DhN8a0V9.js'],'el-timeline-item':['a','el-timeline-item-DhN8a0V9.js'],
};
let imports='';
for(const [name,[exp,module]] of Object.entries(components)){
 const alias='live_'+name.replaceAll('-','_');imports+=`import {${exp} as ${alias}} from './${module}';\n`;
 code=code.replaceAll(`_resolveComponent("${name}")`,alias);
}
imports+='import {v as liveLoading} from "./directive-O5jnGF8G.js";\n';
code=code.replaceAll('_resolveDirective("loading")','liveLoading');
const vue={reactive:'m',onMounted:'j',computed:'p',ref:'r',openBlock:'D',createElementBlock:'L',createElementVNode:'O',createVNode:'F',withCtx:'E',createBlock:'B',createTextVNode:'$',toDisplayString:'Q',unref:'u',Fragment:'X',renderList:'a3',createCommentVNode:'a0',withDirectives:'V',withModifiers:'a2',withKeys:'a1',resolveComponent:'aa',resolveDirective:'aa',normalizeClass:'C'};
code=code.replace(/import\s*\{([^}]+)\}\s*from\s*['"]vue['"]/g,(_,bindings)=>'import {'+bindings.split(',').map(b=>{
 const [name,alias]=b.trim().split(/\s+as\s+/);if(!vue[name])throw Error('Unknown Vue export '+name);return vue[name]+' as '+(alias||name);
}).join(',')+'} from "./vue-CtE0VcsI.js"');
code=code.replace("import { ElMessage, ElMessageBox } from 'element-plus'",'import {E as ElMessage} from "./index-aOhVajLL.js";import {E as ElMessageBox} from "./index-DmVunOLb.js"')
 .replace("import { collectionRows, collectionTotal } from '../../utils/businessResponse'",'import {c as collectionRows,a as collectionTotal} from "./businessResponse-CsbcR7uO.js"')
 .replace("import { useAuthStore } from '../../stores/auth'",'import {x as useAuthStore,E as liveRequest} from "./index-CFS-lxl7.js"');
// Bind by the verified live module exports, not by import position.
const api={INFLUENCER_CONTACT_CHANNEL_LABELS:'I',INFLUENCER_COOPERATION_STATUS_LABELS:'b',fetchInfluencer:'c',fetchInfluencerForm:'l',fetchRelatedInfluencerArchives:'g',createRelatedInfluencerArchive:'j',fetchInfluencerBlacklistHistory:'e',fetchInfluencerContacts:'d',fetchInfluencers:'f',formatInfluencerError:'k',saveInfluencerForm:'s',fetchTikTokCreatorSnapshots:'h',queryTikTokCreator:'q',updateInfluencerBlacklist:'u',updateInfluencerStatus:'i'};
code=code.replace(/import\s*\{([^}]+)\}\s*from\s*['"]\.\.\/\.\.\/api\/influencers['"]/g,()=>{
 return 'import {'+Object.entries(api).map(([n,e])=>e+' as '+n).join(',')+',a as originalPlatforms} from "./influencers-DRFnSV9F.js";\n'+
 'const INFLUENCER_PLATFORM_LABELS=Object.freeze({...originalPlatforms,shopee:"Shopee"});\n'+
 'const archiveMutation=(id,version,method)=>liveRequest({method,url:`/api/internal/influencers/${encodeURIComponent(id)}/archive-deletion/`,headers:{"If-Match":`"${String(version).replace(/^"|"$/g,"")}"`}});\n'+
 'const deleteInfluencerArchive=(id,v)=>archiveMutation(id,v,"delete");const restoreInfluencerArchive=(id,v)=>archiveMutation(id,v,"post");';
});
if(code.includes('_resolveComponent("')||code.includes('_resolveDirective("'))throw Error('Unmapped component/directive');
code=code.replace('export default ','const component = ');
const css=descriptor.styles.map(s=>compileStyle({source:s.content,filename:file,id:scope,scoped:s.scoped}).code).join('\n');
code+=`\ncomponent.__scopeId='${scope}'; if(!document.getElementById('archive-overlay-style')){const s=document.createElement('style');s.id='archive-overlay-style';s.textContent=${JSON.stringify(css)};document.head.appendChild(s);}\n`;
code+='export default {setup(){return()=>live_createElementVNode("section",{class:"influencer-workspace"},[live_createElementVNode("header",{class:"workspace-heading"},[live_createElementVNode("div",null,[live_createElementVNode("span",null,"CREATOR OPERATIONS"),live_createElementVNode("h1",null,"品牌达人等级资源库"),live_createElementVNode("p",null,"集中维护达人平台身份、内容赛道、粉丝规模与合作状态。")])]),live_createVNode(component)])}};';
imports+='import {O as live_createElementVNode,F as live_createVNode} from "./vue-CtE0VcsI.js";\n';
const external=[...new Set(Object.values(components).map(([,m])=>'./'+m)), './directive-O5jnGF8G.js','./vue-CtE0VcsI.js','./index-aOhVajLL.js','./index-DmVunOLb.js','./businessResponse-CsbcR7uO.js','./index-CFS-lxl7.js','./influencers-DRFnSV9F.js'];
await build({stdin:{contents:imports+code,resolveDir:process.cwd()+'/src/views/influencers',loader:'js'},bundle:true,format:'esm',external,minify:true,outfile:process.argv[2]||'archive-overlay/InfluencerList.js'});
