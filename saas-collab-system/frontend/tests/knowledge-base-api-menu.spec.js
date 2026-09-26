import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { canAccessPath, menuItems, routeCapabilities } from '../src/router/menu';

const read = (relativePath) => fs.readFileSync(path.resolve(process.cwd(), relativePath), 'utf8');

describe('内部系统数据接口菜单', () => {
  it('在 API 数据接入下只增加一个受保护入口', () => {
    const apiMenu = menuItems.find((item) => item.label === 'API数据接入');
    const items = apiMenu.children.filter((item) => item.path === '/integrations/ai-open-api');

    expect(items).toHaveLength(1);
    expect(items[0]).toEqual({
      path: '/integrations/ai-open-api',
      label: '内部系统数据接口',
      permissions: ['config.system.manage'],
      allPermissions: ['config.view']
    });
    expect(routeCapabilities.find((item) => item.path === '/integrations/ai-open-api')).toEqual({
      path: '/integrations/ai-open-api',
      permissions: ['config.system.manage'],
      allPermissions: ['config.view'],
      menuPermissions: ['menu.config.integrations_ai_open_api.view'],
      userTypes: ['internal']
    });
  });

  it('只允许具有两项配置权限的内部用户访问', () => {
    const manager = { user_type: 'internal', permissions: ['config.system.manage', 'config.view'] };
    expect(canAccessPath(manager, '/integrations/ai-open-api')).toBe(true);
    expect(canAccessPath({ ...manager, permissions: ['config.system.manage'] }, '/integrations/ai-open-api')).toBe(false);
    expect(canAccessPath({ ...manager, user_type: 'supplier' }, '/integrations/ai-open-api')).toBe(false);
  });

  it('挂载页面并明确禁止知识库回写', () => {
    const router = read('src/router/index.js');
    const page = read('src/views/integrations/AIExternalApiSettings.vue');

    expect(router).toContain("const AIExternalApiSettings = () => import('../views/integrations/AIExternalApiSettings.vue');");
    expect(router).toContain("{ path: 'integrations/ai-open-api', component: AIExternalApiSettings }");
    expect(page).toContain('强制只读');
    expect(page).toContain("const safeMethods = ['GET', 'HEAD', 'OPTIONS'];");
    expect(page).toContain("const blockedMethods = ['POST', 'PUT', 'PATCH', 'DELETE'];");
    expect(page).toContain('不接收调用方回写');
    expect(page).toContain('调用方始终不能回写业务数据');
    expect(page).toContain('只有标记“已接入”的数据块可实际读取');
    expect(page).toContain('实时可用性未核实，不能宣称已开放');
  });
});
