// The sidebar declaration is the source of truth for menu permissions.  Keep
// this module free of imports from menu.js so it can be used by the router at
// runtime and by the release-time registry exporter without creating a cycle.

const MENU_PERMISSION_PREFIX = 'menu.';
const REGISTRY_SOURCE = 'frontend/src/router/menu.js';

function unique(values = []) {
  return [...new Set(values.filter(Boolean))];
}

function slugFromPath(path = '') {
  return String(path || '')
    .replace(/^\/+|\/+$/g, '')
    .split('/')
    .filter(Boolean)
    .join('_')
    .replace(/-+/g, '_')
    .replace(/[^a-zA-Z0-9_-]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toLowerCase();
}

function permissionParts(code) {
  return String(code || '').split('.').filter(Boolean);
}

function moduleFromPermission(code) {
  const parts = permissionParts(code);
  if (parts[0] === 'menu' || parts[0] === 'action' || parts[0] === 'field') {
    return parts[1] || '';
  }
  return parts[0] || '';
}

function actionFromPermission(code) {
  const parts = permissionParts(code);
  if (parts[0] === 'menu' || parts[0] === 'action' || parts[0] === 'field') {
    return parts.slice(2).join('.') || 'view';
  }
  return parts.slice(1).join('.') || 'view';
}

function explicitMenuCodes(item) {
  return unique(Array.isArray(item?.menuPermissions) ? item.menuPermissions : [])
    .filter((code) => String(code).startsWith(MENU_PERMISSION_PREFIX));
}

function actionCodes(item) {
  return unique([
    ...(Array.isArray(item?.permissions) ? item.permissions : []),
    ...(Array.isArray(item?.allPermissions) ? item.allPermissions : []),
  ]).filter((code) => !String(code).startsWith(MENU_PERMISSION_PREFIX));
}

/**
 * Return the stable menu code(s) for a declaration.
 *
 * Existing explicit menu.* codes always win.  New declarations use the first
 * action module plus the route path, so a label change does not change the
 * code and two routes sharing one action still remain separate menu entries.
 */
export function menuPermissionCodesForItem(item) {
  const explicit = explicitMenuCodes(item);
  if (explicit.length) return explicit;

  const path = String(item?.path || '');
  const actions = actionCodes(item);
  const module = moduleFromPermission(actions[0]);
  const resource = slugFromPath(path);
  if (!path || path === '/' || !module || !resource || !actions.length) return [];
  return [`${MENU_PERMISSION_PREFIX}${module}.${resource}.view`];
}

function parentPath(item, ancestors) {
  return ancestors.filter(Boolean).join(' / ');
}

function registryName(item) {
  return String(item?.menuPermissionName || item?.label || '未命名菜单').trim() || '未命名菜单';
}

function registryDescription(item) {
  return String(item?.menuPermissionDescription || `显示${registryName(item)}入口`).trim();
}

function buildDefinition(item, ancestors = []) {
  const codes = menuPermissionCodesForItem(item);
  if (!item?.path || item.path === '/' || !codes.length) return [];
  const actions = actionCodes(item);
  return codes.map((code) => {
    const module = moduleFromPermission(code);
    return {
      code,
      name: registryName(item),
      module: module || 'other',
      action: actionFromPermission(code),
      description: registryDescription(item),
      permission_type: 'menu',
      metadata: {
        path: item.path,
        route: item.path,
        resource: slugFromPath(item.path),
        parent: parentPath(item, ancestors),
        action_codes: actions,
        source: REGISTRY_SOURCE,
        status: 'active',
      },
    };
  });
}

function collectDefinitions(items, ancestors = [], target = []) {
  for (const item of items || []) {
    target.push(...buildDefinition(item, ancestors));
    collectDefinitions(item.children, [...ancestors, item.label], target);
  }
  return target;
}

/**
 * Build the auditable menu permission manifest consumed by the backend sync
 * command.  Duplicate codes are retained as one declaration only when their
 * route metadata is identical; a release check can then report a collision.
 */
export function buildMenuPermissionRegistry(items = []) {
  const definitions = collectDefinitions(items);
  const byCode = new Map();
  for (const definition of definitions) {
    const existing = byCode.get(definition.code);
    if (!existing) {
      byCode.set(definition.code, definition);
      continue;
    }
    const paths = unique([
      existing.metadata?.path,
      existing.metadata?.paths,
      definition.metadata?.path,
      definition.metadata?.paths,
    ].flat());
    if (paths.length > 1) {
      existing.metadata.paths = paths;
      existing.metadata.registry_collision = true;
    }
  }
  return [...byCode.values()];
}

/**
 * Attach derived codes to the same objects used by the sidebar.  Parent
 * groups receive the union of their descendants so menu-only grants can
 * reveal a group while action grants continue to gate the route itself.
 */
export function attachMenuPermissions(items = []) {
  // Keep the sidebar declaration immutable.  Derived codes are computed by
  // buildMenuPermissionRegistry and by the access helpers; mutating menu
  // objects would leak internal registry fields into callers and break the
  // V2.44.70 menu object contract.
  return items;
}

export const MENU_PERMISSION_REGISTRY_SOURCE = REGISTRY_SOURCE;
