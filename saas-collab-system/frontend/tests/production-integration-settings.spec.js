import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  mockProductionIntegrationSettings,
  mockCreateProductionIntegrationSettingsVersion,
  mockApproveProductionIntegrationSettingsVersion,
  mockRollbackProductionIntegrationSettingsVersion
} from '../src/mock/productionSettings';

const read = (file) => readFileSync(resolve(process.cwd(), file), 'utf8');
const page = read('src/views/settings/ProductionIntegrationSettings.vue');
const api = read('src/api/integrations.js');
const router = read('src/router/index.js');
const menu = read('src/router/menu.js');
const readiness = read('src/views/settings/PlatformIntegrationReadiness.vue');
const workspace = read('src/views/integrations/IntegrationWorkspace.vue');

describe('系统管理员生产环境 API 配置闭环', () => {
  it('registers a system-admin-only menu and route', () => {
    expect(menu).toContain("path: '/integrations/production-settings', label: '生产环境配置', permissions: ['config.system.manage'], allPermissions: ['config.view']");
    expect(menu).toContain("{ path: '/integrations/production-settings', permissions: ['config.system.manage'], allPermissions: ['config.view'], userTypes: ['internal'] }");
    expect(router).toContain("const ProductionIntegrationSettings = () => import('../views/settings/ProductionIntegrationSettings.vue');");
    expect(router).toContain("{ path: 'integrations/production-settings', component: ProductionIntegrationSettings }");
  });

  it('covers every non-secret production setting and uses all required permissions', () => {
    for (const field of [
      'network.mode', 'security_approved', 'readonly_sync_enabled', 'allowed_hosts', 'oauth_redirect_allowlist',
      'connection', 'max_retries', 'backoff_base_seconds', 'connect_timeout_seconds', 'read_timeout_seconds',
      'max_retry_wait_seconds', 'max_total_wait_seconds',
      'custody.backend', 'service_url', 'service_host', 'auth_file_path', 'ca_file_path', 'token_available',
      'contract_approved', 'app_id', 'service_id', 'redirect_uri', 'auth_url', 'api_host', 'token_path',
      'refresh_path', 'revoke_path', 'shop_path', 'authorized_shops_path', 'metadata_path', 'order_list_path',
      'order_detail_path', 'return_list_path', 'return_detail_path', 'market', 'region', 'auth_urls', 'api_hosts',
      'listing_write', 'emergency_stop', 'require_batch_approval', 'allowed_platforms', 'allowed_actions', 'allowed_store_ids', 'max_batch_size'
    ]) expect(page).toContain(field);
    expect(page).toContain("systemActionAccess('config.manage')");
    expect(page).toContain("systemActionAccess('config.approve')");
    expect(page).toContain("systemActionAccess('config.rollback')");
    expect(page).toContain("systemActionAccess('config.view')");
    expect(page).toContain("'config.system.manage'");
    expect(page).not.toMatch(/v-model="[^"]*(?:token|secret|password|cookie|session)/i);
    expect(page).toContain('isDangerousChange');
    expect(page).toContain('全球刊登生产写入策略');
    expect(page).toContain('API 同步写入关闭');
    expect(page).toContain('配置通过只代表允许进入内部生产队列');
    expect(page).toContain('parseStoreIdInput');
    expect(page).toContain('Number.isSafeInteger');
    expect(page).toContain('require_batch_approval: true');
    expect(page).toContain('ElMessageBox.confirm');
    expect(page).toContain('isOwnVersion');
    expect(page).toContain('创建人不能审批自己的版本');
    expect(page).toContain('useRoute');
    expect(page).toContain("mode: ''");
    expect(page).not.toContain("!payload.value.network.mode");
    expect(page).toContain('const payload = { value: buildPayload()');
  });

  it('uses the agreed production-settings endpoints and redacted mock metadata', () => {
    expect(api).toContain("/api/internal/integrations/production-settings/");
    expect(api).toContain("/api/internal/integrations/production-settings/versions/");
    expect(api).toContain("/versions/${id}/approve/");
    expect(api).toContain("/versions/${id}/rollback/");
    expect(api).toContain('data: payload');
    const response = mockProductionIntegrationSettings();
    expect(response.success).toBe(true);
    expect(response.data.effective_config).toMatchObject({
      network: expect.objectContaining({ mode: '', allowed_hosts: expect.any(Array) }),
      connection: expect.objectContaining({ max_retries: expect.any(Number), max_total_wait_seconds: expect.any(Number) }),
      custody: expect.objectContaining({ backend: 'refuse' }),
      listing_write: expect.objectContaining({ mode: 'disabled', emergency_stop: true, require_batch_approval: true, allowed_store_ids: expect.any(Array), max_batch_size: 20 }),
      platforms: expect.objectContaining({ lazada: expect.any(Object), shopee: expect.any(Object), tiktok: expect.any(Object) })
    });
    expect(response.data.masked_status.custody.token_available).toBe(false);
    expect(response.data.config.platforms.lazada).toHaveProperty('auth_url');
    expect(response.data.config.platforms.shopee).toHaveProperty('order_detail_path');
    expect(response.data.config.platforms.tiktok).toHaveProperty('authorized_shops_path');
    expect(JSON.stringify(response)).not.toMatch(/"(?:access_token|refresh_token|client_secret|app_secret|partner_key|token_id|cookie|session)"\s*:/i);
  });

  it('supports create, approve and rollback interactions in mock mode', () => {
    const created = mockCreateProductionIntegrationSettingsVersion({
      value: { network: { mode: '' }, connection: { max_retries: 2 }, custody: { backend: 'refuse' }, platforms: {} },
      reason: '测试配置版本'
    });
    expect(created.success).toBe(true);
    const versionId = created.data.id;
    expect(mockApproveProductionIntegrationSettingsVersion(versionId).success).toBe(true);
    const current = mockProductionIntegrationSettings();
    const currentId = current.data.current_version.id;
    expect(mockRollbackProductionIntegrationSettingsVersion(currentId).success).toBe(true);
  });

  it('maps readiness blockers to permission-aware actions and supports workspace deep links', () => {
    expect(readiness).toContain('BLOCKER_ACTIONS');
    for (const code of ['platform_network_mode_disabled', 'credential_custody_not_approved', 'outbound_host_allowlist_missing', 'credential_not_configured', 'callback_missing', 'readonly_not_approved']) {
      expect(readiness).toContain(code);
    }
    expect(readiness).toContain('openBlockerAction');
    expect(readiness).toContain("/integrations/production-settings");
    expect(workspace).toContain('handleDeepLink');
    expect(workspace).toContain("['create', 'credentials', 'verify', 'readonly']");
    expect(workspace).toContain('config_id');
    expect(workspace).toContain('openCredential(row)');
    expect(workspace).toContain('await checkReadonly(row)');
  });
});
