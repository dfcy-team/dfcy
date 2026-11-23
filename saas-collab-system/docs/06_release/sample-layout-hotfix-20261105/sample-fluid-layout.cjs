const fs = require('fs');
const crypto = require('crypto');
let source = fs.readFileSync(__dirname + '/sample-one-sku-public.js', 'utf8');
if (crypto.createHash('sha256').update(source).digest('hex') !== '93c070a5ed5e46432212cb938ee8bd72bcb329066d6d658467a139676957bef7') throw Error('Baseline changed');
const css = `.sample-page .toolbar{display:flex!important;flex-wrap:wrap!important;align-items:center;justify-content:flex-start;gap:10px;overflow:visible!important}
.sample-page .toolbar>.el-input{flex:0 1 320px!important;width:320px!important;min-width:0!important;max-width:100%}
.sample-page .toolbar>.el-select{flex:0 1 160px!important;width:160px!important;min-width:0!important;max-width:100%}
.sample-page .toolbar>.sort-select{flex-basis:210px!important;width:210px!important}
.sample-page .toolbar>.el-checkbox{flex:0 0 auto;margin:0}
.sample-page .toolbar>label:not(.el-checkbox){flex:0 1 230px;max-width:100%;width:230px;min-width:0}
.sample-page .toolbar>label input{width:142px!important;flex:0 1 142px;min-width:0}
.sample-page .toolbar>.el-button{flex:0 0 auto;width:auto!important;margin:0}
`;
source += '\n{const style=document.createElement("style");style.id="sample-layout-fluid-20261105";style.textContent='+JSON.stringify(css)+';document.head.appendChild(style);}\n';
fs.writeFileSync(__dirname + '/sample-fluid-layout.mjs', source);
console.log(crypto.createHash('sha256').update(source).digest('hex'));
