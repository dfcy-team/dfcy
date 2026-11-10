import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
const live = process.argv[2], built = path.resolve('dist/assets');
const oldName = 'SyncExecutionRecords-CQKzcVFv.js';
const read = (root, file) => fs.readFileSync(path.join(root, file), 'utf8');
const files = fs.readdirSync(built), liveFiles = fs.readdirSync(live);
const newName = files.find(f => /^SyncExecutionRecords-.*\.js$/.test(f));
const old = read(live, oldName), fresh = read(built, newName);
const stem = s => s.replace(/-[A-Za-z0-9_-]{8}\.(js|css)$/, '.$1');
// Never collapse different app entrypoints: importing a second entry mounts the
// entire application again. Component hashes alone cannot establish compatibility.
const norm = s => s.replaceAll('index-C6T8h0h3.js', 'FOREIGN_APPLICATION_ENTRY')
  .replace(/(?:\.\/)?[A-Za-z0-9_.-]+-[A-Za-z0-9_-]{8}\.(?:js|css)/g, stem);
const refs = [...fresh.matchAll(/(?:from|import)"\.\/([^"]+)"/g)].map(m => m[1]);
const rootName = fs.readFileSync('dist/index.html', 'utf8').match(/src="\/assets\/([^"]+)"/)[1];
let patched = fresh;
const additions = [], dependencies = {};
for (const dep of refs) {
  const candidates = liveFiles.filter(f => stem(f) === stem(dep));
  const target = dep === rootName ? 'index-BCq0YIA9.js' : candidates.find(f => norm(read(live, f)) === norm(read(built, dep)));
  if (!target && stem(dep) === 'syncPresentation.js') {
    assert.ok(!/(?:from|import)"/.test(read(built, dep)), 'Only standalone presentation helper may be added');
    additions.push(dep);
    continue;
  }
  assert.ok(target, `No compatible live dependency: ${dep}`);
  dependencies[target] = crypto.createHash('sha256').update(read(live, target)).digest('hex');
  if (dep === rootName) assert.equal(read(live, target).match(/export\{([^}]+)\}/g)?.at(-1), read(built, dep).match(/export\{([^}]+)\}/g)?.at(-1), 'Root export mismatch');
  patched = patched.replaceAll('"./'+dep+'"', '"./'+target+'"');
}
const scope = s => [...s.matchAll(/__scopeId","(data-v-[a-f0-9]+)"/g)].at(-1)[1];
const beforeScope = scope(old), afterScope = scope(fresh);
const visited = new Set();
function checkClosure(file) {
  if (visited.has(file) || file === 'index-BCq0YIA9.js') return;
  visited.add(file);
  const code = read(live, file);
  assert.ok(!code.includes('mount("#app")'), `Unexpected application entry: ${file}`);
  dependencies[file] = crypto.createHash('sha256').update(code).digest('hex');
  for (const match of code.matchAll(/(?:from|import)"\.\/([^"]+)"/g)) checkClosure(match[1]);
}
for (const file of Object.keys(dependencies)) checkClosure(file);
const newCss = files.find(f => /^SyncExecutionRecords-.*\.css$/.test(f));
assert.ok(liveFiles.some(f => /^SyncExecutionRecords-.*\.css$/.test(f) && read(live, f) === read(built, newCss).replaceAll(afterScope, beforeScope)), 'Live CSS mismatch');
patched = patched.replaceAll(afterScope, beforeScope);
fs.mkdirSync('sync-evidence-hotfix', { recursive: true });
for (const file of additions) fs.copyFileSync(path.join(built, file), path.join('sync-evidence-hotfix', file));
fs.writeFileSync('sync-evidence-hotfix/'+oldName, patched);
const hash = s => crypto.createHash('sha256').update(s).digest('hex');
fs.writeFileSync('sync-evidence-hotfix/manifest.json', JSON.stringify({ file: oldName, before: hash(old), after: hash(patched), dependencies, additions: Object.fromEntries(additions.map(f => [f, hash(read(built, f))])) }, null, 2));
console.log('PASS: dependencies, exports and CSS checked; isolated sync page ready.');
