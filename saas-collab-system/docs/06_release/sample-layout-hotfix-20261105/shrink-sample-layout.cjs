const fs = require('fs');
const crypto = require('crypto');
let source = fs.readFileSync(__dirname + '/sample-layout-public-verify.js', 'utf8');
if (crypto.createHash('sha256').update(source).digest('hex') !== '2142b3dc3564a7ebd8797a8a6d7d67e171f9d9abb67f8db2985e678e3bef0e81') throw Error('Baseline changed');
const css = `@media(min-width:901px){
.sample-page .toolbar{grid-template-columns:repeat(12,80px);justify-content:start;max-width:100%}
.sample-page .toolbar>.el-input{grid-column:span 4;width:320px!important;max-width:100%}
.sample-page .toolbar>.el-select{grid-column:span 2;width:160px!important;max-width:100%}
.sample-page .toolbar>.sort-select{width:170px!important}
.sample-page .toolbar>.el-checkbox{grid-column:span 2}
.sample-page .toolbar>label:not(.el-checkbox){grid-column:span 3;width:230px}
.sample-page .toolbar>label input{width:142px!important;flex:0 1 142px}
.sample-page .toolbar>.el-button{width:72px;justify-self:start}
.sample-page .toolbar>.el-button:last-child{width:100px}
}
@media(min-width:901px) and (max-width:1400px){.sample-page .toolbar{grid-template-columns:repeat(12,minmax(0,1fr))}.sample-page .toolbar>label:not(.el-checkbox){width:auto}}
`;
source += '\n{const style=document.createElement("style");style.id="sample-layout-compact-20261105";style.textContent='+JSON.stringify(css)+';document.head.appendChild(style);}\n';
fs.writeFileSync(__dirname + '/sample-layout-compact.mjs', source);
console.log(crypto.createHash('sha256').update(source).digest('hex'));
