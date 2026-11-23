const fs = require('fs');
const crypto = require('crypto');
let source = fs.readFileSync(__dirname + '/sample-fluid-public.js', 'utf8');
if (crypto.createHash('sha256').update(source).digest('hex') !== '2575e6a1b7a765939e6e139a0d39edad7e081951032df48c76a8b88ca42f5002') throw Error('Baseline changed');
for (const label of ['创建开始日期', '创建结束日期']) {
  const before = 'h("' + label + '"),t("input",{type:"date",';
  if (source.split(before).length !== 2) throw Error('Nonunique anchor');
  source = source.replace(before, 't("input",{title:"' + label + '（北京时间）",type:"date",');
}
source += '\n{const style=document.createElement("style");style.textContent=".sample-page .toolbar>label:not(.el-checkbox){flex:0 1 142px;width:142px;gap:0!important}";document.head.appendChild(style);}\n';
fs.writeFileSync(__dirname + '/sample-date-labels.mjs', source);
console.log(crypto.createHash('sha256').update(source).digest('hex'));
