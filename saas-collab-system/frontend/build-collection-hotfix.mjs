import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
const live=process.argv[2];
const built=path.resolve('dist/assets');
const out=path.resolve('collection-hotfix');
const read=(root,file)=>fs.readFileSync(path.join(root,file),'utf8');
const oldFile='IntegrationCapabilityMatrix-F6iz7urt.js';
const newFile=fs.readdirSync(built).find(x=>/^IntegrationCapabilityMatrix-.*\.js$/.test(x));
const refs=s=>[...s.matchAll(/(?:from|import)"\.\/([^"]+)"/g)].map(m=>m[1]);
const old=read(live,oldFile), fresh=read(built,newFile);
const a=refs(old),b=refs(fresh);
assert.equal(a.length,b.length,'Dependency count changed');
const stem=s=>s.replace(/-[A-Za-z0-9_-]{8}\.(js|css)$/,'.$1');
const norm=s=>s.replace(/(?:\.\/)?[A-Za-z0-9_.-]+-[A-Za-z0-9_-]{8}\.(?:js|css)/g, m=>stem(m));
for(let i=0;i<a.length;i++){
 assert.equal(stem(a[i]),stem(b[i]),'Dependency order changed');
 if(a[i]==='index-BCq0YIA9.js') {
   // The router export used by this page must remain the same live binding.
   const liveRoot=read(live,a[i]),newRoot=read(built,b[i]);
   assert.equal(liveRoot.match(/export\{([^}]+)\}/g)?.at(-1),newRoot.match(/export\{([^}]+)\}/g)?.at(-1),'Root export contract changed');
 } else assert.equal(norm(read(live,a[i])),norm(read(built,b[i])),`Dependency implementation differs: ${a[i]}`);
}
let patched=fresh;
for(let i=0;i<a.length;i++)patched=patched.replaceAll('"./'+b[i]+'"','"./'+a[i]+'"');
fs.mkdirSync(out,{recursive:true});
fs.writeFileSync(path.join(out,oldFile),patched);
fs.writeFileSync(path.join(out,'manifest.json'),JSON.stringify({file:oldFile,
 before:crypto.createHash('sha256').update(old).digest('hex'),
 after:crypto.createHash('sha256').update(patched).digest('hex'),dependencies:a},null,2));
console.log('Validated '+a.length+' dependencies; scoped hotfix ready.');
