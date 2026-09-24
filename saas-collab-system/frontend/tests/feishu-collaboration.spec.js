import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { canAccessPath, filterMenuItems } from '../src/router/menu';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('飞书协同工作台', () => {
  it('位于 API数据接入下并受集成查看权限保护', () => {
    const viewer = { user_type: 'internal', permissions: ['feishu.view'] };
    const menu = filterMenuItems(viewer);
    const integrations = menu.find((item) => item.label === 'API数据接入');
    expect(integrations.children.some((item) => item.path === '/integrations/feishu' && item.label === '飞书协同')).toBe(true);
    expect(canAccessPath(viewer, '/integrations/feishu')).toBe(true);
    expect(canAccessPath({ user_type: 'internal', permissions: [] }, '/integrations/feishu')).toBe(false);
    expect(canAccessPath({ user_type: 'internal', permissions: ['integrations.view'] }, '/integrations/feishu')).toBe(false);
  });

  it('注册单一路由并提供六个页签', () => {
    const router = read('src/router/index.js');
    const page = read('src/views/integrations/FeishuCollaboration.vue');
    expect(router).toContain("path: 'integrations/feishu'");
    for (const label of ['应用连接', '身份映射', '消息与预警', '报表推送', '审批映射', '运行与事件']) expect(page).toContain(label);
    expect(page).toContain('empty-text');
    expect(page).toContain('v-if="error"');
    for (const permission of ['feishu.connection.manage', 'feishu.identity.manage', 'feishu.notification.manage', 'feishu.report.manage', 'feishu.approval.manage']) expect(page).toContain(permission);
    expect(page).toContain("payload = { name: editor.name, code: stableCode(), enabled: editor.enabled !== false, config }");
  });

  it('客户端使用正式飞书集成端点且不回显密钥', () => {
    const api = read('src/api/feishu.js');
    expect(api).toContain("const base = '/api/internal/integrations/feishu'");
    for (const resource of ['connection', 'identities', 'notifications', 'reports', 'approvals', 'operations']) expect(api).toContain(resource);
    expect(api).toContain('app_secret: undefined');
  });

  it('身份映射展示系统用户并要求人工查询、选择和确认飞书候选', () => {
    const page = read('src/views/integrations/FeishuCollaboration.vue');
    const api = read('src/api/feishu.js');
    for (const field of ['full_name', 'username', 'department', 'open_id']) expect(page).toContain(field);
    expect(page).toContain('查询飞书用户');
    expect(page).toContain('选择飞书用户');
    expect(page).toContain('不会仅凭姓名自动绑定');
    expect(page).toContain('@click="confirmIdentityBinding"');
    expect(api).toContain('fetchFeishuIdentityCandidates');
    expect(api).toContain('identities/system-users/${systemUserId}/candidates/');
    expect(api).toContain('bindFeishuIdentity');
    expect(api).toContain('identities/system-users/${systemUserId}/binding/');
  });
});
