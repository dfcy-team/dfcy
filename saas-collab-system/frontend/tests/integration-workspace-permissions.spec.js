import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const workspace = readFileSync(resolve(process.cwd(), 'src/views/integrations/IntegrationWorkspace.vue'), 'utf8');

describe('IntegrationWorkspace production action permissions', () => {
  it('uses the fine-grained config permissions for every configuration action', () => {
    expect(workspace).toContain("permission: 'integrations.config.create'");
    expect(workspace).toContain("permission: 'integrations.credential.rotate'");
    expect(workspace).toContain("permission: 'integrations.config.verify'");
    expect(workspace).toContain("permission: 'integrations.run_live_readonly'");
    expect(workspace).toContain("permission: 'integrations.config.disable'");

    for (const action of ['configCreateAccess', 'credentialRotateAccess', 'configVerifyAccess', 'configReadonlyAccess', 'configDisableAccess']) {
      expect(workspace).toContain(`getActionAccess(auth, { permission:`);
      expect(workspace).toContain(`${action}.allowed`);
    }
    for (const buttonLabel of ['新建接入配置', '维护凭据', '检查凭据', '本地一致性检查', '平台只读检查', '禁用', '删除']) {
      expect(workspace).toContain(buttonLabel);
    }
    expect(workspace).toContain(':title="configCreateAccess.allowed ?');
    expect(workspace).toContain(':title="credentialRotateAccess.allowed ?');
    expect(workspace).toContain(':title="configVerifyAccess.allowed ?');
    expect(workspace).toContain(':title="configReadonlyAccess.allowed ?');
    expect(workspace).toContain(':title="configDisableAccess.allowed ?');
  });

  it('guards config methods and prevents duplicate high-risk submissions', () => {
    for (const method of ['openCreateConfig', 'prepareConfig', 'openCredential', 'saveCredential', 'verify', 'checkConsistency', 'checkReadonly', 'disableConfig', 'deleteConfig']) {
      const start = workspace.indexOf(`function ${method}`) >= 0
        ? workspace.indexOf(`function ${method}`)
        : workspace.indexOf(`async function ${method}`);
      expect(start, `${method} should exist`).toBeGreaterThan(-1);
      const end = workspace.indexOf('\n}', start) + 2;
      const body = workspace.slice(start, end > 1 ? end : start + 900);
      expect(body).toContain('actionDenied(');
    }
    expect(workspace).toContain(':loading="operating" :disabled="!configCreateAccess.allowed || operating"');
    expect(workspace).toContain(':loading="operating" :disabled="!credentialRotateAccess.allowed || operating"');
    expect(workspace).toContain("'确认加密保存凭据'");
    expect(workspace).toContain('页面不会回显或再次展示密钥原文');
    expect(workspace).toContain('secretCredentialFields.forEach');
    expect(workspace).toContain("configActionLoading.value = configActionKey('verify', row)");
    expect(workspace).toContain("configActionLoading.value = configActionKey('consistency', row)");
    expect(workspace).toContain("configActionLoading.value = configActionKey('readonly', row)");
    expect(workspace).toContain('if (actionDenied(configReadonlyAccess.value) || configActionBusy(row)) return;');
    expect(workspace).toContain("configActionLoading.value = configActionKey('disable', row)");
    expect(workspace).toContain("configActionLoading.value = configActionKey('delete', row)");
    expect(workspace).toContain("configActionBusy(row)");
  });

  it('limits sync-run retry to the mock permission and keeps production readonly reruns in the task flow', () => {
    expect(workspace).toContain("const mockRunAccess = computed(() => getActionAccess(auth, { permission: props.mockRunPermission }));");
    expect(workspace).toContain(':disabled="!mockRunAccess.allowed || retryLoadingId === row.id || retryLimitReached(row)"');
    expect(workspace).toContain('if (actionDenied(mockRunAccess.value) || retryLoadingId.value === row?.id || retryLimitReached(row)) return;');
    expect(workspace).toContain("row?.execution_mode !== 'simulation'");
    expect(workspace).toContain('生产只读运行请返回任务确认重跑');
    expect(workspace).toContain('retryLoadingId.value = row.id');
    expect(workspace).toContain('retryLoadingId.value = null');
  });

  it('requires integrations.manage for sync-job mutations while retaining read-only menu entries', () => {
    expect(workspace).toContain("permission: 'integrations.manage'");
    expect(workspace).toContain(':disabled="!integrationManageAccess.allowed"');
    expect(workspace).toContain("['edit', 'clone', 'toggle', 'delete'].includes(command)");
    expect(workspace).toContain('actionDenied(integrationManageAccess.value)');
    expect(workspace).toContain('if (actionDenied(integrationManageAccess.value) || operating.value) return;');
    expect(workspace).toContain('async function saveJob()');
    expect(workspace).toContain('async function batchToggle(enabled)');
    expect(workspace).toContain('async function batchRunMock()');
  });
});
