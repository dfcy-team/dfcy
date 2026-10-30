import { isApiAccessAdmin } from '../utils/apiAccessAdmin.js';
import { canAccessPath, filterMenuItems, filterSidebarMenuItems, flattenMenuItems, findRouteCapability } from './menu';

export const integrationGroups = [
  { label: '授权接入', paths: ['/integrations/authorization-center'] },
  { label: '绑定与映射', paths: ['/integrations/store-mappings', '/integrations/product-mappings'] },
  { label: '同步管理', paths: ['/integrations/sync-jobs', '/integrations/sync-runs', '/integrations/incidents', '/sales-management/data-quality'] },
  { label: '飞书协同', paths: ['/integrations/feishu'] },
  { label: '内部系统接口', paths: ['/integrations/ai-open-api'] },
  { label: '接入设置', paths: ['/integrations/readiness', '/integrations/capabilities', '/integrations/audit', '/integrations/platform-drill', '/integrations/configs'] }
];

// Presentation only: the canonical menu registry and route guards stay authoritative.
// Never use a group permission as a substitute for a child's existing contract.
export function buildIntegrationSidebar(user) {
  const sidebar = filterSidebarMenuItems(user).filter(item => item.label !== 'API数据接入' || isApiAccessAdmin(user));
  const centerPath = '/integrations/authorization-center';
  if (canAccessPath(user, centerPath) && !sidebar.some(item => item.label === 'API数据接入')) {
    sidebar.push({ label: 'API数据接入', children: [] });
  }
  const authorized = new Map(flattenMenuItems(filterMenuItems(user)).map(item => [item.path, item]));
  if (canAccessPath(user, centerPath)) authorized.set(centerPath, { ...findRouteCapability(centerPath), path: centerPath, label: '店铺与仓库授权' });
  for (const [path, label] of [['/integrations/store-mappings', '店铺绑定'], ['/integrations/product-mappings', 'SKU映射']]) {
    if (canAccessPath(user, path)) authorized.set(path, { ...findRouteCapability(path), path, label });
  }
  return sidebar.map(item => {
    if (item.label !== 'API数据接入') return item;
    const own = new Map(item.children.map(child => [child.path, child]));
    const groups = integrationGroups.map(group => ({
      label: group.label,
      children: group.paths.flatMap(path => {
        const leaf = own.get(path) || authorized.get(path);
        return leaf && canAccessPath(user, path) ? [{ ...leaf, navigationIndex: `api-access:${path}` }] : [];
      })
    }));
    // Future registered pages must remain reachable even before a grouping is added.
    const known = new Set(integrationGroups.flatMap(group => group.paths));
    groups[5].children.push(...item.children.filter(child => !known.has(child.path)));
    return { ...item, children: groups.filter(group => group.children.length) };
  });
}
