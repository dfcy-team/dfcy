import { menuItems as defaultMenuItems } from '../router/menu';
import { adminModuleLabel } from './adminDisplayLabels';
import { buildMenuPermissionRegistry } from '../router/menuRegistry';

const PREFIXES = new Set(['menu', 'action', 'field']);

export function permissionModuleFromCode(code) {
  const parts = String(code || '').split('.').filter(Boolean);
  if (PREFIXES.has(parts[0])) return parts[1] || parts[0];
  return parts[0] || '';
}

function addCodeModules(target, codes = []) {
  for (const code of codes || []) {
    const module = permissionModuleFromCode(code);
    if (module) target.set(module, (target.get(module) || 0) + 1);
  }
}

function collectMenuModules(item, target = new Map()) {
  addCodeModules(target, item?.permissions);
  addCodeModules(target, item?.menuPermissions);
  addCodeModules(target, item?.allPermissions);
  for (const child of item?.children || []) collectMenuModules(child, target);
  return target;
}

function moduleNode(module) {
  return { key: `module:${module}`, type: 'module', module, label: adminModuleLabel(module), children: [] };
}

/** Build the administration permission tree from the sidebar contract. */
export function buildPermissionTree({ menuItems = defaultMenuItems, modules = [], permissions = [] } = {}) {
  const moduleList = [...new Set([
    ...modules,
    ...permissions.map((permission) => permission?.module).filter(Boolean),
  ])];
  const assigned = new Set();
  const tree = [];
  const menuScores = (menuItems || []).map((item) => collectMenuModules(item));
  const preferredMenuIndex = new Map();
  for (const module of moduleList) {
    let bestIndex = -1;
    let bestScore = 0;
    menuScores.forEach((scores, index) => {
      const score = scores.get(module) || 0;
      if (score > bestScore) { bestIndex = index; bestScore = score; }
    });
    if (bestIndex >= 0) preferredMenuIndex.set(module, bestIndex);
  }
  for (const [index, item] of (menuItems || []).entries()) {
    const children = moduleList
      .filter((module) => preferredMenuIndex.get(module) === index)
      .map((module) => { assigned.add(module); return moduleNode(module); });
    if (!children.length) continue;
    tree.push({ key: `menu:${index}:${item.label || index}`, type: 'menu', label: item.label || '未命名菜单', children });
  }
  const unassigned = moduleList.filter((module) => !assigned.has(module));
  if (unassigned.length) {
    tree.push({ key: 'menu:other', type: 'menu', label: '其他模块', children: unassigned.map(moduleNode) });
  }
  return tree;
}

/**
 * Build the advanced role editor hierarchy from the release-time menu
 * registry.  Registry parent metadata is authoritative here: action modules
 * can be reused by several top-level navigation areas, so grouping by module
 * would move valid pages under the wrong first-level menu.
 */
export function buildRegisteredMenuTree({ menuItems = defaultMenuItems } = {}) {
  const groups = new Map();
  for (const definition of buildMenuPermissionRegistry(menuItems || [])) {
    const ancestors = String(definition.metadata?.parent || '')
      .split('/')
      .map((label) => label.trim())
      .filter(Boolean);
    const groupLabel = ancestors[0] || '其他菜单';
    if (!groups.has(groupLabel)) {
      groups.set(groupLabel, {
        key: `registered-menu:${groupLabel}`,
        type: 'registered-menu-group',
        label: groupLabel,
        children: [],
      });
    }
    groups.get(groupLabel).children.push({
      key: `registered-menu-item:${definition.code}`,
      type: 'registered-menu-item',
      code: definition.code,
      label: definition.name,
      path: definition.metadata?.path || '',
      parent: definition.metadata?.parent || '',
      module: definition.module || permissionModuleFromCode(definition.code),
      action_codes: [...new Set(definition.metadata?.action_codes || [])],
    });
  }
  return [...groups.values()];
}

/** Return registered menu definitions absent from the API permission catalog. */
export function detectMenuRegistryDrift({ menuItems = defaultMenuItems, permissions = [] } = {}) {
  const available = new Set((permissions || []).map((item) => item?.code).filter(Boolean));
  return buildMenuPermissionRegistry(menuItems || [])
    .filter((item) => !available.has(item.code))
    .map((item) => ({ code: item.code, name: item.name, path: item.metadata?.path }));
}
