const fs = require('fs');
const crypto = require('crypto');
let source = fs.readFileSync(__dirname + '/sample-live-20261105.js', 'utf8');
console.log('before', crypto.createHash('sha256').update(source).digest('hex'));
function replaceOnce(before, after) {
  if (source.split(before).length !== 2) throw new Error('Patch anchor not unique: ' + before);
  source = source.replace(before, after);
}
replaceOnce('F(a.items,d=>', 'F(a.__sampleSkuExpanded?a.items:a.items.slice(0,2),d=>');
replaceOnce('p(b(a.sku_quantity)),1))]}),_:1})', 'p(b(a.sku_quantity)),1)),a.items?.length>2?u(m,{link:true,type:"primary","aria-expanded":!!a.__sampleSkuExpanded,onClick:event=>{event.stopPropagation();a.__sampleSkuExpanded=!a.__sampleSkuExpanded}},{default:s(()=>[h(a.__sampleSkuExpanded?"收起":`+${a.items.length-2} 项 SKU`)]),_:2},1032,["aria-expanded","onClick"]):D("",!0)]}),_:1})');
const css = `.sample-page .toolbar{display:grid!important;grid-template-columns:repeat(12,minmax(0,1fr));gap:12px 10px;overflow:visible!important;align-items:center}
.sample-page .toolbar>.el-input{grid-column:span 4;min-width:0!important;width:100%!important}
.sample-page .toolbar>.el-select{grid-column:span 2;min-width:0!important;width:100%!important}
.sample-page .toolbar>.el-checkbox{grid-column:span 2;margin:0}
.sample-page .toolbar>label:not(.el-checkbox){grid-column:span 3;min-width:0}
.sample-page .toolbar>label input{min-width:0;width:100%!important;flex:1}
.sample-page .toolbar>.el-button{grid-column:span 1;min-width:0;margin:0}
.sample-page .toolbar>.el-button:last-child{grid-column:span 2}
@media(max-width:900px){.sample-page .toolbar{grid-template-columns:repeat(2,minmax(0,1fr))}.sample-page .toolbar>*{grid-column:span 1!important}.sample-page .toolbar>.el-input,.sample-page .toolbar>label:not(.el-checkbox){grid-column:span 2!important}}
`;
source += '\nif(!document.getElementById("sample-layout-20261105")){const style=document.createElement("style");style.id="sample-layout-20261105";style.textContent='+JSON.stringify(css)+';document.head.appendChild(style);}\n';
fs.writeFileSync(__dirname + '/sample-layout-patched.mjs', source);
console.log('after', crypto.createHash('sha256').update(source).digest('hex'));
