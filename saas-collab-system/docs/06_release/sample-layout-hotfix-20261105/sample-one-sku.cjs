const fs = require('fs');
const crypto = require('crypto');
let source = fs.readFileSync(__dirname + '/sample-layout-compact-public.js', 'utf8');
if (crypto.createHash('sha256').update(source).digest('hex') !== 'd01e3c55f85ade345179d14ac0ee647a5483c413d69865c37629b0c80e52510a') throw Error('Baseline changed');
for (const [before, after] of [
  ['a.__sampleSkuExpanded?a.items:a.items.slice(0,2)', 'a.__sampleSkuExpanded?a.items:a.items.slice(0,1)'],
  ['a.items?.length>2?u(m', 'a.items?.length>1?u(m'],
  ['${a.items.length-2} 项 SKU', '${a.items.length-1} 项 SKU'],
]) {
  if (source.split(before).length !== 2) throw Error('Nonunique patch anchor');
  source = source.replace(before, after);
}
fs.writeFileSync(__dirname + '/sample-one-sku.mjs', source);
console.log(crypto.createHash('sha256').update(source).digest('hex'));
