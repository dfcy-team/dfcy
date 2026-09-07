import { menuItems as defaultMenuItems } from '../router/menu';
import { adminModuleLabel } from './adminDisplayLabels';

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
