import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '..');

describe('integration sync job workspace', () => {
  it('keeps the original detail dimensions, action menu and policy editor', () => {
    const page = fs.readFileSync(path.join(root, 'src/views/integrations/IntegrationWorkspace.vue'), 'utf8');

    expect(page).toContain('jobDetailItems');
    expect(page).toContain("label: '查询范围'");
    expect(page).toContain("label: '单次安全上限'");
    expect(page).toContain("label: '同步检查点'");
    expect(page).toContain("label: '数据写入表'");
    expect(page).toContain('viewJobRuns(activeJob)');
    expect(page).toContain('viewJobBusiness(activeJob)');
    expect(page).toContain('查看任务详情');
    expect(page).toContain('复制配置新建');
    expect(page).toContain('调度与运行');
    expect(page).toContain('要同步哪些数据');
    expect(page).toContain('高级设置（一般无需修改）');
    expect(page).toContain('jobForm.query_page_size');
    expect(page).toContain('jobForm.query_statuses');
    expect(page).toContain("if (command === 'clone')");
    expect(page).toContain('aria-label="同步异常快捷入口"');
    expect(page).toContain('toggleSchedulerHistory');
    expect(page).toContain("path: '/integrations/sync-runs', query: { status: 'failed' }");
    expect(page).toContain('to="/integrations/sync-jobs"');
    expect(page).toContain('to="/alerts/business"');
    expect(page).toContain('scheduler_history');
    expect(page).toContain('hydrateRouteFilters');
    expect(page).toContain('runDetailItems');
    expect(page).toContain("label: '外部平台调用'");
    expect(page).toContain("label: 'Token 刷新/替换'");
    expect(page).toContain("label: '原始响应归档'");
    expect(page).toContain("label: '数据结果'");
    expect(page).toContain('runStages');
    expect(page).toContain('aria-label="同步执行阶段"');
    expect(page).toContain('展示脱敏后的调用、处理和写入结果');
    expect(page).toContain("path: '/integrations/sync-jobs', query: { subject: row.subject_name || '' }");
  });
});
