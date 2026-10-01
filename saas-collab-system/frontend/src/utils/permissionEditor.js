import { moduleCodeForPath } from '../router/menu';
import { adminModuleLabel } from './adminDisplayLabels';

const stem = code => String(code).split('.').slice(0, -1).join('.');
export function permissionAssignmentAvailability(permissions, menuTree, statuses = {}) {
  const pages = menuTree.flatMap(group => group.children);
  const disabled = page => statuses[moduleCodeForPath(page.path)] === 'disabled';
  const unavailable = new Set(pages.filter(disabled).map(page => page.code));
  for (const permission of permissions) {
    if ((permission.permission_type || 'action') !== 'action') continue;
    const matches = pages.filter(page => page.action_codes.some(code => stem(code) === stem(permission.code)));
    // Shared and unregistered operations keep their independent grant boundary.
    const exclusive=({development:'product_development',rpa:'rpa',supply:'supply_chain',purchasing:'supply_chain',listings:'global_listing'})[permission.module];
    if ((matches.length && matches.every(disabled)) || (!matches.length && exclusive && statuses[exclusive] === 'disabled')) unavailable.add(permission.code);
  }
  return unavailable;
}

export function buildEditorPermissionGroups({ permissions, menuTree, moduleTree = [], type, unavailable = new Set() }) {
  const catalog = permissions.filter(permission => (permission.permission_type || 'action') === type && !unavailable.has(permission.code));
  const claimed = new Set();
  const groups = menuTree.map(group => ({...group, children: group.children.filter(page=>!unavailable.has(page.code)).map(page => {
    const items = catalog.filter(permission => !claimed.has(permission.code) && (type === 'menu' ? page.code === permission.code : type === 'action' && page.action_codes.some(code => stem(code) === stem(permission.code))));
    items.forEach(permission => claimed.add(permission.code));
    return {...page, permissions: items};
  }).filter(page => page.permissions.length)}));
  for (const permission of catalog) {
    if (claimed.has(permission.code)) continue;
    const module=permission.module || permission.code.split('.')[0];
    const preferred=moduleTree.find(group=>group.children.some(child=>child.module===module));
    const label=preferred?.label || adminModuleLabel(module);
    let group=groups.find(group=>group.label===label);
    if (!group) {group={key:`editor-module:${module}`,label,children:[]};groups.push(group);}
    let page=group.children.find(page=>page.key===`editor-extra:${module}`);
    if (!page) {page={key:`editor-extra:${module}`,label:`${adminModuleLabel(module)}其他操作`,path:'',module,permissions:[]};group.children.push(page);}
    page.permissions.push(permission);
  }
  return groups.filter(group=>group.children.length);
}

export function permissionChanges(previous = [], next = []) {
  const before=new Set(previous),after=new Set(next);
  return {added:[...after].filter(code=>!before.has(code)).length,removed:[...before].filter(code=>!after.has(code)).length};
}
