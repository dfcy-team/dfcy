import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
const live = process.argv[2], built = 'dist/assets', out = 'ads-capability-hotfix';
const read = (root, name) => fs.readFileSync(path.join(root, name), 'utf8');
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
const file = 'IntegrationCapabilityMatrix-F6iz7urt.js';
const freshFile = fs.readdirSync(built).find(n => /^IntegrationCapabilityMatrix-.*\.js$/.test(n));
const old = read(live, file), fresh = read(built, freshFile);
const refs = s => [...s.matchAll(/(?:from|import)"\.\/([^"]+)"/g)].map(m => m[1]);
const stem = s => s.replace(/-[A-Za-z0-9_-]{8}\.(js|css)$/, '.$1');
const norm = s => s.replace(/(?:\.\/)?[A-Za-z0-9_.-]+-[A-Za-z0-9_-]{8}\.(?:js|css)/g, stem);
const a = refs(old), b = refs(fresh), dependencies = {}, additions = {};
assert.equal(a.length, b.length);
let result = fresh;
fs.mkdirSync(out, { recursive: true });
for (let i = 0; i < a.length; i++) {
  assert.equal(stem(a[i]), stem(b[i]));
  if (stem(b[i]) === 'syncPresentation.js') {
    assert.equal(refs(read(built, b[i])).length, 0);
    fs.copyFileSync(path.join(built,b[i]), path.join(out,b[i]));
    additions[b[i]] = hash(read(built,b[i]));
    continue;
  }
  if (a[i] === 'index-BCq0YIA9.js') {
    assert.equal(read(live,a[i]).match(/export\{([^}]+)\}/g)?.at(-1),read(built,b[i]).match(/export\{([^}]+)\}/g)?.at(-1));
  } else assert.equal(norm(read(live,a[i])),norm(read(built,b[i])),a[i]);
  result = result.replaceAll('"./'+b[i]+'"','"./'+a[i]+'"');
  dependencies[a[i]] = hash(read(live,a[i]));
}
const scopes = s => [...s.matchAll(/__scopeId","(data-v-[a-f0-9]+)"/g)].map(m => m[1]);
const oldScopes = scopes(old), newScopes = scopes(fresh);
assert.equal(oldScopes.length,newScopes.length);
let css = read(built,fs.readdirSync(built).find(n => /^IntegrationCapabilityMatrix-.*\.css$/.test(n)));
newScopes.forEach((s,i) => { result=result.replaceAll(s,oldScopes[i]); css=css.replaceAll(s,oldScopes[i]); });
assert.ok(fs.readdirSync(live).some(n => /^IntegrationCapabilityMatrix-.*\.css$/.test(n) && read(live,n) === css),'Styles differ');
const name = 'IntegrationCapabilityMatrix-fix-'+hash(result).slice(0,12)+'.js';
fs.writeFileSync(path.join(out,name),result);
fs.writeFileSync(path.join(out,'manifest.json'),JSON.stringify({file,name,before:hash(old),after:hash(result),dependencies,additions},null,2));
console.log('PASS: dependency contracts and all component styles; '+name);
