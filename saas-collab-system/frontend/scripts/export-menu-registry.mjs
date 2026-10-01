import { readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { menuItems, menuPermissionRegistry, routeCapabilities } from '../src/router/menu.js';

const registeredPaths = new Set(menuPermissionRegistry.map((row) => row.metadata.path));
function requireStableCodes(items) {
  for (const item of items || []) {
    if (registeredPaths.has(item.path) && !item.menuPermissions?.length) throw new Error(`菜单必须声明稳定 menuPermissions 编码：${item.path}`);
    requireStableCodes(item.children);
  }
}
requireStableCodes(menuItems);

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
  // Git may check JSON snapshots out with CRLF on Windows while the generated
  // payload always uses LF. Compare normalized text so the release gate
  // detects semantic/content drift instead of platform line endings.
  if (existing.replace(/\r\n/g, '\n') !== serialized) {
    console.error(`菜单权限快照已漂移，请运行 npm run permissions:export：${snapshotPath}`);
    process.exitCode = 1;
  } else {
    console.log(`菜单权限快照一致：${menuPermissionRegistry.length} 项菜单，${routeCapabilities.length} 项路由`);
  }
} else {
  await writeFile(snapshotPath, serialized, 'utf8');
  console.log(`已更新菜单权限快照：${menuPermissionRegistry.length} 项菜单，${routeCapabilities.length} 项路由`);
}
