import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');

describe('治理与试点收敛工作台', () => {
  it('exposes exactly four internal menu entries in the prescribed order', async () => {
    const { menuItems } = await import('../src/router/menu');
    const item = menuItems.find((entry) => entry.label === '治理与试点');
    expect(item).toBeTruthy();
    expect(item.internal).toBe(true);
    expect(item.children).toHaveLength(4);
    expect(item.children.map(({ label, path }) => ({ label, path }))).toEqual([
      { label: '治理中心', path: '/governance' },
      { label: '验证中心', path: '/pilot/validation' },
      { label: '发布中心', path: '/pilot/releases' },
      { label: '运维控制台', path: '/pilot/control-room' }
    ]);
    for (const child of item.children) expect(child.permissions.length).toBeGreaterThan(0);
  });

  it('keeps old detail paths in the route contract while removing them from the menu', () => {
    const menu = read('src/router/menu.js');
    const router = read('src/router/index.js');
    expect(menu).toContain("path: '/governance'");
    expect(menu).not.toContain("label: 'API 合同'");
    expect(menu).not.toContain("label: '助手治理'");
    expect(menu).not.toContain("label: '专项安全评审'");
    expect(router).toContain("path: 'governance/api-contracts'");
    expect(router).toContain("path: 'governance/assistants/:id'");
    expect(router).toContain("path: 'pilot/security-reviews/:id'");
  });

  it('registers the two aggregate routes with internal OR capabilities', () => {
    const menu = read('src/router/menu.js');
    expect(menu).toMatch(/path: '\/governance', permissions: \['governance\.api\.view', 'governance\.assistants\.view'\], userTypes: \['internal'\]/);
    expect(menu).toMatch(/path: '\/pilot\/validation', permissions: \['pilot\.security_review\.view', 'pilot\.verification\.view', 'pilot\.performance\.view'\], userTypes: \['internal'\]/);
    expect(menu).toMatch(/path: '\/pilot\/control-room', permissions: \['pilot\.control\.view', 'pilot\.topology\.view', 'pilot\.capacity\.view'\], userTypes: \['internal'\]/);
    expect(read('src/router/index.js')).toContain("const GovernanceCenter = () => import('../views/governance/GovernanceCenter.vue');");
    expect(read('src/router/index.js')).toContain("const ValidationCenter = () => import('../views/pilot/ValidationCenter.vue');");
    expect(read('src/router/index.js')).toContain("route.query.mode === 'recovery'");
  });

  it('provides the six-step journey and fail-closed real-data center entries', () => {
    const journey = read('src/components/GovernancePilotJourney.vue');
    const governance = read('src/views/governance/GovernanceCenter.vue');
    const validation = read('src/views/pilot/ValidationCenter.vue');
    for (const label of ['登记', '验证', '准入', '部署', '观察', '恢复/回滚']) expect(journey).toContain(label);
    expect(journey).toContain('受控试点');
    expect(journey).toContain('aria-disabled="true"');
    expect(governance).toContain('fetchApiContracts');
    expect(governance).toContain('fetchAssistants');
    expect(governance).toContain('fixed-demo/mock');
    expect(governance).toContain('state.value = \'error\'');
    expect(validation).toContain('fetchP8Resources');
    expect(validation).toContain('性能作业会产生真实负载');
    expect(validation).toContain('state.value = \'error\'');
  });

  it('keeps deploy, recovery and rollback inside selected detail context with confirmation', () => {
    const workflow = read('src/views/pilot/PilotWorkflow.vue');
    const controlRoom = read('src/views/pilot/ControlRoom.vue');
    expect(workflow).toContain('详情内生产操作');
    expect(workflow).toContain('ElMessageBox.confirm');
    expect(workflow).toContain("'pilot.release.execute'");
    expect(workflow).toContain("'pilot.recovery.execute'");
    expect(workflow).toContain("'pilot.release.rollback.execute'");
    const table = workflow.slice(workflow.indexOf('<el-table'), workflow.indexOf('<el-drawer'));
    expect(table).not.toContain('confirmExecution(row)');
    expect(table).not.toContain('confirmRollback(row)');
    expect(controlRoom).toContain('GovernancePilotJourney');
    expect(controlRoom).toContain('fetchExecutions({ page: 1, page_size: 100 })');
    expect(controlRoom).toContain('const canOpenControlRoom = computed');
    expect(controlRoom).toContain("auth.hasPermission('pilot.topology.view')");
    expect(controlRoom).toContain("auth.hasPermission('pilot.capacity.view')");
    expect(controlRoom).toContain('if (!canViewControlRoom.value)');
    expect(controlRoom).toContain('if (!canOpenControlRoom.value)');
    expect(controlRoom).toContain('capability.value = \'disabled\'');
    expect(workflow).toContain("switchMode('recovery')");
  });

  it('maps a release work order from selected or real list data without invented values', () => {
    const workflow = read('src/views/pilot/PilotWorkflow.vue');
    expect(workflow).toContain('统一发布工单');
    for (const field of ['commit_sha', 'environment_id', 'created_by_id', 'approved_by_id', 'approval_status', 'evidence_refs', 'scheduled_at', 'execution_id']) {
      expect(workflow).toContain(field);
    }
    expect(workflow).toContain('Array.isArray(value) && value.length === 0');
    expect(workflow).toContain("value === undefined || value === null || value === ''");
    expect(workflow).toContain("return '—'");
  });
});
