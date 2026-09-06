import { readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { menuPermissionRegistry, routeCapabilities } from '../src/router/menu.js';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const snapshotPath = resolve(scriptDir, '../../backend/apps/permissions/menu_registry.json');
const payload = {
  version: 1,
  source: 'frontend/src/router/menu.js',
  menus: menuPermissionRegistry,
  routes: routeCapabilities,
};
const serialized = `${JSON.stringify(payload, null, 2)}\n`;
const checkOnly = process.argv.includes('--check');

let existing = '';
try {
  existing = await readFile(snapshotPath, 'utf8');
} catch (error) {
  if (error.code !== 'ENOENT') throw error;
}

if (checkOnly) {
  if (existing !== serialized) {
    console.error(`菜单权限快照已漂移，请运行 npm run permissions:export：${snapshotPath}`);
    process.exitCode = 1;
  } else {
    console.log(`菜单权限快照一致：${menuPermissionRegistry.length} 项菜单，${routeCapabilities.length} 项路由`);
  }
} else {
  await writeFile(snapshotPath, serialized, 'utf8');
  console.log(`已更新菜单权限快照：${menuPermissionRegistry.length} 项菜单，${routeCapabilities.length} 项路由`);
}
