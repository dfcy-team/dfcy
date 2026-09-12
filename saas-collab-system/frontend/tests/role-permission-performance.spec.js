import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('角色权限页首屏加载性能契约', () => {
  it('角色列表请求不依赖权限目录和权限包请求完成', () => {
    const page = read('src/views/system/RolePermissionMatrix.vue');
    expect(page).toContain('void loadPermissionCatalog(tenantParams);');
    expect(page).toContain('const roleResponse = await fetchRoles(');
    expect(page).not.toContain('const [roleResponse, permissionResult, packageResponse] = await Promise.all');
    expect(page).toContain('if (!roleResponse.success)');
    expect(page).toContain('async function openRole(role)');
    expect(page).toContain('const catalog = await loadPermissionCatalog(targetTenantId.value ? { tenant_id: targetTenantId.value } : {});');
    expect(page).toContain('if (!catalog.directoryResult?.response?.success || !catalog.packageResponse?.success)');
  });

  it('权限目录在组件生命周期内复用同一个请求，并使用后端允许的 500 条单页', () => {
    const page = read('src/views/system/RolePermissionMatrix.vue');
    const api = read('src/api/systemAdmin.js');
    expect(page).toContain('const permissionDirectoryCache = createSuccessfulAsyncCache(');
    expect(page).toContain('const permissionPackageCache = createSuccessfulAsyncCache(');
    expect(page).toContain("result = await permissionDirectoryCache.get('global');");
    expect(page).toContain('return permissionPackageCache.get(key, tenantParams);');
    expect(api).toContain('response = await loader({ page, page_size: 500 });');
  });

  it('权限目录失败不会覆盖已加载的角色列表状态', () => {
    const page = read('src/views/system/RolePermissionMatrix.vue');
    const roleSuccessBlock = page.slice(page.indexOf('const roleResponse = await fetchRoles('), page.indexOf('async function loadPermissionDirectory()'));
    expect(roleSuccessBlock).not.toContain('permissionResponse.success');
    expect(roleSuccessBlock).not.toContain('packageResponse.success');
    expect(page).toContain('if (directoryResult?.response?.success && packageResponse?.success)');
    expect(page).toContain("permissionCatalogError.value = '';");
    expect(page).toContain('v-if="permissionCatalogError"');
  });

  it('快速切换租户时只允许最新角色请求回写', () => {
    const page = read('src/views/system/RolePermissionMatrix.vue');
    expect(page).toContain('const roleLoads = createRequestSequence();');
    expect(page).toContain('const loadToken = roleLoads.begin();');
    expect(page).toContain('if (!loadToken.isCurrent()) return;');
  });
});
