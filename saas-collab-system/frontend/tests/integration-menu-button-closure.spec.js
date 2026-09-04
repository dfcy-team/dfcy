import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const read = (relativePath) => fs.readFileSync(path.resolve(process.cwd(), relativePath), 'utf8');

describe('API 数据接入菜单与按钮闭环', () => {
  it('挂载接入配置和同步运行完整工作台并保留详情路由', () => {
    const router = read('src/router/index.js');

    expect(router).toContain("const IntegrationWorkspace = () => import('../views/integrations/IntegrationWorkspace.vue');");
    expect(router).toContain("{ path: 'integrations/configs', component: IntegrationWorkspace, props: { mode: 'configs' } }");
    expect(router).toContain("{ path: 'integrations/configs/:id', component: IntegrationConfigDetail }");
    expect(router).toContain("{ path: 'integrations/sync-runs', component: IntegrationWorkspace, props: { mode: 'sync-runs', runPermission: 'integrations.run_live_readonly', mockRunPermission: 'integrations.run' } }");
    expect(router).toContain("{ path: 'integrations/sync-runs/:id', component: SyncRunDetail }");
  });

  it('同步任务按钮使用准确中文名称且不向操作员暴露内部 action', () => {
    const page = read('src/views/integrations/SyncJobList.vue');

    expect(page).toContain('>运行模拟任务</el-button>');
    expect(page).toContain('>停用任务</el-button>');
    expect(page).toContain('>指派负责人</el-button>');
    expect(page).toContain('>保存备注</el-button>');
    expect(page).toContain('>解决事件</el-button>');
    expect(page).toContain('>受控重试预览</el-button>');
    expect(page).toContain('运行模拟任务仅写入 Mock 运行记录，停用任务仅停用内部任务');
    expect(page).toContain("action.label === 'disable' ? '停用任务' : '运行模拟任务'");
    expect(page).not.toContain('>run-mock</el-button>');
    expect(page).not.toContain('>disable</el-button>');
    expect(page).not.toContain('run-mock 仅写入');
    expect(page).not.toContain('disable 仅停用');
  });

  it('店铺档案 API 接入和全局确认框使用一致的中文操作名称', () => {
    const app = read('src/App.vue');
    const apiAccessDialog = read('src/components/SubjectApiAccessDialog.vue');

    expect(app).toContain('<el-config-provider :locale="zhCn">');
    expect(app).toContain("import zhCn from 'element-plus/es/locale/lang/zh-cn';");
    expect(apiAccessDialog).toContain('>刷新令牌</el-button>');
    expect(apiAccessDialog).toContain('>撤销授权</el-button>');
    expect(apiAccessDialog).toContain('>平台只读检查</el-button>');
    expect(apiAccessDialog).not.toContain('>刷新授权</el-button>');
  });
});
