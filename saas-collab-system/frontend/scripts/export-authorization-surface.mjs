import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import crypto from 'node:crypto';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const CHECKS = String.raw`(?:hasPermission|hasActionPermission|hasFieldPermission|hasAllDataScopeFor|usePermissionAccess)`;

// Extract only literals supplied to permission-check APIs or permission config
// properties. Arbitrary dotted strings (such as API tracking/mock keys) are not
// authorization references.
export function extractPermissionReferences(source) {
  const found = new Set();
  const literal = String.raw`['"]([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)['"]`;
  const addLiterals = (text) => {
    for (const match of text.matchAll(new RegExp(literal, 'g'))) found.add(match[1]);
  };

  for (const match of source.matchAll(new RegExp(String.raw`${CHECKS}\s*\(([^)]*)\)`, 'g'))) addLiterals(match[1]);
  for (const match of source.matchAll(/\b(?:[a-zA-Z]*Permission|permission|permissions|allPermissions|menuPermissions)\s*:\s*(\[[^\]]*\]|['"][^'"]*['"])/g)) addLiterals(match[1]);
  // Vue templates commonly pass this as a static attribute.
  for (const match of source.matchAll(/\bpermission\s*=\s*(['"])([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)\1/g)) found.add(match[2]);
  return [...found].sort();
}

export function partitionPermissionReferences(references, knownCodes) {
  const known = new Set(knownCodes);
  return {
    accepted: references.filter(row => known.has(row.permission_code)),
    unknown: references.filter(row => !known.has(row.permission_code))
  };
}

async function walk(dir) {
  const files = [];
  for (const entry of await fs.readdir(dir, { withFileTypes: true })) {
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...await walk(file));
    else if (/\.(vue|js)$/.test(file)) files.push(file);
  }
  return files;
}

export async function run({ check = process.argv.includes('--check') } = {}) {
  const manifest = JSON.parse(await fs.readFile(path.join(root, '../backend/apps/permissions/permission_manifest.json'), 'utf8'));
  const references = [], unknown = [];
  for (const file of (await walk(path.join(root, 'src'))).sort()) {
    if (path.relative(root, file).replaceAll('\\', '/').startsWith('src/mock/')) continue;
    const source = await fs.readFile(file, 'utf8');
    for (const code of extractPermissionReferences(source)) {
      const row = { file: path.relative(root, file).replaceAll('\\', '/'), permission_code: code };
      references.push(row);
    }
  }
  const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
  references.sort((a, b) => compare(a.file, b.file) || compare(a.permission_code, b.permission_code));
  const partitioned = partitionPermissionReferences(references, manifest.permissions.map(row => row.code));
  references.splice(0, references.length, ...partitioned.accepted);
  unknown.push(...partitioned.unknown);
  if (unknown.length) {
    console.error(JSON.stringify({ error: '未登记前端权限引用', count: unknown.length, samples: unknown.slice(0, 20) }));
    process.exitCode = 1;
    return;
  }
  const core = { schema_version: 1, catalog_hash: manifest.catalog_hash, references };
  const payload = { ...core, surface_hash: crypto.createHash('sha256').update(JSON.stringify(core)).digest('hex') };
  const text = JSON.stringify(payload, null, 2) + '\n';
  const target = path.join(root, '../backend/apps/permissions/frontend_permission_surface.json');
  if (check) {
    if ((await fs.readFile(target, 'utf8')).replaceAll('\r\n', '\n') !== text) throw new Error('前端权限清单漂移，请运行 permissions:surface:export');
    console.log(`前端权限清单一致：${references.length} 项引用`);
  } else {
    await fs.writeFile(target, text);
    console.log(`已登记前端权限清单：${references.length} 项引用`);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await run();
